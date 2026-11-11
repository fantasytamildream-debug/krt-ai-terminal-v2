"""🧠 Fable picks — API body per Fable 5.2 docs · validation · tracking · run limits (fake transport, no real API call)."""
import json

import pandas as pd

from krt import fable as FB


def _calls():
    mk = lambda i, **o: {"id": f"d|{i}", "date": "2026-11-11", "time": "10:00", "symbol": f"S{i}", "strike": 100, "side": "CE", "entry": 10.0, "sl": 8.5,
                         "targets": [12, 14, 16], "ltp": 10.2, "status": "OPEN", "kind": "MOVERS", "source": "5-min ORB", "lot": 100, "vol_ratio": 2.1, "hits": [], **o}
    return {"calls": {f"d|{i}": mk(i) for i in range(4)}}


def _reply(picks, extra=None):
    out = {"market_view": "Trend up", "picks": picks, "avoid": [], "no_trade_reason": None, "lesson": "x", **(extra or {})}
    return {"type": "message", "content": [{"type": "thinking", "thinking": "secret reasoning"}, {"type": "text", "text": json.dumps(out)}],
            "usage": {"input_tokens": 9000, "output_tokens": 2500, "cache_read_input_tokens": 2000, "cache_creation_input_tokens": 0}}


def test_request_body_follows_fable_docs(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    seen = {}

    def post(body):
        seen.update(body)
        return _reply([])
    FB.STATE["usage"] = {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "usd": 0.0}
    text, u = FB.call_api("hello", _post=post)
    assert seen["model"] == "claude-fable-5-2" and seen["output_config"] == {"effort": "medium"}
    assert "temperature" not in seen and "top_p" not in seen and "top_k" not in seen                  # 400 on Fable 5.2
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"} and seen["max_tokens"] >= 16000
    assert "secret reasoning" not in text and json.loads(text)["market_view"] == "Trend up"            # text blocks only
    assert FB.STATE["usage"]["usd"] == round((9000 * 8 + 2500 * 40 + 2000 * 0.2) / 1e6, 4)


def test_validate_rejects_invented_and_bad_plans():
    cands = [{"id": "d|0", "entry": 10.0}, {"id": "d|1", "entry": 10.0}]
    good = {"id": "d|0", "grade": "GOLD", "confidence": 140, "entry_zone": [9.8, 10.3], "sl": 8.6, "t1": 12, "t2": 14, "t3": 16}
    out = FB.validate({"picks": [good, {**good, "id": "FAKE"}, {**good, "id": "d|1", "sl": 11},
                                 {**good, "id": "d|1", "grade": "GOLD"}]}, cands)
    assert [p["id"] for p in out["picks"]] == ["d|0", "d|1"] and out["picks"][0]["confidence"] == 100
    assert [p["grade"] for p in out["picks"]] == ["GOLD", "A"]                                        # one GOLD only


def test_run_saves_time_and_tracks_own_plan(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    D = _calls()
    now = pd.Timestamp("2026-11-11 10:30")
    pk = {"id": "d|2", "grade": "A", "confidence": 78, "entry_zone": [10.0, 10.4], "sl": 9.0, "t1": 11.5, "t2": 12.5, "t3": 13.5, "why": ["ORB + volume 2x"]}
    new = FB.run(D, now, {"extra": {"d|2": {"score": 90}}}, _post=lambda b: _reply([pk]))
    assert len(new) == 1 and new[0]["time"] == "10:30" and D["fable_picks"]["d|2"]["entry_zone"] == [10.0, 10.4]
    assert FB.run(D, now, {}, _post=lambda b: _reply([pk])) == []                                      # same pick not duplicated
    D["calls"]["d|2"]["ltp"] = 11.6
    FB.track(D, now + pd.Timedelta(minutes=5))
    p = D["fable_picks"]["d|2"]
    assert p["hits"] == ["T1 10:35"] and p["status"] == "OPEN" and p["pnl"] == round((11.6 - 10.2) * 100)
    D["calls"]["d|2"]["ltp"] = 8.9
    FB.track(D, now + pd.Timedelta(minutes=9))
    assert p["status"] == "SL HIT" and p["pnl"] == round((9.0 - 10.2) * 100)
    R = FB.report(D, "2026-11-11")
    assert R["stats"]["all"]["n"] == 1 and R["today"][0]["symbol"] == "S2"


def test_should_run_limits(monkeypatch):
    now = pd.Timestamp("2026-11-11 10:30")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    FB.STATE.update(day=None, runs=0, last_t=0, last_hash=None, busy=False)
    assert FB.should_run(now, [{"id": "a"}]) is False                                                  # no key
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert FB.should_run(now, [{"id": "a"}]) is True
    FB.STATE["last_t"] = __import__("time").time()
    assert FB.should_run(now, [{"id": "b"}]) is False                                                  # min gap 8 min
    FB.STATE.update(last_t=0, runs=99)
    assert FB.should_run(now, [{"id": "c"}]) is False                                                  # daily cap
    FB.STATE.update(runs=0)
    assert FB.should_run(pd.Timestamp("2026-11-11 15:00"), [{"id": "c"}]) is False                     # after 2:30


def test_ask_answers_plain_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    FB.STATE.update(asks=0, chat=[])
    a = FB.ask(_calls(), pd.Timestamp("2026-11-11 11:00"), "Which one should I take?", {},
               _post=lambda b: {"content": [{"type": "text", "text": "Take none right now — S1 is late."}], "usage": {}})
    assert a.startswith("Take none") and FB.STATE["chat"][0]["q"] == "Which one should I take?"


def test_no_deadlock_on_calls_lock(monkeypatch):
    """CALLS_LOCK is not reentrant — fable_once must not call lock-taking helpers while holding it (froze the whole server in testing)."""
    import threading
    import server
    from krt import fable as FBm
    from krt.calls import STORE
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(FBm, "call_api", lambda *a, **k: ('{"market_view":"t","picks":[],"avoid":[],"no_trade_reason":"none","lesson":"-"}', {}))
    FBm.STATE.update(day=None, runs=0, last_t=0, last_hash=None, busy=False)
    server.SNC["t"] = 0                                    # force sniper_state to recompute (it takes CALLS_LOCK)
    res = {}
    th = threading.Thread(target=lambda: res.update(out=server.fable_once(pd.Timestamp("2026-11-11 10:30"), force=True)), daemon=True)
    th.start()
    th.join(20)
    assert not th.is_alive(), "fable_once deadlocked on CALLS_LOCK"
    assert res.get("out") == []
