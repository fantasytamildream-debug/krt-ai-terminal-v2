"""📰 News Radar + 🩷 pink history tests (network இல்லை)."""
import time

import pandas as pd

from krt import newsradar as NR
from krt.ai import pink_history


def test_score_rules():
    assert NR.score("Nykaa Q2 results: net profit jumps 80%, revenue rises 25%")[0] >= 5
    s, ev = NR.score("Tata Steel net profit falls 30%, misses estimates")
    assert s <= -5 and ev == "RESULTS"
    assert NR.score("BEL bags order worth Rs 1,200 crore")[1] == "ORDER"
    assert NR.score("Sensex opens flat")[0] == 0


def _items(sym, sc, ev="RESULTS"):
    return [{"symbol": sym, "title": f"{sym} news", "source": "x", "ts": time.time(), "time": "", "score": sc, "event": ev}]


def test_focus_states():
    lv = {"NYKAA": {"PDH": 210.0, "PDL": 200.0}}
    f = NR.build_focus(_items("NYKAA", 5), lv, {"NYKAA": {"ltp": 208, "vol_ratio": 2.0, "high": 209, "low": 204}})[0]
    assert f["side"] == "CE" and f["status"] == "WATCH" and f["trigger"] == 210.0 and f["ul_sl"] == 200.0
    f = NR.build_focus(_items("NYKAA", 5), lv, {"NYKAA": {"ltp": 211, "vol_ratio": 2.0, "high": 211.5}})[0]
    assert f["status"] == "CONFIRMED"                         # PDH மேல் + volume
    f = NR.build_focus(_items("NYKAA", 5), lv, {"NYKAA": {"ltp": 211, "vol_ratio": 1.0}})[0]
    assert f["status"] == "WATCH"                             # volume இல்லை
    f = NR.build_focus(_items("NYKAA", 5), lv, {"NYKAA": {"ltp": 216, "vol_ratio": 3.0}})[0]
    assert f["status"] == "LATE"                              # 2%+ ஓடிடுச்சு
    f = NR.build_focus(_items("NYKAA", 5), lv, {"NYKAA": {"ltp": 211, "vol_ratio": 2.0}}, mdir="DOWN")[0]
    assert f["status"] == "AGAINST"
    assert NR.build_focus(_items("NYKAA", 2), lv, {}) == []   # score போதல


def test_run_confirmed_creates_news_call(monkeypatch):
    from krt import calls as CL, fullscan as FS, store as SM
    from tests.test_mannan import FakeStore
    fs = FakeStore()
    for m in (CL, SM):
        monkeypatch.setattr(m, "STORE", fs)
    monkeypatch.setattr(CL, "quality_v6", lambda c, now: None)
    monkeypatch.setattr(NR, "collect", lambda items, fno: _items("NYKAA", 6))
    monkeypatch.setattr(FS, "C", {"levels": {"NYKAA": {"PDH": 210.0, "PDL": 200.0}}, "live_q": {"NYKAA": {"ltp": 211, "vol_ratio": 2.2}}})

    def pick(ag, inst, rows):
        for r in rows:
            r["option"] = {"token": "5", "exch": "NFO", "contract": "NYKAA215CE", "strike": 215, "expiry": "2026-11-25", "type": "CE", "lot": 2500, "ltp": 4.0}

    def plan(r, o, now, src=None):
        o["plan"] = {"entry": 4.0, "sl": 3.0, "targets": [4.8, 5.6, 6.4], "risk": 2500, "risk_ok": True, "money": True, "reward_ok": True}
    monkeypatch.setattr(FS, "pick_options", pick)
    monkeypatch.setattr(FS, "attach_plan", plan)
    sent = []
    now = pd.Timestamp("2026-11-05 10:05")
    NR.STATE.update(alerted={}, alerts=[], log=[])
    st = NR.run(object(), {}, [], now, lambda t, k: sent.append(t))
    calls = list(fs.data["calls"].values())
    assert len(calls) == 1 and calls[0]["kind"] == "NEWS" and calls[0]["strike"] == 215
    assert sent and "NEWS FOCUS" in sent[0] and st["focus"][0]["status"] == "CONFIRMED"
    NR.run(object(), {}, [], now + pd.Timedelta(minutes=1), lambda t, k: sent.append(t))
    assert len(fs.data["calls"]) == 1 and len(sent) == 1        # ஒரு stock-க்கு ஒரு call · alert ஒருமுறை


def test_pink_history_by_date():
    pk = {"tier": "dark", "win": 82, "n": 25}
    calls = [{"id": "a", "date": "2026-11-04", "time": "10:00", "pink": pk, "status": "T3 DONE", "pnl_lot": 6000},
             {"id": "b", "date": "2026-11-04", "time": "11:00", "pink": pk, "status": "SL HIT", "pnl_lot": -2500},
             {"id": "c", "date": "2026-11-05", "time": "10:00", "pink": pk, "status": "OPEN", "pnl_lot": 300},
             {"id": "d", "date": "2026-11-05", "time": "10:00", "status": "SL HIT", "pnl_lot": -900}]
    h = pink_history(calls)
    assert h["total"] == {"calls": 3, "closed": 2, "win": 1, "win_rate": 50, "net": 3800}
    d4 = [d for d in h["days"] if d["date"] == "2026-11-04"][0]
    assert d4["win_rate"] == 50 and d4["net"] == 3500 and h["days"][0]["date"] == "2026-11-05"
