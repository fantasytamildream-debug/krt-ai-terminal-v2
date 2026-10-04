import pandas as pd
from krt.levels import completed_levels
from krt.risk import risk_check


def _daily():
    idx = pd.bdate_range("2026-08-03", "2026-10-01")
    return pd.DataFrame({"open": 100, "high": [100 + i for i in range(len(idx))],
                         "low": [90 + i for i in range(len(idx))], "close": 95, "volume": 1}, index=idx)


def test_no_lookahead_pdh():
    d = _daily()
    now = pd.Timestamp("2026-10-01 11:00")
    lv = completed_levels(d, now)
    assert lv["PDH"] == d.loc["2026-09-30", "high"]  # today's high பயன்படுத்தக்கூடாது


def test_month_is_completed_month():
    lv = completed_levels(_daily(), pd.Timestamp("2026-10-01 11:00"))
    assert lv["PMH"] == _daily().loc["2026-09"]["high"].max()


def test_risk_skip():
    ok, r, msg = risk_check(120, 80, 75, {"charges_slippage": 150, "max_risk_per_trade": 2500})
    assert not ok and msg == "SKIP — RISK ABOVE LIMIT"
