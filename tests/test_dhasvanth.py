"""🏹 DHASVANTH — 9.5 checklist grading for the 5 best strategies + 📅 results calendar upgrade."""
import threading

import numpy as np
import pandas as pd

from krt import dhasvanth as DH

DAY = "2026-11-18"          # a Wednesday


def _c(i=0, **o):
    base = {"id": f"{DAY}|X|{i}", "date": DAY, "time": "09:40", "signal_time": f"{DAY} 09:40", "symbol": "SBIN", "strike": 800, "side": "CE",
            "expiry": "2026-11-25", "entry": 20.0, "sl": 16.0, "sl0": 16.0, "targets": [24, 28, 32], "lot": 500, "status": "OPEN", "exch": "NFO",
            "kind": "INTRADAY", "source": "5-min ORB", "vol_ratio": 2.2, "ul_price": 801.0, "ul_sl": 796.0, "ul_targets": [804.0, 808.0, 812.0], "pnl_lot": 0}
    base.update(o)
    return base


def _ctx(calls, **o):
    return {"calls": calls, "live_q": {"SBIN": {"ltp": 801, "open": 798, "vol_ratio": 2.2}}, "charts": {}, "levels": {"SBIN": {"PDH": 830.0}},
            "mdir": "UP", "crash": {}, "results": [], "idx": {}, "bars": {}, "trend": "TRENDING UP",
            "sector_of": {"SBIN": {"name": "Bank", "score": 62}}, **o}


def test_strategy_mapping():
    assert DH.strat_of({"kind": "GU-CLASSIC"}) == "GU"
    assert DH.strat_of({"source": "V4 ⚡ ICT Silver Bullet"}) == "SB"
    assert DH.strat_of({"source": "🛢 ⚡ ICT Silver Bullet"}) == "SB"
    assert DH.strat_of({"source": "Index OI"}) == "IOI"
    assert DH.strat_of({"source": "🛢 🥈 Order Flow + Profile"}) == "OF"
    assert DH.strat_of({"source": "5-min ORB"}) == "ORB"
    assert DH.strat_of({"source": "Breakout/Breakdown"}) is None
    assert DH.market_of({"exch": "MCX", "symbol": "CRUDEOIL"}) == "Commodity" and DH.market_of({"symbol": "NIFTY"}) == "Index"


def test_orb_clean_call_is_pro_and_rules_are_measured():
    c = _c()
    ev = DH.evaluate(c, _ctx([c]), pd.Timestamp(f"{DAY} 09:40"))
    names = {r["name"]: r for r in ev["rules"]}
    assert names["Range size 0.35%–1.5%"]["ok"] is True                      # 4 pts on 800 = 0.5%
    assert names["Retest entry (not chased)"]["ok"] is True                  # price 801 vs level 800
    assert names["Next level ≥2R after costs"]["ok"] is True                 # PDH 830 far away
    assert ev["grade"] == "9.5 PRO" and ev["rating"] == 10.0
    assert ev["size"]["lots"] == 1 and "₹2,000/lot" in ev["size"]["txt"]


def test_orb_second_breakout_late_and_chased_are_skipped():
    first = _c(0)
    second = _c(1, time="10:05", signal_time=f"{DAY} 10:05")
    ev = DH.evaluate(second, _ctx([first, second]), pd.Timestamp(f"{DAY} 10:05"))
    assert ev["grade"] == "SKIP" and "First breakout per stock per day" in ev["crit_fail"]
    late = _c(2, symbol="SBIN", time="12:10", signal_time=f"{DAY} 12:10")
    ev = DH.evaluate(late, _ctx([late]), pd.Timestamp(f"{DAY} 12:10"))
    assert "Before 11:45 AM" in ev["crit_fail"]
    chased = _c(3, ul_price=808.0)
    ev = DH.evaluate(chased, _ctx([chased]), pd.Timestamp(f"{DAY} 09:40"))
    assert {r["name"]: r for r in ev["rules"]}["Retest entry (not chased)"]["ok"] is False and ev["grade"] != "9.5 PRO"


