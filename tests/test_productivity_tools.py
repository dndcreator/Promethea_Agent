from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from agentkit.security.approval import approval_scope
from agentkit.security.sandbox import SandboxPolicy
from gateway import user_secrets
from gateway.capability_service import CapabilityService, ToolInvocationContext, ToolPolicyViolationError
from agentkit.tools.standard import calendar_tools, mail_tools
from agentkit.tools.standard.personal_accounts import mail_settings


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(user_secrets, "USER_SECRETS_DIR", tmp_path / "users")
    monkeypatch.setattr(user_secrets, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr("agentkit.security.sandbox._SANDBOX_POLICY", SandboxPolicy())
    user_secrets.update_user_secrets("alice", {
        "MAIL__IMAP_HOST": "imap.example.com", "MAIL__SMTP_HOST": "smtp.example.com",
        "MAIL__USERNAME": "alice@example.com", "MAIL__PASSWORD": "private-app-password",
        "CALENDAR__URL": "https://calendar.example.com/dav/", "CALENDAR__USERNAME": "alice",
        "CALENDAR__PASSWORD": "private-calendar-password",
    })
    return ToolInvocationContext(user_id="alice", session_id="conversation")


def test_account_credentials_do_not_inherit_global_or_cross_user_values(accounts, monkeypatch):
    user_secrets.ENV_FILE.write_text("MAIL__PASSWORD=operator-password\nMAIL__USERNAME=operator@example.com\n")
    monkeypatch.setenv("MAIL__PASSWORD", "process-password")
    user_secrets.ensure_user_secrets("bob")
    bob = user_secrets.resolve_personal_account_settings("bob", "mail")
    assert bob["password"] == "" and bob["username"] == ""
    assert user_secrets.resolve_personal_account_settings("alice", "mail")["password"] == "private-app-password"
    status = str(user_secrets.get_user_secrets_status("alice"))
    assert "private-app-password" not in status and "private-calendar-password" not in status
    assert user_secrets.get_user_secrets_status("alice")["personal_accounts"]["mail"]["imap_configured"] is True


def test_removing_accounts_cannot_clear_other_runtime_secrets(accounts):
    user_secrets.update_user_secrets("alice", {}, remove=["MAIL__PASSWORD"])
    assert mail_tools.MailSearchTool().check_ready("alice")[0] is False
    assert user_secrets.resolve_personal_account_settings("alice", "calendar")["password"] == "private-calendar-password"
    with pytest.raises(ValueError):
        user_secrets.update_user_secrets("alice", {}, remove=["API__API_KEY"])


@pytest.mark.asyncio
async def test_personal_account_secrets_route_preserves_legacy_request_shape(accounts):
    from gateway.http.routes.config import SecretsUpdateRequest, update_config_secrets
    result = await update_config_secrets(SecretsUpdateRequest(values={"MAIL__FROM": "alias@example.com"}), "alice")
    assert result["secrets"]["personal_accounts"]["mail"]["from"] == "alias@example.com"
    result = await update_config_secrets(SecretsUpdateRequest(remove=["MAIL__PASSWORD"]), "alice")
    assert result["secrets"]["personal_accounts"]["mail"]["smtp_configured"] is False


@pytest.mark.asyncio
async def test_registry_readiness_inspection_and_execution_agree(accounts):
    service = CapabilityService()
    service.ensure_discovered_tools()
    for user, expected in (("alice", True), ("bob", False)):
        scope = SimpleNamespace(user_id=user)
        catalog = await service.get_tool_catalog(run_context=scope)
        search = next(row for row in catalog if row["tool_name"] == "mail.search")
        assert search["callable_now"] is expected
        assert search["requires_confirmation"] is False
        assert service.inspect_capabilities(["mail.search"], run_context=scope)["items"][0]["callable_now"] is expected
    assert service.requires_confirmation("mail.send", {}) is True
    assert service.requires_confirmation("calendar.create", {}) is True
    with pytest.raises(ToolPolicyViolationError, match="not configured"):
        await service.call_tool("mail.search", {}, ctx=ToolInvocationContext(user_id="bob"))


def test_account_network_policy_and_tls_fail_closed(accounts):
    user_secrets.update_user_secrets("alice", {"MAIL__IMAP_HOST": "127.0.0.1"})
    with pytest.raises(PermissionError):
        mail_settings("alice", "imap")
    user_secrets.update_user_secrets("alice", {"MAIL__IMAP_HOST": "imap.example.com", "MAIL__SMTP_SECURITY": "starttls"})
    assert mail_settings("alice", "smtp")["port"] == 587
    user_secrets.update_user_secrets("alice", {"MAIL__SMTP_SECURITY": "plaintext"})
    assert mail_tools.MailSendTool().check_ready("alice")[0] is False


class FakeIMAP:
    def __init__(self):
        self.literal = None
        self.calls = []
        self.validity = b"42"

    def login(self, username, password): pass
    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly)); return "OK", [b"2"]
    def response(self, name): return name, [self.validity]
    def logout(self): self.calls.append(("logout",))
    def uid(self, command, *args):
        self.calls.append((command, *args))
        if command == "SEARCH": return "OK", [b"1 2"]
        raw = b"Subject: =?utf-8?b?5L2g5aW9?=\r\nFrom: sender@example.com\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>Hello <b>Alice</b></p><script>hidden()</script>"
        return "OK", [(b"2 (BODY[] {100}", raw), b")"]


