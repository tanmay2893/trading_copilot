"""Pre-flight strategy analysis using LLM.

Dumps all available context (strategy text, data stats, platform constraints)
to the LLM and lets it reason freely about any issues. No hardcoded check
categories -- the LLM decides what's problematic and how to fix it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import pandas as pd

from backtester.llm.base import BaseLLMProvider, LLMResponse
from backtester.prompts.templates import (
    ANALYSIS_SYSTEM_PROMPT,
    DIAGNOSIS_SYSTEM_PROMPT,
    REVIEW_SYSTEM_PROMPT,
    build_analysis_prompt,
    build_diagnosis_prompt,
    build_review_prompt,
)

log = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    verdict: str                        # "ok" or "fix"
    issues: list[str] = field(default_factory=list)
    fix_instructions: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class AnalysisResult:
    verdict: str                        # "ok" or "revise"
    issues: list[str] = field(default_factory=list)
    revised_strategy: str | None = None
    explanation: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


def _build_corporate_summary(df: pd.DataFrame, corporate_needs: set[str]) -> dict[str, int]:
    """Count corporate events present in the merged DataFrame."""
    counts: dict[str, int] = {}
    if "earnings" in corporate_needs and "Is_Earnings_Day" in df.columns:
        counts["earnings_dates"] = int(df["Is_Earnings_Day"].sum())
    if "dividends" in corporate_needs and "Is_Ex_Dividend" in df.columns:
        counts["ex_dividend_dates"] = int(df["Is_Ex_Dividend"].sum())
    if "splits" in corporate_needs and "Is_Split_Day" in df.columns:
        counts["stock_split_dates"] = int(df["Is_Split_Day"].sum())
    return counts


def _parse_llm_json(raw: str) -> dict:
    """Extract and parse JSON from LLM response, tolerating markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        start = next((i for i, l in enumerate(lines) if l.strip().startswith("```")), 0)
        end = next((i for i in range(len(lines) - 1, start, -1) if lines[i].strip().startswith("```")), len(lines))
        text = "\n".join(lines[start + 1 : end])

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1:
        text = text[brace_start : brace_end + 1]

    return json.loads(text)


def analyze_strategy(
    provider: BaseLLMProvider,
    strategy_text: str,
    ticker: str,
    interval: str,
    start: str,
    end: str,
    was_clamped: bool,
    row_count: int,
    columns: list[str],
    corporate_needs: set[str],
    corporate_summary: dict[str, int],
) -> AnalysisResult:
    """Ask the LLM to review the strategy given all available context.

    Returns AnalysisResult with verdict "ok" (no issues) or "revise" (with
    a proposed improved strategy and explanation).
    """
    prompt = build_analysis_prompt(
        strategy_text=strategy_text,
        ticker=ticker,
        interval=interval,
        start=start,
        end=end,
        was_clamped=was_clamped,
        row_count=row_count,
        columns=columns,
        corporate_needs=corporate_needs,
        corporate_summary=corporate_summary,
    )

    try:
        response: LLMResponse = provider.generate(prompt, ANALYSIS_SYSTEM_PROMPT)
    except Exception:
        log.warning("Strategy analysis LLM call failed, skipping analysis", exc_info=True)
        return AnalysisResult(verdict="ok")

    try:
        data = _parse_llm_json(response.content)
    except (json.JSONDecodeError, ValueError):
        log.warning("Could not parse analysis JSON, skipping analysis")
        return AnalysisResult(verdict="ok")

    verdict = data.get("verdict", "ok").strip().lower()
    if verdict not in ("ok", "revise"):
        verdict = "ok"

    issues = data.get("issues", [])
    if not isinstance(issues, list):
        issues = [str(issues)] if issues else []

    revised = data.get("revised_strategy")
    explanation = data.get("explanation")

    if verdict == "revise" and not revised:
        verdict = "ok"

    return AnalysisResult(
        verdict=verdict,
        issues=[str(i) for i in issues],
        revised_strategy=revised if verdict == "revise" else None,
        explanation=str(explanation) if explanation else None,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )


@dataclass
class DiagnosisResult:
    diagnosis: str = ""
    root_cause: str = "other"           # strategy_too_restrictive | code_bug | data_issue | other
    revised_strategy: str | None = None
    explanation: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


def diagnose_stuck_loop(
    provider: BaseLLMProvider,
    strategy_description: str,
    error_history: list[dict],
    last_code: str,
    row_count: int,
    interval: str,
    columns: list[str],
    has_corporate_data: bool = False,
) -> DiagnosisResult:
    """Ask the LLM to diagnose why the iteration loop is stuck.

    Called when anti-loop has fired multiple times with no progress.
    Returns a DiagnosisResult with root_cause and an optional revised_strategy.
    """
    prompt = build_diagnosis_prompt(
        strategy_description=strategy_description,
        error_history=error_history,
        last_code=last_code,
        row_count=row_count,
        interval=interval,
        columns=columns,
        has_corporate_data=has_corporate_data,
    )

    try:
        response: LLMResponse = provider.generate(prompt, DIAGNOSIS_SYSTEM_PROMPT)
    except Exception:
        log.warning("Diagnosis LLM call failed", exc_info=True)
        return DiagnosisResult(diagnosis="LLM call failed during diagnosis")

    try:
        data = _parse_llm_json(response.content)
    except (json.JSONDecodeError, ValueError):
        log.warning("Could not parse diagnosis JSON")
        return DiagnosisResult(diagnosis="Could not parse LLM diagnosis response")

    root_cause = data.get("root_cause", "other").strip().lower()
    valid_causes = {"strategy_too_restrictive", "code_bug", "data_issue", "other"}
    if root_cause not in valid_causes:
        root_cause = "other"

    revised = data.get("revised_strategy")
    if isinstance(revised, str) and not revised.strip():
        revised = None

    return DiagnosisResult(
        diagnosis=data.get("diagnosis", ""),
        root_cause=root_cause,
        revised_strategy=revised,
        explanation=data.get("explanation"),
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )


