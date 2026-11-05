"""v86: news rally capture · market box · index confirm · news setups (strike) · money machine live entry."""
import time

import pandas as pd

from krt import newsradar as NR


def test_rally_headlines_score():
    for t in ["Sensex zooms 1,900 pts, Nifty jumps over 600 points on US trade deal hopes", "Nifty rallies 600 points as FIIs pour money",
              "Bulls charge on D-Street: Sensex soars 1,950 points", "Stock market today: Sensex, Nifty extend gains"]:
        assert NR.mscore(t) >= 2, t
    assert NR.mscore("Sensex tanks 1,200 points, Nifty below 24,000") <= -3


def _it(sym, title, sc, ev="MARKET"):
    return {"symbol": sym, "title": title, "source": "x", "link": None, "ts": time.time(), "time": "", "score": sc, "event": ev}


def test_market_box_causes_and_index_confirmed():
    items = [_it("NIFTY", "Sensex zooms 1,900 pts on US trade deal hopes", 5), _it("NIFTY", "Nifty jumps over 600 points amid strong FII buying", 5)]
    box = NR.market_box(items, {"NIFTY": {"pct": 2.5}, "BANKNIFTY": {"pct": 3.3}})
    assert box["move"] == "RALLY" and any("trade deal" in c for c in box["causes"]) and any("FII buying" in c for c in box["causes"])
    F = NR.build_focus(items, {}, {}, idx_pct={"NIFTY": 2.5})
    assert F[0]["status"] == "CONFIRMED"
    one = items[:1]
    assert NR.build_focus(one, {}, {}, idx_pct={"NIFTY": 2.5})[0]["status"] == "CONFIRMED"   # 1 headline ஆனாலும் price ≥1% ஒத்துப்போனா


def test_news_setups_with_strike(monkeypatch):
    from krt import fullscan as FS, v4 as V
    NR.CACHE["opt"] = {}
    now = pd.Timestamp("2026-11-05 11:00")
    focus = [{"symbol": "NIFTY", "side": "CE", "index": True, "status": "CONFIRMED", "score": 10, "news": [{"title": "Nifty jumps 600"}], "why": "x"},
             {"symbol": "NYKAA", "side": "CE", "status": "WATCH", "score": 5, "ltp": 350, "ul_sl": 342, "news": [{"title": "CLSA raises Nykaa target"}], "why": "y"}]
    monkeypatch.setattr(V, "pick_strike", lambda ag, inst, idx, side, spot, now: ({"strike": 24550, "expiry": "2026-11-09", "lot": 65, "token": "11", "exch": "NFO", "ltp": 169.1}, ""))
    monkeypatch.setattr(V, "option_plan", lambda o, spot, sl, st: ({"entry": 169.1, "sl": 130.65, "targets": [199.85, 230.65, 261.4]}, ""))
    monkeypatch.setattr(V, "settings", lambda: {})

    def pick(ag, inst, rows):
        for r in rows:
            r["option"] = {"token": "22", "exch": "NFO", "strike": 360, "expiry": "2026-11-25", "lot": 1100, "ltp": 9.0, "type": "CE"}
    monkeypatch.setattr(FS, "pick_options", pick)
    monkeypatch.setattr(FS, "attach_plan", lambda r, o, now, src=None: o.update(plan={"entry": 9.0, "sl": 6.8, "targets": [10.8, 12.6, 14.4]}))

    class Ag:
        def quotes(self, d):
            return {"11": {"ltp": 172.0}, "22": {"ltp": 10.5}}
    out = NR.setups(Ag(), {}, focus, {"NIFTY": {"spot": 24555}}, now)
    by = {x["symbol"]: x for x in out}
    assert by["NIFTY"]["strike"] == 24550 and by["NIFTY"]["live"].startswith("✅") and by["NIFTY"]["first"] == "11:00"
    assert by["NYKAA"]["strike"] == 360 and by["NYKAA"]["live"].startswith("⏭")          # 9 → 10.5 = +16.7% late
    assert out[0]["symbol"] == "NIFTY"                                                     # confirmed index முதலில்


def test_money_machine_live_states(monkeypatch):
    from krt import calls as CL, fullscan as FS, store as SM
    from tests.test_mannan import FakeStore
    fs = FakeStore()
    for m in (CL, SM):
        monkeypatch.setattr(m, "STORE", fs)
    FS.C.pop("mm_first", None)
    t1 = pd.Timestamp("2026-11-05 10:42")
    p = {"symbol": "AUROPHARMA", "side": "CE", "price": 3500, "score": 100, "option": {"ltp": 55.2, "strike": 1740}, "rp": {"sl": 50.7}}
    FS.mm_live([p], t1)
    assert p["live"]["status"] == "OK" and p["live"]["first_time"] == "10:42" and p["live"]["first_opt"] == 55.2
    p2 = dict(p, option={"ltp": 60.05, "strike": 1740})
    FS.mm_live([p2], t1 + pd.Timedelta(hours=3))
    assert p2["live"]["first_time"] == "10:42" and p2["live"]["status"] == "SLIGHT" and p2["live"]["move"] == 8.8   # 55.2 → 60.05
    p3 = dict(p, option={"ltp": 64.0, "strike": 1740})
    FS.mm_live([p3], t1 + pd.Timedelta(hours=3))
    assert p3["live"]["status"] == "LATE"
    fs.data["calls"]["c"] = {"id": "c", "date": "2026-11-05", "kind": "MONEYM", "symbol": "AUROPHARMA", "side": "CE", "entry": 60.05, "sl": 55.55,
                            "status": "OPEN", "time": "14:10"}
    p4 = dict(p, option={"ltp": 61.0, "strike": 1740})
    FS.mm_live([p4], t1 + pd.Timedelta(hours=3, minutes=30))
    assert p4["live"]["call"]["time"] == "14:10" and p4["live"]["ref"] == 60.05 and p4["live"]["status"] == "OK"   # call entry-ஐ வச்சு
    p5 = dict(p, option={"ltp": 54.0, "strike": 1740})
    FS.mm_live([p5], t1 + pd.Timedelta(hours=4))
    assert p5["live"]["status"] == "INVALID"