@pytest.mark.asyncio
async def test_mail_search_and_read_do_not_change_flags(accounts, monkeypatch):
    client = FakeIMAP()
    monkeypatch.setattr(mail_tools.imaplib, "IMAP4_SSL", lambda *args, **kwargs: client)
    found = await mail_tools.MailSearchTool().invoke({"query": "中文", "limit": 1}, accounts)
    assert found["matched"] == 2 and found["messages"][0]["uid"] == "2"
    assert client.literal == "中文".encode()
    assert all(call[2] is True for call in client.calls if call[0] == "select")
    assert all("BODY.PEEK" in call[2] for call in client.calls if call[0] == "FETCH")
    result = await mail_tools.MailReadTool().invoke({"uid": "2", "uid_validity": "42"}, accounts)
    assert result["subject"] == "你好"
    assert "Hello Alice" in result["text"] and "hidden" not in result["text"]
    assert result["untrusted_content"] is True
    with pytest.raises(ValueError, match="mailbox changed"):
        await mail_tools.MailReadTool().invoke({"uid": "2", "uid_validity": "99"}, accounts)


@pytest.mark.asyncio
async def test_mail_send_requires_exact_runtime_consent_and_hides_bcc(accounts, monkeypatch):
    smtp = MagicMock()
    smtp.send_message.return_value = {"no@example.com": (550, b"rejected")}
    monkeypatch.setattr(mail_tools.smtplib, "SMTP_SSL", lambda *args, **kwargs: smtp)
    tool = mail_tools.MailSendTool()
    args = {"to": ["yes@example.com", "no@example.com"], "bcc": ["private@example.com"], "subject": "Hello", "body": "Draft"}
    with pytest.raises(PermissionError): await tool.invoke(args, accounts)
    smtp.send_message.assert_not_called()
    with approval_scope(tool.tool_id, args, confirmed=True):
        with pytest.raises(PermissionError): await tool.invoke({**args, "body": "Changed"}, accounts)
        result = await tool.invoke(args, accounts)
    message = smtp.send_message.call_args.args[0]
    assert message["Bcc"] is None
    assert "private@example.com" in smtp.send_message.call_args.kwargs["to_addrs"]
    assert result["delivered"] is None and result["submission_status"] == "partially_accepted"
    assert result["accepted"] == ["yes@example.com", "private@example.com"]
    smtp.quit.assert_called_once()


@pytest.mark.asyncio
async def test_mail_ambiguous_send_is_not_retried(accounts, monkeypatch):
    smtp = MagicMock()
    smtp.send_message.side_effect = mail_tools.smtplib.SMTPServerDisconnected("lost response")
    monkeypatch.setattr(mail_tools.smtplib, "SMTP_SSL", lambda *args, **kwargs: smtp)
    args = {"to": ["x@example.com"], "subject": "Hello", "body": "Text"}
    with approval_scope("mail.send", args, confirmed=True), pytest.raises(RuntimeError, match="outcome is unknown") as caught:
        await mail_tools.MailSendTool().invoke(args, accounts)
    from agentkit.mcp.tool_result import error_from_exception
    detail = error_from_exception(caught.value)
    assert detail.code == "EXTERNAL_OUTCOME_UNKNOWN" and detail.retryable is False
    smtp.send_message.assert_called_once()
    assert mail_tools.MailSendTool.retry_policy == {"max_retries": 0}


@pytest.mark.asyncio
async def test_auth_errors_do_not_echo_account_secrets(accounts, monkeypatch):
    def fail(*args, **kwargs): raise mail_tools.imaplib.IMAP4.error("private-app-password")
    monkeypatch.setattr(mail_tools.imaplib, "IMAP4_SSL", fail)
    with pytest.raises(RuntimeError) as caught:
        await mail_tools.MailSearchTool().invoke({}, accounts)
    assert "private-app-password" not in str(caught.value)


def test_calendar_requires_explicit_timezones_and_bounded_queries():
    with pytest.raises(ValidationError):
        calendar_tools._Search(calendar_id="cal", start="2026-10-20T10:00:00", end="2026-10-21T10:00:00")
    with pytest.raises(ValidationError):
        calendar_tools._Search(calendar_id="cal", start="2026-10-20T10:00:00Z", end="2028-10-21T10:00:00Z")


