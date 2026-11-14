"""v92 — screenshot bugs: Money Machine strike change / falling premium · pre-breakout late · OI வேகம் · ENTER list · DSK own loss."""
import pandas as pd

from krt import ailab as AL
from krt import fullscan as FS
from tests.test_mannan import FakeStore


def _fs(monkeypatch):
    from krt import calls as CL, store as SM
    fs = FakeStore()
    for m in (CL, SM):
        monkeypatch.setattr(m, "STORE", fs)
    return fs


def test_mm_strike_change_resets_and_falling_premium_is_weak(monkeypatch):
    _fs(monkeypatch)
    FS.C.pop("mm_first", None)
    t = pd.Timestamp("2026-11-09 10:28")
    p = {"symbol": "DIVISLAB", "side": "CE", "price": 11710, "score": 85, "option": {"ltp": 407.65, "strike": 11400}, "rp": {"sl": 340, "targets": [450, 480, 510]}}
    FS.mm_live([p], t)
    p2 = {**p, "option": {"ltp": 238.0, "strike": 11600}, "rp": {"sl": 200, "targets": [260, 280, 300]}}
    FS.mm_live([p2], t + pd.Timedelta(hours=1, minutes=36))
    L = p2["live"]
    assert L["strike"] == 11600 and L["first_opt"] == 238.0 and "strike 11400 → 11600" in L["text"]   # −41% பொய் ஒப்பீடு இல்லை
    assert L["targets"] == [260, 280, 300]                                                          # targets entry-க்கு மேல்
    g = {"symbol": "GLENMARK", "side": "CE", "price": 2694, "score": 90, "option": {"ltp": 78.1, "strike": 2700}, "rp": {"sl": 59.4, "targets": [88, 96, 104]}}
    FS.mm_live([g], t)
    g2 = {**g, "option": {"ltp": 66.05, "strike": 2700}, "rp": {"sl": 50, "targets": [71.4, 76.7, 82.05]}}
    FS.mm_live([g2], t + pd.Timedelta(hours=1))
    assert g2["live"]["status"] == "WEAK" and g2["live"]["targets"] == [88, 96, 104] and g2["live"]["ref"] == 78.1   # முன்னாடி "✅ OK" சொன்னுச்சு


def test_prebreak_breaking_turns_late(monkeypatch):
    AL.STATE["pb_first"] = {}
    rows = [{"symbol": "BANKINDIA", "side": "CE", "level": 140.49, "ltp": 141.6, "dist": 0.8, "score": 70, "status": "BREAKING", "why": ["x"], "vr": 2}]
    monkeypatch.setattr(AL, "prebreak_scan", lambda *a, **k: [dict(r) for r in rows])
    monkeypatch.setattr(FS, "C", {"bars": {}, "live_q": {}})
    AL.prebreak_run(None, {}, pd.Timestamp("2026-11-09 10:14"), live=False)
    assert AL.STATE["prebreak"]["rows"][0]["status"] == "BREAKING"
    AL.prebreak_run(None, {}, pd.Timestamp("2026-11-09 12:04"), live=False)
    r = AL.STATE["prebreak"]["rows"][0]
    assert r["status"] == "LATE" and "10:14-க்கே break" in r["why"][0]


def test_oi_trend_buyers_increase_and_slow():
    AL.OIH.clear()
    assert AL.oi_trend("X", "Long Built Up", 1000, now=0)[0] is None
    d, t = AL.oi_trend("X", "Long Built Up", 1030, now=700)
    assert d == 3.0 and "buyers கூடிக்கிட்டே" in t
    d, t = AL.oi_trend("X", "Long Built Up", 1032, now=1400)
    assert "மெதுவா" in t or "கூடிக்கிட்டே" in t
    AL.OIH.clear()
    AL.oi_trend("Y", "Short Built Up", 1000, now=0)
    assert "sellers கூடிக்கிட்டே" in AL.oi_trend("Y", "Short Built Up", 1050, now=700)[1]


def test_enter_scan_gives_strike_plan_confidence(monkeypatch):
    from krt import ai
    monkeypatch.setitem(ai.STATE, "risk", {"dir": "DOWN"})
    AL.ENT.clear(); AL.OIH.clear()
    monkeypatch.setattr(FS, "C", {"live_q": {"BOSCHLTD": {"ltp": 49410, "vol_ratio": 2.02, "pct": -2.06}}})
    monkeypatch.setitem(AL.STATE, "prebreak", {"rows": []})
    full = {"oi_buildup": {"Short Built Up": [{"symbol": "BOSCHLTD", "pct": -2.06, "oi": 1027, "oi_chg": 27}]}}
    monkeypatch.setattr(AL, "best_strike", lambda *a, **k: {"best": {"strike": 49000, "expiry": "2026-11-23", "lot": 25, "token": "77", "exch": "NFO",
                        "contract": "BOSCH49000PE", "moneyness": "OTM", "delta": 0.42, "theta_pct": 3.1, "iv": 24, "rr": 2.4, "score": 82, "ltp": 1255.4}, "explain": "OTM 49000 PE"})
    import krt.optmath as OM
    monkeypatch.setattr(OM, "plan", lambda *a, **k: {"entry": 1255.4, "sl": 1155.0, "targets": [1335, 1415, 1495], "risk": 2510, "risk_ok": True})

    class Ag:
        def quotes(self, d):
            return {"77": {"ltp": 1262.0}}
    E = AL.enter_scan(Ag(), {}, pd.Timestamp("2026-11-09 12:04"), full, [])
    r = E["rows"][0]
    assert r["symbol"] == "BOSCHLTD" and r["strike"] == 49000 and r["status"] == "OK" and r["targets"] == [1335, 1415, 1495]
    assert 50 <= r["confidence"] <= 95 and any("Market" in p[0] for p in r["conf_parts"])


