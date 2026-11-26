"""🏆 v110 BEST MODE gate · ⚡ 5-sec paper tracker · stale-entry VOID · live NIFTY · async GitHub save."""
import pandas as pd
import pytest

from krt import calls as CL, store as SM
from tests.test_mannan import FakeStore

DAY = "2026-11-17"
NOW = pd.Timestamp(f"{DAY} 10:30")


@pytest.fixture
def fs(monkeypatch):
    f = FakeStore()
    for m in (CL, SM):
        monkeypatch.setattr(m, "STORE", f)
    CL.PROVEN.update(t=0, set=set(), rows={})
    monkeypatch.setitem(CL.MARKET, "nifty_pct", 0.5)
    monkeypatch.setattr(CL, "breadth_now", lambda: (150, 60))           # most stocks rising
    return f


def _c(**o):
    return {"date": DAY, "symbol": "SBIN", "side": "CE", "kind": "MOVERS", "source": "Top Movers", "entry": 20, "sl": 17, "vol_ratio": 2.4, **o}


def test_clean_stock_ce_passes(fs):
    assert CL.best_gate(_c(), fs.data, NOW) is None


def test_breadth_blocks_stock_ce_when_most_stocks_fall(fs, monkeypatch):
    monkeypatch.setattr(CL, "breadth_now", lambda: (76, 117))           # Monday 16 Nov at 10:25
    assert CL.best_gate(_c(), fs.data, NOW)[0] == "Q_BREADTH"
    assert CL.best_gate(_c(symbol="NIFTY"), fs.data, NOW) is None       # index calls are not breadth-gated


def test_live_nifty_counter_and_stock_pe_rule(fs, monkeypatch):
    monkeypatch.setitem(CL.MARKET, "nifty_pct", -0.6)
    assert CL.best_gate(_c(), fs.data, NOW)[0] == "Q_COUNTER_LIVE"
    monkeypatch.setitem(CL.MARKET, "nifty_pct", 0.1)
    assert CL.best_gate(_c(side="PE"), fs.data, NOW)[0] == "Q_STOCK_PE"                 # no clear down day
    monkeypatch.setitem(CL.MARKET, "nifty_pct", -0.5)
    monkeypatch.setattr(CL, "breadth_now", lambda: (40, 160))
    assert CL.best_gate(_c(side="PE"), fs.data, NOW) is None                           # clear down day → stock PE allowed


def test_low_volume_and_weak_module(fs):
    assert CL.best_gate(_c(vol_ratio=0.9), fs.data, NOW)[0] == "Q_LOW_VOL"
    fs.data["calls"] = {f"h{i}": {"id": f"h{i}", "date": "2026-11-0%d" % (1 + i % 5), "symbol": "X", "side": "CE", "kind": "GOKI",
                                  "source": "Goki Mannan Jackpot", "status": "SL HIT" if i % 3 else "T1 HIT", "pnl_lot": -2000 if i % 3 else 1500}
                        for i in range(20)}
    for c in fs.data["calls"].values():
        if c["status"] == "T1 HIT":
            c["status"] = "T3 DONE"
    assert CL.best_gate(_c(kind="GOKI", source="Goki Mannan Jackpot"), fs.data, NOW)[0] in ("Q_WEAK_MODULE", "Q_RETIRED")   # v125: 35% win, −₹15.5k → removed


def test_one_call_per_stock_side_across_modules_and_index_open_rule(fs):
    fs.data["calls"] = {"a": {"id": "a", "date": DAY, "symbol": "BHARTIARTL", "side": "CE", "kind": "MONEYM", "source": "👑 Money Machine", "status": "SL HIT", "pnl_lot": -4441},
                        "n": {"id": "n", "date": DAY, "symbol": "BANKNIFTY", "side": "CE", "kind": "FOOTPRINT", "source": "👣 Footprint", "status": "OPEN", "pnl_lot": 0}}
    assert CL.best_gate(_c(symbol="BHARTIARTL"), fs.data, NOW)[0] == "Q_DUP_ANY"       # 2nd module, same idea
    assert CL.best_gate(_c(symbol="BANKNIFTY", source="2K Profit Machine", kind="MACHINE"), fs.data, NOW)[0] == "Q_DUP_ANY"
    fs.data["calls"]["n"]["status"] = "SL HIT"
    assert CL.best_gate(_c(symbol="BANKNIFTY", source="2K Profit Machine", kind="MACHINE"), fs.data, NOW) is None   # closed → new idea allowed


