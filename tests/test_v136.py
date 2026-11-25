"""v136: no app freeze from GitHub retry inside the calls lock · lock tracer · brain history newest-first + live prev close ·
riser alerts hidden calls · GU morning re-selection gets prices."""
import threading
import time

import pandas as pd

from krt import behaviour as B, riser as RS
from krt.calls import TracedLock
from krt.store import Store


def test_store_retry_runs_in_background(tmp_path, monkeypatch):
    st = Store.__new__(Store)
    st.data, st.load_failed, st._retry_t = {"calls": {}}, True, 0
    called = threading.Event()

    def slow_retry(force=False):
        time.sleep(1.0)
        called.set()
        return False
    monkeypatch.setattr(st, "retry_remote", slow_retry)
    t0 = time.time()
    assert st.load() == {"calls": {}}
    assert time.time() - t0 < 0.2                      # never waits for GitHub
    assert called.wait(3)


def test_traced_lock_reports_holder():
    L = TracedLock()
    assert L.held() is None
    with L:
        h = L.held()
        assert h["by"] == threading.current_thread().name and "test_v136.py" in h["at"]
        assert not L.acquire(timeout=0.05)
    assert L.held() is None and L.acquire(False)
    L.release()


class FakeAg:
    def __init__(self, df):
        self.df, self.calls, self.fail = df, [], 2

    def candles(self, exch, tok, iv, s, e):
        self.calls.append((s, e))
        if self.fail > 0:                              # Angel rate-limit → empty table
            self.fail -= 1
            return pd.DataFrame()
        return self.df[(self.df.index >= s) & (self.df.index <= e)]


def test_history_fetch_newest_first_with_retry(tmp_path, monkeypatch):
    import numpy as np
    monkeypatch.setattr(B.time, "sleep", lambda s: None)
    idx = pd.date_range("2026-08-03 09:15", "2026-11-24 15:25", freq="5min")
    idx = idx[(idx.dayofweek < 5) & (idx.time >= pd.Timestamp("09:15").time()) & (idx.time <= pd.Timestamp("15:25").time())]
    c = 25000 + np.cumsum(np.random.default_rng(1).normal(0, 5, len(idx)))
    df = pd.DataFrame({"open": c, "high": c + 3, "low": c - 3, "close": c}, index=idx)
    ag = FakeAg(df)
    assert B.build(tmp_path, ag, pd.Timestamp("2026-11-25 09:21"))
    assert ag.calls[0][1] > ag.calls[-1][1]            # newest piece first
    assert B.M["fresh"] and B.M["last_day"] == "2026-11-24"


def test_live_prev_close_override():
    import numpy as np
    days = pd.bdate_range("2026-07-01", "2026-07-31")
    rows = []
    px = 24000.0
    for d in days:
        for t in pd.date_range(d + pd.Timedelta(hours=9, minutes=15), periods=75, freq="5min"):
            px += np.sin(len(rows)) * 3
            rows.append((t, px, px + 2, px - 2, px))
    hist = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"]).set_index("time")
    B.M["hist"] = {"NIFTY": B.prepare(B.features(hist))}
    B.M["raw"] = {"NIFTY": hist}                       # memory ends in JULY (stale)
    B.M["tuned"] = {"wset": "balanced", "k": 40}
    td = pd.DataFrame({"open": 25700.0, "high": 25760.0, "low": 25690.0, "close": 25750.0},
                      index=pd.date_range("2026-11-25 09:15", periods=4, freq="5min"))
    A = B.live("NIFTY", td, None, pd.Timestamp("2026-11-25 09:36"), prev_close=25350.0)
    assert "day +1.58%" in A["pattern"] and "+7" not in A["pattern"]


def test_riser_alerts_hidden_calls_too():
    RS.H.clear()
    RS.LAST.clear()
    RS.STATE["alerts"].clear()
    now = pd.Timestamp("2026-11-25 10:00:00")
    sent = []
    c = {"id": "h1", "date": "2026-11-25", "status": "OPEN", "symbol": "AUBANK", "strike": 1000, "side": "CE", "entry": 40, "targets": [50],
         "shadow": True, "shadow_why": "weak module", "kind": "STOCK"}
    for i, p in enumerate((40, 41, 42.5, 44.5)):
        RS.scan([dict(c, ltp=p)], now + pd.Timedelta(seconds=40 * i), lambda *a: sent.append(a))
    assert RS.STATE["alerts"] and RS.STATE["alerts"][0]["hidden"] and sent and "hidden module call" in sent[0][0]
