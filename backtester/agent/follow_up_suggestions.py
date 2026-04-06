"""LLM-generated follow-up chat suggestions after a strategy version is saved."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backtester.agent.session import ChatSession
    from backtester.llm.base import BaseLLMProvider

log = logging.getLogger(__name__)

_MAX_CODE_CHARS = 8000
_MAX_LABEL_LEN = 72
_MAX_PROMPT_LEN = 1200

_SYSTEM = """You help traders decide what to ask next in a strategy backtesting chat.

Return ONLY a JSON array of exactly 3 objects. No markdown fences, no commentary.

Each object must have:
- "label": short button text (6 words or fewer), Title Case or sentence case ok
- "prompt": a single clear user message to send in chat (what they want the assistant to do next)

SCOPE (strict — all three suggestions must stay inside this):
- Improve the **strategy logic only**: entry/exit rules, filters, trend/volatility/regime handling, reducing false signals, clarifying conflicting conditions.
- Suggest **adding or combining indicators** (e.g. volume, momentum, volatility, breadth) when they genuinely help the described idea.
- Explain **why** a logic change helps, or walk through **edge cases** in the current rules.

FORBIDDEN — do not mention or imply any of the following (not even indirectly):
- Tuning, sweeping, or optimizing **numeric parameters** (periods, thresholds, stops, position size) as the main ask — focus on *rules and indicators*, not "try different parameter values".
- **Multi-company / multi-ticker / batch / screening** (e.g. all US stocks, all Indian stocks, run across many symbols, stock screeners).
- Portfolio allocation, position sizing math, broker orders, or live/paper trading setup — unless purely about *signal logic*.

The three prompts must still be **genuinely different angles** within "logic & indicators" (e.g. add a confirming indicator vs. tighten entry filter vs. handle chop vs. regime split). Do not repeat the same idea.

Prompts must be specific to the strategy and code context. Never include PII. Keep prompts professional."""


def _truncate(s: str | None, n: int) -> str:
    if not s:
        return ""
    s = s.strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _parse_suggestions_json(raw: str) -> list[dict[str, str]]:
    text = (raw or "").strip()
    if not text:
        return []
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    data = json.loads(text)
    if not isinstance(data, list):
        return []
    out: list[dict[str, str]] = []
    for item in data[:5]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        prompt = str(item.get("prompt", "")).strip()
        if not label or not prompt:
            continue
        label = _truncate(label, _MAX_LABEL_LEN)
        prompt = _truncate(prompt, _MAX_PROMPT_LEN)
        out.append({"label": label, "prompt": prompt})
        if len(out) >= 3:
            break
    return out[:3]


# Reject suggestions that slip past the LLM (parameter/batch/screening focus).
_FORBIDDEN_PHRASES = (
    "parameter tuning",
    "tune parameters",
    "tune the parameters",
    "optimize parameters",
    "optimize the parameters",
    "parameter sweep",
    "grid search",
    "hyperparameter",
    "all us stock",
    "all indian stock",
    "all stocks",
    "batch rerun",
    "multi-ticker",
    "multi ticker",
    "multi-stock",
    "multi stock",
    "multi company",
    "multi-company",
    "multiple tickers",
    "multiple stocks",
    "every ticker",
    "each ticker",
    "across tickers",
    "stock screener",
    "screen stocks",
    "universe of stocks",
    "another ticker",
    "different ticker",
    "other tickers",
    "run on multiple",
    "test on multiple",
)


def _allowed_logic_only_suggestion(label: str, prompt: str) -> bool:
    combined = f"{label}\n{prompt}".lower()
    return not any(p in combined for p in _FORBIDDEN_PHRASES)


def _filter_logic_only(items: list[dict[str, str]]) -> list[dict[str, str]]:
    return [x for x in items if _allowed_logic_only_suggestion(x["label"], x["prompt"])]


def generate_follow_up_suggestions(
    session: ChatSession,
    provider: BaseLLMProvider,
    latest_user_message: str,
) -> tuple[list[dict[str, str]], int, int]:
    """Produce up to 3 follow-up suggestions. Returns (suggestions, input_tokens, output_tokens)."""
    state = session.state_summary()
    code = _truncate(session.active_code, _MAX_CODE_CHARS)
    strat = _truncate(session.active_strategy, 2000)
    recent = session.chat_summary_for_analysis(max_messages=8, max_content_len=500)
    user_bit = _truncate(latest_user_message, 2000)

    user_prompt = f"""Session state:
{state}

Natural-language strategy (if any):
{strat or "(not captured)"}

Recent conversation:
{recent}

Latest user request this turn:
{user_bit}

Current strategy code (Python, may be truncated):
```python
{code or "(no code)"}
```

Remember: logic and indicators only — no parameter sweeps, no multi-stock or batch workflows.

Output the JSON array of 3 objects now."""

    try:
        resp = provider.generate(user_prompt, _SYSTEM)
    except Exception as exc:
        log.warning("follow_up_suggestions LLM call failed: %s", exc)
        return [], 0, 0

    in_tok = int(getattr(resp, "input_tokens", 0) or 0)
    out_tok = int(getattr(resp, "output_tokens", 0) or 0)

    try:
        parsed = _parse_suggestions_json(resp.content or "")
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        log.warning("follow_up_suggestions parse failed: %s", exc)
        return [], in_tok, out_tok

    parsed = _filter_logic_only(parsed)
    if len(parsed) < 2:
        log.warning(
            "follow_up_suggestions: need at least 2 items after logic-only filter, got %s",
            len(parsed),
        )
        return [], in_tok, out_tok

    return parsed[:3], in_tok, out_tok
