"""Prompt construction + code extraction from LLM responses."""

from __future__ import annotations

import re

import pandas as pd

from backtester.llm.base import BaseLLMProvider, LLMResponse
from backtester.prompts.templates import (
    SYSTEM_PROMPT,
    build_anti_loop_prompt,
    build_codegen_prompt,
    build_fix_prompt,
    build_review_fix_prompt,
)


def _df_info(df: pd.DataFrame) -> tuple[list[str], dict[str, str], str, int]:
    cols = list(df.columns)
    dtypes = {c: str(df[c].dtype) for c in cols}
    sample = df.head(3).to_string(index=False)
    return cols, dtypes, sample, len(df)


def extract_code(raw: str) -> str:
    """Extract Python code from LLM response, stripping markdown fences if present."""
    fenced = re.search(r"```(?:python)?\s*\n(.*?)```", raw, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return raw.strip()


def generate_strategy_code(
    provider: BaseLLMProvider,
    strategy_description: str,
    df: pd.DataFrame,
    interval: str = "1d",
    has_corporate_data: bool = False,
) -> tuple[str, LLMResponse]:
    cols, dtypes, sample, count = _df_info(df)
    prompt = build_codegen_prompt(
        strategy_description, cols, dtypes, sample, count,
        data_interval=interval, has_corporate_data=has_corporate_data,
    )
    response = provider.generate(prompt, SYSTEM_PROMPT)
    code = extract_code(response.content)
    return code, response


def generate_fix_code(
    provider: BaseLLMProvider,
    strategy_description: str,
    current_code: str,
    error_type: str,
    error_message: str,
    traceback_str: str,
    attempt_history: list[dict],
    df: pd.DataFrame,
    include_sample: bool = False,
    interval: str = "1d",
    has_corporate_data: bool = False,
) -> tuple[str, LLMResponse]:
    cols, _, sample, _ = _df_info(df)
    prompt = build_fix_prompt(
        strategy_description=strategy_description,
        current_code=current_code,
        error_type=error_type,
        error_message=error_message,
        traceback_str=traceback_str,
        attempt_history=attempt_history,
        data_columns=cols,
        sample_rows=sample if include_sample else "",
        data_interval=interval,
        has_corporate_data=has_corporate_data,
    )
    response = provider.generate(prompt, SYSTEM_PROMPT)
    code = extract_code(response.content)
    return code, response


def generate_anti_loop_code(
    provider: BaseLLMProvider,
    strategy_description: str,
    current_code: str,
    repeated_error: str,
    repeat_count: int,
    df: pd.DataFrame,
    interval: str = "1d",
    has_corporate_data: bool = False,
) -> tuple[str, LLMResponse]:
    cols, _, sample, _ = _df_info(df)
    prompt = build_anti_loop_prompt(
        strategy_description=strategy_description,
        current_code=current_code,
        repeated_error=repeated_error,
        repeat_count=repeat_count,
        data_columns=cols,
        sample_rows=sample,
        data_interval=interval,
        has_corporate_data=has_corporate_data,
    )
    response = provider.generate(prompt, SYSTEM_PROMPT)
    code = extract_code(response.content)
    return code, response


def generate_review_fix_code(
    provider: BaseLLMProvider,
    strategy_description: str,
    current_code: str,
    review_issues: list[str],
    fix_instructions: str,
    df: pd.DataFrame,
    interval: str = "1d",
    has_corporate_data: bool = False,
) -> tuple[str, LLMResponse]:
    """Generate fixed code based on post-execution review feedback."""
    cols, _, sample, _ = _df_info(df)
    prompt = build_review_fix_prompt(
        strategy_description=strategy_description,
        current_code=current_code,
        review_issues=review_issues,
        fix_instructions=fix_instructions,
        data_columns=cols,
        sample_rows=sample,
        data_interval=interval,
        has_corporate_data=has_corporate_data,
    )
    response = provider.generate(prompt, SYSTEM_PROMPT)
    code = extract_code(response.content)
    return code, response
