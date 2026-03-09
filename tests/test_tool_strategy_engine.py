from gateway.tool_strategy import ToolStrategyEngine


def test_strategy_prefers_browser_for_download_page_intent():
    engine = ToolStrategyEngine()
    catalog = [
        {
            "tool_type": "mcp",
            "service_name": "computer_control",
            "tool_name": "browser_action",
            "description": "browser goto click type",
        },
        {
            "tool_type": "mcp",
            "service_name": "computer_control",
            "tool_name": "fs_action",
            "description": "filesystem read write list",
        },
    ]
    out = engine.recommend(
        step={"goal": "open website and click download"},
        user_message="Go to the download page in browser",
        observations=[],
        catalog=catalog,
        strategy_hints={},
    )
    assert out["use_tool"] is True
    assert out["service_name"] == "computer_control"
    assert out["tool_name"] == "browser_action"


def test_strategy_prefers_filesystem_for_save_to_folder_intent():
    engine = ToolStrategyEngine()
    catalog = [
        {
            "tool_type": "mcp",
            "service_name": "computer_control",
            "tool_name": "process_action",
            "description": "run process launch app",
        },
        {
            "tool_type": "mcp",
            "service_name": "computer_control",
            "tool_name": "fs_action",
            "description": "filesystem read write list",
        },
    ]
    out = engine.recommend(
        step={"goal": "save torrent file to target folder"},
        user_message="Save file into a directory and verify path exists",
        observations=[],
        catalog=catalog,
        strategy_hints={},
    )
    assert out["use_tool"] is True
    assert out["tool_name"] == "fs_action"


def test_strategy_prefers_unified_content_action_for_fetch_intent():
    engine = ToolStrategyEngine()
    catalog = [
        {
            "tool_type": "mcp",
            "service_name": "content_tools",
            "tool_name": "web_fetch",
            "description": "fetch and parse web pages",
        },
        {
            "tool_type": "mcp",
            "service_name": "computer_control",
            "tool_name": "content_action",
            "description": "unified content operations",
        },
    ]
    out = engine.recommend(
        step={"goal": "fetch webpage content"},
        user_message="Fetch this web page and parse PDF details",
        observations=[],
        catalog=catalog,
        strategy_hints={},
    )
    assert out["use_tool"] is True
    assert out["service_name"] == "computer_control"
    assert out["tool_name"] == "content_action"


def test_strategy_uses_runtime_quality_hint_to_prefer_more_reliable_tool():
    engine = ToolStrategyEngine()
    catalog = [
        {
            "tool_type": "mcp",
            "service_name": "computer_control",
            "tool_name": "browser_action",
            "description": "open website click button",
        },
        {
            "tool_type": "mcp",
            "service_name": "computer_control",
            "tool_name": "perception_action",
            "description": "observe and click on screen with OCR",
        },
    ]
    out = engine.recommend(
        step={"goal": "open website and click login button"},
        user_message="Open website and click the login button",
        observations=[],
        catalog=catalog,
        strategy_hints={
            "tool_quality": [
                {
                    "service_name": "computer_control",
                    "tool_name": "browser_action",
                    "runs": 10,
                    "success_rate": 0.9,
                },
                {
                    "service_name": "computer_control",
                    "tool_name": "perception_action",
                    "runs": 10,
                    "success_rate": 0.2,
                },
            ]
        },
    )
    assert out["use_tool"] is True
    assert out["tool_name"] == "browser_action"


def test_strategy_avoids_high_risk_tool_without_explicit_dangerous_intent():
    engine = ToolStrategyEngine()
    catalog = [
        {
            "tool_type": "mcp",
            "service_name": "computer_control",
            "tool_name": "execute_command",
            "description": "run shell command",
        },
        {
            "tool_type": "mcp",
            "service_name": "computer_control",
            "tool_name": "browser_action",
            "description": "open url in browser",
        },
    ]
    out = engine.recommend(
        step={"goal": "open official website homepage"},
        user_message="Open the official website homepage",
        observations=[],
        catalog=catalog,
        strategy_hints={},
    )
    assert out["use_tool"] is True
    assert out["tool_name"] == "browser_action"
