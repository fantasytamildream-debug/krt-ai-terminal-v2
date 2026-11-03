"""Angel One session — login (நாளுக்கு ஒருமுறை), throttle, candles, quotes, OI buildup."""
import threading, time
import pandas as pd
from .data.angel_provider import angel_login
from .instruments import ist_today


class Angel:
    def __init__(self):
        self.api, self.day, self._last = None, None, 0.0
        self._lk = threading.Lock()

    def ensure(self):
        with self._lk:
            need = self.api is None or self.day != ist_today()
        if need:
            self.api, _ = angel_login()
            self.day = ist_today()

    def _wait(self, gap):
        with self._lk:
            d = time.time() - self._last
            if d < gap:
                time.sleep(gap - d)
            self._last = time.time()

    def priority(self):
        """with ag.priority(): ... — இந்த thread-ன் API calls முதலில் (மற்ற loops max 120 sec காத்திருக்கும்).
        👑 Goki / Elite 15-min scan deep scan-ஓட மோதி late ஆனதுக்கு fix."""
        ag = self

        class _P:
            def __enter__(self_):
                ag._prio = threading.get_ident()
                ag._prio_t = time.time()

            def __exit__(self_, *e):
                ag._prio = None
                return False
        return _P()

    def _yield(self):
        p = getattr(self, "_prio", None)
        if not p or p == threading.get_ident():
            return
        end = time.time() + 120
        while getattr(self, "_prio", None) and time.time() < end and time.time() - getattr(self, "_prio_t", 0) < 180:
            time.sleep(0.2)

    CANDLE_PER_MIN = 150          # Angel historical API ≈180/min — 150-ல் நிறுத்தி வைக்கும் (எல்லா loops சேர்த்து)

    def _candle_slot(self):
        """Sliding 60-sec window: நிமிடத்துக்கு CANDLE_PER_MIN-க்கு மேல் candle request போகாது (காத்திருக்கும்)."""
        import collections
        with self._lk:
            w = self.__dict__.setdefault("_cwin", collections.deque())
            now = time.time()
            while w and now - w[0] > 60:
                w.popleft()
            wait = (60 - (now - w[0]) + 0.05) if len(w) >= self.CANDLE_PER_MIN else 0
        if wait > 0:
            self.rate_waits = getattr(self, "rate_waits", 0) + 1
            time.sleep(min(wait, 30))
        with self._lk:
            self._cwin.append(time.time())

    def _call(self, fn, *a, gap=0.4, tries=4):
        self.ensure()
        self._yield()
        err = None
        for i in range(tries):
            cd = getattr(self, "_cool", 0) - time.time()
            if cd > 0:
                time.sleep(min(cd, 5))               # rate-limit cool-down — எல்லா threads-ம் காத்திருக்கும்
            self._wait(gap)
            try:
                res = fn(*a)
            except Exception as e:
                res, err = None, str(e)
                if "access rate" in err.lower() or "rate limit" in err.lower() or "too many" in err.lower():
                    self._cool = time.time() + 3 * (2 ** i)   # Angel "exceeding access rate" → 3 / 6 / 12 sec backoff
                    self.rate_hits = getattr(self, "rate_hits", 0) + 1
                    continue
            if isinstance(res, dict) and res.get("status"):
                return res
            if isinstance(res, dict):
                err = res.get("message") or res.get("errorcode")
                if res.get("errorcode") in ("AG8001", "AG8002", "AG8003"):  # token expired
                    self.api = None
                    self.ensure()
            time.sleep(0.8)
        raise RuntimeError(err or "Angel One response இல்லை")

    def candles(self, exch, token, interval, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        p = {"exchange": exch, "symboltoken": token, "interval": interval,
             "fromdate": start.strftime("%Y-%m-%d %H:%M"), "todate": end.strftime("%Y-%m-%d %H:%M")}
        self._candle_slot()
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
