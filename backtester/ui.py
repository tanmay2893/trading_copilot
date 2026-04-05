"""Shared rich UI components -- live status panels, spinners, step logging.

Aims for clear, continuous feedback while long jobs run.
"""

from __future__ import annotations

import io
import sys
import time
from contextlib import contextmanager
from typing import Generator

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text
from rich.table import Table
from rich.syntax import Syntax
from rich import box

console = Console(force_terminal=True)

SPINNER_STYLE = "dots"


@contextmanager
def step(description: str, detail: str = "") -> Generator[StepContext, None, None]:
    """Context manager that shows a spinner while running, then ✓ or ✗."""
    ctx = StepContext(description, detail)
    ctx.start()
    try:
        yield ctx
        ctx.succeed()
    except Exception as e:
        ctx.fail(str(e))
        raise


class StepContext:
    def __init__(self, description: str, detail: str = ""):
        self.description = description
        self.detail = detail
        self._live: Live | None = None
        self._start_time = 0.0
        self._sub_status = ""
        self._finished = False

    def start(self):
        self._start_time = time.perf_counter()
        spinner = Spinner(SPINNER_STYLE, text=self._render_text(), style="cyan")
        self._live = Live(spinner, console=console, refresh_per_second=12, transient=True)
        self._live.start()

    def update(self, sub_status: str):
        """Update the running status text (e.g. 'attempt 2/10')."""
        self._sub_status = sub_status
        if self._live:
            spinner = Spinner(SPINNER_STYLE, text=self._render_text(), style="cyan")
            self._live.update(spinner)

    def _render_text(self) -> Text:
        txt = Text()
        txt.append(self.description, style="bold white")
        if self._sub_status:
            txt.append(f"  {self._sub_status}", style="dim")
        elif self.detail:
            txt.append(f"  {self.detail}", style="dim")
        return txt

    def _elapsed(self) -> str:
        elapsed = time.perf_counter() - self._start_time
        if elapsed < 1:
            return f"{elapsed * 1000:.0f}ms"
        return f"{elapsed:.1f}s"

    def succeed(self, message: str = ""):
        if self._finished:
            return
        self._finished = True
        if self._live:
            self._live.stop()
        txt = Text()
        txt.append("  ✓ ", style="bold green")
        txt.append(self.description, style="white")
        if message:
            txt.append(f"  {message}", style="dim")
        txt.append(f"  ({self._elapsed()})", style="dim")
        console.print(txt)

    def fail(self, message: str = ""):
        if self._finished:
            return
        self._finished = True
        if self._live:
            self._live.stop()
        txt = Text()
        txt.append("  ✗ ", style="bold red")
        txt.append(self.description, style="white")
        if message:
            txt.append(f"  {message}", style="dim red")
        txt.append(f"  ({self._elapsed()})", style="dim")
        console.print(txt)


def print_header(title: str, subtitle: str = ""):
    console.print()
    console.print(f"  [bold cyan]{title}[/]")
    if subtitle:
        console.print(f"  [dim]{subtitle}[/]")
    console.print()


def print_code(code: str, title: str = "Generated Strategy"):
    syntax = Syntax(code, "python", theme="monokai", line_numbers=True, word_wrap=True)
    panel = Panel(syntax, title=f"[bold]{title}[/]", border_style="dim", box=box.ROUNDED, padding=(0, 1))
    console.print(panel)


def print_error_box(title: str, message: str):
    panel = Panel(
        Text(message, style="red"),
        title=f"[bold red]{title}[/]",
        border_style="red",
        box=box.ROUNDED,
        padding=(0, 1),
    )
    console.print(panel)


def print_iteration_status(attempt: int, max_attempts: int, error_type: str, message: str):
    txt = Text()
    txt.append(f"  ↻ ", style="yellow")
    txt.append(f"Attempt {attempt}/{max_attempts}", style="bold yellow")
    txt.append(f"  [{error_type}] ", style="dim yellow")
    txt.append(message[:120], style="dim")
    console.print(txt)


