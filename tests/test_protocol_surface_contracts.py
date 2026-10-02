from types import SimpleNamespace

from gateway.config_protocol import normalize_config_update_params
from gateway.http.surface_discovery import (
    build_surface_payload,
    collect_http_surface_from_routes,
)


def test_ws_config_update_normalization_accepts_canonical_shape():
    normalized = normalize_config_update_params(
        {
            "config": {"memory": {"enabled": False, "profile": "balanced"}},
            "options": {"hot_apply": "true"},
            "validate": "false",
        }
    )
    assert normalized["config"]["memory"]["enabled"] is False
    assert normalized["config"]["memory"]["profile"] == "balanced"
    assert normalized["hot_apply"] is True
    assert normalized["validate"] is False


def test_ws_config_update_normalization_respects_false_hot_apply():
    normalized = normalize_config_update_params(
        {
            "config": {"system": {"stream_mode": True}},
            "options": {"hot_apply": False},
        }
    )
    assert normalized["hot_apply"] is False


def test_collect_http_surface_filters_api_routes_and_methods():
    fake_routes = [
        SimpleNamespace(path="/health", methods={"GET"}, name="health"),
        SimpleNamespace(path="/api/chat", methods={"POST", "OPTIONS"}, name="chat"),
        SimpleNamespace(path="/api/status", methods={"GET", "HEAD"}, name="status"),
    ]
    fake_request = SimpleNamespace(app=SimpleNamespace(routes=fake_routes))

    rows = collect_http_surface_from_routes(fake_request.app.routes)
    assert [row["path"] for row in rows] == ["/api/chat", "/api/status"]
    assert rows[0]["methods"] == ["POST"]
    assert rows[0]["stability"] == "stable"
    assert rows[1]["methods"] == ["GET"]


def test_ops_surfaces_includes_contract_endpoints():
    fake_routes = [
        SimpleNamespace(path="/api/chat", methods={"POST", "OPTIONS"}, name="chat"),
        SimpleNamespace(path="/api/ops/surfaces", methods={"GET"}, name="ops_surfaces"),
    ]
    fake_request = SimpleNamespace(app=SimpleNamespace(routes=fake_routes))
    payload = build_surface_payload(fake_request.app.routes)
    assert payload["status"] == "success"
    assert payload["surfaces"]["contracts"]["protocol"] == "/api/ops/protocol"
    assert payload["surfaces"]["contracts"]["openapi"] == "/openapi.json"
    assert payload["surfaces"]["contracts"]["public_schema"] == "/api/ops/schema"
    assert payload["surfaces"]["contracts"]["http_contracts"] == "/api/ops/http-contracts"
    assert payload["surfaces"]["contracts"]["framework_check"] == "/api/ops/framework-check"
    assert payload["surfaces"]["contracts"]["readiness"] == "/api/ops/readiness"
    assert payload["surfaces"]["contracts"]["governance"] == "/api/ops/governance"
    assert payload["surfaces"]["contracts"]["config"] == "/api/config/contract"
    assert "stable" in payload["surfaces"]["stability_levels"]
    assert payload["surfaces"]["cli_reference"]["ops.surfaces"]["command"] == "promethea ops surfaces"
    assert payload["surfaces"]["cli_reference"]["ops.methods"]["http"] == "GET /api/ops/methods"
    assert payload["surfaces"]["cli_reference"]["ops.http_contracts"]["command"] == "promethea ops http-contracts"
    assert payload["surfaces"]["cli_reference"]["ops.readiness"]["http"] == "GET /api/ops/readiness"
    assert payload["surfaces"]["cli_reference"]["ops.governance"]["command"] == "promethea ops governance"


def test_collect_http_surface_marks_canonical_route_stable():
    fake_routes = [
        SimpleNamespace(path="/api/config/update", methods={"POST"}, name="config_update"),
    ]
    rows = collect_http_surface_from_routes(fake_routes)
    stability = {row["path"]: row["stability"] for row in rows}
    assert stability["/api/config/update"] == "stable"
