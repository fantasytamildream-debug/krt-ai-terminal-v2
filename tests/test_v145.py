"""v145: every alert carries an exact option (TAKE / SKIP) · Trident ACTIVE (80–84, half size) · NIFTY candles fall back to live ticks."""
import pandas as pd

import server as S
from krt import trident as T


def test_active_band():
    assert T.band(82) == "ACTIVE" and T.band(86) == "HIGH QUALITY" and T.band(78) == "WATCHLIST"


def test_alert_picks_turn_and_crash(monkeypatch):
    from krt import crash as CR, bigvol as BV
    td = str(S.now_ist().date())
    CR.TURN.update(side="UP", date=td, since="11:56", off=0.75, text="x")
    CR.DAY.update(date=td, hi=25950.0, lo=25734.0)
    S.TICK["items"]["NIFTY"] = {"ltp": 25930.0, "pct": 0.42}
    now = S.now_ist()
    BV.SCR["ENRIN|x|CRASH"] = {"symbol": "ENRIN", "date": td, "time": now.strftime("%H:%M"), "full": str(now), "side": "CRASH", "m10": -0.9, "vol": 7.4,
                               "price": 3120.0, "ul_sl": 3134.8, "opt": {}, "result": None}
    monkeypatch.setattr(S, "_cc_strike", lambda sym, sd, px: {"strike": round(px / 50) * 50, "side": sd, "token": sym + sd, "exch": "NFO",
                                                              "expiry": "2026-12-29", "lot": 65 if sym == "NIFTY" else 275})
    monkeypatch.setattr(S, "opt_quotes", lambda items: {items[0][1]: {"ltp": 120.0, "bid": 119.5, "ask": 120.0}})
    S.APC.update(t=0, d={})
    try:
        P = S.alert_picks()
        assert P["turn"]["side"] == "CE" and P["turn"]["take"] and P["turn"]["plan"]["sl"] < 120
        k = [k for k in P if k.startswith("SCR|ENRIN")][0]
        assert P[k]["side"] == "PE" and P[k]["strike"] == 3100 and "plan" in P[k]
    finally:
        BV.SCR.pop("ENRIN|x|CRASH", None)
        CR.TURN.update(side=None)


def test_nifty_candles_from_ticks_when_angel_has_none():
    from krt import roadmap as RM, behaviour as BH
    now = pd.Timestamp("2026-11-26 12:05:00")
    RM.H.pop("NIFTY", None)
    for i in range(6 * 60):                                   # 09:15 → 12:15 ticks every 30 s… only up to now matters
        t = pd.Timestamp("2026-11-26 09:15:00") + pd.Timedelta(seconds=30 * i)
        if t > now:
            break
        RM.H.setdefault("NIFTY", __import__("collections").deque(maxlen=5000)).append((t, 25800 + i * 0.3))
    BH.M["raw"] = {}
    S.BHC["today"] = {}
    d = S._tri_d5("NIFTY", now)
    assert d is not None and d.index[-1] == pd.Timestamp("2026-11-26 12:00") and len(d) > 20
