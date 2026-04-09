"""Agent tool implementations — thin async wrappers around existing engines.

Each tool handler receives the ChatSession, emits ProgressEvents, and returns
a structured dict that the orchestrator feeds back to the LLM.
"""

from __future__ import annotations

import asyncio
import json
import math
import numbers
import statistics
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable, Awaitable

import pandas as pd

from backtester.agent.events import (
    CodeEvent,
    ErrorEvent,
    ProgressEvent,
    StrategyVersionEvent,
    TableEvent,
    TextEvent,
)
from backtester.progress_narrative import (
    ALIGN_STRATEGY,
    ANALYZE_RESULTS,
    BACKTEST_DONE,
    CHART_ATTACHED,
    CORPORATE_CONTEXT,
    CUSTOM_ANALYSIS,
    FETCH_PREVIEW,
    FIX_STRATEGY,
    LOAD_MARKET_DATA,
    REFINE_STRATEGY,
    SIMULATE_TRADES,
    STRATEGY_REVISION,
    VALIDATE_SIGNALS,
    detail_analysis_running,
    detail_analysis_skipped,
    detail_analysis_success,
    detail_backtest_failed_attempts,
    detail_chart_missing,
    detail_chart_sent,
    detail_corporate_from_session,
    detail_corporate_running,
    detail_corporate_success,
    detail_fix_error,
    detail_validation_success,
    detail_data_loaded,
    detail_load_running,
    detail_rerun_code,
    detail_signals,
    detail_signals_and_attempts,
    detail_strategy_revision_blocked,
    detail_strategy_revision_running,
    detail_strategy_revision_success,
    format_backtest_window_label,
    interval_phrase,
)
from backtester.agent.session import AGENT_SESSIONS_DIR, ChatSession, RunSummary

Callback = Callable[..., Awaitable[None]]


def _run_sync(fn, *args, **kwargs):
    """Run a blocking function in the default executor."""
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, lambda: fn(*args, **kwargs))


def _rerun_version_id_for_ui(
    session_id: str,
    explicit_version_id: str | None,
    code_to_run: str,
) -> str | None:
    """Version id for StrategyVersionEvent on rerun: explicit pick, else last manifest entry if its file matches code."""
    if explicit_version_id and explicit_version_id.strip():
        return explicit_version_id.strip()
    from backtester.compliance.manifest import load_manifest

    manifest = load_manifest(session_id)
    if not manifest:
        return None
    last = manifest[-1]
    vid = last.get("version_id")
    if not vid or not isinstance(vid, str):
        return None
    disk = ChatSession.get_strategy_code_for_version(session_id, vid)
    if disk and disk.strip() == code_to_run.strip():
        return vid
    return None


def _corporate_data_dict_for_tool(data_df: pd.DataFrame) -> dict[str, Any]:
    """Build a JSON-serializable summary of merged corporate/earnings columns for tool responses."""
    out: dict[str, Any] = {
        "ohlcv_plus_corporate_columns": list(data_df.columns),
        "has_earnings_columns": "Is_Earnings_Day" in data_df.columns,
    }
    if "Is_Earnings_Day" not in data_df.columns:
        out["note"] = (
            "No earnings columns on this dataframe. Run a backtest or fetch_data with "
            "include_corporate_events=true / include_earnings=true for an earnings-related strategy."
        )
        return out
    es = data_df["Is_Earnings_Day"].fillna(False)
    if es.dtype == object:
        es = es.map(lambda x: str(x).strip().lower() in ("true", "1", "1.0", "yes"))
    earn_mask = es.astype(bool)
    cols = ["Date"] + [c for c in ("EPS_Estimate", "EPS_Actual", "EPS_Surprise_Pct") if c in data_df.columns]
    earn_df = data_df.loc[earn_mask, cols].copy()
    out["earnings_days_in_range"] = int(earn_mask.sum())
    if earn_df.empty:
        out["earnings_calendar"] = []
    else:
        out["earnings_calendar"] = json.loads(earn_df.to_json(orient="records", date_format="iso"))
    return out


def _save_strategy_version(
    session: ChatSession,
    code: str,
    *,
    source: str = "run_backtest",
    strategy_text: str | None = None,
    change_request: str | None = None,
    ticker: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    interval: str | None = None,
) -> str:
    """Persist a snapshot of the given strategy code and append to version manifest for compliance."""
    from datetime import datetime, timezone

    version_id = uuid.uuid4().hex[:12]
    base_dir = AGENT_SESSIONS_DIR / session.session_id / "strategy_versions"
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"{version_id}.py"
    path.write_text(code, encoding="utf-8")

    manifest_path = base_dir / "manifest.json"
    manifest: list[dict] = []
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError):
            manifest = []
    entry = {
        "version_id": version_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "strategy_text": strategy_text,
        "change_request": change_request,
        "ticker": ticker or getattr(session, "active_ticker", None),
        "start_date": start_date or getattr(session, "start_date", None),
        "end_date": end_date or getattr(session, "end_date", None),
        "interval": interval or getattr(session, "active_interval", None),
    }
    manifest.append(entry)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return version_id


# ---------------------------------------------------------------------------
# run_backtest
# ---------------------------------------------------------------------------

