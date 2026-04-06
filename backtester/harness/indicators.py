import pandas as pd
from ta.momentum import RSIIndicator, StochasticOscillator, WilliamsRIndicator
from ta.trend import MACD, SMAIndicator, EMAIndicator, CCIIndicator, ADXIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator, VolumeWeightedAveragePrice


def add_rsi(df: pd.DataFrame, period: int = 14, col: str = "Close") -> None:
    ind = RSIIndicator(close=df[col], window=period)
    df["RSI"] = ind.rsi().ffill()


def add_macd(
    df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> None:
    ind = MACD(
        close=df["Close"],
        window_slow=slow,
        window_fast=fast,
        window_sign=signal,
    )
    df["MACD"] = ind.macd().ffill()
    df["MACD_Signal"] = ind.macd_signal().ffill()
    df["MACD_Hist"] = ind.macd_diff().ffill()


def add_bollinger(
    df: pd.DataFrame, period: int = 20, std_dev: float = 2
) -> None:
    ind = BollingerBands(
        close=df["Close"], window=period, window_dev=std_dev
    )
    df["BB_Upper"] = ind.bollinger_hband().ffill()
    df["BB_Middle"] = ind.bollinger_mavg().ffill()
    df["BB_Lower"] = ind.bollinger_lband().ffill()


def _sma_ema_column_name(prefix: str, period: int, col: str) -> str:
    """Stable column name; disambiguate non-Close series (e.g. volume MA vs price MA)."""
    if col == "Close":
        return f"{prefix}_{period}"
    safe = "".join(ch if ch.isalnum() else "_" for ch in col).strip("_") or "series"
    return f"{prefix}_{period}_{safe}"


def add_sma(df: pd.DataFrame, period: int, col: str = "Close") -> None:
    ind = SMAIndicator(close=df[col], window=period)
    df[_sma_ema_column_name("SMA", period, col)] = ind.sma_indicator().ffill()


def add_ema(df: pd.DataFrame, period: int, col: str = "Close") -> None:
    ind = EMAIndicator(close=df[col], window=period)
    df[_sma_ema_column_name("EMA", period, col)] = ind.ema_indicator().ffill()


def add_atr(df: pd.DataFrame, period: int = 14, suffix: str | None = None) -> None:
    """Add ATR column. suffix=None -> 'ATR'; suffix='5' -> 'ATR_5' (for multiple periods)."""
    ind = AverageTrueRange(
        high=df["High"], low=df["Low"], close=df["Close"], window=period
    )
    col = "ATR" if suffix is None else f"ATR_{suffix}"
    df[col] = ind.average_true_range().ffill()


def add_stochastic(
    df: pd.DataFrame, k_period: int = 14, d_period: int = 3
) -> None:
    ind = StochasticOscillator(
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        window=k_period,
        smooth_window=d_period,
    )
    df["Stoch_K"] = ind.stoch().ffill()
    df["Stoch_D"] = ind.stoch_signal().ffill()


def add_vwap(df: pd.DataFrame) -> None:
    ind = VolumeWeightedAveragePrice(
        high=df["High"],
        low=df["Low"],
        close=df["Close"],
        volume=df["Volume"],
    )
    df["VWAP"] = ind.volume_weighted_average_price().ffill()


def add_obv(df: pd.DataFrame) -> None:
    ind = OnBalanceVolumeIndicator(close=df["Close"], volume=df["Volume"])
    df["OBV"] = ind.on_balance_volume().ffill()


def add_williams_r(df: pd.DataFrame, period: int = 14) -> None:
    ind = WilliamsRIndicator(
        high=df["High"], low=df["Low"], close=df["Close"], lbp=period
    )
    df["Williams_R"] = ind.williams_r().ffill()


def add_cci(df: pd.DataFrame, period: int = 20, constant: float = 0.015) -> None:
    ind = CCIIndicator(
        high=df["High"], low=df["Low"], close=df["Close"], window=period, constant=constant
    )
    df["CCI"] = ind.cci().ffill()


def add_adx(df: pd.DataFrame, period: int = 14) -> None:
    ind = ADXIndicator(
        high=df["High"], low=df["Low"], close=df["Close"], window=period
    )
    df["ADX"] = ind.adx().ffill()
    df["ADX_Pos"] = ind.adx_pos().ffill()
    df["ADX_Neg"] = ind.adx_neg().ffill()
