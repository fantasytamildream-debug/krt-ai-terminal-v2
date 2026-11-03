"""V10 tests — Angel per-minute candle limiter, History P/L kinds, Swing off."""
import threading
import time

from krt import angel_api as AA
from krt import fullscan as FS


def test_candle_limiter_waits_when_window_full(monkeypatch):
    ag = AA.Angel.__new__(AA.Angel)
    ag._lk = threading.Lock()
    ag.CANDLE_PER_MIN = 3
    slept = []
    monkeypatch.setattr(AA.time, "sleep", lambda s: slept.append(s))
    for _ in range(3):
        ag._candle_slot()
    assert not slept                       # 3 வரை உடனே
    ag._candle_slot()                      # 4-வது → காத்திருக்கணும்
    assert slept == [30]                   # window 60s → max 30s ஒரே தடவை காத்திருப்பு
    assert getattr(ag, "rate_waits", 0) == 1


def test_rate_error_backoff_escalates(monkeypatch):
    ag = AA.Angel.__new__(AA.Angel)
    ag._lk, ag._last = threading.Lock(), 0
    ag.ensure = lambda: None
    ag._yield = lambda: None
    monkeypatch.setattr(AA.time, "sleep", lambda s: None)
    cools = []
    n = {"i": 0}

    def fn():
        n["i"] += 1
        cools.append(round(getattr(ag, "_cool", 0) - time.time()))
        if n["i"] < 3:
            raise Exception("Couldn't parse the JSON response received from the server: b'Access denied because of exceeding access rate'")
        return {"status": True, "data": []}
    assert ag._call(fn)["status"]
    assert n["i"] == 3 and ag.rate_hits == 2
    assert cools[1] >= 2 and cools[2] >= 5           # 3 sec → 6 sec


def test_swing_off():
    assert FS.SWING_ON is False


def test_history_summary_has_new_kinds(monkeypatch):
    from krt import calls as CL
    src = open(CL.__file__, encoding="utf-8").read()
    assert 'sorted({c["kind"] for c in allc}' in src
