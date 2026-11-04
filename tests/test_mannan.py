"""👑 Jackpot Mannan tests — crafted scenarios + full call pipeline (network இல்லை)."""
import numpy as np
import pandas as pd

from krt import mannan as M


def _day(start, n, px=100.0, step=0.0, vol=1000.0):
    idx = pd.date_range(start, periods=n, freq="5min")
    c = px + np.arange(n) * step
    return pd.DataFrame({"open": c - 0.05, "high": c + 0.2, "low": c - 0.2, "close": c, "volume": vol}, index=idx)


def test_eia_release_breakout_ist_time():
    assert M.eia_time("CRUDEOIL", pd.Timestamp("2026-11-04").date()) == pd.Timestamp("2026-11-04 21:00")   # EST → 21:00 IST
    assert M.eia_time("CRUDEOIL", pd.Timestamp("2026-07-01").date()) == pd.Timestamp("2026-07-01 20:00")   # EDT → 20:00 IST
    assert M.eia_time("NATURALGAS", pd.Timestamp("2026-11-04").date()) is None                            # Thursday மட்டும்
    prev = _day("2026-11-03 09:00", 170, 5500)
    td = _day("2026-11-04 09:00", 147, 5500)                 # 09:00 … 21:10
    td.loc[pd.Timestamp("2026-11-04 21:00"), ["open", "high", "low", "close"]] = [5500, 5510, 5490, 5505]
    td.loc[pd.Timestamp("2026-11-04 21:10"), ["open", "high", "low", "close", "volume"]] = [5506, 5530, 5505, 5528, 6000]
    X = M.build(pd.concat([prev, td]))
    s = M.s_eia(X, "CRUDEOIL")
    assert s and s["side"] == "CE" and s["sl"] == 5490


def test_orderflow_absorption():
    prev = _day("2026-11-02 09:15", 75, 100)
    td = _day("2026-11-03 09:15", 12, 100, -0.3)
    a = td.index[8]
    td.loc[a, ["open", "high", "low", "close", "volume"]] = [96.6, 96.8, 96.5, 96.7, 9000]     # அதிக volume · சின்ன range · day low
    for i, t in enumerate(td.index[9:]):
        b = 96.9 + i * 0.4
        td.loc[t, ["open", "high", "low", "close", "volume"]] = [b - 0.3, b + 0.05, b - 0.35, b, 1500]
    X = M.build(pd.concat([prev, td]))
    s = M.s_ofabs(X)
    assert s and s["side"] == "CE" and "Absorption" in s["why"]


def test_triple_barrier():
    m = _day("2026-11-03 09:15", 30, 100, 0.5)
    assert M.triple_barrier(m, 5, "CE", 99.0, 1.0) == 1          # ஏறுது → CE target
    assert M.triple_barrier(m, 5, "PE", 101.0, 1.0) == 0         # PE SL


def _X(px=100.0):
    return {"px": px, "atr": 1.0, "vwap": px - 0.5, "regime": "UP", "t": pd.Timestamp("2026-11-03 11:00")}


def test_confluence_rules():
    st = {k: {"p": None, "n": 0} for k, *_ in M.STRATS["IDX"]}
    sig = lambda s, sl: {"side": s, "sl": sl, "why": "x"}
    r = M.confluence("IDX", {"MTF": sig("CE", 98.5), "ORB": sig("CE", 99.0), "AVWAP": sig("CE", 98.8)}, _X(), st, "UP")
    assert r["ok"] and r["side"] == "CE" and r["score"] >= 75 and r["sl"] == 99.0
    r = M.confluence("IDX", {"MTF": sig("CE", 98.5), "ORB": sig("CE", 99.0), "SWEEP": sig("PE", 101)}, _X(), st, "UP")
    assert not r["ok"] and any("எதிர் பக்கம்" in w for w in r["why_not"])
    r = M.confluence("IDX", {"MTF": sig("CE", 98.5), "ORB": sig("CE", 99.0), "AVWAP": sig("CE", 98.8)}, _X(), st, "DOWN")
    assert not r["ok"] and any("Market திசை" in w for w in r["why_not"])
    r = M.confluence("IDX", {"MTF": sig("CE", 98.5)}, _X(), st, "UP")
    assert not r["ok"]                                            # ஒரு strategy மட்டும் → call இல்லை
    bad = {k: {"p": 0.3, "n": 40} for k, *_ in M.STRATS["IDX"]}
    r = M.confluence("IDX", {"MTF": sig("CE", 98.5), "ORB": sig("CE", 99.0), "AVWAP": sig("CE", 98.8)}, _X(), bad, "UP")
    assert not r["ok"] and any("meta-label" in w for w in r["why_not"])     # backtest மோசம் → block


