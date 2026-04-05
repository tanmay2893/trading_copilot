"""yfinance data downloader with local parquet caching."""

from __future__ import annotations

import time

import pandas as pd
import yfinance as yf

from backtester.config import CACHE_DIR
from backtester.data.symbol_resolve import get_country

STANDARD_COLUMNS = ["Date", "Open", "High", "Low", "Close", "Volume"]
CACHE_MAX_AGE_SEC = 24 * 60 * 60


def download_data(
    ticker: str,
    start: str,
    end: str,
    interval: str = "1d",
    country: str | None = None,
) -> pd.DataFrame:
    """Download OHLCV data. For Indian symbols, try .NS (NSE) first then .BO (BSE)."""
    if country is None:
        country = get_country(ticker)
    # Indian stocks: try .NS then .BO (skip suffix if ticker starts with ^, e.g. indices)
    if country == "INDIA":
        if (ticker or "").strip().startswith("^"):
            candidates = [ticker.strip()]
        else:
            candidates = [ticker + ".NS", ticker + ".BO"]
    else:
        candidates = [ticker]
    last_error: Exception | None = None
    for yf_ticker in candidates:
        try:
            return _download_one(yf_ticker, start, end, interval)
        except Exception as e:
            last_error = e
            continue
    raise last_error or ValueError(
        f"No data returned for {ticker} ({interval}) from {start} to {end}"
    )


def _download_one(ticker: str, start: str, end: str, interval: str) -> pd.DataFrame:
    cache_path = CACHE_DIR / f"{ticker}_{interval}_{start}_{end}.parquet"
    if cache_path.exists():
        mtime = cache_path.stat().st_mtime
        if time.time() - mtime < CACHE_MAX_AGE_SEC:
            df = pd.read_parquet(cache_path)
            _validate(df)
            return df

    t = yf.Ticker(ticker)
    hist = t.history(start=start, end=end, interval=interval)
    if hist.empty:
        raise ValueError(f"No data returned for {ticker} ({interval}) from {start} to {end}")

    hist = hist.reset_index()
    rename = {}
    first_col = hist.columns[0]
    if first_col not in ("Date", "Datetime"):
        rename[first_col] = "Date"
    elif first_col == "Datetime":
        rename["Datetime"] = "Date"
    if "Close" not in hist.columns and "Adj Close" in hist.columns:
        rename["Adj Close"] = "Close"
    df = hist.rename(columns=rename)
    missing = [c for c in STANDARD_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    df = df[STANDARD_COLUMNS]

    if hasattr(df["Date"].dt, "tz") and df["Date"].dt.tz is not None:
        df["Date"] = df["Date"].dt.tz_localize(None)

    _validate(df)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_path, index=False)
    return df


def _validate(df: pd.DataFrame) -> None:
    if len(df) < 10:
        raise ValueError(f"Data has only {len(df)} rows; need at least 10")
    for col in df.columns:
        if df[col].isna().all():
            raise ValueError(f"Column '{col}' is entirely NaN")
