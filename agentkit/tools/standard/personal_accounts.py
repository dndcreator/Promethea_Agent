"""User-scoped account configuration shared by productivity tools."""
from __future__ import annotations

from urllib.parse import urlsplit

from agentkit.mcp.invocation_context import get_invocation_context
from agentkit.security.approval import matches_approved_call
from agentkit.security.sandbox import get_sandbox_policy
from gateway.user_secrets import resolve_personal_account_settings


class ExternalOutcomeUnknown(RuntimeError):
    code = "EXTERNAL_OUTCOME_UNKNOWN"
    category = "external"
    retryable = False
    advice = "Inspect provider records before any further submission; do not blindly retry."


def account_user(ctx=None) -> str:
    user_id = str(get_invocation_context().get("user_id") or getattr(ctx, "user_id", "") or "")
    if not user_id:
        raise PermissionError("personal accounts require an authenticated user")
    return user_id


def require_consent(tool_id: str, args: dict) -> None:
    if not matches_approved_call(tool_id, args):
        raise PermissionError("this external write requires Runtime confirmation for the exact call")


def check_endpoint(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("account endpoints require HTTPS without embedded credentials or fragments")
    decision = get_sandbox_policy().check_url(url)
    if not decision.allowed:
        raise PermissionError(f"account endpoint blocked: {decision.reason}")
    return url


def mail_settings(user_id: str, direction: str) -> dict:
    settings = resolve_personal_account_settings(user_id, "mail")
    required = [f"{direction}_host", "username", "password"]
    if not all(settings.get(key) for key in required):
        raise ValueError(f"mail {direction} account is not configured for this user")
    host = settings[f"{direction}_host"]
    if any(character in host for character in "/@?#\\\r\n "):
        raise ValueError("mail host must be a hostname, not a URL")
    default_port = 993 if direction == "imap" else (587 if settings.get("smtp_security") == "starttls" else 465)
    port = int(settings.get(f"{direction}_port") or default_port)
    if not 1 <= port <= 65535:
        raise ValueError("mail port must be between 1 and 65535")
    check_endpoint(f"https://{host}:{port}")
    return {**settings, "host": host, "port": port}


class AccountTool:
    domain = "productivity"
    timeout_ms = 60000
    retry_policy = {"max_retries": 0}
    concurrency_safe = False

    def check_ready(self, user_id: str) -> tuple[bool, str]:
        try:
            self.settings(user_id)
            return True, ""
        except (ValueError, PermissionError) as error:
            return False, str(error)
        except Exception:
            return False, "personal_account_readiness_failed"
