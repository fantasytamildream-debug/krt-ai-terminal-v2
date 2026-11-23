"""v132: /api/status never queues behind a slow build (serves the last copy) · strat_state has its own cache (name clash fixed)."""
import json
import threading
import time

import server as S


class F(S.H):
    def __init__(self, path):
        self.path, self.headers, self.out = path, {}, {}

    def _send(self, code, body, ctype=None):
        self.out = {"code": code, "body": body}

    def _send_status(self):
        self.out = {"code": 200, "body": S.STC["b"]}


def test_busy_build_serves_last_copy_fast():
    S.STC.update(t=time.time(), b=b'{"version": "old"}', gz=None)
    S.STATUS_LOCK.acquire()                                   # another request is building
    S.STB.update(start=time.time() - 50, tid=threading.get_ident(), where=None)
    try:
        f = F("/api/status")
        t0 = time.time()
        f.do_GET()
        assert time.time() - t0 < 1 and f.out["code"] == 200 and json.loads(f.out["body"])["version"] == "old"
        assert S.STB["where"]                                  # watchdog recorded where the build is stuck
        g = F("/api/ticks")
        g.do_GET()
        assert json.loads(g.out["body"])["sbusy"]["s"] >= 45
    finally:
        S.STB.update(start=None, where=None)
        S.STATUS_LOCK.release()


def test_full_build_and_strat_cache_separate():
    S.STC.update(t=0, b=None, gz=None)
    f = F("/api/status")
    f.do_GET()
    d = json.loads(f.out["body"])
    assert d["version"] == S.APP_VERSION and "status_build" in d
    assert not (d.get("strategies") or {}).get("err")
    assert "b" in S.STC and "d" not in S.STC and "d" in S.STRC
