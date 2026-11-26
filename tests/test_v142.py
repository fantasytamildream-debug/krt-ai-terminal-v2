"""v142: 🔱 KRT TRIDENT AI — triple market alpha engines (index · stock · commodity), risk filters, walk-forward backtest."""
import json

import numpy as np
import pandas as pd

import server as S
from krt import trident as T


def _d5(days, drift=0.0, seed=1, start=25000.0):
    rng = np.random.default_rng(seed)
    rows, px = [], start
    for d in days:
        for t in pd.date_range(d + pd.Timedelta(hours=9, minutes=15), periods=75, freq="5min"):
            o = px
            px *= 1 + rng.normal(drift, 0.0009)
            rows.append((t, o, max(o, px) * 1.0003, min(o, px) * 0.9997, px))
    return pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"]).set_index("time")


DAYS = pd.bdate_range("2026-10-01", "2026-11-25")


def test_resample_keeps_only_complete_bars():
    d = _d5(DAYS[-1:])
    part = d.iloc[:8]                                            # 09:15 … 09:50 (last 5-min closes 09:55)
    r15 = T.resample(part, "15min")
    assert list(r15.index.strftime("%H:%M")) == ["09:15", "09:30"]     # 09:45 bar not complete yet → dropped
    assert r15["high"].iloc[0] == part["high"].iloc[:3].max()


def test_trend_day_gives_ce_and_coverage_rules():
    d = _d5(DAYS, drift=0.00025, seed=3)
    r = T.index_eval("NIFTY", d)
    assert r["side"] == "CE" and r["comps"]["trend"] > 0 and r["comps"]["ma3"] > 0
    assert r["comps"]["iv"] is None and r["coverage"] < 100                      # no chain → IV / skew honestly missing
    s, cov, _ = T.combine({"momentum": 1.0, "sr": None, "trend": None, "meanrev": None, "iv": None, "skew": None, "ma3": None, "combo": None}, T.W_INDEX)
    assert cov < T.CFG["cover"]                                                  # → NO TRADE when most data is missing
    dn = T.index_eval("NIFTY", _d5(DAYS, drift=-0.00025, seed=3))
    assert dn["side"] == "PE"


def test_quality_is_not_a_win_rate_and_bands():
    assert T.band(92) == "ELITE" and T.band(86) == "HIGH QUALITY" and T.band(80) == "WATCHLIST" and T.band(60) == "REJECT"
    assert T.quality(0.0, 0, 1.0) == 50 and T.quality(1.0, 10, 1.0) == 100


def test_option_plan_risk_and_liquidity_filters():
    p, bad = T.plan_option({"ltp": 200, "bid": 199, "ask": 200}, 25800, 25760, 65, 0.5)
    assert bad is None and p["sl"] == 180.0 and p["targets"] == [230.0, 240.0, 260.0] and p["risk_lot"] == 1300
    p, bad = T.plan_option({"ltp": 200, "bid": 199, "ask": 200}, 25800, 25600, 65, 0.5)
    assert bad and "risk" in bad                                                  # 1-lot risk > ₹2,500 → rejected
    p, bad = T.plan_option({"ltp": 20, "bid": 18, "ask": 20}, 1000, 990, 500, 0.5)
    assert bad and "spread" in bad


def test_index_option_selection_from_chain():
    now = pd.Timestamp("2026-11-26 10:30")
    ch = []
    for k in range(25600, 26050, 50):
        ce = max(5, 25800 - k + 120)
        pe = max(5, k - 25800 + 120)
        ch.append({"strike": float(k), "CE": {"ltp": ce, "bid": ce - 0.5, "ask": ce, "lot": 65, "token": f"C{k}", "exch": "NFO", "contract": f"N{k}CE"},
                   "PE": {"ltp": pe, "bid": pe - 0.5, "ask": pe, "lot": 65, "token": f"P{k}", "exch": "NFO", "contract": f"N{k}PE"}})
    best, why = S._tri_index_option({"chain": ch, "expiry": "2026-12-01"}, "CE", 25810, 25775, now)
    assert best, why
    o, p = best
    assert o["strike"] in (25800.0, 25750.0) and 0.40 <= abs(o["delta"]) <= 0.70 and p["risk_lot"] <= 2500
    none, why = S._tri_index_option({"chain": ch, "expiry": "2026-11-26"}, "CE", 25810, 25775, pd.Timestamp("2026-11-26 13:30"))
    assert none is None and "expiry" in why


def test_stock_engine_and_knn():
    idx = pd.bdate_range("2026-03-01", "2026-11-25")
    c = pd.Series(np.linspace(100, 160, len(idx)) + np.sin(np.arange(len(idx))) * 0.5, index=idx)
    d = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1e5}, index=idx)
    n = pd.Series(np.linspace(24000, 25000, len(idx)), index=idx)
    r = T.stock_eval("AAA", d, {"ltp": 161.0, "pct": 1.5, "vol_ratio": 2.0, "vwap": 160.0}, n, 0.0, "Long Built Up")
    assert r["side"] == "CE" and r["comps"]["momentum"] > 0 and r["comps"]["residual"] is not None and r["comps"]["knn"] is not None
    assert any("unusual volume" in c[0] for c in r["conf"]) and r["score"] >= 75


def test_commodity_engine_marks_missing_global_data():
    d = _d5(DAYS[-10:], drift=0.0003, seed=5, start=120000)
    d["volume"] = 100
    r = T.comm_eval("GOLD", {"5M": d, "15M": T.resample(d, "15min"), "1H": T.resample(d, "60min"), "has_vol": True})
    assert r["side"] == "CE" and "dollar index" in r["missing"] and r["comps"]["events"] is None


def test_backtest_walk_forward_runs():
    bt = T.backtest_index({"NIFTY": _d5(pd.bdate_range("2026-09-01", "2026-11-25"), drift=0.00008, seed=7)})
    m = bt["markets"]["NIFTY"]
    assert "in_sample" in m and "out_of_sample" in m and "Underlying" in bt["note"]
    for part in ("in_sample", "out_of_sample"):
        x = m[part]
        if x["trades"]:
            assert x["wins"] + x["losses"] == x["trades"] and x["max_dd_r"] >= 0


class F(S.H):
    def __init__(self, path):
        self.path, self.headers, self.out = path, {}, {}

    def _send(self, code, body, ctype=None):
        self.out = {"code": code, "body": body}


def test_trident_endpoint():
    T.STATE.update(log=[{"date": "2026-11-26", "engine": "INDEX", "lead": "Price momentum §3.1", "status": "T3 DONE", "pnl": 3900, "time": "10:30",
                         "market": "NIFTY", "side": "CE"}])
    f = F("/api/trident")
    f.do_GET()
    d = json.loads(f.out["body"])
    assert d["cfg"]["call"] == 85 and "INDEX" in d["weights"] and d["weights"]["INDEX"]["momentum"] == 20
    assert list(d["perf"].values())[0]["pnl"] == 3900


def test_structurally_missing_data_not_counted_as_missing():
    comps = {"momentum": 0.8, "multifactor": 0.7, "earnings": None, "sector": 0.6, "sr": 0.5, "residual": 0.6, "iv": None, "knn": 0.4}
    _, cov_old, _ = T.combine(comps, T.W_STOCK)
    _, cov_new, _ = T.combine(comps, T.W_STOCK, None, ("iv", "earnings"))
    assert cov_old == 0.75 and cov_new == 1.0