def test_dsk_not_blocked_by_other_modules_loss(monkeypatch):
    from krt import dsk as DS
    import krt.ai as ai
    monkeypatch.setattr(ai, "charges", lambda c: 0)
    day = "2026-11-09"
    calls = [{"id": f"x{i}", "date": day, "kind": "MOVERS", "status": "SL HIT", "pnl_lot": -5000} for i in range(5)]   # மற்ற modules -25,000
    nt, net, _ = DS.notrade(calls, pd.Timestamp(f"{day} 12:00"), {}, "SIDEWAYS")
    assert not nt and net == 0                                                                    # DSK block ஆகாது
    calls += [{"id": f"d{i}", "date": day, "kind": "DSK", "status": "SL HIT", "pnl_lot": -2600} for i in range(2)]
    nt, net, _ = DS.notrade(calls, pd.Timestamp(f"{day} 12:30"), {}, "SIDEWAYS")
    assert not nt and net == -5200                                                            # v107: no loss stop — net still reported


def test_chain_flow_buyers_sellers(monkeypatch):
    """BANKINDIA மாதிரி: 142-ல் CE buyers, 145-ல் CE writers (தடை), 140-ல் PE writers (support)."""
    import pandas as pd
    from krt import ailab as AL
    import krt.instruments as I
    monkeypatch.setattr(I, "ist_today", lambda: pd.Timestamp("2026-11-09").date())
    rows = [[f"{t}{k}", f"BANKINDIA{k}{t}", "2026-11-25", float(k), t, 5200, "NFO"] for k in range(136, 149) for t in ("CE", "PE")]
    inst = {"opts": {"BANKINDIA": rows}}
    snap = {"oi": {r[0]: 100000.0 for r in rows}, "ltp": {r[0]: 3.0 for r in rows}}

    class Ag:
        def quotes(self, d):
            return {t: {"ltp": snap["ltp"][t], "opnInterest": snap["oi"][t], "tradeVolume": 1000} for ex, ts in d.items() for t in ts}
    AL.CHS.clear()
    now = pd.Timestamp("2026-11-09 10:00")
    AL.chain_flow(Ag(), inst, "BANKINDIA", 141.6, now, "CE")                       # baseline
    snap["oi"]["CE142"], snap["ltp"]["CE142"] = 112000.0, 3.6                     # buyers
    snap["oi"]["CE144"], snap["ltp"]["CE144"] = 130000.0, 2.7                     # CE writers (spot-ல் இருந்து 2%-க்குள்)
    snap["oi"]["PE140"], snap["ltp"]["PE140"] = 125000.0, 2.6                     # PE writers
    r = AL.chain_flow(Ag(), inst, "BANKINDIA", 141.6, now + pd.Timedelta(minutes=20), "CE")
    tag = {(x["strike"], x["type"]): x["tag"] for x in r["rows"]}
    assert tag[(142, "CE")] == "BUYERS" and tag[(144, "CE")] == "WRITERS" and tag[(140, "PE")] == "WRITERS"
    assert r["resistance"] == 144 and r["support"] == 140 and r["buyers_strike"] == 142
    assert r["verdict"].startswith("⛔") and "144" in r["verdict"]                # 144 CE writers 2%-க்குள் = தடை
    assert r["since"] == "10:00"


def test_chart_breakout_alert_once_and_invalid():
    import pandas as pd
    from krt import ailab as AL
    AL.CHALERT.clear()
    sent = []
    R = {"charts": [{"call": {"symbol": "NIFTY", "strike": 24950, "side": "CE", "entry": 72, "ltp": 75, "sl": 50.4, "targets": [95]},
                     "analysis": {"px": 24970, "up_level": 24965.65, "dn_level": 24851.85, "pattern": "Inverse head & shoulders", "advice": {"verdict": "TAKE"}}}]}
    now = pd.Timestamp("2026-11-09 12:06")
    AL.chart_alerts(R, now, lambda m, k, u: sent.append(m))
    AL.chart_alerts(R, now + pd.Timedelta(minutes=5), lambda m, k, u: sent.append(m))
    assert len(sent) == 1 and "CHART BREAKOUT" in sent[0] and "24965.65 மேல்" in sent[0]
    R["charts"][0]["analysis"]["px"] = 24840
    AL.chart_alerts(R, now + pd.Timedelta(minutes=10), lambda m, k, u: sent.append(m))
    assert len(sent) == 2 and "INVALID" in sent[1]
    R["charts"][0]["analysis"].update(px=24990, advice={"verdict": "WAIT"})       # WAIT verdict-க்கு breakout alert இல்லை
    AL.CHALERT.clear(); sent.clear()
    AL.chart_alerts(R, now, lambda m, k, u: sent.append(m))
    assert sent == []
