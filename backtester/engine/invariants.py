"""Invariant and regression checks for strategy refinements and fixes.

These helpers operate on pairs of signals DataFrames and simple natural-
language change/fix requests to detect obvious behavioral inconsistencies,
such as adding a stricter condition but increasing the number of BUY signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


@dataclass
class SignalComparison:
    baseline_buy: int
    baseline_sell: int
    new_buy: int
    new_sell: int
    added_buy_dates: list[str]
    removed_buy_dates: list[str]
    added_sell_dates: list[str]
    removed_sell_dates: list[str]


def _normalise_dates(df: pd.DataFrame, date_col: str = "Date") -> pd.Series:
    """Return a normalised datetime series for comparison."""
    if date_col not in df.columns and "date" in df.columns:
        date_col = "date"
    return pd.to_datetime(df[date_col])


def compare_signals(
    baseline_df: pd.DataFrame,
    new_df: pd.DataFrame,
) -> SignalComparison:
    """Compute basic counts and which signal dates were added/removed.

    This comparison is intentionally simple: it only looks at BUY/SELL counts
    and dates, not prices or intra-day ordering.
    """
    base_dates = _normalise_dates(baseline_df)
    new_dates = _normalise_dates(new_df)

    base_buy_dates = set(base_dates[baseline_df["Signal"] == "BUY"].dt.strftime("%Y-%m-%d"))
    base_sell_dates = set(base_dates[baseline_df["Signal"] == "SELL"].dt.strftime("%Y-%m-%d"))
    new_buy_dates = set(new_dates[new_df["Signal"] == "BUY"].dt.strftime("%Y-%m-%d"))
    new_sell_dates = set(new_dates[new_df["Signal"] == "SELL"].dt.strftime("%Y-%m-%d"))

    added_buy = sorted(new_buy_dates - base_buy_dates)
    removed_buy = sorted(base_buy_dates - new_buy_dates)
    added_sell = sorted(new_sell_dates - base_sell_dates)
    removed_sell = sorted(base_sell_dates - new_sell_dates)

    return SignalComparison(
        baseline_buy=int((baseline_df["Signal"] == "BUY").sum()),
        baseline_sell=int((baseline_df["Signal"] == "SELL").sum()),
        new_buy=int((new_df["Signal"] == "BUY").sum()),
        new_sell=int((new_df["Signal"] == "SELL").sum()),
        added_buy_dates=added_buy,
        removed_buy_dates=removed_buy,
        added_sell_dates=added_sell,
        removed_sell_dates=removed_sell,
    )


def infer_refinement_intent(change_text: str) -> dict:
    """Heuristically infer what kind of change the user wants.

    Returns flags such as:
    - expect_fewer_buys: when the text clearly suggests an additional filter
      or restriction on when to buy.
    """
    text = change_text.lower()
    tokens: dict[str, bool] = {}

    add_filter_keywords: Iterable[str] = (
        "add condition",
        "additional condition",
        "only when",
        "only if",
        "filter",
        "stricter",
        "more selective",
        "too many signals",
        "too many buys",
        "reduce signals",
        "reduce buys",
        "top ",
        "percentile",
        "%",
    )
    tokens["expect_fewer_buys"] = any(k in text for k in add_filter_keywords)

    return tokens


def check_refinement_invariants(
    baseline_signals_df: pd.DataFrame,
    new_signals_df: pd.DataFrame,
    change_text: str,
) -> list[str]:
    """Return human-readable invariant violations between baseline and new signals.

    This is conservative: if we cannot confidently infer intent, we do not
    emit violations. It is designed to be strategy-agnostic.
    """
    if baseline_signals_df is None or new_signals_df is None:
        return []

    intent = infer_refinement_intent(change_text)
    comparison = compare_signals(baseline_signals_df, new_signals_df)
    violations: list[str] = []

    if intent.get("expect_fewer_buys"):
        if comparison.new_buy > comparison.baseline_buy:
            violations.append(
                f"BUY count increased after applying what appears to be a restrictive change: "
                f"baseline BUY={comparison.baseline_buy}, new BUY={comparison.new_buy}."
            )

    return violations


def signals_match(comp: SignalComparison) -> bool:
    """True if baseline and new signals are identical (same BUY/SELL dates)."""
    return (
        not comp.added_buy_dates
        and not comp.removed_buy_dates
        and not comp.added_sell_dates
        and not comp.removed_sell_dates
    )


def format_signal_diff_for_prompt(comp: SignalComparison, max_dates: int = 10) -> str:
    """Produce a short text summary of before/after signal behaviour."""
    lines = [
        f"Baseline: {comp.baseline_buy} BUY, {comp.baseline_sell} SELL.",
        f"New run: {comp.new_buy} BUY, {comp.new_sell} SELL.",
    ]

    if comp.added_buy_dates:
        added = ", ".join(comp.added_buy_dates[:max_dates])
        more = " (and more)" if len(comp.added_buy_dates) > max_dates else ""
        lines.append(f"Added BUY dates: {added}{more}.")
    if comp.removed_buy_dates:
        removed = ", ".join(comp.removed_buy_dates[:max_dates])
        more = " (and more)" if len(comp.removed_buy_dates) > max_dates else ""
        lines.append(f"Removed BUY dates: {removed}{more}.")

    if comp.added_sell_dates:
        added = ", ".join(comp.added_sell_dates[:max_dates])
        more = " (and more)" if len(comp.added_sell_dates) > max_dates else ""
        lines.append(f"Added SELL dates: {added}{more}.")
    if comp.removed_sell_dates:
        removed = ", ".join(comp.removed_sell_dates[:max_dates])
        more = " (and more)" if len(comp.removed_sell_dates) > max_dates else ""
        lines.append(f"Removed SELL dates: {removed}{more}.")

    return "\n".join(lines)


def diagnostic_bullets_for_comparison(
    comp: SignalComparison,
    label_a: str,
    label_b: str,
) -> list[str]:
    """Return short diagnostic bullets for a signal comparison (counts and likely causes)."""
    bullets: list[str] = []
    buy_diff = comp.new_buy - comp.baseline_buy
    sell_diff = comp.new_sell - comp.baseline_sell
    bullets.append(
        f"{label_a} vs {label_b}: BUY {comp.baseline_buy} → {comp.new_buy} ({buy_diff:+d}), "
        f"SELL {comp.baseline_sell} → {comp.new_sell} ({sell_diff:+d})."
    )
    causes: list[str] = []
    if comp.removed_buy_dates or comp.added_buy_dates or comp.removed_sell_dates or comp.added_sell_dates:
        causes.append("Different indicator parameters (e.g. RSI/MA period or threshold)")
        causes.append("Different bar or date-boundary handling (e.g. first/last bar of day)")
        causes.append("Floating-point comparison differences (e.g. <= vs <)")
        causes.append("Ambiguous wording in a refinement command interpreted differently")
    if causes:
        bullets.append("Possible causes: " + "; ".join(causes) + ".")
    return bullets

