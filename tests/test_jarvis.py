"""🤖 JARVIS — scoring, 5-target planner, validator, Top 10 / Top 3, signal IDs, live tracking, verified performance, Ask."""
import threading

import pandas as pd

from krt import jarvis as JV

DAY = "2026-11-16"
NOW = pd.Timestamp(f"{DAY} 10:30")


def _call(i=0, **o):
    return {"id": f"{DAY}|C{i}", "date": DAY, "time": "10:20", "symbol": o.pop("symbol", "SBIN"), "strike": 1050, "side": "CE", "expiry": "2026-11-25",
            "contract": f"SBIN1050CE{i}", "exch": "NFO", "entry": 20.0, "sl": 18.3, "targets": [26, 30, 34], "ltp": 20.3, "lot": 500, "status": "OPEN",
            "kind": "MOVERS", "source": "5-min ORB", "vol_ratio": 2.4, "spread_pct": 0.8, "ul_price": 1040.0, "ul_sl": 1030.0, "token": "t", **o}


def _chart():
    rows = [{"key": k, "agree": 0.8} for k in ("pa", "smc", "sd", "sr", "vwap", "mtf", "vp", "of")]
    return {"structure": {"trend": "UP", "events": [{"type": "BOS ⬆", "side": "UP", "price": 1038}]}, "methods": {"rows": rows},
            "mtf": {"tf": {"5m": "UP", "15m": "UP", "1H": "UP"}}, "advice": {"verdict": "TAKE"}, "px": 1040.0,
            "sr_up": [{"price": 1046.0}, {"price": 1052.0}], "up_target": 1060.0, "up_level": 1041.0, "liquidity": {"zones": [], "eq": []}}


def _ctx(calls, **o):
    return {"calls": calls, "charts": {"SBIN": _chart()}, "sniper": {c["id"]: {"aligned": 4} for c in calls}, "money_oi": {"SBIN": "Long Built Up"},
            "idx": {}, "enter": {}, "levels": {"SBIN": {"PDH": 1049.0, "PWH": 1068.0, "PMH": 1075.0}}, "live_q": {"SBIN": {"ltp": 1040.0}},
            "mdir": "UP", "crash": {}, "integrity": {"status": "HEALTHY"}, "results": [], "ticks": {}, **o}


def test_score_full_evidence_is_elite_and_missing_data_is_zero():
    c = _call()
    P, why, miss = JV.score(c, _chart(), _ctx([c]))
    assert sum(P.values()) >= 85 and not miss and any("BOS" in w for w in why)
    P2, _, miss2 = JV.score(c, {}, _ctx([c], money_oi={}))
    assert P2["structure"] is None and P2["oi"] is None and {"structure", "trend", "oi", "mtf"} <= set(miss2)     # never guessed


def test_five_targets_from_real_levels_only():
    c = _call()
    pl = JV.plan5(c, _chart(), _ctx([c]))
    T = pl["targets"]
    assert len(T) == 5 and [t["ul"] for t in T] == [1046.0, 1049.0, 1052.0, 1060.0, 1068.0]               # sorted, beyond price, deduped
    assert all(T[i]["prem"] < T[i + 1]["prem"] for i in range(4)) and T[0]["prem"] == round(20 + 0.5 * 6, 2)
    few = JV.plan5(c, {"px": 1040.0, "sr_up": [{"price": 1046.0}]}, _ctx([c], levels={}, live_q={"SBIN": {"ltp": 1040.0}}))
    assert len(few["targets"]) == 1                                                                         # only one real level → only one target
    assert all(t["prem"] > 20 for t in few["targets"])


def test_validator_rejects_late_and_against_market():
    c = _call()
    ok = JV.validate(c, _chart(), JV.plan5(c, _chart(), _ctx([c])), _ctx([c]), NOW)
    assert ok["decision"] == "APPROVE" and not ok["fails"]
    late = _call(ltp=21.5)
    assert "Entry still valid" in JV.validate(late, _chart(), JV.plan5(late, _chart(), _ctx([late])), _ctx([late]), NOW)["fails"]
    v = JV.validate(c, _chart(), JV.plan5(c, _chart(), _ctx([c])), _ctx([c], mdir="DOWN"), NOW)
    assert v["decision"] == "REJECT" and "Market direction" in v["fails"]


