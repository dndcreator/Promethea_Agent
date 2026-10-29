"""Static test inventory. Findings are review candidates, never deletion rules."""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def inventory(root=ROOT):
    files, fingerprints = [], defaultdict(list)
    for path in sorted((root / "tests").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        tests = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")]
        calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
        owners = sorted({node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in {"gateway", "memory", "computer", "core", "agentkit", "channels"}})
        weak = []
        for node in tests:
            assertions = [item for item in ast.walk(node) if isinstance(item, ast.Assert)]
            checks = [ast.unparse(item.func) for item in ast.walk(node) if isinstance(item, ast.Call)]
            if not assertions and not any("assert" in call.lower() or "raises" in call or "expect" in call for call in checks):
                weak.append(node.name)
            body = ast.FunctionDef(name="test", args=node.args, body=node.body, decorator_list=[])
            digest = hashlib.sha256(ast.dump(body, include_attributes=False).encode()).hexdigest()
            fingerprints[digest].append(f"{path.relative_to(root).as_posix()}::{node.name}")
        files.append({"path": path.relative_to(root).as_posix(), "definitions": len(tests), "owners": owners,
                      "mock_calls": sum("Mock" in call or "patch" in call for call in calls),
                      "assertion_review": weak, "disposition": "retain unless specifically reviewed"})
    return {"schema_version": 1, "scope": "Python test definitions, not parametrized collected cases or coverage",
            "files": files, "definitions": sum(row["definitions"] for row in files),
            "exact_duplicate_candidates": [rows for rows in fingerprints.values() if len(rows) > 1],
            "other_assets": {folder: sorted(path.relative_to(root).as_posix() for path in (root / folder).rglob("*.test.mjs")) for folder in ("UI/tests", "sdk/typescript/tests")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = inventory()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(report["files"]), "definitions": report["definitions"],
                      "assertion_review": [row for row in report["files"] if row["assertion_review"]],
                      "exact_duplicate_candidates": report["exact_duplicate_candidates"]}, indent=2))


if __name__ == "__main__":
    main()
