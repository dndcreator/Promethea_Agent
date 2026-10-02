from gateway.http.schemas import ChatRequest, ChatResponse
from gateway.http.surface_discovery import build_surface_payload
from gateway.protocol import GatewayProtocol
from gateway.public_contracts import build_public_contract_schema
from gateway.public_views import public_task, public_workbench


def test_public_contract_schema_contains_only_external_objects():
    schema = build_public_contract_schema()

    assert schema["version"] == "1.0"
    assert {
        "RunRequest",
        "RunResponse",
        "Session",
        "Event",
        "ToolCall",
        "ToolResult",
        "Error",
    }.issubset(schema["$defs"])
    serialized = str(schema)
    assert "RunContext" not in serialized
    assert "tool_executor" not in serialized


def test_public_task_view_hides_runtime_execution_ownership():
    task = public_task({
        "task_id": "task_1",
        "title": "Demo",
        "status": "running",
        "revision": 2,
        "executions": {"run_1": {"owner_id": "runtime", "lease_token": "secret"}},
        "runs": [{
            "run_id": "run_1",
            "run_type": "workflow",
            "status": "running",
            "attempts": [{"attempt_id": "attempt_1", "owner_id": "runtime"}],
            "metadata": {"execution_token": "internal"},
        }],
    })

    assert task is not None
    assert "executions" not in task
    assert task["runs"][0]["attempt_count"] == 1
    assert "attempts" not in task["runs"][0]
    assert "metadata" not in task["runs"][0]


def test_public_workbench_summarizes_internal_service_records():
    snapshot = public_workbench({
        "task": None,
        "tasks": [],
        "runs": [],
        "workflow_runs": [{
            "workflow_run_id": "wr1",
            "workflow_id": "research",
            "status": "running",
            "active_attempt_id": "attempt-secret",
            "idempotency_key": "internal-key",
            "current_step": {
                "step_id": "search",
                "name": "Search sources",
                "status": "running",
                "attempt_count": 1,
                "retry_policy": {"max_attempts": 3},
            },
        }],
        "recovery_items": [],
        "memory_proposals": [{
            "proposal_id": "p1",
            "status": "pending",
            "memory_type": "semantic",
            "content": "private memory text",
            "conflict_candidates": [{"content": "private conflict text"}],
        }],
        "recall_runs": [{
            "request_id": "recall1",
            "query_text": "writing preference",
            "memory_records": [{"content": "private recalled memory"}],
            "dropped_candidates": [{"content": "private dropped memory"}],
        }],
    })

    workflow = snapshot["workflow_runs"][0]
    assert workflow["current_step"]["name"] == "Search sources"
    assert "active_attempt_id" not in workflow
    assert "idempotency_key" not in workflow
    assert "retry_policy" not in workflow["current_step"]
    assert snapshot["memory_proposals"][0]["conflict_count"] == 1
    assert "content" not in snapshot["memory_proposals"][0]
    assert snapshot["recall_runs"][0]["selected_count"] == 1
    assert snapshot["recall_runs"][0]["dropped_count"] == 1
    assert "memory_records" not in snapshot["recall_runs"][0]


def test_http_chat_models_reuse_public_run_contracts():
    request = ChatRequest(message="hello", requested_workflow="research")
    response = ChatResponse(response="world", status="completed")

    assert request.requested_workflow == "research"
    assert response.response == "world"
    assert response.status == "completed"


def test_gateway_response_adds_structured_error_without_removing_legacy_error():
    response = GatewayProtocol.create_response(
        "req-1",
        False,
        payload={
            "error_detail": {
                "code": "service_unavailable",
                "message": "tool service unavailable",
                "retryable": True,
                "dependency": "capability_service",
            }
        },
        error="tool service unavailable",
    )

    assert response.error == "tool service unavailable"
    assert response.error_detail is not None
    assert response.error_detail.code == "service_unavailable"
    assert response.error_detail.dependency == "capability_service"


def test_surface_discovery_publishes_machine_readable_schemas():
    payload = build_surface_payload([])
    contracts = payload["surfaces"]["contracts"]

    assert contracts["openapi"] == "/openapi.json"
    assert contracts["public_schema"] == "/api/ops/schema"
