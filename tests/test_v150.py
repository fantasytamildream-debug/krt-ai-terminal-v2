"""v150: World Top Strategies engine · score rules · walk-forward gating · lookup / desk / best-pick times."""
import numpy as np
import pandas as pd
import server as S
from krt import worldtop as W


def _frame(days=6, drift=0.0, seed=3, last_break=None):
    rng = np.random.default_rng(seed)
    idx = []
    for d in pd.bdate_range("2026-11-16", periods=days):
        idx += list(pd.date_range(d + pd.Timedelta("9h15min"), d + pd.Timedelta("15h25min"), freq="5min"))
    idx = pd.DatetimeIndex(idx)
    r = rng.normal(drift, 0.0008, len(idx))
    c = 1000 * np.exp(np.cumsum(r))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * 1.0004
    l = np.minimum(o, c) * 0.9996
    v = rng.integers(1000, 2000, len(idx)).astype(float)
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v}, index=idx)


def test_orb_and_vwap_momentum_fire_on_breakout():
    d = _frame()
    day = d.index[-1].normalize()
    T = d[d.index >= day]
    d = d[d.index < day + pd.Timedelta("9h55min")]            # cut today at 09:50 — break just happened
    t_idx = d.index[d.index >= day]
    base = float(d.loc[t_idx[0], "open"])
    # quiet opening range then a strong push up on volume
    for i, ts in enumerate(t_idx):
        px = base * (1 + (0.0005 * (i % 2) if i < 6 else 0.002 * (i - 5)))
        d.loc[ts, ["open", "high", "low", "close"]] = [px * 0.999, px * 1.001, px * 0.998, px]
        d.loc[ts, "volume"] = 1500 if i < 6 else 6000
    ev = W.evaluate(d, None, is_index=False)
    assert ev and "orb" in ev["signals"] and ev["signals"]["orb"]["side"] == "CE"
    assert ev["signals"]["orb"]["inv"] < ev["X"]["px"]


def _ev_with(sig_side="CE", keys=("orb",)):
    d = _frame()
    X = W.context(d)
    sigs = {k: {"side": sig_side, "inv": X["px"] * 0.99, "why": "test", "trigger": X["px"]} for k in keys}
    return {"regime": "BREAKOUT", "info": {}, "signals": sigs, "allowed": list(keys), "off": {}, "X": X}


PLAN = {"entry": 50, "entry_zone": [50, 51], "sl": 45, "targets": [57.5, 60, 65], "risk_lot": 2000, "rr_t2": 2.0, "spread_pct": 1.0, "lot": 400}


def test_score_counts_only_walk_forward_approved_methods():
    ev = _ev_with(keys=("orb", "vwap_mom"))
    ext = {"nifty_pct": 0.5, "plan": PLAN, "plan_bad": None, "terminal": ["Index OI"], "terminal_opp": [], "rvol": 2}
    on = W.score(ev, "CE", ext, {"orb": "on", "vwap_mom": "on"})
    W.CFG["mode"] = "strict"
    try:
        unt = W.score(ev, "CE", ext, {"orb": "untested", "vwap_mom": "untested"})
    finally:
        W.CFG["mode"] = "all"
    assert on["parts"]["global"] == 18 and unt["parts"]["global"] == 0
    assert unt["reject"] and "no global method" in unt["reject"]
    allm = W.score(ev, "CE", ext, {"orb": "untested", "vwap_mom": "weak"})       # v151 default: all methods live
    assert allm["parts"]["global"] == 18


def test_score_rejects_risk_spread_and_conflict():
    ev = _ev_with(keys=("orb",))
    big = dict(PLAN, risk_lot=4200)
    r = W.score(ev, "CE", {"plan": big, "plan_bad": "1-lot risk ₹4,200 > ₹2,500"}, {"orb": "on"})
    assert r["reject"] and "2,500" in r["reject"]
    r = W.score(ev, "CE", {"plan": dict(PLAN, spread_pct=5.0), "plan_bad": None}, {"orb": "on"})
    assert "spread" in r["reject"]
    ev2 = _ev_with(keys=("orb",))
    ev2["signals"]["ict"] = {"side": "PE", "inv": 1, "why": "x", "trigger": 1}
    ev2["allowed"].append("ict")
    r = W.score(ev2, "CE", {"plan": PLAN, "plan_bad": None}, {"orb": "on", "ict": "on"})
    assert r["reject"] and "conflict" in r["reject"]
    # correlated terminal source (5-min ORB = same idea as the ORB method) is not counted twice
    r = W.score(ev, "CE", {"plan": PLAN, "plan_bad": None, "terminal": ["5-min ORB"]}, {"orb": "on"})
    assert r["parts"]["terminal"] == 0