def test_grade_rules_missing_data_never_counts():
    R = DH.R
    assert DH.grade([R("a", True, ""), R("b", True, "", True)])["grade"] == "9.5 PRO"
    assert DH.grade([R("a", True, ""), R("b", False, "", True)])["grade"] == "SKIP"
    g = DH.grade([R("a", True, ""), R("b", None, ""), R("c", None, ""), R("d", None, "")])
    assert g["grade"] == "TAKE" and g["known"] == 1                           # 100% of known but only 25% coverage → not PRO
    assert DH.grade([R("a", None, "")])["grade"] == "NO DATA"


def _frames(day=DAY, up=True):
    idx = pd.date_range(f"2026-11-17 09:15", f"2026-11-17 15:29", freq="1min").append(pd.date_range(f"{day} 09:15", f"{day} 11:00", freq="1min"))
    n = len(idx)
    base = 24000 + np.cumsum(np.where(np.arange(n) % 7 < 4, 1.0, -0.6)) * (1 if up else -1)
    df = pd.DataFrame({"open": base - 0.5, "high": base + 2, "low": base - 2, "close": base + 0.5, "volume": 1000.0}, index=idx)
    from krt import v4 as V
    fr = {"1M": df, "3M": V._resample(df, "3min"), "5M": V._resample(df, "5min"), "15M": V._resample(df, "15min"), "1H": V._resample(df, "60min")}
    fr["5M"]["fvol"] = fr["5M"]["volume"]
    return fr


def test_silver_bullet_window_and_failed_streak():
    from krt import v4 as V
    V.FR["NIFTY"] = (pd.Timestamp(f"{DAY} 11:00"), _frames())
    ok = _c(10, symbol="NIFTY", source="V4 ⚡ ICT Silver Bullet", kind="V4", time="10:12", signal_time=f"{DAY} 10:12", ul_price=None, vol_ratio=None)
    ev = DH.evaluate(ok, _ctx([ok]), pd.Timestamp(f"{DAY} 10:12"))
    names = {r["name"]: r for r in ev["rules"]}
    assert names["First 25 min of the window"]["ok"] is True
    assert names["HTF bias (15m / 1H)"]["ok"] is not None                    # computed from the cached frames, not guessed
    late = dict(ok, id="L", time="10:40", signal_time=f"{DAY} 10:40")
    ev = DH.evaluate(late, _ctx([late]), pd.Timestamp(f"{DAY} 10:40"))
    assert ev["grade"] == "SKIP" and "First 25 min of the window" in ev["crit_fail"]
    losers = [dict(ok, id=f"P{i}", date="2026-11-17", signal_time=f"2026-11-17 1{i}:00", status="SL HIT", pnl_lot=-900) for i in range(2)]
    ev = DH.evaluate(ok, _ctx(losers + [ok]), pd.Timestamp(f"{DAY} 10:12"))
    assert "Last 2 same-direction Silver Bullets not both failed" in ev["crit_fail"]


def test_index_oi_rate_walls_and_pcr():
    DH.HIST.clear()
    t0 = pd.Timestamp(f"{DAY} 10:00")
    for k in range(0, 35, 5):                 # puts written faster, support moving up
        DH.HIST.setdefault("NIFTY", []).append((t0 + pd.Timedelta(minutes=k), 1_000_000 + k * 1000, 1_000_000 + k * 6000, 24000 + (k >= 20) * 100, 24300, 24150))
    c = _c(20, symbol="NIFTY", source="Index OI", time="10:34", signal_time=f"{DAY} 10:34", vol_ratio=None)
    ctx = _ctx([c], idx={"NIFTY": {"pcr": 1.3}}, live_q={f"S{i}": {"pct": 1 if i < 30 else -1} for i in range(40)})
    ev = DH.evaluate(c, ctx, pd.Timestamp(f"{DAY} 10:34"))
    n = {r["name"]: r for r in ev["rules"]}
    assert n["OI change last 15–30 min supports side"]["ok"] is True
    assert n["Wall shifted in trade direction"]["ok"] is True
    assert n["5-min + 15-min OI agree"]["ok"] is True
    assert n["Breadth (advance / decline) agrees"]["ok"] is True
    assert n["PCR extreme only with price confirmation"]["ok"] is True       # 1.3 = normal tilt
    ev = DH.evaluate(c, dict(ctx, idx={"NIFTY": {"pcr": 1.8}}), pd.Timestamp(f"{DAY} 10:34"))
    assert {r["name"]: r for r in ev["rules"]}["PCR extreme only with price confirmation"]["ok"] in (True, False)


