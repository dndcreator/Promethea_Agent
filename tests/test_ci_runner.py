"""CI must expose real failure causes, including failed collection and timeout."""
import json
import io
from pathlib import Path
import subprocess

import pytest

from tests import run_all_tests


@pytest.mark.parametrize("failure", ["collection", "timeout", "malformed_junit"])
def test_runner_keeps_failure_reason_and_nonzero_exit(monkeypatch, tmp_path, capsys, failure):
    def execute(command, **kwargs):
        kwargs["stdout"].write("ROOT CAUSE: missing test dependency\n")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        xml = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        xml.write_text("bad XML" if failure == "malformed_junit" else '<testsuite><testcase name="collection"><error message="missing dependency"/></testcase></testsuite>')
        return 2
    monkeypatch.setattr(run_all_tests, "run_bounded", execute)
    output = tmp_path / "report"
    assert run_all_tests.main(["--file", "test_request_validation.py", "--output", str(output)]) == 1
    assert "ROOT CAUSE: missing test dependency" in capsys.readouterr().out
    report = json.loads((output / "summary.json").read_text())
    assert not report["passed"]
    assert report["runs"][0]["failure_kind"] == ("timeout" if failure == "timeout" else "collection_or_interrupt")
    if failure == "malformed_junit":
        assert report["runs"][0]["error"].startswith("Invalid JUnit")


def test_gold_groups_cover_distinct_risks_not_only_happy_paths():
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "tests/evaluation/behavior.json").read_text(encoding="utf-8"))["cases"]
    groups = {case["group"] for case in cases}
    assert groups == {"action", "memory", "retrieval", "situation", "ambient", "continuity", "delegation"}
    for group in groups:
        selected = [case for case in cases if case["group"] == group]
        assert 5 <= len(selected) <= 10
        assert {case["category"] for case in selected} == {"positive", "negative", "boundary", "historical_failure"}
        assert all(case.get("expect") and case.get("oracle_basis") for case in selected)


def test_unencodable_console_failure_still_preserves_report(monkeypatch, tmp_path):
    def execute(command, **kwargs):
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
        kwargs["stdout"].write("ROOT CAUSE: \u2603 \ufffd\n")
        xml = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        xml.write_text('<testsuite><testcase name="broken"><failure message="real failure"/></testcase></testsuite>')
        return 1

    monkeypatch.setattr(run_all_tests, "run_bounded", execute)
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="gbk", errors="strict")
    output = tmp_path / "report"
    with monkeypatch.context() as patch:
        patch.setattr(run_all_tests.sys, "stdout", console)
        assert run_all_tests.main(["--file", "test_request_validation.py", "--output", str(output)]) == 1
    console.flush()
    assert b'ROOT CAUSE:' in raw.getvalue()
    report = json.loads((output / "summary.json").read_text())
    assert not report["passed"] and report["runs"][0]["failure_kind"] == "test_failure"