def test_pairs_and_rv_z():
    bars = {"A": {"t": [str(d.date()) for d in pd.bdate_range(end="2026-11-02", periods=60)], "c": list(100 + np.sin(np.arange(60)) )},
            "B": {"t": [str(d.date()) for d in pd.bdate_range(end="2026-11-02", periods=60)], "c": [100.0] * 60}}
    assert M.pairs_z(bars, "A", "B", 110, 100) > 2               # A இன்று மிக அதிகம்
    a = _day("2026-11-03 09:00", 60, 100, 0.1)
    b = _day("2026-11-03 09:00", 60, 100, 0.0)
    z, turn = M.rv_z(a, b)
    assert z is not None and z > 1


class FakeStore:
    def __init__(self):
        self.data, self.dirty, self.remote, self.error = {"calls": {}}, False, None, None

    def load(self):
        return self.data

    def save(self, force=False):
        pass


def test_index_pipeline_creates_one_best_call(monkeypatch):
    from krt import calls as CL, store as SM
    fs = FakeStore()
    for mod in (CL, SM):
        monkeypatch.setattr(mod, "STORE", fs)
    monkeypatch.setattr(CL, "tg", lambda *a, **k: None)
    monkeypatch.setattr(CL, "quality_v6", lambda c, now: None)
    now = pd.Timestamp("2026-11-03 11:01")
    prev = _day("2026-11-02 09:15", 75, 23500)
    td = _day("2026-11-03 09:15", 21, 23500, 2)
    fr = {"5M": pd.concat([prev, td]), "15M": None, "1H": None, "data_time": "2026-11-03 23:59"}
    M.V.FR.clear()
    M.V.FR.update({"NIFTY": (now, fr), "BANKNIFTY": (now, fr)})
    sig = lambda s: {"side": s, "sl": 23520.0, "why": "test"}
    monkeypatch.setattr(M, "evaluate", lambda seg, X, name=None: {"MTF": sig("CE"), "ORB": sig("CE"), "AVWAP": sig("CE")})
    monkeypatch.setattr(M, "bt_get", lambda *a, **k: {})
    monkeypatch.setattr(M, "_mdir", lambda: "UP")
    opt = {"token": "77", "exch": "NFO", "contract": "NIFTY03NOV2623550CE", "strike": 23550, "expiry": "2026-11-03", "lot": 65,
           "ltp": 80.0, "ask": 80.0, "spread_pct": 0.5, "delta": 0.5, "type": "CE"}
    monkeypatch.setattr(M.V, "pick_strike", lambda *a: (dict(opt), ""))
    out = M.run_index(None, {}, {"index": []}, now)
    rows = out["rows"]
    assert rows[0]["ok"] and rows[0].get("call")
    calls = list(fs.data["calls"].values())
    assert len(calls) == 1                                       # ஒரு run-க்கு best 1 மட்டும்
    c = calls[0]
    assert c["kind"] == "MANNAN-IDX" and c["mannan"]["strats"] == ["MTF", "ORB", "AVWAP"] and c["intraday"]
    assert 0 < c["sl"] < c["entry"] < c["targets"][0]
    out = M.run_index(None, {}, {"index": []}, now + pd.Timedelta(minutes=5))
    assert len(fs.data["calls"]) == 2                            # BANKNIFTY (NIFTY ஏற்கனவே call ஆனது)
    t3 = now + pd.Timedelta(minutes=10)
    M.V.FR.update({"NIFTY": (t3, fr), "BANKNIFTY": (t3, fr)})
    out = M.run_index(None, {}, {"index": []}, t3)
    assert len(fs.data["calls"]) == 2 and all(r.get("call") in fs.data["calls"] for r in out["rows"])   # புது call இல்லை, ஏற்கனவே உள்ள call link
    rep = M.report()
    assert len(rep["segs"]["IDX"]["calls"]) == 2 and len(rep["segs"]["IDX"]["strats"]) == 10