def test_side_brake_after_three_sl(fs):
    fs.data["calls"] = {f"s{i}": {"id": f"s{i}", "date": DAY, "symbol": f"S{i}", "side": "CE", "kind": "MOVERS", "source": "Top Movers", "status": "SL HIT",
                                  "pnl_lot": -1500, "exit_time": f"{DAY} 10:{10 + i}:00"} for i in range(3)}
    r = CL.best_gate(_c(), fs.data, NOW)
    assert r[0] == "Q_SIDE_BRAKE" and "paused" in r[1]
    assert CL.best_gate(_c(), fs.data, pd.Timestamp(f"{DAY} 11:30")) is None           # brake lifts after 45 min
    assert CL.best_gate(_c(side="PE"), fs.data, NOW)[0] != "Q_SIDE_BRAKE"              # other side unaffected


def test_mcx_after_130_is_hidden(fs):
    c = _c(kind="MCX", symbol="CRUDEOIL", source="🛢 🔥 MCX Momentum Breakout", exch="MCX")
    assert CL.quality_v6(dict(c), pd.Timestamp(f"{DAY} 11:00")) is None
    assert CL.quality_v6(dict(c), pd.Timestamp(f"{DAY} 19:00"))[0] == "Q_MCX_LATE"


class AG:
    def __init__(self, px):
        self.px = px

    def quotes(self, req):
        return {t: {"ltp": self.px[t]} for ex, ts in req.items() for t in ts if t in self.px}


def _open(cid, **o):
    return {"id": cid, "date": DAY, "time": "10:00", "signal_time": f"{DAY} 10:00", "symbol": "PNB", "strike": 145, "side": "CE", "kind": "PICK",
            "source": "My pick", "entry": 3.36, "sl": 3.15, "targets": [3.6, 3.85, 4.1], "lot": 8000, "status": "OPEN", "hits": [], "token": "t1", "exch": "NFO", **o}


def test_fast_track_sl_and_targets(fs):
    fs.data["calls"] = {"p": _open("p"), "q": _open("q", token="t2", symbol="ITC", entry=6.15, sl=4.85, targets=[7.3, 8.45, 9.65], lot=1725)}
    n = CL.fast_track(AG({"t1": 3.14, "t2": 7.35}), pd.Timestamp(f"{DAY} 10:28:05"))
    p, q = fs.data["calls"]["p"], fs.data["calls"]["q"]
    assert n == 2 and p["status"] == "SL HIT" and p["exit"] == 3.14                     # filled at 3.14, not 2.82 (30-sec lag)
    assert q["status"] == "T1 HIT" and q["sl"] > q["entry"] and q["pnl_lot"] == round((7.35 - 6.15) * 1725)


def test_stale_entry_is_void_not_a_loss(fs):
    c = _open("s", kind="MONEYM", source="👑 Money Machine", symbol="LICHSGFIN", entry=14.4, sl=11.9, targets=[16.4, 18.4, 20.4], lot=1000, token="t3",
              signal_time=f"{DAY} 09:58")
    fs.data["calls"] = {"s": c}
    CL.fast_track(AG({"t3": 11.75}), pd.Timestamp(f"{DAY} 09:58:20"))
    assert c["status"] == "VOID" and "stale entry" in c["void_why"] and c["pnl_lot"] == 0
    old = _open("o", kind="MONEYM", source="👑 Money Machine", token="t4", signal_time=f"{DAY} 09:00")
    fs.data["calls"]["o"] = old
    CL.fast_track(AG({"t4": 3.0}), pd.Timestamp(f"{DAY} 10:28"))
    assert old["status"] == "SL HIT"                                                   # older call → a real SL, never voided


