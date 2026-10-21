"""Keep local Runtime data out of Git without hiding distributable sources."""

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not (ROOT / ".git").exists(),
    reason="repository hygiene checks require a Git checkout",
)


def ignored(paths):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"],
        input="\0".join(paths) + "\0", cwd=ROOT, text=True,
        encoding="utf-8", capture_output=True, check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    return set(result.stdout.rstrip("\0").split("\0")) if result.stdout else set()


def test_runtime_and_build_outputs_are_ignored():
    paths = [
        ".env", ".env.production", "UI/.env.development.local", "config.json",
        "config/users/example/identity.sqlite3", "config/users/example/secrets.env",
        "config/users/identity.sqlite3-wal", "workspace/example/document.pdf",
        "brain/basal_ganglia/moirai_learning/learning.sqlite3",
        "memory/sqlite_graph.db", "memory/sqlite_graph.db-wal",
        "memory/sqlite_graph.db-shm", "memory/test.sqlite-journal",
        "memory/test.sqlite3-wal", "memory/raw_log.jsonl", "memory/raw_log.state.json",
        "memory/raw_log.state.json.123.tmp", "memory/node_store.json",
        "memory/moirai_runs/checkpoint.json", "memory/migrations/generation.json",
        "memory/hippocampus/replay_state.json", "logs/app.log.zip",
        "gateway/sessions.json", "gateway/sessions.json.corrupt.123",
        "gateway/sessions.json.tmp123", "gateway/.task_state.json.123.tmp",
        "gateway/runtime_events.jsonl.state.json.tmp", ".promethea/environments.json",
        "workspace/example/.promethea/downloads/attachment.pdf",
        "extensions/community/_generated/example/tool.py", ".runtime/self-evolve/task.py",
        ".tmp/pytest-runtime/cases/data.json", "UI/node_modules/example/index.js",
        "UI/dist/index.html", "sdk/typescript/dist/index.js", "target/debug/promethea",
        "src-tauri/target/debug/promethea", "UI/tsconfig.tsbuildinfo", ".coverage.worker",
    ]
    assert ignored(paths) == set(paths)


def test_sources_contracts_assets_and_examples_remain_visible():
    paths = [
        "config.py", "config/default.json", "env.example", ".env.example",
        "UI/.env.example", "UI/package-lock.json", "sdk/typescript/package-lock.json",
        "Cargo.lock", "gateway/public_contracts.py", "contracts/runtime-v1.schema.json",
        "agentkit/tools/moirai/learning.py", "extensions/community/example/tool.py",
        "skills/packs/official/coding_copilot/skill.yaml",
        "docs/assets/screenshots/01-ui-overview.png", "benchmarks/general_capability_tasks.json",
    ]
    assert ignored(paths) == set()


def test_no_tracked_files_match_local_only_rules():
    result = subprocess.run(
        ["git", "ls-files", "-ci", "--exclude-standard"], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    assert not result.stdout.strip(), "Tracked local-only files must be removed from the Git index"
