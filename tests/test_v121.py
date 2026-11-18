"""v121: Command Center (movers · real option chain · strike plan) · Market Guide · regime detector · JARVIS Sniper."""
import numpy as np
import pandas as pd

from krt import command as CMD, guide as GD, jsniper as JS


def LQ():
    return {"AAA": {"ltp": 110, "pct": 3.2, "vol_ratio": 2.4, "high": 111, "low": 104, "vwap": 108, "volume": 5000},
            "BBB": {"ltp": 90, "pct": -2.5, "vol_ratio": 1.8, "high": 95, "low": 89.5, "vwap": 92, "volume": 4000},
            "TCS": {"ltp": 3000, "pct": 0.4, "vol_ratio": 0.9, "high": 3010, "low": 2980, "vwap": None, "volume": 100},
            "INFY": {"ltp": 1500, "pct": -0.2, "vol_ratio": None, "high": 1510, "low": 1490}}


def test_movers_tabs_and_setups():
    m = CMD.movers(LQ(), {"AAA": {"PDH": 108, "PDL": 100}, "BBB": {"PDH": 99, "PDL": 91}}, [{"symbol": "AAA", "kind": "Long Built Up", "oi_chg_pct": 4.2}])
    assert m["gainers"][0]["symbol"] == "AAA" and m["losers"][0]["symbol"] == "BBB"
    assert m["breakouts"][0]["setup"] == "BREAKOUT" and m["breakdowns"][0]["symbol"] == "BBB"
    assert m["oi"][0]["oi"] == "Long Built Up"
    assert m["volume"][0]["symbol"] == "AAA"
    it = [s for s in m["sectors"] if s["sector"] == "IT"][0]
    assert it["leader"] == "TCS" and it["laggard"] == "INFY"
    tcs = [r for r in m["gainers"] if r["symbol"] == "TCS"][0]
    assert tcs["vwap"] is None and tcs["vwap_pos"] is None          # missing data stays missing


def _prem(n=40, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 1.5, n))
    idx = pd.date_range("2026-11-17 09:15", periods=n, freq="5min")
    return pd.DataFrame({"open": c - 0.5, "high": c + 2, "low": c - 2, "close": c, "volume": 1000}, index=idx)


def test_premium_plan_closed_candles_only():
    df = _prem()
    closed = df.index[-2]
    p = CMD.premium_plan(df, 50, closed)
    assert p["entry"] == round(float(df["close"].iloc[-2]), 2)        # forming candle ignored
    assert p["sl"] < p["entry"] < p["targets"][0] < p["targets"][1] < p["targets"][2]
    assert len(p["t_src"]) == 3 and p["risk_lot"] == round((p["entry"] - p["sl"]) * 50)
    df2 = df.copy()
    df2.iloc[-1, df2.columns.get_loc("close")] = 999                  # a wild forming candle must not change the plan
    assert CMD.premium_plan(df2, 50, closed) == p


class FakeAg:
    def quotes(self, toks):
        out = {"99": {"ltp": 1005}}
        for ex, L in toks.items():
            for t in L:
                if t == "99":
                    continue
                k = int(t)
                out[t] = {"ltp": max(1, 30 - abs(k - 1000) / 5), "depth": {"buy": [{"price": 20}], "sell": [{"price": 20.4}]},
                          "tradeVolume": 5000 - abs(k - 1000) * 10, "opnInterest": 10000, "percentChange": 2.0}
        return out


def test_chain_real_strikes_only():
    exp = str((pd.Timestamp.now(tz="Asia/Kolkata") + pd.Timedelta(days=8)).date())
    rows = [[str(k + (1 if t == "PE" else 0)), f"AAA{k}{t}", exp, float(k), t, 500, "NFO"] for k in range(900, 1110, 10) for t in ("CE", "PE")]
    inst = {"opts": {"AAA": rows}, "eq": {"AAA": "99"}}
    ch = CMD.chain(FakeAg(), inst, "AAA", width=3)
    assert ch["ok"] and ch["atm"] == 1000.0 and ch["lot"] == 500 and ch["expiry"] == exp
    ks = sorted({r["strike"] for r in ch["rows"]})
    assert ks == [970.0, 980.0, 990.0, 1000.0, 1010.0, 1020.0, 1030.0]
    assert all(r["contract"].startswith("AAA") for r in ch["rows"])
    assert any(r.get("rank") == 1 for r in ch["rows"] if r["type"] == "CE")
    x = [r for r in ch["rows"] if r["strike"] == 1000.0 and r["type"] == "CE"][0]
    assert x["spread_pct"] == round(0.4 / 20.2 * 100, 2) and x.get("model") is True
    bad = CMD.chain(FakeAg(), {"opts": {}, "eq": {}}, "ZZZ")
    assert not bad["ok"]


def test_greeks_signs():
    now = pd.Timestamp("2026-11-17 10:00")
    ce = CMD._greeks(25, 1000, 1000, "2026-11-27", "CE", now)
    pe = CMD._greeks(25, 1000, 1000, "2026-11-27", "PE", now)
    assert 0.4 < ce["delta"] < 0.65 and -0.65 < pe["delta"] < -0.35
    assert ce["theta"] < 0 and pe["theta"] < 0 and ce["gamma"] > 0


