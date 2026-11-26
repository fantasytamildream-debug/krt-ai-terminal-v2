"""v147: alerts step OTM to fit ₹2,500 · TAKE NOW / WAIT / MISSED / SKIP states · GU far-expiry thresholds."""
import numpy as np
import pandas as pd

import server as S
from krt import gamma_unwind as G


def test_otm_fit_and_states(monkeypatch):
    from krt import crash as CR, bigvol as BV
    td = str(S.now_ist().date())
    CR.TURN.update(side=None)
    now = S.now_ist()
    BV.SCR.clear()
    BV.SCR["GODREJPROP|x|SURGE"] = {"symbol": "GODREJPROP", "date": td, "time": now.strftime("%H:%M"), "full": str(now), "side": "SURGE",
                                    "m10": 1.37, "vol": 5.3, "price": 1980.0, "ul_sl": 1959.5, "opt": {}, "result": None}
    rows = [[f"T{k}", f"GP{k}CE", "2026-12-29", float(k), "CE", 325, "NFO"] for k in range(1900, 2120, 20)]
    monkeypatch.setattr(S, "_cc_strike", lambda sym, sd, px: {"strike": 1980.0, "side": "CE", "token": "T1980", "exch": "NFO", "expiry": "2026-12-29", "lot": 325})
    monkeypatch.setattr(S, "opt_quotes", lambda items: {items[0][1]: {"ltp": max(5.0, 100 - (int(items[0][1][1:]) - 1980) * 1.2)}})
    import krt.instruments as INS
    monkeypatch.setattr(INS, "contracts", lambda inst, sym, n: (None, rows))
    monkeypatch.setattr(S, "load_inst", lambda p: {})
    S.APC.update(t=0, d={})
    try:
        P = S.alert_picks()
        k = [v for kk, v in P.items() if kk.startswith("SCR|GODREJPROP|")][0]
        assert k["state"] == "TAKE NOW" and k["otm"] >= 1 and k["strike"] > 1980 and k["plan"]["risk_lot"] <= 2500
    finally:
        BV.SCR.clear()


def test_gu_far_expiry_thresholds():
    n = 30
    idx = pd.date_range("2026-11-26 10:00", periods=n, freq="5min")
    c = np.full(n, 10.0)
    c[-1] = 10.6
    df = pd.DataFrame({"open": c - 0.05, "high": c + 0.1, "low": c - 0.1, "close": c, "volume": np.r_[np.full(n - 3, 100), [300, 300, 300]]}, index=idx)
    oi = [1000] * 20 + [990, 975, 960, 945]                     # −5.5 % from peak, falling
    con = {"side": "CE", "edge": 100, "dte": 23, "oi": 10 ** 6, "lot": 100, "zone": (95, 100)}
    r = G.classic_eval(con, df, oi, {"close5": 101}, {}, pd.Timestamp("2026-11-26 11:00"), "UP")
    assert r["checks"]["A · OI unwind ≥5% + falling"]
    near = dict(con, dte=5)
    r2 = G.classic_eval(near, df, oi, {"close5": 101}, {}, pd.Timestamp("2026-11-26 11:00"), "UP")
    assert not r2["checks"]["A · OI unwind ≥8% + falling"]
