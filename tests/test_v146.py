"""v146: Green lane AI — every net-profitable module (green rows of Module ratings) is never gate-blocked."""
import time

import pandas as pd

from krt import calls as C


def test_green_list_and_free_lane(monkeypatch):
    monkeypatch.setitem(C.PROVEN, "rows", {"📊 Index Jackpot": {"n": 1, "w": 5935, "l": 0}, "Gamma Unwind Classic": {"n": 23, "w": 150000, "l": 40000},
                                           "Breakout/Breakdown": {"n": 111, "w": 20000, "l": 24551}})
    monkeypatch.setitem(C.PROVEN, "t", time.time())
    G = C.green_list()
    assert [g["source"] for g in G] == ["Gamma Unwind Classic", "📊 Index Jackpot"]
    assert C.free_lane({"source": "📊 Index Jackpot"}) and not C.free_lane({"source": "Breakout/Breakdown"})
    monkeypatch.setattr(C, "_quality_v6", lambda c, now: ("Q_WEAK_MODULE", "recent calls lost"))
    c = {"source": "Gamma Unwind Classic"}
    assert C.quality_v6(c, pd.Timestamp("2026-11-26 11:00")) is None and "free lane" in c["risk_warn"][0]
    assert C.quality_v6({"source": "Breakout/Breakdown"}, pd.Timestamp("2026-11-26 11:00"))[0] == "Q_WEAK_MODULE"
