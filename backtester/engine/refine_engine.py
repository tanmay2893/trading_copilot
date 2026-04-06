"""Refinement engine: orchestrates a single turn of interactive strategy modification.

Reuses the existing executor and validator pipeline, adding conversation-aware
prompt construction and automatic fix retries.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backtester.engine.code_generator import _df_info, extract_code
from backtester.engine.executor import execute_strategy
from backtester.engine.session import ConversationTurn, RefineSession
from backtester.engine.invariants import (
    check_refinement_invariants,
    compare_signals,
    format_signal_diff_for_prompt,
)
from backtester.data.corporate import detect_corporate_needs
from backtester.engine.validator import validate_output
from backtester.llm.base import BaseLLMProvider
from backtester.prompts.templates import (
    REFINE_SYSTEM_PROMPT,
    build_change_summary_prompt,
    build_refine_fix_prompt,
    build_refine_prompt,
)
from backtester.ui import print_iteration_status, step


@dataclass
class RefineResult:
    success: bool = False
    code: str = ""
    signals_df: pd.DataFrame | None = None
    indicator_df: pd.DataFrame | None = None
    indicator_columns: list[str] = field(default_factory=list)
    summary: str = ""
    attempts: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    error_message: str = ""


def run_refine_turn(
    session: RefineSession,
    change_request: str,
    provider: BaseLLMProvider,
    df: pd.DataFrame,
    baseline_signals_df: pd.DataFrame | None = None,
    max_attempts: int = 5,
    verbose: bool = False,
    chart_image: str | None = None,
    is_selected_version: bool = False,
) -> RefineResult:
    """Execute a single refinement turn: modify code, execute, validate, auto-fix.

    *chart_image*: optional base64-encoded PNG for visual LLM context.
    """
    from backtester.data.corporate import has_corporate_columns

    result = RefineResult()
    code_before = session.current_code
    current_code = session.current_code

    cols, dtypes, sample, count = _df_info(df)
    conversation_context = session.to_prompt_context()
    last_error: dict = {}
    corp_flag = has_corporate_columns(df)
    snap = set(getattr(session, "corporate_needs_snapshot", None) or [])
    corp_needs_for_validation = snap | detect_corporate_needs(session.strategy_description or "")
    images = [chart_image] if chart_image else None

    # Pre-compute baseline counts for prompt context if available.
    baseline_buy_count = None
    baseline_sell_count = None
    if baseline_signals_df is not None and not baseline_signals_df.empty:
        baseline_buy_count = int((baseline_signals_df["Signal"] == "BUY").sum())
        baseline_sell_count = int((baseline_signals_df["Signal"] == "SELL").sum())

    for attempt in range(1, max_attempts + 1):
        result.attempts = attempt

        if attempt == 1:
            with step("Refining strategy", f"[attempt {attempt}/{max_attempts}]"):
                prompt = build_refine_prompt(
                    current_code=current_code,
                    change_request=change_request,
                    strategy_description=session.strategy_description,
                    conversation_history=conversation_context,
                    data_columns=cols,
                    data_dtypes=dtypes,
                    sample_rows=sample,
                    row_count=count,
                    data_interval=session.interval,
                    has_corporate_data=corp_flag,
                    baseline_buy_count=baseline_buy_count,
                    baseline_sell_count=baseline_sell_count,
                    is_selected_version=is_selected_version,
                )
                if chart_image:
                    prompt += (
                        "\n\n## Chart Screenshot\n"
                        "A chart screenshot is attached. Use it to: (1) see where BUY/SELL "
                        "markers appear relative to price and any indicators; (2) identify the "
                        "events or dates you believe are important based on the user's request; "
                        "and (3) ensure the refined implementation matches the user's intent.\n"
                    )
                llm_resp = provider.generate(prompt, REFINE_SYSTEM_PROMPT, images=images)
                result.total_input_tokens += llm_resp.input_tokens
                result.total_output_tokens += llm_resp.output_tokens
                current_code = extract_code(llm_resp.content)
        else:
            print_iteration_status(
                attempt, max_attempts,
                last_error.get("error_type", "UNKNOWN"),
                last_error.get("message", "")[:100],
            )
            with step("Fixing refinement", f"[attempt {attempt}/{max_attempts}]"):
                prompt = build_refine_fix_prompt(
                    current_code=current_code,
                    change_request=change_request,
                    strategy_description=session.strategy_description,
                    error_type=last_error.get("error_type", "UNKNOWN"),
                    error_message=last_error.get("message", ""),
                    traceback_str=last_error.get("traceback", ""),
                    data_columns=cols,
                    data_interval=session.interval,
                    has_corporate_data=corp_flag,
                    is_selected_version=is_selected_version,
                )
                llm_resp = provider.generate(prompt, REFINE_SYSTEM_PROMPT)
                result.total_input_tokens += llm_resp.input_tokens
                result.total_output_tokens += llm_resp.output_tokens
                current_code = extract_code(llm_resp.content)

        result.code = current_code

        with step("Running backtest", f"[attempt {attempt}/{max_attempts}]") as s:
            exec_result = execute_strategy(current_code, df)
            if exec_result.success:
                s.succeed(f"{exec_result.signal_count} signals in {exec_result.duration:.1f}s")
            else:
                s.fail(f"{exec_result.error_type}: {exec_result.error_message[:80]}")

        if not exec_result.success:
            last_error = {
                "error_type": exec_result.error_type,
                "message": exec_result.error_message,
                "traceback": exec_result.traceback_str,
            }
            continue

        with step("Validating output") as s:
            validation = validate_output(
                exec_result.output_df,
                df,
                strategy_description=session.strategy_description,
                corporate_needs=corp_needs_for_validation or None,
                strategy_code=current_code,
            )
            if validation.valid:
                s.succeed(f"all {len(validation.test_results)} tests passed")
            else:
                s.fail(f"{len(validation.issues)} issue(s)")

        if not validation.valid:
            last_error = {
                "error_type": "VALIDATION_FAILURE",
                "message": "; ".join(validation.issues),
                "traceback": "",
            }
            continue

        # --- Phase 4: Invariant checks against baseline behaviour (optional) ---
        if baseline_signals_df is not None:
            invariant_issues = check_refinement_invariants(
                baseline_signals_df=baseline_signals_df,
                new_signals_df=exec_result.output_df,
                change_text=change_request,
            )
            if invariant_issues:
                comp = compare_signals(baseline_signals_df, exec_result.output_df)
                diff_text = format_signal_diff_for_prompt(comp)
                last_error = {
                    "error_type": "INVARIANT_VIOLATION",
                    "message": "; ".join(invariant_issues) + f"\n\nSignal diff:\n{diff_text}",
                    "traceback": "",
                }
                continue

        result.success = True
        result.signals_df = exec_result.output_df
        result.indicator_df = exec_result.indicator_df
        result.indicator_columns = exec_result.indicator_columns

        with step("Summarizing changes"):
            summary, in_tok, out_tok = _generate_change_summary(
                provider, code_before, current_code, change_request,
            )
            result.summary = summary
            result.total_input_tokens += in_tok
            result.total_output_tokens += out_tok

        turn = ConversationTurn(
            request=change_request,
            code_before=code_before,
            code_after=current_code,
            summary=summary,
            attempt_count=attempt,
        )
        session.add_turn(turn)
        return result

    result.success = False
    result.error_message = last_error.get("message", "Unknown error")
    return result


def _generate_change_summary(
    provider: BaseLLMProvider,
    code_before: str,
    code_after: str,
    change_request: str,
) -> tuple[str, int, int]:
    """Ask the LLM to summarize what changed. Returns (summary, input_tokens, output_tokens)."""
    prompt = build_change_summary_prompt(code_before, code_after, change_request)
    resp = provider.generate(prompt, "You summarize code changes concisely.")
    return resp.content.strip(), resp.input_tokens, resp.output_tokens
