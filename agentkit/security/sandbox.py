from __future__ import annotations

import ipaddress
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import urlparse


DEFAULT_DENY_FRAGMENTS = [
    "rm -rf",
    "del /f /q",
    "format ",
    "shutdown",
    "reboot",
    "mkfs",
    "diskpart",
    "net user",
    "reg add",
]

DEFAULT_ALLOW_COMMANDS = [
    "python",
    "pytest",
    "pip",
    "uv",
    "git",
    "rg",
    "cmd",
    "powershell",
]

WRITE_INTENTS = {"write", "edit", "patch", "delete", "move", "copy", "mkdir"}


@dataclass
class SandboxDecision:
    allowed: bool
    reason: str


class SandboxPolicy:
    """Non-Docker sandbox policy: workspace + command + network guardrails."""

    def __init__(
        self,
        *,
        enabled: bool,
        profile: str,
        workspace_access: str,
        command_mode: str,
        allowed_commands: Optional[Iterable[str]] = None,
        deny_fragments: Optional[Iterable[str]] = None,
        network_mode: str = "restricted",
        allowed_domains: Optional[Iterable[str]] = None,
        block_private_network: bool = True,
    ) -> None:
        self.enabled = bool(enabled)
        self.profile = str(profile or "off").strip().lower()
        self.workspace_access = str(workspace_access or "rw").strip().lower()
        self.command_mode = str(command_mode or "allowlist").strip().lower()
        self.allowed_commands = {str(x).strip().lower() for x in (allowed_commands or DEFAULT_ALLOW_COMMANDS) if str(x).strip()}
        self.deny_fragments = [str(x).strip().lower() for x in (deny_fragments or DEFAULT_DENY_FRAGMENTS) if str(x).strip()]
        self.network_mode = str(network_mode or "restricted").strip().lower()
        self.allowed_domains = [str(x).strip().lower() for x in (allowed_domains or []) if str(x).strip()]
        self.block_private_network = bool(block_private_network)

    @classmethod
    def from_global_config(cls) -> "SandboxPolicy":
        try:
            from config import config

            cfg = (config.model_dump() if hasattr(config, "model_dump") else {})
            sb = cfg.get("sandbox", {}) if isinstance(cfg, dict) else {}
        except Exception:
            sb = {}

        return cls(
            enabled=bool(sb.get("enabled", False)),
            profile=str(sb.get("profile", "off")),
            workspace_access=str(sb.get("workspace_access", "rw")),
            command_mode=str(sb.get("command_mode", "allowlist")),
            allowed_commands=sb.get("allowed_commands") or DEFAULT_ALLOW_COMMANDS,
            deny_fragments=sb.get("deny_fragments") or DEFAULT_DENY_FRAGMENTS,
            network_mode=str(sb.get("network_mode", "restricted")),
            allowed_domains=sb.get("allowed_domains") or [],
            block_private_network=bool(sb.get("block_private_network", True)),
        )

    def is_enforced(self) -> bool:
        return self.enabled and self.profile != "off"

    def check_path(self, path: str, *, intent: str = "read", workspace_root: Optional[Path] = None) -> SandboxDecision:
        if not self.is_enforced():
            return SandboxDecision(True, "sandbox disabled")

        root = (workspace_root or Path.cwd()).resolve()
        p = Path(path)
        if not p.is_absolute():
            p = root / p
        p = p.resolve()

        try:
            p.relative_to(root)
        except ValueError:
            return SandboxDecision(False, f"path outside workspace: {p}")

        if self.workspace_access == "none":
            return SandboxDecision(False, "workspace access is none")

        normalized_intent = str(intent or "read").strip().lower()
        if self.workspace_access == "ro" and normalized_intent in WRITE_INTENTS:
            return SandboxDecision(False, f"workspace is read-only for intent: {normalized_intent}")

        return SandboxDecision(True, "path allowed")

    def check_command(self, command: str, *, cwd: str = ".", workspace_root: Optional[Path] = None) -> SandboxDecision:
        if not self.is_enforced():
            return SandboxDecision(True, "sandbox disabled")

        cmd = str(command or "").strip()
        if not cmd:
            return SandboxDecision(False, "empty command")

        path_decision = self.check_path(cwd, intent="read", workspace_root=workspace_root)
        if not path_decision.allowed:
            return path_decision

        lower_cmd = cmd.lower()
        for frag in self.deny_fragments:
            if frag in lower_cmd:
                return SandboxDecision(False, f"command contains denied fragment: {frag}")

        first = self._extract_first_token(cmd)
        if not first:
            return SandboxDecision(False, "cannot parse command token")

        if self.command_mode == "allowlist" and first not in self.allowed_commands:
            return SandboxDecision(False, f"command not in allowlist: {first}")

        return SandboxDecision(True, "command allowed")

    def check_url(self, url: str) -> SandboxDecision:
        if not self.is_enforced():
            return SandboxDecision(True, "sandbox disabled")

        parsed = urlparse(str(url or "").strip())
        if parsed.scheme not in {"http", "https"}:
            return SandboxDecision(False, f"unsupported url scheme: {parsed.scheme or 'unknown'}")

        host = (parsed.hostname or "").strip().lower()
        if not host:
            return SandboxDecision(False, "url host missing")

        if self.network_mode == "none":
            return SandboxDecision(False, "network mode is none")

        if self.block_private_network and self._is_private_host(host):
            return SandboxDecision(False, f"private/loopback host blocked: {host}")

        if self.allowed_domains and not self._domain_allowed(host):
            return SandboxDecision(False, f"host not in allowed_domains: {host}")

        return SandboxDecision(True, "url allowed")

    def _domain_allowed(self, host: str) -> bool:
        for domain in self.allowed_domains:
            d = domain.lstrip(".")
            if host == d or host.endswith("." + d):
                return True
        return False

    def _is_private_host(self, host: str) -> bool:
        if host in {"localhost", "127.0.0.1", "::1"}:
            return True
        try:
            ip = ipaddress.ip_address(host)
            return ip.is_private or ip.is_loopback or ip.is_link_local
        except ValueError:
            return False

    def _extract_first_token(self, command: str) -> str:
        try:
            parts: List[str] = shlex.split(command, posix=False)
        except Exception:
            parts = str(command).split()
        if not parts:
            return ""
        token = parts[0].strip().strip('"').strip("'")
        token = token.replace("\\", "/").split("/")[-1]
        return token.lower()


_SANDBOX_POLICY: Optional[SandboxPolicy] = None


def get_sandbox_policy() -> SandboxPolicy:
    global _SANDBOX_POLICY
    if _SANDBOX_POLICY is None:
        _SANDBOX_POLICY = SandboxPolicy.from_global_config()
    return _SANDBOX_POLICY


def reload_sandbox_policy() -> SandboxPolicy:
    global _SANDBOX_POLICY
    _SANDBOX_POLICY = SandboxPolicy.from_global_config()
    return _SANDBOX_POLICY
