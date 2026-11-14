"""🧠 KRT Brain (free, on-server) — blockers · confirmations · TAKE/WATCH/SKIP · gold · picks · ML only if proven · no deadlock."""
import pandas as pd

from krt import brain as BR


def _c(i, **o):
    return {"id": f"d|{i}", "date": "2026-11-11", "time": "10:00", "symbol": f"S{i}", "strike": 100, "side": "CE", "entry": 10.0, "sl": 8.5, "targets": [12, 14, 16],
            "ltp": 10.2, "status": "OPEN", "kind": "MOVERS", "source": "Gamma Unwind Classic", "lot": 100, "vol_ratio": 2.3, "hits": [], **o}


def _hist(src, n, wins, pw=2000, pl=-800):
    return [{"id": f"h{src}{i}", "date": "2026-11-0%d" % (1 + i % 8), "source": src, "kind": "X", "status": "T2 DONE" if i < wins else "SL HIT",
             "pnl_lot": pw if i < wins else pl, "symbol": "Z", "side": "CE"} for i in range(n)]


def test_wilson_small_sample_counts_less():
    assert BR.wilson(5, 5) < BR.wilson(42, 60)                       # 5/5 (100%) < 42/60 (70%) — luck vs proof
    assert BR.wilson(0, 0) == 0.0


def test_blockers_and_take_watch_skip():
    mods = BR.module_table(_hist("Gamma Unwind Classic", 20, 14) + _hist("Weak", 20, 6, 900, -1500))
    assert mods["Gamma Unwind Classic"]["proven"] and not mods["Weak"]["proven"] and mods["Weak"]["exp"] < 0
    good = dict(bp={"score": 86, "breaks": ["prev-day high 95 broken", "prev-week high 98 broken"]}, q={"tier": "PRIORITY", "score": 88},
                chart={"verdict": "TAKE", "mscore": 74}, lab={"verdict": "TAKE"}, guide={"side": "CE", "k": "BUY"}, mods=mods, mdir="UP",
                candles=[{"name": "Bullish engulfing", "side": "UP"}])
    v = BR.verdict(_c(1), **good)
    assert v["decision"] == "TAKE" and v["gold"] and len(v["conf"]) >= 6 and v["say"].startswith("GOLD — TAKE")
    assert BR.verdict(_c(2, ltp=11.0), **good)["block"][0].startswith("late")                         # +10% chase
    assert "near the stop loss" in BR.verdict(_c(3, ltp=8.8), **good)["say"]
    assert "against market direction" in BR.verdict(_c(4), **{**good, "mdir": "DOWN"})["say"]
    assert "loses money" in BR.verdict(_c(5, source="Weak"), **good)["say"]
    nv = BR.verdict(_c(6, vol_ratio=0.8), **{**good, "guide": {}})
    assert nv["decision"] == "SKIP" and "no volume confirmation" in nv["say"]
    weak = BR.verdict(_c(7), bp={"score": 66}, chart={}, mods=mods, mdir="UP")
    assert weak["decision"] in ("WATCH", "SKIP") and not weak["gold"]


def test_run_saves_max_three_with_time_and_push():
    calls = {f"d|{i}": _c(i) for i in range(6)}
    for h in _hist("Gamma Unwind Classic", 20, 14):
        calls[h["id"]] = h
    D = {"calls": calls}
    inp = {"bp_rows": [{"id": f"d|{i}", "score": 88, "breaks": ["prev-day high broken"]} for i in range(6)],
           "charts_table": [{"id": f"d|{i}", "verdict": "TAKE", "mscore": 72} for i in range(6)], "mdir": "UP"}
    sent = []
    new = BR.run(D, pd.Timestamp("2026-11-11 10:40"), inp, lambda m, k, u: sent.append(m))
    assert len(new) == 6 and len(D["brain_picks"]) == 6 and all(p["time"] == "10:40" for p in new)      # v107: no daily cap
    assert len(sent) == 6 and sent[0].startswith(("🧠 BRAIN PICK", "🪙 BRAIN GOLD"))
    assert BR.run(D, pd.Timestamp("2026-11-11 10:41"), inp, None) == []
    rows = BR.STATE["rows"]
    assert rows[0]["decision"] == "TAKE" and len(rows) == 6                                        # every open call gets a verdict
    D["calls"]["d|0"].update(status="T2 DONE", pnl_lot=1500)
    R = BR.report(D, "2026-11-11")
    assert R["stats"]["all"]["n"] == 1 and R["stats"]["all"]["win"] == 100 and len(R["today"]) == 6


