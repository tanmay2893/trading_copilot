"""Server-side chart rendering for LLM vision context.

Renders OHLCV candlestick data with buy/sell signal markers and indicator
overlays into a base64-encoded PNG suitable for multimodal LLM prompts.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)


def render_chart_to_base64(
    data_df: pd.DataFrame,
    signals_df: Optional[pd.DataFrame] = None,
    indicator_columns: Optional[list[str]] = None,
    indicator_df: Optional[pd.DataFrame] = None,
    title: str = "Strategy Chart",
    width: int = 16,
    height: int = 9,
    dpi: int = 120,
) -> str | None:
    """Render an OHLCV chart with signals and indicators, return base64 PNG.

    Returns None if rendering fails (e.g. missing data or matplotlib issues).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib.patches import FancyArrowPatch
    except ImportError:
        log.warning("matplotlib not available — chart screenshot skipped")
        return None

    if data_df is None or data_df.empty:
        return None

    try:
        chart_df = indicator_df if indicator_df is not None else data_df.copy()
        date_col = "Date" if "Date" in chart_df.columns else "Datetime" if "Datetime" in chart_df.columns else chart_df.columns[0]
        df = chart_df.copy()

        if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
            df[date_col] = pd.to_datetime(df[date_col], utc=True)
        if hasattr(df[date_col].dt, "tz") and df[date_col].dt.tz is not None:
            df[date_col] = df[date_col].dt.tz_localize(None)

        df = df.sort_values(date_col).reset_index(drop=True)
        dates = df[date_col]

        has_indicators = indicator_columns and any(c in df.columns and pd.api.types.is_numeric_dtype(df[c]) for c in indicator_columns)
        fig, ax_price = plt.subplots(figsize=(width, height), dpi=dpi)
        fig.patch.set_facecolor("#1a1a2e")
        ax_price.set_facecolor("#1a1a2e")

        # Candlestick-like rendering via bar chart
        if all(c in df.columns for c in ["Open", "High", "Low", "Close"]):
            up = df["Close"] >= df["Open"]
            down = ~up

            ax_price.vlines(dates[up], df["Low"][up], df["High"][up], color="#22c55e", linewidth=0.6)
            ax_price.vlines(dates[down], df["Low"][down], df["High"][down], color="#ef4444", linewidth=0.6)

            bar_width = _compute_bar_width(dates)
            ax_price.bar(dates[up], df["Close"][up] - df["Open"][up], bottom=df["Open"][up],
                         width=bar_width, color="#22c55e", edgecolor="#22c55e", linewidth=0.5)
            ax_price.bar(dates[down], df["Open"][down] - df["Close"][down], bottom=df["Close"][down],
                         width=bar_width, color="#ef4444", edgecolor="#ef4444", linewidth=0.5)
        elif "Close" in df.columns:
            ax_price.plot(dates, df["Close"], color="#60a5fa", linewidth=1)

        # Overlay indicators (SMA, EMA, BB, etc.)
        overlay_colors = ["#f59e0b", "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16"]
        if has_indicators:
            color_idx = 0
            for col in indicator_columns:
                if col not in df.columns or not pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_bool_dtype(df[col]):
                    continue
                vals = df[col].dropna()
                if vals.empty:
                    continue
                price_range = df["Close"].max() - df["Close"].min() if "Close" in df.columns else 1
                col_range = vals.max() - vals.min()
                if col_range < price_range * 5:
                    c = overlay_colors[color_idx % len(overlay_colors)]
                    ax_price.plot(dates, df[col], color=c, linewidth=1, alpha=0.8, label=col)
                    color_idx += 1

        # Buy/Sell signal markers
        if signals_df is not None and not signals_df.empty:
            sig_date_col = "Date" if "Date" in signals_df.columns else signals_df.columns[0]
            sig_df = signals_df.copy()
            if not pd.api.types.is_datetime64_any_dtype(sig_df[sig_date_col]):
                sig_df[sig_date_col] = pd.to_datetime(sig_df[sig_date_col], utc=True)
            if hasattr(sig_df[sig_date_col].dt, "tz") and sig_df[sig_date_col].dt.tz is not None:
                sig_df[sig_date_col] = sig_df[sig_date_col].dt.tz_localize(None)

            buys = sig_df[sig_df["Signal"] == "BUY"]
            sells = sig_df[sig_df["Signal"] == "SELL"]

            if not buys.empty:
                ax_price.scatter(buys[sig_date_col], buys["Price"], marker="^", color="#22c55e",
                                 s=60, zorder=5, label="BUY", edgecolors="white", linewidths=0.5)
            if not sells.empty:
                ax_price.scatter(sells[sig_date_col], sells["Price"], marker="v", color="#ef4444",
                                 s=60, zorder=5, label="SELL", edgecolors="white", linewidths=0.5)

        ax_price.set_title(title, color="white", fontsize=14, pad=10)
        ax_price.tick_params(colors="white", labelsize=8)
        ax_price.yaxis.label.set_color("white")
        ax_price.spines["top"].set_visible(False)
        ax_price.spines["right"].set_color("#333")
        ax_price.spines["left"].set_color("#333")
        ax_price.spines["bottom"].set_color("#333")
        ax_price.grid(True, alpha=0.15, color="white")

        ax_price.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax_price.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate(rotation=30)

        if has_indicators or (signals_df is not None and not signals_df.empty):
            ax_price.legend(loc="upper left", fontsize=8, facecolor="#1a1a2e",
                            edgecolor="#444", labelcolor="white")

        plt.tight_layout()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")

    except Exception:
        log.warning("Chart rendering failed", exc_info=True)
        return None


def _compute_bar_width(dates: pd.Series) -> float:
    """Estimate a reasonable bar width from date spacing."""
    if len(dates) < 2:
        return 0.8
    diffs = dates.diff().dropna()
    median_diff = diffs.median()
    if hasattr(median_diff, "days"):
        days = median_diff.days
    else:
        days = median_diff.total_seconds() / 86400
    return max(days * 0.6, 0.3)
