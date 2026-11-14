"""v100: SL widen (calls varala fix) · footprint Grade B · ⚠ crash radar · 🎯 SQS / integrity."""
import pandas as pd

from tests.test_mannan import FakeStore


def test_sl_widen_instead_of_reject(monkeypatch):
    from krt import calls as CL, store as SM
    fs = FakeStore()
    for m in (CL, SM):
        monkeypatch.setattr(m, "STORE", fs)
    CL.PROVEN.update(t=0, set=set())
    now = pd.Timestamp("2026-11-11 11:00")
    c = {"date": "2026-11-11", "symbol": "INDUSINDBK", "side": "CE", "kind": "INTRADAY", "source": "5-min ORB", "entry": 35.0, "sl": 31.5,   # 10% SL
         "targets": [38.5, 42.0, 45.5], "lot": 700}
    assert CL.quality_v6(c, now) is None                                           # முன்னாடி Q_SL_TIGHT reject
    assert c["sl"] == 29.75 and c["targets"][0] == 40.25 and "10% → 15%" in c["sl_widened"]   # R-multiple அதே (1R → 1R)
    assert c["risk"] == round((35 - 29.75) * 700) and c["risk_ok"] is False         # ₹3,675 > 2,500 → warning
    big = {**c, "sl": 31.5, "targets": [38.5], "lot": 2000, "symbol": "X"}
    assert CL.quality_v6(big, now) is None and big["sl"] == 29.75                  # v107: widened anyway, big risk shown as a warning
    assert big["risk_ok"] is False


def test_footprint_grade_b():
    from krt import footprint as F
    S = {"last": {"ltp": 100.0}, "bars": {1: {}}, "kind": "EQ"}
    an = {"buy_stack": 3, "sell_stack": 0, "delta": 500, "delta_pct": 60.0, "close_pos": 0.8}
    ck = F.checklist("CE", an, 1.22, S, {"mdir": "UP", "hm": "13:24"})
    assert ck["grade"] == "B" and ck["pass"] and 50 <= ck["conf"] <= 95
    assert F.checklist("CE", an, 1.6, S, {"mdir": "UP", "hm": "13:24"})["grade"] == "A"
    assert F.checklist("CE", an, 1.0, S, {"mdir": "UP", "hm": "13:24"})["grade"] is None


def test_crash_radar_escalation_and_outcome():
    from krt import crash as CR
    CR.H.clear(); CR.STATE.update(level="NONE", side=None, history=[], last_push=None)
    t0 = pd.Timestamp("2026-11-11 11:00")
    sent = []
    for i in range(10):                                                             # நிலையான market
        CR.tick({"NIFTY": {"ltp": 25000}, "BANKNIFTY": {"ltp": 60000}}, t0 + pd.Timedelta(minutes=i), {"dn": 40, "up": 55}, None, lambda m, k, u: sent.append(m))
    assert CR.STATE["level"] == "NONE" and not sent
    t1 = t0 + pd.Timedelta(minutes=15)
    st = CR.tick({"NIFTY": {"ltp": 24880}, "BANKNIFTY": {"ltp": 59600}}, t1, {"dn": 70, "up": 25},
                 {"an": {"sell_stack": 3, "delta_pct": -55}}, lambda m, k, u: sent.append(m))
    assert st["level"] == "ALERT" and st["side"] == "DOWN" and len(st["signals"]) >= 3 and sent and sent[0].startswith("🚨 CRASH ALERT")
    CR.tick({"NIFTY": {"ltp": 24870}, "BANKNIFTY": {"ltp": 59550}}, t1 + pd.Timedelta(minutes=2), {"dn": 72}, None, lambda m, k, u: sent.append(m))
    assert len(sent) == 1                                                           # cooldown — spam இல்லை
    CR.tick({"NIFTY": {"ltp": 24800}, "BANKNIFTY": {"ltp": 59400}}, t1 + pd.Timedelta(minutes=16), {"dn": 72}, None, None)
    r = CR.report()
    assert r["history"][0]["after15"] < -0.15 and r["history"][0]["right"] and r["hit"] == 100


def test_sqs_tiers_integrity_calibration():
    from krt import sqs as SQ
    rows = [{"key": k, "agree": 0.8} for k in ("pa", "smc", "sr", "sd", "mtf", "of", "vsa", "vwap", "vp")]
    ch = {"analysis": {"methods": {"rows": rows}, "mtf": {"tf": {"5m": "UP", "15m": "UP", "1H": "UP"}}}}
    c = {"symbol": "X", "side": "CE", "entry": 100, "sl": 85, "lot": 100, "vol_ratio": 2.5, "spread_pct": 0.8, "source": "Top Movers", "kind": "MOVERS"}
    q = SQ.score(c, ch, {"side": "CE", "k": "BUY"}, {"score": 90, "chain": {"verdict": "✅ ok"}}, {"use": ["Trend / Momentum"]}, "UP")
    assert q["tier"] == "PRIORITY" and q["score"] >= 85 and q["lots"] == 1 and q["aligned"] == 4
    weak = SQ.score({**c, "vol_ratio": 0.5, "lot": 500}, None, None, None, {"use": []}, "DOWN")
    assert weak["tier"] == "SKIP" and weak["lots"] == 0 and any(w.startswith("✗") for w in weak["why"])
    now = pd.Timestamp("2026-11-11 11:00:00")
    ig = SQ.integrity(now, "10:59:55", "2026-11-11 10:55:00", "10:58:00", None, None, "2026-11-11 10:59:58", True)
    assert ig["status"] == "HEALTHY"
    assert SQ.integrity(now, "10:40:00", None, "10:58:00", None, None, None, True)["status"] == "BAD"
    cal = SQ.calibrate([{"sqs": {"tier": "PRIORITY"}, "status": "T2 DONE", "pnl_lot": 900}, {"sqs": {"tier": "PRIORITY"}, "status": "SL HIT", "pnl_lot": -500}])
    assert cal["PRIORITY"]["win_rate"] == 50
