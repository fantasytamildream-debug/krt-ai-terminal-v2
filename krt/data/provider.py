"""Data provider interface. Broker (Kite / Upstox / Angel / Dhan) adapters இதை implement செய்ய வேண்டும்."""
from abc import ABC, abstractmethod
import pandas as pd


class DataProvider(ABC):
    @abstractmethod
    def daily(self, symbol: str) -> pd.DataFrame:
        """Corporate-action adjusted daily OHLCV. Index: date. Columns: open high low close volume."""

    @abstractmethod
    def intraday(self, symbol: str) -> pd.DataFrame:
        """Intraday OHLCV, index = candle START time."""

    def is_stale(self, symbol: str, now: pd.Timestamp, max_age_min: int = 20) -> bool:
        df = self.intraday(symbol)
        if df.empty:
            return True
        return (now - df.index[-1]) > pd.Timedelta(minutes=max_age_min)

    def option_chain(self, symbol: str) -> pd.DataFrame:
        """Phase 3: live option chain (strike, expiry, type, bid, ask, oi, volume, iv, delta)."""
        raise NotImplementedError("Option chain — development phase 3")
