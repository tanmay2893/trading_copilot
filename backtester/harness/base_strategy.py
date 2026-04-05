from abc import ABC, abstractmethod
import pandas as pd


class BaseStrategy(ABC):
    """Base for backtest strategies. Subclasses may override __init__(self, df, *, param=default, ..., **kwargs)
    and must call super().__init__(df). Tunable parameters as __init__ kwargs allow the runner to pass overrides."""

    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self.signals: list[dict] = []

    @abstractmethod
    def setup(self) -> None:
        """Compute indicators. Store as new self.df columns."""
        ...

    @abstractmethod
    def generate_signals(self) -> None:
        """Iterate self.df rows and append dicts to self.signals.
        Each dict: {"date": ..., "signal": "BUY"/"SELL", "price": float}
        """
        ...

    def run(self) -> pd.DataFrame:
        self.setup()
        self.generate_signals()
        if not self.signals:
            return pd.DataFrame(columns=["Date", "Signal", "Price"])
        result = pd.DataFrame(self.signals)
        rename_map = {}
        for col in result.columns:
            lc = col.lower().strip()
            if lc == "date" and "Date" not in rename_map.values():
                rename_map[col] = "Date"
            elif lc == "signal" and "Signal" not in rename_map.values():
                rename_map[col] = "Signal"
            elif lc == "price" and "Price" not in rename_map.values():
                rename_map[col] = "Price"
        result = result.rename(columns=rename_map)
        if {"Date", "Signal", "Price"}.issubset(result.columns):
            return result[["Date", "Signal", "Price"]]
        result = result.iloc[:, :3]
        result.columns = ["Date", "Signal", "Price"]
        return result
