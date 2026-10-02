from agentkit.mcp.tool_result import normalize_tool_result
from computer.locations import SystemLocationRegistry


def test_legacy_uppercase_error_is_normalized_once_at_adapter_boundary():
    result = normalize_tool_result(
        "computer_control.fs_action",
        "ERROR: operation failed: Directory not found: missing",
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "FS_NOT_FOUND"
    assert result.error.retryable is True


def test_structured_success_does_not_depend_on_rendered_text():
    result = normalize_tool_result(
        "demo.tool",
        {"ok": True, "value": "text containing ERROR: as ordinary data"},
    )

    assert result.ok is True
    assert result.error is None


def test_system_location_registry_accepts_provider_defined_names(tmp_path):
    registry = SystemLocationRegistry(workspace_root=tmp_path)
    custom = tmp_path / "custom"
    registry.register("project_assets", lambda: custom)

    assert registry.resolve("project_assets") == custom
    assert registry.available_names() == ["project_assets"]
