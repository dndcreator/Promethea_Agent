"""Timezone-aware primitives shared by prompts and durable scheduling."""

from __future__ import annotations

import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo


AUTO_TIMEZONE = "auto"
SYSTEM_TIMEZONE = "system"
UTC = timezone.utc
_CLOCK_TIME = re.compile(r"^(?P<hour>[01]\d|2[0-3]):(?P<minute>[0-5]\d)(?::(?P<second>[0-5]\d))?$")


def _timezone_object(timezone_name: str):
    if str(timezone_name).upper() == "UTC":
        return UTC
    try:
        return ZoneInfo(timezone_name)
    except Exception as zoneinfo_error:
        try:
            import pytz

            return pytz.timezone(timezone_name)
        except Exception:
            raise ValueError(f"unknown timezone: {timezone_name}") from zoneinfo_error


def resolve_timezone_name(user_config: Optional[Dict[str, Any]] = None, requested: str = "") -> str:
    config = user_config if isinstance(user_config, dict) else {}
    system = config.get("system") if isinstance(config.get("system"), dict) else {}
    candidate = str(requested or system.get("timezone") or AUTO_TIMEZONE).strip()
    if candidate and candidate.lower() not in {AUTO_TIMEZONE, SYSTEM_TIMEZONE}:
        _timezone_object(candidate)
        return candidate

    env_timezone = str(os.environ.get("TZ") or "").strip()
    if env_timezone:
        try:
            _timezone_object(env_timezone)
            return env_timezone
        except Exception:
            pass
    local_key = str(getattr(datetime.now().astimezone().tzinfo, "key", "") or "").strip()
    if local_key:
        try:
            _timezone_object(local_key)
            return local_key
        except Exception:
            pass
    return SYSTEM_TIMEZONE


def resolve_context_timezone_name(
    user_config: Optional[Dict[str, Any]] = None,
    client_timezone: str = "",
) -> str:
    """Resolve a run timezone, preferring an explicit user setting over client detection."""
    config = user_config if isinstance(user_config, dict) else {}
    system = config.get("system") if isinstance(config.get("system"), dict) else {}
    configured = str(system.get("timezone") or AUTO_TIMEZONE).strip()
    if configured and configured.lower() not in {AUTO_TIMEZONE, SYSTEM_TIMEZONE}:
        return resolve_timezone_name(requested=configured)
    if str(client_timezone or "").strip():
        return resolve_timezone_name(requested=client_timezone)
    return resolve_timezone_name(config)


def local_datetime(timestamp: Optional[float] = None, timezone_name: str = SYSTEM_TIMEZONE) -> datetime:
    instant = datetime.now(UTC) if timestamp is None else datetime.fromtimestamp(float(timestamp), UTC)
    if timezone_name == SYSTEM_TIMEZONE:
        return instant.astimezone()
    return instant.astimezone(_timezone_object(timezone_name))


def localize(naive: datetime, timezone_name: str) -> datetime:
    if naive.tzinfo is not None:
        return naive
    if timezone_name == SYSTEM_TIMEZONE:
        return naive.astimezone()
    zone = _timezone_object(timezone_name)
    localizer = getattr(zone, "localize", None)
    return localizer(naive) if callable(localizer) else naive.replace(tzinfo=zone)


def normalize_trigger(
    trigger: Optional[Dict[str, Any]],
    *,
    interval_seconds: Optional[int] = None,
    timezone_name: str,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    raw = dict(trigger or {})
    kind = str(raw.get("type") or ("interval" if interval_seconds is not None else "")).strip().lower()
    now = float(now_ts) if now_ts is not None else datetime.now(UTC).timestamp()
    if kind == "interval":
        seconds = int(raw.get("seconds") or interval_seconds or 0)
        if seconds <= 0:
            raise ValueError("interval trigger seconds must be > 0")
        return {"type": "interval", "seconds": seconds, "anchor_at": now}
    if kind == "at":
        value = str(raw.get("at") or "").strip()
        if not value:
            raise ValueError("at trigger requires an ISO datetime")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        resolved = localize(parsed, timezone_name)
        return {"type": "at", "at": resolved.astimezone(UTC).isoformat().replace("+00:00", "Z")}
    if kind == "calendar":
        clock = str(raw.get("time") or "").strip()
        if not _CLOCK_TIME.fullmatch(clock):
            raise ValueError("calendar trigger time must use HH:MM or HH:MM:SS")
        weekdays = raw.get("weekdays")
        if weekdays is None:
            normalized_weekdays = list(range(7))
        elif isinstance(weekdays, list):
            normalized_weekdays = sorted({int(value) for value in weekdays})
            if not normalized_weekdays or any(value < 0 or value > 6 for value in normalized_weekdays):
                raise ValueError("calendar weekdays must contain integers from 0 to 6")
        else:
            raise ValueError("calendar weekdays must be an array")
        return {"type": "calendar", "time": clock, "weekdays": normalized_weekdays}
    raise ValueError("trigger type must be interval, at, or calendar")


def next_run_at(trigger: Dict[str, Any], *, after_ts: float, timezone_name: str) -> Optional[float]:
    kind = str(trigger.get("type") or "")
    if kind == "interval":
        seconds = int(trigger["seconds"])
        anchor = float(trigger.get("anchor_at") or after_ts)
        steps = max(1, math.floor((float(after_ts) - anchor) / seconds) + 1)
        return anchor + steps * seconds
    if kind == "at":
        target = datetime.fromisoformat(str(trigger["at"]).replace("Z", "+00:00")).timestamp()
        return target if target > float(after_ts) else None
    if kind == "calendar":
        local_after = local_datetime(after_ts, timezone_name)
        match = _CLOCK_TIME.fullmatch(str(trigger["time"]))
        if match is None:
            raise ValueError("invalid persisted calendar time")
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        second = int(match.group("second") or 0)
        weekdays = {int(value) for value in trigger.get("weekdays") or range(7)}
        for offset in range(8):
            day = local_after.date() + timedelta(days=offset)
            if day.weekday() not in weekdays:
                continue
            candidate = localize(datetime(day.year, day.month, day.day, hour, minute, second), timezone_name)
            candidate_ts = candidate.timestamp()
            if candidate_ts > float(after_ts):
                return candidate_ts
        raise RuntimeError("unable to calculate the next calendar occurrence")
    raise ValueError(f"unsupported trigger type: {kind}")


def clock_snapshot(
    user_config: Optional[Dict[str, Any]] = None,
    *,
    requested_timezone: str = "",
) -> Dict[str, str]:
    timezone_name = resolve_timezone_name(user_config, requested_timezone)
    now = local_datetime(timezone_name=timezone_name)
    return {
        "timezone": timezone_name,
        "local_date": now.date().isoformat(),
        "local_time": now.strftime("%H:%M:%S"),
        "local_datetime": now.isoformat(timespec="seconds"),
        "utc_datetime": now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
