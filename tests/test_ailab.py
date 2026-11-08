"""🧪 AI Lab tests — strike selector · level lab · pre-breakout · battle lab · learning · regime brain · OI flow."""
import numpy as np
import pandas as pd

from krt import ailab as AL
from krt.optmath import bs, iv


def _inst(spot, side="CE", step=10, lot=1250, exp="2026-11-25"):
    rows = [[f"T{k}", f"VBL{k}{side}", exp, float(k), side, lot, "NFO"] for k in range(int(spot) - 50, int(spot) + 60, step)]
    return {"opts": {"VBL": rows}, "eq": {"VBL": "1"}}


class Ag:
    def __init__(self, spot, now, bad=None):
        self.spot, self.now, self.bad = spot, now, bad or set()

    def quotes(self, d):
        out = {}
        for ex, toks in d.items():
            for t in toks:
                K = float(t[1:])
                p = max(bs(self.spot, K, 20 / 365, 0.3, "CE"), 0.1)
                sp = 0.25 if t not in self.bad else p * 0.08
                out[t] = {"ltp": round(p, 2), "depth": {"buy": [{"price": round(p - sp / 2, 2)}], "sell": [{"price": round(p + sp / 2, 2)}]},
                          "opnInterest": 250000, "tradeVolume": 90000}
        return out


def test_best_strike_prefers_liquid_near_atm(monkeypatch):
    import krt.instruments as I
    monkeypatch.setattr(I, "ist_today", lambda: pd.Timestamp("2026-11-05").date())
    now = pd.Timestamp("2026-11-05 11:00")
    r = AL.best_strike(Ag(430, now, bad={"T430"}), _inst(430), "VBL", "CE", 430, now, 426, 440)
    assert r["best"] and r["best"]["strike"] != 430                 # ATM illiquid (spread 8%) → வேறு strike
    assert 0.35 <= r["best"]["delta"] <= 0.85 and r["best"]["rr"] and r["explain"]          # ITM-ம் சரி (spread % குறைவு)
    far = [x for x in r["rows"] if x["strike"] >= 450]
    assert far and all(x["score"] <= r["best"]["score"] for x in far)
    assert {x["moneyness"] for x in r["rows"]} >= {"ITM", "OTM"}


def _daily(path, vol=1e6, start="2025-10-01"):
    idx = pd.bdate_range(start=start, periods=len(path))
    c = np.asarray(path, float)
    return pd.DataFrame({"open": c * 0.998, "high": c * 1.006, "low": c * 0.994, "close": c, "volume": vol}, index=idx)


def test_level_rejected_history_leans_pe():
    # 430-க்கு 6 தடவை வந்து எல்லாம் reject (high தொட்டு கீழே close)
    p = []
    for k in range(6):
        p += list(np.linspace(415, 428.5, 8)) + [426, 420, 416]
    d1 = _daily(p)
    d1.loc[d1["close"] >= 428, "high"] = 431.0
    r = AL.analyse_level("VBL", 430, d1, None, ltp=427, vr=1.1)
    assert r["hist"]["daily"]["reject"] >= 5 and r["p_reject"] >= 60 and r["lean"] == "PE"
    assert "probability" in r["honest"] and r["pos"] == "BELOW"


def test_level_breaks_and_holds_5m_leans_ce():
    rows, t = [], pd.Timestamp("2026-10-20 09:15")
    for day in range(10):
        base = 425
        for i in range(75):
            ts = t + pd.Timedelta(days=day) + pd.Timedelta(minutes=5 * i)
            px = base + (i / 75) * 3 if i < 40 else 431 + (i - 40) * 0.25        # 430 தாண்டி ஏறுது
            rows.append((ts, px - 0.2, px + 0.4, px - 0.4, px, 1000))
    m5 = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume"]).set_index("t")
    d1 = _daily(np.linspace(380, 432, 60))
    r = AL.analyse_level("VBL", 430, d1, m5, ltp=433, vr=2.0)
    assert r["hist"]["m5"]["n"] >= 5 and r["hist"]["m5"]["held"] >= r["hist"]["m5"]["n"] - 1 and r["lean"] == "CE"
    assert r["pos"] == "ABOVE" and "CE trigger" in r["now"]


def test_prebreak_detects_compression():
    c = list(np.linspace(100, 120, 47)) + list(120 + np.sin(np.arange(8)) * 0.2)          # wide trend பிறகு கடைசி 8 நாள் tight range
    h = [x * 1.025 for x in c[:47]] + [x + 0.3 for x in c[47:]]
    l = [x * 0.975 for x in c[:47]] + [x - 0.3 for x in c[47:]]
    v = [2e6] * 47 + [1e6] * 8
    bars = {"ABC": {"t": [str(d.date()) for d in pd.bdate_range(end="2026-11-04", periods=55)], "o": c, "h": h, "l": l, "c": c, "v": v}}
    rows = AL.prebreak_scan(bars, {"ABC": {"ltp": 120.5, "vol_ratio": 1.2}}, {"ABC": "Long Built Up"})
    assert rows and rows[0]["symbol"] == "ABC" and rows[0]["side"] == "CE" and rows[0]["comp"] < 0.75 and rows[0]["score"] >= 70
    lvl = rows[0]["level"]
    rows = AL.prebreak_scan(bars, {"ABC": {"ltp": lvl + 0.5, "vol_ratio": 2.4}}, {})
    assert rows[0]["status"] == "BREAKING"
    rows = AL.prebreak_scan(bars, {"ABC": {"ltp": lvl + 0.5, "vol_ratio": 0.9}}, {})
    assert rows[0]["status"] == "FAKE?"                                                   # volume இல்லாத break


