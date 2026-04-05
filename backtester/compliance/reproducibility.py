"""Reproducibility: rebuild strategy from commands and compare signals."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backtester.compliance.manifest import CommandsUpToVersion, get_commands_up_to_version
from backtester.engine.executor import execute_strategy
from backtester.engine.invariants import (
    SignalComparison,
    compare_signals,
    diagnostic_bullets_for_comparison,
    format_signal_diff_for_prompt,
    signals_match,
)
from backtester.llm.base import BaseLLMProvider


@dataclass
class ReproducibilityResult:
    passed: bool
    choice_required: bool = False
    summary: str = ""
    summary_bullets: list[str] = field(default_factory=list)
    options: list[dict] = field(default_factory=list)
    original_signals_df: pd.DataFrame | None = None
    rebuild1_signals_df: pd.DataFrame | None = None
    rebuild2_signals_df: pd.DataFrame | None = None
    comparison_original_vs_rebuild1: SignalComparison | None = None
    error: str = ""


def _run_code_on_data(code: str, data_df: pd.DataFrame) -> pd.DataFrame | None:
    """Execute strategy code on data; return signals DataFrame or None on failure."""
    from backtester.engine.executor import ExecutionResult

    result: ExecutionResult = execute_strategy(code, data_df)
    if not result.success or result.output_df is None:
        return None
    return result.output_df


def _rebuild_strategy(
    provider: BaseLLMProvider,
    commands: CommandsUpToVersion,
    data_df: pd.DataFrame,
    interval: str,
    has_corporate_data: bool,
) -> str | None:
    """
    Rebuild strategy from initial_strategy + change_requests.
    Returns final code or None on failure.
    """
    from backtester.engine.iteration_engine import run_iteration_loop
    from backtester.engine.refine_engine import run_refine_turn
    from backtester.engine.session import RefineSession

    result = run_iteration_loop(
        provider=provider,
        strategy_description=commands.initial_strategy,
        data_df=data_df,
        max_iterations=10,
        verbose=False,
        interval=interval,
        has_corporate_data=has_corporate_data,
        on_progress=None,
    )
    if not result.success or not result.code:
        return None
    current_code = result.code

    for change_request in commands.change_requests:
        session = RefineSession.new_session(
            ticker=commands.ticker,
            interval=interval,
            strategy_description=commands.initial_strategy,
            data_path="",
            current_code=current_code,
        )
        refine_result = run_refine_turn(
            session=session,
            change_request=change_request,
            provider=provider,
            df=data_df,
            baseline_signals_df=None,
            max_attempts=5,
            verbose=False,
            chart_image=None,
        )
        if not refine_result.success:
            return None
        current_code = refine_result.code

    return current_code


def _summarize_three_way_diff(
    provider: BaseLLMProvider,
    original_df: pd.DataFrame,
    rebuild1_df: pd.DataFrame,
    rebuild2_df: pd.DataFrame,
    comp_ovs1: SignalComparison,
    comp_ovs2: SignalComparison,
    comp_1vs2: SignalComparison,
) -> tuple[str, list[str]]:
    """Use LLM to summarize differences between original, rebuild1, rebuild2. Returns (summary, bullets)."""
    # Structured diagnostics from actual comparison data (counts and likely causes)
    diag_ovs1 = diagnostic_bullets_for_comparison(comp_ovs1, "Original", "Rebuild 1")
    diag_ovs2 = diagnostic_bullets_for_comparison(comp_ovs2, "Original", "Rebuild 2")
    diag_1vs2 = diagnostic_bullets_for_comparison(comp_1vs2, "Rebuild 1", "Rebuild 2")
    structured_diag = "\n".join(
        ["Structured comparison (counts and possible causes):"]
        + diag_ovs1 + diag_ovs2 + diag_1vs2
    )
    prompt = f"""You are analyzing reproducibility of a trading strategy. We rebuilt the strategy from the user's natural-language commands twice. Below are signal comparisons.

{structured_diag}

Detailed diffs (dates added/removed):

Original (saved version) vs Rebuild 1:
{format_signal_diff_for_prompt(comp_ovs1, max_dates=15)}

Original vs Rebuild 2:
{format_signal_diff_for_prompt(comp_ovs2, max_dates=15)}

Rebuild 1 vs Rebuild 2:
{format_signal_diff_for_prompt(comp_1vs2, max_dates=15)}

Write a short summary (2-3 sentences) and then a bullet list explaining:
- Key differences (which signal sets differ and how, using the counts/dates above)
- Specific reasons this might have happened: e.g. different indicator parameters (RSI period, threshold), different date/bar boundary handling, floating-point comparison (<= vs <), or ambiguous wording in a refinement command—tie to the actual numbers/dates where possible
- Caveats the user should be aware of when choosing which version to use for paper trading

Format your response as:
SUMMARY:
<your summary>