def test_outside_time_saves_setup_with_strike_no_call(monkeypatch):
    fs = _store(monkeypatch)
    rows = [{"ok": True, "score": 90, "symbol": "DABUR", "side": "CE", "px": 393.15, "sl": 390.0, "agree": ["RS", "MTF"], "why_not": []}]
    opt = {"token": "9", "exch": "NFO", "contract": "DABUR395CE", "strike": 395, "expiry": "2026-11-25", "lot": 1250,
           "plan": {"entry": 6.0, "sl": 4.1, "targets": [7.6, 9.2, 10.8]}}
    out = M._finish("STK", rows, pd.Timestamp("2026-11-04 15:05"), lambda r: (dict(opt), None))
    r = out["rows"][0]
    assert not r.get("call") and any("நேரம்" in w for w in r["why_not"])
    st = r["setup"]
    assert st["strike"] == 395 and st["entry"] == 6.0 and st["targets"] == [7.6, 9.2, 10.8] and not fs.data["calls"]
    assert list(fs.data["mannan_setups"].values())[0]["reason"].startswith("⏰")


def test_setup_tracker_targets_trail_and_eod(monkeypatch):
    fs = _store(monkeypatch)
    now = pd.Timestamp("2026-11-04 15:05")
    rows = [{"ok": True, "score": 90, "symbol": "DABUR", "side": "CE", "px": 393.15, "sl": 390.0, "agree": ["RS", "MTF"], "why_not": []}]
    opt = {"token": "9", "exch": "NFO", "strike": 395, "lot": 100, "plan": {"entry": 6.0, "sl": 4.0, "targets": [7.0, 8.0, 9.0]}}
    M._finish("STK", rows, now, lambda r: (dict(opt), None))
    px = {"v": 7.2}

    class Ag:
        def quotes(self, d):
            return {"9": {"ltp": px["v"]}}
    M.track_setups(Ag(), now + pd.Timedelta(minutes=1))
    x = list(fs.data["mannan_setups"].values())[0]
    assert x["status"] == "T1 HIT" and x["sl"] == 6.0 and x["pnl_lot"] == 120       # T1 → SL entry
    px["v"] = 5.9
    M.track_setups(Ag(), now + pd.Timedelta(minutes=2))
    assert x["status"] == "TRAIL SL" and x["pnl_lot"] == -10
    # EOD
    rows[0].update(symbol="ITC")
    M._finish("STK", rows, now, lambda r: (dict(opt, token="10"), None))
    px["v"] = 6.5
    M.track_setups(Ag(), pd.Timestamp("2026-11-04 15:21"))
    y = [s for s in fs.data["mannan_setups"].values() if s["symbol"] == "ITC"][0]
    assert y["status"] == "EOD EXIT"


def test_covered_call_screen():
    n = 80
    t = [str(d.date()) for d in pd.bdate_range(end="2026-11-02", periods=n)]
    rng = np.random.default_rng(1)
    c = list(np.cumprod(1 + rng.normal(0.003, 0.008, n)) * 1000)
    bars = {"GOODCO": {"t": t, "o": c, "h": [x * 1.005 for x in c], "l": [x * 0.995 for x in c], "c": c, "v": [1e6] * n}}
    out = M.covered_calls(bars, {}, {"opts": {}})
    assert isinstance(out, list)


def _store(monkeypatch):
    from krt import calls as CL, store as SM
    fs = FakeStore()
    for mod in (CL, SM):
        monkeypatch.setattr(mod, "STORE", fs)
    monkeypatch.setattr(CL, "tg", lambda *a, **k: None)
    monkeypatch.setattr(CL, "quality_v6", lambda c, now: None)
    monkeypatch.setattr(M, "bt_get", lambda *a, **k: {})
    return fs


