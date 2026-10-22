from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from gateway.http.schemas import ChatRequest, ChatResponse
from gateway.public_contracts import RunRequest, RunResponse
from scripts.generate_public_contracts import generated_artifacts


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("stale", [False, True])
def test_generator_checks_real_artifacts_without_runtime_dependencies(tmp_path, stale):
    script = textwrap.dedent('''
        import importlib.abc
        from pathlib import Path
        import sys

        sys.path.insert(0, sys.argv[1])
        blocked = {"psutil", "playwright", "pyautogui", "fastapi", "neo4j", "openai", "mcp"}

        class NoRuntimeDependencies(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split(".")[0] in blocked:
                    raise ModuleNotFoundError(f"Runtime dependency unavailable: {fullname}", name=fullname)

        sys.meta_path.insert(0, NoRuntimeDependencies())
        from scripts import generate_public_contracts as generator

        if sys.argv[2] == "stale":
            generator.SDK_TYPESCRIPT_PATH = Path(sys.argv[3])
        sys.argv = [generator.__file__, "--check"]
        result = generator.main()
        assert not any(name.split(".")[0] in blocked for name in sys.modules)
        assert not any(name in sys.modules for name in (
            "computer.browser", "computer.browser_runtime", "computer.screen",
            "computer.filesystem", "computer.process", "computer.environment",
        ))
        raise SystemExit(result)
    ''')
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(ROOT), "stale" if stale else "current", str(tmp_path / "missing.ts")],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == (1 if stale else 0), result.stdout + result.stderr
    if stale:
        assert "stale generated contract:" in result.stdout
        assert "missing.ts" in result.stdout
    else:
        assert "Traceback" not in result.stderr


def test_generated_contract_artifacts_are_current():
    for path, expected in generated_artifacts().items():
        assert path.exists(), f"missing generated contract: {path.relative_to(ROOT)}"
        assert path.read_text(encoding="utf-8") == expected, (
            f"stale generated contract: {path.relative_to(ROOT)}; "
            "run scripts/generate_public_contracts.py"
        )


def test_http_run_models_add_no_second_protocol_shape():
    assert ChatRequest.model_fields.keys() == RunRequest.model_fields.keys()
    assert ChatResponse.model_fields.keys() == RunResponse.model_fields.keys()


def test_typescript_api_uses_sdk_exported_generated_types():
    source = (ROOT / "UI" / "src" / "services" / "api.ts").read_text(encoding="utf-8")
    sdk_index = (ROOT / "sdk" / "typescript" / "src" / "index.ts").read_text(encoding="utf-8")

    assert "from '@promethea/sdk'" in source
    assert "from './generated/public-contracts.js'" in sdk_index
    assert "Attachment," in sdk_index
    assert "RunRequest," in sdk_index
    assert "const runRequest: RunRequest" in source
    assert "export type ChatAttachment = Attachment & { file_id: string }" in source
    assert "export type ChatAttachment = {" not in source
