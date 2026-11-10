"""The live local-app driver only observes actual generated workspace artifacts."""
import json
from pathlib import Path
from io import StringIO

import pytest

from scripts.evaluate_capability_context import unapproved_effects
from scripts.evaluate_local_app import app_artifacts, interactive_approval


@pytest.mark.parametrize("answer,expected", [("approve wanted", "approve"), ("reject wanted", "reject"), ("approve other", None), ("", None)])
def test_interactive_approval_requires_explicit_decision_for_exact_id(monkeypatch, answer, expected):
    monkeypatch.setattr("sys.stdin", StringIO(answer + "\n"))
    assert interactive_approval({"tool_call_id": "wanted", "tool_name": "fixture.action", "args": {}}) == expected


def test_sensitive_audit_resolves_parameterized_effects_and_consumes_each_approval():
    spec = {"tool_name": "browser_action", "service_name": "computer_control", "metadata": {"side_effect_selector": {
        "parameter": "action", "default": "external_write", "groups": {"read_only": ["snapshot"]},
    }}}
    args = {"action": "record_press", "keys": ["ArrowUp"]}
    read = {"tool_spec": spec, "args": {"action": "snapshot"}}
    write = {"tool_spec": spec, "args": args}
    approved = {"tool_name": "computer_control.browser_action", "args": args, "decision": "approve"}
    assert unapproved_effects([read, write, write], [approved]) == ["computer_control.browser_action"]


def test_task_keeps_original_user_goal_and_assessor_checks_out_of_the_prompt():
    case = json.loads((Path(__file__).parent / "evaluation/local-todo-live.json").read_text(encoding="utf-8"))
    assert case["id"] == "todo" and len(case["independent_checks"]) == 6
    assert "workspace.write_file" not in case["goal"] and "localStorage" not in case["goal"]
    assert "file://" not in case["goal"]


def test_app_inventory_does_not_manufacture_files_or_include_private_runtime_data(tmp_path):
    workspace = tmp_path / "workspace"
    source = workspace / "owner" / "comparison-todo" / "app"
    source.mkdir(parents=True)
    (source / "index.html").write_text("actual generated artifact", encoding="utf-8")
    (source / "style.css").write_text("body {}", encoding="utf-8")
    (source / "secrets.json").write_text("private", encoding="utf-8")
    hidden = source / ".runtime"
    hidden.mkdir()
    (hidden / "internal.html").write_text("runtime", encoding="utf-8")
    before = {path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
    found = app_artifacts(tmp_path)
    assert {Path(row["path"]).name for row in found} == {"index.html", "style.css"}
    assert all(row["bytes"] > 0 and len(row["sha256"]) == 64 for row in found)
    assert before == {path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