async def handle_run_backtest(
    session: ChatSession,
    on_event: Callback,
    provider,
    strategy: str,
    ticker: str,
    start: str = "2020-01-01",
    end: str = "2025-01-01",
    interval: str = "auto",
) -> dict:
    """Full pipeline: download data -> analyze -> generate -> iterate -> return."""
    from backtester.data.interval import (
        VALID_INTERVALS,
        clamp_date_range,
        detect_interval,
    )

    if interval == "auto":
        resolved_interval = detect_interval(strategy)
    else:
        if interval not in VALID_INTERVALS:
            return {"success": False, "error": f"Invalid interval '{interval}'"}
        resolved_interval = interval

    start, end, was_clamped = clamp_date_range(start, end, resolved_interval)

    # -- Download data --
    await on_event(ProgressEvent(step=LOAD_MARKET_DATA, status="running", detail=detail_load_running(ticker, resolved_interval, start, end)))
    try:
        from backtester.data.downloader import download_data
        data_df = await _run_sync(download_data, ticker, start, end, interval=resolved_interval)
    except Exception as exc:
        await on_event(ProgressEvent(step=LOAD_MARKET_DATA, status="failed", detail=str(exc)))
        return {"success": False, "error": f"Data download failed: {exc}"}
    await on_event(ProgressEvent(step=LOAD_MARKET_DATA, status="success", detail=detail_data_loaded(len(data_df), ticker, resolved_interval, start, end)))

    # -- Corporate events --
    from backtester.data.corporate import detect_corporate_needs, download_corporate_data, merge_corporate_data
    corporate_needs = detect_corporate_needs(strategy)
    has_corporate_data = False
    if corporate_needs:
        await on_event(ProgressEvent(step=CORPORATE_CONTEXT, status="running", detail=detail_corporate_running(corporate_needs)))
        corp_failed = False
        corp_detail = ""
        try:
            corporate = await _run_sync(download_corporate_data, ticker, corporate_needs, start, end)
            data_df = merge_corporate_data(data_df, corporate)
            has_corporate_data = True
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Corporate data fetch/merge failed")
            corp_failed = True
            corp_detail = str(exc)
        await on_event(
            ProgressEvent(
                step=CORPORATE_CONTEXT,
                status="failed" if corp_failed else "success",
                detail=corp_detail[:120] if corp_failed else detail_corporate_success(),
            )
        )

    # -- Pre-flight analysis --
    from backtester.engine.strategy_analyzer import analyze_strategy, _build_corporate_summary
    await on_event(ProgressEvent(step=ALIGN_STRATEGY, status="running", detail=detail_analysis_running()))
    try:
        corp_summary = _build_corporate_summary(data_df, corporate_needs) if corporate_needs else {}
        analysis = await _run_sync(
            analyze_strategy,
            provider=provider,
            strategy_text=strategy,
            ticker=ticker,
            interval=resolved_interval,
            start=start,
            end=end,
            was_clamped=was_clamped,
            row_count=len(data_df),
            columns=list(data_df.columns),
            corporate_needs=corporate_needs,
            corporate_summary=corp_summary,
        )
        await on_event(ProgressEvent(step=ALIGN_STRATEGY, status="success", detail=detail_analysis_success(analysis.verdict)))
        if analysis.verdict == "revise" and analysis.revised_strategy:
            strategy = analysis.revised_strategy
    except Exception:
        await on_event(ProgressEvent(step=ALIGN_STRATEGY, status="success", detail=detail_analysis_skipped()))

    # -- Iteration loop (with auto-retry on intervention) --
    from backtester.engine.iteration_engine import run_iteration_loop

    loop = asyncio.get_event_loop()

    def _sync_progress(step_name: str, status: str, detail: str = ""):
        asyncio.run_coroutine_threadsafe(
            on_event(ProgressEvent(step=step_name, status=status, detail=detail)),
            loop,
        ).result(timeout=5)

    # Always store data in session so refine can work even after failure
    session.active_ticker = ticker
    session.active_strategy = strategy
    session.active_interval = resolved_interval
    session.active_data_df = data_df
    session.corporate_needs_snapshot = sorted(corporate_needs) if corporate_needs else None

    total_attempts = 0
    max_retries = 2

    for retry in range(max_retries):
        result = await _run_sync(
            run_iteration_loop,
            provider=provider,
            strategy_description=strategy,
            data_df=data_df,
            max_iterations=10,
            verbose=False,
            interval=resolved_interval,
            has_corporate_data=has_corporate_data,
            corporate_needs=corporate_needs if corporate_needs else None,
            on_progress=_sync_progress,
        )
        total_attempts += result.attempts

        if result.success:
            break

        if result.needs_intervention and result.diagnosis and hasattr(result.diagnosis, 'revised_strategy') and result.diagnosis.revised_strategy:
            from backtester.data.corporate import relaxation_drops_earnings_constraint
            revised = result.diagnosis.revised_strategy
            if relaxation_drops_earnings_constraint(strategy, revised):
                await on_event(ProgressEvent(
                    step=STRATEGY_REVISION,
                    status="failed",
                    detail=detail_strategy_revision_blocked(),
                ))
                break
            await on_event(ProgressEvent(
                step=STRATEGY_REVISION,
                status="running",
                detail=detail_strategy_revision_running(),
            ))
            strategy = revised
            session.active_strategy = strategy
            await on_event(ProgressEvent(
                step=STRATEGY_REVISION,
                status="success",
                detail=detail_strategy_revision_success(),
            ))
            continue

        break

    if result.success:
        await on_event(ProgressEvent(
            step=BACKTEST_DONE,
            status="success",
            detail=detail_signals_and_attempts(len(result.signals_df), total_attempts),
        ))

        session.active_code = result.code
        session.active_signals_df = result.signals_df
        session.active_indicator_df = result.indicator_df
        session.active_indicator_columns = result.indicator_columns or []

        buy_count = int((result.signals_df["Signal"] == "BUY").sum())
        sell_count = int((result.signals_df["Signal"] == "SELL").sum())

        session.add_run(RunSummary(
            ticker=ticker,
            strategy=strategy,
            interval=resolved_interval,
            signal_count=len(result.signals_df),
            buy_count=buy_count,
            sell_count=sell_count,
            attempts=total_attempts,
            success=True,
        ))

        first_date = str(result.signals_df["Date"].iloc[0]) if len(result.signals_df) > 0 else "N/A"
        last_date = str(result.signals_df["Date"].iloc[-1]) if len(result.signals_df) > 0 else "N/A"

        version_id = _save_strategy_version(
            session,
            result.code,
            source="run_backtest",
            strategy_text=strategy,
            ticker=ticker,
            start_date=start,
            end_date=end,
            interval=resolved_interval,
        )
        await on_event(StrategyVersionEvent(version_id=version_id))
        # New backtest becomes the current version; clear chat base so refine uses latest
        if getattr(session, "chat_base_version_id", None):
            session.chat_base_version_id = None
            session.save()

        return {
            "success": True,
            "ticker": ticker,
            "interval": resolved_interval,
            "interval_label": interval_phrase(resolved_interval),
            "window_label": format_backtest_window_label(start, end),
            "total_signals": len(result.signals_df),
            "buy_signals": buy_count,
            "sell_signals": sell_count,
            "first_signal_date": first_date,
            "last_signal_date": last_date,
            "attempts": total_attempts,
            "strategy_used": strategy[:200],
            "strategy_version_id": version_id,
        }
    else:
        await on_event(ProgressEvent(step=BACKTEST_DONE, status="failed", detail=detail_backtest_failed_attempts(total_attempts)))
        # Keep last attempted code and outputs so refine_strategy can use them as context
        # (e.g. user says "relax the RSI threshold to 40" after a failed run)
        if result.code:
            session.active_code = result.code
            session.active_signals_df = result.signals_df if result.signals_df is not None else None
            session.active_indicator_df = result.indicator_df if result.indicator_df is not None else None
            session.active_indicator_columns = result.indicator_columns or []
        last_errors = [
            f"[{e['error_type']}] {e['message'][:100]}"
            for e in result.error_history[-3:]
        ]
        return {
            "success": False,
            "error": f"Failed after {total_attempts} attempts",
            "last_errors": last_errors,
            "data_rows": len(data_df),
            "interval": resolved_interval,
        }


# ---------------------------------------------------------------------------
# refine_strategy
# ---------------------------------------------------------------------------

async def handle_refine_strategy(
    session: ChatSession,
    on_event: Callback,
    provider,
    change_request: str,
) -> dict:
    if session.active_data_df is None:
        return {"success": False, "error": "No active backtest to refine. Run a backtest first."}

    base_code = session.active_code
    is_selected_version = False
    if getattr(session, "chat_base_version_id", None):
        loaded = ChatSession.get_strategy_code_for_version(session.session_id, session.chat_base_version_id)
        if loaded:
            base_code = loaded
            is_selected_version = True
        else:
            session.chat_base_version_id = None
            session.save()
    if not base_code:
        return {"success": False, "error": "No active backtest to refine. Run a backtest first."}

    from backtester.engine.refine_engine import run_refine_turn
    from backtester.engine.session import RefineSession

    refine_session = RefineSession.new_session(
        ticker=session.active_ticker or "UNKNOWN",
        interval=session.active_interval or "1d",
        strategy_description=session.active_strategy or "",
        data_path="",
        current_code=base_code,
    )

    chart_image = session.pending_chart_image
    session.pending_chart_image = None

    # Capture baseline signals (if any) so the refinement engine can
    # enforce simple invariants like "a restrictive change should not
    # increase the number of BUY signals".
    baseline_signals_df = session.active_signals_df.copy() if session.active_signals_df is not None else None

    loop = asyncio.get_event_loop()

    def _sync_progress(step_name: str, status: str, detail: str = ""):
        asyncio.run_coroutine_threadsafe(
            on_event(ProgressEvent(step=step_name, status=status, detail=detail)),
            loop,
        ).result(timeout=120)

    result = await _run_sync(
        run_refine_turn,
        session=refine_session,
        change_request=change_request,
        provider=provider,
        df=session.active_data_df,
        baseline_signals_df=baseline_signals_df,
        max_attempts=5,
        verbose=False,
        chart_image=chart_image,
        is_selected_version=is_selected_version,
        on_progress=_sync_progress,
    )

    if result.success:
        session.active_code = result.code
        session.active_signals_df = result.signals_df
        if result.indicator_df is not None:
            session.active_indicator_df = result.indicator_df
        if result.indicator_columns:
            session.active_indicator_columns = result.indicator_columns

        buy_count = int((result.signals_df["Signal"] == "BUY").sum()) if result.signals_df is not None else 0
        sell_count = int((result.signals_df["Signal"] == "SELL").sum()) if result.signals_df is not None else 0
        total_signals = len(result.signals_df) if result.signals_df is not None else 0

        await on_event(ProgressEvent(
            step=BACKTEST_DONE,
            status="success",
            detail=detail_signals_and_attempts(total_signals, result.attempts),
        ))

        version_id = _save_strategy_version(
            session,
            result.code,
            source="refine",
            change_request=change_request,
        )
        await on_event(StrategyVersionEvent(version_id=version_id))

        return {
            "success": True,
            "summary": result.summary,
            "total_signals": total_signals,
            "buy_signals": buy_count,
            "sell_signals": sell_count,
            "attempts": result.attempts,
            "strategy_version_id": version_id,
        }
    else:
        await on_event(ProgressEvent(step=REFINE_STRATEGY, status="failed", detail=result.error_message))
        return {"success": False, "error": result.error_message}


# ---------------------------------------------------------------------------
# fix_strategy
# ---------------------------------------------------------------------------

async def handle_fix_strategy(
    session: ChatSession,
    on_event: Callback,
    provider,
    issue: str,
) -> dict:
    if session.active_data_df is None:
        return {"success": False, "error": "No active backtest to fix. Run a backtest first."}

    base_code = session.active_code
    is_selected_version = False
    if getattr(session, "chat_base_version_id", None):
        loaded = ChatSession.get_strategy_code_for_version(session.session_id, session.chat_base_version_id)
        if loaded:
            base_code = loaded
            is_selected_version = True
        else:
            session.chat_base_version_id = None
            session.save()
    if not base_code:
        return {"success": False, "error": "No active backtest to fix. Run a backtest first."}

    from backtester.engine.context_engine import RunArtifacts
    from backtester.engine.iteration_engine import run_fix_loop

    artifacts = RunArtifacts()
    artifacts.strategy_description = session.active_strategy or ""
    artifacts.generated_code = base_code
    artifacts.data_df = session.active_data_df
    artifacts.signals_df = session.active_signals_df
    artifacts.interval = session.active_interval or "1d"

    chart_image = session.pending_chart_image
    session.pending_chart_image = None

    if chart_image:
        await on_event(ProgressEvent(step=CHART_ATTACHED, status="success", detail=detail_chart_sent()))
    else:
        await on_event(ProgressEvent(step=CHART_ATTACHED, status="failed", detail=detail_chart_missing()))

    await on_event(ProgressEvent(step=FIX_STRATEGY, status="running", detail=issue[:80]))
    result = await _run_sync(
        run_fix_loop,
        provider=provider,
        issue=issue,
        artifacts=artifacts,
        data_df=session.active_data_df,
        max_iterations=5,
        verbose=False,
        interval=session.active_interval or "1d",
        chart_image=chart_image,
        is_selected_version=is_selected_version,
    )

    if result.success:
        await on_event(ProgressEvent(step=FIX_STRATEGY, status="success"))

        session.active_code = result.code
        session.active_signals_df = result.signals_df
        if result.indicator_df is not None:
            session.active_indicator_df = result.indicator_df
        if result.indicator_columns:
            session.active_indicator_columns = result.indicator_columns

        buy_count = int((result.signals_df["Signal"] == "BUY").sum()) if result.signals_df is not None else 0
        sell_count = int((result.signals_df["Signal"] == "SELL").sum()) if result.signals_df is not None else 0
        total_signals = len(result.signals_df) if result.signals_df is not None else 0

        await on_event(ProgressEvent(
            step=BACKTEST_DONE,
            status="success",
            detail=detail_signals_and_attempts(total_signals, result.attempts),
        ))

        version_id = _save_strategy_version(
            session,
            result.code,
            source="fix",
            change_request=issue,
        )
        await on_event(StrategyVersionEvent(version_id=version_id))

        return {
            "success": True,
            "total_signals": total_signals,
            "buy_signals": buy_count,
            "sell_signals": sell_count,
            "attempts": result.attempts,
            "strategy_version_id": version_id,
        }
    else:
        await on_event(ProgressEvent(step=FIX_STRATEGY, status="failed"))
        return {"success": False, "error": f"Fix failed after {result.attempts} attempts"}


