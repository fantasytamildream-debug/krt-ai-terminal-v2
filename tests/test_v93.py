"""v93: 🔥 Call of the Day + Top 5 · 📅 Results diary · 🌅 Pre-open · 📊 pattern gate · 🔮 prediction learning."""
import datetime as dt

import numpy as np
import pandas as pd

from tests.test_mannan import FakeStore


def _fs(monkeypatch):
    from krt import calls as CL, store as SM
    fs = FakeStore()
    for m in (CL, SM):
        monkeypatch.setattr(m, "STORE", fs)
    return fs


def test_call_of_day_lock_track_max5(monkeypatch):
    from krt import ailab as AL, daypicks as DP
    fs = _fs(monkeypatch)
    rows = [{"symbol": f"S{i}", "side": "CE", "strike": 100, "expiry": "2026-11-25", "lot": 100, "token": str(i), "exch": "NFO", "contract": f"S{i}CE",
             "entry": 10.0, "ltp": 10.0, "sl": 8.0, "targets": [12.0, 14.0, 16.0], "status": "OK", "confidence": 95 - i, "src": "🏦 OI flow", "why": ["x"]}
            for i in range(7)] + [{"symbol": "WEAKCONF", "side": "CE", "token": "w", "entry": 5, "sl": 4, "targets": [6], "status": "OK", "confidence": 70},
                                 {"symbol": "CHAINBAD", "side": "CE", "token": "c", "entry": 5, "sl": 4, "targets": [6], "status": "OK", "confidence": 99,
                                  "chain": {"verdict": "⛔ CE-க்கு எதிர்"}}]
    monkeypatch.setitem(AL.STATE, "enter", {"rows": rows})
    px = {str(i): 10.0 for i in range(7)}

    class Ag:
        def quotes(self, d):
            return {t: {"ltp": px[t]} for ex, ts in d.items() for t in ts}
    sent = []
    now = pd.Timestamp("2026-11-10 09:45")
    L = DP.run(Ag(), now, [], lambda m, k, u: sent.append(m))
    assert len(L) == 5 and L[0]["cotd"] and L[0]["symbol"] == "S0" and L[0]["conf"] == 95          # max 5, best = Call of the Day
    assert not any(r["symbol"] in ("WEAKCONF", "CHAINBAD") for r in L)                              # conf <80 · chain ⛔ இல்லை
    assert sent[0].startswith("🔥 CALL OF THE DAY · BUY S0") and len(sent) == 5
    px["0"], px["1"] = 12.5, 7.5
    DP.run(Ag(), now + pd.Timedelta(minutes=20), [], None)
    by = {r["symbol"]: r for r in fs.data["day_picks"]["2026-11-10"]}
    assert by["S0"]["status"] == "T1 HIT" and by["S0"]["sl"] == 10.0 and by["S1"]["status"] == "SL HIT" and by["S1"]["pnl_lot"] == -200
    px["0"] = 9.9
    DP.run(Ag(), now + pd.Timedelta(minutes=40), [], None)
    assert by["S0"]["status"] == "TRAIL SL" and by["S0"]["pnl_lot"] == 0                            # T1-க்கு பிறகு entry-ல் exit
    DP.run(Ag(), pd.Timestamp("2026-11-10 15:21"), [], None)
    assert all(r["status"] not in DP.OPEN for r in by.values())
    rep = DP.report(fs.data, "2026-11-10")
    assert rep["cotd"]["n"] == 1 and rep["days"][0]["n"] == 5


def test_news_result_dates():
    from krt.events import news_dates
    today = dt.date(2026, 11, 10)
    items = [{"title": "HAL Q2 results on Nov 12: what to expect", "symbols": ["HAL"]},
             {"title": "Board meeting on 13th November to consider financial results - Grasim", "symbols": ["GRASIM"]},
             {"title": "Nifty rallies 300 points", "symbols": ["NIFTY"]}]
    got = {x["symbol"]: x["date"] for x in news_dates(items, today)}
    assert got == {"HAL": "2026-11-12", "GRASIM": "2026-11-13"}


