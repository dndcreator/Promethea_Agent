from gateway.protocol_contracts import build_domain_contracts, build_ws_method_contracts


def test_ws_method_contracts_include_config_update_aliases():
    rows = build_ws_method_contracts()
    cfg = next(row for row in rows if row["method"] == "config.update")
    assert cfg["stability"] == "stable"
    assert cfg["params_model"] == "ConfigUpdateParams"
    assert cfg["aliases"]["config_data"] == "config"
    assert cfg["aliases"]["hot_reload"] == "options.hot_apply"


def test_ws_method_contracts_cover_chat_and_workflow():
    rows = build_ws_method_contracts()
    methods = {row["method"] for row in rows}
    assert "chat" in methods
    assert "workflow.start" in methods
    assert "memory.query" in methods


def test_domain_contracts_publish_core_domains():
    domains = build_domain_contracts()
    assert "config" in domains
    assert "memory" in domains
    assert "workflow" in domains
    assert "ops" in domains
    assert "/api/config/update" in domains["config"]["http"]
    assert "/api/ops/governance" in domains["ops"]["http"]