def test_bands():
    assert W.band(96) == "ELITE SETUP" and W.band(91) == "A+ SETUP" and W.band(86) == "A GRADE SETUP" and W.band(70).startswith("WATCHLIST")


def test_walk_forward_gate():
    good = [{"d": f"2026-0{1 + i // 30}-{1 + i % 28:02d}", "r": 2.0 if i % 2 else -1.0, "rg": "TRENDING"} for i in range(60)]
    bad = [{"d": r["d"], "r": -1.0, "rg": "SIDEWAYS"} for r in good]
    res, en = W.walk_forward({"orb": good, "ict": bad, "darvas": []})
    assert en["orb"] == "on" and en["ict"] == "weak" and en["darvas"] == "untested"
    assert res["orb"]["oos"]["trades"] > 0 and "TRENDING" in res["orb"]["regime"]


def test_regime_disables_unsuitable():
    assert "orb" not in W.REGIME_OK["SIDEWAYS"] and "vwap_mr" in W.REGIME_OK["SIDEWAYS"] and "turtle" in W.REGIME_OK["TRENDING"]


def test_backtest_runs_on_history():
    d = _frame(days=30, drift=0.00005)
    out, comb = W.backtest_intraday({"NIFTY": d}, step_min=30, max_days=20)
    assert set(out) == set(W.FN)
    assert all(isinstance(v, list) for v in out.values())


def test_worldtop_state_and_lookup_unknown(monkeypatch):
    st = S.worldtop_state()
    assert len(st["methods"]) == 14 and "regime_map" in st
    monkeypatch.setattr(S, "load_inst", lambda p: {"eq": {"VBL": "1"}, "mcx_fut": {"GOLD": ["9"]}})
    S.LKC.clear()
    r = S.lookup_state("ZZZQ")
    assert r["ok"] is False and "not found" in r["msg"]


def test_lookup_known_symbol(monkeypatch):
    d = _frame(days=5)
    monkeypatch.setattr(S, "load_inst", lambda p: {"eq": {"VBL": "1"}, "mcx_fut": {}})
    monkeypatch.setattr(S, "angel_configured", lambda: True)

    class A:
        def candles(self, *a, **k):
            return d
    monkeypatch.setattr(S, "get_angel", lambda: A())
    monkeypatch.setattr(S, "fit_option", lambda *a, **k: None)
    S.LKC.clear()
    S.WT["frames"].pop("VBL", None)
    r = S.lookup_state("vbl")
    assert r["ok"] and r["symbol"] == "VBL" and len(r["candles"]) > 50 and len(r["methods"]) == 14
    assert "success" in r and r["jackpot"] in (True, False)


def test_best_pick_has_times(monkeypatch):
    from krt import fullscan as FSm, bigvol as BV
    day = str(S.now_ist().date())
    monkeypatch.setitem(FSm.C, "live_q", {})
    monkeypatch.setitem(S.STATE, "full", {"money": {"sectors": []}})
    monkeypatch.setattr(S, "opt_quotes", lambda items: {})
    S.MNTOP.clear()
    rows = [{"id": "a", "time": "12:21", "status": "OPEN", "verdict": "TAKE", "symbol": "AAA", "side": "CE", "token": "T1", "exch": "NFO", "src": "x"}]
    best = S._mn_rank(rows, {"a": {"source": "x"}}, None, {}, day)
    assert best[0]["came"] == "12:21" and best[0]["top_since"]


def test_v151_all_methods_live_and_commodity_normalised():
    ev = _ev_with(keys=("orb",))
    PL = dict(PLAN)
    r = W.score(ev, "CE", {"plan": PL, "plan_bad": None}, {"orb": "weak"})
    assert r["parts"]["global"] == 9 and any("backtest weak" in w for w in r["warn"])
    ext = {"plan": PL, "plan_bad": None, "is_index": True, "market": "COMMODITY"}
    rc = W.score(ev, "CE", ext, {"orb": "on"})
    rs = W.score(ev, "CE", dict(ext, market="STOCK", is_index=False), {"orb": "on"})
    assert rc["possible"] == 87 and rc["total"] == round(rc["raw"] * 100 / 87)
    res, en = W.walk_forward({"orb": [{"d": f"2026-01-{1 + i:02d}", "r": (-1.0 if i < 15 else 2.0), "rg": "X"} for i in range(25)]})
    assert en["orb"] == "recent"
