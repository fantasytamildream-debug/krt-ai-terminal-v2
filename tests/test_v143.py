"""v143: free lane (Index OI · OI Footprint · Sweep+CHOCH · STAR modules never gate-blocked) · red→green turn alert ·
Market Brain / Roadmap picks carry a full call (trigger, entry, SL, targets)."""
import pandas as pd

import server as S
from krt import calls as C, crash as CR


def test_free_lane_turns_blocks_into_warnings(monkeypatch):
    monkeypatch.setattr(C, "_quality_v6", lambda c, now: ("Q_DAY_MAX", "today's index calls max reached"))
    c = {"source": "Index OI", "symbol": "NIFTY"}
    assert C.quality_v6(c, pd.Timestamp("2026-11-26 10:30")) is None and c["free_lane"] and "max reached" in c["risk_warn"][0]
    c2 = {"source": "🔥 Sweep+CHOCH+Candle", "symbol": "TCS"}
    assert C.quality_v6(c2, pd.Timestamp("2026-11-26 10:30")) is None
    o = {"source": "2K Profit Machine", "symbol": "TCS"}
    assert C.quality_v6(o, pd.Timestamp("2026-11-26 10:30"))[0] == "Q_DAY_MAX"            # normal modules unchanged
    monkeypatch.setattr(C, "_quality_v6", lambda c, now: ("Q_DUP", "already called"))
    assert C.quality_v6({"source": "Index OI"}, pd.Timestamp("2026-11-26 10:30"))[0] == "Q_DUP"   # duplicates still blocked


def _reset():
    CR.H.clear()
    CR.DAY.update(date=None, hi=None, lo=None)
    CR.TURN.update(side=None, since=None, off=None, day=None, text=None, strong=False, date=None)
    CR.STATE.update(level="NONE", side=None, signals=[], history=[], last_push=None)


def test_red_to_green_turn_alerts():
    _reset()
    prev, t0, sent = 25650.0, pd.Timestamp("2026-11-26 09:30"), []
    path = [25640 - i * 0.6 for i in range(40)] + [25616 + i * 1.6 for i in range(1, 70)]     # low −0.13 %… → +100 pts to green
    path = [25610 - i * 0.2 for i in range(5)] + path
    for i, px in enumerate(path):
        CR.tick({"NIFTY": {"ltp": px, "pct": (px / prev - 1) * 100}}, t0 + pd.Timedelta(seconds=20 * i), {}, None, lambda *a: sent.append(a))
    assert CR.TURN["side"] == "UP" and "SHORT COVERING" in CR.TURN["text"] and any("SHORT COVERING" in s[0] for s in sent)


def test_brain_picks_have_full_call(monkeypatch):
    S.BHC["d"] = {"NIFTY": {"name": "NIFTY", "spot": 25800.0, "side": None, "p": {"up": 15, "dn": 12}}}
    S.RMC["d"] = {"maps": {"NIFTY": {"up": [{"level": 25850, "p60": 40}], "down": [{"level": 25750, "p60": 45}]}}}
    monkeypatch.setattr(S, "_cc_strike", lambda n, sd, px: {"strike": 25800, "side": sd, "token": "T" + sd, "exch": "NFO", "expiry": "2026-12-01", "lot": 65})
    monkeypatch.setattr(S, "opt_quotes", lambda items: {items[0][1]: {"ltp": 150.0, "bid": 149.5, "ask": 150.0}})
    d = S.behaviour_state()
    ce = [p for p in d["picks"]["NIFTY"] if p["side"] == "CE"][0]
    assert ce["trigger"] == 25850 and ce["plan"]["entry"] == 150.0 and ce["plan"]["sl"] < 150 and len(ce["plan"]["targets"]) == 3
    S.BHC["d"], S.RMC["d"] = {}, None