def test_stock_pipeline_with_spread_and_iv(monkeypatch):
    from krt import fullscan as FS
    fs = _store(monkeypatch)
    now = pd.Timestamp("2026-11-03 11:01")
    m5 = pd.concat([_day("2026-11-02 09:15", 75, 1000), _day("2026-11-03 09:15", 21, 1000, 1)])
    monkeypatch.setattr(M, "_stock_m5", lambda ag, tok, sym, now: m5)
    monkeypatch.setattr(M, "_mdir", lambda: "UP")
    sig = lambda s: {"side": s, "sl": 1010.0, "why": "t"}
    monkeypatch.setattr(M, "evaluate", lambda seg, X, name=None: {"RS": sig("CE"), "UNUSUAL": sig("CE"), "MTF": sig("CE")})
    best = {"token": "9", "exch": "NFO", "contract": "AAA-1020CE", "strike": 1020, "expiry": "2026-11-25", "type": "CE", "lot": 250,
            "ltp": 30.0, "ask": 30.2, "bid": 29.8, "spread_pct": 1.3, "moneyness": "ATM"}
    alt = dict(best, token="10", contract="AAA-1040CE", strike=1040, ltp=21.0, bid=20.8, ask=21.2)

    def fake_pick(ag, inst, rows):
        for r in rows:
            r["option"], r["option_alts"] = dict(best), [alt]

    def fake_plan(r, o, now, src=None):
        o["plan"] = {"entry": 30.2, "sl": 22.0, "targets": [38.2, 46.2, 54.2], "risk": 2050, "risk_ok": True, "money": True, "reward_ok": True}
    monkeypatch.setattr(FS, "pick_options", fake_pick)
    monkeypatch.setattr(FS, "attach_plan", fake_plan)
    monkeypatch.setattr(FS, "C", {"bars": {}, "levels": {}})
    live_q = {"AAA": {"ltp": 1020, "pct": 2.5, "vol_ratio": 3.2}}
    out = M.run_stocks(None, {"eq": {"AAA": "1"}}, {"index": [{"index": "NIFTY", "pct": 0.4}]}, live_q, now)
    c = list(fs.data["calls"].values())
    assert len(c) == 1 and c[0]["kind"] == "MANNAN-STK", out["rows"][0].get("why_not")
    sp = c[0]["mannan"]["spread"]
    assert sp and sp["buy"] == 1020 and sp["sell"] == 1040 and sp["debit"] == round(30.2 - 20.8, 2) and sp["max_profit"] > 0


def test_commodity_pipeline(monkeypatch):
    from krt import commodity as CM
    fs = _store(monkeypatch)
    now = pd.Timestamp("2026-11-03 19:31")
    m5 = pd.concat([_day("2026-11-02 09:00", 170, 5500), _day("2026-11-03 09:00", 126, 5500, 0.5)])
    fr = {"5M": m5, "15M": None, "1H": M.V._resample(m5, "60min", offset="9h0min")}
    monkeypatch.setattr(CM, "FR", {"CRUDEOIL": (now, fr)})
    monkeypatch.setattr(CM, "_fut", lambda inst, n: ["1", "CRUDEOILFUT", "2026-11-19", "MCX"] if n == "CRUDEOIL" else None)
    sig = lambda s: {"side": s, "sl": 5545.0, "why": "t"}
    monkeypatch.setattr(M, "evaluate", lambda seg, X, name=None: {"TSMOM": sig("CE"), "DONCHIAN": sig("CE"), "OFI": sig("CE")})
    monkeypatch.setattr(M, "_daily", lambda *a, **k: None)
    monkeypatch.setattr(CM, "pick_option", lambda *a: {"token": "5", "contract": "CRUDEOILM5600CE", "expiry": "2026-11-17", "strike": 5600,
                                                     "mult": 10, "ltp": 120.0, "ask": 120.0, "bid": 119.0, "spread_pct": 0.8, "commodity": "CRUDEOILM"})

    class Ag:
        def quotes(self, d):
            return {"1": {"ltp": 5560, "totBuyQuan": 3000, "totSellQuan": 1500}}
    out = M.run_commodity(Ag(), {}, now)
    c = list(fs.data["calls"].values())
    assert len(c) == 1 and c[0]["kind"] == "MANNAN-CMD" and c[0]["exch"] == "MCX", out["rows"][0].get("why_not")
    assert 0 < c[0]["sl"] < c[0]["entry"] < c[0]["targets"][0]


def test_index_stale_frames_reloaded(monkeypatch):
    _store(monkeypatch)
    now = pd.Timestamp("2026-11-04 11:05:20")
    fr_old = {"5M": pd.concat([_day("2026-11-03 09:15", 75, 23500), _day("2026-11-04 09:15", 22, 23500, 1)]), "15M": None, "1H": None,
              "data_time": "2026-11-04 11:01"}
    M.V.FR.clear()
    M.V.FR["NIFTY"] = (now, fr_old)
    called = []
    monkeypatch.setattr(M.V, "load_frames", lambda ag, inst, idx, now: called.append(idx) or None)
    M.run_index(None, {}, {"index": []}, now)
    assert "NIFTY" in called                    # 11:05 bar இல்லாத frames → நேரடி reload
