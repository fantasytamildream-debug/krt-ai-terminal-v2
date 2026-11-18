"""v124: recent-form module gate (hidden calls count) · module health shows hidden · guide newest-first + JARVIS says ·
movers guidance · riser building · SMC today-only + strike to watch · backfilled spikes not pushed."""
import pandas as pd

from krt import calls as CL, guide as GD, command as CMD, riser as RS, smc as S, bigvol as BV


def _c(i, src, pnl, day, shadow=False, why=None):
    return {"id": f"c{i}", "source": src, "kind": "X", "status": "SL HIT" if pnl < 0 else "TRAIL SL", "pnl_lot": pnl, "date": day, "time": "10:00",
            "shadow": shadow, "shadow_why": why, "symbol": "AAA", "side": "CE"}


def test_recent_form_counts_hidden_calls_and_skips_duplicates():
    day = str(pd.Timestamp.now(tz="Asia/Kolkata").date())
    calls = {}
    for i in range(20):                                              # hidden (watch-only) calls that now WIN
        calls[f"h{i}"] = _c(i, "ModA", 1000, day, True, "ModA has lost money … watch-only")
    for i in range(5):                                               # duplicate copies must not count
        calls[f"d{i}"] = _c(100 + i, "ModA", -9000, day, True, "AAA CE already called today — one call per stock per side")
    rf = CL.recent_form({"calls": calls})
    assert rf["ModA"]["n"] == 20 and rf["ModA"]["net"] == 20000 and rf["ModA"]["win"] == 100


def test_module_health_shows_hidden_working():
    day = "2026-11-18"
    calls = {"a": _c(1, "Volume+OI", -500, day, True, "Volume+OI lost money in its last 30 calls — watch-only")}
    calls["a"]["status"] = "OPEN"
    rows = CL.module_health({"calls": calls}, pd.Timestamp("2026-11-18 11:00"))
    r = [x for x in rows if x["source"] == "Volume+OI"][0]
    assert r["hidden"] == 1 and r["status"].startswith("🟢 working") and r["today"] == 0


def test_guide_big_newest_first_and_old_last():
    day = "2026-11-18"
    feed = [{"symbol": "OLD", "side": "BUY", "mult": 9, "price": 100, "high": 101, "low": 99, "time": f"{day} 09:30", "end": "09:35", "date": day,
             "exch": "NSE", "seen": "10:45:00", "backfill": True},
            {"symbol": "NEW", "side": "SELL", "mult": 3, "price": 100, "high": 101, "low": 99, "time": f"{day} 10:50", "end": "10:55", "date": day,
             "exch": "NSE", "seen": "10:55:15", "backfill": False}]
    early = [{"symbol": "ERL", "side": "BUY", "mult": 6, "price": 50, "time": "10:01", "full": f"{day} 10:01:05", "date": day},
             {"symbol": "ERL2", "side": "BUY", "mult": 6, "price": 50, "time": "10:57", "full": f"{day} 10:57:05", "date": day}]
    g = GD.build({"label": "BEARISH", "evidence": [], "agree": "4/5"}, {}, {}, {"pct": -0.6}, [], feed, early, [], [], [],
                 now=pd.Timestamp(f"{day} 11:00"), breadth={"up": 40, "down": 178})
    order = [b["symbol"] for b in g["big"]]
    assert order[0] == "ERL2" and order.index("NEW") < order.index("ERL") and order[-1] == "OLD"
    say = {x["k"]: x["t"] for x in g["say"]}
    assert "FALLING" in say["market"] and "PE" in say["market"]
    assert "WAIT" in say["do"]
    assert "ERL2" in say["big"] and "OLD" not in say["big"]


def test_movers_advise():
    r = {"symbol": "IREDA", "pct": 2.7, "ltp": 120.6, "vwap": 120.1, "rvol": 3.3, "pdh": 121.0, "pdl": 115, "day_pos": 80,
         "big": {"side": "SELL", "mult": 6.4, "time": "2026-11-18 10:05"}}
    a = CMD.advise(r, "BEAR", {"strike": 120.0, "expiry": "2026-11-25"})
    assert a["tag"] == "AVOID" and "SELLING" in a["txt"]
    r["big"] = None
    a = CMD.advise(r, "BEAR", {"strike": 120.0, "expiry": "2026-11-25"})
    assert a["tag"] == "BUY CE" and "120 CE" in a["txt"] and "121" in a["txt"] and "1 lot" in a["txt"]
    r["ltp"] = 119.5
    assert CMD.advise(r, None)["tag"] == "AVOID"                      # below VWAP on an up move


def test_riser_building_stage_and_hidden_rows():
    RS.H.clear()
    RS.LAST.clear()
    t0 = pd.Timestamp("2026-11-18 10:00:00")
    c = {"id": "x1", "date": "2026-11-18", "status": "OPEN", "symbol": "AAA", "strike": 100, "side": "CE", "entry": 10.0, "sl": 7.0,
         "targets": [13.0], "shadow": True, "shadow_why": "ModA lost money — watch-only"}
    sent = []
    for k, px in enumerate([10.0, 10.1, 10.2, 10.3]):
        c["ltp"] = px
        RS.scan([dict(c)], t0 + pd.Timedelta(seconds=30 * k), lambda *a: sent.append(a))
    L = RS.STATE["live"]
    assert L and L[0]["state"] == "BUILDING" and L[0]["hidden"] and "can enter" in L[0]["act"]
    assert not sent                                                  # hidden / building rows are not pushed


def test_smc_only_today_setups():
    import sys
    sys.path.insert(0, "tests")
    import test_v122 as T
    P = T.bearish_sweep_path()
    df = T.mk(P, start="2026-11-17 13:15")                            # all bars on the previous day …
    extra = T.mk([(P[-1][3],) * 4] * 3, start="2026-11-18 09:15")     # … plus 3 flat bars today
    an = S.analyse(pd.concat([df, extra]))
    assert not [s for s in S.setups(an, "AAA") if s["kind"] == "Sweep reversal"]


def test_backfill_spike_not_pushed():
    BV.FEED.clear()
    BV.SW["pushed"].clear()
    sent = []
    BV._feed_add("ZZZ", [{"time": "2026-11-18 09:30", "side": "BUY", "mult": 9.0, "price": 100.0}], "NSE", {}, 101.0,
                 lambda *a: sent.append(a), "2026-11-18", pd.Timestamp("2026-11-18 10:45"))
    r = BV.FEED["ZZZ|2026-11-18 09:30"]
    assert r["backfill"] is True and not sent
    BV.FEED.clear()
