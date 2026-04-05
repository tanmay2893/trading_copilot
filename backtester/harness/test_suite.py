from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class TestResult:
    name: str
    passed: bool
    message: str


def run_tests(signals_df: pd.DataFrame, data_df: pd.DataFrame) -> list[TestResult]:
    results: list[TestResult] = []
    date_col = "date" if "date" in data_df.columns else "Date"
    data_dates = pd.to_datetime(data_df[date_col])
    data_min = data_dates.min()
    data_max = data_dates.max()

    required = {"Date", "Signal", "Price"}
    if set(signals_df.columns) >= required:
        results.append(TestResult("test_schema", True, "Has Date, Signal, Price columns"))
    else:
        missing = required - set(signals_df.columns)
        results.append(
            TestResult("test_schema", False, f"Missing columns: {missing}")
        )

    valid_signals = set(signals_df["Signal"].dropna().unique()) <= {"BUY", "SELL"}
    if valid_signals:
        results.append(
            TestResult("test_signal_values", True, "Signal values are BUY or SELL")
        )
    else:
        bad = set(signals_df["Signal"].dropna().unique()) - {"BUY", "SELL"}
        results.append(
            TestResult(
                "test_signal_values",
                False,
                f"Invalid signal values: {bad}",
            )
        )

    prices = pd.to_numeric(signals_df["Price"], errors="coerce")
    has_nan_inf = prices.isna().any() or (prices.dtype.kind in "fc" and np.isinf(prices.astype(float)).any())
    if not has_nan_inf:
        results.append(
            TestResult("test_no_nan_prices", True, "No NaN/inf in Price column")
        )
    else:
        results.append(
            TestResult(
                "test_no_nan_prices",
                False,
                "Price column contains NaN or inf",
            )
        )

    if len(signals_df) >= 1:
        results.append(TestResult("test_has_signals", True, "At least 1 signal exists"))
    else:
        results.append(
            TestResult("test_has_signals", False, "No signals in output")
        )

    buy_count = (signals_df["Signal"] == "BUY").sum()
    sell_count = (signals_df["Signal"] == "SELL").sum()
    if buy_count >= 1 and sell_count >= 1:
        results.append(
            TestResult("test_has_both_types", True, "At least 1 BUY and 1 SELL")
        )
    else:
        results.append(
            TestResult(
                "test_has_both_types",
                False,
                f"Need both BUY and SELL (buy={buy_count}, sell={sell_count})",
            )
        )

    signal_dates = pd.to_datetime(signals_df["Date"])
    in_range = (signal_dates >= data_min) & (signal_dates <= data_max)
    if in_range.all():
        results.append(
            TestResult(
                "test_dates_in_range",
                True,
                "All signal dates fall within data date range",
            )
        )
    else:
        bad_dates = signal_dates[~in_range].tolist()
        results.append(
            TestResult(
                "test_dates_in_range",
                False,
                f"Signal dates outside range: {bad_dates[:5]}...",
            )
        )

    n_signals = len(signals_df)
    n_data = len(data_df)
    pct = n_signals / n_data if n_data > 0 else 0
    if 1 <= n_signals <= max(n_data, 1):
        results.append(
            TestResult(
                "test_reasonable_count",
                True,
                f"Signal count ({n_signals}) between 1 and data rows ({n_data})",
            )
        )
    else:
        results.append(
            TestResult(
                "test_reasonable_count",
                False,
                f"Signal count {n_signals} not in [1, {n_data}]",
            )
        )

    chronological = signal_dates.is_monotonic_increasing
    if chronological:
        results.append(
            TestResult("test_chronological", True, "Signals are in date order")
        )
    else:
        results.append(
            TestResult(
                "test_chronological",
                False,
                "Signals are not in chronological order",
            )
        )

    return results
