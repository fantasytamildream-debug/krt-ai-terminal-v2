"""v126: big-player action (TAKE / WAIT / LATE / AVOID) · strike carries token · premium plan T1–T5."""
import pandas as pd

from krt import bpadvice as BA, command as CMD

NOW = pd.Timestamp("2026-11-18 15:30")


def _r(side="SELL", hi=3221, lo=3190, end="15:25"):
    return {"symbol": "TRENT", "side": side, "high": hi, "low": lo, "price": 3195, "date": "2026-11-18", "time": "2026-11-18 15:20", "end": end,
            "exch": "NSE", "opt": {"strike": 3200, "side": "PE" if side == "SELL" else "CE", "lot": 100}}


def test_take_when_confirmed():
    a = BA.advise(_r(), 3185, 61.5, "BEAR", NOW)
    assert a["tag"] == "TAKE" and "3200 PE" in a["txt"] and a["plan"]["sl"] < 61.5 < a["plan"]["targets"][0]


def test_wait_until_trigger():
    a = BA.advise(_r(), 3200, 61.5, "BEAR", NOW)
    assert a["tag"] == "WAIT" and "below 3190" in a["txt"]


def test_late_and_failed_and_old():
    assert BA.advise(_r(), 3150, 61.5, None, NOW)["tag"] == "LATE"           # ran > 1 range past the low
    assert BA.advise(_r(), 3230, 61.5, None, NOW)["tag"] == "AVOID"          # broke the other side
    assert BA.advise(_r(end="14:00"), 3185, 61.5, None, NOW)["tag"] == "LATE"  # 90 min old


def test_risk_cap():
    r = _r()
    r["opt"]["lot"] = 5000
    assert BA.advise(r, 3185, 61.5, None, NOW)["tag"] == "AVOID"


def test_absorb_is_wait():
    assert BA.advise(dict(_r(), side="ABSORB"), 3195, None)["tag"] == "WAIT"
