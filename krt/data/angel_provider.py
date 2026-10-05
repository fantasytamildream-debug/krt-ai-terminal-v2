"""Angel One SmartAPI data provider.
Credentials .env file-ல் இருந்து மட்டும் படிக்கப்படும் (GitHub-ல் push ஆகாது)."""
import json, os, time
from pathlib import Path
import pandas as pd
import requests
from .provider import DataProvider

MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
INDEX_TOKENS = {"NIFTY": "99926000", "BANKNIFTY": "99926009"}
REQUIRED = ("ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_MPIN", "ANGEL_TOTP_SECRET")


def _silence_smartapi_logs():
    """SmartAPI library password-ஐ screen + logs/app.log-ல் எழுதுகிறது. அதை நிறுத்துகிறோம்."""
    import logging, logzero
    logzero.logfile(None)
    logzero.loglevel(logging.CRITICAL)
    logging.getLogger("SmartApi").setLevel(logging.CRITICAL)


def angel_login():
    from SmartApi import SmartConnect
    import pyotp
    missing = [k for k in REQUIRED if not os.getenv(k)]
    if missing:
        raise RuntimeError(f".env file-ல் இவை இல்லை: {', '.join(missing)}  →  python scripts/setup_env.py run பண்ணுங்க")
    api = SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))
    _silence_smartapi_logs()
    totp = pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET").replace(" ", "")).now()
    s = api.generateSession(os.getenv("ANGEL_CLIENT_ID"), os.getenv("ANGEL_MPIN"), totp)
    if not s or not s.get("status"):
        msg = s.get("message") if isinstance(s, dict) else s
        raise RuntimeError(f"Angel One login failed: {msg}")
    return api, s


class AngelProvider(DataProvider):
    def __init__(self, cache_dir: str | Path, daily_days: int = 400, intraday_days: int = 25):
        self.api, _ = angel_login()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.daily_days, self.intraday_days = daily_days, intraday_days
        self.tokens = self._load_master()
        self._daily, self._intra = {}, {}

    # ---------- symbol → token ----------
    def _load_master(self) -> dict:
        from ..instruments import load
        data = load(self.cache_dir)
        self.fno = set(data["fno"])
        return {**data["eq"], **INDEX_TOKENS}

    # ---------- candles ----------
    def _candles(self, symbol: str, interval: str, days: int) -> pd.DataFrame:
        tok = self.tokens.get(symbol)
        if not tok:
            print(f"  ⚠ {symbol}: Angel One-ல் symbol கிடைக்கவில்லை")
            return pd.DataFrame()
        end = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)
        start = end - pd.Timedelta(days=days)
        params = {"exchange": "NSE", "symboltoken": tok, "interval": interval,
                  "fromdate": start.strftime("%Y-%m-%d 09:15"), "todate": end.strftime("%Y-%m-%d %H:%M")}
        msg = ""
        for _ in range(3):
            time.sleep(0.4)  # rate limit
            try:
                res = self.api.getCandleData(params)
            except Exception as e:
                res = {"status": False, "message": str(e)}
            if isinstance(res, dict) and res.get("status") and res.get("data"):
                df = pd.DataFrame(res["data"], columns=["time", "open", "high", "low", "close", "volume"])
                t = pd.to_datetime(df["time"])
                if t.dt.tz is not None:
                    t = t.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
                df["time"] = t
                return df.set_index("time").sort_index().astype(float)
            msg = res.get("message") if isinstance(res, dict) else res
            time.sleep(1.5)
        print(f"  ⚠ {symbol} {interval}: data வரவில்லை ({msg})")
        return pd.DataFrame()

    def daily(self, symbol):
        if symbol not in self._daily:
            df = self._candles(symbol, "ONE_DAY", self.daily_days)
            if not df.empty:
                df.index = df.index.normalize()
            self._daily[symbol] = df
        return self._daily[symbol]

    def intraday(self, symbol):
        if symbol not in self._intra:
            self._intra[symbol] = self._candles(symbol, "FIFTEEN_MINUTE", self.intraday_days)
        return self._intra[symbol]
