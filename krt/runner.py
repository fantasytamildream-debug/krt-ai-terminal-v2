"""ஒரு scan-ஐ run செய்து JSON-ready result தரும் (CLI + website இரண்டுக்கும்)."""
import os
from dataclasses import asdict
import pandas as pd
from dotenv import load_dotenv
from .config import load_settings, ROOT
from .data.csv_provider import CSVProvider
from .scanner import scan
from .chartink import build_watchlist
from .signals import SignalLog

IST = "Asia/Kolkata"


def now_ist() -> pd.Timestamp:
    return pd.Timestamp.now(tz=IST).tz_localize(None).floor("min")


def market_open(t: pd.Timestamp) -> bool:
    """NSE holidays இதில் இல்லை — holiday அன்று data stale ஆக BLOCKED காட்டும்."""
    if t.weekday() >= 5:
        return False
    m = t.hour * 60 + t.minute
    return 9 * 60 + 15 <= m <= 15 * 60 + 30


def angel_configured() -> bool:
    load_dotenv(ROOT / ".env", override=True)
    return all(os.getenv(k) for k in ("ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_MPIN", "ANGEL_TOTP_SECRET"))


def run_scan(source: str | None = None, at: str | None = None, use_chartink: bool = True) -> dict:
    load_dotenv(ROOT / ".env", override=True)
    cfg = load_settings()
    source = source or os.getenv("BROKER", "csv")
    now = pd.Timestamp(at) if at else now_ist()
    msgs = []

    if source == "angel":
        from .data.angel_provider import AngelProvider
        provider = AngelProvider(ROOT / "data" / "cache")
    else:
        provider = CSVProvider(ROOT / "data" / "sample")

    watch = None
    if use_chartink and source == "angel" and cfg.get("chartink", {}).get("enabled"):
        watch, cmsgs = build_watchlist(cfg)
        msgs += cmsgs
        if cfg["chartink"].get("fno_only") and getattr(provider, "fno", None):
            non_fno = [s for s in watch if s not in provider.fno]
            for s in non_fno:
                watch.pop(s)
            if non_fno:
                msgs.append(f"F&O இல்லாததால் skip: {', '.join(non_fno)}")
        if not watch:
            msgs.append("Chartink-ல் stocks இல்லை → default stock list scan ஆகிறது")
            watch = None
        if at:
            msgs.append("Chartink எப்போதும் இப்போதைய result தான் தரும் — பழைய time-க்கு அல்ல")

    res = scan(provider, cfg, now, watch)
    log = SignalLog(ROOT / "logs" / "signals.jsonl")
    new = [s for s in res["signals"] if log.add(s)]
    res["signals"] = [{"id": s.id, **asdict(s)} for s in res["signals"]]
    res.update(msgs=msgs, source=source, new_signals=len(new),
               market_open=market_open(now), replay=bool(at))
    return res
