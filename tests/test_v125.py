"""v125: strategy tiers (⭐ star / ⚫ removed), star modules skip soft filters, hidden list excludes duplicates, alerts sort by alert time."""
import pandas as pd
import pytest

from krt import calls as CL, guide as GD


def _calls(src, wins, losses, w=1500, l=-2000, day="2026-11-10"):
    out = {}
    for i in range(wins):
        out[f"{src}w{i}"] = {"id": f"{src}w{i}", "date": day, "time": "10:00", "symbol": f"S{i}", "side": "CE", "kind": "X", "source": src,
                             "status": "T3 DONE", "pnl_lot": w}
    for i in range(losses):
        out[f"{src}l{i}"] = {"id": f"{src}l{i}", "date": day, "time": "10:00", "symbol": f"L{i}", "side": "CE", "kind": "X", "source": src,
                             "status": "SL HIT", "pnl_lot": l}
    return out


def test_tiers():
    d = {"calls": {**_calls("Good", 12, 8), **_calls("Bad", 3, 17), **_calls("Meh", 10, 10, 1000, -1000)}}
    t = CL.strategy_tiers(d)
    assert t["Good"]["tier"] == "STAR" and t["Bad"]["tier"] == "RETIRED" and t["Meh"]["tier"] is None


def test_retired_recovers_when_recent_form_turns_positive():
    old = _calls("Back", 2, 18, day="2026-09-01")                       # old big losses
    d = {"calls": old}
    assert CL.strategy_tiers(d)["Back"]["tier"] == "RETIRED"
    day = str(pd.Timestamp.now(tz="Asia/Kolkata").date())
    d["calls"].update(_calls("Back", 25, 5, 3000, -1000, day))          # recent 30 calls profitable
    assert CL.strategy_tiers(d)["Back"]["tier"] != "RETIRED"


@pytest.fixture
def gate_data():
    CL.PROVEN.update(t=0, set=set(), rows={})
    return {"calls": _calls("Star", 14, 6, day=str((pd.Timestamp.now(tz="Asia/Kolkata") - pd.Timedelta(days=3)).date()))}


def test_star_skips_low_volume(gate_data):
    CL.MARKET["nifty_pct"] = 0.2
    c = {"symbol": "ABC", "side": "CE", "kind": "X", "source": "Star", "vol_ratio": 0.9, "date": str(pd.Timestamp.now(tz="Asia/Kolkata").date())}
    r = CL.best_gate(dict(c), gate_data, pd.Timestamp.now())
    assert r is None or r[0] != "Q_LOW_VOL"
    c2 = dict(c, source="Other")
    assert CL.best_gate(c2, gate_data, pd.Timestamp.now())[0] == "Q_LOW_VOL"


def test_guide_sorts_by_alert_time():
    day = "2026-11-18"
    feed = [{"symbol": "LATE", "side": "BUY", "mult": 4, "price": 10, "high": 11, "low": 9, "time": f"{day} 11:25", "end": "11:30", "date": day,
             "exch": "NSE", "seen": "12:28:10", "backfill": False}]
    early = [{"symbol": "E1", "side": "BUY", "mult": 6, "price": 5, "time": "11:51", "full": f"{day} 11:51:05", "date": day}]
    g = GD.build({"label": "BEARISH", "evidence": []}, {}, {}, {}, [], feed, early, [], [], [], now=pd.Timestamp(f"{day} 12:38"))
    assert [b["symbol"] for b in g["big"]] == ["LATE", "E1"]
