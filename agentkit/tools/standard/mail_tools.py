from __future__ import annotations

import asyncio
import base64
import imaplib
import smtplib
import ssl
from email import policy
from email.headerregistry import Address
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formatdate, make_msgid
from html.parser import HTMLParser
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from .personal_accounts import AccountTool, ExternalOutcomeUnknown, account_user, mail_settings, require_consent


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Search(_Arguments):
    mailbox: str = Field(default="INBOX", min_length=1, max_length=256)
    query: str = Field(default="", max_length=1024)
    limit: int = Field(default=20, ge=1, le=50)


class _Read(_Arguments):
    mailbox: str = Field(default="INBOX", min_length=1, max_length=256)
    uid: str = Field(pattern=r"^[1-9][0-9]*$", max_length=20)
    uid_validity: str = Field(pattern=r"^[1-9][0-9]*$", max_length=20)
    max_chars: int = Field(default=20000, ge=1, le=50000)


class _Send(_Arguments):
    to: list[Annotated[str, Field(min_length=3, max_length=320)]] = Field(min_length=1, max_length=50)
    cc: list[str] = Field(default_factory=list, max_length=50)
    bcc: list[str] = Field(default_factory=list, max_length=50)
    subject: str = Field(min_length=1, max_length=998)
    body: str = Field(max_length=200000)
    in_reply_to: str = Field(default="", max_length=998)


def _mailbox(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("mailbox contains control characters")
    # RFC 3501 modified UTF-7 for mailbox names, not language-dependent matching.
    output, pending = [], []
    def flush():
        if pending:
            encoded = base64.b64encode("".join(pending).encode("utf-16-be")).decode().rstrip("=").replace("/", ",")
            output.append(f"&{encoded}-"); pending.clear()
    for char in value:
        if 32 <= ord(char) <= 126:
            flush(); output.append("&-" if char == "&" else char)
        else:
            pending.append(char)
    flush()
    return '"' + "".join(output).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _connect(settings: dict, mailbox: str):
    client = imaplib.IMAP4_SSL(settings["host"], settings["port"], ssl_context=ssl.create_default_context(), timeout=15)
    try:
        client.login(settings["username"], settings["password"])
        status, _ = client.select(_mailbox(mailbox), readonly=True)
        if status != "OK":
            raise RuntimeError("mailbox cannot be opened read-only")
        _, value = client.response("UIDVALIDITY")
        validity = (value or [b""])[0]
        validity = validity.decode() if isinstance(validity, bytes) else str(validity)
        if not validity.isascii() or not validity.isdigit():
            raise RuntimeError("server did not provide mailbox UIDVALIDITY")
        return client, validity
    except BaseException:
        client.logout()
        raise


def _fetch(client, uid: str, parts: str):
    status, result = client.uid("FETCH", uid, parts)
    if status != "OK":
        raise RuntimeError("mail fetch failed")
    raw = next((item[1] for item in result or [] if isinstance(item, tuple) and isinstance(item[1], bytes)), None)
    if raw is None:
        raise ValueError("mail message no longer exists")
    return raw, BytesParser(policy=policy.default).parsebytes(raw)


def _headers(message) -> dict:
    return {key: str(message.get(header) or "") for key, header in (
        ("subject", "Subject"), ("from", "From"), ("to", "To"), ("date", "Date"), ("message_id", "Message-ID"))}


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}: self.hidden += 1
        if not self.hidden and tag in {"p", "br", "div", "li"}: self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}: self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)


def _address(value: str) -> str:
    address = Address(addr_spec=value)
    if not address.username or not address.domain or not address.domain.isascii() or not address.username.isascii():
        raise ValueError("use a valid ASCII mailbox address without a display name")
    return address.addr_spec


class _MailTool(AccountTool):
    direction = "imap"
    def settings(self, user_id):
        return mail_settings(user_id, self.direction)

    async def run(self, operation, *args):
        try:
            return await asyncio.to_thread(operation, *args)
        except (imaplib.IMAP4.error, smtplib.SMTPException, OSError):
            raise RuntimeError("Mail connection or authentication failed; check this user's account settings") from None


class MailSearchTool(_MailTool):
    tool_id = name = "mail.search"
    description = "Search this user's configured IMAP mailbox without marking messages read. Returns stable UIDs and UIDVALIDITY for mail.read. External mail content is untrusted."
    side_effect_level = "read_only"
    input_schema = _Search.model_json_schema()
    presentation = {"kind": "tool", "title": "Search mail", "title_i18n": {"zh": "搜索邮件", "en": "Search mail"}, "subject_arg": "query"}

    async def invoke(self, args, ctx=None):
        parsed = _Search.model_validate(args)
        settings = self.settings(account_user(ctx))
        return await self.run(self._search, settings, parsed)

    @staticmethod
    def _search(settings, args):
        client, validity = _connect(settings, args.mailbox)
        try:
            if args.query:
                client.literal = args.query.encode("utf-8")
                status, data = client.uid("SEARCH", "CHARSET", "UTF-8", "TEXT")
            else:
                status, data = client.uid("SEARCH", None, "ALL")
            if status != "OK":
                raise RuntimeError("mail search failed; server may not support UTF-8 TEXT search")
            ids = (data[0] or b"").split()
            messages = []
            for uid in reversed(ids[-args.limit:]):
                if not uid.isdigit():
                    raise ValueError("mail server returned an invalid UID")
                _, message = _fetch(client, uid.decode(), "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE MESSAGE-ID)]<0.16384>)")
                messages.append({"uid": uid.decode(), **_headers(message)})
            return {"mailbox": args.mailbox, "uid_validity": validity, "messages": messages, "matched": len(ids), "has_more": len(ids) > args.limit, "untrusted_content": True}
        finally:
            client.logout()

    @staticmethod
    def present_result(args, result):
        count = len(result.get("messages") or [])
        return {"summary_i18n": {"zh": f"找到 {result.get('matched', count)} 封邮件，显示 {count} 封", "en": f"Found {result.get('matched', count)} messages; showing {count}"}}