def test_regime_classes_and_unknown():
    assert GD.regime(None, None)["label"] == "UNKNOWN"
    assert GD.regime({"pct": 0.1}, None, stale=True)["label"] == "NO TRADE"
    secs = [{"pct": 1.0}] * 9 + [{"pct": -0.5}]
    r = GD.regime({"pct": 0.9, "spot": 24500, "support": 24200, "resistance": 24400}, {"up": 150, "down": 40}, secs, {"bull_pct": 72})
    assert r["label"] == "STRONG BULLISH" and r["agree"] == "5/5"
    r = GD.regime({"pct": -0.5}, {"up": 40, "down": 150}, [{"pct": -1}] * 10, {"bull_pct": 30})
    assert r["label"] in ("BEARISH", "STRONG BEARISH")
    r = GD.regime({"pct": 0.6}, {"up": 40, "down": 150}, [{"pct": 1}] * 10, {"bull_pct": 30})
    assert r["label"] == "HIGH VOLATILITY" and r["conflicts"] == []


def test_guide_build():
    rg = {"label": "BULLISH", "evidence": ["NIFTY +0.50%"], "agree": "3/4"}
    jv = [{"id": "c1", "symbol": "AAA", "strike": 110, "side": "CE", "verdict": "TAKE", "verdict_why": "ok", "plan": {"entry": 5, "sl": 4, "targets": [{"prem": 6}, {"prem": 7}]}, "score": 85},
          {"id": "c2", "symbol": "BBB", "strike": 90, "side": "CE", "verdict": "DON'T TAKE", "verdict_why": "against sector", "plan": {}}]
    day = str(pd.Timestamp("2026-11-17").date())
    feed = [{"symbol": "AAA", "side": "BUY", "mult": 6.0, "price": 109, "high": 110, "low": 106, "time": day + " 10:05", "date": day, "exch": "NSE", "seen": "10:10:15"}]
    g = GD.build(rg, {"advice": "Trend day", "avoid": [{"module": "All rounder", "win": 10, "exp": -1300}]},
                 {"sectors": [{"sector": "IT", "pct": 1.2}, {"sector": "Bank", "pct": -0.6}]},
                 {"spot": 24300, "support": 24200, "resistance": 24400, "pcr": 1.3}, jv, feed, [], [], [], [], now=pd.Timestamp("2026-11-17 11:00"))
    assert g["take"][0]["targets"] == [6, 7] and g["best"][0]["tag"] == "JARVIS TAKE"
    assert any("All rounder" in a["why"] for a in g["avoid"])
    assert g["big"][0]["target"] == 109 + 2 * 4 and g["big"][0]["sl"] == 106
    assert g["strong"][0]["sector"] == "IT" and g["weak"][0]["sector"] == "Bank"
    assert any("24,400" in t for t in g["next"])


def test_sniper_scores_traps_and_risk():
    parts = {"structure": 18, "trend": 15, "volume": 15, "oi": 15, "liquidity": 10, "mtf": 10, "rr": 10, "regime": 5}
    row = {"id": "c1", "symbol": "AAA", "side": "CE", "strike": 110, "lot": 100, "ltp": 5.05, "entry": 5, "verdict": "TAKE", "module": "Index OI",
           "parts": parts, "plan": {"entry": 5, "sl": 4, "zone": [4.9, 5.15], "targets": [{"prem": 6}, {"prem": 7}, {"prem": 8}]}, "val": {"decision": "APPROVE"}}
    lq = {"AAA": {"ltp": 110, "pct": 1.5, "vol_ratio": 2.0, "high": 111, "low": 104, "vwap": 108}}
    out = JS.build([row], lq, {"AAA": {"PDH": 108}}, [{"sector": "Others", "pct": 0.5}], [], [], [], [], "BULLISH", 20)
    c = out["cards"][0]
    assert c["score"] >= 90 and c["state"] == "CONFIRMED" and not c["reject"] and c["risk"] <= 2500
    lq2 = {"AAA": {"ltp": 107, "pct": 1.0, "vol_ratio": 0.8, "high": 111, "low": 104, "vwap": 108}}   # back below PDH, weak vol, below VWAP
    c2 = JS.build([row], lq2, {"AAA": {"PDH": 108}}, [], [], [], [], [], "BULLISH", 20)["cards"][0]
    assert c2["state"] == "INVALIDATED" and any("trap" in r for r in c2["reject"])
    big = dict(row, lot=5000)
    c3 = JS.build([big], lq, {}, [], [], [], [], [], "BULLISH", 20)["cards"][0]
    assert any("> ₹2,500" in r for r in c3["reject"])
    c4 = JS.build([row], lq, {}, [], [], [{"module": "Index OI", "win": 20, "exp": -900}], [], [], "RANGE", 20)["cards"][0]
    assert any("disabled in this market" in r for r in c4["reject"])
    c5 = JS.build([dict(row, parts={})], lq, {}, [], [], [], [], [], None, 20)["cards"][0]
    assert c5["missing"] and c5["band"] == "REJECT"
