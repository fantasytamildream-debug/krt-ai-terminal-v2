"""v105: handler crash → JSON (not a dropped connection / Render 502) · isolated loop steps · uptime + RAM diagnostics."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import server


def _serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_ask_brain_ok_and_crash_returns_json(monkeypatch):
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    from krt import brain as BR
    srv, base = _serve()
    try:
        code, j = _post(base + "/api/brain/ask", {"q": "what should I take now?"})
        assert code == 200 and j["ok"] and j["answer"]
        monkeypatch.setattr(BR, "answer", lambda *a, **k: (_ for _ in ()).throw(KeyError("strike")))
        code, j = _post(base + "/api/brain/ask", {"q": "vbl"})
        assert code == 500 and j["ok"] is False and "KeyError" in j["answer"]           # real error text, not a 502
    finally:
        srv.shutdown()


def test_steps_isolated_and_errors_visible():
    ran = []
    server.LOOP_ERR.clear()
    server._step("mood", lambda: (_ for _ in ()).throw(ValueError("bad mood data")))
    server._step("brain", lambda: ran.append("brain"))                                    # still runs after mood failed
    assert ran == ["brain"] and "ValueError: bad mood data" in server.LOOP_ERR["mood"]["err"] and "brain" not in server.LOOP_ERR
    server._step("mood", lambda: ran.append("mood"))
    assert "mood" not in server.LOOP_ERR                                                  # clears once it works again


def test_sys_state_reports_uptime_and_ram():
    st = server.sys_state()
    assert st["up_min"] >= 0 and (st["rss_mb"] is None or st["rss_mb"] > 10) and isinstance(st["loop_err"], dict)
