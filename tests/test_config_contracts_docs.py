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
