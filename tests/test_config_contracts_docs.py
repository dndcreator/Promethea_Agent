import pytest

from config import APIConfig, MemoryConfig, ReasoningConfig, SandboxConfig


def test_api_failover_models_parses_comma_separated_string():
    cfg = APIConfig(failover_models="gpt-4.1-mini,gpt-4o-mini")
    assert cfg.failover_models == ["gpt-4.1-mini", "gpt-4o-mini"]


def test_api_failover_models_parses_json_array_string():
    cfg = APIConfig(failover_models='["gpt-4.1-mini", "gpt-4o-mini"]')
    assert cfg.failover_models == ["gpt-4.1-mini", "gpt-4o-mini"]


def test_memory_store_backend_rejects_unsupported_value():
    with pytest.raises(ValueError):
        MemoryConfig(store_backend="redis")


def test_reasoning_mode_rejects_non_react_tot():
    with pytest.raises(ValueError):
        ReasoningConfig(mode="deep")


@pytest.mark.parametrize("profile", ["off", "dev", "strict"])
def test_sandbox_profile_accepts_documented_values(profile: str):
    cfg = SandboxConfig(profile=profile)
    assert cfg.profile == profile


def test_sandbox_defaults_to_restricted_host_access():
    cfg = SandboxConfig()
    assert cfg.enabled is True
    assert cfg.profile == "strict"
    assert cfg.command_mode == "approval"
    assert cfg.desktop_mode == "approval"
    assert cfg.process_mode == "managed_only"
    assert cfg.browser_disable_chromium_sandbox is False


@pytest.mark.parametrize("mode", ["observe_only", "approval", "host_control"])
def test_sandbox_desktop_mode_accepts_documented_values(mode: str):
    assert SandboxConfig(desktop_mode=mode).desktop_mode == mode
