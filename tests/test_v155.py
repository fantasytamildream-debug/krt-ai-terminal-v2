"""v155: riser keeps alerts across a restart · 1-minute burst · watched strikes."""
import datetime as dt
from krt import riser as RS


def _call(cid, ltp, e=100.0):
    return {"id": cid, "date": "2026-11-27", "status": "OPEN", "kind": "INTRADAY", "symbol": "AAA", "strike": 100, "side": "CE",
            "ltp": ltp, "entry": e, "targets": [130], "sl": 85, "source": "5-min ORB"}


def test_burst_one_minute():
    RS.H.clear(); RS.LAST.clear(); RS.STATE.update(day=None, alerts=[], live=[])
    t0 = dt.datetime(2026, 11, 27, 11, 0, 0)
    for i, p in enumerate([100, 100.2, 100.4, 100.5]):
        RS.scan([_call("c1", p)], t0 + dt.timedelta(seconds=20 * i))
    new = RS.scan([_call("c1", 104.0)], t0 + dt.timedelta(seconds=80))
    assert new and new[0]["burst"] is True and new[0]["state"] in ("RISING", "STRONG")


def test_restore_after_restart_and_watch_items():
    snap = RS.snapshot()
    assert snap["alerts"] and snap["day"] == "2026-11-27"
    RS.STATE.update(day=None, alerts=[], live=[]); RS.LAST.clear()
    RS.restore(snap, "2026-11-27")
    assert RS.STATE["alerts"] and RS.LAST
    w = dict(_call("W|555", 50, 40), kind="WATCH", targets=[], token="555", exch="NFO", lot=50, lots3m=120, source="🐋 Big buyer strike")
    t0 = dt.datetime(2026, 11, 27, 12, 0, 0)
    RS.H.clear()
    new = []
    for i, p in enumerate([40, 40.5, 41, 41.6, 43.0]):
        new += RS.scan([], t0 + dt.timedelta(seconds=20 * i), extra=[dict(w, ltp=p)])
    assert new and new[0]["watch"] is True and new[0]["token"] == "555" and new[0]["lots3m"] == 120