# ---------------------------------------------------------------------------
# query_results
# ---------------------------------------------------------------------------

async def handle_query_results(
    session: ChatSession,
    on_event: Callback,
    provider,
    question: str,
) -> dict:
    if session.active_signals_df is None:
        return {"success": False, "error": "No signals data available. Run a backtest first."}

    df = session.active_signals_df

    df_info = (
        f"Columns: {list(df.columns)}\n"
        f"Shape: {df.shape}\n"
        f"dtypes:\n{df.dtypes.to_string()}\n"
        f"First 3 rows:\n{df.head(3).to_string()}\n"
        f"Last 3 rows:\n{df.tail(3).to_string()}"
    )

    prompt = f"""\
You have a pandas DataFrame `df` with backtest signals.

{df_info}

The user asks: "{question}"

Write a short Python snippet that computes the answer. The snippet should:
1. Use only pandas/numpy operations on `df`
2. Store the final answer in a variable called `answer`
3. `answer` should be a string suitable for showing the user

Output ONLY the Python code, no explanation."""

    await on_event(ProgressEvent(step=ANALYZE_RESULTS, status="running"))

    resp = await _run_sync(provider.generate, prompt, "You are a data analysis assistant. Output only Python code.")
    code = _extract_code(resp.content)

    try:
        namespace: dict[str, Any] = {"df": df.copy(), "pd": pd}
        import numpy as np
        namespace["np"] = np
        exec(code, namespace)  # noqa: S102
        answer = str(namespace.get("answer", "No answer computed"))
    except Exception as exc:
        answer = f"Query failed: {exc}"

    await on_event(ProgressEvent(step=ANALYZE_RESULTS, status="success"))
    return {"success": True, "answer": answer}


# ---------------------------------------------------------------------------
# run_custom_analysis — generalizable analysis using code version + chat summary + data
# ---------------------------------------------------------------------------

def _trades_for_analysis(signals_df: pd.DataFrame) -> list[dict]:
    """Return trade pairs as list of dicts with serializable values for prompt/namespace."""
    pairs = _signals_to_trade_pairs(signals_df)
    out = []
    for t in pairs:
        entry_date = t["entry_date"]
        exit_date = t["exit_date"]
        out.append({
            "entry_date": entry_date.strftime("%Y-%m-%d") if hasattr(entry_date, "strftime") else str(entry_date),
            "exit_date": exit_date.strftime("%Y-%m-%d") if hasattr(exit_date, "strftime") else str(exit_date),
            "entry_price": t["entry_price"],
            "exit_price": t["exit_price"],
            "signal_type": t["signal_type"],
            "pnl": t["pnl"],
            "pnl_pct": t["pnl_pct"],
            "days_held": t["days_held"],
        })
    return out


async def handle_run_custom_analysis(
    session: ChatSession,
    on_event: Callback,
    provider,
    query: str,
) -> dict:
    """Run helper Python (generated by LLM) with full context: strategy code, chat summary, signals df, trades, and full OHLCV data.
    Answer is returned to the user; the helper code is not shown."""
    if session.active_signals_df is None:
        return {"success": False, "error": "No backtest data available. Run a backtest first."}

    df = session.active_signals_df
    trades = _trades_for_analysis(df)
    chat_summary = session.chat_summary_for_analysis(max_messages=12, max_content_len=400)
    strategy_desc = (session.active_strategy or "N/A")[:500]
    code_snippet = (session.active_code or "# No code")[:3000]
    if len(session.active_code or "") > 3000:
        code_snippet += "\n# ... (truncated)"

    ticker = session.active_ticker or "N/A"
    currency_note = "Use ₹ for amounts when answering for this Indian ticker." if (
        ticker and (".NS" in str(ticker) or ".BO" in str(ticker) or str(ticker).upper() in ("NIFTY", "NIFTY 50", "CNXIT"))
    ) else "Use USD ($) for amounts when answering for this US ticker."

    # Prefer chart data (OHLCV + strategy indicators) so analysis sees same columns as the chart; fallback to raw OHLCV.
    data_df = session.active_indicator_df if (session.active_indicator_df is not None and not session.active_indicator_df.empty) else session.active_data_df

    # Build table heads so the LLM knows exact format and can write the custom function accordingly.
    backtest_table_head = df.head(10).to_string() if len(df) > 0 else "(empty)"
    pl_table = pd.DataFrame(trades) if trades else pd.DataFrame()
    pl_table_head = pl_table.head(10).to_string() if not pl_table.empty else "(no trades)"
    chart_data_head = ""
    if data_df is not None and not data_df.empty:
        chart_data_head = data_df.head(10).to_string()

    data_section = f"""- **Backtesting table** (signals, variable `df`): {len(df)} rows. Columns: {list(df.columns)}.
First 10 rows:
```
{backtest_table_head}
```

- **Profit/loss table** (variable `trades`): list of {len(trades)} dicts with keys entry_date, exit_date, entry_price, exit_price, signal_type, pnl, pnl_pct, days_held.
First 10 rows (as table):
```
{pl_table_head}
```"""
    if chart_data_head:
        data_section += f"""

- **Chart data** (variable `data_df`): OHLCV + all strategy indicator columns, same as chart. {len(data_df)} rows. Columns: {list(data_df.columns)}.
First 10 rows:
```
{chart_data_head}
```
Use `data_df` to infer which exit condition was triggered per trade. If you need 'previous day high' and no such column exists, use data_df['High'].shift(1) and handle NaN for the first row."""
    else:
        data_section += "\n\n- **Chart data** (`data_df`): not available in this session."

    prompt = f"""You have full context for a backtest session.

## Strategy description
{strategy_desc}

## Current strategy code (excerpt)
```python
{code_snippet}
```

## Recent conversation
{chat_summary}

## Data
- Ticker: {ticker}. {currency_note}
{data_section}

## User question
{query}

Write a short Python snippet that uses `df`, `trades`, and optionally `data_df` (and pd, np if needed) to compute the answer. Set the result in a variable `answer` (a string suitable to show the user). Output ONLY the Python code, no explanation."""

    await on_event(ProgressEvent(step=CUSTOM_ANALYSIS, status="running"))

    resp = await _run_sync(provider.generate, prompt, "You are a data analysis assistant. Output only Python code.")
    code = _extract_code(resp.content)

    try:
        import numpy as np
        namespace: dict[str, Any] = {
            "df": df.copy(),
            "trades": trades,
            "pd": pd,
            "np": np,
        }
        if data_df is not None and not data_df.empty:
            namespace["data_df"] = data_df.copy()
            # Ensure Date is datetime for comparison with entry_date/exit_date
            _d = namespace["data_df"]
            date_col = "date" if "date" in _d.columns else "Date"
            if date_col in _d.columns and not pd.api.types.is_datetime64_any_dtype(_d[date_col]):
                namespace["data_df"] = _d.copy()
                namespace["data_df"][date_col] = pd.to_datetime(namespace["data_df"][date_col])
        exec(code, namespace)  # noqa: S102
        answer = str(namespace.get("answer", "No answer computed"))
    except Exception as exc:
        answer = f"Analysis failed: {exc}"

    await on_event(ProgressEvent(step=CUSTOM_ANALYSIS, status="success"))
    # Return only answer so the agent presents the result without exposing helper code
    return {"success": True, "answer": answer}


# ---------------------------------------------------------------------------
# show_code
# ---------------------------------------------------------------------------

async def handle_show_code(
    session: ChatSession,
    on_event: Callback,
    **kwargs,
) -> dict:
    if not session.active_code:
        return {"success": False, "error": "No strategy code available. Run a backtest first."}
    await on_event(CodeEvent(code=session.active_code))
    return {"success": True, "code": session.active_code}


