"""Resolve stock symbol to exchange/country and yfinance ticker (e.g. .NS/.BO for India)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Project root: parent of backtester package
_BACKTESTER_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKTESTER_DIR.parent

_US_STOCKS_PATH = _PROJECT_ROOT / "us_stocks.csv"
_INDIA_STOCKS_PATH = _PROJECT_ROOT / "india_stocks.csv"

_cached_us: pd.DataFrame | None = None
_cached_india: pd.DataFrame | None = None


def _load_us_symbols() -> set[str]:
    global _cached_us
    if _cached_us is None:
        if not _US_STOCKS_PATH.exists():
            _cached_us = pd.DataFrame(columns=["Symbol", "Name"])
        else:
            _cached_us = pd.read_csv(_US_STOCKS_PATH)
    return set(_cached_us["Symbol"].astype(str).str.upper())


def _load_india_symbols() -> set[str]:
    global _cached_india
    if _cached_india is None:
        if not _INDIA_STOCKS_PATH.exists():
            _cached_india = pd.DataFrame(columns=["Symbol", "Name"])
        else:
            _cached_india = pd.read_csv(_INDIA_STOCKS_PATH)
    return set(_cached_india["Symbol"].astype(str).str.upper())


def get_country(symbol: str) -> str:
    """Return 'INDIA' if symbol is in india_stocks.csv, else 'US'."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return "US"
    if sym in _load_india_symbols():
        return "INDIA"
    return "US"


def resolve_yfinance_symbol(symbol: str, country: str | None = None) -> str:
    """Return the ticker string used by yfinance (no network call).

    - US: symbol as-is.
    - INDIA: returns symbol.NS (callers should try .NS then .BO when fetching data).
    """
    sym = (symbol or "").strip()
    if not sym:
        raise ValueError("Empty symbol")
    if country is None:
        country = get_country(sym)
    if country != "INDIA":
        return sym
    if sym.startswith("^"):
        return sym
    return sym + ".NS"


def resolve_yfinance_symbol_with_fallback(symbol: str, country: str | None = None) -> str:
    """Resolve Indian symbols by trying .NS then .BO (one quick history check each)."""
    sym = (symbol or "").strip()
    if not sym:
        raise ValueError("Empty symbol")
    if country is None:
        country = get_country(sym)
    if country != "INDIA":
        return sym
    if sym.startswith("^"):
        return sym
    import yfinance as yf
    for suffix in (".NS", ".BO"):
        t = yf.Ticker(sym + suffix)
        hist = t.history(period="5d", interval="1d")
        if hist is not None and not hist.empty and len(hist) >= 1:
            return sym + suffix
    return sym + ".NS"
