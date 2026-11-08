"""🎯 DSK tests — walk-forward honesty (signal → ON, noise → OFF) · picks · no-trade · speed."""
import time

import numpy as np
import pandas as pd

from krt import dsk as DS


def _calls(n, rng, signal=True):
    out = []
    for i in range(n):
        trend = rng.random() < 0.5
        ce = rng.random() < 0.5
        vr = rng.uniform(1, 6)
        win = (trend and vr > 3) if signal else (rng.random() < 0.45)
        if signal and rng.random() < 0.15:
            win = not win                                       # கொஞ்சம் noise
        out.append({"id": str(i), "source": "Top Movers" if trend else "V4 💎 VWAP Mean Reversion", "kind": "MOVERS" if trend else "V4",
                    "side": "CE" if ce else "PE", "vol_ratio": vr, "grade": "A", "time": f"{10 + i % 5}:{(i * 7) % 60:02d}", "regime": "TREND UP",
                    "status": "T3 DONE" if win else "SL HIT", "pnl_lot": 2500 if win else -2000, "date": "2026-10-01",
                    "exit_time": f"2026-10-01 {i:06d}", "lot": 1, "entry": 10, "exit": 10, "symbol": f"S{i}"})
    return out


def _nocharges(monkeypatch):
    import krt.ai as ai
    monkeypatch.setattr(ai, "charges", lambda c: 0)


def test_walk_forward_on_with_real_pattern(monkeypatch):
    _nocharges(monkeypatch)
    rng = np.random.default_rng(1)
    _, X, y, net = DS.dataset(_calls(400, rng, True))
    wf = DS.walk_forward(X, y, net)
    assert wf["ok"] and wf["useful"] and wf["best"]["avg"] > wf["base"]["avg"] and wf["auc"] > 0.7


def test_walk_forward_off_on_noise(monkeypatch):
    _nocharges(monkeypatch)
    rng = np.random.default_rng(7)
    _, X, y, net = DS.dataset(_calls(400, rng, False))
    wf = DS.walk_forward(X, y, net)
    assert wf["ok"] and not wf["useful"] and "OFF" in wf["why"]          # luck-ஐ model-ஆ காட்டாது


def test_model_speed_1000(monkeypatch):
    _nocharges(monkeypatch)
    DS.MODEL.update(t=0, m=None)
    t = time.time()
    M = DS.model(_calls(1000, np.random.default_rng(3), True))
    assert time.time() - t < 20 and M["m"] is not None and M["wf"]["ok"]


def test_run_makes_dsk_call_and_notrade(monkeypatch):
    _nocharges(monkeypatch)
    from krt import calls as CL, store as SM
    from tests.test_mannan import FakeStore
    fs = FakeStore()
    for m in (CL, SM):
        monkeypatch.setattr(m, "STORE", fs)
    hist = _calls(300, np.random.default_rng(2), True)
    DS.MODEL.update(t=0, m=None)
    day = "2026-11-09"
    now = pd.Timestamp(f"{day} 11:00")
    live = [{"id": f"L{i}", "date": day, "time": "10:55", "source": "Top Movers", "kind": "MOVERS", "side": "CE", "symbol": f"STK{i}",
             "vol_ratio": 4.5, "grade": "A", "status": "OPEN", "action": "ENTRY", "entry": 10.0, "ltp": 10.2, "sl": 8.0, "targets": [12, 14, 16],
             "lot": 1000, "contract": f"STK{i}CE", "token": str(i), "exch": "NFO", "regime": "TREND UP", "hits": []} for i in range(5)]
    for c in live:
        fs.data["calls"][c["id"]] = c
    oi = {"oi_buildup": {"Long Built Up": [{"symbol": f"STK{i}"} for i in range(5)]}, "index": []}
    st = DS.run(hist + live, oi, now, {"dir": "UP"}, {"regime": "TRENDING", "use": ["Trend / Momentum"]})
    dsk = [c for c in fs.data["calls"].values() if c["kind"] == "DSK"]
    assert len(dsk) == 3 and not st["notrade"]                                            # max 3/day
    assert all(c["entry"] == 10.2 and c["dsk"]["from"].startswith("L") for c in dsk)
    assert st["picks"] and st["picks"][0]["score"] >= 75 and any(p[0] == "🏦 Institutional" for p in st["picks"][0]["parts"])
    # no-trade: இன்று 2 DSK SL
    for c in dsk[:2]:
        c.update(status="SL HIT", pnl_lot=-2500, exit_time=f"{day} 11:30")
    st = DS.run(hist + list(fs.data["calls"].values()), oi, now + pd.Timedelta(minutes=40), {"dir": "UP"}, {"regime": "TRENDING", "use": ["Trend / Momentum"]})
    assert any("SL" in x for x in st["notrade"]) and st["risk"]["lots"] == 0


def test_against_market_lowers_score(monkeypatch):
    _nocharges(monkeypatch)
    ctx = {"model": None, "wf": {}, "oi": {}, "brain": {"use": []}, "sym2sec": {}, "sec_pct": {}, "dir": "DOWN"}
    c = {"side": "CE", "grade": "A", "vol_ratio": 4, "source": "Top Movers", "symbol": "X"}
    s_against, _, _ = DS._rank(c, ctx)
    s_with, _, _ = DS._rank(dict(c, side="PE"), ctx)
    assert s_with - s_against == 25