def print_summary_table(stats: dict):
    table = Table(box=box.SIMPLE_HEAVY, show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    for k, v in stats.items():
        table.add_row(k, str(v))
    console.print()
    console.print(Panel(table, title="[bold]Results[/]", border_style="green", box=box.ROUNDED))


# --- Interactive refine mode UI helpers ---

def print_refine_header(session):
    """Display session info when entering refine mode."""
    from backtester.engine.session import RefineSession
    console.print()
    console.print(f"  [bold cyan]Strategy Refiner[/]  [dim](Session: {session.session_id})[/]")
    console.print(f"  [dim]Ticker:[/] {session.ticker}  [dim]|  Interval:[/] {session.interval}")
    console.print(f"  [dim]Strategy:[/] \"{session.strategy_description[:120]}{'...' if len(session.strategy_description) > 120 else ''}\"")
    if session.conversation:
        console.print(f"  [dim]Turns so far:[/] {len(session.conversation)}")
    console.print()
    console.print("  [dim]Type 'help' for commands, 'exit' to quit.[/]")
    console.print()


def print_code_diff(old_code: str, new_code: str):
    """Show a colorized unified diff between two code versions."""
    import difflib
    old_lines = old_code.splitlines(keepends=True)
    new_lines = new_code.splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, fromfile="before", tofile="after", lineterm=""))

    if not diff:
        console.print("  [dim]No changes detected.[/]")
        return

    txt = Text()
    for line in diff:
        line_clean = line.rstrip("\n")
        if line_clean.startswith("+++") or line_clean.startswith("---"):
            txt.append(line_clean + "\n", style="bold")
        elif line_clean.startswith("@@"):
            txt.append(line_clean + "\n", style="cyan")
        elif line_clean.startswith("+"):
            txt.append(line_clean + "\n", style="green")
        elif line_clean.startswith("-"):
            txt.append(line_clean + "\n", style="red")
        else:
            txt.append(line_clean + "\n", style="dim")

    panel = Panel(txt, title="[bold]Diff[/]", border_style="dim", box=box.ROUNDED, padding=(0, 1))
    console.print(panel)


def print_turn_summary(turn_number: int, summary: str, signals_df=None, prev_signals_df=None):
    """Compact summary of a refinement turn result."""
    console.print()
    console.print(f"  [bold green]✓ Changes applied[/]  [dim](turn {turn_number})[/]")
    for line in summary.strip().splitlines():
        console.print(f"  {line.strip()}")

    if signals_df is not None:
        buy_count = int((signals_df["Signal"] == "BUY").sum())
        sell_count = int((signals_df["Signal"] == "SELL").sum())
        sig_text = f"  [dim]Signals:[/] {buy_count} BUY, {sell_count} SELL"
        if prev_signals_df is not None:
            prev_buy = int((prev_signals_df["Signal"] == "BUY").sum())
            prev_sell = int((prev_signals_df["Signal"] == "SELL").sum())
            sig_text += f"  [dim](was {prev_buy}/{prev_sell})[/]"
        console.print(sig_text)
    console.print()


def print_refine_failure(error_message: str, attempts: int):
    """Report a failed refinement attempt."""
    console.print()
    console.print(f"  [bold red]✗ Refinement failed[/] after {attempts} attempt(s)")
    console.print(f"  [dim red]{error_message[:200]}[/]")
    console.print(f"  [dim]Previous version preserved. Try rephrasing your request.[/]")
    console.print()


def print_conversation_history(session):
    """Formatted list of all conversation turns."""
    if not session.conversation:
        console.print("  [dim]No conversation history yet.[/]")
        return

    console.print()
    for i, turn in enumerate(session.conversation, 1):
        console.print(f"  [bold cyan]Turn {i}[/]  [dim]{turn.timestamp[:19]}[/]")
        console.print(f"    [dim]Request:[/] {turn.request}")
        console.print(f"    [dim]Summary:[/] {turn.summary}")
        console.print(f"    [dim]Attempts:[/] {turn.attempt_count}")
        console.print()