def test_order_flow_event_filter_and_half_size():
    c = _c(30, symbol="CRUDEOIL", exch="MCX", source="🛢 🥈 Order Flow + Profile", kind="MCX", time="21:10", signal_time=f"{DAY} 21:10", lot=100)
    ev = DH.evaluate(c, _ctx([c]), pd.Timestamp(f"{DAY} 21:10"))           # Wed: EIA 10:30 New York = 21:00 IST (winter)
    n = {r["name"]: r for r in ev["rules"]}
    assert n["No major data release ±30 min"]["ok"] is False and "EIA crude" in n["No major data release ±30 min"]["why"]
    assert n["Real aggressor delta"]["ok"] is False and "halved" in ev["size"]["txt"] or ev["size"]["lots"] == 0
    assert ev["grade"] == "SKIP"


def test_run_freezes_grade_and_report():
    D = {"calls": {}}
    a, b = _c(40), _c(41, symbol="TCS", status="SL HIT", pnl_lot=-2000)
    D["calls"] = {a["id"]: a, b["id"]: b}
    sent = []
    n = DH.run(D, _ctx(list(D["calls"].values())), pd.Timestamp(f"{DAY} 09:41"), send=lambda *x: sent.append(x))
    assert n == 2 and set(D["dhas"]) == {a["id"], b["id"]} and len(sent) == 1        # push only for an OPEN 9.5 PRO
    D["dhas"][a["id"]]["grade"] = "FROZEN"
    DH.run(D, _ctx(list(D["calls"].values())), pd.Timestamp(f"{DAY} 09:45"))
    assert D["dhas"][a["id"]]["grade"] == "FROZEN"                                   # never re-graded
    D["dhas"][a["id"]]["grade"] = "9.5 PRO"
    R = DH.report(D, pd.Timestamp(f"{DAY} 09:45"))
    orb = next(x for x in R["boxes"] if x["key"] == "ORB")
    assert [x["key"] for x in R["boxes"]] == ["GU", "SB", "IOI", "OF", "ORB"]
    assert orb["today"][0]["id"] == a["id"] and R["top"][0]["id"] == a["id"] and orb["stats"]["all"]["n"] == 1 and orb["ai"]


def test_dhas_run_no_deadlock():
    import server
    th = threading.Thread(target=lambda: server.dhas_run(pd.Timestamp(f"{DAY} 10:30")), daemon=True)
    th.start()
    th.join(20)
    assert not th.is_alive(), "dhas_run deadlocked on CALLS_LOCK"
    assert isinstance(server.dhas_state(), dict)


# ───────── results calendar ─────────
def test_calendar_sources_merge_and_fallback(monkeypatch):
    from krt import events as EV

    class S:
        dirty = False
        d = {"calls": {}}

        def load(self):
            return self.d
    st = S()
    EV.CACHE.clear()
    monkeypatch.setattr(EV, "SOURCES", (("NSE calendar", lambda f: (_ for _ in ()).throw(RuntimeError("403"))),
                                        ("BSE forthcoming", lambda f: [{"symbol": "HAL", "date": "2026-11-25", "src": "BSE"}])))
    C = EV.refresh_calendar(st, {"HAL"}, [], pd.Timestamp(DAY).date())
    assert "HAL|2026-11-25" in C and EV.STATE["src"]["NSE calendar"]["ok"] is False and "NSE calendar" in EV.STATE["nse_err"]
    assert EV.fno_names({}, {"opts": {"HAL": [], "NIFTY": []}}) == {"HAL"}


def test_outlook_has_expectation_and_advance():
    from krt import events as EV
    cl = list(np.linspace(100, 112, 30))
    o = EV.outlook({"r20": 8, "near_high": True, "oi": "Long Built Up", "sector": {"name": "Defence", "score": 70}}, cl, [])
    assert o["lean"] == "LEAN UP" and o["side"] == "CE" and o["expect"].startswith("POSITIVE") and o["advance"].startswith("Advance view: CE")
    o = EV.outlook({"r20": 0}, [100] * 30, [])
    assert o["side"] is None and "no side" in o["advance"]
