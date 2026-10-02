from pathlib import Path

from gateway.http.schemas import ChatRequest, ChatResponse
from gateway.public_contracts import RunRequest, RunResponse
from scripts.generate_public_contracts import generated_artifacts


ROOT = Path(__file__).resolve().parents[1]


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
