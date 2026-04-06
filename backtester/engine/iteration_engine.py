"""Smart iteration engine: the core loop that generates, runs, validates, and fixes strategy code.

Orchestrates code generation → execution → validation → intelligent retry
with error classification, context accumulation, and anti-loop detection.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

from backtester.progress_narrative import (
    CODE_FROM_RULES,
    DIAGNOSE_STUCK,
    DRAFTING_FIX,
    FIX_EXECUTION,
    QUALITY_REVIEW,
    REGENERATE,
    REVIEW_FIX,
    SIMULATE_TRADES,
    UNDERSTANDING_ISSUE,
    VALIDATE_SIGNALS,
    detail_attempt,
    detail_code_lines,
    detail_fix_error,
    detail_review_auto_accept,
    detail_review_outcome,
    detail_signals,
    detail_validation_success,
)
from backtester.config import RUNS_DIR
from backtester.engine.code_generator import (
    generate_anti_loop_code,
    generate_fix_code,
    generate_review_fix_code,
    generate_strategy_code,
)
from backtester.engine.context_engine import RunArtifacts, build_context
from backtester.engine.executor import ExecutionResult, execute_strategy
from backtester.engine.invariants import (
    check_refinement_invariants,
)
from backtester.data.corporate import detect_corporate_needs, relaxation_drops_earnings_constraint
from backtester.engine.validator import ValidationResult, validate_output
from backtester.llm.base import BaseLLMProvider
from backtester.prompts.templates import SYSTEM_PROMPT
from backtester.ui import (
    console,
    print_code,
    print_error_box,
    print_iteration_status,
    step,
)

ANTI_LOOP_THRESHOLD = 3
MAX_REVIEW_REJECTIONS = 2


@dataclass
class IterationResult:
    success: bool = False
    signals_df: pd.DataFrame | None = None
    code: str = ""
    attempts: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    error_history: list[dict] = field(default_factory=list)
    test_failures: list[str] = field(default_factory=list)
    needs_intervention: bool = False
    diagnosis: object | None = None     # DiagnosisResult when needs_intervention is True
    indicator_df: pd.DataFrame | None = None
    indicator_columns: list[str] = field(default_factory=list)


ERROR_TYPE_MAP = {
    "SyntaxError": "SYNTAX_ERROR",
    "IndentationError": "SYNTAX_ERROR",
    "ImportError": "IMPORT_ERROR",
    "ModuleNotFoundError": "IMPORT_ERROR",
    "KeyError": "DATA_ERROR",
    "IndexError": "DATA_ERROR",
    "TypeError": "RUNTIME_ERROR",
    "ValueError": "RUNTIME_ERROR",
    "ZeroDivisionError": "RUNTIME_ERROR",
    "AttributeError": "RUNTIME_ERROR",
    "TIMEOUT": "TIMEOUT",
}


def classify_error(error_type: str) -> str:
    return ERROR_TYPE_MAP.get(error_type, "RUNTIME_ERROR")


def run_iteration_loop(
    provider: BaseLLMProvider,
    strategy_description: str,
    data_df: pd.DataFrame,
    max_iterations: int = 10,
    verbose: bool = False,
    interval: str = "1d",
    has_corporate_data: bool = False,
    corporate_needs: set | None = None,
    on_progress: Callable | None = None,
) -> IterationResult:
    from backtester.engine.strategy_analyzer import review_strategy_code, diagnose_stuck_loop

    def _emit(step_name: str, status: str, detail: str = ""):
        if on_progress:
            on_progress(step_name, status, detail)

    result = IterationResult()
    error_counter: Counter[str] = Counter()
    anti_loop_cycles = 0
    consecutive_review_rejections = 0
    current_code = ""
    pending_review_fix: dict | None = None
    is_review_fix_attempt = False

    for attempt in range(1, max_iterations + 1):
        result.attempts = attempt

        # --- Phase 1: Generate or Fix code ---
        if attempt == 1:
            _emit(CODE_FROM_RULES, "running", detail_attempt(attempt, max_iterations))
            with step(CODE_FROM_RULES, f"[{provider.__class__.__name__}]") as s:
                code, llm_resp = generate_strategy_code(
                    provider, strategy_description, data_df,
                    interval=interval, has_corporate_data=has_corporate_data,
                    corporate_needs=corporate_needs,
                )
                result.total_input_tokens += llm_resp.input_tokens
                result.total_output_tokens += llm_resp.output_tokens
                current_code = code
                s.succeed(detail_code_lines(_count_lines(code)))
            _emit(CODE_FROM_RULES, "success", detail_code_lines(_count_lines(code)))
            is_review_fix_attempt = False
        elif pending_review_fix is not None:
            review_data = pending_review_fix
            pending_review_fix = None
            is_review_fix_attempt = True
            _emit(REVIEW_FIX, "running", detail_attempt(attempt, max_iterations))
            print_iteration_status(
                attempt, max_iterations, "REVIEW",
                "; ".join(review_data["issues"][:2])[:100],
            )
            with step(REVIEW_FIX, f"[attempt {attempt}/{max_iterations}]"):
                code, llm_resp = generate_review_fix_code(
                    provider, strategy_description, current_code,
                    review_data["issues"],
                    review_data["fix_instructions"],
                    data_df,
                    interval=interval, has_corporate_data=has_corporate_data,
                    corporate_needs=corporate_needs,
                )
                result.total_input_tokens += llm_resp.input_tokens
                result.total_output_tokens += llm_resp.output_tokens
                current_code = code
            _emit(REVIEW_FIX, "success")
        else:
            is_review_fix_attempt = False
            last_err = result.error_history[-1] if result.error_history else {}
            err_type = last_err.get("error_type", "UNKNOWN")
            err_msg = last_err.get("message", "")
            err_tb = last_err.get("traceback", "")

            error_signature = f"{err_type}:{err_msg[:80]}"
            error_counter[error_signature] += 1

            if error_counter[error_signature] >= ANTI_LOOP_THRESHOLD:
                anti_loop_cycles += 1

                if anti_loop_cycles >= 2:
                    print_iteration_status(
                        attempt, max_iterations, "STUCK",
                        f"Anti-loop fired {anti_loop_cycles}x — diagnosing via LLM"
                    )
                    _emit(DIAGNOSE_STUCK, "running")
                    with step(DIAGNOSE_STUCK, "LLM") as s:
                        diag = diagnose_stuck_loop(
                            provider=provider,
                            strategy_description=strategy_description,
                            error_history=result.error_history,
                            last_code=current_code,
                            row_count=len(data_df),
                            interval=interval,
                            columns=list(data_df.columns),
                            has_corporate_data=has_corporate_data,
                        )
                        result.total_input_tokens += diag.input_tokens
                        result.total_output_tokens += diag.output_tokens
                        s.succeed(diag.root_cause)
                    _emit(DIAGNOSE_STUCK, "success", diag.root_cause)

                    if (
                        diag.root_cause in ("strategy_too_restrictive", "data_issue")
                        and diag.revised_strategy
                        and not relaxation_drops_earnings_constraint(
                            strategy_description, diag.revised_strategy
                        )
                    ):
                        result.needs_intervention = True
                        result.diagnosis = diag
                        return result

                print_iteration_status(
                    attempt, max_iterations, "ANTI-LOOP",
                    f"Same error {error_counter[error_signature]}x — forcing new approach"
                )
                _emit(REGENERATE, "running", detail_attempt(attempt, max_iterations))
                with step(REGENERATE, f"[attempt {attempt}/{max_iterations}]"):
                    code, llm_resp = generate_anti_loop_code(
                        provider, strategy_description, current_code,
                        f"{err_type}: {err_msg}", error_counter[error_signature], data_df,
                        interval=interval, has_corporate_data=has_corporate_data,
                        corporate_needs=corporate_needs,
                    )
                    result.total_input_tokens += llm_resp.input_tokens
                    result.total_output_tokens += llm_resp.output_tokens
                    current_code = code
                    error_counter.clear()
                _emit(REGENERATE, "success")
            else:
                include_sample = attempt >= 4
                print_iteration_status(attempt, max_iterations, err_type, err_msg[:100])
                _emit(FIX_EXECUTION, "running", f"{err_type} · {detail_attempt(attempt, max_iterations)}")
                with step(FIX_EXECUTION, f"[attempt {attempt}/{max_iterations}]"):
                    code, llm_resp = generate_fix_code(
                        provider, strategy_description, current_code,
                        err_type, err_msg, err_tb,
                        result.error_history, data_df,
                        include_sample=include_sample,
                        interval=interval, has_corporate_data=has_corporate_data,
                        corporate_needs=corporate_needs,
                    )
                    result.total_input_tokens += llm_resp.input_tokens
                    result.total_output_tokens += llm_resp.output_tokens
                    current_code = code
                _emit(FIX_EXECUTION, "success")

        if verbose:
            print_code(current_code, f"Strategy (attempt {attempt})")

        result.code = current_code

        # --- Phase 2: Execute ---
        _emit(SIMULATE_TRADES, "running", detail_attempt(attempt, max_iterations))
        with step(SIMULATE_TRADES, f"[attempt {attempt}/{max_iterations}]") as s:
            exec_result = execute_strategy(current_code, data_df)
            if exec_result.success:
                s.succeed(f"{exec_result.signal_count} signals in {exec_result.duration:.1f}s")
            else:
                s.fail(f"{exec_result.error_type}: {exec_result.error_message[:80]}")

        if not exec_result.success:
            _emit(SIMULATE_TRADES, "failed", detail_fix_error(exec_result.error_type, exec_result.error_message))
            if not is_review_fix_attempt:
                consecutive_review_rejections = 0
            result.error_history.append({
                "attempt": attempt,
                "error_type": classify_error(exec_result.error_type),
                "raw_type": exec_result.error_type,
                "message": exec_result.error_message,
                "traceback": exec_result.traceback_str,
            })
            continue

        _emit(SIMULATE_TRADES, "success", detail_signals(exec_result.signal_count))

        # --- Phase 3: Validate ---
        _emit(VALIDATE_SIGNALS, "running")
        with step(VALIDATE_SIGNALS) as s:
            validation = validate_output(
                exec_result.output_df,
                data_df,
                strategy_description=strategy_description,
                corporate_needs=corporate_needs,
                strategy_code=current_code,
            )
            if validation.valid:
                s.succeed(f"all {len(validation.test_results)} tests passed")
            else:
                s.fail(f"{len(validation.issues)} issue(s)")

        if not validation.valid:
            _emit(VALIDATE_SIGNALS, "failed", "; ".join(validation.issues)[:100])
            if not is_review_fix_attempt:
                consecutive_review_rejections = 0
            result.test_failures = validation.issues
            result.error_history.append({
                "attempt": attempt,
                "error_type": "VALIDATION_FAILURE",
                "raw_type": "VALIDATION_FAILURE",
                "message": "; ".join(validation.issues),
                "traceback": "",
            })
            continue

        _emit(VALIDATE_SIGNALS, "success", detail_validation_success(len(validation.test_results)))

        # --- Phase 4: LLM Code Review ---
        if consecutive_review_rejections >= MAX_REVIEW_REJECTIONS:
            _emit(QUALITY_REVIEW, "success", detail_review_auto_accept(consecutive_review_rejections))
            console.print(
                f"  [yellow]⚠[/] Accepting code after {consecutive_review_rejections} consecutive "
                f"review rejections (execution + validation passed)"
            )
        else:
            _emit(QUALITY_REVIEW, "running")
            with step(QUALITY_REVIEW, "LLM") as s:
                review = review_strategy_code(
                    provider=provider,
                    strategy_description=strategy_description,
                    generated_code=current_code,
                    signals_df=exec_result.output_df,
                    data_interval=interval,
                    has_corporate_data=has_corporate_data,
                    data_df=data_df,
                )
                result.total_input_tokens += review.input_tokens
                result.total_output_tokens += review.output_tokens

                if review.verdict == "ok":
                    s.succeed("approved")
                else:
                    issue_preview = "; ".join(review.issues[:2])[:80] if review.issues else "issues found"
                    s.fail(issue_preview)

            if review.verdict == "fix" and review.issues:
                _emit(QUALITY_REVIEW, "failed", "; ".join(review.issues[:2])[:80])
                consecutive_review_rejections += 1
                result.error_history.append({
                    "attempt": attempt,
                    "error_type": "CODE_REVIEW",
                    "raw_type": "CODE_REVIEW",
                    "message": "; ".join(review.issues),
                    "traceback": "",
                })
                pending_review_fix = {
                    "issues": review.issues,
                    "fix_instructions": review.fix_instructions or "; ".join(review.issues),
                }
                continue

            _emit(QUALITY_REVIEW, "success", detail_review_outcome(True, ""))

        # --- Success ---
        result.success = True
        result.signals_df = exec_result.output_df
        result.indicator_df = exec_result.indicator_df
        result.indicator_columns = exec_result.indicator_columns
        return result

    result.success = False
    return result


def run_fix_loop(
    provider: BaseLLMProvider,
    issue: str,
    artifacts: RunArtifacts,
    data_df: pd.DataFrame,
    max_iterations: int = 5,
    verbose: bool = False,
    interval: str = "1d",
    chart_image: str | None = None,
    is_selected_version: bool = False,
) -> IterationResult:
    """Fix loop for user-reported issues using context engineering.

    *chart_image*: optional base64-encoded PNG of the current chart
    (fully zoomed out) to give the LLM visual context.
    *is_selected_version*: when True, the code is the version the user selected in the strategies panel; emphasize that it must be fixed while applying the user's change.
    """
    result = IterationResult()
    result.code = artifacts.generated_code

    with step(UNDERSTANDING_ISSUE, "context engineering"):
        context = build_context(issue, artifacts)

    chart_note = ""
    if chart_image:
        chart_note = (
            "\n\n## Chart Screenshot\n"
            "A fully zoomed-out chart screenshot is attached as an image. "
            "Correlate BUY/SELL markers with the price series and any visible "
            "indicators. Use this visual context to understand which events "
            "or dates the user believes are wrong (too many, too few, or "
            "mis-timed signals) and adjust the logic accordingly.\n"
            "If the issue is only that an SMA/EMA line does not match the **price** scale, check whether "
            "that series is a **volume** (or other non-price) moving average — if so, different scale is "
            "correct; do not \"fix\" by converting it to price SMA unless the user explicitly asked.\n"
        )

    selected_note = ""
    if is_selected_version:
        selected_note = (
            "\n## Important: Selected version\n"
            "The code in context below is the strategy version the user selected in the strategies panel. "
            "You MUST fix this code to resolve the issue while still applying the user's change. Do not use any other code as the base.\n\n"
        )

    fix_prompt = f"""\
