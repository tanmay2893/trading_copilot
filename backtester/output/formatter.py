"""CSV signal formatter + terminal summary."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from backtester.ui import console, print_summary_table
from rich.table import Table
from rich import box

if TYPE_CHECKING:
    from backtester.engine.indicator_selector import IndicatorSelection
    from backtester.engine.parameter_extractor import ParameterLine


def save_signals_csv(signals_df: pd.DataFrame, output_path: str) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    signals_df.to_csv(path, index=False)
    return path


def save_chart_data_csv(chart_df: pd.DataFrame, output_path: str) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    chart_df.to_csv(path, index=False)
    return path


def print_run_summary(
    signals_df: pd.DataFrame,
    output_path: str,
    ticker: str,
    attempts: int,
    input_tokens: int,
    output_tokens: int,
    chart_data_path: str | None = None,
):
    buy_count = int((signals_df["Signal"] == "BUY").sum())
    sell_count = int((signals_df["Signal"] == "SELL").sum())
    total = len(signals_df)
    first_date = signals_df["Date"].iloc[0] if total > 0 else "N/A"
    last_date = signals_df["Date"].iloc[-1] if total > 0 else "N/A"

    summary = {
        "Ticker": ticker,
        "Total Signals": str(total),
        "Buy Signals": str(buy_count),
        "Sell Signals": str(sell_count),
        "First Signal": str(first_date),
        "Last Signal": str(last_date),
        "Attempts": str(attempts),
        "Tokens (in/out)": f"{input_tokens:,} / {output_tokens:,}",
        "Signals File": output_path,
    }
    if chart_data_path:
        summary["Chart Data File"] = chart_data_path

    print_summary_table(summary)


def print_chart_indicators(selection: "IndicatorSelection") -> None:
    """Display the classified chart indicators so the user knows what's in the chart data."""
    if not selection.overlay and not selection.oscillator:
        console.print("\n  [dim]No chart indicators selected.[/]\n")
        return

    table = Table(
        box=box.ROUNDED,
        title="Chart Indicators (included in chart data output)",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Indicator", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Visualization", style="dim")

    for col in selection.overlay:
        table.add_row(col, "overlay", "Overlaid on price chart (same scale)")
    for col in selection.oscillator:
        table.add_row(col, "oscillator", "Sub-panel below price chart")

    console.print()
    console.print(table)

    if selection.internal:
        console.print(f"  [dim]Excluded (internal): {', '.join(selection.internal)}[/]")
    console.print()


def print_parameters_used(parameters: list["ParameterLine"], run_dir: Path | None = None) -> None:
    """Display strategy parameters so the user can see and change them (edit the saved strategy file)."""
    if not parameters:
        console.print("\n  [dim]No parameters extracted. Edit the strategy file to add or change constants.[/]\n")
        return
    table = Table(box=box.ROUNDED, title="Parameters used (edit strategy file to change)", show_header=True, header_style="bold")
    table.add_column("Parameter", style="cyan")
    table.add_column("Value", style="green")
    table.add_column("Description", style="dim")
    for p in parameters:
        table.add_row(p.name, p.value, p.description or "-")
    console.print()
    console.print(table)
    if run_dir:
        console.print(f"  [dim]Strategy file: {run_dir / 'strategy.py'}[/]")
    console.print("  [dim]To change: edit the constants at the top of the strategy file and re-run or use backtester fix.[/]\n")
