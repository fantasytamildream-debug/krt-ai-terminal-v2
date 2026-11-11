"""v95: 🧠 15 chart methods · regime weights · learning · all calls → Chart Room · entry-now."""
import numpy as np
import pandas as pd

from krt import chartroom as CR
from krt import methods as MT


def _df(kind, n=150, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-11-09 09:15", periods=75, freq="5min").append(pd.date_range("2026-11-10 09:15", periods=n - 75, freq="5min"))
    if kind == "up":
        c = 100 + np.cumsum(rng.normal(0.12, 0.25, n))
    else:
        c = 100 + np.sin(np.arange(n) / 4) * 1.2 + rng.normal(0, 0.15, n)
    o = np.r_[c[0], c[:-1]]
    h, l = np.maximum(o, c) + rng.uniform(0.05, 0.3, n), np.minimum(o, c) - rng.uniform(0.05, 0.3, n)
    v = rng.uniform(800, 1200, n) * (1 + (np.diff(np.r_[c[0], c]) > 0) * 0.5)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


def test_all_15_methods_run_without_error():
    for kind in ("up", "side"):
        df = _df(kind)
        a = CR.analyse(df)
        M = MT.run_all(df, a, "CE", {"nifty_ret": 0.1})
        assert len(M["rows"]) == 15 and not [r for r in M["rows"] if r["txt"].startswith("பிழை")], [r["txt"] for r in M["rows"] if r["txt"].startswith("பிழை")]
        assert 0 <= M["score"] <= 100 and M["verdict"] in ("TAKE", "WAIT", "AVOID") and len(M["focus"]) == 5


def test_trend_up_ce_vs_pe():
    df = _df("up")
    a = CR.analyse(df)
    ce, pe = MT.run_all(df, a, "CE", {"nifty_ret": 0.0}), MT.run_all(df, a, "PE", {"nifty_ret": 0.0})
    assert ce["score"] > 60 and pe["score"] < 40 and ce["score"] + pe["score"] == 100
    assert pe["verdict"] != "TAKE" and len(ce["pro"]) >= 4


def test_regime_changes_weights():
    df = _df("up")
    a = CR.analyse(df)
    a["regime"] = {"kind": "SIDEWAYS"}
    w_side = {r["key"]: r["weight"] for r in MT.run_all(df, a, "CE")["rows"]}
    a["regime"] = {"kind": "TRENDING UP"}
    w_tr = {r["key"]: r["weight"] for r in MT.run_all(df, a, "CE")["rows"]}
    assert w_side["vp"] > w_tr["vp"] and w_tr["mtf"] > w_side["mtf"]          # sideways = Volume Profile · trend = MTF


def test_method_learning_multiplier():
    preds = [{"broke": "UP", "votes": {"pa": 0.8, "ew": -0.6}} for _ in range(20)]
    st = MT.method_stats(preds)
    assert st["pa"]["acc"] == 100 and st["pa"]["mult"] == 1.5 and st["ew"]["acc"] == 0 and st["ew"]["mult"] == 0.5
    df = _df("up")
    a = CR.analyse(df)
    r = {x["key"]: x for x in MT.run_all(df, a, "CE", {}, st)["rows"]}
    r0 = {x["key"]: x for x in MT.run_all(df, a, "CE", {}, {})["rows"]}
    assert r["pa"]["weight"] > r0["pa"]["weight"] and r["ew"]["weight"] < r0["ew"]["weight"]


def test_wyckoff_spring_and_vsa():
    df = _df("side")
    lo = float(df["low"].iloc[-40:-5].min())
    df.iloc[-2, df.columns.get_loc("low")] = lo - 0.6
    df.iloc[-1, df.columns.get_loc("close")] = lo + 0.4
    df.iloc[-1, df.columns.get_loc("open")] = lo + 0.1
    a = CR.analyse(df)
    w = MT.m_wy(df, a, {})
    assert w["vote"] > 0.5 and "Spring" in w["txt"]


def test_pick_calls_all_kinds_and_entry_now():
    day = "2026-11-10"
    mk = lambda s, **o: {"id": s, "symbol": s, "date": day, "status": "OPEN", "kind": "MOVERS", "time": "10:00", **o}
    calls = [mk("GOLD", exch="MCX", kind="MCX"), mk("NIFTY", kind="V4"), mk("A", pink={"tier": "dark"}), mk("B", kind="PICK"), mk("C", status="SL HIT")]
    got = [c["symbol"] for c in CR.pick_calls(calls, day)]
    assert got[0] == "A" and "GOLD" in got and "NIFTY" in got and "B" not in got and "C" not in got
    c = {"status": "OPEN", "entry": 10, "sl": 8, "ltp": 10.2, "side": "CE"}
    assert CR.entry_now(c, "TAKE")["k"] == "ENTER" and CR.entry_now(c, "WAIT")["k"] == "WAIT" and CR.entry_now(c, "AVOID")["k"] == "SKIP"
    assert CR.entry_now({**c, "ltp": 11.2}, "TAKE")["k"] == "LATE" and CR.entry_now({**c, "ltp": 7.9}, "TAKE")["k"] == "SKIP"
    assert CR.entry_now({**c, "ltp": 11.2}, "AVOID")["k"] == "SKIP"            # chart எதிர் + ஓடிடுச்சு → SKIP (LATE இல்லை)
    assert CR.entry_now({**c, "hits": ["T1 10:30"]}, "TAKE")["k"] == "HOLD" and CR.entry_now({**c, "status": "T3 DONE"}, "TAKE")["k"] == "DONE"


def test_run_once_charts_all_calls_and_table(monkeypatch):
    from tests.test_mannan import FakeStore
    fs = FakeStore()
    day = "2026-11-10"
    mk = lambda s, **o: {"id": f"{day}|{s}", "symbol": s, "date": day, "status": "OPEN", "kind": "MOVERS", "time": "10:00", "side": "CE", "strike": 100,
                         "entry": 10.0, "sl": 8.0, "targets": [12, 14, 16], "ltp": 10.1, "lot": 100, "hits": [], **o}
    fs.data["calls"] = {c["id"]: c for c in [mk(f"S{i}") for i in range(14)] + [mk("GOLD", exch="MCX", kind="MCX"), mk("DONE1", status="T3 DONE", pnl_lot=600)]}

    class Ag:
        def candles(self, ex, tok, iv, a, b):
            return _df("up")
    inst = {"eq": {f"S{i}": str(i) for i in range(14)}, "mcx_fut": {"GOLD": ["g1"]}}
    CR.run_once(Ag(), inst, fs, pd.Timestamp(f"{day} 12:00"))
    ch = CR.STATE["charts"]
    assert len(ch) == 12 and all("methods" in x["analysis"] for x in ch)                       # max 12 charts
    syms = {x["call"]["symbol"] for x in ch}
    assert "GOLD" in syms or len([c for c in fs.data["calls"].values() if c["status"] == "OPEN"]) > 12
    T = CR.STATE["calls_table"]
    assert len(T) == 16 and any(r["symbol"] == "DONE1" and r["now"]["k"] == "DONE" for r in T)   # முடிந்தவையும் table-ல்
    r = next(r for r in T if r["charted"])
    assert r["mscore"] is not None and r["verdict"] in ("TAKE", "WAIT", "AVOID") and r["now"]["k"] in ("ENTER", "WAIT", "SKIP", "LATE")
    p = next(iter(fs.data["chart_preds"].values()))
    assert p.get("votes") and len(p["votes"]) == 15


def test_forecast_path_and_real_history_confidence():
    df = _df("up")
    a = CR.analyse(df)
    a["methods"] = MT.run_all(df, a, "CE")
    v = a["methods"]["votes"]
    hist = [{"status": "TARGET ✓", "broke": "UP", "votes": v, "pattern": "x"} for _ in range(12)] + \
           [{"status": "FAILED", "broke": "UP", "votes": {k: -x for k, x in v.items()}, "pattern": "x"} for _ in range(30)]
    f = MT.forecast(a, "CE", hist, k=20)
    assert f["tp"] > f["px"] > f["sl"] and f["path"][0]["y"] == f["px"] and f["path"][-1]["y"] == f["tp"] and f["path"][-1]["w"] > f["path"][1]["w"]
    assert f["matches"] == 20 and f["hits"] == 12 and f["conf"] == 60 and "15-method" in f["how"]     # nearest = similar votes முதலில்
    f2 = MT.forecast(a, "CE", [], k=20)
    assert f2["matches"] == 0 and f2["conf"] is None and f2["small"]                                 # history இல்லைன்னா fake % இல்லை
    pe = MT.forecast(a, "PE", hist)
    assert pe["tp"] < pe["px"] < pe["sl"]


def test_setups_added_to_chart_room(monkeypatch):
    from krt import ailab as AL, combo as CB, daypicks as DP
    monkeypatch.setitem(DP.STATE, "today", [{"symbol": "MM", "side": "CE", "strike": 3350, "entry": 90, "sl": 62, "targets": [130], "ltp": 92, "status": "OPEN", "cotd": True, "time": "09:34", "token": "t"}])
    monkeypatch.setitem(AL.STATE, "enter", {"rows": [{"symbol": "CUB", "side": "CE", "status": "OK", "confidence": 94, "strike": 230, "entry": 8.3, "sl": 6.85, "ltp": 8.0, "src": "OI flow"},
                                                    {"symbol": "LOW", "side": "CE", "status": "OK", "confidence": 50}]})
    monkeypatch.setitem(CB.STATE, "rows", [{"symbol": "BEL", "side": "PE", "score": 5, "time": "10:00"}, {"symbol": "MM", "side": "CE", "score": 6}])
    S = CR.pick_setups({"NIFTY"}, "2026-11-11", 10)
    assert [x["symbol"] for x in S] == ["MM", "CUB", "BEL"] and all(x["is_setup"] for x in S)          # dedupe · conf 70+ மட்டும்
    assert S[0]["source"] == "🔥 Call of the Day" and CR.pick_setups({"NIFTY"}, "2026-11-11", 1)[0]["symbol"] == "MM"
    assert CR.entry_now(S[2], "TAKE")["txt"].startswith("Setup மட்டும்")
    assert CR.entry_now(S[1], "TAKE")["k"] == "ENTER"
