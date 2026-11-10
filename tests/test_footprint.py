"""👣 Footprint strategy tests."""
import pandas as pd

from krt import footprint as F


def _q(ltp, vol, bid, ask):
    return {"ltp": ltp, "tradeVolume": vol, "depth": {"buy": [{"price": bid}], "sell": [{"price": ask}]}}


def _feed_bull(sym, start, base=1000.0, step=0.3):
    """ஒரு 1-min bar-ல் விலை ஏறிக்கிட்டே ask-ல் பெரிய buys (stacked buy imbalance) — முன்னாடி 6 quiet bars (RVOL baseline)."""
    t = start
    vol = 0.0
    px = base
    for m in range(6):                                  # quiet bars: சின்ன volume, இரண்டு பக்கமும்
        for k in range(10):
            vol += 50
            px = base + (0.1 if k % 2 else -0.1)
            F.ingest(sym, _q(px, vol, px - 0.05, px + 0.05), t + pd.Timedelta(minutes=m, seconds=k * 5))
    t2 = t + pd.Timedelta(minutes=6)
    for k in range(12):                                 # bull bar: ask lift, ஒவ்வொரு level-லும் பெரிய buy
        vol += 400
        px = base + k * step
        F.ingest(sym, _q(px, vol, px - 0.1, px), t2 + pd.Timedelta(seconds=k * 4))
    return t2


def test_spread_tick_exception():
    assert F.spread_ok(99.5, 100.5)[0] is True                        # 1% ✓
    ok, pct, txt = F.spread_ok(2.95, 3.05)                            # 3.3% ஆனா 2 ticks
    assert ok and pct > 1 and "tick-size exception" in txt
    assert F.spread_ok(2.90, 3.10)[0] is False                        # 4 ticks, 6.7%
    assert F.tick_size(180) == 0.01 and F.tick_size(900) == 0.05 and F.step_for(25000, 0.05) == 7.5


def test_stacked_buy_imbalance_and_checklist():
    F.FP.clear()
    t2 = _feed_bull("TST", pd.Timestamp("2026-11-10 10:00"))
    S = F.FP["TST"]
    k = (t2.hour * 60 + t2.minute)
    B = S["bars"][1][k]
    an = F.analyze_bar(B)
    assert an["buy_stack"] >= 3 and an["sell_stack"] == 0 and an["delta"] > 0 and an["close_pos"] > 0.8
    rv = F.rvol(S, 1, k)
    assert rv and rv >= 1.5
    ck = F.checklist("CE", an, rv, S, {"mdir": "UP", "hm": "10:07"})
    assert ck["pass"] and all(i["ok"] for i in ck["items"] if i["must"])
    pe = F.checklist("PE", an, rv, S, {"mdir": "UP", "hm": "10:07"})
    assert not pe["pass"]
    late = F.checklist("CE", an, rv, S, {"mdir": "UP", "hm": "15:00"})
    assert not late["pass"]                                            # 14:45-க்கு பிறகு இல்லை


def test_scan_creates_call_with_option_filters(monkeypatch):
    from krt import calls as CL, store as SM, ailab as AL
    from tests.test_mannan import FakeStore
    fs = FakeStore()
    for m in (CL, SM):
        monkeypatch.setattr(m, "STORE", fs)
    monkeypatch.setattr(CL, "quality_v6", lambda c, now: None)
    F.FP.clear(); F.STATE.update(signals=[], universe=[{"symbol": "TST", "token": "1", "exch": "NSE", "kind": "EQ", "opt_name": "TST"}],
                                  u_t=pd.Timestamp("2026-11-10 10:00"))
    t2 = _feed_bull("TST", pd.Timestamp("2026-11-10 10:00"))
    rows = [{"strike": 1000, "delta": 0.72, "bid": 20, "ask": 20.1, "ltp": 20, "lot": 100, "expiry": "2026-11-25", "token": "a", "exch": "NFO", "contract": "x"},
            {"strike": 1005, "delta": 0.52, "bid": 3.9, "ask": 4.3, "ltp": 4.1, "lot": 100, "expiry": "2026-11-25", "token": "b", "exch": "NFO", "contract": "y"},
            {"strike": 1010, "delta": 0.48, "bid": 2.95, "ask": 3.0, "ltp": 3.0, "lot": 100, "expiry": "2026-11-25", "token": "c", "exch": "NFO", "contract": "z"}]
    monkeypatch.setattr(AL, "best_strike", lambda *a, **k: {"rows": rows})
    import krt.optmath as OM
    monkeypatch.setattr(OM, "plan", lambda prem, spot, K, exp, side, ul_sl, tg, now, lot: {"entry": prem, "sl": round(prem * 0.8, 2),
                                                                                            "targets": [round(prem * 1.45, 2), round(prem * 1.7, 2), round(prem * 2, 2)], "risk": prem * 0.2 * lot})
    now = t2 + pd.Timedelta(minutes=1, seconds=5)
    F.STATE["u_t"] = now                                                # universe refresh (5 நிமிடம்) test-ல் வேண்டாம்
    F.scan(object(), {}, now, [], "UP")
    calls = [c for c in fs.data["calls"].values() if c["kind"] == "FOOTPRINT"]
    assert len(calls) == 1 and calls[0]["strike"] == 1010                # 1000: delta 0.72 ✗ · 1005: spread 10% ✗ · 1010: ✓ (2 ticks exception)
    assert calls[0]["fp"]["stack"] >= 3 and calls[0]["checklist"]
    sig = F.STATE["signals"][0]
    assert sig["pass"] and sig["call"]["strike"] == 1010 and fs.data["fp_signals"]


def test_tune_needs_data_then_ranks():
    J = [{"stack": 3 + (i % 2), "rvol": 1.6 + (i % 3) * 0.3, "result": 0.3 if i % 3 else -0.1} for i in range(40)]
    T = F.tune(J)
    assert T["rows"] and T["best"]["win"] >= T["rows"][-1]["win"]
    assert F.tune(J[:5])["rows"] == [] and F.tune(J[:5])["need"] == 20
