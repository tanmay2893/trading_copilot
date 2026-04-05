"""Corporate event detection, fetching, and merging into OHLCV data."""

from __future__ import annotations

import re
import time

import numpy as np
import pandas as pd
import yfinance as yf

from backtester.config import CACHE_DIR

CACHE_MAX_AGE_SEC = 24 * 60 * 60

CORPORATE_COLUMNS = {
    "dividends": ["Dividend_Amount", "Is_Ex_Dividend"],
    "splits": ["Split_Ratio", "Is_Split_Day"],
    "earnings": [
        "Is_Earnings_Day",
        "Days_To_Earnings",
        "EPS_Estimate",
        "EPS_Actual",
        "EPS_Surprise_Pct",
    ],
}

ALL_CORPORATE_COLUMNS = [col for cols in CORPORATE_COLUMNS.values() for col in cols]

_KEYWORD_MAP: dict[str, list[str]] = {
    "earnings": [
        r"earnings",
        r"eps\b",
        r"quarterly\s+report",
        r"earnings\s+surprise",
        r"beat\s+estimate",
        r"miss\s+estimate",
        r"post[\-\s]?earnings",
        r"pre[\-\s]?earnings",
        r"earnings\s+announcement",
        r"earnings\s+date",
        r"earnings\s+release",
        r"earnings\s+call",
        r"report\s+earnings",
    ],
    "dividends": [
        r"dividend",
        r"ex[\-\s]?dividend",
        r"ex[\-\s]?date",
        r"payout\s+ratio",
        r"dividend\s+yield",
        r"dividend\s+cut",
        r"dividend\s+hike",
        r"dividend\s+increase",
        r"dividend\s+decrease",
    ],
    "splits": [
        r"\bsplit\b",  # "split", "split is announced", "after split", etc.
        r"stock\s+split",
        r"reverse\s+split",
        r"share\s+split",
        r"split\s+ratio",
        r"split\s+adjusted",
    ],
}


def detect_corporate_needs(strategy_text: str) -> set[str]:
    """Scan strategy NL text and return which corporate event types are referenced."""
    text_lower = strategy_text.lower()
    needs: set[str] = set()
    for event_type, patterns in _KEYWORD_MAP.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                needs.add(event_type)
                break
    return needs


def has_corporate_columns(df: pd.DataFrame) -> bool:
    """Check whether a DataFrame already contains any corporate event columns."""
    return any(col in df.columns for col in ALL_CORPORATE_COLUMNS)


