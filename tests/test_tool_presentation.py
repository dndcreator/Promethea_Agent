import pytest

from agentkit.tools.standard.memory_tools import MemoryGetContextTool
from agentkit.tools.standard.web_tools import WebFetchTextTool
from gateway.tools.presentation import (
    project_tool_call,
    project_tool_result,
    validate_presentation_declaration,
)


def test_declarative_tool_presentation_projects_subject_and_reference():
    presentation = project_tool_call(
        WebFetchTextTool(),
        {"url": "https://example.com/article"},
    )

    assert presentation["title_i18n"]["zh"] == "读取网页"
    assert presentation["subject"] == "https://example.com/article"
    assert presentation["references"] == [{
        "kind": "url",
        "target": "https://example.com/article",
        "label": "https://example.com/article",
        "metadata": {},
    }]


def test_result_presentation_preserves_call_identity():
    tool = MemoryGetContextTool(memory_service=object())
    call = project_tool_call(tool, {"query": "preferred writing style"})
    result = project_tool_result(
        tool,
        {"query": "preferred writing style"},
        {"context": "The user prefers concise sentences."},
        call_presentation=call,
    )

    assert result["title"] == "Recall memory"
    assert result["subject"] == "preferred writing style"
    assert result["references"][0]["kind"] == "memory"


def test_undeclared_tool_uses_description_as_readable_fallback():
    class DemoTool:
        description = "Read the current project status. Internal details follow."

    assert project_tool_call(DemoTool(), {})["title"] == "Read the current project status"


def test_presentation_declaration_rejects_unknown_fields_and_incomplete_references():
    with pytest.raises(ValueError):
        validate_presentation_declaration({"title": "Read", "frontend_component": "CustomCard"})
    with pytest.raises(ValueError, match="requires arg or target"):
        validate_presentation_declaration({"title": "Read", "references": [{"kind": "url"}]})