def reanalyze_strategy(
    provider: BaseLLMProvider,
    strategy_text: str,
    issues: list[str],
    previous_revision: str,
    user_feedback: str,
    ticker: str,
    interval: str,
    start: str,
    end: str,
    row_count: int,
    columns: list[str],
    revision_history: list[dict] | None = None,
) -> AnalysisResult:
    """Re-analyze a strategy incorporating user feedback on why they rejected the revision.

    Returns AnalysisResult with an alternative revision that addresses the feedback.
    """
    from backtester.prompts.templates import REANALYSIS_SYSTEM_PROMPT, build_reanalysis_prompt

    prompt = build_reanalysis_prompt(
        strategy_text=strategy_text,
        issues=issues,
        previous_revision=previous_revision,
        user_feedback=user_feedback,
        ticker=ticker,
        interval=interval,
        start=start,
        end=end,
        row_count=row_count,
        columns=columns,
        revision_history=revision_history,
    )

    try:
        response: LLMResponse = provider.generate(prompt, REANALYSIS_SYSTEM_PROMPT)
    except Exception:
        log.warning("Reanalysis LLM call failed", exc_info=True)
        return AnalysisResult(verdict="ok")

    try:
        data = _parse_llm_json(response.content)
    except (json.JSONDecodeError, ValueError):
        log.warning("Could not parse reanalysis JSON")
        return AnalysisResult(verdict="ok")

    issues_out = data.get("issues", [])
    if not isinstance(issues_out, list):
        issues_out = [str(issues_out)] if issues_out else []

    revised = data.get("revised_strategy")
    explanation = data.get("explanation")

    if not revised:
        return AnalysisResult(verdict="ok")

    return AnalysisResult(
        verdict="revise",
        issues=[str(i) for i in issues_out],
        revised_strategy=revised,
        explanation=str(explanation) if explanation else None,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )


def review_strategy_code(
    provider: BaseLLMProvider,
    strategy_description: str,
    generated_code: str,
    signals_df: pd.DataFrame,
    data_interval: str = "1d",
    has_corporate_data: bool = False,
    data_df: pd.DataFrame | None = None,
) -> ReviewResult:
    """Ask the LLM to review generated code against the strategy description.

    If data_df is provided, the review prompt includes data row count and date
    range plus signal date range so the LLM can judge whether the number and
    distribution of signals are plausible (e.g. too many/few given the strategy).

    Returns ReviewResult with verdict "ok" or "fix" (with issues and
    specific fix instructions).
    """
    buy_count = int((signals_df["Signal"] == "BUY").sum())
    sell_count = int((signals_df["Signal"] == "SELL").sum())
    signal_count = len(signals_df)
    sample_signals = signals_df.head(10).to_string(index=False)

    data_row_count: int | None = None
    data_date_range_str: str | None = None
    if data_df is not None and not data_df.empty:
        data_row_count = len(data_df)
        date_col = "Date" if "Date" in data_df.columns else "date"
        if date_col in data_df.columns:
            d = pd.to_datetime(data_df[date_col])
            data_date_range_str = f"{d.min().date()} to {d.max().date()}"

    signal_date_range_str: str | None = None
    if not signals_df.empty and "Date" in signals_df.columns:
        sd = pd.to_datetime(signals_df["Date"])
        signal_date_range_str = f"first {sd.min().date()}, last {sd.max().date()}"

    prompt = build_review_prompt(
        strategy_description=strategy_description,
        generated_code=generated_code,
        signal_count=signal_count,
        buy_count=buy_count,
        sell_count=sell_count,
        sample_signals=sample_signals,
        data_interval=data_interval,
        has_corporate_data=has_corporate_data,
        data_row_count=data_row_count,
        data_date_range_str=data_date_range_str,
        signal_date_range_str=signal_date_range_str,
    )

    try:
        response: LLMResponse = provider.generate(prompt, REVIEW_SYSTEM_PROMPT)
    except Exception:
        log.warning("Strategy review LLM call failed, skipping review", exc_info=True)
        return ReviewResult(verdict="ok")

    try:
        data = _parse_llm_json(response.content)
    except (json.JSONDecodeError, ValueError):
        log.warning("Could not parse review JSON, skipping review")
        return ReviewResult(verdict="ok")

    verdict = data.get("verdict", "ok").strip().lower()
    if verdict not in ("ok", "fix"):
        verdict = "ok"

    issues = data.get("issues", [])
    if not isinstance(issues, list):
        issues = [str(issues)] if issues else []

    fix_instructions = data.get("fix_instructions")

    if verdict == "fix" and not issues and not fix_instructions:
        verdict = "ok"

    return ReviewResult(
        verdict=verdict,
        issues=[str(i) for i in issues],
        fix_instructions=str(fix_instructions) if fix_instructions else None,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
