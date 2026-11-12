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


def test_index_lane_not_starved_by_stock_calls(monkeypatch):
    import pandas as pd
    from krt import calls as CL, store as SM
    from tests.test_mannan import FakeStore
    fs = FakeStore()
    for m in (CL, SM):
        monkeypatch.setattr(m, "STORE", fs)
    CL.PROVEN.update(t=0, set=set())
    day = "2026-11-12"
    fs.data["calls"] = {f"s{i}": {"id": f"s{i}", "date": day, "symbol": f"STK{i}", "side": "CE", "kind": "MOVERS", "source": "Top Movers", "status": "OPEN", "pnl_lot": 0}
                        for i in range(12)}                                                   # stocks used all 12 slots
    fs.data["calls"]["n1"] = {"id": "n1", "date": day, "symbol": "NIFTY", "side": "CE", "kind": "V4", "source": "V4 💎 VWAP Mean Reversion", "status": "OPEN", "pnl_lot": 0}
    now = pd.Timestamp(f"{day} 11:00")
    sb = {"date": day, "symbol": "NIFTY", "side": "CE", "kind": "V4", "source": "V4 ⚡ ICT Silver Bullet", "entry": 100, "sl": 90}
    assert CL.quality_v6(sb, now) is None                                                     # Silver Bullet NIFTY still comes
    assert CL.quality_v6(dict(sb, symbol="SENSEX", source="V4 🥇 Order Flow + Profile"), now) is None
    st = {"date": day, "symbol": "TCS", "side": "CE", "kind": "MOVERS", "source": "Top Movers", "entry": 100, "sl": 85}
    assert CL.quality_v6(st, now)[0] == "Q_DAY_MAX"                                           # stock lane still capped at 12
    CL.SKIPPED.update(day=day, log=[{"time": "10:05", "symbol": "NIFTY", "source": "Index OI", "code": "Q_SL_TIGHT", "detail": ""}])
    D = CL.index_diag(fs.data, now)
    assert D["NIFTY"]["calls"][0]["source"].startswith("V4") and D["NIFTY"]["rejects"][0]["code"] == "Q_SL_TIGHT" and D["SENSEX"]["calls"] == []


def test_self_heal_missing_or_misplaced_brain(tmp_path):
    """krt/brain.py missing on the server (GitHub upload went wrong) → server finds a misplaced copy, else restores the built-in one."""
    import shutil, subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for case in ("moved", "embedded"):
        d = tmp_path / case
        skip = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".git")
        shutil.copytree(root, d, ignore=lambda p, names: set(skip(p, names)) | ({"logs", "data"} & set(names) if Path(p) == root else set()))
        (d / "krt" / "brain.py").unlink()
        if case == "moved":
            shutil.copy(root / "krt" / "brain.py", d / "brain (1).py")
        out = subprocess.run([sys.executable, "-c", "import server, json; from krt import brain, mood; print(json.dumps(server.HEAL))"],
                             cwd=d, capture_output=True, text=True, timeout=90)
        heal = __import__("json").loads(out.stdout.strip().splitlines()[-1])
        assert (heal["moved"].get("brain") == "brain (1).py") if case == "moved" else (heal["embedded"] == ["brain"])
        assert heal["missing"] == []
