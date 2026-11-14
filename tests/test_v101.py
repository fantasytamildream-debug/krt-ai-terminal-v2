"""v101: 🤖 AI Best Picks + 🪙 Golden · strike history · ⚡ Silver Bullet regime fix."""
import pandas as pd

from krt import bestpicks as BP


def _c(i, **o):
    return {"id": f"d|{i}", "date": "2026-11-11", "time": "10:00", "symbol": f"S{i}", "side": "CE", "strike": 100, "entry": 10.0, "sl": 8.5, "targets": [12, 14, 16],
            "ltp": 10.2, "status": "OPEN", "kind": "MOVERS", "source": "Top Movers", "lot": 100, "vol_ratio": 2.4, "hits": [], **o}


def test_score_golden_and_penalties():
    lv = {"PDH": 95, "PWH": 98, "PMH": 120}
    r = BP.score_one(_c(1), {"score": 80}, {"verdict": "TAKE", "mscore": 74}, {"verdict": "TAKE"}, lv, 100, {"side": "CE", "k": "BUY"}, False)
    assert r["score"] >= 88 and r["golden"] and len(r["breaks"]) == 2 and r["state"] == "ENTER"
    late = BP.score_one(_c(2, ltp=11.0), {"score": 80}, {"verdict": "TAKE"}, None, lv, 100, None, False)
    assert late["state"].startswith("LATE") and not late["golden"]
    nsl = BP.score_one(_c(3, ltp=8.8), {"score": 90}, {"verdict": "TAKE"}, {"verdict": "TAKE"}, lv, 100, None, True)
    assert nsl["state"] == "NEAR SL" and nsl["score"] < 75
    bad = BP.score_one(_c(4), {"score": 80}, {"verdict": "AVOID"}, {"verdict": "SKIP"}, lv, 90, {"side": "PE", "k": "BUY"}, False)
    assert bad["score"] < 60 and "chart says AVOID" in bad["why"]


def test_run_saves_picks_with_time_and_results():
    calls = {f"d|{i}": _c(i) for i in range(9)}
    calls["old"] = _c(9, id="old", date="2026-11-05", symbol="S0", status="T2 DONE", hits=["T1 10:20", "T2 10:40"], pnl_lot=900)
    calls["old2"] = _c(10, id="old2", date="2026-11-06", symbol="S0", status="SL HIT", pnl_lot=-400)
    D = {"calls": calls}
    sq = [{"id": f"d|{i}", "score": 82} for i in range(9)]
    ct = [{"id": f"d|{i}", "verdict": "TAKE", "mscore": 70} for i in range(9)]
    sent = []
    now = pd.Timestamp("2026-11-11 10:30")
    new = BP.run(D, now, sq, ct, {}, {f"S{i}": {"PDH": 95} for i in range(9)}, {f"S{i}": {"ltp": 100} for i in range(9)}, {}, set(), lambda m, k, u: sent.append(m))
    J = D["best_picks"]
    assert len(new) == 9 and len(J) == 9 and all(p["time"] == "10:30" for p in J.values())                       # v107: no daily cap
    p0 = J["d|0"]
    assert p0["hist"]["all"]["n"] == 2 and p0["hist"]["all"]["t1"] == 1 and p0["hist"]["all"]["sl"] == 1             # strike history
    assert len(sent) == 9 and sent[0].startswith(("🤖 AI BEST PICK", "🪙 GOLDEN CALL"))
    assert BP.run(D, now + pd.Timedelta(minutes=1), sq, ct, {}, {}, {}, {}, set(), None) == []                     # duplicates இல்லை
    D["calls"]["d|0"].update(status="T3 DONE", pnl_lot=1200)
    R = BP.report(D, "2026-11-11")
    assert R["today"] and R["stats"]["all"]["n"] == 1 and R["stats"]["all"]["win"] == 100


def test_silver_bullet_called_in_any_regime():
    src = open("krt/v4.py", encoding="utf-8").read()
    i = src.index("pref = list(PREFERRED.get(reg, []))")
    blk = src[i:i + 600]
    assert '(res.get("SILVER") or {}).get("stage") == "CONFIRMED"' in blk and 'pref.append("SILVER")' in blk