def print_signal_summary(signals_df):
    """Show a compact signal summary for the current strategy."""
    if signals_df is None or signals_df.empty:
        console.print("  [dim]No signals generated yet.[/]")
        return

    buy_count = int((signals_df["Signal"] == "BUY").sum())
    sell_count = int((signals_df["Signal"] == "SELL").sum())
    total = len(signals_df)
    console.print(f"  [dim]Total signals:[/] {total}  ({buy_count} BUY, {sell_count} SELL)")
    console.print(f"  [dim]Date range:[/] {signals_df['Date'].iloc[0]} -> {signals_df['Date'].iloc[-1]}")


def print_intervention_panel(diagnosis, max_iterations: int = 12) -> None:
    """Display diagnosis and proposed relaxation when the iteration loop is stuck."""
    console.print()

    if diagnosis.diagnosis:
        console.print(Panel(
            Text(diagnosis.diagnosis, style="yellow"),
            title="[bold yellow]Strategy Diagnosis[/]",
            border_style="yellow",
            box=box.ROUNDED,
            padding=(0, 1),
        ))

    if diagnosis.revised_strategy:
        console.print(Panel(
            Text(diagnosis.revised_strategy, style="white"),
            title="[bold cyan]Suggested Relaxation[/]",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(0, 1),
        ))

    if diagnosis.explanation:
        console.print(f"  [dim]Explanation:[/] {diagnosis.explanation}")
        console.print()

    console.print("  [bold]What would you like to do?[/]")
    console.print("    [cyan][1][/] Accept relaxed strategy")
    console.print("    [cyan][2][/] Enter your own revision")
    console.print(f"    [cyan][3][/] Keep trying with original ({max_iterations} more attempts)")
    console.print("    [cyan][4][/] Abort")


def print_revision_menu() -> None:
    """Display options when user rejects a suggested strategy revision."""
    console.print()
    console.print("  [bold]What would you like to do?[/]")
    console.print("    [cyan][1][/] Tell me what you'd prefer [dim](AI generates a new alternative)[/]")
    console.print("    [cyan][2][/] Write your own revision")
    console.print("    [cyan][3][/] Proceed with original strategy [dim](ignore issues)[/]")
    console.print()


def print_new_revision_panel(analysis) -> None:
    """Display a new alternative revision after user feedback."""
    if analysis.revised_strategy:
        console.print(Panel(
            Text(analysis.revised_strategy, style="white"),
            title="[bold cyan]Alternative revision[/]",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(0, 1),
        ))

    if analysis.explanation:
        console.print(f"  [dim]Explanation:[/] {analysis.explanation}")
        console.print()


def print_refine_help():
    """Show available commands in refine mode."""
    console.print()
    console.print("  [bold]Available commands:[/]")
    console.print("    [cyan]exit[/], [cyan]quit[/]      Save session and exit")
    console.print("    [cyan]undo[/]            Revert to previous code version")
    console.print("    [cyan]history[/]         Show conversation history")
    console.print("    [cyan]code[/]            Show current strategy code")
    console.print("    [cyan]signals[/]         Show current signal summary")
    console.print("    [cyan]help[/]            Show this help message")
    console.print("    [dim]<anything else>[/]  Treated as a change request")
    console.print()


def print_stock_search_results(matches_df) -> None:
    """Display a numbered table of matching stocks from search."""
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold", padding=(0, 1))
    table.add_column("#", style="cyan", width=4, justify="right")
    table.add_column("Symbol", style="green bold", min_width=6)
    table.add_column("Market", style="dim", width=8)
    table.add_column("Name", style="white")

    for i, (_, row) in enumerate(matches_df.iterrows(), 1):
        country = row.get("Country", "US")
        market = "(US)" if country == "US" else "(INDIA)"
        table.add_row(str(i), row["Symbol"], market, row["Name"])

    console.print(table)


def print_rerun_header(ticker: str, name: str, country: str = "US") -> None:
    """Header when re-running the same strategy on a different stock."""
    market = "(US)" if country == "US" else "(INDIA)"
    console.print()
    console.print(f"  [bold cyan]Re-running strategy on {ticker}[/]  [dim]{market} {name}[/]")
    console.print()
