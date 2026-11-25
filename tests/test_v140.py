"""v140: F&O stock crash / surge detector · early spikes in the Big Players table · index futures flow + crash rows in /api/ticks."""
import json

import pandas as pd

import server as S
from krt import bigvol as BV


def _h(prices, vols, t0="2026-11-25 13:00"):
    t0 = pd.Timestamp(t0)
    cum, out = 0, []
    for i, (p, v) in enumerate(zip(prices, vols)):
        cum += v
        out.append((t0 + pd.Timedelta(minutes=i), cum, p))
    return out


def test_crash_detected_and_tracked(monkeypatch):
    BV.SCR.clear()
    monkeypatch.setattr(BV, "strike_for", lambda inst, s, sd, px, mcx=False: {"strike": 380.0, "side": sd, "expiry": "2026-12-29", "token": "9"})
    prices = [400.0] * 9 + [400 - i * 0.8 for i in range(1, 12)]       # −2.2 % in 10 min, ends at the low
    vols = [1000] * 9 + [6000] * 11
    h = _h(prices, vols)
    sent = []
    r = BV._crash_check("TMPV", h, {"low": prices[-1], "high": 401}, h[-1][0], {}, 0.1, lambda *a: sent.append(a))
    assert r and r["side"] == "CRASH" and r["opt"]["side"] == "PE" and r["m10"] <= -1.2 and sent and "PE fast" in sent[0][0]
    assert BV._crash_check("TMPV", h, {"low": prices[-1]}, h[-1][0], {}, 0.1, None) is None          # 30-min cool-down
    BV.crash_track(h[-1][0] + pd.Timedelta(minutes=16), lambda s: prices[-1] * 0.99)
    assert BV.SCT["right"] == 1


def test_no_crash_when_market_falls_too_or_bounced():
    BV.SCR.clear()
    prices = [400.0] * 9 + [400 - i * 0.8 for i in range(1, 12)]
    vols = [1000] * 9 + [6000] * 11
    h = _h(prices, vols)
    assert BV._crash_check("AAA", h, {"low": prices[-1]}, h[-1][0], {}, -1.8, None) is None        # NIFTY fell as much → not stock-specific
    hb = _h(prices[:-3] + [prices[-4] + 3, prices[-4] + 4, prices[-4] + 5], vols)                      # bounced off the low
    assert BV._crash_check("BBB", hb, {"low": min(prices)}, hb[-1][0], {}, 0.0, None) is None
    hq = _h(prices, [1000] * 20)                                                                       # no volume
    assert BV._crash_check("CCC", hq, {"low": prices[-1]}, hq[-1][0], {}, 0.0, None) is None


def test_early_spikes_join_big_players_table(monkeypatch):
    day = str(S.now_ist().date())
    hm = S.now_ist().strftime("%H:%M")
    BV.EARLY["BAJFINANCE|x"] = {"symbol": "BAJFINANCE", "exch": "NSE", "date": day, "time": hm, "full": f"{day} {hm}:20", "side": "BUY", "mult": 5.6,
                                "move": 0.18, "price": 1126.55, "opt": None, "early": True}
    monkeypatch.setattr(S, "opt_quotes", lambda items, ttl=20: {})
    try:
        rows = S.bp_rows(mkt="BULL")
        r = [x for x in rows if x["symbol"] == "BAJFINANCE"][0]
        assert r["early"] and r["high"] > r["low"] and r["ai"]["tag"] != "WAIT" or "no side" not in r["ai"]["txt"]
    finally:
        BV.EARLY.pop("BAJFINANCE|x", None)


class F(S.H):
    def __init__(self, path):
        self.path, self.headers, self.out = path, {}, {}

    def _send(self, code, body, ctype=None):
        self.out = {"code": code, "body": body}


def test_ticks_carry_crash_and_index_flow():
    from krt import footprint as FP
    day = S.now_ist().strftime("%Y-%m-%d")
    BV.SCR["TMPV|13:20|CRASH"] = {"symbol": "TMPV", "date": day, "time": "13:20", "full": f"{day} 13:20:05", "side": "CRASH", "m10": -2.1, "vol": 5.0,
                                  "price": 391.2, "ul_sl": 399.5, "opt": {"strike": 390.0, "side": "PE"}, "result": None}
    FP.STATE["signals"].append({"key": "k1", "date": day, "time": "13:09", "symbol": "SENSEX", "side": "PE", "px": 83500, "stack": 4, "delta_pct": -78})
    try:
        f = F("/api/ticks")
        f.do_GET()
        B = json.loads(f.out["body"])["big"]
        assert any(b.get("crash") and b["symbol"] == "TMPV" and b["opt"] == "PE" for b in B)
        assert any(b.get("index") and b["symbol"] == "SENSEX" and b["side"] == "SELL" for b in B)
    finally:
        BV.SCR.clear()
        FP.STATE["signals"].pop()


def test_footprint_universe_has_sensex():
    from krt import footprint as FP
    inst = {"fut": {"NIFTY": ["1", "NF", "2026-12-29", "NFO"], "BANKNIFTY": ["2", "BN", "2026-12-29", "NFO"], "SENSEX": ["3", "SX", "2026-12-24", "BFO"]}, "eq": {}}
    U = FP.universe(inst, pd.Timestamp("2026-11-25 13:00"))
    assert [u["symbol"] for u in U[:3]] == ["NIFTY", "BANKNIFTY", "SENSEX"] and U[2]["exch"] == "BFO"