# ---------------------------------------------------------------------------
# get_signal_summary
# ---------------------------------------------------------------------------

async def handle_get_signal_summary(
    session: ChatSession,
    on_event: Callback,
    **kwargs,
) -> dict:
    if session.active_signals_df is None:
        return {"success": False, "error": "No signals available. Run a backtest first."}

    df = session.active_signals_df
    buy_count = int((df["Signal"] == "BUY").sum()) if "Signal" in df.columns else 0
    sell_count = int((df["Signal"] == "SELL").sum()) if "Signal" in df.columns else 0
    total = len(df)
    first_date = str(df["Date"].iloc[0]) if total > 0 else "N/A"
    last_date = str(df["Date"].iloc[-1]) if total > 0 else "N/A"

    summary = {
        "ticker": session.active_ticker or "N/A",
        "interval": session.active_interval or "N/A",
        "total_signals": total,
        "buy_signals": buy_count,
        "sell_signals": sell_count,
        "hold_signals": total - buy_count - sell_count,
        "first_signal_date": first_date,
        "last_signal_date": last_date,
        "strategy": (session.active_strategy or "N/A")[:200],
    }

    await on_event(TableEvent(
        title="Signal Summary",
        headers=["Metric", "Value"],
        rows=[[k, str(v)] for k, v in summary.items()],
    ))
    return {"success": True, **summary}


# ---------------------------------------------------------------------------
# get_trades_table — convert signals to entry/exit/profit-loss rows
# ---------------------------------------------------------------------------

MAX_TRADES_TABLE_ROWS = 500


def _signals_to_trade_pairs(signals_df: pd.DataFrame) -> list[dict]:
    """Convert Date/Signal/Price into list of trade dicts with numeric P/L.
    Pairs: first BUY with first following SELL (long); first SELL with first following BUY (short).
    Each dict: entry_date, exit_date, entry_price, exit_price, signal_type (LONG|SHORT), pnl, pnl_pct, days_held.
    """
    if signals_df is None or len(signals_df) == 0:
        return []
    df = signals_df.copy()
    if "Date" not in df.columns or "Signal" not in df.columns or "Price" not in df.columns:
        return []
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date", "Price"])
    signals = df["Signal"].astype(str).str.upper()
    n = len(df)
    pairs: list[dict] = []
    i = 0
    while i < n:
        if signals.iloc[i] == "BUY":
            j = i + 1
            while j < n and signals.iloc[j] != "SELL":
                j += 1
            if j >= n:
                break
            entry_date = df["Date"].iloc[i]
            exit_date = df["Date"].iloc[j]
            entry_price = float(df["Price"].iloc[i])
            exit_price = float(df["Price"].iloc[j])
            pnl = exit_price - entry_price
            pnl_pct = (pnl / entry_price * 100) if entry_price else 0.0
            days_held = (exit_date - entry_date).days if hasattr(exit_date - entry_date, "days") else 0
            pairs.append({
                "entry_date": entry_date,
                "exit_date": exit_date,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "signal_type": "LONG",
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "days_held": days_held,
            })
            i = j + 1
        elif signals.iloc[i] == "SELL":
            j = i + 1
            while j < n and signals.iloc[j] != "BUY":
                j += 1
            if j >= n:
                i += 1
                continue
            entry_date = df["Date"].iloc[i]
            exit_date = df["Date"].iloc[j]
            entry_price = float(df["Price"].iloc[i])
            exit_price = float(df["Price"].iloc[j])
            # Short: profit when exit (cover) < entry (short)
            pnl = entry_price - exit_price
            pnl_pct = (pnl / entry_price * 100) if entry_price else 0.0
            days_held = (exit_date - entry_date).days if hasattr(exit_date - entry_date, "days") else 0
            pairs.append({
                "entry_date": entry_date,
                "exit_date": exit_date,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "signal_type": "SHORT",
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "days_held": days_held,
            })
            i = j + 1
        else:
            i += 1
    return pairs


def _signals_to_trades_df(signals_df: pd.DataFrame, capital_per_trade: float | None = None) -> pd.DataFrame:
    """Convert Date/Signal/Price signals into trades: Entry Date, Exit Date, Entry Price, Exit Price, Signal Type, Profit/Loss, Profit/Loss %, Days Held.
    If capital_per_trade is set, adds P/L (₹) = (Profit/Loss % / 100) * capital_per_trade for each trade."""
    base_cols = ["Entry Date", "Exit Date", "Entry Price", "Exit Price", "Signal Type", "Profit/Loss", "Profit/Loss %", "Days Held"]
    if capital_per_trade is not None:
        base_cols = base_cols + ["P/L (₹)"]
    pairs = _signals_to_trade_pairs(signals_df)
    if not pairs:
        return pd.DataFrame(columns=base_cols)
    rows = []
    for t in pairs:
        entry_date = t["entry_date"]
        exit_date = t["exit_date"]
        row = {
            "Entry Date": entry_date.strftime("%Y-%m-%d") if hasattr(entry_date, "strftime") else str(entry_date),
            "Exit Date": exit_date.strftime("%Y-%m-%d") if hasattr(exit_date, "strftime") else str(exit_date),
            "Entry Price": f"{t['entry_price']:.4g}",
            "Exit Price": f"{t['exit_price']:.4g}",
            "Signal Type": "BUY-SELL" if t["signal_type"] == "LONG" else "SELL-BUY",
            "Profit/Loss": f"{t['pnl']:.6g}",
            "Profit/Loss %": f"{t['pnl_pct']:.2f}%",
            "Days Held": str(t["days_held"]) if t["days_held"] != "" else "",
        }
        if capital_per_trade is not None:
            pnl_rupees = round((t["pnl_pct"] / 100.0) * capital_per_trade, 2)
            row["P/L (₹)"] = f"₹{pnl_rupees:,.2f}"
        rows.append(row)
    return pd.DataFrame(rows)


def _trades_table_columns(pnl_format: str, with_capital: bool = False) -> list[str]:
    """Return column names for the trades table based on pnl_format: 'absolute' | 'percent' | 'both'. If with_capital, include P/L (₹)."""
    base = ["Entry Date", "Exit Date", "Entry Price", "Exit Price", "Signal Type"]
    if pnl_format == "percent":
        cols = base + ["Profit/Loss %", "Days Held"]
    elif pnl_format == "both":
        cols = base + ["Profit/Loss", "Profit/Loss %", "Days Held"]
    else:
        cols = base + ["Profit/Loss", "Days Held"]
    if with_capital:
        cols = cols + ["P/L (₹)"]
    return cols


async def handle_get_trades_table(
    session: ChatSession,
    on_event: Callback,
    **kwargs,
) -> dict:
    """Return backtest results as a trades table. Supports pnl_format: absolute (default), percent, or both.
    If capital_per_trade is provided (e.g. 100000), adds P/L (₹) = (Profit/Loss % / 100) * capital_per_trade for each trade."""
    if session.active_signals_df is None:
        return {"success": False, "error": "No signals available. Run a backtest first."}

    limit = kwargs.get("limit") or MAX_TRADES_TABLE_ROWS
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = MAX_TRADES_TABLE_ROWS
    if limit <= 0:
        limit = MAX_TRADES_TABLE_ROWS

    pnl_format = (kwargs.get("pnl_format") or "absolute").strip().lower()
    if pnl_format not in ("absolute", "percent", "both"):
        pnl_format = "absolute"

    capital_per_trade = None
    if kwargs.get("capital_per_trade") is not None:
        try:
            capital_per_trade = float(kwargs["capital_per_trade"])
            if capital_per_trade <= 0 or not math.isfinite(capital_per_trade):
                capital_per_trade = None
        except (TypeError, ValueError):
            capital_per_trade = None

    trades_df = _signals_to_trades_df(session.active_signals_df, capital_per_trade=capital_per_trade)
    if trades_df.empty:
        headers = _trades_table_columns(pnl_format, with_capital=capital_per_trade is not None)
        await on_event(TableEvent(
            title="Trades (no complete BUY→SELL pairs)",
            headers=headers,
            rows=[],
        ))
        return {
            "success": True,
            "total_trades": 0,
            "message": "No complete BUY-SELL pairs in signals.",
            "headers": headers,
            "rows": [],
        }

    n_total = len(trades_df)
    n_show = min(n_total, limit)
    head = trades_df.head(n_show)
    wanted = _trades_table_columns(pnl_format, with_capital=capital_per_trade is not None)
    select = [c for c in wanted if c in head.columns]
    head = head[select]
    headers = list(head.columns)
    rows = head.values.tolist()
    rows = [[str(c) for c in row] for row in rows]

    title = "Backtest trades (entry, exit, P&L)" if n_total <= n_show else f"Backtest trades (first {n_show} of {n_total})"
    if pnl_format == "percent":
        title = "Backtest trades (entry, exit, P&L %)" if n_total <= n_show else f"Backtest trades (first {n_show} of {n_total}, P&L %)"
    elif pnl_format == "both":
        title = "Backtest trades (entry, exit, P&L and %)" if n_total <= n_show else f"Backtest trades (first {n_show} of {n_total}, P&L and %)"

    await on_event(TableEvent(title=title, headers=headers, rows=rows))
    return {
        "success": True,
        "total_trades": n_total,
        "shown": n_show,
        "truncated": n_total > n_show,
        # Same cells as the UI table — model must cite these, not invent prices.
        "headers": headers,
        "rows": rows,
        "cite_in_text": "Use only dates and prices from headers/rows when stating numbers in your reply.",
    }


