"""Use the LLM to extract and describe strategy parameters from generated code."""

from __future__ import annotations

import re
from dataclasses import dataclass

from backtester.llm.base import BaseLLMProvider
from backtester.prompts.templates import build_parameter_extraction_prompt

PARAM_EXTRACT_SYSTEM = "You list configurable parameters from code. Output only lines in the format: NAME = value  # description"


@dataclass
class ParameterLine:
    name: str
    value: str
    description: str


def get_parameters_used(provider: BaseLLMProvider, strategy_code: str) -> tuple[list[ParameterLine], str]:
    """Call the LLM to extract parameters from the strategy code. Returns (parsed lines, raw response)."""
    prompt = build_parameter_extraction_prompt(strategy_code)
    response = provider.generate(prompt, PARAM_EXTRACT_SYSTEM)
    raw = response.content.strip()
    lines = _parse_parameter_lines(raw)
    return lines, raw


def _parse_parameter_lines(raw: str) -> list[ParameterLine]:
    """Parse LLM output into list of ParameterLine. Expects lines like 'NAME = value  # desc' or 'NAME = value'."""
    out: list[ParameterLine] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("(none)"):
            continue
        if "=" not in line:
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)(?:\s*#\s*(.+))?$", line.strip())
        if match:
            name, value, desc = match.group(1), match.group(2).strip(), (match.group(3) or "").strip()
            out.append(ParameterLine(name=name, value=value, description=desc))
    return out


def _extract_init_params(strategy_code: str) -> list[dict]:
    """Extract __init__(self, df, *, name=default, ...) params from strategy code. Returns list of {name, value, description}."""
    out: list[dict] = []
    if "def __init__" not in strategy_code:
        return out
    # Find signature: from "def __init__(" to the matching "):"
    start = strategy_code.find("def __init__(")
    if start == -1:
        return out
    paren = strategy_code.find("(", start)
    if paren == -1:
        return out
    depth = 1
    i = paren + 1
    while i < len(strategy_code) and depth > 0:
        c = strategy_code[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    if depth != 0:
        return out
    sig = strategy_code[paren + 1 : i - 1].replace("\n", " ").replace("\r", " ")
    # Split at commas only at depth 0 so values can contain commas.
    parts: list[str] = []
    depth = 0
    start = 0
    for j, c in enumerate(sig):
        if c == "(" or c == "[" or c == "{":
            depth += 1
        elif c == ")" or c == "]" or c == "}":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(sig[start:j].strip())
            start = j + 1
    parts.append(sig[start:].strip())
    for part in parts:
        if part in ("self", "df", "*", "**kwargs"):
            continue
        if part.startswith("*") and "=" in part:
            part = part.lstrip("*").strip()
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", part)
        if match:
            name, value = match.group(1), match.group(2).strip().rstrip(",")
            if not name.startswith("_"):
                out.append({"name": name, "value": value, "description": ""})
    return out


def extract_parameters_from_code(strategy_code: str) -> list[dict]:
    """Extract parameters from __init__ defaults first, then class-level constants (no LLM). Returns list of {name, value, description}."""
    # Prefer __init__ params so rerun UI gets the same names the runner uses.
    init_params = _extract_init_params(strategy_code)
    if init_params:
        return init_params
    # Fallback: class-level constants (legacy generated code).
    out: list[dict] = []
    in_class = False
    for line in strategy_code.splitlines():
        stripped = line.strip()
        if stripped.startswith("class ") and "BaseStrategy" in line:
            in_class = True
            continue
        if in_class:
            if stripped.startswith("def ") or (stripped and not line.startswith((" ", "\t"))):
                break
            # Match indented NAME = value (optional # description). Name typically UPPER_CASE.
            match = re.match(r"^[ \t]*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)(?:\s*#\s*(.+))?$", line)
            if match:
                name, value, desc = match.group(1), match.group(2).strip().rstrip(","), (match.group(3) or "").strip()
                if not name.startswith("_"):
                    out.append({"name": name, "value": value, "description": desc})
    return out
