"""Context engineering: intelligent context selection for user-reported issues.

Scores relevance of each context source against the user's issue description,
then assembles a token-budgeted prompt with only the most relevant pieces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ContextPiece:
    name: str
    content: str
    relevance: float = 0.0
    token_estimate: int = 0


@dataclass
class RunArtifacts:
    strategy_description: str = ""
    generated_code: str = ""
    signals_df: pd.DataFrame | None = None
    data_df: pd.DataFrame | None = None
    error_history: list[dict] = field(default_factory=list)
    test_failures: list[str] = field(default_factory=list)
    interval: str = "1d"


KEYWORD_SOURCE_MAP = {
    "rsi": ["code_setup", "indicator_values"],
    "macd": ["code_setup", "indicator_values"],
    "bollinger": ["code_setup", "indicator_values"],
    "sma": ["code_setup", "indicator_values"],
    "ema": ["code_setup", "indicator_values"],
    "atr": ["code_setup", "indicator_values"],
    "stochastic": ["code_setup", "indicator_values"],
    "buy": ["code_signals", "signal_output"],
    "sell": ["code_signals", "signal_output"],
    "signal": ["code_signals", "signal_output", "test_failures"],
    "crash": ["error_history"],
    "error": ["error_history"],
    "fail": ["error_history", "test_failures"],
    "wrong": ["signal_output", "code_signals"],
    "too many": ["signal_output", "code_signals"],
    "no signal": ["signal_output", "code_signals"],
    "nan": ["data_window", "code_setup"],
    "missing": ["data_window", "code_setup"],
    "date": ["data_window", "signal_output"],
    "price": ["data_window", "signal_output"],
}

DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def build_context(
    issue: str,
    artifacts: RunArtifacts,
    token_budget: int = 8000,
) -> str:
    """Assemble a focused prompt from the most relevant context pieces."""
    keywords = _extract_keywords(issue)
    mentioned_dates = DATE_PATTERN.findall(issue)

    pieces = _gather_pieces(artifacts, keywords, mentioned_dates)
    _score_pieces(pieces, keywords)
    pieces.sort(key=lambda p: p.relevance, reverse=True)

    selected: list[ContextPiece] = []
    used_tokens = 0
    for piece in pieces:
        if piece.relevance <= 0:
            continue
        if used_tokens + piece.token_estimate > token_budget:
            continue
        selected.append(piece)
        used_tokens += piece.token_estimate

    sections = [f"## {p.name}\n{p.content}" for p in selected]
    return "\n\n".join(sections)


def _extract_keywords(issue: str) -> list[str]:
    lower = issue.lower()
    found = []
    for kw in KEYWORD_SOURCE_MAP:
        if kw in lower:
            found.append(kw)
    words = re.findall(r"[a-z_]+", lower)
    for w in words:
        if w not in found and len(w) > 3:
            found.append(w)
    return found


def _gather_pieces(
    artifacts: RunArtifacts,
    keywords: list[str],
    mentioned_dates: list[str],
) -> list[ContextPiece]:
    pieces: list[ContextPiece] = []

    if artifacts.generated_code:
        setup_code, signal_code = _split_strategy_code(artifacts.generated_code)
        pieces.append(ContextPiece("Strategy setup()", setup_code, token_estimate=_est_tokens(setup_code)))
        pieces.append(ContextPiece("Strategy generate_signals()", signal_code, token_estimate=_est_tokens(signal_code)))

    pieces.append(ContextPiece(
        "Original Strategy Description",
        artifacts.strategy_description,
        token_estimate=_est_tokens(artifacts.strategy_description),
    ))

    if artifacts.data_df is not None:
        window = _extract_data_window(artifacts.data_df, mentioned_dates)
        pieces.append(ContextPiece("Data Window", window, token_estimate=_est_tokens(window)))

        schema = f"Columns: {list(artifacts.data_df.columns)}\nRows: {len(artifacts.data_df)}"
        pieces.append(ContextPiece("Data Schema", schema, token_estimate=_est_tokens(schema)))

    if artifacts.signals_df is not None and not artifacts.signals_df.empty:
        sig_window = _extract_signal_window(artifacts.signals_df, mentioned_dates)
        pieces.append(ContextPiece("Signal Output", sig_window, token_estimate=_est_tokens(sig_window)))

    if artifacts.error_history:
        deduped = _dedupe_errors(artifacts.error_history)
        err_text = "\n".join(f"- [{e['error_type']}] {e['message'][:150]}" for e in deduped)
        pieces.append(ContextPiece("Error History", err_text, token_estimate=_est_tokens(err_text)))

    if artifacts.test_failures:
        fail_text = "\n".join(f"- {f}" for f in artifacts.test_failures)
        pieces.append(ContextPiece("Test Failures", fail_text, token_estimate=_est_tokens(fail_text)))

    return pieces


def _score_pieces(pieces: list[ContextPiece], keywords: list[str]):
    for piece in pieces:
        score = 0.1  # baseline
        lower_content = piece.content.lower()
        lower_name = piece.name.lower()

        for kw in keywords:
            boosted_sources = KEYWORD_SOURCE_MAP.get(kw, [])
            name_tag = lower_name.replace(" ", "_").lower()
            if any(src in name_tag for src in boosted_sources):
                score += 0.3
            if kw in lower_content:
                score += 0.1

        if "error" in lower_name or "failure" in lower_name:
            if any(kw in ("crash", "error", "fail", "wrong") for kw in keywords):
                score += 0.2

        piece.relevance = min(score, 1.0)


def _split_strategy_code(code: str) -> tuple[str, str]:
    """Split code into setup-related and signal-related sections."""
    lines = code.split("\n")
    setup_lines = []
    signal_lines = []
    in_signals = False
    for line in lines:
        if "generate_signals" in line:
            in_signals = True
        if in_signals:
            signal_lines.append(line)
        else:
            setup_lines.append(line)
    return "\n".join(setup_lines) or code, "\n".join(signal_lines) or ""


def _extract_data_window(df: pd.DataFrame, dates: list[str], window: int = 20) -> str:
    if not dates:
        head = df.head(3).to_string(index=False)
        tail = df.tail(3).to_string(index=False)
        return f"First 3 rows:\n{head}\n\nLast 3 rows:\n{tail}"

    date_col = "Date" if "Date" in df.columns else "date"
    dt_col = pd.to_datetime(df[date_col])
    slices = []
    for d in dates[:2]:
        target = pd.Timestamp(d)
        nearest_idx = (dt_col - target).abs().idxmin()
        start = max(0, nearest_idx - window)
        end = min(len(df), nearest_idx + window)
        slices.append(df.iloc[start:end].to_string(index=False))
    return "\n\n".join(slices)


def _extract_signal_window(df: pd.DataFrame, dates: list[str], window: int = 10) -> str:
    if not dates:
        if len(df) <= 20:
            return df.to_string(index=False)
        head = df.head(5).to_string(index=False)
        tail = df.tail(5).to_string(index=False)
        return f"First 5 signals:\n{head}\n\nLast 5 signals:\n{tail}"

    dt_col = pd.to_datetime(df["Date"])
    slices = []
    for d in dates[:2]:
        target = pd.Timestamp(d)
        nearby = df[(dt_col >= target - pd.Timedelta(days=window)) & (dt_col <= target + pd.Timedelta(days=window))]
        slices.append(nearby.to_string(index=False))
    return "\n\n".join(slices) if slices else df.head(10).to_string(index=False)


def _dedupe_errors(history: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for h in history:
        key = f"{h.get('error_type', '')}:{h.get('message', '')[:100]}"
        if key in seen:
            seen[key]["count"] = seen[key].get("count", 1) + 1
        else:
            seen[key] = {**h, "count": 1}
    deduped = list(seen.values())
    for d in deduped:
        if d.get("count", 1) > 1:
            d["message"] = f"[occurred {d['count']}x] {d['message']}"
    return deduped[-3:]


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)