# ---------------------------------------------------------------------------
# get_backtesting_table — summary of all trades (backtesting metrics)
# ---------------------------------------------------------------------------

def _compute_backtest_summary(pairs: list[dict]) -> dict[str, str]:
    """Compute backtesting summary metrics from trade pairs. Returns dict of Metric -> formatted Value.

    P/L semantics:
    - Total P/L (price units): sum of per-trade pnl in price units (e.g. index points); not rupees.
    - Total Return %: sum of per-trade pnl_pct. With fixed capital C per trade, total profit in ₹ = (Total Return % / 100) * C.
    - Per-trade P/L in ₹: (pnl_pct / 100) * capital_per_trade. Use get_trades_table(capital_per_trade=C) to show this.
    """
    if not pairs:
        return {
            "Total Trades": "0",
            "Winning Trades": "0",
            "Losing Trades": "0",
            "Win Rate (%)": "—",
            "Total P/L (price units)": "—",
            "Total Return %": "—",
            "Avg Return % per trade": "—",
            "Avg P/L per Trade": "—",
            "Total P/L (₹) at ₹100,000/trade": "—",
            "Avg Win": "—",
            "Avg Loss": "—",
            "Risk/Reward Ratio": "—",
            "Profit Factor": "—",
            "Avg Days Held": "—",
            "Best Trade": "—",
            "Worst Trade": "—",
            "Max Consecutive Wins": "—",
            "Max Consecutive Losses": "—",
        }
    n = len(pairs)
    pnls = [t["pnl"] for t in pairs]
    pnl_pcts = [t["pnl_pct"] for t in pairs]
    days_held = [t["days_held"] for t in pairs if isinstance(t["days_held"], (int, float))]

    winning = [p for p in pnls if p > 0]
    losing = [p for p in pnls if p < 0]
    n_win = len(winning)
    n_lose = len(losing)
    win_rate = (n_win / n * 100) if n else 0.0

    total_pnl = sum(pnls)
    avg_pnl = total_pnl / n if n else 0.0
    total_return_pct = sum(pnl_pcts)  # Sum of trade returns (e.g. 4.34%); with fixed capital per trade, total P/L in ₹ = (total_return_pct/100)*capital
    avg_return_pct = (total_return_pct / n) if n else 0.0  # Average return % per trade
    avg_win = (sum(winning) / n_win) if n_win else 0.0
    avg_loss = (sum(losing) / n_lose) if n_lose else 0.0

    gross_profit = sum(winning) if winning else 0.0
    gross_loss = sum(losing) if losing else 0.0
    abs_loss = abs(gross_loss)
    profit_factor = (gross_profit / abs_loss) if abs_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

    # Risk/Reward = |Avg Loss| / |Avg Win| (risk per unit of reward)
    abs_avg_win = abs(avg_win) if n_win else 0.0
    risk_reward = (abs(avg_loss) / abs_avg_win) if (n_win and n_lose and abs_avg_win > 0) else None

    avg_days = (sum(days_held) / len(days_held)) if days_held else 0.0
    best = max(pnls) if pnls else 0.0
    worst = min(pnls) if pnls else 0.0

    # Total P/L in ₹ when using fixed capital per trade (e.g. ₹1,00,000): (total_return_pct/100)*capital
    capital_example = 100_000
    total_pnl_rupees_at_capital = round((total_return_pct / 100.0) * capital_example, 2)

    # Consecutive wins/losses
    max_cw = 0
    max_cl = 0
    cw = 0
    cl = 0
    for p in pnls:
        if p > 0:
            cw += 1
            cl = 0
            max_cw = max(max_cw, cw)
        elif p < 0:
            cl += 1
            cw = 0
            max_cl = max(max_cl, cl)
        else:
            cw = cl = 0

    def fmt(x: float, pct: bool = False) -> str:
        if pct:
            return f"{x:.2f}%"
        return f"{x:.6g}" if x != int(x) else str(int(x))

    return {
        "Total Trades": str(n),
        "Winning Trades": str(n_win),
        "Losing Trades": str(n_lose),
        "Win Rate (%)": fmt(win_rate, pct=True),
        "Total P/L (price units)": fmt(total_pnl),
        "Total Return %": fmt(total_return_pct, pct=True),
        "Avg Return % per trade": fmt(avg_return_pct, pct=True),
        "Avg P/L per Trade": fmt(avg_pnl),
        f"Total P/L (₹) at ₹{capital_example:,}/trade": f"₹{total_pnl_rupees_at_capital:,.2f}",
        "Avg Win": fmt(avg_win) if n_win else "—",
        "Avg Loss": fmt(avg_loss) if n_lose else "—",
        "Risk/Reward Ratio": f"{risk_reward:.2f}" if risk_reward is not None else "—",
        "Profit Factor": f"{profit_factor:.2f}" if abs_loss > 0 else ("inf" if gross_profit > 0 else "0"),
        "Avg Days Held": fmt(avg_days),
        "Best Trade": fmt(best),
        "Worst Trade": fmt(worst),
        "Max Consecutive Wins": str(max_cw),
        "Max Consecutive Losses": str(max_cl),
    }


def compute_chart_backtest_extras(
    signals_df: pd.DataFrame | None,
) -> tuple[list[dict[str, float | str]], dict[str, str]] | tuple[None, None]:
    """Build equity curve points and summary (including max drawdown and trade-based Sharpe) for the chart API."""
    if signals_df is None or len(signals_df) == 0:
        return None, None
    pairs = _signals_to_trade_pairs(signals_df)
    summary = _compute_backtest_summary(pairs)

    equity_curve: list[dict[str, float | str]] = []
    if pairs:
        sorted_pairs = sorted(pairs, key=lambda p: p["exit_date"])

        def fmt_d(d) -> str:
            if hasattr(d, "strftime"):
                return d.strftime("%Y-%m-%d")
            s = str(d)
            return s[:10] if len(s) >= 10 else s

        cum = 100.0
        equity_curve.append({"time": fmt_d(sorted_pairs[0]["entry_date"]), "equity": cum})
        for t in sorted_pairs:
            cum += float(t["pnl_pct"])
            equity_curve.append({"time": fmt_d(t["exit_date"]), "equity": round(cum, 6)})

    equities = [float(p["equity"]) for p in equity_curve] if equity_curve else []
    if equities:
        peak = equities[0]
        max_dd = 0.0
        for x in equities:
            peak = max(peak, x)
            if peak > 0:
                max_dd = max(max_dd, (peak - x) / peak * 100.0)
        summary["Max Drawdown (%)"] = f"{max_dd:.2f}%"
    else:
        summary["Max Drawdown (%)"] = "—"

    pnl_pcts = [float(t["pnl_pct"]) for t in pairs]
    if len(pnl_pcts) > 1:
        m = statistics.mean(pnl_pcts)
        s = statistics.stdev(pnl_pcts)
        if s > 0 and math.isfinite(m):
            sharpe = (m / s) * math.sqrt(len(pnl_pcts))
            summary["Sharpe (approx., trades)"] = f"{sharpe:.2f}" if math.isfinite(sharpe) else "—"
        else:
            summary["Sharpe (approx., trades)"] = "—"
    else:
        summary["Sharpe (approx., trades)"] = "—"

    return equity_curve, summary


def compute_backtest_metrics_numeric(signals_df: pd.DataFrame | None) -> dict[str, float | None]:
    """Compute profit_factor, risk_reward, max_loss_pct from signals for batch/API. max_loss_pct is worst trade as %."""
    if signals_df is None or len(signals_df) == 0:
        return {"profit_factor": 0.0, "risk_reward": None, "max_loss_pct": None}
    pairs = _signals_to_trade_pairs(signals_df)
    if not pairs:
        return {"profit_factor": 0.0, "risk_reward": None, "max_loss_pct": None}
    pnls = [t["pnl"] for t in pairs]
    pnl_pcts = [t["pnl_pct"] for t in pairs]
    n = len(pairs)
    winning = [p for p in pnls if p > 0]
    losing = [p for p in pnls if p < 0]
    n_win = len(winning)
    n_lose = len(losing)
    gross_profit = sum(winning) if winning else 0.0
    gross_loss = sum(losing) if losing else 0.0
    abs_loss = abs(gross_loss)
    profit_factor = (gross_profit / abs_loss) if abs_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    avg_win = (sum(winning) / n_win) if n_win else 0.0
    avg_loss = (sum(losing) / n_lose) if n_lose else 0.0
    abs_avg_win = abs(avg_win) if n_win else 0.0
    risk_reward = (abs(avg_loss) / abs_avg_win) if (n_win and n_lose and abs_avg_win > 0) else None
    # Worst trade as percentage (min of pnl_pct)
    max_loss_pct = min(pnl_pcts) if pnl_pcts else None
    return {"profit_factor": profit_factor, "risk_reward": risk_reward, "max_loss_pct": max_loss_pct}


