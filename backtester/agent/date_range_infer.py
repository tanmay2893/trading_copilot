"""Infer backtest start/end dates from natural language using the configured LLM."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime

from backtester.llm.base import BaseLLMProvider

log = logging.getLogger(__name__)


def _parse_llm_json_object(raw: str) -> dict | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None


def _normalize_iso(d: str | None) -> str | None:
    if not d or not isinstance(d, str):
        return None
    s = d.strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.date().isoformat()
    except (ValueError, TypeError):
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date().isoformat()
        except (ValueError, TypeError):
            return None


def _validate_range(
    start: str | None, end: str | None, today: date
) -> tuple[str | None, str | None]:
    if not start or not end:
        return (None, None)
    try:
        ds = date.fromisoformat(start)
        de = date.fromisoformat(end)
    except ValueError:
        return (None, None)
    if ds > de:
        ds, de = de, ds
    if ds > today:
        return (None, None)
    if de > today:
        de = today
    if ds > de:
        return (None, None)
    return (ds.isoformat(), de.isoformat())


def infer_suggested_backtest_dates(
    provider: BaseLLMProvider,
    user_text: str,
    *,
    today: date | None = None,
) -> tuple[str | None, str | None]:
    """Return (start_date, end_date) as YYYY-MM-DD if the user message implies a range; else (None, None)."""
    text = (user_text or "").strip()
    if not text:
        return (None, None)

    today_d = today or date.today()
    today_s = today_d.isoformat()

    prompt = f"""You extract backtest date ranges from a user's message about a trading strategy.

Today's calendar date (authoritative "now"): {today_s}

Read the user message. If they specify or clearly imply a historical period for the backtest, output strict JSON only (no markdown, no code fences) with this shape:
{{"start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD"}}

Rules:
- "all of 2024" / "entire 2024" / "for 2024" → 2024-01-01 through 2024-12-31.
- "2024-2025" as a range → 2024-01-01 through 2025-12-31 (unless they give explicit month/day).
- "2023 to 2024" without months → full calendar years 2023-01-01 through 2024-12-31.
- If only one calendar year is mentioned → that full year.
- If they give explicit from/until dates, use those.
- end_date must not be after {today_s}; clamp to {today_s} if needed (you may still output the clamped value).
- If the message does NOT mention any time period, window, year, or date range for backtesting, output: {{"start_date":null,"end_date":null}}

User message:
{text}
"""

    try:
        resp = provider.generate(
            prompt,
            "You reply with a single JSON object only. No other text.",
        )
        data = _parse_llm_json_object(resp.content or "")
        if not data:
            return (None, None)
        start = _normalize_iso(data.get("start_date"))
        end = _normalize_iso(data.get("end_date"))
        return _validate_range(start, end, today_d)
    except Exception:
        log.exception("infer_suggested_backtest_dates failed")
        return (None, None)