The user reports this issue with the strategy output:
"{issue}"
{selected_note}
## Relevant Context
{context}
{chart_note}
Fix the Strategy class to resolve this issue. Output ONLY the full Python code."""

    images = [chart_image] if chart_image else None
    current_code = artifacts.generated_code

    for attempt in range(1, max_iterations + 1):
        result.attempts = attempt

        with step(DRAFTING_FIX, f"[attempt {attempt}/{max_iterations}]"):
            prompt = fix_prompt if attempt == 1 else _build_refix_prompt(
                issue, current_code, result.error_history[-1] if result.error_history else {},
            )
            llm_resp = provider.generate(
                prompt, SYSTEM_PROMPT,
                images=images if attempt == 1 else None,
            )
            result.total_input_tokens += llm_resp.input_tokens
            result.total_output_tokens += llm_resp.output_tokens

            from backtester.engine.code_generator import extract_code
            current_code = extract_code(llm_resp.content)

        if verbose:
            print_code(current_code, f"Fixed Strategy (attempt {attempt})")

        result.code = current_code

        with step(SIMULATE_TRADES, f"[attempt {attempt}/{max_iterations}]") as s:
            exec_result = execute_strategy(current_code, data_df)
            if exec_result.success:
                s.succeed(detail_signals(exec_result.signal_count))
            else:
                s.fail(f"{exec_result.error_type}")

        if not exec_result.success:
            result.error_history.append({
                "attempt": attempt,
                "error_type": classify_error(exec_result.error_type),
                "raw_type": exec_result.error_type,
                "message": exec_result.error_message,
                "traceback": exec_result.traceback_str,
            })
            continue

        with step(VALIDATE_SIGNALS) as s:
            _corp = detect_corporate_needs(artifacts.strategy_description or "")
            validation = validate_output(
                exec_result.output_df,
                data_df,
                strategy_description=artifacts.strategy_description,
                corporate_needs=_corp if _corp else None,
                strategy_code=current_code,
            )
            if validation.valid:
                s.succeed("all tests passed")
            else:
                s.fail(f"{len(validation.issues)} issue(s)")

        if not validation.valid:
            result.error_history.append({
                "attempt": attempt,
                "error_type": "VALIDATION_FAILURE",
                "raw_type": "VALIDATION_FAILURE",
                "message": "; ".join(validation.issues),
                "traceback": "",
            })
            continue

        # Optional invariant checks against the previous signals (if present).
        if artifacts.signals_df is not None:
            invariant_issues = check_refinement_invariants(
                baseline_signals_df=artifacts.signals_df,
                new_signals_df=exec_result.output_df,
                change_text=issue,
            )
            if invariant_issues:
                # Treat this as a soft failure so the LLM can be guided by
                # the violation message on the next attempt.
                result.error_history.append({
                    "attempt": attempt,
                    "error_type": "INVARIANT_VIOLATION",
                    "raw_type": "INVARIANT_VIOLATION",
                    "message": "; ".join(invariant_issues),
                    "traceback": "",
                })
                continue

        result.success = True
        result.signals_df = exec_result.output_df
        result.indicator_df = exec_result.indicator_df
        result.indicator_columns = exec_result.indicator_columns
        return result

    result.success = False
    return result


def save_run_artifacts(
    ticker: str,
    strategy_description: str,
    iteration_result: IterationResult,
    data_df: pd.DataFrame,
    interval: str = "1d",
) -> Path:
    """Persist run artifacts for later `fix` command usage."""
    run_dir = RUNS_DIR / f"{ticker}_{int(time.time())}"
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "strategy.py").write_text(iteration_result.code, encoding="utf-8")
    (run_dir / "description.txt").write_text(strategy_description, encoding="utf-8")
    data_df.to_csv(run_dir / "data.csv", index=False)

    if iteration_result.signals_df is not None:
        iteration_result.signals_df.to_csv(run_dir / "signals.csv", index=False)

    if iteration_result.indicator_df is not None:
        iteration_result.indicator_df.to_csv(run_dir / "indicator_data.csv", index=False)

    meta = {
        "success": iteration_result.success,
        "attempts": iteration_result.attempts,
        "total_input_tokens": iteration_result.total_input_tokens,
        "total_output_tokens": iteration_result.total_output_tokens,
        "error_history": iteration_result.error_history,
        "test_failures": iteration_result.test_failures,
        "interval": interval,
        "indicator_columns": iteration_result.indicator_columns,
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    latest_link = RUNS_DIR / "latest"
    latest_link.write_text(str(run_dir), encoding="utf-8")
    return run_dir


def load_latest_artifacts() -> RunArtifacts | None:
    """Load artifacts from the most recent run."""
    latest_link = RUNS_DIR / "latest"
    if not latest_link.exists():
        return None

    run_dir = Path(latest_link.read_text().strip())
    if not run_dir.exists():
        return None

    artifacts = RunArtifacts()

    desc_path = run_dir / "description.txt"
    if desc_path.exists():
        artifacts.strategy_description = desc_path.read_text(encoding="utf-8")

    code_path = run_dir / "strategy.py"
    if code_path.exists():
        artifacts.generated_code = code_path.read_text(encoding="utf-8")

    data_path = run_dir / "data.csv"
    if data_path.exists():
        artifacts.data_df = pd.read_csv(data_path)

    signals_path = run_dir / "signals.csv"
    if signals_path.exists():
        artifacts.signals_df = pd.read_csv(signals_path)

    meta_path = run_dir / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        artifacts.error_history = meta.get("error_history", [])
        artifacts.test_failures = meta.get("test_failures", [])
        artifacts.interval = meta.get("interval", "1d")

    return artifacts


def _build_refix_prompt(issue: str, code: str, last_error: dict) -> str:
    return f"""\
Previous fix attempt FAILED. The user's original issue: "{issue}"

Current code:
```python
{code}
```

Error: [{last_error.get('error_type', 'UNKNOWN')}] {last_error.get('message', '')}

Fix the code. Output ONLY the complete fixed Python code."""


def _count_lines(code: str) -> int:
    return len([l for l in code.strip().splitlines() if l.strip()])
