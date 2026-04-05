"""Sandboxed subprocess execution of generated strategy code."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict

import pandas as pd

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)


@dataclass
class ExecutionResult:
    success: bool
    stdout: str
    stderr: str
    output_df: Optional[pd.DataFrame]
    exit_code: int
    duration: float
    error_type: str = ""
    error_message: str = ""
    traceback_str: str = ""
    signal_count: int = 0
    buy_count: int = 0
    sell_count: int = 0
    indicator_df: Optional[pd.DataFrame] = None
    indicator_columns: list = field(default_factory=list)


def execute_strategy(
    strategy_code: str,
    data_df: pd.DataFrame,
    timeout: int = 60,
    param_overrides: Optional[Dict[str, str]] = None,
) -> ExecutionResult:
    """Write strategy to temp file, run via runner.py in a subprocess."""
    runner_path = Path(__file__).resolve().parent.parent / "harness" / "runner.py"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        strategy_path = tmpdir_path / "strategy.py"
        data_path = tmpdir_path / "data.csv"
        output_path = tmpdir_path / "signals.csv"

        strategy_path.write_text(strategy_code, encoding="utf-8")
        data_df.to_csv(data_path, index=False)

        env = os.environ.copy()
        env["PYTHONPATH"] = PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
        if param_overrides:
            try:
                env["BACKTESTER_PARAM_OVERRIDES"] = json.dumps(param_overrides)
            except Exception:
                env.pop("BACKTESTER_PARAM_OVERRIDES", None)

        start = time.perf_counter()
        try:
            result = subprocess.run(
                [sys.executable, str(runner_path), str(strategy_path), str(data_path), str(output_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmpdir,
                env=env,
            )
        except subprocess.TimeoutExpired:
            duration = time.perf_counter() - start
            return ExecutionResult(
                success=False,
                stdout="",
                stderr="",
                output_df=None,
                exit_code=-1,
                duration=duration,
                error_type="TIMEOUT",
                error_message=f"Strategy execution timed out after {timeout}s",
                traceback_str="",
            )

        duration = time.perf_counter() - start
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        parsed = _parse_runner_output(stdout)
        if parsed and parsed.get("status") == "success":
            output_df = None
            if output_path.exists():
                output_df = pd.read_csv(output_path)
            indicator_df = None
            chart_data_path = tmpdir_path / "chart_data.csv"
            if chart_data_path.exists():
                indicator_df = pd.read_csv(chart_data_path)
            return ExecutionResult(
                success=True,
                stdout=stdout,
                stderr=stderr,
                output_df=output_df,
                exit_code=result.returncode,
                duration=duration,
                signal_count=parsed.get("signal_count", 0),
                buy_count=parsed.get("buy_count", 0),
                sell_count=parsed.get("sell_count", 0),
                indicator_df=indicator_df,
                indicator_columns=parsed.get("indicator_columns", []),
            )

        error_type = ""
        error_message = ""
        traceback_str = ""
        if parsed and parsed.get("status") == "error":
            error_type = parsed.get("error_type", "UNKNOWN")
            error_message = parsed.get("message", "")
            traceback_str = parsed.get("traceback", "")
        elif stderr:
            error_type, error_message = _classify_stderr(stderr)
            traceback_str = stderr

        return ExecutionResult(
            success=False,
            stdout=stdout,
            stderr=stderr,
            output_df=None,
            exit_code=result.returncode,
            duration=duration,
            error_type=error_type,
            error_message=error_message,
            traceback_str=traceback_str,
        )


def _parse_runner_output(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def _classify_stderr(stderr: str) -> tuple[str, str]:
    lower = stderr.lower()
    if "syntaxerror" in lower:
        return "SYNTAX_ERROR", _last_line(stderr)
    if "importerror" in lower or "modulenotfounderror" in lower:
        return "IMPORT_ERROR", _last_line(stderr)
    if "keyerror" in lower or "indexerror" in lower:
        return "DATA_ERROR", _last_line(stderr)
    if "typeerror" in lower or "valueerror" in lower or "zerodivisionerror" in lower:
        return "RUNTIME_ERROR", _last_line(stderr)
    return "UNKNOWN", _last_line(stderr)


def _last_line(text: str) -> str:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    return lines[-1] if lines else ""