def test_store_upload_is_async(monkeypatch, tmp_path):
    import threading
    import time
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_DATA_REPO", "u/r")
    st = SM.Store("calls.json")
    st.local = tmp_path / "calls.json"
    st.data, st.sha, st.dirty = {"calls": {"a": 1}}, "s1", True
    gate = threading.Event()
    seen = []

    class R:
        status_code = 200

        def json(self):
            return {"content": {"sha": "s2"}}

    def put(*a, **k):
        gate.wait(5)
        seen.append(k["json"]["sha"])
        return R()
    monkeypatch.setattr(SM.requests, "put", put)
    t0 = time.time()
    st.save(force=True)
    assert time.time() - t0 < 0.5 and st.local.exists() and not st.dirty            # returned at once, local file written
    gate.set()
    for _ in range(50):
        if seen:
            break
        time.sleep(0.05)
    time.sleep(0.1)
    assert seen == ["s1"] and st.sha == "s2"


def test_status_is_cached_shared_and_gzipped(monkeypatch):
    import gzip
    import io
    import json
    import server
    server.STC.update(t=0, b=None, gz=None)

    class H(server.Handler if hasattr(server, "Handler") else object):
        pass
    h = object.__new__([c for c in vars(server).values() if isinstance(c, type) and hasattr(c, "_send_status")][0])
    out = io.BytesIO()
    sent = {}
    h.wfile, h.path = out, "/api/status"
    h.headers = {"Accept-Encoding": "gzip, deflate"}
    h.send_response = lambda code: sent.setdefault("code", code)
    h.send_header = lambda k, v: sent.__setitem__(k, v)
    h.end_headers = lambda: None
    h.do_GET() if not hasattr(h, "_do_GET") else h._do_GET()
    assert sent.get("Content-Encoding") == "gzip" and json.loads(gzip.decompress(out.getvalue()))["version"] == server.APP_VERSION
    t0 = server.STC["t"]
    out.truncate(0)
    out.seek(0)
    h.do_GET() if not hasattr(h, "_do_GET") else h._do_GET()
    assert server.STC["t"] == t0                                                      # second poll within 3 s → same cached bytes
    assert server.mem_guard("test") > 0


def test_v113_market_ok_bigplayer_and_coach(fs, monkeypatch):
    from krt import bigplayer as BPL, coach as CO
    monkeypatch.setattr(CL, "breadth_now", lambda: (69, 148))
    assert "breadth" in CL.market_ok({"symbol": "ITC", "side": "CE", "vol_ratio": 2})
    assert CL.market_ok({"symbol": "NIFTY", "side": "CE"}) is None
    rows = [{"symbol": "ITC", "side": "CE", "kind": "Long Built Up", "oi_chg_pct": 4.9, "accel": 0.8, "vr": 2.6, "pct": 1.2, "flow": "buyers adding"},
            {"symbol": "TCS", "side": "CE", "kind": "Short Covering", "oi_chg_pct": -3, "vr": 2, "pct": 2}]
    R = BPL.radar(rows, [{"symbol": "ITC", "side": "CE", "status": "NEAR", "level": 293.2}],
                  [{"symbol": "ITC", "side": "CE", "strike": 295, "entry": 5.1, "sl": 3.9, "targets": [7, 8], "expiry": "2026-11-25"}], [], (150, 60), 0.5)
    assert len(R) == 1 and R[0]["symbol"] == "ITC" and R[0]["score"] >= 75 and "CE strike 295" in R[0]["action"] and R[0]["plan"]["strike"] == 295
    c = {"status": "OPEN", "entry": 10, "sl": 8, "targets": [12, 14], "ltp": 10.1, "vol_ratio": 3, "side": "CE"}
    assert CO.advise(c, None, "CE", {"state": "RISING"}, True)["tag"] == "JACKPOT"
    assert CO.advise(dict(c, ltp=10.9), None)["tag"] == "WAIT"
    assert CO.advise(c, "breadth 69 up / 148 down")["tag"] == "AVOID"
    assert CO.advise(dict(c, ltp=10.6, max_ltp=11.5), None)["tag"] == "EXIT"
    assert CO.advise(dict(c, status="T1 HIT", hits=["T1 10:30"], ltp=12.2), None)["tag"] == "HOLD"