def test_scan_top10_elite_max3_and_no_trade():
    calls = [_call(i, strike=1050 + i * 5, contract=f"S{i}") for i in range(5)]
    st = JV.scan(_ctx(calls), NOW)
    assert len(st["top"]) == 5 and len(st["elite"]) == 3 and st["no_trade"] is None and all(r["score"] >= 80 for r in st["elite"])
    st = JV.scan(_ctx(calls, mdir="DOWN"), NOW)
    assert st["elite"] == [] and st["no_trade"].startswith("NO TRADE")
    st = JV.scan(_ctx(calls, integrity={"status": "BAD", "issues": ["Live ticks வரல"]}), NOW)
    assert st["elite"] == [] and st["breaker"].startswith("data feed unhealthy")


def test_publish_signal_id_and_full_lifecycle():
    c = _call()
    D = {"calls": {c["id"]: c}}
    JV.scan(_ctx([c]), NOW)
    new = JV.publish(D, NOW)
    assert len(new) == 1 and new[0]["sid"] == "JV-20261116-001" and new[0]["status"] == "WAITING" and len(new[0]["orig"]["targets"]) == 5
    assert JV.publish(D, NOW) == []                                                                         # no duplicate
    rec = new[0]
    T = rec["orig"]["targets"]
    JV.track(D, NOW)
    assert rec["status"] == "ENTRY CONFIRMED" and rec["entry_px"] == 20.3
    c["ltp"] = T[0] + 0.1
    JV.track(D, NOW + pd.Timedelta(minutes=5))
    assert rec["status"] == "T1 HIT" and rec["sl"] == 20.3 and rec["versions"][0]["change"].endswith("after T1")
    c["ltp"] = T[1] + 0.1
    JV.track(D, NOW + pd.Timedelta(minutes=9))
    assert rec["sl"] == T[0] and rec["orig"]["sl"] == 18.3                                                  # original kept (immutable)
    c["ltp"] = T[0] - 0.2
    JV.track(D, NOW + pd.Timedelta(minutes=14))
    assert rec["status"] == "CLOSED" and rec["exit_px"] == T[0] and rec["net"] < rec["pnl"]                 # costs deducted
    P = JV.performance(D, NOW)
    assert P["triggered"] == 1 and P["wins"] == 1 and P["net"] == rec["net"] and "CE" in P["by_side"] and "Stock" in P["by_type"]


def test_not_triggered_at_eod():
    c = _call(ltp=23.0)
    D = {"calls": {c["id"]: c}}
    JV.STATE["elite"] = [dict(JV.scan(_ctx([_call()]), NOW)["top"][0], ltp=23.0)]
    rec = JV.publish(D, NOW)[0]
    JV.track(D, pd.Timestamp(f"{DAY} 15:21"))
    assert rec["status"] == "NOT TRIGGERED" and JV.performance(D, NOW)["triggered"] == 0


def test_ask_answers_from_scan():
    c = _call()
    JV.scan(_ctx([c]), NOW)
    assert "score" in JV.answer("why did you select SBIN?", NOW)
    assert "at risk per lot" in JV.answer("how much capital is at risk", NOW)
    assert "invalid" in JV.answer("what is the invalidation price", NOW)


def test_jarvis_run_no_deadlock():
    import server
    server.SNC["t"] = 0
    th = threading.Thread(target=lambda: server.jarvis_run(pd.Timestamp(f"{DAY} 10:30")), daemon=True)
    th.start()
    th.join(20)
    assert not th.is_alive(), "jarvis_run deadlocked on CALLS_LOCK"


def test_resistance_too_close_is_rejected():
    c = _call(sl=16.0)                                 # wide 20% stop, first real resistance only +6 points away → RR 1:0.75
    v = JV.validate(c, _chart(), JV.plan5(c, _chart(), _ctx([c])), _ctx([c]), NOW)
    assert v["decision"] == "REJECT" and "Risk-to-reward" in v["fails"]