def pct_from_pairs_list(pairs: list[dict]) -> tuple[float | None, float | None]:
    """Win rate % and sum of trade return % from pair dicts (same semantics as _safe_pct_from_pairs)."""
    if not pairs:
        return None, None
    wins = sum(1 for p in pairs if float(p.get("pnl", 0.0)) > 0)
    total = len(pairs)
    win_rate = (wins / total) * 100.0 if total else None
    total_return = sum(float(p.get("pnl_pct", 0.0)) for p in pairs)
    return win_rate, total_return


def annualize_linear_trade_pnl_sum_pct(
    period_total_pct: float | None,
    period_calendar_days: int,
) -> float | None:
    """Scale sum-of-trade % P&L to an estimated annual % using segment calendar length.

    Uses linear extrapolation: annual ≈ period_total × (365.25 / days). Comparable across
    different train/test window lengths. ``period_calendar_days`` is at least 1.
    """
    if period_total_pct is None:
        return None
    d = max(1, int(period_calendar_days))
    return float(period_total_pct) * (365.25 / float(d))


def parameter_search_split_calendar_days(data_df: pd.DataFrame) -> dict[str, Any] | None:
    """80/20 row split; calendar days from first to last bar in each segment (inclusive)."""
    n = len(data_df)
    if n < 10 or "Date" not in data_df.columns:
        return None
    split_idx = int(n * 0.8)
    if split_idx < 1:
        split_idx = 1
    if split_idx >= n:
        split_idx = n - 1
    d0 = pd.to_datetime(data_df["Date"].iloc[0])
    d_tr1 = pd.to_datetime(data_df["Date"].iloc[split_idx - 1])
    d_te0 = pd.to_datetime(data_df["Date"].iloc[split_idx])
    d_te1 = pd.to_datetime(data_df["Date"].iloc[n - 1])
    train_days = max(1, (d_tr1 - d0).days + 1)
    test_days = max(1, (d_te1 - d_te0).days + 1)
    return {
        "split_idx": split_idx,
        "train_period_calendar_days": train_days,
        "test_period_calendar_days": test_days,
        "train_bars": split_idx,
        "test_bars": n - split_idx,
    }


def compute_backtest_metrics_numeric_from_pairs(pairs: list[dict]) -> dict[str, float | None]:
    """Same as compute_backtest_metrics_numeric but from pre-built trade pair dicts."""
    if not pairs:
        return {"profit_factor": 0.0, "risk_reward": None, "max_loss_pct": None}
    pnls = [t["pnl"] for t in pairs]
    pnl_pcts = [t["pnl_pct"] for t in pairs]
    winning = [p for p in pnls if p > 0]
    losing = [p for p in pnls if p < 0]
    n_win = len(winning)
    n_lose = len(losing)
    gross_profit = sum(winning) if winning else 0.0
    gross_loss = sum(losing) if losing else 0.0
    abs_loss = abs(gross_loss)
    profit_factor = (gross_profit / abs_loss) if abs_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    avg_win = (sum(winning) / n_win) if n_win else 0.0
    avg_loss = (sum(losing) / n_lose) if n_lose else 0.0
    abs_avg_win = abs(avg_win) if n_win else 0.0
    risk_reward = (abs(avg_loss) / abs_avg_win) if (n_win and n_lose and abs_avg_win > 0) else None
    max_loss_pct = min(pnl_pcts) if pnl_pcts else None
    return {"profit_factor": profit_factor, "risk_reward": risk_reward, "max_loss_pct": max_loss_pct}


def parameter_search_train_test_from_signals(
    signals_df: pd.DataFrame | None,
    data_df: pd.DataFrame,
) -> dict[str, Any]:
    """Split completed trades by first bar date of the holdout (80% row index on ``data_df``)."""
    if signals_df is None or len(signals_df) == 0:
        return {"error": "No signals"}
    split_info = parameter_search_split_calendar_days(data_df)
    if not split_info:
        return {"error": "Not enough price bars for train/test split (need at least 10)."}
    split_idx = int(split_info["split_idx"])
    train_period_days = int(split_info["train_period_calendar_days"])
    test_period_days = int(split_info["test_period_calendar_days"])
    split_dt = pd.to_datetime(data_df["Date"].iloc[split_idx])
    train_end = data_df["Date"].iloc[split_idx - 1]
    test_start = data_df["Date"].iloc[split_idx]
    train_end_str = train_end.strftime("%Y-%m-%d") if hasattr(train_end, "strftime") else str(train_end)[:10]
    test_start_str = test_start.strftime("%Y-%m-%d") if hasattr(test_start, "strftime") else str(test_start)[:10]

    pairs = _signals_to_trade_pairs(signals_df)
    train_pairs: list[dict] = []
    test_pairs: list[dict] = []
    for p in pairs:
        ed = pd.to_datetime(p["entry_date"])
        if ed < split_dt:
            train_pairs.append(p)
        else:
            test_pairs.append(p)

    tw, tt_raw = pct_from_pairs_list(train_pairs)
    tew, tet_raw = pct_from_pairs_list(test_pairs)
    tt_ann = annualize_linear_trade_pnl_sum_pct(tt_raw, train_period_days)
    tet_ann = annualize_linear_trade_pnl_sum_pct(tet_raw, test_period_days)
    num_tr = compute_backtest_metrics_numeric_from_pairs(train_pairs)
    num_te = compute_backtest_metrics_numeric_from_pairs(test_pairs)

    annual_gap: float | None = None
    if tt_ann is not None and tet_ann is not None:
        annual_gap = float(tt_ann) - float(tet_ann)

    return {
        "train_win_rate_pct": tw,
        "train_total_return_pct": tt_ann,
        "train_total_return_pct_period": tt_raw,
        "train_profit_factor": num_tr.get("profit_factor"),
        "train_risk_reward": num_tr.get("risk_reward"),
        "train_max_loss_pct": num_tr.get("max_loss_pct"),
        "test_win_rate_pct": tew,
        "test_total_return_pct": tet_ann,
        "test_total_return_pct_period": tet_raw,
        "test_profit_factor": num_te.get("profit_factor"),
        "test_risk_reward": num_te.get("risk_reward"),
        "test_max_loss_pct": num_te.get("max_loss_pct"),
        "annual_return_gap": annual_gap,
        "train_trades": len(train_pairs),
        "test_trades": len(test_pairs),
        "train_end_date": train_end_str,
        "test_start_date": test_start_str,
        "split_idx": split_idx,
        "train_bars": split_info["train_bars"],
        "test_bars": split_info["test_bars"],
        "train_period_calendar_days": train_period_days,
        "test_period_calendar_days": test_period_days,
    }


def resolve_strategy_code_for_parameter_search(
    session: ChatSession,
    version_id: str | None,
) -> tuple[str | None, str | None]:
    """Load strategy code for optimization. Does not mutate session."""
    if version_id:
        path = AGENT_SESSIONS_DIR / session.session_id / "strategy_versions" / f"{version_id}.py"
        if not path.exists():
            return None, f"Strategy version {version_id} not found."
        return path.read_text(encoding="utf-8"), None
    code_to_run = ChatSession.get_latest_strategy_code_from_disk(session.session_id)
    if not code_to_run or not code_to_run.strip():
        code_to_run = session.active_code
    if not code_to_run or not code_to_run.strip():
        return None, "No active strategy to optimize. Run a backtest first."
    return code_to_run, None


async def load_full_history_ohlcv_for_parameter_search(
    session: ChatSession,
    ticker: str,
    version_id: str | None,
) -> dict[str, Any]:
    """Fetch widest allowed OHLCV + corporate merge once. Returns error dict on failure."""
    from backtester.data.corporate import detect_corporate_needs, download_corporate_data, merge_corporate_data
    from backtester.data.downloader import download_data
    from backtester.data.interval import full_history_date_range

    code_to_run, err = resolve_strategy_code_for_parameter_search(session, version_id)
    if err:
        return {"success": False, "error": err}

    strategy_nl = session.active_strategy or ""
    interval = session.active_interval or "1d"
    start, end, was_clamped = full_history_date_range(interval)

    try:
        data_df = await _run_sync(download_data, ticker.strip(), start, end, interval=interval)
    except Exception as exc:
        return {"success": False, "error": f"Data download failed: {exc}"}

    corporate_needs = detect_corporate_needs(strategy_nl)
    if corporate_needs:
        try:
            corporate = await _run_sync(download_corporate_data, ticker.strip(), corporate_needs, start, end)
            data_df = merge_corporate_data(data_df, corporate)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Corporate data merge failed during parameter search")
            return {"success": False, "error": f"Corporate data merge failed: {exc}"}

    return {
        "success": True,
        "data_df": data_df,
        "code_to_run": code_to_run,
        "strategy_nl": strategy_nl,
        "corporate_needs": corporate_needs,
        "history_start": start,
        "history_end": end,
        "was_clamped": was_clamped,
        "interval": interval,
    }


