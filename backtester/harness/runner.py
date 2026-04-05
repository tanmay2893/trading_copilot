import importlib.util
import inspect
import json
import os
import sys
import traceback
from pathlib import Path

import ast
import pandas as pd

try:
    from backtester.harness.base_strategy import BaseStrategy
except ImportError:
    try:
        from .base_strategy import BaseStrategy
    except ImportError:
        from base_strategy import BaseStrategy


def _parse_override_value(raw_value: str | float | int | bool) -> object:
    """Convert override string to Python literal when possible."""
    if not isinstance(raw_value, str):
        return raw_value
    try:
        return ast.literal_eval(raw_value)
    except Exception:
        return raw_value


def _get_init_param_names(strategy_cls) -> list[str] | None:
    """Return names of __init__ parameters beyond (self, df), or None if **kwargs is used (any override key allowed)."""
    try:
        sig = inspect.signature(strategy_cls.__init__)
    except Exception:
        return []
    out = []
    for name, param in sig.parameters.items():
        if name in ("self", "df"):
            continue
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return None  # **kwargs: pass all overrides as kwargs
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
            out.append(name)
    return out


def _apply_param_overrides(strategy_cls, overrides: dict | None) -> None:
    """Apply class-level parameter overrides before instantiation (fallback when Strategy has no __init__ params)."""
    if not overrides:
        return
    for name, raw_value in overrides.items():
        if not hasattr(strategy_cls, name):
            continue
        value = _parse_override_value(raw_value)
        setattr(strategy_cls, name, value)


def run_strategy_from_file(
    strategy_path: str, data_csv_path: str, output_csv_path: str
) -> None:
    try:
        df = pd.read_csv(data_csv_path)
        original_columns = list(df.columns)
        date_col = "date" if "date" in df.columns else "Date"
        if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
            df[date_col] = pd.to_datetime(df[date_col], utc=True)
        if hasattr(df[date_col].dt, "tz") and df[date_col].dt.tz is not None:
            df[date_col] = df[date_col].dt.tz_localize(None)

        spec = importlib.util.spec_from_file_location("strategy_module", strategy_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        strategy_cls = None
        for name in dir(module):
            obj = getattr(module, name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseStrategy)
                and obj is not BaseStrategy
            ):
                strategy_cls = obj
                break

        if strategy_cls is None:
            raise ValueError("No class subclasses BaseStrategy found in strategy file")

        # Optional runtime parameter overrides from env.
        overrides_raw = os.environ.get("BACKTESTER_PARAM_OVERRIDES")
        overrides = None
        if overrides_raw:
            try:
                overrides = json.loads(overrides_raw)
            except Exception:
                overrides = None

        init_params = _get_init_param_names(strategy_cls)
        if overrides and init_params is not None and len(init_params) > 0:
            # Strategy has __init__(self, df, *, param1=..., param2=...): pass overrides as kwargs.
            allowed = set(init_params)
            kwargs = {
                k: _parse_override_value(v)
                for k, v in overrides.items()
                if k in allowed
            }
            strategy = strategy_cls(df, **kwargs)
        elif overrides and init_params is None:
            # Strategy has **kwargs: pass all overrides as kwargs.
            kwargs = {k: _parse_override_value(v) for k, v in overrides.items()}
            strategy = strategy_cls(df, **kwargs)
        elif overrides and len(init_params) == 0:
            # Strategy has no __init__ params beyond (self, df): fall back to class-level overrides.
            _apply_param_overrides(strategy_cls, overrides)
            strategy = strategy_cls(df)
        else:
            strategy = strategy_cls(df)
        result = strategy.run()

        result.to_csv(output_csv_path, index=False)

        indicator_columns = [
            c for c in strategy.df.columns
            if c not in original_columns and pd.api.types.is_numeric_dtype(strategy.df[c])
        ]
        chart_data_path = str(Path(output_csv_path).parent / "chart_data.csv")
        ohlcv_cols = [date_col, "Open", "High", "Low", "Close", "Volume"]
        keep_cols = ohlcv_cols + indicator_columns
        keep_cols = [c for c in keep_cols if c in strategy.df.columns]
        strategy.df[keep_cols].to_csv(chart_data_path, index=False)

        buy_count = int((result["Signal"] == "BUY").sum())
        sell_count = int((result["Signal"] == "SELL").sum())
        summary = {
            "status": "success",
            "signal_count": len(result),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "indicator_columns": indicator_columns,
        }
        print(json.dumps(summary))

    except Exception as e:
        err_summary = {
            "status": "error",
            "error_type": type(e).__name__,
            "message": str(e),
            "traceback": traceback.format_exc(),
        }
        print(json.dumps(err_summary))
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": "UsageError",
                    "message": "Usage: python runner.py <strategy_path> <data_csv_path> <output_csv_path>",
                    "traceback": "",
                }
            )
        )
        sys.exit(1)
    run_strategy_from_file(sys.argv[1], sys.argv[2], sys.argv[3])
