from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


class OpenClawTemporalWindowsMixin:
    @staticmethod
    def _valid_timezone_name(name: str | None) -> bool:
        raw = str(name or '').strip()
        if not raw:
            return False
        try:
            ZoneInfo(raw)
        except Exception:
            return False
        return True

    @staticmethod
    def _valid_clock_string(value: Any) -> bool:
        raw = str(value or '').strip()
        parts = raw.split(':', 1)
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            return False
        hh = int(parts[0])
        mm = int(parts[1])
        return 0 <= hh <= 23 and 0 <= mm <= 59

    @staticmethod
    def _parse_clock(value: str | None, *, default: str = '00:00') -> tuple[int, int]:
        raw = str(value or default).strip() or default
        try:
            hh_raw, mm_raw = raw.split(':', 1)
            hh = max(0, min(23, int(hh_raw)))
            mm = max(0, min(59, int(mm_raw)))
            return hh, mm
        except Exception:
            hh_raw, mm_raw = default.split(':', 1)
            return int(hh_raw), int(mm_raw)

    @staticmethod
    def _resolve_timezone(name: str | None) -> ZoneInfo:
        try:
            return ZoneInfo(str(name or 'UTC').strip() or 'UTC')
        except Exception:
            return ZoneInfo('UTC')

    @classmethod
    def _window_interval_for_date(
        cls,
        *,
        date_value,
        start_time: str,
        end_time: str,
        timezone_name: str,
    ) -> tuple[datetime, datetime]:
        tz = cls._resolve_timezone(timezone_name)
        start_h, start_m = cls._parse_clock(start_time, default='00:00')
        end_h, end_m = cls._parse_clock(end_time, default='23:59')
        start_dt = datetime(date_value.year, date_value.month, date_value.day, start_h, start_m, tzinfo=tz)
        end_dt = datetime(date_value.year, date_value.month, date_value.day, end_h, end_m, tzinfo=tz)
        if (end_h, end_m) <= (start_h, start_m):
            end_dt = end_dt + timedelta(days=1)
        return start_dt, end_dt

    @classmethod
    def _recurring_window_state(
        cls,
        *,
        weekdays: list[Any] | tuple[Any, ...] | None,
        start_time: str,
        end_time: str,
        timezone_name: str,
        now_ts: float,
    ) -> dict[str, Any]:
        tz = cls._resolve_timezone(timezone_name)
        now_local = datetime.fromtimestamp(float(now_ts), tz)
        normalized_weekdays = cls._normalize_weekdays(weekdays)
        if not normalized_weekdays:
            normalized_weekdays = list(range(7))
        active = False
        active_until = None
        active_from = None
        for offset in (-1, 0):
            candidate_date = (now_local + timedelta(days=offset)).date()
            if candidate_date.weekday() not in normalized_weekdays:
                continue
            start_dt, end_dt = cls._window_interval_for_date(
                date_value=candidate_date,
                start_time=start_time,
                end_time=end_time,
                timezone_name=timezone_name,
            )
            if start_dt <= now_local < end_dt:
                active = True
                active_from = start_dt
                active_until = end_dt
                break
        next_start = None
        if not active:
            for offset in range(0, 8):
                candidate_date = (now_local + timedelta(days=offset)).date()
                if candidate_date.weekday() not in normalized_weekdays:
                    continue
                start_dt, end_dt = cls._window_interval_for_date(
                    date_value=candidate_date,
                    start_time=start_time,
                    end_time=end_time,
                    timezone_name=timezone_name,
                )
                if start_dt > now_local:
                    next_start = start_dt
                    break
                if end_dt <= now_local:
                    continue
        return {
            'timezone': timezone_name,
            'weekdays': normalized_weekdays,
            'active': active,
            'active_from': active_from.timestamp() if active_from is not None else None,
            'active_until': active_until.timestamp() if active_until is not None else None,
            'next_start_at': next_start.timestamp() if next_start is not None else None,
        }

    @classmethod
    def _absolute_window_state(
        cls,
        *,
        starts_at: Any,
        ends_at: Any,
        now_ts: float,
    ) -> dict[str, Any]:
        try:
            start_value = float(starts_at)
            end_value = float(ends_at)
        except Exception:
            return {'active': False, 'active_from': None, 'active_until': None, 'next_start_at': None}
        active = start_value <= float(now_ts) < end_value
        next_start = start_value if start_value > float(now_ts) else None
        return {'active': active, 'active_from': start_value, 'active_until': end_value if active else None, 'next_start_at': next_start}

    @classmethod
    def _window_clock_bounds(
        cls,
        *,
        window: dict[str, Any],
        default_start: str = '00:00',
        default_end: str = '23:59',
    ) -> tuple[str, str]:
        if window.get('start_time') is not None or window.get('end_time') is not None or window.get('from_time') is not None or window.get('to_time') is not None:
            start_h, start_m = cls._parse_clock(str(window.get('start_time') or window.get('from_time') or default_start), default=default_start)
            end_h, end_m = cls._parse_clock(str(window.get('end_time') or window.get('to_time') or default_end), default=default_end)
            return f'{start_h:02d}:{start_m:02d}', f'{end_h:02d}:{end_m:02d}'
        try:
            start_hour = int(window.get('start_hour') if window.get('start_hour') is not None else window.get('from_hour', 0))
        except Exception:
            start_hour = 0
        try:
            end_hour = int(window.get('end_hour') if window.get('end_hour') is not None else window.get('to_hour', 24))
        except Exception:
            end_hour = 24
        start_hour = max(0, min(23, start_hour))
        end_hour = max(0, min(24, end_hour))
        return f'{start_hour:02d}:00', '00:00' if end_hour == 24 else f'{end_hour:02d}:00'

    @classmethod
    def _window_allows_ts(
        cls,
        *,
        base_ts: float,
        window: dict[str, Any],
        default_timezone: str = 'UTC',
    ) -> tuple[bool, float | None]:
        tz_name = str(window.get('timezone') or default_timezone or 'UTC').strip() or 'UTC'
        start_time, end_time = cls._window_clock_bounds(window=window)
        state = cls._recurring_window_state(
            weekdays=list(window.get('days') or window.get('weekdays') or []),
            start_time=start_time,
            end_time=end_time,
            timezone_name=tz_name,
            now_ts=float(base_ts),
        )
        if bool(state.get('active')):
            return True, float(base_ts)
        next_start = state.get('next_start_at')
        return False, float(next_start) if next_start is not None else None

    @classmethod
    def _route_schedule_ts(
        cls,
        *,
        route: dict[str, Any],
        routing_policy: dict[str, Any],
        now: float | None = None,
    ) -> tuple[float, list[str]]:
        import time

        current_ts = float(now if now is not None else time.time())
        delay_s = float(route.get('delay_s') or 0.0)
        candidate_ts = current_ts + max(0.0, delay_s)
        reasons: list[str] = []
        windows = list(route.get('time_windows') or [])
        if delay_s > 0:
            reasons.append('delayed_step')
        if not windows:
            return candidate_ts, reasons
        allowed = False
        earliest: float | None = None
        default_tz = str(routing_policy.get('default_timezone') or 'UTC')
        for window in windows:
            if not isinstance(window, dict):
                continue
            matches, next_start = cls._window_allows_ts(base_ts=candidate_ts, window=window, default_timezone=default_tz)
            if matches:
                allowed = True
                break
            if next_start is not None:
                earliest = next_start if earliest is None else min(earliest, next_start)
        if allowed:
            return candidate_ts, reasons
        reasons.append('outside_delivery_window')
        return float(earliest if earliest is not None else candidate_ts), reasons