def test_v114_bigvol_spikes_and_radar_boost():
    import numpy as np
    from krt import bigvol as BV, bigplayer as BPL
    idx = pd.date_range("2026-11-16 09:15", periods=30, freq="15min")
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0}, index=idx)
    df.iloc[25, [3, 4]] = [100.9, 5000]          # close near the high + 5× volume → BUY spike
    df.iloc[28, [3, 4]] = [100.8, 9000]
    sp = BV.spikes(df)
    assert sp[0]["side"] == "BUY" and sp[0]["mult"] >= 2.5 and len(sp) == 2
    bias, label, td = BV.verdict(sp, "2026-11-16")
    assert bias == "CE" and "big buyers" in label and len(td) == 2
    BV.CACHE["ITC"] = (__import__("time").time(), {"symbol": "ITC", "spikes": sp, "bias": bias, "label": label, "today": td})
    rows = [{"symbol": "ITC", "side": "CE", "kind": "Long Built Up", "oi_chg_pct": 2.5, "vr": 1.6, "pct": 1.0},
            {"symbol": "ITC", "side": "PE", "kind": "Short Built Up", "oi_chg_pct": 2.5, "vr": 1.6, "pct": -1.0}]
    R = {r["side"]: r for r in BPL.radar(rows, [], [], [], (120, 80), 0.3)}
    assert R["CE"]["score"] - R["PE"]["score"] >= 30 and any("🐋" in w for w in R["CE"]["why"]) and R["CE"]["bigvol"]
    BV.CACHE.clear()


def test_v115_whole_market_sweep_feed_and_strike():
    from krt import bigvol as BV
    BV.CACHE.clear(); BV.FEED.clear(); BV.SW.update(cursor=0, pushed=set())
    idx = pd.date_range("2026-11-17 13:55", periods=30, freq="5min")

    def mk(buy):
        df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0}, index=idx)
        df.iloc[26, [3, 4]] = [100.9 if buy else 99.1, 9000]
        return df

    class AG:
        n = 0

        def candles(self, ex, tok, iv, a, b):
            AG.n += 1
            return mk(tok == "1")
    xp = str((pd.Timestamp.now() + pd.Timedelta(days=20)).date())          # a future expiry (the fixed date went stale)
    inst = {"fno": ["ITC", "TCS"], "eq": {"ITC": "1", "TCS": "2"},
            "opts": {"ITC": [["t1", "ITC25NOV300CE", xp, 300.0, "CE", 1600, "NFO"], ["t2", "ITC25NOV300PE", xp, 300.0, "PE", 1600, "NFO"]],
                     "TCS": [["t3", "TCS25NOV100PE", xp, 100.0, "PE", 175, "NFO"]]}}
    sent = []
    now = pd.Timestamp("2026-11-17 16:20")
    BV.sweep(AG(), inst, now, send=lambda *a: sent.append(a))
    R = BV.feed_report()
    by = {r["symbol"]: r for r in R["rows"]}
    assert by["ITC"]["side"] == "BUY" and by["ITC"]["opt"]["side"] == "CE" and by["ITC"]["opt"]["strike"] == 300
    assert by["TCS"]["side"] == "SELL" and by["TCS"]["opt"]["side"] == "PE" and by["TCS"]["date"] == "2026-11-17"
    assert R["summary"]["buy"] == 1 and R["summary"]["sell"] == 1 and len(sent) == 2
    n0 = AG.n
    BV.sweep(AG(), inst, now + pd.Timedelta(minutes=2))
    assert AG.n == n0                                      # no re-fetch until a new 5-min candle closes
    BV.CACHE.clear(); BV.FEED.clear()