async def execute_parameter_search_combo(
    code_to_run: str,
    data_df: pd.DataFrame,
    strategy_nl: str,
    corporate_needs: Any,
    param_overrides: dict[str, str],
) -> dict[str, Any]:
    """Run strategy once on preloaded data; validate. Does not touch ChatSession."""
    from backtester.engine.executor import execute_strategy
    from backtester.engine.validator import validate_output

    exec_result = await _run_sync(
        execute_strategy,
        code_to_run,
        data_df,
        param_overrides=param_overrides,
    )
    if not exec_result.success:
        return {
            "success": False,
            "error": f"Execution failed: [{exec_result.error_type}] {exec_result.error_message}",
        }
    validation = await _run_sync(
        validate_output,
        exec_result.output_df,
        data_df,
        strategy_description=strategy_nl or None,
        corporate_needs=corporate_needs if corporate_needs else None,
        strategy_code=code_to_run,
    )
    if not validation.valid:
        return {"success": False, "error": f"Validation failed: {'; '.join(validation.issues)}"}
    return {"success": True, "signals_df": exec_result.output_df}


def mark_parameter_search_overfitting(rows: list[dict]) -> None:
    """Flag the worst 30% of rows by (train − test) estimated annual return % among positive gaps."""
    worst_frac = 0.30
    scored: list[tuple[float, dict]] = []
    for row in rows:
        if not row.get("success"):
            row["overfitting_risk"] = False
            continue
        gap = row.get("annual_return_gap")
        if gap is None or not isinstance(gap, (int, float)) or not math.isfinite(gap):
            row["overfitting_risk"] = False
            continue
        if gap <= 0:
            row["overfitting_risk"] = False
            continue
        scored.append((float(gap), row))
    if not scored:
        return
    scored.sort(key=lambda x: -x[0])
    n = len(scored)
    worst_n = max(1, int(math.ceil(n * worst_frac)))
    for i, (_, row) in enumerate(scored):
        row["overfitting_risk"] = i < worst_n


