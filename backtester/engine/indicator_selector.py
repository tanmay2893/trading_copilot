"""LLM-based indicator classification for chart output.

Two-phase approach:
  Phase 1 — Classify: LLM analyzes strategy code and categorizes each computed
            indicator column as overlay, oscillator, or internal.
  Phase 2 — Review:  A second LLM call reviews the classification for correctness
            and finalizes the selection.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from backtester.llm.base import BaseLLMProvider
from backtester.prompts.templates import (
    INDICATOR_REVIEW_SYSTEM_PROMPT,
    INDICATOR_SELECTION_SYSTEM_PROMPT,
    build_indicator_review_prompt,
    build_indicator_selection_prompt,
)

log = logging.getLogger(__name__)


@dataclass
class IndicatorSelection:
    overlay: list[str] = field(default_factory=list)
    oscillator: list[str] = field(default_factory=list)
    internal: list[str] = field(default_factory=list)
    reasoning: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def _parse_llm_json(raw: str) -> dict:
    """Extract and parse JSON from LLM response, tolerating markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        start = next((i for i, l in enumerate(lines) if l.strip().startswith("```")), 0)
        end = next(
            (i for i in range(len(lines) - 1, start, -1) if lines[i].strip().startswith("```")),
            len(lines),
        )
        text = "\n".join(lines[start + 1 : end])

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1:
        text = text[brace_start : brace_end + 1]

    return json.loads(text)


def select_chart_indicators(
    provider: BaseLLMProvider,
    strategy_code: str,
    strategy_description: str,
    indicator_columns: list[str],
    original_columns: list[str],
) -> IndicatorSelection:
    """Run two-phase LLM classification to decide which indicators to include in chart output.

    Returns an IndicatorSelection with overlay and oscillator columns finalized.
    """
    if not indicator_columns:
        return IndicatorSelection(reasoning="No indicator columns computed by the strategy.")

    total_in = 0
    total_out = 0

    # --- Phase 1: Classify ---
    classify_prompt = build_indicator_selection_prompt(
        strategy_code=strategy_code,
        indicator_columns=indicator_columns,
        original_columns=original_columns,
    )

    try:
        resp1 = provider.generate(classify_prompt, INDICATOR_SELECTION_SYSTEM_PROMPT)
        total_in += resp1.input_tokens
        total_out += resp1.output_tokens
    except Exception:
        log.warning("Indicator classification LLM call failed", exc_info=True)
        return _fallback_classification(indicator_columns, total_in, total_out)

    try:
        phase1 = _parse_llm_json(resp1.content)
    except (json.JSONDecodeError, ValueError):
        log.warning("Could not parse indicator classification JSON")
        return _fallback_classification(indicator_columns, total_in, total_out)

    overlay = _ensure_str_list(phase1.get("overlay", []))
    oscillator = _ensure_str_list(phase1.get("oscillator", []))
    internal = _ensure_str_list(phase1.get("internal", []))
    reasoning = str(phase1.get("reasoning", ""))

    valid_set = set(indicator_columns)
    overlay = [c for c in overlay if c in valid_set]
    oscillator = [c for c in oscillator if c in valid_set]
    internal = [c for c in internal if c in valid_set]

    # --- Phase 2: Review ---
    review_prompt = build_indicator_review_prompt(
        strategy_description=strategy_description,
        strategy_code=strategy_code,
        overlay_cols=overlay,
        oscillator_cols=oscillator,
        internal_cols=internal,
        reasoning=reasoning,
    )

    try:
        resp2 = provider.generate(review_prompt, INDICATOR_REVIEW_SYSTEM_PROMPT)
        total_in += resp2.input_tokens
        total_out += resp2.output_tokens
    except Exception:
        log.warning("Indicator review LLM call failed, using phase-1 result", exc_info=True)
        return IndicatorSelection(
            overlay=overlay,
            oscillator=oscillator,
            internal=internal,
            reasoning=reasoning,
            input_tokens=total_in,
            output_tokens=total_out,
        )

    try:
        phase2 = _parse_llm_json(resp2.content)
    except (json.JSONDecodeError, ValueError):
        log.warning("Could not parse indicator review JSON, using phase-1 result")
        return IndicatorSelection(
            overlay=overlay,
            oscillator=oscillator,
            internal=internal,
            reasoning=reasoning,
            input_tokens=total_in,
            output_tokens=total_out,
        )

    final_overlay = _ensure_str_list(phase2.get("overlay", overlay))
    final_oscillator = _ensure_str_list(phase2.get("oscillator", oscillator))
    final_reasoning = str(phase2.get("reasoning", reasoning))

    final_overlay = [c for c in final_overlay if c in valid_set]
    final_oscillator = [c for c in final_oscillator if c in valid_set]

    return IndicatorSelection(
        overlay=final_overlay,
        oscillator=final_oscillator,
        internal=[c for c in indicator_columns if c not in final_overlay and c not in final_oscillator],
        reasoning=final_reasoning,
        input_tokens=total_in,
        output_tokens=total_out,
    )


def _fallback_classification(
    indicator_columns: list[str],
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> IndicatorSelection:
    """Heuristic fallback when LLM calls fail — classify by column name patterns."""
    overlay = []
    oscillator = []
    internal = []

    OVERLAY_PATTERNS = {"SMA", "EMA", "BB_Upper", "BB_Middle", "BB_Lower", "VWAP", "SAR"}
    OSCILLATOR_PATTERNS = {
        "RSI", "MACD", "MACD_Signal", "MACD_Hist",
        "Stoch_K", "Stoch_D", "CCI", "Williams_R",
        "ADX", "ADX_Pos", "ADX_Neg", "ATR", "OBV",
    }

    def _volume_series_ma(name: str) -> bool:
        # SMA_20_Volume / EMA_10_Volume — not price overlays
        return "Volume" in name and (
            name.startswith("SMA_") or name.startswith("EMA_") or name.startswith("WMA_")
        )

    for col in indicator_columns:
        if _volume_series_ma(col):
            oscillator.append(col)
            continue
        matched = False
        for pattern in OVERLAY_PATTERNS:
            if col == pattern or col.startswith(pattern + "_") or col.startswith(pattern):
                overlay.append(col)
                matched = True
                break
        if matched:
            continue
        for pattern in OSCILLATOR_PATTERNS:
            if col == pattern or col.startswith(pattern + "_") or col.startswith(pattern):
                oscillator.append(col)
                matched = True
                break
        if not matched:
            internal.append(col)

    return IndicatorSelection(
        overlay=overlay,
        oscillator=oscillator,
        internal=internal,
        reasoning="Fallback heuristic classification (LLM unavailable)",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def build_chart_dataframe(
    indicator_df,
    selection: IndicatorSelection,
) -> "pd.DataFrame":
    """Filter the full indicator DataFrame to only OHLCV + selected overlay/oscillator columns."""
    import pandas as pd

    if indicator_df is None:
        return pd.DataFrame()

    date_col = "date" if "date" in indicator_df.columns else "Date"
    ohlcv = [date_col, "Open", "High", "Low", "Close", "Volume"]
    selected = selection.overlay + selection.oscillator
    keep = [c for c in ohlcv + selected if c in indicator_df.columns]
    return indicator_df[keep].copy()


def _ensure_str_list(val) -> list[str]:
    if isinstance(val, list):
        return [str(v) for v in val]
    if isinstance(val, str):
        return [val] if val else []
    return []