def test_v116_jarvis_brain_regime_learning_mistakes_levels_ask():
    from krt import jarvis_brain as JB
    assert JB.regime(0.6, (150, 60), "TRENDING UP")["label"] == "TRENDING UP"
    assert JB.regime(0.54, (76, 117))["label"] == "VOLATILE"
    assert JB.regime(0.05, (100, 100))["label"] == "RANGE"
    calls = []
    for i in range(20):
        calls.append({"id": f"a{i}", "date": "2026-11-1%d" % (i % 9), "time": "10:10", "symbol": "SBIN", "side": "CE", "source": "Index OI", "kind": "INTRADAY",
                      "regime": "TRENDING UP", "status": "T1 HIT" if False else ("TRAIL SL" if i % 4 else "SL HIT"), "pnl_lot": 1500 if i % 4 else -1000, "vol_ratio": 2.6})
        calls.append({"id": f"b{i}", "date": "2026-11-1%d" % (i % 9), "time": "10:10", "symbol": "TCS", "side": "CE", "source": "Top Movers", "kind": "MOVERS",
                      "regime": "TRENDING UP", "status": "SL HIT", "pnl_lot": -2000, "vol_ratio": 1.2, "mfe_pct": 0.5})
    M, L = JB.learn(calls)
    use, avoid = JB.for_regime(M, "TRENDING UP")
    assert use[0]["module"] == "Index OI" and avoid[0]["module"] == "Top Movers"
    assert any(x["factor"] == "volume" and x["value"] == "<1.5×" and x["pts"] < 0 for x in L)
    d_bad, notes = JB.adjust({"source": "Top Movers", "symbol": "TCS", "side": "CE", "vol_ratio": 1.1, "time": "10:30"}, L, M, "TRENDING UP")
    d_good, _ = JB.adjust({"source": "Index OI", "symbol": "SBIN", "side": "CE", "vol_ratio": 2.8, "time": "10:30"}, L, M, "TRENDING UP")
    assert d_bad < 0 and d_good > d_bad + 10 and notes
    mj = JB.mistakes([dict(calls[1], date="2026-11-17")], "2026-11-17", {"Top Movers"})
    assert mj["n"] == 1 and {"low volume", "weak module", "no follow-through"} <= set(mj["rows"][0]["tags"]) and mj["next_time"]
    m = JB.level_map("ITC", 294.55, {"PDH": 285.3, "PDL": 282.1, "PWH": 290.25, "PWL": 277.9, "PMH": 269.8, "PML": 252.8}, (286.85, 283.85, 1))
    assert m["priority"].startswith("Above PDH+PWH+PMH") and m["bias"] == "CE" and m["buy_above"] == 290.25 and m["qty"] > 0
    JB.STATE.update(regime=JB.regime(0.6, (150, 60)), matrix=M, lessons=L, use=use, avoid=avoid, levels={"ITC": m}, mistakes=mj, ctx={})
    assert "TRENDING UP" in JB.answer("market today?") and "Index OI" in JB.answer("which strategy should I use")
    assert "BUY ABOVE" in JB.answer("ITC levels?") and "SL hits" in JB.answer("my mistakes")


def test_v117_index_oi_early_veto_and_verdict(fs):
    from krt import jarvis_brain as JB
    c = _c(symbol="NIFTY", kind="INTRADAY", source="Index OI", time="09:30", side="PE")
    assert CL.quality_v6(dict(c), pd.Timestamp(f"{DAY} 09:30")) is None or CL.quality_v6(dict(c), pd.Timestamp(f"{DAY} 09:30"))[0] != "Q_OPEN_NOISE"
    orb = _c(kind="INTRADAY", source="5-min ORB", time="09:30")
    assert CL.quality_v6(dict(orb), pd.Timestamp(f"{DAY} 09:30"))[0] == "Q_OPEN_NOISE"
    JB.STATE.update(avoid=[{"module": "👑 Money Machine", "exp": -389, "n": 10}], regime={"label": "TRENDING UP"}, regime_used="TRENDING UP", lessons=[])
    assert "loses in a TRENDING UP market" in JB.veto({"source": "👑 Money Machine", "symbol": "ANGELONE", "side": "CE"})
    assert "loses" in CL.market_ok({"source": "👑 Money Machine", "symbol": "ANGELONE", "side": "CE", "vol_ratio": 4})
    ok = {"val": {"decision": "APPROVE", "warns": []}, "score": 82, "module": "Index OI", "symbol": "NIFTY", "side": "PE", "why": ["PCR 0.65"]}
    assert JB.verdict(ok)[0] == "TAKE"
    assert JB.verdict(dict(ok, score=60, val={"decision": "DOWNGRADE", "warns": ["volume"]}))[0] == "WAIT"
    assert JB.verdict(dict(ok, val={"decision": "REJECT", "fails": ["Entry still valid"]}))[0] == "DON'T TAKE"
    assert JB.verdict(dict(ok, module="👑 Money Machine"))[0] == "DON'T TAKE"
    JB.STATE.update(avoid=[], regime=None, regime_used=None)


