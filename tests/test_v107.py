"""v107: no limits · nothing auto-paused · commodity risk = warning · results AI outlook · high-profit box · early rising detector."""
import pandas as pd

from tests.test_mannan import FakeStore


def test_paused_module_still_gives_call_with_warning(monkeypatch):
    from krt import calls as CL, store as SM, ai as AI
    fs = FakeStore()
    for m in (CL, SM):
        monkeypatch.setattr(m, "STORE", fs)
    monkeypatch.setattr(AI, "blocked", lambda c: ("Q_MODULE_PAUSED", "Chart pattern: avg −₹1,484 — auto pause"))
    c = {"date": "2026-11-16", "symbol": "TCS", "side": "CE", "kind": "INTRADAY", "source": "Chart pattern", "entry": 100, "sl": 85, "lot": 100}
    assert CL.quality_v6(c, pd.Timestamp("2026-11-16 11:00")) is None and "auto pause" in c["risk_warn"][0]


def test_optimizer_never_pauses():
    from krt import ai as AI
    src = open("krt/ai.py", encoding="utf-8").read()
    assert 'mods[m]["paused"] = False' in src and AI.AI["max_day"] >= 10 ** 6


def test_no_daily_caps_anywhere():
    from krt import bestpicks, brain, combo, commodity, dsk, footprint, mannan, newsradar, fullscan, calls
    assert min(bestpicks.CFG["max_day"], brain.CFG["max_day"], combo.CFG["max_day"], commodity.CFG["max_day"], dsk.CFG["max_day"],
               footprint.CFG["max_day"], newsradar.CFG["max_day"], fullscan.MACHINE["max_calls"], fullscan.STRONG["max_day"],
               calls.QV6["max_day"], calls.QV6["idx_max"], *[v["max_day"] for v in mannan.SEG.values()]) >= 10 ** 6


def test_results_outlook():
    from krt import events as EV
    cl = [100 * (1.004 ** i) for i in range(60)]                    # steady up-trend
    row = {"r20": 8.5, "near_high": True, "oi": "Long Built Up", "implied": {"pct": 4.0}}
    o = EV.outlook(row, cl, [{"reaction": 3.1}, {"reaction": 2.0}, {"reaction": -1.0}])
    assert o["lean"] == "LEAN UP" and o["side"] == "CE" and any("past results: 2/3" in w for w in o["why"]) and "IV crush" in o["watch"]
    weak = EV.outlook({"r20": -9, "near_high": False, "oi": "Short Built Up", "implied": {"pct": 3}}, [100 * (0.995 ** i) for i in range(60)], [])
    assert weak["lean"] == "LEAN DOWN" and "bounce" in (weak["warn"] or "")


def test_high_profit_modules_and_today_calls():
    from krt import highprofit as HP
    day = "2026-11-16"
    old = [{"id": f"s{i}", "date": "2026-11-05", "source": "V4 ⚡ ICT Silver Bullet", "status": "T1 DONE" if i % 6 else "SL HIT", "pnl_lot": 900 if i % 6 else -1500}
           for i in range(12)] + [{"id": f"b{i}", "date": "2026-11-05", "source": "Chart pattern", "status": "SL HIT", "pnl_lot": -1000} for i in range(12)]
    today = [{"id": "t1", "date": day, "time": "10:31", "symbol": "NIFTY", "strike": 25300, "side": "CE", "source": "V4 ⚡ ICT Silver Bullet", "status": "OPEN",
              "entry": 120, "sl": 105, "targets": [140, 160, 180], "ltp": 128, "pnl_lot": 520},
             {"id": "t2", "date": day, "time": "10:40", "symbol": "TCS", "side": "CE", "source": "Chart pattern", "status": "OPEN"}]
    R = HP.report({"calls": {c["id"]: c for c in old + today}}, day, [{"id": "t1", "state": "RISING", "chg3m": 5.0}])
    assert [m["module"] for m in R["modules"]] == ["V4 ⚡ ICT Silver Bullet"] and R["modules"][0]["win"] == 83
    assert [c["id"] for c in R["today"]] == ["t1"] and R["today"][0]["rising"]["state"] == "RISING"


def test_riser_detects_climb_once():
    from krt import riser as RS
    RS.H.clear(); RS.LAST.clear(); RS.STATE["alerts"] = []
    t0 = pd.Timestamp("2026-11-16 10:30:00")
    c = {"id": "x", "date": "2026-11-16", "symbol": "SBIN", "strike": 1050, "side": "CE", "status": "OPEN", "entry": 25.0, "targets": [30, 33, 36], "ltp": 25.0}
    sent = []
    for i, px in enumerate([25.0, 25.2, 25.6, 26.1, 26.5]):          # +6% in ~80 s, every step up
        c["ltp"] = px
        new = RS.scan([dict(c)], t0 + pd.Timedelta(seconds=20 * i), lambda m, k, u: sent.append(m))
    assert len(RS.STATE["alerts"]) == 1 and RS.STATE["alerts"][0]["state"] == "RISING" and sent and sent[0].startswith("🚀 RISING")
    c["ltp"] = 26.7
    RS.scan([dict(c)], t0 + pd.Timedelta(seconds=120), None)
    assert len(RS.STATE["alerts"]) == 1                                # no spam
    flat = dict(c, id="y", ltp=25.0)
    RS.H.clear()
    for i in range(6):
        RS.scan([dict(flat)], t0 + pd.Timedelta(seconds=20 * i), None)
    assert not any(a["id"] == "y" for a in RS.STATE["alerts"])


def test_commodity_risk_is_warning_not_block():
    src = open("krt/commodity.py", encoding="utf-8").read()
    assert 'b["risk_warn"] = f"⚠ risk' in src and 'c["shadow"] = False' in src
