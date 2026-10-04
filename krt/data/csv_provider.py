from pathlib import Path
import pandas as pd
from .provider import DataProvider


class CSVProvider(DataProvider):
    """Offline testing: data/sample/{SYMBOL}_daily.csv, {SYMBOL}_15m.csv"""

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self._cache: dict[str, pd.DataFrame] = {}

    def _load(self, name: str) -> pd.DataFrame:
        if name not in self._cache:
            p = self.folder / f"{name}.csv"
            if not p.exists():
                self._cache[name] = pd.DataFrame()
            else:
                self._cache[name] = pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
        return self._cache[name]

    def daily(self, symbol):
        return self._load(f"{symbol}_daily")

    def intraday(self, symbol):
        return self._load(f"{symbol}_15m")
