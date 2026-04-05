"""Timeframe detection from strategy text and yfinance interval helpers."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

VALID_INTERVALS = [
    "1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo",
]

INTERVAL_MAX_DAYS: dict[str, int] = {
    "1m": 6,
    "2m": 58,
    "5m": 58,
    "15m": 58,
    "30m": 58,
    "60m": 725,
    "90m": 58,
    "1h": 725,
    "1d": 100_000,
    "5d": 100_000,
    "1wk": 100_000,
    "1mo": 100_000,
    "3mo": 100_000,
}

INTERVAL_LABELS: dict[str, str] = {
    "1m": "1-minute",
    "2m": "2-minute",
    "5m": "5-minute",
    "15m": "15-minute",
    "30m": "30-minute",
    "60m": "1-hour",
    "90m": "90-minute",
    "1h": "1-hour",
    "1d": "daily",
    "5d": "5-day",
    "1wk": "weekly",
    "1mo": "monthly",
    "3mo": "quarterly",
}

_KEYWORD_MAP: list[tuple[re.Pattern, str]] = [
    # Explicit yfinance-style intervals: "5m bars", "1h candles", "15m data"
    (re.compile(r"\b(1)\s*m(?:in(?:ute)?)?(?:\s+(?:bar|candle|chart|data|timeframe))?\b", re.I), "1m"),
    (re.compile(r"\b(2)\s*m(?:in(?:ute)?)?(?:\s+(?:bar|candle|chart|data|timeframe))?\b", re.I), "2m"),
    (re.compile(r"\b(5)\s*[-\s]?m(?:in(?:ute)?)?s?\b", re.I), "5m"),
    (re.compile(r"\b(15)\s*[-\s]?m(?:in(?:ute)?)?s?\b", re.I), "15m"),
    (re.compile(r"\b(30)\s*[-\s]?m(?:in(?:ute)?)?s?\b", re.I), "30m"),
    (re.compile(r"\b(60)\s*[-\s]?m(?:in(?:ute)?)?s?\b", re.I), "60m"),
    (re.compile(r"\b(90)\s*[-\s]?m(?:in(?:ute)?)?s?\b", re.I), "90m"),
    # N-minute generic (catches "10-minute" etc. mapped to closest)
    (re.compile(r"\b(\d+)\s*[-\s]?minute", re.I), "_minuteN"),
    # Hourly
    (re.compile(r"\bhourly\b", re.I), "1h"),
    (re.compile(r"\b1\s*[-\s]?h(?:our|r)?\b", re.I), "1h"),
    (re.compile(r"\b4\s*[-\s]?h(?:our|r)?s?\b", re.I), "1h"),  # 4h not in yfinance, closest is 1h
    # Weekly
    (re.compile(r"\bweekly\b", re.I), "1wk"),
    (re.compile(r"\b1\s*[-\s]?w(?:ee)?k\b", re.I), "1wk"),
    # Monthly
    (re.compile(r"\bmonthly\b", re.I), "1mo"),
    (re.compile(r"\b1\s*[-\s]?mo(?:nth)?\b", re.I), "1mo"),
    (re.compile(r"\b3\s*[-\s]?mo(?:nth)?s?\b", re.I), "3mo"),
    (re.compile(r"\bquarterly\b", re.I), "3mo"),
    # Daily (explicit mention)
    (re.compile(r"\bdaily\b", re.I), "1d"),
    (re.compile(r"\b1\s*[-\s]?d(?:ay)?\b", re.I), "1d"),
    # "intraday" without specifics -> 1h as a sensible default
    (re.compile(r"\bintraday\b", re.I), "1h"),
]

_MINUTE_SNAP = {1: "1m", 2: "2m", 5: "5m", 10: "15m", 15: "15m", 20: "30m", 30: "30m", 60: "60m", 90: "90m"}


def _snap_minutes(n: int) -> str:
    """Map an arbitrary minute count to the nearest valid yfinance interval."""
    if n in _MINUTE_SNAP:
        return _MINUTE_SNAP[n]
    closest = min(_MINUTE_SNAP.keys(), key=lambda k: abs(k - n))
    return _MINUTE_SNAP[closest]


_EXPLICIT_BAR_PATTERN = re.compile(
    r"(?:on|use|using)\s+(\w[\w\s-]*?)\s+bars?\b", re.I
)

_PROXY_CONTEXT = re.compile(
    r"(?:proxy|resampl|derived|aggregat)", re.I
)


def detect_interval(strategy_text: str) -> str:
    """Parse strategy description and return the best-matching yfinance interval.

    Gives priority to explicit "On <X> bars" phrasing. Ignores timeframe
    keywords that appear inside proxy/resampling context (e.g. "weekly proxy").
    Returns "1d" if no timeframe clues are found.
    """
    explicit = _EXPLICIT_BAR_PATTERN.search(strategy_text)
    if explicit:
        bar_type = explicit.group(1).strip().lower()
        for pattern, interval in _KEYWORD_MAP:
            if pattern.search(bar_type):
                if interval == "_minuteN":
                    m = pattern.search(bar_type)
                    return _snap_minutes(int(m.group(1)))
                return interval

    for pattern, interval in _KEYWORD_MAP:
        for m in pattern.finditer(strategy_text):
            context_start = max(0, m.start() - 40)
            context_end = min(len(strategy_text), m.end() + 40)
            surrounding = strategy_text[context_start:context_end]
            if _PROXY_CONTEXT.search(surrounding):
                continue
            if interval == "_minuteN":
                return _snap_minutes(int(m.group(1)))
            return interval
    return "1d"


def clamp_date_range(
    start: str, end: str, interval: str
) -> tuple[str, str, bool]:
    """Adjust dates so they stay within yfinance's lookback limits.

    yfinance restricts intraday data to the last N days from *today*.
    Both start and end must fall within that window. If the requested
    range is entirely outside the window, we move it to the most recent
    available window.

    Returns (new_start, new_end, was_clamped).
    """
    max_days = INTERVAL_MAX_DAYS.get(interval, 100_000)
    if max_days >= 100_000:
        return start, end, False

    today = datetime.now()
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    earliest_allowed = today - timedelta(days=max_days)

    was_clamped = False

    # End date can't be in the future
    if end_dt > today:
        end_dt = today
        was_clamped = True

    # If the end date itself is older than the allowed window,
    # move the entire range to the most recent available window
    if end_dt < earliest_allowed:
        end_dt = today
        start_dt = earliest_allowed
        was_clamped = True
    elif start_dt < earliest_allowed:
        start_dt = earliest_allowed
        was_clamped = True

    if start_dt >= end_dt:
        end_dt = today
        start_dt = today - timedelta(days=max_days)
        was_clamped = True

    return start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"), was_clamped


def is_intraday(interval: str) -> bool:
    return interval in {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}