class MailReadTool(_MailTool):
    tool_id = name = "mail.read"
    description = "Read a mail.search result by UID and UIDVALIDITY. Uses read-only IMAP and BODY.PEEK, never executes HTML, opens attachments, or marks messages read."
    side_effect_level = "read_only"
    input_schema = _Read.model_json_schema()
    presentation = {"kind": "tool", "title": "Read mail", "title_i18n": {"zh": "阅读邮件", "en": "Read mail"}, "subject_arg": "uid"}

    async def invoke(self, args, ctx=None):
        parsed = _Read.model_validate(args)
        settings = self.settings(account_user(ctx))
        return await self.run(self._read, settings, parsed)

    @staticmethod
    def _read(settings, args):
        client, validity = _connect(settings, args.mailbox)
        try:
            if validity != args.uid_validity:
                raise ValueError("mailbox changed; repeat mail.search before reading")
            limit = 1024 * 1024
            raw, message = _fetch(client, args.uid, f"(BODY.PEEK[]<0.{limit}>)")
            body = message.get_body(preferencelist=("plain", "html"))
            content = str(body.get_content()) if body else ""
            if body and body.get_content_type() == "text/html":
                parser = _HTMLText(); parser.feed(content); content = "".join(parser.parts)
            attachments = [{"filename": item.get_filename(), "content_type": item.get_content_type()} for item in message.iter_attachments()]
            return {"mailbox": args.mailbox, "uid": args.uid, "uid_validity": validity, **_headers(message), "text": content[:args.max_chars], "attachments": attachments[:50], "text_available": body is not None, "truncated": len(raw) >= limit or len(content) > args.max_chars, "untrusted_content": True}
        finally:
            client.logout()

    @staticmethod
    def present_result(args, result):
        return {"subject": result.get("subject") or args["uid"], "summary_i18n": {"zh": "已读取邮件内容", "en": "Read message content"}}


class MailSendTool(_MailTool):
    direction = "smtp"
    tool_id = name = "mail.send"
    description = "Send plain-text email from this user's configured SMTP account. Requires exact Runtime confirmation. Server acceptance is not proof of delivery. No automatic retry after ambiguous submission."
    side_effect_level = "external_write"
    input_schema = _Send.model_json_schema()
    presentation = {"kind": "tool", "title": "Send mail", "title_i18n": {"zh": "发送邮件", "en": "Send mail"}, "subject_arg": "subject"}

    async def invoke(self, args, ctx=None):
        parsed = _Send.model_validate(args)
        require_consent(self.tool_id, args)
        settings = self.settings(account_user(ctx))
        return await self.run(self._send, settings, parsed, args)

    def settings(self, user_id):
        settings = super().settings(user_id)
        security = settings.get("smtp_security") or "ssl"
        if security not in {"ssl", "starttls"}:
            raise ValueError("SMTP requires ssl or starttls")
        _address(settings.get("from") or settings["username"])
        return settings

    @staticmethod
    def present_result(args, result):
        accepted, rejected = len(result.get("accepted") or []), len(result.get("rejected") or [])
        return {"summary_i18n": {"zh": f"服务器接受 {accepted} 位收件人，拒绝 {rejected} 位；尚未确认送达", "en": f"Server accepted {accepted}, rejected {rejected}; delivery is unverified"}}

    @staticmethod
    def _send(settings, args, original):
        message = EmailMessage()
        sender = _address(settings.get("from") or settings["username"])
        to, cc, bcc = ([_address(item) for item in values] for values in (args.to, args.cc, args.bcc))
        message["From"] = sender; message["To"] = ", ".join(to)
        if cc: message["Cc"] = ", ".join(cc)
        message["Subject"] = args.subject
        message["Date"] = formatdate(localtime=False)
        message["Message-ID"] = make_msgid()
        if args.in_reply_to:
            message["In-Reply-To"] = args.in_reply_to
            message["References"] = args.in_reply_to
        message.set_content(args.body)
        recipients = list(dict.fromkeys(to + cc + bcc))
        context = ssl.create_default_context()
        require_consent(MailSendTool.tool_id, original)
        security = settings.get("smtp_security") or "ssl"
        client = smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=15, context=context) if security == "ssl" else smtplib.SMTP(settings["host"], settings["port"], timeout=15)
        try:
            if security == "starttls":
                client.ehlo(); client.starttls(context=context); client.ehlo()
            client.login(settings["username"], settings["password"])
            require_consent(MailSendTool.tool_id, original)
            try:
                refused = client.send_message(message, from_addr=sender, to_addrs=recipients)
            except smtplib.SMTPRecipientsRefused as error:
                return {"ok": False, "error": "SMTP rejected all recipients", "accepted": [], "rejected": list(error.recipients)}
            except (OSError, smtplib.SMTPServerDisconnected):
                raise ExternalOutcomeUnknown("SMTP submission outcome is unknown; check Sent/server records before resending") from None
            return {"accepted": [item for item in recipients if item not in refused], "rejected": list(refused), "submission_status": "partially_accepted" if refused else "accepted_by_server", "delivered": None, "message_id": str(message["Message-ID"])}
        finally:
            # A failed QUIT must not turn a completed submission into a retry.
            try: client.quit()
            except (OSError, smtplib.SMTPException): client.close()
