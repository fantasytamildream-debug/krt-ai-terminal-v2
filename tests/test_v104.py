"""v104: 🌡 market mood · sector mood · best calls buyer interest · 🟢 buyers / 🔴 sellers alerts · ⚡ early crash divergence."""
import threading

import pandas as pd

from krt import mood as MD


def test_mood_scores_skip_missing_and_label():
    MD.H.clear()
    t0 = pd.Timestamp("2026-11-12 10:00")
    ticks = {"NIFTY": {"ltp": 25000, "pct": 0.8}, "BANKNIFTY": {"ltp": 60000, "pct": 1.2}, "SENSEX": {"ltp": 82000, "pct": 0.7},
             "GOLD": {"ltp": 141000, "pct": -0.9}, "INDIA VIX": {"ltp": 12, "pct": -4}}
    hist = {}
    MD.update(t0, ticks, {"up": 70, "dn": 25}, [{"index": "NIFTY", "bias": "BULLISH TILT", "pcr": 1.3}], {}, [{"symbol": "NIFTY", "index": True, "side": "CE", "status": "CONFIRMED"}],
              {"sectors": [{"sector": "Banks", "pct": 1.4, "n": 12, "up": 11}, {"sector": "IT", "pct": -0.8, "n": 10, "up": 2}], "oi": {"bull_pct": 70}}, hist)
    for i in range(1, 25):                                    # NIFTY keeps rising → momentum
        ticks["NIFTY"]["ltp"] += 6
        R = MD.update(t0 + pd.Timedelta(minutes=i), ticks, {"up": 70, "dn": 25}, [], {}, [], {}, hist)
    n = R["NIFTY"]
    assert n["score"] >= 60 and n["label"] in ("Bullish", "Very bullish") and n["parts"]["momentum"] > 0 and "flow" not in n["parts"]   # no footprint → skipped
    g = R["GOLD"]
    assert g["score"] < 50 and set(g["parts"]) <= {"price", "momentum"}                                          # MCX: no breadth / OI / news
    o = R["Overall"]
    assert o["score"] > 60 and "vix" in o["parts"] and o["breakdown"]["bull"] > o["breakdown"]["bear"]
    assert "FINNIFTY" not in R                                                                                     # no data → no fake gauge
    assert hist["2026-11-12"]["NIFTY"] and "now" in n["say"]
    S = MD.STATE["sectors"]
    assert S[0]["sector"] == "Banks" and S[0]["label"] in ("Bullish", "Very bullish") and S[-1]["sector"] == "IT"


def test_best_calls_buyer_interest():
    calls = {"a": {"symbol": "SBIN", "strike": 1050, "side": "CE", "entry": 25.9, "sl": 22.6, "ltp": 26.0, "targets": [28.6, 31.2, 33.8], "vol_ratio": 2.4}}
    rows = [{"id": "a", "decision": "TAKE", "score": 86, "say": "TAKE: 3 confirmations"}, {"id": "b", "decision": "SKIP"}]
    out = MD.best_calls(rows, calls, {"SBIN": {"flow": "Buyers 3 levels-ல் தொடர்ந்து"}}, [{"symbol": "SBIN", "oi": "Long Built Up"}],
                        lambda s, sd, k: {"all": {"n": 8, "t1": 6}})
    c = out[0]
    assert len(out) == 1 and c["to_targets"][0] == 10.0 and c["t1_rate"] == 75 and "volume 2.4× normal" in c["buyers"] and "OI: Long Built Up" in c["buyers"]


def test_buyer_seller_alerts_with_cooldown():
    from krt import footprint as F
    F.FLOW.update(last={}, alerts=[])
    now = pd.Timestamp("2026-11-12 10:30")
    view = {"SBIN": {1: {"an": {"delta_pct": 62, "buy_stack": 3, "sell_stack": 0}, "rvol": 2.1, "bar": {"c": 1052}}},
            "TCS": {1: {"an": {"delta_pct": -55, "buy_stack": 0, "sell_stack": 4}, "rvol": 1.8, "bar": {"c": 3900}}},
            "LOWV": {1: {"an": {"delta_pct": 80, "buy_stack": 5, "sell_stack": 0}, "rvol": 1.1, "bar": {"c": 10}}}}
    sent = []
    new = F.flow_alerts(view, now, lambda m, k, u: sent.append(m))
    assert {(a["symbol"], a["side"]) for a in new} == {("SBIN", "BUY"), ("TCS", "SELL")}                    # low RVOL ignored
    assert sent[0].startswith(("🟢 BUYERS ENTERING", "🔴 SELLERS ENTERING"))
    assert F.flow_alerts(view, now + pd.Timedelta(minutes=5), None) == []                                   # 15-min cooldown
    assert len(F.flow_alerts(view, now + pd.Timedelta(minutes=16), None)) == 2


def test_early_crash_divergence():
    from krt import crash as CR
    CR.H.clear()
    t0 = pd.Timestamp("2026-11-12 11:00")
    for i in range(16):                                       # NIFTY rising +0.3% …
        CR._push("NIFTY", t0 + pd.Timedelta(minutes=i), 25000 * (1 + 0.0002 * i))
        CR._push("breadth_dn", t0 + pd.Timedelta(minutes=i), 30 + 0.8 * i)   # … but decliners growing 30 → 42
    ev = CR.evaluate(t0 + pd.Timedelta(minutes=15), {"dn": 42, "up": 53}, {"an": {"delta_pct": -55}})       # futures already selling
    early = [s for s in ev["signals"] if s.startswith("⚡ early")]
    assert ev["side"] == "DOWN" and ev["level"] == "WATCH" and len(early) == 2 and len(ev["signals"]) == 2     # no double counting


def test_mood_run_no_deadlock(monkeypatch):
    import server
    th = threading.Thread(target=lambda: server.mood_run(pd.Timestamp("2026-11-12 10:30")), daemon=True)
    th.start()
    th.join(15)
    assert not th.is_alive(), "mood_run deadlocked on CALLS_LOCK"