BULLETS:
- <bullet 1>
- <bullet 2>
- ...
"""
    resp = provider.generate(prompt, "You are a concise technical analyst. Be clear and neutral.")
    text = resp.content.strip()
    summary = ""
    bullets: list[str] = []
    if "BULLETS:" in text:
        parts = text.split("BULLETS:", 1)
        summary = parts[0].replace("SUMMARY:", "").strip()
        bullet_block = parts[1].strip()
        for line in bullet_block.split("\n"):
            line = line.strip()
            if line.startswith("-"):
                bullets.append(line[1:].strip())
            elif line:
                bullets.append(line)
    else:
        summary = text
    # Prepend structured diagnostics so user always sees concrete counts and causes
    bullets = diag_ovs1 + diag_ovs2 + diag_1vs2 + bullets
    return summary, bullets


def run_reproducibility(
    session_id: str,
    version_id: str,
    provider: BaseLLMProvider,
    data_df: pd.DataFrame | None = None,
) -> ReproducibilityResult:
    """
    Run reproducibility check for the given version.
    If data_df is None, data is loaded using run params from the manifest.
    If signals match on first rebuild -> passed.
    If not, rebuild again and compare all three; then summarize and set choice_required.
    """
    from backtester.agent.session import AGENT_SESSIONS_DIR
    from backtester.data.corporate import (
        detect_corporate_needs,
        download_corporate_data,
        merge_corporate_data,
    )
    from backtester.data.downloader import download_data
    from backtester.data.interval import clamp_date_range, detect_interval

    result = ReproducibilityResult(passed=False)

    commands = get_commands_up_to_version(session_id, version_id)
    if commands is None:
        result.error = "Version not found in manifest or manifest invalid (first entry must be run_backtest)."
        return result

    version_dir = AGENT_SESSIONS_DIR / session_id / "strategy_versions"
    code_path = version_dir / f"{version_id}.py"
    if not code_path.exists():
        result.error = "Strategy version file not found."
        return result

    original_code = code_path.read_text(encoding="utf-8")

    if data_df is None:
        start, end, _ = clamp_date_range(
            commands.start_date,
            commands.end_date,
            commands.interval,
        )
        try:
            data_df = download_data(
                commands.ticker,
                start,
                end,
                interval=commands.interval,
            )
        except Exception as e:
            result.error = f"Failed to load data: {e}"
            return result

        corporate_needs = detect_corporate_needs(commands.initial_strategy)
        if corporate_needs:
            try:
                corporate = download_corporate_data(
                    commands.ticker,
                    corporate_needs,
                    start,
                    end,
                )
                data_df = merge_corporate_data(data_df, corporate)
            except Exception:
                pass

    from backtester.data.corporate import has_corporate_columns

    interval = commands.interval
    has_corporate = has_corporate_columns(data_df)

    signals_original = _run_code_on_data(original_code, data_df)
    if signals_original is None or signals_original.empty:
        result.error = "Original version code failed to run on data."
        return result

    code_rebuild1 = _rebuild_strategy(
        provider, commands, data_df, interval, has_corporate
    )
    if code_rebuild1 is None:
        result.error = "First rebuild from commands failed (code generation or refine step failed)."
        return result

    signals_rebuild1 = _run_code_on_data(code_rebuild1, data_df)
    if signals_rebuild1 is None or signals_rebuild1.empty:
        result.error = "First rebuilt code failed to run on data."
        return result

    comp1 = compare_signals(signals_original, signals_rebuild1)
    result.comparison_original_vs_rebuild1 = comp1
    result.original_signals_df = signals_original
    result.rebuild1_signals_df = signals_rebuild1

    if signals_match(comp1):
        result.passed = True
        result.summary = "Signals match: strategy is reproducible from your commands."
        return result

    code_rebuild2 = _rebuild_strategy(
        provider, commands, data_df, interval, has_corporate
    )
    if code_rebuild2 is None:
        result.summary = "First rebuild did not match original. A second rebuild was run but failed (code generation or a refine step failed), so only the original and first rebuild are available."
        result.summary_bullets = [
            "Rebuilding from the same commands produced different signals the first time.",
            "A second rebuild was attempted from the same commands but failed (e.g. LLM returned invalid code or a refine step failed). You can run the check again to retry.",
        ] + diagnostic_bullets_for_comparison(comp1, "Original", "Rebuild 1")
        result.options = [
            {"id": "original", "label": "Use original saved version", "description": "The strategy code as saved when you ran backtest/refine."},
            {"id": "rebuild_1", "label": "Use first rebuild", "description": "Code rebuilt from your commands (first attempt)."},
        ]
        result.choice_required = True
        return result

    signals_rebuild2 = _run_code_on_data(code_rebuild2, data_df)
    if signals_rebuild2 is None or signals_rebuild2.empty:
        result.summary = "First rebuild did not match original. A second rebuild was run but the generated code failed to execute on the data, so only the original and first rebuild are available."
        result.summary_bullets = [
            "A second rebuild was attempted; the generated code failed when run on the same data (e.g. runtime error). You can run the check again to retry.",
        ] + diagnostic_bullets_for_comparison(comp1, "Original", "Rebuild 1")
        result.options = [
            {"id": "original", "label": "Use original saved version", "description": "The strategy code as saved when you ran backtest/refine."},
            {"id": "rebuild_1", "label": "Use first rebuild", "description": "Code rebuilt from your commands (first attempt)."},
        ]
        result.choice_required = True
        return result

    result.rebuild2_signals_df = signals_rebuild2
    comp_ovs2 = compare_signals(signals_original, signals_rebuild2)
    comp_1vs2 = compare_signals(signals_rebuild1, signals_rebuild2)

    summary_text, bullets = _summarize_three_way_diff(
        provider,
        signals_original,
        signals_rebuild1,
        signals_rebuild2,
        comp1,
        comp_ovs2,
        comp_1vs2,
    )
    result.summary = summary_text
    result.summary_bullets = bullets
    result.choice_required = True
    result.options = [
        {"id": "original", "label": "Use original saved version", "description": "The strategy code as saved when you ran backtest/refine."},
        {"id": "rebuild_1", "label": "Use first rebuild", "description": "Code rebuilt from your commands (first attempt)."},
        {"id": "rebuild_2", "label": "Use second rebuild", "description": "Code rebuilt from your commands (second attempt)."},
    ]
    return result
