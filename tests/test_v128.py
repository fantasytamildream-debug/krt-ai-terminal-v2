"""v128: level history (tests / held / broke / follow-through) + GU run log."""
import numpy as np
import pandas as pd

from krt import levelhist as LH


def range_then_break():
    """~2 years: price bounces between ~100 (support) and ~110 (resistance) 8 times, then breaks above 110 and runs."""
    c = []
    for cyc in range(8):
        c += list(np.linspace(101, 109.3, 30)) + list(np.linspace(109.3, 101, 30))
    c += list(np.linspace(101, 109, 20)) + list(np.linspace(111.5, 122, 25))
    idx = pd.bdate_range("2024-11-01", periods=len(c))
    c = np.array(c)
    return pd.DataFrame({"open": c, "high": c + 0.8, "low": c - 0.8, "close": c, "volume": 1000}, index=idx)


def test_zones_and_record():
    d = range_then_break()
    r = LH.analyse(d.iloc[:-25], px=105)                       # before the breakout
    res = [z for z in r["zones"] if z["role"] == "RESISTANCE"][0]
    sup = [z for z in r["zones"] if z["role"] == "SUPPORT"][0]
    assert res["tests"] >= 6 and res["held_pct"] >= 80 and res["strength"] == "STRONG"
    assert sup["strength"] == "STRONG"
    assert any("tested" in t and "IF a daily close above" in t for t in r["lines"])


def test_break_follow_through_counted():
    d = range_then_break()
    Z, a = LH.zones(d)
    z = max([z for z in Z if 108 <= z["mid"] <= 112], key=lambda z: z["n"])
    T = LH.record(d, z, a)
    br = [t for t in T if t["result"] == "BROKE"]
    assert br and br[-1]["follow"] is True and br[-1]["move5"] > 0


def test_short_history_returns_none():
    assert LH.analyse(range_then_break().iloc[:60]) is None


def test_gu_log_persists():
    import server as S
    from krt.calls import STORE
    snap = {"contracts": [{"symbol": "GAIL", "strike": 200.0, "side": "CE", "expiry": "2026-12-29", "dte": 25,
                           "eval": {"classic": {"checks": {"A · x": True, "B · y": False, "Stock · z": True}, "drop": 6.1, "ok": False, "lite": False}}}],
            "zones": [1, 2]}
    S.gu_log(snap, pd.Timestamp("2026-11-24 10:02"))
    rows = (STORE.load().get("gu_runs") or {}).get("2026-11-24")
    assert rows and rows[-1]["best"].startswith("GAIL 200 CE") and rows[-1]["failed"] == ["B · y"]
    st = S.gu_runs_state()
    assert st["rows"][0]["time"] == "10:02"
