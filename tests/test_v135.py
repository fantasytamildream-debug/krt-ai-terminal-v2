"""v135: 🧠 Market Behaviour Brain (memory → similar moments → what happened next, learns daily) · crash + big players in /api/ticks."""
import json

import numpy as np
import pandas as pd

import server as S
from krt import behaviour as B


def _mk(seed, base, days, planted=True):
    r = np.random.default_rng(seed)
    rows, px = [], base
    for d in days:
        px *= 1 + r.normal(0, 0.004)
        push = 0
        for i, t in enumerate(pd.date_range(d + pd.Timedelta(hours=9, minutes=15), periods=75, freq="5min")):
            o = px
            shock = -0.004 if planted and i in (20, 21, 22) and r.random() < 0.5 else 0
            if shock:
                push = 12                                  # planted behaviour: after a fast fall, it keeps falling for an hour
            drift = -0.0008 if push > 0 else 0
            push -= 1
            px *= 1 + r.normal(drift, 0.0008) + shock
            rows.append((t, o, max(o, px) * 1.0003, min(o, px) * 0.9997, px))
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"]).set_index("time")


DAYS = pd.bdate_range("2026-08-17", "2026-11-23")


def test_features_and_outcomes():
    N = _mk(1, 25000, DAYS[:5])
    F = B.features(N)
    d0 = F[F["date"] == str(DAYS[1].date())]
    assert len(d0) == 75 and abs(d0["tod"].iloc[0] - 5 / 375) < 1e-9
    assert d0["maxdn"].iloc[-1] != d0["maxdn"].iloc[-1]          # last candle: future unknown → NaN
    assert (d0["pos"].between(0, 1)).all() and (d0["offhi"] <= 1e-9).all() and (d0["offlo"] >= -1e-9).all()
    i = 10
    c = N.loc[d0.index[i], "close"]
    fut = N.loc[d0.index[i + 1]:d0.index[i + 12], "low"].min()
    assert abs(d0["maxdn"].iloc[i] - (fut / c - 1) * 100) < 1e-6


def test_brain_learns_planted_behaviour():
    N = _mk(3, 25000, DAYS)
    H, Z = B.prepare(B.features(N))
    fast_fall = H[(H["r15"] <= -0.6) & (H["tod"] < 0.4)].iloc[0]
    quiet = H[(H["r30"].abs() < 0.05)].iloc[0]
    a, q = B.answer(H, Z, fast_fall, "speed", 40), B.answer(H, Z, quiet, "speed", 40)
    assert a["dn"] > q["dn"] + 15 and a["dn"] > a["base"]["dn"]
    tu = B.tune(H, Z, days=10, step=4)
    assert tu["skill"] is not None and tu["skill"] > 0 and tu["wset"] in B.WSETS


def test_live_answer_uses_closed_candles_and_other_days_only():
    N = _mk(5, 25000, DAYS)
    hist = N[N.index.date < DAYS[-1].date()]
    B.M["hist"] = {"NIFTY": B.prepare(B.features(hist))}
    B.M["raw"] = {"NIFTY": hist}
    B.M["tuned"] = {"wset": "speed", "k": 40}
    today = N[N.index.date == DAYS[-1].date()].iloc[:30]
    now = today.index[-1] + pd.Timedelta(minutes=2)              # last candle still forming
    A = B.live("NIFTY", today, None, now)
    assert A["bar"] == today.index[-2].strftime("%H:%M") and A["verdict"] in ("CRASH RISK", "RALLY CHANCE", "DOWN", "UP", "MIXED")
    assert A["p"]["n"] == 40 and A["head"] and "·" in A["pattern"]


class _St:
    def __init__(self):
        self.d, self.dirty = {}, False

    def load(self):
        return self.d


def test_track_record():
    st = _St()
    N = _mk(7, 25000, DAYS[-1:], planted=False)
    t0 = pd.Timestamp(str(DAYS[-1].date()) + " 10:00")
    spot = float(N.loc[t0, "close"])
    B.track({"name": "NIFTY", "spot": spot, "verdict": "DOWN", "p": {"dn": 60, "up": 20, "fall": 70, "rise": 30}}, st, t0, N)
    out = B.track(None, st, t0 + pd.Timedelta(minutes=65), N)
    p = st.d["behav_log"][0]
    assert p["status"] == "DONE" and out["n"] == 1
    r = (float(N[(N.index >= t0) & (N.index < t0 + pd.Timedelta(minutes=60))]["close"].iloc[-1]) / spot - 1) * 100
    assert p["ok"] == (r <= -0.2) and p["wrong"] == (r >= 0.2)


class F(S.H):
    def __init__(self, path):
        self.path, self.headers, self.out = path, {}, {}

    def _send(self, code, body, ctype=None):
        self.out = {"code": code, "body": body}


def test_ticks_carry_crash_and_big_and_behaviour_endpoint():
    from krt import bigvol as BV, crash as CR
    CR.STATE.update(level="WATCH", side="DOWN", signals=["NIFTY 5 நிமிடத்தில் -0.45%"], time="09:28:00")
    td = S.now_ist().strftime("%Y-%m-%d")
    BV.EARLY["TCS|10:15"] = {"symbol": "TCS", "date": td, "time": "10:15", "full": td + " 10:15:30", "side": "SELL", "mult": 6.2, "early": True,
                             "opt": {"strike": 2480, "side": "PE"}}
    try:
        f = F("/api/ticks")
        f.do_GET()
        d = json.loads(f.out["body"])
        assert d["crash"]["level"] == "WATCH" and d["crash"]["side"] == "DOWN"
        assert any(b["symbol"] == "TCS" and b["early"] and b["strike"] == 2480 for b in d["big"])
    finally:
        BV.EARLY.pop("TCS|10:15", None)
        CR.STATE.update(level="NONE", side=None, signals=[])
    g = F("/api/behaviour")
    g.do_GET()
    assert "answers" in json.loads(g.out["body"])
