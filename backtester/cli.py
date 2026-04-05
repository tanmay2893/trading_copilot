"""CLI entry point with live spinners and step-by-step status output."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import json
import typer

from backtester.ui import console, print_code, print_error_box, print_header, step

app = typer.Typer(
    name="backtester",
    help="Financial backtesting from natural-language strategy descriptions",
    add_completion=False,
    no_args_is_help=True,
)


@app.command()
def run(
    strategy: Optional[str] = typer.Option(None, "--strategy", "-s", help="NLP strategy description"),
    strategy_file: Optional[str] = typer.Option(None, "--strategy-file", "-f", help="Path to file containing strategy description"),
    ticker: str = typer.Option(..., "--ticker", "-t", help="Stock ticker symbol (e.g. AAPL)"),
    start: str = typer.Option("2020-01-01", "--start", help="Start date (YYYY-MM-DD)"),
    end: str = typer.Option("2025-01-01", "--end", help="End date (YYYY-MM-DD)"),
    interval: str = typer.Option("auto", "--interval", help="Data interval: auto | 1m | 5m | 15m | 30m | 1h | 1d | 1wk | 1mo (auto=detect from strategy)"),
    model: str = typer.Option("deepseek", "--model", "-m", help="Remote model: opus | openai | deepseek"),
    max_iterations: int = typer.Option(10, "--max-iterations", "-n", help="Max retry iterations"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output CSV path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show generated code"),
    no_analyze: bool = typer.Option(False, "--no-analyze", help="Skip pre-flight strategy analysis"),
):
    """Generate and run a backtesting strategy from natural language."""
    from backtester.data.interval import (
        INTERVAL_LABELS,
        VALID_INTERVALS,
        clamp_date_range,
        detect_interval,
    )

    strategy_text = _resolve_strategy(strategy, strategy_file)
    output_path = output or f"./signals_{ticker}.csv"

    # --- Resolve interval ---
    if interval == "auto":
        resolved_interval = detect_interval(strategy_text)
        console.print(f"  [dim]Detected interval:[/] {resolved_interval} ({INTERVAL_LABELS.get(resolved_interval, resolved_interval)})")
    else:
        if interval not in VALID_INTERVALS:
            print_error_box("Error", f"Invalid interval '{interval}'. Valid: {', '.join(VALID_INTERVALS)}")
            raise typer.Exit(1)
        resolved_interval = interval

    # --- Clamp date range for intraday limits ---
    start, end, was_clamped = clamp_date_range(start, end, resolved_interval)
    if was_clamped:
        console.print(f"  [yellow]Date range clamped to {start} -> {end} (yfinance {resolved_interval} limit)[/yellow]")

    print_header(
        f"backtester | {ticker}",
        f"{start} -> {end} | interval={resolved_interval} | model={model} | max_iter={max_iterations}",
    )

    console.print(f"  [dim]Strategy:[/] {strategy_text[:120]}{'...' if len(strategy_text) > 120 else ''}")
    console.print()

    # --- Download data ---
    from backtester.data.downloader import download_data

    with step("Downloading data", f"{ticker} {resolved_interval} {start}->{end}") as s:
        data_df = download_data(ticker, start, end, interval=resolved_interval)
        s.succeed(f"{len(data_df):,} rows ({data_df['Date'].iloc[0]} -> {data_df['Date'].iloc[-1]})")

    # --- Detect & fetch corporate event data if needed ---
    from backtester.data.corporate import detect_corporate_needs, download_corporate_data, merge_corporate_data

    corporate_needs = detect_corporate_needs(strategy_text)
    has_corporate_data = False
    if corporate_needs:
        with step("Fetching corporate data", ", ".join(sorted(corporate_needs))) as s:
            corporate = download_corporate_data(ticker, corporate_needs, start, end)
            data_df = merge_corporate_data(data_df, corporate)
            has_corporate_data = True
            s.succeed(", ".join(sorted(corporate_needs)))

    # --- Initialize LLM ---
    from backtester.llm.router import get_provider

    with step("Connecting to LLM", model):
        provider = get_provider(model, use_env_keys=True)

    # --- Pre-flight strategy analysis ---
    if not no_analyze:
        from backtester.engine.strategy_analyzer import analyze_strategy, _build_corporate_summary

        with step("Analyzing strategy", "LLM") as s:
            corp_summary = _build_corporate_summary(data_df, corporate_needs) if corporate_needs else {}
            analysis = analyze_strategy(
                provider=provider,
                strategy_text=strategy_text,
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
            s.succeed(analysis.verdict)

        if analysis.verdict == "revise" and analysis.revised_strategy:
            strategy_text, resolved_interval, data_df, has_corporate_data, corporate_needs = (
                _handle_revision(
                    analysis, strategy_text, ticker, start, end,
                    interval, resolved_interval, data_df, has_corporate_data, corporate_needs,
                    provider=provider,
                )
            )

    # --- Run iteration loop (with mid-loop intervention) ---
    from backtester.engine.iteration_engine import run_iteration_loop, save_run_artifacts
    from backtester.ui import print_intervention_panel

    while True:
        console.print()
        console.print("  [bold]Iteration loop[/]")
        console.print("  [dim]─" * 40 + "[/]")

        result = run_iteration_loop(
            provider=provider,
            strategy_description=strategy_text,
            data_df=data_df,
            max_iterations=max_iterations,
            verbose=verbose,
            interval=resolved_interval,
            has_corporate_data=has_corporate_data,
        )

        console.print("  [dim]─" * 40 + "[/]")
        console.print()

        if result.success:
            break

        if not result.needs_intervention or not result.diagnosis:
            break

        # --- Mid-loop intervention: show diagnosis and ask user ---
        print_intervention_panel(result.diagnosis, max_iterations)

        import sys
        if sys.stdin.isatty():
            from rich.prompt import Prompt
            choice = Prompt.ask("  Choose", choices=["1", "2", "3", "4"], default="1", console=console)
        else:
            console.print("  [dim]Non-interactive mode — auto-accepting relaxed strategy.[/]")
            choice = "1"

        if choice == "1":
            strategy_text = result.diagnosis.revised_strategy
            console.print("  [green]✓[/] Using relaxed strategy.")
            strategy_text, resolved_interval, data_df, has_corporate_data, corporate_needs = (
                _repipeline_strategy(
                    strategy_text, ticker, start, end,
                    interval, resolved_interval, data_df, has_corporate_data, corporate_needs,
                )
            )
        elif choice == "2":
            custom = console.input("  [bold]Enter revised strategy:[/] ")
            if custom.strip():
                strategy_text = custom.strip()
                console.print("  [green]✓[/] Using your custom strategy.")
                strategy_text, resolved_interval, data_df, has_corporate_data, corporate_needs = (
                    _repipeline_strategy(
                        strategy_text, ticker, start, end,
                        interval, resolved_interval, data_df, has_corporate_data, corporate_needs,
                    )
                )
            else:
                console.print("  [dim]No input — keeping original strategy.[/]")
        elif choice == "3":
            console.print(f"  [dim]Retrying with original strategy ({max_iterations} more attempts)...[/]")
            continue
        else:
            console.print("  [dim]Aborted by user.[/]")
            break

        continue

    # --- Save artifacts ---
    with step("Saving run artifacts"):
        run_dir = save_run_artifacts(ticker, strategy_text, result, data_df, interval=resolved_interval)

    if result.success:
        from backtester.engine.indicator_selector import (
            IndicatorSelection,
            build_chart_dataframe,
            select_chart_indicators,
        )
        from backtester.engine.parameter_extractor import get_parameters_used
        from backtester.output.formatter import (
            print_chart_indicators,
            print_parameters_used,
            print_run_summary,
            save_chart_data_csv,
            save_signals_csv,
        )

        with step("Writing signals CSV", output_path):
            save_signals_csv(result.signals_df, output_path)

        # --- Indicator selection for chart data ---
        chart_data_path: str | None = None
        indicator_selection: IndicatorSelection | None = None

        if result.indicator_df is not None and result.indicator_columns:
            ohlcv_base = ["Date", "date", "Open", "High", "Low", "Close", "Volume"]
            original_cols = [c for c in result.indicator_df.columns if c in ohlcv_base]

            with step("Selecting chart indicators", "LLM (classify + review)") as s:
                indicator_selection = select_chart_indicators(
                    provider=provider,
                    strategy_code=result.code,
                    strategy_description=strategy_text,
                    indicator_columns=result.indicator_columns,
                    original_columns=original_cols,
                )
                result.total_input_tokens += indicator_selection.input_tokens
                result.total_output_tokens += indicator_selection.output_tokens
                n_selected = len(indicator_selection.overlay) + len(indicator_selection.oscillator)
                s.succeed(
                    f"{n_selected} indicators selected "
                    f"({len(indicator_selection.overlay)} overlay, "
                    f"{len(indicator_selection.oscillator)} oscillator)"
                )

            chart_df = build_chart_dataframe(result.indicator_df, indicator_selection)
            if not chart_df.empty:
                chart_data_path = output_path.replace(".csv", "_chart_data.csv")
                if chart_data_path == output_path:
                    chart_data_path = "./chart_data_" + ticker + ".csv"
                with step("Writing chart data CSV", chart_data_path):
                    save_chart_data_csv(chart_df, chart_data_path)
                    (run_dir / "chart_data.csv").parent.mkdir(parents=True, exist_ok=True)
                    chart_df.to_csv(run_dir / "chart_data.csv", index=False)

        with step("Extracting parameters", "LLM"):
            param_lines, param_raw = get_parameters_used(provider, result.code)
            (run_dir / "parameters.txt").write_text(param_raw, encoding="utf-8")
            # Save structured parameters for future interactive overrides.
            try:
                param_struct = [
                    {"name": p.name, "value": p.value, "description": p.description}
                    for p in param_lines
                ]
                (run_dir / "parameters.json").write_text(
                    json.dumps(param_struct, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                # Non-fatal: rerun parameter UI will simply not be available.
                pass

        if verbose:
            print_code(result.code, "Final Strategy")

        print_run_summary(
            result.signals_df, output_path, ticker,
            result.attempts, result.total_input_tokens, result.total_output_tokens,
            chart_data_path=chart_data_path,
        )
        if indicator_selection:
            print_chart_indicators(indicator_selection)
        print_parameters_used(param_lines, run_dir)

        # --- Run same strategy on other stocks (interactive, with optional parameter overrides, no LLM) ---
        _run_on_other_stocks_loop(
            strategy_code=result.code,
            strategy_text=strategy_text,
            indicator_selection=indicator_selection,
            resolved_interval=resolved_interval,
            start=start,
            end=end,
            corporate_needs=corporate_needs,
            verbose=verbose,
            run_dir=run_dir,
        )
    else:
        print_error_box(
            f"Failed after {result.attempts} attempts",
            "\n".join(
                f"[{e['error_type']}] {e['message'][:120]}"
                for e in result.error_history[-3:]
            ) or "Unknown error",
        )
        if result.code:
            print_code(result.code, "Last Attempted Strategy")
        console.print(f"\n  [dim]Run artifacts saved to: {run_dir}[/]")
        console.print("  [dim]Try: backtester fix --issue \"describe the problem\" --last-run[/]\n")
        raise typer.Exit(1)


@app.command()
def fix(
    issue: str = typer.Option(..., "--issue", "-i", help="Describe the problem"),
    last_run: bool = typer.Option(True, "--last-run", help="Use artifacts from the most recent run"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override model"),
    max_iterations: int = typer.Option(5, "--max-iterations", "-n", help="Max fix iterations"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """Fix a previously run strategy based on a user-reported issue."""
    from backtester.engine.iteration_engine import load_latest_artifacts, run_fix_loop, save_run_artifacts
    from backtester.llm.router import get_provider

    print_header("backtester | fix", f'Issue: "{issue}"')

    if not last_run:
        print_error_box("Error", "Only --last-run is supported currently")
        raise typer.Exit(1)

    with step("Loading previous run"):
        artifacts = load_latest_artifacts()
        if artifacts is None:
            print_error_box("Error", "No previous run found. Run `backtester run` first.")
            raise typer.Exit(1)

    model_alias = model or "deepseek"
    with step("Connecting to LLM", model_alias):
        provider = get_provider(model_alias, use_env_keys=True)

    data_df = artifacts.data_df
    resolved_interval = artifacts.interval

    from backtester.engine.chart_renderer import render_chart_to_base64

    with step("Rendering chart screenshot"):
        chart_image = render_chart_to_base64(
            data_df=data_df,
            signals_df=artifacts.signals_df,
            indicator_columns=[],
            title=f"Fix target — {resolved_interval}",
        )
        if chart_image:
            console.print("  [dim]Chart screenshot captured for LLM vision context[/]")

    console.print(f"  [dim]Interval:[/] {resolved_interval}")
    console.print()
    console.print("  [bold]Fix loop[/]")
    console.print("  [dim]─" * 40 + "[/]")

    result = run_fix_loop(
        provider=provider,
        issue=issue,
        artifacts=artifacts,
        data_df=data_df,
        max_iterations=max_iterations,
        verbose=verbose,
        interval=resolved_interval,
        chart_image=chart_image,
    )

    console.print("  [dim]─" * 40 + "[/]")
    console.print()

    if result.success:
        from backtester.output.formatter import print_run_summary, save_signals_csv

        output_path = "./signals_fixed.csv"
        with step("Writing fixed signals CSV", output_path):
            save_signals_csv(result.signals_df, output_path)

        with step("Saving run artifacts"):
            save_run_artifacts("fixed", issue[:50], result, data_df)

        print_run_summary(
            result.signals_df, output_path, "fixed",
            result.attempts, result.total_input_tokens, result.total_output_tokens,
        )
    else:
        print_error_box(
            f"Fix failed after {result.attempts} attempts",
            "\n".join(
                f"[{e['error_type']}] {e['message'][:120]}"
                for e in result.error_history[-3:]
            ) or "Unknown error",
        )
        raise typer.Exit(1)


@app.command()
def refine(
    model: str = typer.Option("deepseek", "--model", "-m", help="Remote model: opus | openai | deepseek"),
    resume: Optional[str] = typer.Option(None, "--resume", help="Session ID to resume"),
    max_iterations: int = typer.Option(5, "--max-iterations", "-n", help="Max attempts per change"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show generated code"),
):
    """Interactively refine a previously generated strategy through conversation."""
    from backtester.engine.refine_engine import run_refine_turn
    from backtester.engine.session import RefineSession
    from backtester.llm.router import get_provider
    from backtester.ui import (
        print_code_diff,
        print_conversation_history,
        print_refine_failure,
        print_refine_header,
        print_refine_help,
        print_signal_summary,
        print_turn_summary,
    )

    import pandas as pd

    # --- Load or resume session ---
    session: RefineSession | None = None

    if resume:
        with step("Loading session", resume):
            session = RefineSession.load(resume)
            if session is None:
                print_error_box("Error", f"Session '{resume}' not found.")
                raise typer.Exit(1)
    else:
        with step("Loading latest run"):
            from backtester.engine.iteration_engine import load_latest_artifacts
            artifacts = load_latest_artifacts()
            if artifacts is None:
                print_error_box("Error", "No previous run found. Run `backtester run` first.")
                raise typer.Exit(1)
            if not artifacts.generated_code:
                print_error_box("Error", "Previous run has no generated code.")
                raise typer.Exit(1)

        latest_link = __import__("backtester.config", fromlist=["RUNS_DIR"]).RUNS_DIR / "latest"
        run_dir = Path(latest_link.read_text().strip())
        data_path = str(run_dir / "data.csv")

        meta_path = run_dir / "meta.json"
        ticker = run_dir.name.rsplit("_", 1)[0]
        interval = artifacts.interval

        session = RefineSession.new_session(
            ticker=ticker,
            interval=interval,
            strategy_description=artifacts.strategy_description,
            data_path=data_path,
            current_code=artifacts.generated_code,
        )

    # --- Load data ---
    with step("Loading data", session.data_path):
        data_df = pd.read_csv(session.data_path)

    # --- Connect LLM ---
    with step("Connecting to LLM", model):
        provider = get_provider(model, use_env_keys=True)

    # --- Execute current code to get baseline signals ---
    from backtester.engine.executor import execute_strategy
    current_signals_df: pd.DataFrame | None = None
    try:
        with step("Running current strategy"):
            exec_result = execute_strategy(session.current_code, data_df)
            if exec_result.success:
                current_signals_df = exec_result.output_df
    except Exception:
        console.print("  [dim]Could not run baseline strategy (non-fatal).[/]")

    # --- Display session header ---
    print_refine_header(session)
    if current_signals_df is not None:
        print_signal_summary(current_signals_df)
        console.print()

    # --- Interactive REPL ---
    while True:
        try:
            user_input = console.input("[bold cyan]refine>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            user_input = "exit"

        if not user_input:
            continue

        command = user_input.lower()

        if command in ("exit", "quit"):
            with step("Saving session"):
                session.save()
            console.print(f"  [dim]Session saved. Resume with:[/] backtester refine --resume {session.session_id}")
            console.print()
            break

        if command == "help":
            print_refine_help()
            continue

        if command == "history":
            print_conversation_history(session)
            continue

        if command == "code":
            print_code(session.current_code, "Current Strategy")
            continue

        if command == "signals":
            if current_signals_df is not None:
                print_signal_summary(current_signals_df)
            else:
                console.print("  [dim]No signals available.[/]")
            continue

        if command == "undo":
            if session.undo():
                console.print("  [green]✓[/] Reverted to previous version.")
                with step("Running reverted strategy"):
                    exec_result = execute_strategy(session.current_code, data_df)
                    if exec_result.success:
                        current_signals_df = exec_result.output_df
                if current_signals_df is not None:
                    print_signal_summary(current_signals_df)
                console.print()
            else:
                console.print("  [dim]Nothing to undo.[/]")
            continue

        # --- Treat as a change request ---
        prev_signals_df = current_signals_df
        code_before = session.current_code

        from backtester.engine.chart_renderer import render_chart_to_base64

        refine_chart = render_chart_to_base64(
            data_df=data_df,
            signals_df=current_signals_df,
            indicator_columns=[],
        )

        console.print()
        result = run_refine_turn(
            session=session,
            change_request=user_input,
            provider=provider,
            df=data_df,
            max_attempts=max_iterations,
            verbose=verbose,
            chart_image=refine_chart,
        )

        if result.success:
            if verbose:
                print_code_diff(code_before, result.code)
            print_turn_summary(
                len(session.conversation),
                result.summary,
                result.signals_df,
                prev_signals_df,
            )
            current_signals_df = result.signals_df
            session.save()
        else:
            print_refine_failure(result.error_message, result.attempts)


def _load_stock_list():
    """Load US and India stock lists from us_stocks.csv and india_stocks.csv."""
    import pandas as pd

    root = Path(__file__).resolve().parent.parent
    frames = []
    for path, country in [(root / "us_stocks.csv", "US"), (root / "india_stocks.csv", "INDIA")]:
        if path.exists():
            df = pd.read_csv(path)
            df["Country"] = country
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["Symbol", "Name", "Country"])
    return pd.concat(frames, ignore_index=True)


def _search_stocks(stock_df, query: str, max_results: int = 15):
    """Search stocks by symbol or name (case-insensitive).

    Priority: exact symbol > symbol-starts-with > name-contains.
    """
    query_upper = query.strip().upper()
    if not query_upper:
        return stock_df.head(max_results)

    exact = stock_df[stock_df["Symbol"].str.upper() == query_upper]
    if not exact.empty:
        return exact

    starts_with = stock_df[stock_df["Symbol"].str.upper().str.startswith(query_upper)]
    name_match = stock_df[stock_df["Name"].str.upper().str.contains(query_upper, na=False)]

    import pandas as pd
    combined = pd.concat([starts_with, name_match]).drop_duplicates(subset=["Symbol"])
    return combined.head(max_results)


def _load_run_parameters(run_dir: Path) -> list[dict]:
    """Load structured parameters saved for a run, if available."""
    param_path = run_dir / "parameters.json"
    if not param_path.exists():
        return []
    try:
        data = json.loads(param_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            # Normalize shape.
            out = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                out.append(
                    {
                        "name": str(item.get("name", "")),
                        "value": str(item.get("value", "")),
                        "description": str(item.get("description", "")),
                    }
                )
            return out
    except Exception:
        return []
    return []


def _prompt_parameter_overrides(params: list[dict]) -> dict[str, str]:
    """Display parameters and let the user override defaults for this rerun."""
    if not params:
        return {}

    console.print()
    console.print("  [bold cyan]Strategy parameters[/]")
    console.print("  [dim]Press Enter to keep defaults, or override by index or name.[/]")
    for idx, p in enumerate(params, 1):
        desc = p.get("description") or "-"
        console.print(
            f"    [cyan]{idx}[/] [bold]{p.get('name')}[/] = [green]{p.get('value')}[/]  [dim]{desc}[/]"
        )

    console.print()
    try:
        raw = console.input(
            "  [bold]Overrides[/] (e.g. 1=20,3=0.8 or RSI_PERIOD=20; Enter for defaults): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return {}

    if not raw:
        return {}

    overrides: dict[str, str] = {}
    entries = [e.strip() for e in raw.split(",") if e.strip()]
    for entry in entries:
        if "=" not in entry:
            continue
        key, val = entry.split("=", 1)
        key = key.strip()
        val = val.strip()
        if not key:
            continue
        # Support numeric index (1-based) or parameter name.
        if key.isdigit():
            idx = int(key) - 1
            if 0 <= idx < len(params):
                name = params[idx]["name"]
                overrides[name] = val
        else:
            # Match by name (case-sensitive).
            names = [p["name"] for p in params]
            if key in names:
                overrides[key] = val
    return overrides


def _prompt_date_range_for_rerun(start: str, end: str) -> tuple[str, str]:
    """Ask user for start/end date for this rerun; defaults to the given (initial) values."""
    console.print()
    console.print("  [bold cyan]Date range for this run[/]")
    console.print("  [dim]Press Enter to keep current range, or type a new date (YYYY-MM-DD).[/]")
    console.print(f"  Current: [green]{start}[/] → [green]{end}[/]")
    console.print()
    try:
        raw_start = console.input(f"  [bold]Start date[/] [{start}]: ").strip()
        raw_end = console.input(f"  [bold]End date[/] [{end}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return start, end
    new_start = raw_start if raw_start else start
    new_end = raw_end if raw_end else end
    return new_start, new_end


def _run_on_other_stocks_loop(
    strategy_code: str,
    strategy_text: str,
    indicator_selection,
    resolved_interval: str,
    start: str,
    end: str,
    corporate_needs: set,
    verbose: bool = False,
    run_dir: Path | None = None,
):
    """Interactive loop to re-run the same strategy on different stocks.

    No LLM calls are made — the existing code and indicator classification are reused.
    """
    import sys

    if not sys.stdin.isatty():
        return

    from backtester.data.downloader import download_data
    from backtester.engine.executor import execute_strategy
    from backtester.engine.indicator_selector import build_chart_dataframe
    from backtester.engine.validator import validate_output
    from backtester.output.formatter import print_run_summary, save_chart_data_csv, save_signals_csv
    from backtester.ui import print_rerun_header, print_stock_search_results

    stock_df = _load_stock_list()
    if stock_df.empty:
        return

    console.print()
    console.print("  [bold cyan]── Run on other stocks ──[/]")
    console.print("  [dim]Search by ticker or company name. Type 'exit' to quit.[/]")
    console.print()

    while True:
        try:
            query = console.input("[bold cyan]stock>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        if not query or query.lower() in ("exit", "quit", "q"):
            break

        matches = _search_stocks(stock_df, query)
        if matches.empty:
            console.print("  [dim]No matches found. Try a different term.[/]")
            continue

        print_stock_search_results(matches)

        if len(matches) == 1:
            selected = matches.iloc[0]
        else:
            try:
                choice = console.input("  [bold]Select #[/] (Enter to search again): ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break

            if not choice:
                continue

            try:
                idx = int(choice) - 1
                if idx < 0 or idx >= len(matches):
                    console.print("  [dim]Invalid selection.[/]")
                    continue
                selected = matches.iloc[idx]
            except ValueError:
                console.print("  [dim]Enter a number from the list.[/]")
                continue

        new_ticker = selected["Symbol"]
        country = selected.get("Country", "US")
        print_rerun_header(new_ticker, selected["Name"], country)

        # --- Date range for this rerun (default: same as initial run) ---
        rerun_start, rerun_end = _prompt_date_range_for_rerun(start, end)

        # --- Optional parameter overrides for this rerun ---
        param_overrides: dict[str, str] = {}
        if run_dir is not None:
            params = _load_run_parameters(run_dir)
            if params:
                param_overrides = _prompt_parameter_overrides(params)

        # --- Download data ---
        try:
            with step("Downloading data", f"{new_ticker} {resolved_interval} {rerun_start}->{rerun_end}") as s:
                data_df = download_data(new_ticker, rerun_start, rerun_end, interval=resolved_interval)
                s.succeed(f"{len(data_df):,} rows")
        except Exception as e:
            console.print(f"  [red]✗ Failed to download data: {e}[/]\n")
            continue

        # --- Fetch corporate data if strategy needs it ---
        if corporate_needs:
            from backtester.data.corporate import download_corporate_data, merge_corporate_data
            try:
                with step("Fetching corporate data", ", ".join(sorted(corporate_needs))) as s:
                    corporate = download_corporate_data(new_ticker, corporate_needs, rerun_start, rerun_end)
                    data_df = merge_corporate_data(data_df, corporate)
                    s.succeed(", ".join(sorted(corporate_needs)))
            except Exception as e:
                console.print(f"  [yellow]⚠ Corporate data unavailable: {e}[/]")

        # --- Execute strategy (NO LLM) ---
        with step("Running backtest", new_ticker) as s:
            exec_result = execute_strategy(
                strategy_code,
                data_df,
                param_overrides=param_overrides or None,
            )
            if exec_result.success:
                s.succeed(f"{exec_result.signal_count} signals in {exec_result.duration:.1f}s")
            else:
                s.fail(f"{exec_result.error_type}: {exec_result.error_message[:80]}")

        if not exec_result.success:
            console.print(f"  [red]✗ Strategy failed on {new_ticker}:[/] {exec_result.error_message[:150]}\n")
            continue

        # --- Validate ---
        with step("Validating output") as s:
            validation = validate_output(exec_result.output_df, data_df)
            if validation.valid:
                s.succeed(f"all {len(validation.test_results)} tests passed")
            else:
                s.fail(f"{len(validation.issues)} issue(s)")

        if not validation.valid:
            console.print(f"  [yellow]⚠ Validation issues: {'; '.join(validation.issues[:3])}[/]")

        # --- Build chart data (reuse existing indicator classification — NO LLM) ---
        chart_data_path: str | None = None
        if indicator_selection and exec_result.indicator_df is not None:
            chart_df = build_chart_dataframe(exec_result.indicator_df, indicator_selection)
            if not chart_df.empty:
                chart_data_path = f"./chart_data_{new_ticker}.csv"
                with step("Writing chart data CSV", chart_data_path):
                    save_chart_data_csv(chart_df, chart_data_path)

        # --- Save signals ---
        output_path = f"./signals_{new_ticker}.csv"
        with step("Writing signals CSV", output_path):
            save_signals_csv(exec_result.output_df, output_path)

        # --- Summary ---
        print_run_summary(
            exec_result.output_df, output_path, new_ticker,
            attempts=1, input_tokens=0, output_tokens=0,
            chart_data_path=chart_data_path,
        )
        if indicator_selection:
            from backtester.output.formatter import print_chart_indicators
            print_chart_indicators(indicator_selection)

        console.print()


def _handle_revision(
    analysis,
    original_strategy: str,
    ticker: str,
    start: str,
    end: str,
    user_interval: str,
    current_interval: str,
    orig_data_df,
    orig_has_corporate: bool,
    orig_corporate_needs: set,
    provider=None,
) -> tuple:
    """Show analysis results and run an interactive loop until user accepts a revision.

    Behaves like an intelligent agent: when user rejects, offers options to
    give feedback for a new alternative, write their own, or proceed with original.

    Returns (strategy_text, resolved_interval, data_df, has_corporate_data, corporate_needs).
    """
    import sys
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.text import Text
    from rich import box

    from backtester.data.corporate import detect_corporate_needs, download_corporate_data, merge_corporate_data
    from backtester.data.downloader import download_data
    from backtester.data.interval import clamp_date_range, detect_interval, INTERVAL_LABELS
    from backtester.ui import print_new_revision_panel, print_revision_menu

    console.print()

    if analysis.issues:
        issue_text = Text()
        for i, issue in enumerate(analysis.issues, 1):
            issue_text.append(f"  {i}. {issue}\n", style="yellow")
        console.print(Panel(
            issue_text,
            title="[bold yellow]Strategy analysis found potential issues[/]",
            border_style="yellow",
            box=box.ROUNDED,
            padding=(0, 1),
        ))

    console.print(Panel(
        Text(analysis.revised_strategy, style="white"),
        title="[bold cyan]Suggested revision[/]",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(0, 1),
    ))

    if analysis.explanation:
        console.print(f"  [dim]Explanation:[/] {analysis.explanation}")
        console.print()

    current_analysis = analysis
    revision_history: list[dict] = []

    while True:
        if sys.stdin.isatty():
            accepted = Confirm.ask("  Use revised strategy?", default=True, console=console)
        else:
            accepted = True

        if accepted:
            strategy_text = current_analysis.revised_strategy
            console.print("  [green]✓[/] Using revised strategy.")
            console.print()
            break

        # --- User rejected: show intelligent options ---
        print_revision_menu()

        if sys.stdin.isatty():
            choice = Prompt.ask("  Choose", choices=["1", "2", "3"], default="1", console=console)
        else:
            console.print("  [dim]Non-interactive mode — proceeding with original.[/]")
            return original_strategy, current_interval, orig_data_df, orig_has_corporate, orig_corporate_needs

        if choice == "1":
            # --- Get feedback and generate alternative ---
            feedback = console.input("  [bold]What would you prefer?[/] ").strip()
            if not feedback:
                console.print("  [dim]No feedback given — keeping current suggestion.[/]")
                continue

            revision_history.append({
                "revision": current_analysis.revised_strategy,
                "feedback": feedback,
            })

            if provider is None:
                console.print("  [dim]No LLM provider available — proceeding with original.[/]")
                return original_strategy, current_interval, orig_data_df, orig_has_corporate, orig_corporate_needs

            from backtester.engine.strategy_analyzer import reanalyze_strategy

            with step("Generating alternative", "incorporating your feedback") as s:
                new_analysis = reanalyze_strategy(
                    provider=provider,
                    strategy_text=original_strategy,
                    issues=analysis.issues,
                    previous_revision=current_analysis.revised_strategy,
                    user_feedback=feedback,
                    ticker=ticker,
                    interval=current_interval,
                    start=start,
                    end=end,
                    row_count=len(orig_data_df),
                    columns=list(orig_data_df.columns),
                    revision_history=revision_history,
                )
                if new_analysis.verdict == "revise" and new_analysis.revised_strategy:
                    s.succeed("new alternative ready")
                else:
                    s.fail("could not generate alternative")

            if new_analysis.verdict == "revise" and new_analysis.revised_strategy:
                current_analysis = new_analysis
                console.print()
                print_new_revision_panel(current_analysis)
                continue
            else:
                console.print("  [dim]Could not generate a better alternative. Proceeding with original strategy.[/]")
                return original_strategy, current_interval, orig_data_df, orig_has_corporate, orig_corporate_needs

        elif choice == "2":
            # --- User writes their own revision ---
            console.print("  [dim]Enter your revised strategy (press Enter twice to finish):[/]")
            lines = []
            while True:
                line = console.input("  [dim]>[/] ")
                if line == "" and lines and lines[-1] == "":
                    lines.pop()
                    break
                lines.append(line)
            custom = "\n".join(lines).strip()
            if custom:
                strategy_text = custom
                console.print("  [green]✓[/] Using your custom strategy.")
                console.print()
                break
            else:
                console.print("  [dim]No input — keeping current suggestion.[/]")
                continue

        else:  # choice == "3"
            console.print("  [dim]Proceeding with original strategy (issues noted).[/]")
            console.print()
            return original_strategy, current_interval, orig_data_df, orig_has_corporate, orig_corporate_needs

    # --- Apply the chosen strategy and re-pipeline if needed ---
    new_interval = detect_interval(strategy_text) if user_interval == "auto" else current_interval
    new_start, new_end, new_clamped = clamp_date_range(start, end, new_interval)
    needs_redownload = (new_interval != current_interval)

    if needs_redownload:
        label = INTERVAL_LABELS.get(new_interval, new_interval)
        console.print(f"  [dim]Interval changed to {new_interval} ({label})[/]")
        if new_clamped:
            console.print(f"  [yellow]Date range re-clamped to {new_start} -> {new_end}[/]")
        with step("Re-downloading data", f"{ticker} {new_interval}") as s:
            data_df = download_data(ticker, new_start, new_end, interval=new_interval)
            s.succeed(f"{len(data_df):,} rows")
    else:
        data_df = orig_data_df
        new_start, new_end = start, end

    new_corporate_needs = detect_corporate_needs(strategy_text)
    has_corporate_data = False

    if new_corporate_needs:
        if new_corporate_needs == orig_corporate_needs and not needs_redownload:
            data_df = orig_data_df
            has_corporate_data = orig_has_corporate
        else:
            if needs_redownload or data_df is not orig_data_df:
                pass
            else:
                corp_cols = [c for c in data_df.columns if c in (
                    "Dividend_Amount", "Is_Ex_Dividend", "Split_Ratio", "Is_Split_Day",
                    "Is_Earnings_Day", "Days_To_Earnings", "EPS_Estimate", "EPS_Actual",
                    "EPS_Surprise_Pct",
                )]
                if corp_cols:
                    data_df = data_df.drop(columns=corp_cols)

            with step("Fetching corporate data", ", ".join(sorted(new_corporate_needs))) as s:
                corporate = download_corporate_data(ticker, new_corporate_needs, new_start, new_end)
                data_df = merge_corporate_data(data_df, corporate)
                has_corporate_data = True
                s.succeed(", ".join(sorted(new_corporate_needs)))

    return strategy_text, new_interval, data_df, has_corporate_data, new_corporate_needs


def _repipeline_strategy(
    strategy_text: str,
    ticker: str,
    start: str,
    end: str,
    user_interval: str,
    current_interval: str,
    orig_data_df,
    orig_has_corporate: bool,
    orig_corporate_needs: set,
) -> tuple:
    """Re-run interval detection, date clamping, data download, and corporate fetch.

    Used after the user accepts a revised strategy (either from pre-flight
    analysis or from mid-loop intervention).

    Returns (strategy_text, resolved_interval, data_df, has_corporate_data, corporate_needs).
    """
    from backtester.data.corporate import detect_corporate_needs, download_corporate_data, merge_corporate_data
    from backtester.data.downloader import download_data
    from backtester.data.interval import clamp_date_range, detect_interval, INTERVAL_LABELS

    new_interval = detect_interval(strategy_text) if user_interval == "auto" else current_interval
    new_start, new_end, new_clamped = clamp_date_range(start, end, new_interval)
    needs_redownload = (new_interval != current_interval)

    if needs_redownload:
        label = INTERVAL_LABELS.get(new_interval, new_interval)
        console.print(f"  [dim]Interval changed to {new_interval} ({label})[/]")
        if new_clamped:
            console.print(f"  [yellow]Date range re-clamped to {new_start} -> {new_end}[/]")
        with step("Re-downloading data", f"{ticker} {new_interval}") as s:
            data_df = download_data(ticker, new_start, new_end, interval=new_interval)
            s.succeed(f"{len(data_df):,} rows")
    else:
        data_df = orig_data_df
        new_start, new_end = start, end

    new_corporate_needs = detect_corporate_needs(strategy_text)
    has_corporate_data = False

    if new_corporate_needs:
        if new_corporate_needs == orig_corporate_needs and not needs_redownload:
            data_df = orig_data_df
            has_corporate_data = orig_has_corporate
        else:
            if needs_redownload or data_df is not orig_data_df:
                pass
            else:
                corp_cols = [c for c in data_df.columns if c in (
                    "Dividend_Amount", "Is_Ex_Dividend", "Split_Ratio", "Is_Split_Day",
                    "Is_Earnings_Day", "Days_To_Earnings", "EPS_Estimate", "EPS_Actual",
                    "EPS_Surprise_Pct",
                )]
                if corp_cols:
                    data_df = data_df.drop(columns=corp_cols)

            with step("Fetching corporate data", ", ".join(sorted(new_corporate_needs))) as s:
                corporate = download_corporate_data(ticker, new_corporate_needs, new_start, new_end)
                data_df = merge_corporate_data(data_df, corporate)
                has_corporate_data = True
                s.succeed(", ".join(sorted(new_corporate_needs)))

    return strategy_text, new_interval, data_df, has_corporate_data, new_corporate_needs


def _resolve_strategy(strategy: str | None, strategy_file: str | None) -> str:
    if strategy:
        return strategy
    if strategy_file:
        path = Path(strategy_file)
        if not path.exists():
            print_error_box("Error", f"Strategy file not found: {strategy_file}")
            raise typer.Exit(1)
        return path.read_text(encoding="utf-8").strip()
    print_error_box("Error", "Provide --strategy or --strategy-file")
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