def test_diary_plan_and_result_day_setup(monkeypatch):
    from krt import events as EV, fullscan as FS
    fs = _fs(monkeypatch)
    EV.add_manual(fs, "HAL", "2026-11-12")
    EV.add_manual(fs, "TATAPOWER", "2026-11-10")
    cl = list(np.linspace(4000, 4300, 30))
    monkeypatch.setattr(FS, "C", {"bars": {"HAL": {"c": cl, "h": [x * 1.01 for x in cl]}, "TATAPOWER": {"c": [400] * 30, "h": [405] * 30}},
                                  "live_q": {"TATAPOWER": {"ltp": 401, "high": 404, "low": 398, "vol_ratio": 1.0}}})
    EV.STATE["r15"] = {}
    now = pd.Timestamp("2026-11-10 09:35")
    rows = {r["symbol"]: r for r in EV.diary(fs, None, {}, now, {}, live=True)}
    assert rows["HAL"]["days"] == 2 and "பெரிய position வேண்டாம்" in rows["HAL"]["plan"]
    assert rows["TATAPOWER"]["days"] == 0 and rows["TATAPOWER"]["setup"]["side"] is None and "404" in rows["TATAPOWER"]["setup"]["txt"]
    FS.C["live_q"]["TATAPOWER"].update(ltp=406, vol_ratio=2.1)
    rows = {r["symbol"]: r for r in EV.diary(fs, None, {}, now + pd.Timedelta(minutes=20), {}, live=True)}
    assert rows["TATAPOWER"]["setup"]["side"] == "CE"                                              # 15-min high 404 மேல் + volume


def test_preopen_selection(monkeypatch):
    from krt import events as EV, fullscan as FS
    monkeypatch.setattr(FS, "C", {"bars": {s: {"c": [100] * 5} for s in ("UP2", "UP6", "DN2", "FLAT")},
                                  "live_q": {"UP2": {"open": 102}, "UP6": {"open": 106}, "DN2": {"open": 98}, "FLAT": {"open": 100.3}}})
    EV.STATE["preopen"] = {"rows": []}
    P = EV.preopen(pd.Timestamp("2026-11-10 09:16"), {"oi_buildup": {"Long Built Up": [{"symbol": "UP2"}]}}, [])
    by = {r["symbol"]: r for r in P["rows"]}
    assert set(by) == {"UP2", "DN2"} and by["UP2"]["side"] == "CE" and by["DN2"]["side"] == "PE"   # 6% gap = chase இல்லை, flat இல்லை
    assert by["UP2"]["score"] > by["DN2"]["score"] and P["src"] == "Angel open"


def test_pattern_gate():
    from krt.chartroom import pattern_gate
    by = {"Head & shoulders": {"dir_n": 4 + 3, "dir_ok": 1}, "Double bottom": {"dir_n": 62, "dir_ok": 60}}
    a = {"pattern": "Head & shoulders", "advice": {"verdict": "TAKE", "text": "x"}}
    g = pattern_gate(a, by)
    assert g["tag"] == "WEAK" and a["advice"]["verdict"] == "WAIT"
    a2 = {"pattern": "Double bottom", "advice": {"verdict": "TAKE"}}
    assert pattern_gate(a2, by)["tag"] == "PROVEN" and a2["advice"]["verdict"] == "TAKE"


def test_prediction_learns_only_if_better():
    from krt import predict as PR
    rng = np.random.default_rng(4)
    L = []
    for i in range(120):                                    # உண்மை: Breadth தான் direction-ஐ சொல்லுது; பழைய rules 50% தப்பு
        b = rng.uniform(-1, 1)
        mv = 0.3 * b + rng.normal(0, 0.05)
        L.append({"sig": {"Breadth": round(b, 2), "PCR": round(rng.uniform(-1, 1), 2)}, "status": "✓" if rng.random() < 0.5 else "✗", "move": mv})
    m = PR.learn(L)
    assert m["use"] and m["acc_new"] > m["acc_old"] and m["w"]["Breadth"] > abs(m["w"]["PCR"])
    noise = [{"sig": {"Breadth": round(rng.uniform(-1, 1), 2)}, "status": "✓" if i % 2 else "✗", "move": float(rng.normal(0, 0.3))} for i in range(120)]
    assert not PR.learn(noise)["use"]                         # pattern இல்லைன்னா கத்துக்கிட்டது-ஐ use பண்ணாது
    assert PR.learn(L[:10])["use"] is False and PR.learn(L[:10])["need"] == 40
