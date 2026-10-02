from pathlib import Path

from agentkit.security.sandbox import SandboxPolicy


def test_sandbox_defaults_fail_closed_for_unconfined_host_capabilities():
    policy = SandboxPolicy()

    assert policy.is_enforced() is True
    assert policy.check_command("python -V").allowed is False
    assert policy.check_desktop_action("screenshot").allowed is True
    assert policy.check_desktop_action("click").allowed is False
    assert policy.check_process_action("kill", managed=False).allowed is False
    assert policy.check_process_action("kill", managed=True).allowed is True


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


def test_explicit_host_control_does_not_disable_other_sandbox_boundaries():
    policy = SandboxPolicy(
        desktop_mode="host_control",
        process_mode="host_control",
        workspace_access="rw",
        command_mode="deny",
    )

    assert policy.check_desktop_action("click").allowed is True
    assert policy.check_process_action("terminate", managed=False).allowed is True
    assert policy.check_command("python -V").allowed is False
