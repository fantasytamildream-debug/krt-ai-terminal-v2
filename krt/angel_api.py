"""Angel One session — login (நாளுக்கு ஒருமுறை), throttle, candles, quotes, OI buildup."""
import time
import pandas as pd
from .data.angel_provider import angel_login
from .instruments import ist_today


class Angel:
    def __init__(self):
        self.api, self.day, self._last = None, None, 0.0

    def ensure(self):
        if self.api is None or self.day != ist_today():
            self.api, _ = angel_login()
            self.day = ist_today()

    def _wait(self, gap):
        d = time.time() - self._last
        if d < gap:
            time.sleep(gap - d)
        self._last = time.time()

    def _call(self, fn, *a, gap=0.4, tries=3):
        self.ensure()
        err = None
        for i in range(tries):
            self._wait(gap)
            try:
                res = fn(*a)
            except Exception as e:
                res, err = None, str(e)
            if isinstance(res, dict) and res.get("status"):
                return res
            if isinstance(res, dict):
                err = res.get("message") or res.get("errorcode")
                if res.get("errorcode") in ("AG8001", "AG8002", "AG8003"):  # token expired
                    self.api = None
                    self.ensure()
            time.sleep(1 + i)
        raise RuntimeError(err or "Angel One response இல்லை")

    def candles(self, exch, token, interval, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        p = {"exchange": exch, "symboltoken": token, "interval": interval,
             "fromdate": start.strftime("%Y-%m-%d %H:%M"), "todate": end.strftime("%Y-%m-%d %H:%M")}
        try:
            res = self._call(lambda: self.api.getCandleData(p))
        except RuntimeError:
            return pd.DataFrame()
        rows = res.get("data") or []
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
        t = pd.to_datetime(df["time"])
        if t.dt.tz is not None:
            t = t.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
        df["time"] = t
        return df.set_index("time").sort_index().astype(float)

    def quotes(self, exch_tokens: dict) -> dict:
        """{"NSE":[tok..],"NFO":[..]} → {token: quote}. 50 per call."""
        flat = [(e, t) for e, toks in exch_tokens.items() for t in toks]
        out = {}
        for i in range(0, len(flat), 50):
            batch = {}
            for e, t in flat[i:i + 50]:
                batch.setdefault(e, []).append(t)
            try:
                res = self._call(lambda: self.api.getMarketData("FULL", batch), gap=0.25)
            except RuntimeError:
                continue
            for q in (res.get("data") or {}).get("fetched") or []:
                out[str(q.get("symbolToken"))] = q
        return out

    def oi_buildup(self, kind: str) -> list:
        try:
            res = self._call(lambda: self.api.oIBuildup({"expirytype": "NEAR", "datatype": kind}), gap=1.1)
            return res.get("data") or []
        except RuntimeError:
            return []
