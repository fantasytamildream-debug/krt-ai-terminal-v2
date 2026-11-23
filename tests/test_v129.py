"""v129: 👑 Mannan Strategy Box — only the 8 chosen strategies, AI verdict + confidence, newest TAKE on top."""
import server as S
from krt import calls as C


def _call(i, src, side="CE", entry=10, sl=8, ltp=10, **kw):
    c = {"id": f"c{i}", "date": str(S.now_ist().date()), "time": f"10:{i:02d}:00", "source": src, "symbol": "NIFTY", "strike": 24500,
         "side": side, "entry": entry, "sl": sl, "ltp": ltp, "targets": [12, 14, 16], "status": "OPEN", "kind": "IDX", "lot": 75}
    c.update(kw)
    return c


def _run(monkeypatch, calls, nifty=0.6, tiers=None):
    monkeypatch.setattr(C.STORE, "load", lambda: {"calls": {c["id"]: c for c in calls}})
    monkeypatch.setitem(C.PROVEN, "tiers", tiers or {"Index OI": {"win": 62, "n": 30}, "5-min ORB": {"win": 40, "n": 30}})
    monkeypatch.setitem(C.MARKET, "nifty_pct", nifty)
    S.MNC.update(t=0, d=None)
    return S.mannan_state()


def test_only_the_8_strategies(monkeypatch):
    M = _run(monkeypatch, [_call(1, "Index OI"), _call(2, "All rounder"), _call(3, "Index OI", kind="PICK")])
    assert [r["id"] for r in M["rows"]] == ["c1"] and len(M["sources"]) == 8


def test_verdicts_and_confidence(monkeypatch):
    M = _run(monkeypatch, [
        _call(1, "Index OI"),                                  # 62 + 8 (with market) → TAKE
        _call(2, "5-min ORB", side="PE"),                      # 40 − 15 (against) = 25 → WAIT
        _call(3, "Index OI", ltp=11),                          # ran 10% → LATE
        _call(4, "Index OI", shadow=True, shadow_why="low volume"),
        _call(5, "Index OI", status="SL HIT", pnl_lot=-150),
        _call(6, "Index OI", ltp=8.3),                         # near SL → AVOID
    ])
    R = {r["id"]: r for r in M["rows"]}
    assert R["c1"]["verdict"] == "TAKE" and R["c1"]["conf"] == 70
    assert R["c2"]["verdict"] == "WAIT" and R["c2"]["conf"] == 25
    assert R["c3"]["verdict"] == "LATE"
    assert R["c4"]["verdict"] == "DON'T TAKE" and R["c4"]["hidden"] and "low volume" in R["c4"]["txt"]
    assert R["c5"]["verdict"] == "DONE"
    assert R["c6"]["verdict"] == "AVOID"
    assert M["rows"][0]["id"] == "c1" and M["rows"][-1]["id"] == "c5"


def test_newest_first_inside_group(monkeypatch):
    M = _run(monkeypatch, [_call(1, "Index OI"), _call(9, "Index OI")])
    assert [r["id"] for r in M["rows"]] == ["c9", "c1"]
