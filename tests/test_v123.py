"""v123: /api/status must return 200 right after a restart (JVC name clash crashed it with HTTP 500)."""
import json

import server as S


def test_status_ok_on_fresh_start():
    S.JVC.clear()
    S.JVC.update(t=0, d=None)
    S.STC.update(t=0, b=None, gz=None)
    out = {}

    class F(S.H):
        def __init__(self, path):
            self.path, self.headers = path, {}

        def _send(self, code, body, ctype=None):
            out["code"], out["body"] = code, body

        def _send_status(self):
            out["code"], out["body"] = 200, S.STC["b"]
    F("/api/status").do_GET()
    assert out["code"] == 200
    d = json.loads(out["body"])
    assert d["version"] == S.APP_VERSION and "jarvis" in d


def test_no_name_clash():
    assert "t" in S.JVC and "pushed" in S.JVP and "pushed" not in S.JVC