def test_battle_lab_oos_and_brain():
    calls = []
    for i in range(40):
        calls.append({"id": f"t{i}", "source": "Top Movers", "kind": "MOVERS", "status": "T3 DONE" if i % 3 else "SL HIT", "pnl_lot": 2000 if i % 3 else -1500,
                      "date": f"2026-10-{1 + i % 28:02d}", "time": "10:30", "exit_time": f"2026-10-{1 + i % 28:02d} {10 + i % 5}:00", "regime": "TREND UP", "lot": 1,
                      "entry": 10, "exit": 12, "side": "CE", "grade": "A", "vol_ratio": 3})
        calls.append({"id": f"m{i}", "source": "V4 💎 VWAP Mean Reversion", "kind": "V4", "status": "SL HIT" if i % 3 else "T1 HIT", "pnl_lot": -1800 if i % 3 else 900,
                      "date": f"2026-10-{1 + i % 28:02d}", "time": "11:00", "exit_time": f"2026-10-{1 + i % 28:02d} {11 + i % 4}:30", "regime": "TREND UP", "lot": 1,
                      "entry": 10, "exit": 8, "side": "PE", "grade": "B", "vol_ratio": 1.5})
    import krt.ai as ai
    ai.charges, orig = (lambda c: 0), ai.charges
    try:
        B = AL.battle_lab(calls)
        L = AL.learning(calls)
    finally:
        ai.charges = orig
    fam = {r["family"]: r for r in B["rows"]}
    assert fam["Trend / Momentum"]["oos"]["n"] == 12 and fam["Trend / Momentum"]["oos"]["net"] > 0
    assert B["best"]["TRENDING"][0]["family"] == "Trend / Momentum"
    assert any(r["value"] == "Trend / Momentum" for r in L["good"]) and any(r["value"] == "VWAP / Mean-Rev" for r in L["bad"])
    assert any("⛔" in t for t in L["tips"]) and any("✅" in t for t in L["tips"])
    br = AL.regime_brain({"index": [{"index": "NIFTY", "pct": 0.9}]}, {"dir": "UP", "vel": 0.05}, B)
    assert br["regime"] == "TRENDING" and br["use"][0] == "Trend / Momentum" and br["source"] == "history"


def test_oi_flow_meaning():
    f = AL.oi_flow({"Long Built Up": [{"symbol": "ABC", "pct": 3.1, "oi": 1200, "oi_chg": 200}]}, {"ABC": {"vol_ratio": 2.0}})
    assert f[0]["side"] == "CE" and f[0]["oi_chg_pct"] == 20.0 and f[0]["strong"] and "bullish" in f[0]["meaning"]


def test_mannan_iv_unit_fixed():
    src = open(AL.__file__.replace("ailab.py", "mannan.py"), encoding="utf-8").read()
    assert "iv = iv / 100 if iv else None" in src


def _reject_daily():
    p = []
    for k in range(6):
        p += list(np.linspace(415, 428.5, 8)) + [426, 420, 416]
    d1 = _daily(p)
    d1.loc[d1["close"] >= 428, "high"] = 431.0
    return d1


def test_call_verdict_ce_bad_history_and_late():
    c = {"id": "x", "symbol": "VBL", "side": "CE", "ul_price": 430, "strike": 435, "time": "10:30"}
    v = AL.call_verdict(c, _reject_daily(), None, 431, 1.2)
    assert v["hist"] == "BAD" and "fail" in v["txt"] and not v["late"] and "430 மேல்" in v["trigger"]
    v = AL.call_verdict(c, _reject_daily(), None, 445, 1.2)
    assert v["late"] and v["beyond"] > 3


def test_call_verdict_pe_mirror_support_break_holds():
    # 400 support-ஐ ஒவ்வொரு தடவையும் கீழே உடைச்சு கீழேயே இருக்கு (PE-க்கு நல்ல history)
    p = []
    for k in range(6):
        p += list(np.linspace(420, 404, 8)) + [396, 392, 395, 405, 412, 418]
    d1 = _daily(p)
    c = {"id": "y", "symbol": "ABC", "side": "PE", "ul_price": 400, "strike": 400}
    v = AL.call_verdict(c, d1, None, 399.5, 1.6)
    assert v["hist"] == "OK" and v["p_hold"] >= 55 and "கீழ்" in v["trigger"]


def test_autolab_run_budget_and_cache(monkeypatch):
    from krt import fullscan as FS
    AL.SYMC.clear(); AL.AUTO.clear()
    monkeypatch.setattr(FS, "C", {"live_q": {}})
    calls_made = []

    class Ag:
        def candles(self, ex, tok, iv, a, b):
            calls_made.append((tok, iv))
            return _reject_daily()
    now = pd.Timestamp("2026-11-09 11:00")
    calls = [{"id": f"2026-11-09|X|S{i}", "date": "2026-11-09", "symbol": f"S{i}", "side": "CE", "ul_price": 430, "status": "OPEN", "exch": "NFO",
              "pink": i == 3, "time": "10:00"} for i in range(5)]
    inst = {"eq": {f"S{i}": str(i) for i in range(5)}}
    AL.autolab_run(Ag(), inst, now, calls, max_fetch=2)
    assert len(AL.AUTO) == 2 and any(k.endswith("S3") for k in AL.AUTO)        # pink முதலில் · ஒரு run-க்கு 2 symbols
    n1 = len(calls_made)
    AL.autolab_run(Ag(), inst, now + pd.Timedelta(minutes=1), calls, max_fetch=2)
    assert len(AL.AUTO) == 4 and len(calls_made) == n1 + 4                     # புது 2 symbols மட்டும் fetch (cache வேலை செய்யுது)