def download_corporate_data(
    ticker: str,
    needs: set[str],
    start: str,
    end: str,
    country: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Fetch corporate event data from yfinance for the requested event types."""
    from backtester.data.symbol_resolve import get_country, resolve_yfinance_symbol_with_fallback

    if country is None:
        country = get_country(ticker)
    yf_ticker = resolve_yfinance_symbol_with_fallback(ticker, country)
    t = yf.Ticker(yf_ticker)
    result: dict[str, pd.DataFrame] = {}

    if "dividends" in needs:
        result["dividends"] = _fetch_dividends(t, yf_ticker, start, end)

    if "splits" in needs:
        result["splits"] = _fetch_splits(t, yf_ticker, start, end)

    if "earnings" in needs:
        result["earnings"] = _fetch_earnings(t, yf_ticker, start, end)

    return result


def merge_corporate_data(
    ohlcv_df: pd.DataFrame, corporate: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    """Left-merge corporate event DataFrames onto the OHLCV data by date."""
    df = ohlcv_df.copy()
    date_col = df["Date"]

    if hasattr(date_col.dt, "tz") and date_col.dt.tz is not None:
        date_col = date_col.dt.tz_localize(None)

    merge_dates = pd.to_datetime(date_col).dt.normalize()
    df["_merge_date"] = merge_dates

    if "dividends" in corporate:
        div = corporate["dividends"]
        if not div.empty:
            div = div.copy()
            div["_merge_date"] = pd.to_datetime(div["Date"]).dt.normalize()
            div = div.drop(columns=["Date"])
            df = df.merge(div, on="_merge_date", how="left")
        df["Dividend_Amount"] = df.get("Dividend_Amount", pd.Series(dtype="float64")).fillna(0.0)
        df["Is_Ex_Dividend"] = df["Dividend_Amount"] > 0

    if "splits" in corporate:
        spl = corporate["splits"]
        if not spl.empty:
            spl = spl.copy()
            spl["_merge_date"] = pd.to_datetime(spl["Date"]).dt.normalize()
            spl = spl.drop(columns=["Date"])
            df = df.merge(spl, on="_merge_date", how="left")
        df["Split_Ratio"] = df.get("Split_Ratio", pd.Series(dtype="float64")).fillna(1.0)
        df["Is_Split_Day"] = df["Split_Ratio"] != 1.0

    if "earnings" in corporate:
        earn = corporate["earnings"]
        if not earn.empty:
            earn = earn.copy()
            earn["_merge_date"] = pd.to_datetime(earn["Date"]).dt.normalize()
            earn = earn.drop(columns=["Date"])
            df = df.merge(earn, on="_merge_date", how="left")

        df["Is_Earnings_Day"] = df.get("Is_Earnings_Day", pd.Series(dtype="bool")).fillna(False)

        if not earn.empty:
            earnings_dates = sorted(earn["_merge_date"].dropna().unique())
            df["Days_To_Earnings"] = _compute_days_to_earnings(
                df["_merge_date"], earnings_dates
            )
        else:
            df["Days_To_Earnings"] = np.nan

        for col in ("EPS_Estimate", "EPS_Actual", "EPS_Surprise_Pct"):
            if col not in df.columns:
                df[col] = np.nan

    df = df.drop(columns=["_merge_date"])
    return df


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cache_path(ticker: str, event_type: str, start: str, end: str) -> "pathlib.Path":
    import pathlib
    return CACHE_DIR / f"{ticker}_corporate_{event_type}_{start}_{end}.parquet"


def _read_cache(path) -> pd.DataFrame | None:
    if path.exists() and (time.time() - path.stat().st_mtime) < CACHE_MAX_AGE_SEC:
        return pd.read_parquet(path)
    return None


def _write_cache(df: pd.DataFrame, path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _fetch_dividends(t: yf.Ticker, ticker: str, start: str, end: str) -> pd.DataFrame:
    cache = _cache_path(ticker, "dividends", start, end)
    cached = _read_cache(cache)
    if cached is not None:
        return cached

    try:
        divs = t.dividends
    except Exception:
        divs = pd.Series(dtype="float64")

    if divs is None or (isinstance(divs, pd.Series) and divs.empty):
        empty = pd.DataFrame(columns=["Date", "Dividend_Amount"])
        _write_cache(empty, cache)
        return empty

    df = divs.reset_index()
    df.columns = ["Date", "Dividend_Amount"]
    df["Date"] = pd.to_datetime(df["Date"])
    if hasattr(df["Date"].dt, "tz") and df["Date"].dt.tz is not None:
        df["Date"] = df["Date"].dt.tz_localize(None)

    mask = (df["Date"] >= pd.Timestamp(start)) & (df["Date"] <= pd.Timestamp(end))
    df = df.loc[mask].reset_index(drop=True)

    _write_cache(df, cache)
    return df


def _fetch_splits(t: yf.Ticker, ticker: str, start: str, end: str) -> pd.DataFrame:
    cache = _cache_path(ticker, "splits", start, end)
    cached = _read_cache(cache)
    if cached is not None:
        return cached

    try:
        splits = t.splits
    except Exception:
        splits = pd.Series(dtype="float64")

    if splits is None or (isinstance(splits, pd.Series) and splits.empty):
        empty = pd.DataFrame(columns=["Date", "Split_Ratio"])
        _write_cache(empty, cache)
        return empty

    df = splits.reset_index()
    df.columns = ["Date", "Split_Ratio"]
    df["Date"] = pd.to_datetime(df["Date"])
    if hasattr(df["Date"].dt, "tz") and df["Date"].dt.tz is not None:
        df["Date"] = df["Date"].dt.tz_localize(None)

    mask = (df["Date"] >= pd.Timestamp(start)) & (df["Date"] <= pd.Timestamp(end))
    df = df.loc[mask].reset_index(drop=True)

    _write_cache(df, cache)
    return df


def _fetch_earnings(t: yf.Ticker, ticker: str, start: str, end: str) -> pd.DataFrame:
    cache = _cache_path(ticker, "earnings", start, end)
    cached = _read_cache(cache)
    if cached is not None:
        return cached

    try:
        earn = t.earnings_dates
    except Exception:
        earn = None

    if earn is None or earn.empty:
        empty = pd.DataFrame(
            columns=["Date", "Is_Earnings_Day", "EPS_Estimate", "EPS_Actual", "EPS_Surprise_Pct"]
        )
        _write_cache(empty, cache)
        return empty

    df = earn.reset_index()
    date_col = df.columns[0]
    df = df.rename(columns={date_col: "Date"})
    df["Date"] = pd.to_datetime(df["Date"])
    if hasattr(df["Date"].dt, "tz") and df["Date"].dt.tz is not None:
        df["Date"] = df["Date"].dt.tz_localize(None)

    rename_map = {}
    for col in df.columns:
        col_lower = col.lower()
        if "eps" in col_lower and "estimate" in col_lower:
            rename_map[col] = "EPS_Estimate"
        elif "reported" in col_lower or ("eps" in col_lower and "actual" in col_lower):
            rename_map[col] = "EPS_Actual"
        elif "surprise" in col_lower and "%" in col_lower:
            rename_map[col] = "EPS_Surprise_Pct"
        elif "surprise" in col_lower:
            rename_map[col] = "EPS_Surprise_Pct"
    df = df.rename(columns=rename_map)

    df["Is_Earnings_Day"] = True

    keep = ["Date", "Is_Earnings_Day"]
    for c in ("EPS_Estimate", "EPS_Actual", "EPS_Surprise_Pct"):
        if c in df.columns:
            keep.append(c)
        else:
            df[c] = np.nan
            keep.append(c)
    df = df[keep]

    mask = (df["Date"] >= pd.Timestamp(start)) & (df["Date"] <= pd.Timestamp(end))
    df = df.loc[mask].reset_index(drop=True)

    _write_cache(df, cache)
    return df


def _compute_days_to_earnings(
    merge_dates: pd.Series, earnings_dates: list
) -> pd.Series:
    """Compute signed trading-day distance to nearest earnings date.

    Works for any data frequency (daily, hourly, 15-min, etc.).
    All bars on the same calendar day share the same value.
    Positive = earnings N trading days ahead, negative = N trading days behind, 0 = earnings day.
    """
    if not len(earnings_dates):
        return pd.Series(np.nan, index=merge_dates.index)

    norm_dates = pd.to_datetime(merge_dates).dt.normalize()
    unique_dates = norm_dates.drop_duplicates().sort_values().reset_index(drop=True)
    earn_set = {pd.Timestamp(d).normalize() for d in earnings_dates}
    earn_day_indices = [i for i, d in enumerate(unique_dates) if d in earn_set]

    if not earn_day_indices:
        return pd.Series(np.nan, index=merge_dates.index)

    earn_idx_arr = np.array(earn_day_indices)
    day_result = {}
    for i, d in enumerate(unique_dates):
        diffs = earn_idx_arr - i
        abs_diffs = np.abs(diffs)
        nearest = int(np.argmin(abs_diffs))
        day_result[d] = int(diffs[nearest])

    return norm_dates.map(day_result).astype("Int64")
