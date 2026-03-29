from gateway.http.http_contracts import build_http_contracts, index_http_contracts
from gateway.http.surface_discovery import collect_http_surface_from_routes


def test_http_contract_registry_contains_core_endpoints():
    contracts = build_http_contracts()
    indexed = index_http_contracts(contracts)
    assert "config.update" in indexed
    assert "ops.protocol" in indexed
    assert "ops.http_contracts" in indexed
    assert indexed["config.update"]["path"] == "/api/config/update"
    assert indexed["ops.http_contracts"]["path"] == "/api/ops/http-contracts"


def test_http_contract_registry_marks_expected_stability_levels():
    contracts = build_http_contracts()
    stability = {item["id"]: item["stability"] for item in contracts}
    assert stability["config.update"] == "stable"
    assert stability["ops.surfaces"] == "stable"


def test_http_contract_registry_can_cover_runtime_surface_routes():
    fake_routes = [
        type("R", (), {"path": "/api/chat", "methods": {"POST", "OPTIONS"}, "name": "chat"}),
        type("R", (), {"path": "/api/custom/feature", "methods": {"GET"}, "name": "custom"}),
    ]
    contracts = build_http_contracts(routes=fake_routes)
    by_path_method = {(c["path"], c["method"]) for c in contracts}
    assert ("/api/chat", "POST") in by_path_method
    assert ("/api/custom/feature", "GET") in by_path_method


def test_http_contract_registry_covers_all_registered_api_routes():
    from gateway.app import app

    surface = collect_http_surface_from_routes(app.routes)
    contracts = build_http_contracts(routes=app.routes)

    surface_pairs = {(row["path"], method) for row in surface for method in (row.get("methods") or [])}
    contract_pairs = {(row["path"], row["method"]) for row in contracts}

    missing = sorted(surface_pairs - contract_pairs)
    assert missing == []
