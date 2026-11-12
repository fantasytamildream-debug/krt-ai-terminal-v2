"""v98: 👑 Mannan Gamma Unwind (Index) · ✅ proven lane (Index OI fix) · 🩺 health · 🔥 Combo · 📐 Spreads."""
import numpy as np
import pandas as pd

from tests.test_mannan import FakeStore


def _rows(spot, ce_oi, ce_ltp, pe_oi=None, step=50):
    rows = []
    for k in range(int(spot // step * step) - 5 * step, int(spot // step * step) + 6 * step, step):
        rows.append({"strike": float(k), "CE": {"token": f"C{k}", "oi": ce_oi.get(k, 20000), "ltp": ce_ltp.get(k, 50.0)},
                     "PE": {"token": f"P{k}", "oi": (pe_oi or {}).get(k, 20000), "ltp": 50.0}})
    return rows


def test_mannan_gamma_unwind_ce():
    from krt.fullscan import mgu_signal
    H, t0 = {}, pd.Timestamp("2026-11-11 10:00")
    assert mgu_signal("NIFTY", 25000, _rows(25000, {25100: 100000}, {25100: 40.0}), t0, H) is None             # baseline
    s = mgu_signal("NIFTY", 25060, _rows(25060, {25100: 89000}, {25100: 48.0}), t0 + pd.Timedelta(minutes=6), H)
    assert s and s["side"] == "CE" and s["strike"] == 25100 and s["drop"] >= 8 and s["jump"] >= 15 and s["mom"] >= 0.12
    H2 = {}
    mgu_signal("NIFTY", 25000, _rows(25000, {25100: 100000}, {25100: 40.0}), t0, H2)
    assert mgu_signal("NIFTY", 25060, _rows(25060, {25100: 96000}, {25100: 48.0}), t0 + pd.Timedelta(minutes=6), H2) is None   # 4% drop மட்டும்


def test_proven_lane_unblocks_index_oi(monkeypatch):
    from krt import calls as CL, store as SM
    fs = FakeStore()
    for m in (CL, SM):
        monkeypatch.setattr(m, "STORE", fs)
    CL.PROVEN.update(t=0, set=set())
    hist = {f"h{i}": {"id": f"h{i}", "date": "2026-11-0%d" % (1 + i % 4), "symbol": "NIFTY", "kind": "INTRADAY", "source": "Index OI", "status": "T2 DONE" if i % 3 else "SL HIT",
                      "pnl_lot": 2000 if i % 3 else -1500} for i in range(20)}
    day = "2026-11-11"
    other = {f"o{i}": {"id": f"o{i}", "date": day, "symbol": "NIFTY" if i == 0 else f"S{i}", "kind": "INTRADAY", "source": "Top Movers", "status": "OPEN", "pnl_lot": 0}
             for i in range(12)}
    fs.data["calls"] = {**hist, **other}
    now = pd.Timestamp(f"{day} 11:00")
    c = {"date": day, "symbol": "NIFTY", "side": "PE", "kind": "INTRADAY", "source": "Index OI", "entry": 100, "sl": 85}
    assert CL.quality_v6(c, now) is None                                                      # 12 calls + NIFTY dup இருந்தும் pass
    c2 = dict(c, source="Weak Module")
    assert CL.quality_v6(c2, now) is None                                                     # v106 index lane: another module's NIFTY call is allowed
    fs.data["calls"]["dupe"] = {"id": "dupe", "date": day, "symbol": "NIFTY", "side": "PE", "kind": "INTRADAY", "source": "Weak Module", "status": "OPEN", "pnl_lot": 0}
    assert CL.quality_v6(dict(c2), now)[0] == "Q_DUP"                                         # same module + same index + same side → blocked
    s2 = {"date": day, "symbol": "S1", "side": "CE", "kind": "INTRADAY", "source": "Weak Module", "entry": 100, "sl": 85}
    assert CL.quality_v6(s2, now)[0] in ("Q_DUP", "Q_DAY_MAX")                                # stocks keep the old gate


def test_module_health(monkeypatch):
    from krt import calls as CL
    d = {"calls": {"a": {"id": "a", "date": "2026-11-04", "time": "10:00", "kind": "INTRADAY", "source": "Index OI", "status": "SL HIT"},
                   "b": {"id": "b", "date": "2026-11-11", "time": "10:05", "kind": "INTRADAY", "source": "Top Movers", "status": "OPEN"}}}
    CL.SKIPPED.update(day="2026-11-11", log=[{"source": "Index OI", "code": "Q_DAY_MAX"}, {"source": "Index OI", "code": "Q_DAY_MAX"}])
    CL.PROVEN.update(t=0, set=set())
    H = {r["source"]: r for r in CL.module_health(d, pd.Timestamp("2026-11-11 12:00"))}
    assert H["Index OI"]["status"].startswith("🟡") and H["Index OI"]["top"] == ["Q_DAY_MAX ×2"] and H["Index OI"]["days"] == 7
    assert H["Top Movers"]["status"].startswith("🟢")


def test_combo_all_conditions(monkeypatch):
    from krt import combo as CB, chartroom as CR, methods as MT
    n = 60
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": [1000.0] * (n - 3) + [3000.0, 1200, 1100]},
                      index=pd.date_range("2026-11-11 09:15", periods=n, freq="5min"))
    a = {"atr": 1.0, "liquidity": {"sweeps": [{"i": n - 3, "side": "UP", "txt": "⚡ EQL sweep"}]}, "trap": {}, "structure": {"events": [{"type": "CHOCH ⬆", "side": "UP", "price": 100}]}}
    monkeypatch.setattr(CR, "analyse", lambda d: dict(a))
    monkeypatch.setattr(CR, "candle_engine", lambda o, h, l, c, atr: [{"name": "Bullish engulfing", "side": "UP"}])
    monkeypatch.setattr(MT, "run_all", lambda d, a_, side: {"score": 72 if side == "CE" else 28, "pro": ["x"] * 8})
    ev = CB.evaluate(df, "CE", "UP")
    assert ev["pass"] and ev["score"] == 6 and ev["vx"] >= 1.5
    assert not CB.evaluate(df, "PE", "UP")["pass"]
    a["structure"] = {"events": [{"type": "BOS ⬆", "side": "UP", "price": 100}]}                 # CHOCH இல்லை (continuation மட்டும்)
    ev2 = CB.evaluate(df, "CE", "UP")
    assert not ev2["pass"] and any("BOS" in c["txt"] for c in ev2["checks"])


def _chain(spot, ce_wall, pe_wall, step=50):
    rows = []
    for k in range(int(spot - 10 * step), int(spot + 11 * step), step):
        dist = abs(k - spot) / step
        mk = lambda t, oi: {"token": f"{t}{k}", "exch": "NFO", "contract": f"N{k}{t}", "lot": 65, "oi": oi,
                            "ltp": max(1.0, 120 - dist * 10), "bid": max(1.0, 120 - dist * 10) - 0.5, "ask": max(1.0, 120 - dist * 10) + 0.5}
        rows.append({"strike": float(k), "CE": mk("C", 300000 if k == ce_wall else 50000), "PE": mk("P", 300000 if k == pe_wall else 50000)})
    return rows


def test_spreads_build_and_exit(monkeypatch):
    from krt import spreads as SP
    x = {"index": "NIFTY", "spot": 25000, "bias": "NEUTRAL / RANGE", "pcr": 1.0, "chain": _chain(25000, 25300, 24700)}
    sp = SP.build(x, 0.2)
    assert sp["kind"] == "IRON CONDOR" and [l["strike"] for l in sp["legs"]] == [25300, 25400, 24700, 24600] and sp["credit"] > 0
    assert sp["max_loss"] == round((100 - sp["credit"]) * 65) and sp["be"]["up"] > 25300 and sp["be"]["dn"] < 24700
    assert SP.build(dict(x, bias="BULLISH TILT"), 0.6)["kind"] == "BULL PUT SPREAD"
    assert SP.build(dict(x, bias="NEUTRAL / RANGE"), 0.9) is None                               # trend நாள் = IC இல்லை
    fs = FakeStore()
    from krt import calls as CL, store as SM
    for m in (CL, SM):
        monkeypatch.setattr(m, "STORE", fs)

    class Ag:
        def __init__(s, f): s.f = f
        def quotes(s, d):
            if s.f is None:
                return {}
            return {t: {"ltp": 1.0, "depth": {"buy": [{"price": 1.0 * s.f}], "sell": [{"price": 1.2 * s.f}]}} for ex, ts in d.items() for t in ts}
    SP.run(Ag(None), pd.Timestamp("2026-11-11 10:05"), [x], 0.2)                              # open (quote இன்னும் வரல)
    S = fs.data["spreads"]
    assert len(S) == 1 and S[0]["status"] == "OPEN"
    SP.run(Ag(1.0), pd.Timestamp("2026-11-11 10:20"), [x], 0.2)                                # legs மலிவு → profit ≥ 50% credit
    assert S[0]["status"].startswith("TARGET") and S[0]["pnl"] > 0