def test_v118_advance_candidates_and_5min_spikes():
    from krt import advance as ADV, bigvol as BV
    idx = pd.date_range("2026-11-17 09:15", periods=40, freq="5min")
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0}, index=idx)
    df.iloc[0, 4] = 50000                                   # opening candle — must be ignored
    df.iloc[30, [3, 4]] = [100.9, 6000]
    sp = BV.spikes(df)
    assert len(sp) == 1 and sp[0]["time"].endswith("11:45") and sp[0]["low"] == 99.0
    bv = {"spikes": sp}
    oi = [{"symbol": "PGEL", "side": "CE", "kind": "Long Built Up", "oi_chg_pct": 3.1}]
    now = pd.Timestamp("2026-11-17 12:05")
    rows, watch = ADV.candidates(oi, lambda s: bv, {"PGEL": {"ltp": 100.6, "pct": 1.2, "vol_ratio": 2.2}}, now)
    assert len(rows) == 1 and rows[0]["sl"] == round(99.0 * 0.998, 2) and rows[0]["big"][0]["mult"] >= 3
    rows, watch = ADV.candidates(oi, lambda s: bv, {"PGEL": {"ltp": 103.0, "pct": 4.0}}, now)
    assert not rows and watch and "late" in " ".join(watch[0]["why_not"])
    rows, _ = ADV.candidates(oi, lambda s: bv, {"PGEL": {"ltp": 100.6, "pct": 1.2}}, pd.Timestamp("2026-11-17 14:30"))
    assert rows == []                                        # spike older than 60 min → not fresh


def test_v119_combo_alert(monkeypatch):
    import server
    from krt import bigvol as BV, calls as CL
    from tests.test_mannan import FakeStore
    f = FakeStore()
    monkeypatch.setattr(CL, "STORE", f)
    day = str(server.now_ist().date())
    f.data["calls"] = {"c1": {"id": "c1", "date": day, "symbol": "POLICYBZR", "side": "PE", "strike": 1040, "status": "OPEN", "kind": "INTRADAY",
                              "source": "5-min ORB", "entry": 30, "sl": 25, "targets": [35], "ltp": 31}}
    BV.FEED.clear()
    BV.FEED["POLICYBZR|x"] = {"symbol": "POLICYBZR", "exch": "NSE", "time": f"{day} 13:40", "date": day, "side": "SELL", "mult": 3.2, "price": 1044.6, "opt": None}
    BV.FEED["TCS|x"] = {"symbol": "TCS", "exch": "NSE", "time": f"{day} 13:40", "date": day, "side": "BUY", "mult": 3.2, "price": 2400, "opt": None}
    C = server.jv_combos()
    assert len(C) == 1 and C[0]["txt"].startswith("BUY POLICYBZR 1040 PE") and "big SELL 3.2× at 13:40" in C[0]["txt"]
    sent = []
    server.jv_combo_push(lambda *a: sent.append(a)); server.jv_combo_push(lambda *a: sent.append(a))
    assert len(sent) == 1 and server.jv_alerts()[0]["k"] == "combo"
    BV.FEED.clear()