def test_travel_skill_is_discoverable_and_does_not_grant_tool_authority():
    from skills.registry import SkillRegistry
    registry = SkillRegistry()
    registry.load_official_packs()
    skill = registry.get_skill("travel_booking")
    assert skill and skill.model_invocable and skill.execution_context == "inline"
    assert skill.allowed_tools == [] and skill.permission_profile == "default"
    assert skill.examples and skill.evaluation_cases
    service = CapabilityService()
    service.ensure_discovered_tools()
    assert service.requires_confirmation("skill.run", {"skill_id": "travel_booking"}) is False
    assert service.requires_confirmation("computer_control.browser_action", {"action": "click"}) is True


def test_caldav_transport_restricts_redirects_origin_and_writes():
    session = MagicMock()
    response = session.request.return_value
    response.status_code = 207
    response.iter_content.return_value = [b"<xml/>"]
    args = {"expected_etag": '"v1"'}
    transport = calendar_tools._ScopedSession(session, ("calendar.example.com", 443), "calendar.delete", args)
    with pytest.raises(PermissionError): transport.request("GET", "https://other.example.com/")
    with pytest.raises(PermissionError): transport.request("DELETE", "https://calendar.example.com/event")
    with approval_scope("calendar.delete", args, confirmed=True):
        transport.request("DELETE", "https://calendar.example.com/event")
    assert session.request.call_args.kwargs["headers"]["If-Match"] == '"v1"'
    assert session.request.call_args.kwargs["allow_redirects"] is False
    response.status_code = 302
    with pytest.raises(PermissionError, match="redirect"):
        transport.request("GET", "https://calendar.example.com/")


def test_caldav_transport_bounds_payload_and_preserves_create_precondition():
    session = MagicMock()
    response = session.request.return_value
    response.status_code = 201
    response.iter_content.return_value = [b"x" * (8 * 1024 * 1024 + 1)]
    args = {"uid": "new"}
    transport = calendar_tools._ScopedSession(session, ("calendar.example.com", 443), "calendar.create", args)
    with approval_scope("calendar.create", args, confirmed=True), pytest.raises(ValueError, match="8 MiB"):
        transport.request("PUT", "https://calendar.example.com/new.ics")
    assert session.request.call_args.kwargs["headers"]["If-None-Match"] == "*"


@pytest.mark.asyncio
async def test_calendar_tools_use_real_icalendar_and_caldav_client_contract(accounts, monkeypatch):
    caldav = pytest.importorskip("caldav")
    icalendar = pytest.importorskip("icalendar")
    settings = calendar_tools.calendar_settings("alice")
    with calendar_tools._client(settings, "calendar.list", {}) as real_client:
        assert isinstance(real_client, caldav.DAVClient)
        assert isinstance(real_client.session, calendar_tools._ScopedSession)
    saved = []
    resource = SimpleNamespace(props={}, load=lambda: None, delete=MagicMock())
    class Calendar:
        id = "owned"; name = "Personal"
        def save_event(self, data, no_overwrite=False):
            assert no_overwrite
            saved.append(icalendar.Calendar.from_ical(data))
            return resource
        def event_by_uid(self, uid): return resource
        def search(self, **kwargs):
            assert kwargs["expand"] and kwargs["start"].tzinfo
            return []
    calendar = Calendar()
    @contextmanager
    def fake_client(*args):
        yield SimpleNamespace(principal=lambda: SimpleNamespace(calendars=lambda: [calendar]))
    monkeypatch.setattr(calendar_tools, "_client", fake_client)
    rows = await calendar_tools.CalendarListTool().invoke({}, accounts)
    assert rows["calendars"][0]["calendar_id"] == "owned"
    args = {"calendar_id": "owned", "uid": "7d14109e-2cb3-43e7-b9c8-5dbd42dd78e7", "summary": "会议", "start": "2026-10-20T10:00:00+08:00", "end": "2026-10-20T11:00:00+08:00"}
    with pytest.raises(PermissionError): await calendar_tools.CalendarCreateTool().invoke(args, accounts)
    with approval_scope("calendar.create", args, confirmed=True):
        result = await calendar_tools.CalendarCreateTool().invoke(args, accounts)
    assert result["created"] and str(saved[0].walk("VEVENT")[0]["SUMMARY"]) == "会议"
    assert not saved[0].walk("VEVENT")[0].get("ATTENDEE")
    resource.icalendar_instance = saved[0]
    from caldav.elements import dav
    resource.props[dav.GetEtag.tag] = '"v2"'
    delete = {"calendar_id": "owned", "uid": args["uid"], "expected_etag": '"v1"'}
    with approval_scope("calendar.delete", delete, confirmed=True), pytest.raises(ValueError, match="changed"):
        await calendar_tools.CalendarDeleteTool().invoke(delete, accounts)
    resource.delete.assert_not_called()
