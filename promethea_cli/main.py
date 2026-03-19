from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
AUTH_FILE = Path.home() / ".promethea" / "cli_auth.json"


class CliError(Exception):
    pass


def _print(obj: Any, pretty: bool = False) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2 if pretty else None))


def _load_json(inline: Optional[str], file_path: Optional[str]) -> Dict[str, Any]:
    if bool(inline) == bool(file_path):
        raise CliError("use exactly one of --json or --file")
    src = inline if inline else Path(file_path or "").read_text(encoding="utf-8")
    data = json.loads(src or "{}")
    if not isinstance(data, dict):
        raise CliError("json payload must be an object")
    return data


class AuthStore:
    def __init__(self, path: Path = AUTH_FILE) -> None:
        self.path = path

    def token(self) -> Optional[str]:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return None
        token = data.get("access_token")
        return str(token) if token else None

    def save_login(self, payload: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "access_token": payload.get("access_token"),
                    "token_type": payload.get("token_type", "bearer"),
                    "user_id": payload.get("user_id"),
                    "username": payload.get("username"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


class Client:
    def __init__(
        self,
        base_url: str,
        token: Optional[str],
        pretty: bool,
        store: AuthStore,
        idempotency_key: Optional[str] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.pretty = pretty
        self.store = store
        self.idempotency_key = idempotency_key

    def _headers(self, auth: bool, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = dict(extra or {})
        token = self.token or self.store.token()
        if auth and token:
            headers["Authorization"] = f"Bearer {token}"
        if self.idempotency_key:
            headers["X-Idempotency-Key"] = self.idempotency_key
        return headers

    def req(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        form: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        stream: bool = False,
    ) -> requests.Response:
        try:
            return requests.request(
                method=method,
                url=f"{self.base_url}{path}",
                headers=self._headers(auth, headers),
                params=params,
                json=payload,
                files=files,
                data=form,
                stream=stream,
                timeout=180,
            )
        except requests.RequestException as exc:
            raise CliError(f"request failed: {exc}") from exc

    def req_json(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        r = self.req(method, path, **kwargs)
        ctype = str(r.headers.get("content-type", ""))
        if r.status_code >= 400:
            msg = r.json() if "application/json" in ctype else r.text
            raise CliError(f"{r.status_code} {path}: {msg}")
        if "application/json" not in ctype:
            raise CliError(f"expected JSON from {path}, got {ctype}")
        return r.json()

    def emit(self, data: Any) -> None:
        _print(data, pretty=self.pretty)


def _dispatch_alias(args: argparse.Namespace) -> None:
    if args.command in {"register", "login", "logout", "whoami"}:
        args.command = "auth"
        args.auth_cmd = args.command_alias


def cmd_auth(args: argparse.Namespace, c: Client) -> None:
    if args.auth_cmd == "register":
        body = {"username": args.username, "password": args.password}
        if args.agent_name:
            body["agent_name"] = args.agent_name
        c.emit(c.req_json("POST", "/api/auth/register", auth=False, payload=body))
        return
    if args.auth_cmd == "login":
        body = {"username": args.username, "password": args.password}
        data = c.req_json("POST", "/api/auth/login", auth=False, payload=body)
        if data.get("access_token"):
            c.store.save_login(data)
        c.emit(data)
        return
    if args.auth_cmd == "logout":
        c.store.clear()
        c.emit({"status": "success", "message": "logged out"})
        return
    if args.auth_cmd == "whoami":
        c.emit(c.req_json("GET", "/api/user/profile"))
        return
    if args.auth_cmd == "delete":
        c.emit(c.req_json("POST", "/api/user/delete", payload={"confirm": True}))
        c.store.clear()
        return
    raise CliError(f"unknown auth command: {args.auth_cmd}")


def cmd_chat(args: argparse.Namespace, c: Client) -> None:
    if args.chat_cmd in {"send", "chat"}:
        body = {
            "message": args.message,
            "stream": bool(args.stream),
            "session_id": args.session_id,
            "requested_mode": args.mode,
            "requested_skill": args.skill,
        }
        if args.stream:
            r = c.req("POST", "/api/chat", payload=body, stream=True)
            if r.status_code >= 400:
                raise CliError(f"{r.status_code} /api/chat: {r.text}")
            for line in r.iter_lines(decode_unicode=True):
                if not line:
                    continue
                raw = str(line).strip()
                if not raw.startswith("data:"):
                    continue
                item = raw[5:].strip()
                try:
                    c.emit(json.loads(item))
                except Exception:
                    c.emit({"type": "raw", "content": item})
            return
        c.emit(c.req_json("POST", "/api/chat", payload=body))
        return
    if args.chat_cmd == "chat-confirm":
        body = {"session_id": args.session_id, "tool_call_id": args.tool_call_id, "action": args.action}
        c.emit(c.req_json("POST", "/api/chat/confirm", payload=body))
        return
    raise CliError(f"unknown chat command: {args.chat_cmd}")

def cmd_ask(args: argparse.Namespace, c: Client) -> None:
    shim = argparse.Namespace(
        chat_cmd="send",
        message=args.message,
        stream=bool(args.stream),
        session_id=args.session_id,
        mode=args.mode,
        skill=args.skill,
    )
    cmd_chat(shim, c)



def cmd_simple(args: argparse.Namespace, c: Client) -> None:
    mapping = {
        # followup
        ("followup", None): ("POST", "/api/followup", lambda a: {"selected_text": a.selected_text, "query_type": a.query_type, "custom_query": a.custom_query, "session_id": a.session_id}),
        # sessions
        ("sessions", "list"): ("GET", "/api/sessions", None),
        ("sessions", "show"): ("GET", None, None),
        # status
        ("status", "base"): ("GET", "/api/status", None),
        ("status", "services"): ("GET", "/api/status/services", None),
        ("status", "memory"): ("GET", "/api/health/memory", None),
        ("status", "routes"): ("GET", "/api/status/routes", None),
        ("status", "tools"): ("GET", "/api/status/tools", None),
        # metrics
        ("metrics", "json"): ("GET", "/api/metrics", None),
        # doctor
        ("doctor", "run"): ("GET", "/api/doctor", None),
        ("doctor", "migrate"): ("POST", "/api/doctor/migrate-config", lambda _a: {}),
        # ops
        ("ops", "capabilities"): ("GET", "/api/ops/capabilities", None),
        ("ops", "runbook"): ("GET", "/api/ops/runbook", None),
        ("ops", "abstractions"): ("GET", "/api/ops/abstractions", None),
        ("ops", "protocol"): ("GET", "/api/ops/protocol", None),
        # skills
        ("skills", "catalog"): ("GET", "/api/skills/catalog", None),
        ("skills", "show"): ("GET", None, None),
        ("skills", "install"): ("POST", "/api/skills/install", lambda a: {"skill_id": a.skill_id, "enabled": not a.disabled}),
        ("skills", "activate"): ("POST", "/api/skills/activate", lambda a: {"skill_id": None if a.clear else a.skill_id}),
    }
    key = (args.command, getattr(args, f"{args.command}_cmd", None))
    if key not in mapping:
        raise CliError("unsupported simple command")
    method, path, body_fn = mapping[key]
    if key == ("sessions", "show"):
        path = f"/api/sessions/{args.session_id}"
    if key == ("skills", "show"):
        path = f"/api/skills/{args.skill_id}"
    payload = body_fn(args) if body_fn else None
    c.emit(c.req_json(method, path, payload=payload))


def cmd_config(args: argparse.Namespace, c: Client) -> None:
    sub = args.config_cmd
    if sub == "get":
        params = {"view": args.view}
        if args.raw:
            params["raw"] = "true"
        c.emit(c.req_json("GET", "/api/config", params=params))
    elif sub == "update":
        body: Dict[str, Any] = {"config": _load_json(args.json, args.file)}
        if args.hot_apply:
            body["options"] = {"hot_apply": True}
        c.emit(c.req_json("POST", "/api/config/update", payload=body))
    elif sub == "reset":
        c.emit(c.req_json("POST", "/api/config/reset", payload={"reset_to_default": not args.no_default}))
    elif sub == "switch-model":
        body: Dict[str, Any] = {"model": args.model}
        if args.api_key:
            body["api_key"] = args.api_key
        if args.model_base_url:
            body["base_url"] = args.model_base_url
        c.emit(c.req_json("POST", "/api/config/switch-model", payload=body))
    elif sub == "diagnose":
        c.emit(c.req_json("GET", "/api/config/diagnose"))
    elif sub == "reload":
        c.emit(c.req_json("POST", "/api/config/reload", payload={}))
    elif sub == "runtime":
        c.emit(c.req_json("GET", "/api/config/runtime"))
    elif sub == "runtime-reload":
        c.emit(c.req_json("POST", "/api/config/runtime/reload", payload={}))
    elif sub == "preferences":
        c.emit(c.req_json("GET", "/api/config/preferences", params={"scope": args.scope} if args.scope else None))
    elif sub == "tool-policy":
        c.emit(c.req_json("GET", "/api/config/tool-policy", params={"agent_id": args.agent_id} if args.agent_id else None))
    elif sub == "channel":
        c.emit(c.req_json("GET", f"/api/config/channel/{args.channel_id}"))
    else:
        raise CliError(f"unknown config command: {sub}")


def cmd_memory(args: argparse.Namespace, c: Client) -> None:
    sub = args.memory_cmd
    if sub == "capabilities":
        c.emit(c.req_json("GET", "/api/memory/capabilities"))
        return
    if sub == "graph":
        path = f"/api/memory/graph/{args.session_id}" if args.session_id else "/api/memory/graph"
        c.emit(c.req_json("GET", path))
        return
    if sub in {"cluster", "decay", "cleanup", "concepts", "summaries", "forgetting-stats"}:
        base = {
            "cluster": "/api/memory/cluster",
            "decay": "/api/memory/decay",
            "cleanup": "/api/memory/cleanup",
            "concepts": "/api/memory/concepts",
            "summaries": "/api/memory/summaries",
            "forgetting-stats": "/api/memory/forgetting/stats",
        }[sub]
        method = "POST" if sub in {"cluster", "decay", "cleanup"} else "GET"
        c.emit(c.req_json(method, f"{base}/{args.session_id}", payload={} if method == "POST" else None))
        return
    if sub == "summarize":
        c.emit(c.req_json("POST", f"/api/memory/summarize/{args.session_id}", params={"incremental": str(bool(args.incremental)).lower()}, payload={}))
        return
    if sub == "summary-get":
        c.emit(c.req_json("GET", f"/api/memory/summary/{args.summary_id}"))
        return
    if sub == "recall-runs":
        params: Dict[str, Any] = {"limit": args.limit}
        if args.session_id:
            params["session_id"] = args.session_id
        if args.trace_id:
            params["trace_id"] = args.trace_id
        c.emit(c.req_json("GET", "/api/memory/recall/runs", params=params))
        return
    if sub == "recall-inspect":
        c.emit(c.req_json("GET", f"/api/memory/recall/{args.request_id}"))
        return
    if sub == "entries-list":
        params: Dict[str, Any] = {
            "scope": args.scope,
            "q": args.query,
            "limit": args.limit,
            "offset": args.offset,
            "include_archived": str(bool(args.include_archived)).lower(),
        }
        if args.session_id:
            params["session_id"] = args.session_id
        if args.memory_types:
            params["memory_types"] = args.memory_types
        c.emit(c.req_json("GET", "/api/memory/entries", params=params))
        return
    if sub == "entries-create":
        payload: Dict[str, Any] = {
            "content": args.content,
            "memory_type": args.memory_type,
        }
        if args.session_id:
            payload["session_id"] = args.session_id
        if args.source_layer:
            payload["source_layer"] = args.source_layer
        c.emit(c.req_json("POST", "/api/memory/entries", payload=payload))
        return
    if sub == "entries-update":
        payload: Dict[str, Any] = {}
        if args.content is not None:
            payload["content"] = args.content
        if args.memory_type is not None:
            payload["memory_type"] = args.memory_type
        if args.metadata_json or args.metadata_file:
            payload["metadata"] = _load_json(args.metadata_json, args.metadata_file)
        c.emit(c.req_json("PATCH", f"/api/memory/entries/{args.memory_id}", payload=payload))
        return
    if sub == "entries-delete":
        c.emit(c.req_json("DELETE", f"/api/memory/entries/{args.memory_id}"))
        return
    if sub == "write-decisions":
        params: Dict[str, Any] = {"limit": args.limit}
        if args.session_id:
            params["session_id"] = args.session_id
        if args.trace_id:
            params["trace_id"] = args.trace_id
        if args.decision:
            params["decision"] = args.decision
        c.emit(c.req_json("GET", "/api/memory/write-decisions", params=params))
        return
    if sub == "write-proposals":
        params: Dict[str, Any] = {"status": args.status, "limit": args.limit}
        c.emit(c.req_json("GET", "/api/memory/write-proposals", params=params))
        return
    if sub == "proposal-decide":
        c.emit(
            c.req_json(
                "POST",
                f"/api/memory/write-proposals/{args.proposal_id}/decision",
                payload={"action": args.action},
            )
        )
        return
    if sub == "dev-dashboard":
        params: Dict[str, Any] = {"limit": args.limit}
        if args.session_id:
            params["session_id"] = args.session_id
        c.emit(c.req_json("GET", "/api/memory/dev/dashboard", params=params))
        return
    raise CliError(f"unknown memory command: {sub}")

def cmd_workflow(args: argparse.Namespace, c: Client) -> None:
    sub = args.workflow_cmd
    if sub == "define":
        c.emit(c.req_json("POST", "/api/workflow/define", payload=_load_json(args.json, args.file)))
    elif sub == "list":
        c.emit(c.req_json("GET", "/api/workflow/list", params={"limit": args.limit}))
    elif sub == "start":
        c.emit(c.req_json("POST", "/api/workflow/start", payload=_load_json(args.json, args.file)))
    elif sub in {"run", "pause", "resume", "checkpoints"}:
        method = "GET" if sub in {"run", "checkpoints"} else "POST"
        path = {
            "run": f"/api/workflow/run/{args.workflow_run_id}",
            "pause": f"/api/workflow/pause/{args.workflow_run_id}",
            "resume": f"/api/workflow/resume/{args.workflow_run_id}",
            "checkpoints": f"/api/workflow/checkpoints/{args.workflow_run_id}",
        }[sub]
        c.emit(c.req_json(method, path, payload={} if method == "POST" else None))
    elif sub in {"retry", "approve"}:
        path = "/api/workflow/retry" if sub == "retry" else "/api/workflow/approve"
        c.emit(c.req_json("POST", path, payload=_load_json(args.json, args.file)))
    else:
        raise CliError(f"unknown workflow command: {sub}")


def cmd_security(args: argparse.Namespace, c: Client) -> None:
    if args.security_cmd == "report":
        c.emit(c.req_json("GET", "/api/security/audit/report", params={"limit": args.limit}))
    elif args.security_cmd == "events":
        params: Dict[str, Any] = {"limit": args.limit}
        if args.action:
            params["action"] = args.action
        c.emit(c.req_json("GET", "/api/security/audit/events", params=params))
    else:
        raise CliError(f"unknown security command: {args.security_cmd}")


def cmd_automation(args: argparse.Namespace, c: Client) -> None:
    path = "/api/automation/webhook" if args.automation_cmd == "webhook" else "/api/automation/cron/wakeup"
    headers = {"X-Automation-Token": args.automation_token} if args.automation_token else None
    body = {"user_id": args.user_id, "message": args.message, "session_id": args.session_id, "source": args.source}
    c.emit(c.req_json("POST", path, auth=False, headers=headers, payload=body))


def cmd_batch(args: argparse.Namespace, c: Client) -> None:
    c.emit(c.req_json("POST", "/api/batch", payload=_load_json(args.json, args.file)))


def cmd_voice(args: argparse.Namespace, c: Client) -> None:
    sub = args.voice_cmd
    if sub == "capabilities":
        c.emit(c.req_json("GET", "/api/voice/capabilities"))
        return
    if sub == "turn":
        c.emit(c.req_json("POST", "/api/voice/turn", payload={"text": args.text, "session_id": args.session_id, "wake_word": args.wake_word}))
        return
    if sub == "stt":
        p = Path(args.file)
        with p.open("rb") as f:
            files = {"audio": (p.name, f, args.content_type)}
            c.emit(c.req_json("POST", "/api/voice/stt", files=files))
        return
    if sub == "tts":
        body: Dict[str, Any] = {"text": args.text, "format": args.format}
        for name in ("provider", "voice", "speed", "stability", "similarity_boost", "style", "use_speaker_boost"):
            value = getattr(args, name, None)
            if value is not None:
                body[name] = value
        r = c.req("POST", "/api/voice/tts", payload=body)
        if r.status_code >= 400:
            raise CliError(f"{r.status_code} /api/voice/tts: {r.text}")
        if args.out:
            out = Path(args.out)
            out.write_bytes(r.content)
            c.emit({"status": "success", "written": str(out), "bytes": len(r.content)})
        else:
            c.emit({"status": "success", "mime": r.headers.get("content-type", "application/octet-stream"), "audio_base64": base64.b64encode(r.content).decode("ascii")})
        return
    if sub == "ptt":
        p = Path(args.file)
        form = {"session_id": args.session_id or "", "wake_word": args.wake_word or "", "speak": str(bool(args.speak)).lower(), "tts_provider": args.tts_provider or "", "tts_voice": args.tts_voice or "", "tts_format": args.tts_format}
        with p.open("rb") as f:
            files = {"audio": (p.name, f, args.content_type)}
            c.emit(c.req_json("POST", "/api/voice/ptt", files=files, form=form))
        return
    raise CliError(f"unknown voice command: {sub}")


def cmd_call(args: argparse.Namespace, c: Client) -> None:
    path = args.path if args.path.startswith("/") else "/" + args.path
    params: Dict[str, str] = {}
    for item in args.query:
        if "=" not in item:
            raise CliError(f"invalid --query '{item}', expected key=value")
        k, v = item.split("=", 1)
        params[k] = v
    payload = _load_json(args.json, args.file) if (args.json or args.file) else None
    if args.stream:
        r = c.req(args.method, path, auth=not args.no_auth, params=params or None, payload=payload, stream=True)
        if r.status_code >= 400:
            raise CliError(f"{r.status_code} {path}: {r.text}")
        for line in r.iter_lines(decode_unicode=True):
            if line:
                print(line)
        return
    r = c.req(args.method, path, auth=not args.no_auth, params=params or None, payload=payload)
    if r.status_code >= 400:
        raise CliError(f"{r.status_code} {path}: {r.text}")
    if "application/json" in str(r.headers.get("content-type", "")):
        c.emit(r.json())
    else:
        print(r.text)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="promethea", description="Promethea protocol-first CLI")
    p.add_argument("--base-url", default=os.getenv("PROMETHEA_BASE_URL", DEFAULT_BASE_URL))
    p.add_argument("--token", default=None)
    p.add_argument("--pretty", action="store_true")
    p.add_argument("--idempotency-key", default=None)
    sp = p.add_subparsers(dest="command", required=True)

    auth = sp.add_parser("auth")
    asp = auth.add_subparsers(dest="auth_cmd", required=True)
    r = asp.add_parser("register"); r.add_argument("username"); r.add_argument("password"); r.add_argument("--agent-name", default=None)
    l = asp.add_parser("login"); l.add_argument("username"); l.add_argument("password")
    asp.add_parser("logout"); asp.add_parser("whoami"); asp.add_parser("delete")

    for alias in ("register", "login", "logout", "whoami"):
        a = sp.add_parser(alias, help=argparse.SUPPRESS)
        a.set_defaults(command_alias=alias)
        if alias in {"register", "login"}:
            a.add_argument("username"); a.add_argument("password")
        if alias == "register":
            a.add_argument("--agent-name", default=None)

    chat = sp.add_parser("chat"); csp = chat.add_subparsers(dest="chat_cmd", required=True)
    ch = csp.add_parser("send"); ch.add_argument("message"); ch.add_argument("--session-id", default=None); ch.add_argument("--mode", default=None); ch.add_argument("--skill", default=None); ch.add_argument("--stream", action="store_true")
    ch_legacy = csp.add_parser("chat", help=argparse.SUPPRESS); ch_legacy.add_argument("message"); ch_legacy.add_argument("--session-id", default=None); ch_legacy.add_argument("--mode", default=None); ch_legacy.add_argument("--skill", default=None); ch_legacy.add_argument("--stream", action="store_true")
    cc = csp.add_parser("chat-confirm"); cc.add_argument("session_id"); cc.add_argument("tool_call_id"); cc.add_argument("action", choices=["approve", "reject"])

    ask = sp.add_parser("ask"); ask.add_argument("message"); ask.add_argument("--session-id", default=None); ask.add_argument("--mode", default=None); ask.add_argument("--skill", default=None); ask.add_argument("--stream", action="store_true")

    f = sp.add_parser("followup"); f.add_argument("selected_text"); f.add_argument("query_type"); f.add_argument("session_id"); f.add_argument("--custom-query", default=None)
    ses = sp.add_parser("sessions"); ssp = ses.add_subparsers(dest="sessions_cmd", required=True); ssp.add_parser("list"); ss = ssp.add_parser("show"); ss.add_argument("session_id")
    st = sp.add_parser("status"); tsp = st.add_subparsers(dest="status_cmd", required=True); [tsp.add_parser(x) for x in ("base", "services", "memory", "routes", "tools")]

    cfg = sp.add_parser("config"); cgp = cfg.add_subparsers(dest="config_cmd", required=True)
    g = cgp.add_parser("get"); g.add_argument("--view", choices=["basic", "full"], default="full"); g.add_argument("--raw", action="store_true")
    u = cgp.add_parser("update"); u.add_argument("--json", default=None); u.add_argument("--file", default=None); u.add_argument("--hot-apply", action="store_true")
    rs = cgp.add_parser("reset"); rs.add_argument("--no-default", action="store_true")
    sm = cgp.add_parser("switch-model"); sm.add_argument("model"); sm.add_argument("--api-key", default=None); sm.add_argument("--model-base-url", default=None)
    cgp.add_parser("diagnose"); cgp.add_parser("reload"); cgp.add_parser("runtime"); cgp.add_parser("runtime-reload")
    pr = cgp.add_parser("preferences"); pr.add_argument("--scope", default=None)
    tp = cgp.add_parser("tool-policy"); tp.add_argument("--agent-id", default=None)
    chn = cgp.add_parser("channel"); chn.add_argument("channel_id")

    mem = sp.add_parser("memory"); msp = mem.add_subparsers(dest="memory_cmd", required=True)
    msp.add_parser("capabilities")
    mg = msp.add_parser("graph"); mg.add_argument("--session-id", default=None)
    for x in ("cluster", "summarize", "decay", "cleanup", "concepts", "summaries", "forgetting-stats"):
        cmd = msp.add_parser(x); cmd.add_argument("session_id")
        if x == "summarize":
            cmd.add_argument("--incremental", action="store_true")
    sget = msp.add_parser("summary-get"); sget.add_argument("summary_id")
    rr = msp.add_parser("recall-runs"); rr.add_argument("--session-id", default=None); rr.add_argument("--trace-id", default=None); rr.add_argument("--limit", type=int, default=20)
    ri = msp.add_parser("recall-inspect"); ri.add_argument("request_id")
    mel = msp.add_parser("entries-list"); mel.add_argument("--scope", default="all", choices=["all", "session", "project", "identity", "constraints", "preferences"]); mel.add_argument("--session-id", default=None); mel.add_argument("--memory-types", default=None); mel.add_argument("--query", default=""); mel.add_argument("--limit", type=int, default=100); mel.add_argument("--offset", type=int, default=0); mel.add_argument("--include-archived", action="store_true")
    mec = msp.add_parser("entries-create"); mec.add_argument("content"); mec.add_argument("--memory-type", default="preference"); mec.add_argument("--session-id", default=None); mec.add_argument("--source-layer", default=None)
    meu = msp.add_parser("entries-update"); meu.add_argument("memory_id"); meu.add_argument("--content", default=None); meu.add_argument("--memory-type", default=None); meu.add_argument("--metadata-json", default=None); meu.add_argument("--metadata-file", default=None)
    med = msp.add_parser("entries-delete"); med.add_argument("memory_id")
    mwd = msp.add_parser("write-decisions"); mwd.add_argument("--session-id", default=None); mwd.add_argument("--trace-id", default=None); mwd.add_argument("--decision", default=None); mwd.add_argument("--limit", type=int, default=100)
    mwp = msp.add_parser("write-proposals"); mwp.add_argument("--status", default="pending", choices=["pending", "confirmed", "dismissed", "all"]); mwp.add_argument("--limit", type=int, default=100)
    mpd = msp.add_parser("proposal-decide"); mpd.add_argument("proposal_id"); mpd.add_argument("action", choices=["confirm_write", "ignore_once", "reduce_similar"])
    mdd = msp.add_parser("dev-dashboard"); mdd.add_argument("--session-id", default=None); mdd.add_argument("--limit", type=int, default=200)
    wf = sp.add_parser("workflow"); wsp = wf.add_subparsers(dest="workflow_cmd", required=True)
    for x in ("define", "start", "retry", "approve"):
        cmd = wsp.add_parser(x); cmd.add_argument("--json", default=None); cmd.add_argument("--file", default=None)
    wfl = wsp.add_parser("list"); wfl.add_argument("--limit", type=int, default=50)
    for x in ("run", "pause", "resume", "checkpoints"):
        cmd = wsp.add_parser(x); cmd.add_argument("workflow_run_id")

    skl = sp.add_parser("skills"); skp = skl.add_subparsers(dest="skills_cmd", required=True)
    skp.add_parser("catalog")
    sks = skp.add_parser("show"); sks.add_argument("skill_id")
    ski = skp.add_parser("install"); ski.add_argument("skill_id"); ski.add_argument("--disabled", action="store_true")
    ska = skp.add_parser("activate"); ska.add_argument("skill_id", nargs="?"); ska.add_argument("--clear", action="store_true")

    sec = sp.add_parser("security"); scp = sec.add_subparsers(dest="security_cmd", required=True)
    sr = scp.add_parser("report"); sr.add_argument("--limit", type=int, default=100)
    se = scp.add_parser("events"); se.add_argument("--action", default=None); se.add_argument("--limit", type=int, default=100)

    met = sp.add_parser("metrics"); mtp = met.add_subparsers(dest="metrics_cmd", required=True); mtp.add_parser("json"); mtp.add_parser("prometheus")
    doc = sp.add_parser("doctor"); dcp = doc.add_subparsers(dest="doctor_cmd", required=True); dcp.add_parser("run"); dcp.add_parser("migrate")
    ops = sp.add_parser("ops"); opp = ops.add_subparsers(dest="ops_cmd", required=True); opp.add_parser("capabilities"); opp.add_parser("runbook"); opp.add_parser("abstractions"); opp.add_parser("protocol")

    auto = sp.add_parser("automation"); atp = auto.add_subparsers(dest="automation_cmd", required=True)
    for x in ("webhook", "cron"):
        cmd = atp.add_parser(x); cmd.add_argument("user_id"); cmd.add_argument("message"); cmd.add_argument("--session-id", default=None); cmd.add_argument("--source", default=x); cmd.add_argument("--automation-token", default=None)

    batch = sp.add_parser("batch"); batch.add_argument("--json", default=None); batch.add_argument("--file", default=None)

    voice = sp.add_parser("voice"); vsp = voice.add_subparsers(dest="voice_cmd", required=True)
    vsp.add_parser("capabilities")
    vt = vsp.add_parser("turn"); vt.add_argument("text"); vt.add_argument("--session-id", default=None); vt.add_argument("--wake-word", default=None)
    vs = vsp.add_parser("stt"); vs.add_argument("file"); vs.add_argument("--content-type", default="audio/webm")
    vts = vsp.add_parser("tts"); vts.add_argument("text"); vts.add_argument("--provider", default=None); vts.add_argument("--voice", default=None); vts.add_argument("--format", default="mp3"); vts.add_argument("--speed", type=float, default=None); vts.add_argument("--stability", type=float, default=None); vts.add_argument("--similarity-boost", dest="similarity_boost", type=float, default=None); vts.add_argument("--style", type=float, default=None); vts.add_argument("--use-speaker-boost", dest="use_speaker_boost", action="store_true"); vts.add_argument("--out", default=None)
    vp = vsp.add_parser("ptt"); vp.add_argument("file"); vp.add_argument("--content-type", default="audio/webm"); vp.add_argument("--session-id", default=None); vp.add_argument("--wake-word", default=None); vp.add_argument("--speak", action="store_true"); vp.add_argument("--tts-provider", default=None); vp.add_argument("--tts-voice", default=None); vp.add_argument("--tts-format", default="mp3")

    call = sp.add_parser("call")
    call.add_argument("method", choices=["GET", "POST", "PATCH", "DELETE"])
    call.add_argument("path")
    call.add_argument("--query", action="append", default=[])
    call.add_argument("--json", default=None)
    call.add_argument("--file", default=None)
    call.add_argument("--no-auth", action="store_true")
    call.add_argument("--stream", action="store_true")
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if hasattr(args, "command_alias"):
        args.command = "auth"
        args.auth_cmd = args.command_alias
    store = AuthStore()
    client = Client(
        args.base_url,
        args.token or store.token(),
        args.pretty,
        store,
        idempotency_key=args.idempotency_key,
    )

    try:
        if args.command == "auth":
            cmd_auth(args, client)
        elif args.command == "chat":
            cmd_chat(args, client)
        elif args.command == "ask":
            cmd_ask(args, client)
        elif args.command in {"followup", "sessions", "status", "metrics", "doctor", "ops", "skills"}:
            if args.command == "metrics" and args.metrics_cmd == "prometheus":
                r = client.req("GET", "/api/metrics/prometheus")
                if r.status_code >= 400:
                    raise CliError(f"{r.status_code} /api/metrics/prometheus: {r.text}")
                print(r.text)
            else:
                cmd_simple(args, client)
        elif args.command == "config":
            cmd_config(args, client)
        elif args.command == "memory":
            cmd_memory(args, client)
        elif args.command == "workflow":
            cmd_workflow(args, client)
        elif args.command == "security":
            cmd_security(args, client)
        elif args.command == "automation":
            cmd_automation(args, client)
        elif args.command == "batch":
            cmd_batch(args, client)
        elif args.command == "voice":
            cmd_voice(args, client)
        elif args.command == "call":
            cmd_call(args, client)
        else:
            raise CliError(f"unsupported command: {args.command}")
    except CliError as exc:
        _print({"status": "error", "error": str(exc)}, pretty=args.pretty)
        return 2
    except Exception as exc:  # pragma: no cover
        _print({"status": "error", "error": str(exc)}, pretty=args.pretty)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