async def handle_get_backtesting_table(
    session: ChatSession,
    on_event: Callback,
    **kwargs,
) -> dict:
    """Return backtesting summary table: metrics computed from all trades (from profit/loss signal table)."""
    if session.active_signals_df is None:
        return {"success": False, "error": "No signals available. Run a backtest first."}

    pairs = _signals_to_trade_pairs(session.active_signals_df)
    summary = _compute_backtest_summary(pairs)

    headers = ["Metric", "Value"]
    rows = [[k, v] for k, v in summary.items()]

    formula = (
        r"Risk/Reward Ratio = \frac{|\text{Average Losing Trade}|}{|\text{Average Winning Trade}|}"
    )

    await on_event(TableEvent(
        title="Backtesting summary",
        headers=headers,
        rows=rows,
        formula=formula,
    ))
    return {
        "success": True,
        "total_trades": len(pairs),
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# get_signals_table
# ---------------------------------------------------------------------------

MAX_SIGNALS_TABLE_ROWS = 500


def _fmt_signal_table_cell(val: Any, col: str) -> str:
    """Stringify DataFrame cells for the signals UI table; round prices for readability."""
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    col_l = col.lower()
    if isinstance(val, numbers.Real) and not isinstance(val, bool):
        if "price" in col_l or col_l in ("open", "high", "low", "close"):
            return f"{float(val):.2f}"
    return str(val)


async def handle_get_signals_table(
    session: ChatSession,
    on_event: Callback,
    **kwargs,
) -> dict:
    """Return the backtest output signals as a table (emits TableEvent for the UI)."""
    if session.active_signals_df is None:
        return {"success": False, "error": "No signals available. Run a backtest first."}

    limit = kwargs.get("limit") or MAX_SIGNALS_TABLE_ROWS
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = MAX_SIGNALS_TABLE_ROWS
    if limit <= 0:
        limit = MAX_SIGNALS_TABLE_ROWS

    df = session.active_signals_df
    cols = list(df.columns)
    if not cols:
        return {"success": False, "error": "Signals DataFrame has no columns."}

    n_total = len(df)
    n_show = min(n_total, limit)
    head = df.head(n_show)

    headers = cols
    rows = []
    for _, row in head.iterrows():
        rows.append([_fmt_signal_table_cell(row[c], c) for c in cols])

    await on_event(TableEvent(
        title="Output signals" if n_total <= n_show else f"Output signals (first {n_show} of {n_total})",
        headers=headers,
        rows=rows,
    ))
    return {
        "success": True,
        "total_signals": n_total,
        "shown": n_show,
        "truncated": n_total > n_show,
        # Same cells as the UI table — the model does not see the WebSocket table; it must use this JSON.
        "headers": headers,
        "rows": rows,
        "cite_in_text": "Use only dates and prices from headers/rows when stating numbers in your reply; do not estimate from memory.",
    }


# ---------------------------------------------------------------------------
# fetch_data
# ---------------------------------------------------------------------------

async def handle_fetch_data(
    session: ChatSession,
    on_event: Callback,
    ticker: str,
    start: str = "2020-01-01",
    end: str = "2025-01-01",
    interval: str = "1d",
    include_corporate_events: bool = True,
    include_earnings: bool = False,
    **kwargs,
) -> dict:
    from backtester.data.corporate import detect_corporate_needs, download_corporate_data, merge_corporate_data
    from backtester.data.downloader import download_data
    from backtester.data.interval import clamp_date_range

    start, end, _ = clamp_date_range(start, end, interval)

    await on_event(ProgressEvent(step=FETCH_PREVIEW, status="running", detail=detail_load_running(ticker, interval, start, end)))
    try:
        data_df = await _run_sync(download_data, ticker, start, end, interval=interval)
    except Exception as exc:
        await on_event(ProgressEvent(step=FETCH_PREVIEW, status="failed", detail=str(exc)))
        return {"success": False, "error": str(exc)}

    await on_event(ProgressEvent(step=FETCH_PREVIEW, status="success", detail=detail_data_loaded(len(data_df), ticker, interval, start, end)))

    corporate_needs: set[str] = set()
    if include_corporate_events:
        if session.corporate_needs_snapshot:
            corporate_needs |= set(session.corporate_needs_snapshot)
        corporate_needs |= detect_corporate_needs(session.active_strategy or "")
    if include_earnings:
        corporate_needs.add("earnings")

    if corporate_needs:
        await on_event(
            ProgressEvent(
                step=CORPORATE_CONTEXT,
                status="running",
                detail=detail_corporate_running(corporate_needs),
            )
        )
        try:
            corporate = await _run_sync(download_corporate_data, ticker, corporate_needs, start, end)
            data_df = merge_corporate_data(data_df, corporate)
            await on_event(ProgressEvent(step=CORPORATE_CONTEXT, status="success", detail=detail_corporate_success()))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Corporate merge in fetch_data failed")
            await on_event(ProgressEvent(step=CORPORATE_CONTEXT, status="failed", detail=str(exc)[:120]))

    preview = data_df.head(5).to_dict(orient="records")
    result: dict[str, Any] = {
        "success": True,
        "ticker": ticker,
        "interval": interval,
        "rows": len(data_df),
        "columns": list(data_df.columns),
        "date_range": f"{data_df['Date'].iloc[0]} to {data_df['Date'].iloc[-1]}",
        "preview": json.dumps(preview, default=str),
        "corporate": _corporate_data_dict_for_tool(data_df),
    }
    return result


async def handle_get_corporate_data(
    session: ChatSession,
    on_event: Callback,
    ticker: str | None = None,
    start: str | None = None,
    end: str | None = None,
    **kwargs,
) -> dict:
    """Return merged earnings (and related) corporate columns: prefer session data, else fetch."""
    from backtester.data.corporate import download_corporate_data, merge_corporate_data
    from backtester.data.downloader import download_data
    from backtester.data.interval import clamp_date_range

    ticker = ticker or session.active_ticker
    if not ticker:
        return {"success": False, "error": "No ticker. Pass ticker= or run a backtest first."}

    interval = session.active_interval or "1d"
    start = start or session.start_date or "2020-01-01"
    end = end or session.end_date or "2025-12-31"
    start, end, _ = clamp_date_range(start, end, interval)

    df = session.active_data_df
    use_session = (
        df is not None
        and not df.empty
        and "Is_Earnings_Day" in df.columns
        and session.active_ticker is not None
        and ticker == session.active_ticker
    )

    if use_session:
        data_df = df.copy()
        dts = pd.to_datetime(data_df["Date"])
        mask = (dts >= pd.Timestamp(start)) & (dts <= pd.Timestamp(end))
        data_df = data_df.loc[mask].reset_index(drop=True)
        await on_event(
            ProgressEvent(
                step=CORPORATE_CONTEXT,
                status="success",
                detail=detail_corporate_from_session(len(data_df)),
            )
        )
    else:
        await on_event(ProgressEvent(step=LOAD_MARKET_DATA, status="running", detail=detail_load_running(ticker, interval, start, end)))
        try:
            data_df = await _run_sync(download_data, ticker, start, end, interval=interval)
        except Exception as exc:
            await on_event(ProgressEvent(step=LOAD_MARKET_DATA, status="failed", detail=str(exc)))
            return {"success": False, "error": str(exc)}
        await on_event(ProgressEvent(step=LOAD_MARKET_DATA, status="success", detail=detail_data_loaded(len(data_df), ticker, interval, start, end)))
        await on_event(ProgressEvent(step=CORPORATE_CONTEXT, status="running", detail=detail_corporate_running({"earnings"})))
        try:
            corporate = await _run_sync(
                download_corporate_data, ticker, {"earnings"}, start, end
            )
            data_df = merge_corporate_data(data_df, corporate)
            await on_event(ProgressEvent(step=CORPORATE_CONTEXT, status="success", detail=detail_corporate_success()))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("get_corporate_data fetch failed")
            await on_event(ProgressEvent(step=CORPORATE_CONTEXT, status="failed", detail=str(exc)[:120]))
            return {"success": False, "error": str(exc)}

    corp = _corporate_data_dict_for_tool(data_df)
    rows = corp.get("earnings_calendar") or []
    if rows:
        headers = list(rows[0].keys())
        table_rows = [[str(r.get(h, "")) for h in headers] for r in rows[:80]]
        await on_event(
            TableEvent(
                title=f"Earnings calendar ({ticker}) — {corp.get('earnings_days_in_range', 0)} day(s) in range",
                headers=headers,
                rows=table_rows,
            )
        )

    return {
        "success": True,
        "ticker": ticker,
        "interval": interval,
        "date_range": f"{start} to {end}",
        "source": "session_active_data_df" if use_session else "fetched",
        **corp,
    }


# ---------------------------------------------------------------------------
# rerun_on_ticker  (no LLM — reuses existing strategy code on a new ticker)
# ---------------------------------------------------------------------------

async def handle_rerun_on_ticker(
    session: ChatSession,
    on_event: Callback,
    ticker: str,
    start: str = "",
    end: str = "",
    param_overrides: dict | None = None,
    version_id: str | None = None,
    **kwargs,
) -> dict:
    """Re-execute strategy code on a different ticker's data. Use version_id for a historical code version, else current active code."""
    if version_id:
        path = AGENT_SESSIONS_DIR / session.session_id / "strategy_versions" / f"{version_id}.py"
        if not path.exists():
            return {"success": False, "error": f"Strategy version {version_id} not found."}
        code_to_run = path.read_text(encoding="utf-8")
    else:
        # "Latest": use most recent saved strategy file (manifest last entry) or session active code. No new version is created on rerun.
        code_to_run = ChatSession.get_latest_strategy_code_from_disk(session.session_id)
        if not code_to_run or not code_to_run.strip():
            code_to_run = session.active_code
        if code_to_run:
            session.active_code = code_to_run
    if not code_to_run or not code_to_run.strip():
        return {"success": False, "error": "No active strategy to rerun. Run a backtest first."}

    from backtester.data.downloader import download_data
    from backtester.data.interval import clamp_date_range
    from backtester.engine.executor import execute_strategy
    from backtester.engine.validator import validate_output

    interval = session.active_interval or "1d"
    if not start:
        start = "2000-01-01"
    if not end:
        end = "2025-12-31"
    start, end, _ = clamp_date_range(start, end, interval)

    await on_event(ProgressEvent(step=LOAD_MARKET_DATA, status="running", detail=detail_load_running(ticker, interval, start, end)))
    try:
        data_df = await _run_sync(download_data, ticker, start, end, interval=interval)
    except Exception as exc:
        await on_event(ProgressEvent(step=LOAD_MARKET_DATA, status="failed", detail=str(exc)))
        return {"success": False, "error": f"Data download failed: {exc}"}
    await on_event(ProgressEvent(step=LOAD_MARKET_DATA, status="success", detail=detail_data_loaded(len(data_df), ticker, interval, start, end)))

    strategy_nl = session.active_strategy or ""
    from backtester.data.corporate import detect_corporate_needs, download_corporate_data, merge_corporate_data

    corporate_needs = detect_corporate_needs(strategy_nl)
    if corporate_needs:
        await on_event(ProgressEvent(step=CORPORATE_CONTEXT, status="running", detail=detail_corporate_running(corporate_needs)))
        try:
            corporate = await _run_sync(download_corporate_data, ticker, corporate_needs, start, end)
            data_df = merge_corporate_data(data_df, corporate)
            await on_event(ProgressEvent(step=CORPORATE_CONTEXT, status="success", detail=detail_corporate_success()))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("Corporate data merge failed on rerun")
            await on_event(ProgressEvent(step=CORPORATE_CONTEXT, status="failed", detail=str(exc)[:120]))

    await on_event(ProgressEvent(step=SIMULATE_TRADES, status="running", detail=detail_rerun_code()))
    exec_result = await _run_sync(
        execute_strategy,
        code_to_run,
        data_df,
        param_overrides=param_overrides,
    )

    if not exec_result.success:
        await on_event(ProgressEvent(step=SIMULATE_TRADES, status="failed", detail=detail_fix_error(exec_result.error_type, exec_result.error_message)))
        return {
            "success": False,
            "error": f"Execution failed: [{exec_result.error_type}] {exec_result.error_message}",
        }
    await on_event(ProgressEvent(step=SIMULATE_TRADES, status="success", detail=detail_signals(exec_result.signal_count)))

    await on_event(ProgressEvent(step=VALIDATE_SIGNALS, status="running"))
    validation = await _run_sync(
        validate_output,
        exec_result.output_df,
        data_df,
        strategy_description=strategy_nl or None,
        corporate_needs=corporate_needs if corporate_needs else None,
        strategy_code=code_to_run,
    )
    rerun_ui_vid = _rerun_version_id_for_ui(session.session_id, version_id, code_to_run)
    if rerun_ui_vid:
        await on_event(StrategyVersionEvent(version_id=rerun_ui_vid))
    if not validation.valid:
        await on_event(ProgressEvent(step=VALIDATE_SIGNALS, status="failed", detail="; ".join(validation.issues)[:80]))
        return {"success": False, "error": f"Validation failed: {'; '.join(validation.issues)}"}
    await on_event(ProgressEvent(step=VALIDATE_SIGNALS, status="success", detail=detail_validation_success(len(validation.test_results))))

    await on_event(ProgressEvent(step=BACKTEST_DONE, status="success", detail=detail_signals(exec_result.signal_count)))

    session.active_ticker = ticker
    session.active_data_df = data_df
    session.active_signals_df = exec_result.output_df
    session.active_indicator_df = exec_result.indicator_df
    session.active_indicator_columns = exec_result.indicator_columns or []

    buy_count = int((exec_result.output_df["Signal"] == "BUY").sum())
    sell_count = int((exec_result.output_df["Signal"] == "SELL").sum())

    session.add_run(RunSummary(
        ticker=ticker,
        strategy=session.active_strategy or "",
        interval=interval,
        signal_count=exec_result.signal_count,
        buy_count=buy_count,
        sell_count=sell_count,
        attempts=1,
        success=True,
    ))

    # Do not create a new strategy version on rerun — rerun only executes an existing saved version on a new ticker/params.

    first_date = str(exec_result.output_df["Date"].iloc[0]) if len(exec_result.output_df) > 0 else "N/A"
    last_date = str(exec_result.output_df["Date"].iloc[-1]) if len(exec_result.output_df) > 0 else "N/A"

    summary = (
        f"Replayed your saved strategy on **{ticker}** ({interval_phrase(interval)}, "
        f"{format_backtest_window_label(start, end)}): "
        f"{exec_result.signal_count} signals ({buy_count} buys, {sell_count} sells), "
        f"from **{first_date}** through **{last_date}**."
    )
    await on_event(TextEvent(content=summary))

    return {
        "success": True,
        "ticker": ticker,
        "interval": interval,
        "total_signals": exec_result.signal_count,
        "buy_signals": buy_count,
        "sell_signals": sell_count,
        "first_signal_date": first_date,
        "last_signal_date": last_date,
        "rerun_strategy_version_id": rerun_ui_vid or None,
    }


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOL_HANDLERS: dict[str, Callable] = {
    "run_backtest": handle_run_backtest,
    "refine_strategy": handle_refine_strategy,
    "fix_strategy": handle_fix_strategy,
    "query_results": handle_query_results,
    "run_custom_analysis": handle_run_custom_analysis,
    "show_code": handle_show_code,
    "get_signal_summary": handle_get_signal_summary,
    "get_signals_table": handle_get_signals_table,
    "get_trades_table": handle_get_trades_table,
    "get_backtesting_table": handle_get_backtesting_table,
    "fetch_data": handle_fetch_data,
    "get_corporate_data": handle_get_corporate_data,
}


async def execute_tool(
    session: ChatSession,
    tool_name: str,
    arguments: dict,
    on_event: Callback,
    provider=None,
) -> dict:
    """Dispatch to the appropriate tool handler."""
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return {"success": False, "error": f"Unknown tool: {tool_name}"}

    kwargs: dict[str, Any] = {
        "session": session,
        "on_event": on_event,
        **arguments,
    }
    if tool_name in ("run_backtest", "refine_strategy", "fix_strategy", "query_results", "run_custom_analysis"):
        kwargs["provider"] = provider

    # Use session date range for run_backtest when set (calendar-picked, used for whole conversation)
    if tool_name == "run_backtest" and getattr(session, "start_date", None) and getattr(session, "end_date", None):
        kwargs["start"] = session.start_date
        kwargs["end"] = session.end_date

    try:
        return await handler(**kwargs)
    except Exception as exc:
        await on_event(ErrorEvent(message=str(exc)))
        return {"success": False, "error": str(exc), "traceback": traceback.format_exc()}


def _extract_code(text: str) -> str:
    """Extract Python code from markdown fences or raw text."""
    import re
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()
