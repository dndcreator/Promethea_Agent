from pathlib import Path

from agentkit.security.sandbox import SandboxPolicy


def test_sandbox_blocks_write_when_workspace_read_only():
    policy = SandboxPolicy(
        enabled=True,
        profile="strict",
        workspace_access="ro",
        command_mode="allowlist",
        allowed_commands=["python"],
        network_mode="restricted",
    )
    d = policy.check_path("a.txt", intent="write", workspace_root=Path.cwd())
    assert d.allowed is False


def test_sandbox_blocks_command_not_in_allowlist():
    policy = SandboxPolicy(
        enabled=True,
        profile="strict",
        workspace_access="rw",
        command_mode="allowlist",
        allowed_commands=["python"],
        network_mode="restricted",
    )
    d = policy.check_command("npm run test", cwd=".", workspace_root=Path.cwd())
    assert d.allowed is False


def test_sandbox_blocks_private_network_and_enforces_domain_allowlist():
    policy = SandboxPolicy(
        enabled=True,
        profile="strict",
        workspace_access="rw",
        command_mode="allowlist",
        allowed_commands=["python"],
        network_mode="restricted",
        allowed_domains=["example.com"],
        block_private_network=True,
    )
    blocked_private = policy.check_url("http://127.0.0.1:8000")
    assert blocked_private.allowed is False

    blocked_domain = policy.check_url("https://openai.com")
    assert blocked_domain.allowed is False

    allowed = policy.check_url("https://api.example.com/data")
    assert allowed.allowed is True
