from datetime import datetime, timezone

from gateway.runtime_context import build_runtime_clock
from gateway.temporal import (
    next_run_at,
    normalize_trigger,
    resolve_context_timezone_name,
    resolve_timezone_name,
)


def test_timezone_resolution_prefers_user_config_over_host():
    assert resolve_timezone_name({"system": {"timezone": "Europe/Paris"}}) == "Europe/Paris"
    assert build_runtime_clock(user_config={"system": {"timezone": "UTC"}})["timezone"] == "UTC"


def test_runtime_timezone_uses_client_only_when_user_setting_is_auto():
    assert resolve_context_timezone_name(
        {"system": {"timezone": "Europe/Paris"}},
        "Asia/Shanghai",
    ) == "Europe/Paris"
    assert resolve_context_timezone_name(
        {"system": {"timezone": "auto"}},
        "Asia/Shanghai",
    ) == "Asia/Shanghai"
    assert build_runtime_clock(
        timezone_name="Asia/Shanghai",
        user_config={"system": {"timezone": "auto"}},
    )["timezone"] == "Asia/Shanghai"


def test_at_trigger_converts_local_time_to_utc():
    trigger = normalize_trigger(
        {"type": "at", "at": "2026-09-28T09:00:00"},
        timezone_name="Asia/Shanghai",
        now_ts=0,
    )
    assert trigger["at"] == "2026-09-28T01:00:00Z"


def test_calendar_trigger_calculates_weekday_in_selected_timezone():
    friday = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc).timestamp()
    trigger = normalize_trigger(
        {"type": "calendar", "time": "09:30", "weekdays": [0]},
        timezone_name="UTC",
        now_ts=friday,
    )
    next_at = next_run_at(trigger, after_ts=friday, timezone_name="UTC")
    assert datetime.fromtimestamp(next_at, timezone.utc).isoformat() == "2026-10-05T09:30:00+00:00"


def test_interval_trigger_preserves_phase_after_missed_runs():
    trigger = {"type": "interval", "seconds": 60, "anchor_at": 100.0}
    assert next_run_at(trigger, after_ts=281.0, timezone_name="UTC") == 340.0