def test_ml_used_only_when_walk_forward_proves_it():
    class M_:
        def predict(self, X): return [0.9]
    c = _c(1)
    assert BR.ml_prob(c, {"m": M_(), "wf": {"useful": False}}) is None                              # not proven → ignored
    assert BR.ml_prob(c, {"m": M_(), "wf": {"useful": True}}) == 0.9


def test_brain_run_no_deadlock(monkeypatch):
    import threading
    import server
    server.SNC["t"] = 0
    res = {}
    th = threading.Thread(target=lambda: res.update(out=server.brain_run(pd.Timestamp("2026-11-11 10:30"))), daemon=True)
    th.start()
    th.join(20)
    assert not th.is_alive(), "brain_run deadlocked on CALLS_LOCK"


def _snap_hist(n, predictive, seed=3):
    import random
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        has = rnd.random() < 0.5
        win = (rnd.random() < (0.75 if has else 0.25)) if predictive else (rnd.random() < 0.5)
        out.append({"id": f"h{i}", "date": f"2026-10-{1 + i % 28:02d}", "time": f"{10 + i % 4}:{10 + i % 40}", "status": "T1 DONE" if win else "SL HIT",
                    "pnl_lot": 900 if win else -700, "brain_f": {"score": 0.7, "n_conf": 0.5, "n_block": 0, "n_risk": 0, "mod_win": 0.5,
                                                                **{f"has_{k}": 0.0 for k in BR.SNAP_KEYS}, "has_chart": float(has)}})
    return out


def test_snapshot_learning_honest():
    BR.SNAP.update(t=0)
    assert BR.snap_train(_snap_hist(120, True))["on"] is False                     # < 200 → still learning
    BR.SNAP.update(t=0)
    m = BR.snap_train(_snap_hist(400, True))
    assert m["on"] and m["auc"] >= 0.58                                       # real signal → ON
    p_good = BR.snap_prob({**_snap_hist(1, True)[0]["brain_f"], "has_chart": 1.0}, m)
    p_bad = BR.snap_prob({**_snap_hist(1, True)[0]["brain_f"], "has_chart": 0.0}, m)
    assert p_good > 0.6 > 0.4 > p_bad
    BR.SNAP.update(t=0)
    assert BR.snap_train(_snap_hist(400, False))["on"] is False                    # pure noise → stays OFF (no fake confidence)


def test_snapshot_first_look_only():
    v = {"score": 80, "conf": ["chart 15-method TAKE", "prev-day high broken"], "block": [], "risk": [], "module": {"win": 60}}
    f = BR.snapshot(v)
    assert f["has_chart"] == 1.0 and f["has_broken"] == 1.0 and f["has_footprint"] == 0.0 and f["mod_win"] == 0.6


def test_answer_free_qa():
    BR.STATE["rows"] = [{"symbol": "SBIN", "strike": 1050, "side": "CE", "decision": "TAKE", "score": 84, "say": "TAKE: 3 confirmations", "block": [],
                         "conf": ["chart TAKE", "volume 2.4x"], "risk": []},
                        {"symbol": "CANBK", "strike": 132, "side": "CE", "decision": "SKIP", "score": 40, "say": "SKIP: premium already +9% (late)",
                         "block": ["late"], "conf": [], "risk": []}]
    now = pd.Timestamp("2026-11-11 11:00")
    assert "SBIN 1050 CE" in BR.answer("what should I take now?", now) and "Take now" in BR.answer("what now", now)
    a = BR.answer("why not canbk?", now)
    assert a.startswith("CANBK 132 CE → SKIP") and "Blockers: late" in a
    assert "Only CE setups" in BR.answer("market?", now, {"dir": "UP", "up": 60, "dn": 35})
    BR.STATE["rows"] = []
    assert BR.answer("what to take", now).startswith("Nothing to take right now")
