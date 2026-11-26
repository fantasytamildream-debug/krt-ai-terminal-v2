import datetime as dt
import krt.calls as K


def _c(i, src, date, time, pnl=None, status="SL HIT", exit_time=None, q=(), sym=None, grade="A", risk=2000, shadow=False):
    return {"id": i, "source": src, "kind": "INTRADAY", "date": date, "time": time, "symbol": sym or i, "side": "CE",
            "status": status, "pnl_lot": pnl, "exit_time": exit_time, "qcodes": list(q), "grade": grade, "risk": risk,
            "shadow": shadow}


def _hist(src, good_after_sl):
    calls = {}
    for d in range(1, 7):
        day = f"2026-11-0{d}"
        calls[f"{src}a{d}"] = _c(f"{src}a{d}", src, day, "10:00", -1000, exit_time=f"{day} 10:30:00")
        calls[f"{src}b{d}"] = _c(f"{src}b{d}", src, day, "10:05", -1000, exit_time=f"{day} 10:40:00")
        calls[f"{src}c{d}"] = _c(f"{src}c{d}", src, day, "11:00", 2000 if good_after_sl else -1000, "T3 DONE" if good_after_sl else "SL HIT",
                                 f"{day} 12:00:00")
    return calls


def test_module_brake_after_two_sl():
    K.BRAKE["day"] = None
    calls = _hist("Chart pattern", False)
    day = "2026-11-26"
    calls["x1"] = _c("x1", "Chart pattern", day, "10:00", -900, exit_time=f"{day} 10:20:00")
    calls["x2"] = _c("x2", "Chart pattern", day, "10:10", -900, exit_time=f"{day} 10:50:00")
    new = _c("x3", "Chart pattern", day, "11:00", None, "OPEN")
    r = K.brake_check(new, calls, [], dt.datetime(2026, 11, 26, 11, 0))
    assert r and r[0] == "Q_MOD_BRAKE"
    # before the 2nd SL exit → still allowed (no look-ahead)
    K.BRAKE["day"] = None
    assert K.brake_check(new, calls, [], dt.datetime(2026, 11, 26, 10, 45)) is None


def test_module_exempt_when_history_profitable():
    K.BRAKE["day"] = None
    calls = _hist("5-min ORB", True)
    day = "2026-11-26"
    calls["x1"] = _c("x1", "5-min ORB", day, "10:00", -900, exit_time=f"{day} 10:20:00")
    calls["x2"] = _c("x2", "5-min ORB", day, "10:10", -900, exit_time=f"{day} 10:50:00")
    new = _c("x3", "5-min ORB", day, "11:00", None, "OPEN")
    assert K.brake_check(new, calls, [], dt.datetime(2026, 11, 26, 11, 0)) is None


def test_bad_flag_learned():
    K.BRAKE["day"] = None
    calls = {}
    for d in range(1, 8):
        day = f"2026-11-0{d}"
        calls[f"l{d}"] = _c(f"l{d}", "5-min ORB", day, "12:00", 1500 if d == 1 else -900, "T1 HIT" if d == 1 else "SL HIT",
                            f"{day} 13:00:00", q=["TIME_LUNCH"])
        calls[f"l{d}"]["status"] = "T3 DONE" if d == 1 else "SL HIT"
    new = _c("n", "5-min ORB", "2026-11-26", "12:19", None, "OPEN", q=["TIME_LUNCH"])
    r = K.brake_check(new, calls, ["TIME_LUNCH"], dt.datetime(2026, 11, 26, 12, 19))
    assert r and r[0] == "Q_BAD_FLAG" and "lunch" in r[1]
    assert K.brake_check(dict(new, qcodes=[]), calls, [], dt.datetime(2026, 11, 26, 12, 19)) is None
    st = K.brake_state(calls, "2026-11-26")
    assert st["bad_flags"] and st["bad_flags"][0]["n"] == 7


def test_brake_codes_are_shadow():
    assert "Q_MOD_BRAKE" in K.SHADOW_CODES and "Q_BAD_FLAG" in K.SHADOW_CODES
