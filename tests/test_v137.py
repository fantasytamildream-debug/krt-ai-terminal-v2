"""v137: Mannan box matches strategy names without medal / V4 prefix · Market Brain for 4 indices + option pick."""
import pandas as pd

import server as S
from krt import behaviour as B


def test_mannan_name_matching():
    assert S._mn_key("V4 🥈 Order Flow + Profile") == "order flow + profile"
    assert S._mn_key("🛢 🥇 Order Flow + Profile") == "order flow + profile"
    assert S._mn_key("V4 ⚡ ICT Silver Bullet") == "ict silver bullet"
    assert S._mn_key("👑 Money Machine") == "money machine" and S._mn_key("👑 Mannan Commodity") == "mannan commodity"
    assert S._mn_key("Index OI") and S._mn_key("5-min ORB") and S._mn_key("Gamma Unwind Classic") and S._mn_key("Breakout CE")
    assert not S._mn_key("2K Profit Machine") and not S._mn_key("V4 🥇 CQSMC PRO") and not S._mn_key("My pick") and not S._mn_key("👑 Mannan Index")


def test_mannan_box_shows_v4_order_flow(monkeypatch):
    from krt import calls as C
    day = str(S.now_ist().date())
    c = {"id": "2026|V4|NIFTY", "date": day, "time": "10:24:00", "source": "V4 🥈 Order Flow + Profile", "symbol": "NIFTY", "strike": 25750,
         "side": "CE", "entry": 275, "sl": 236, "ltp": 280, "targets": [306, 336], "status": "OPEN", "kind": "V4", "lot": 65}
    monkeypatch.setattr(C.STORE, "load", lambda: {"calls": {c["id"]: c}})
    S.MNC.update(t=0, d=None)
    assert [r["id"] for r in S.mannan_state()["rows"]] == [c["id"]]


class Ag:
    def __init__(self):
        self.seen = []

    def candles(self, ex, tok, iv, s, e):
        self.seen.append((ex, tok))
        idx = pd.date_range(max(s, pd.Timestamp("2026-10-01")), e, freq="5min")
        idx = idx[(idx.dayofweek < 5) & (idx.time >= pd.Timestamp("09:15").time()) & (idx.time <= pd.Timestamp("15:25").time())]
        if not len(idx):
            return pd.DataFrame()
        c = pd.Series(range(len(idx)), index=idx, dtype=float) % 37 + 80000
        return pd.DataFrame({"open": c, "high": c + 5, "low": c - 5, "close": c})


def test_brain_builds_four_indices(tmp_path, monkeypatch):
    monkeypatch.setattr(B.time, "sleep", lambda s: None)
    ag = Ag()
    assert B.build(tmp_path, ag, pd.Timestamp("2026-11-25 09:30"))
    assert set(B.M["hist"]) == {"NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"}
    assert ("BSE", "99919000") in ag.seen and ("NSE", "99926037") in ag.seen


def test_brain_state_picks(monkeypatch):
    S.BHC["d"] = {"NIFTY": {"name": "NIFTY", "spot": 25790.0, "side": "CE", "p": {"up": 40, "dn": 10}},
                  "SENSEX": {"name": "SENSEX", "spot": 84040.0, "side": None, "p": {"up": 15, "dn": 12}}}
    monkeypatch.setattr(S, "_cc_strike", lambda n, sd, px: {"strike": round(px / 100) * 100, "side": sd, "token": f"{n}{sd}", "exch": "NFO",
                                                            "expiry": "2026-12-01", "lot": 65, "contract": f"{n}X{sd}"})
    monkeypatch.setattr(S, "opt_quotes", lambda items: {items[0][1]: {"ltp": 123.0}})
    d = S.behaviour_state()
    assert d["picks"]["NIFTY"][0]["side"] == "CE" and d["picks"]["NIFTY"][0]["mode"] == "BUY" and d["picks"]["NIFTY"][0]["ltp"] == 123.0
    assert [p["mode"] for p in d["picks"]["SENSEX"]] == ["IF IT BREAKS UP", "IF IT BREAKS DOWN"]
    S.BHC["d"] = {}
