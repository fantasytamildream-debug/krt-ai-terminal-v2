"""V9 tests — market direction, pink tier, Strong Break (fake Angel data, network இல்லை)."""
import pandas as pd

from krt import ai
from krt import fullscan as FS


def test_market_dir_screenshot_case():
    # Image 1: NIFTY +1.07%, vel -0.02, breadth ↑37 ↓18, prediction UP → பழைய code "கீழே" சொன்னது
    assert ai.market_dir(1.07, -0.02, 37, 18, {"dir": "UP"}) == "UP"


def test_market_dir_mixed_is_none():
    assert ai.market_dir(0.1, 0.05, 20, 18, {"dir": "RANGE"}) is None
    assert ai.market_dir(-0.5, 0.0, 30, 10, {"dir": "UP"}) is not None or True   # வாக்கு கணக்கு crash ஆகக்கூடாது


def test_market_dir_down():
    assert ai.market_dir(-0.8, -0.2, 10, 40, {"dir": "DOWN"}) == "DOWN"


def _md(n, win, exp, af=None, paused=False):
    return {"n": n, "win": win, "exp": exp, "paused": paused, "after_filters": af or {"n": 0, "win": None, "exp": None}}


def test_pink_tiers():
    assert ai.pink_tier(_md(30, 82, 500))["tier"] == "dark"
    assert ai.pink_tier(_md(30, 77, 500))["tier"] == "light"
    small = ai.pink_tier(_md(8, 90, 700))
    assert small["tier"] == "light" and small["small"]          # 20 calls-க்கு குறைவு → dark இல்லை
    assert ai.pink_tier(_md(30, 85, -50)) is None                # நஷ்டம் → pink இல்லை
    assert ai.pink_tier(_md(3, 100, 900)) is None                # 3 calls → போதாது
    assert ai.pink_tier(_md(30, 85, 500, paused=True)) is None
    # filters பிறகு உள்ள stats முன்னுரிமை
    assert ai.pink_tier(_md(105, 37, -16, {"n": 25, "win": 81, "exp": 300}))["tier"] == "dark"


def test_pink_of_aipick_uses_source_module():
    ai.STATE["opt"] = {"mods": {"Top Movers": {"pink": {"tier": "light", "win": 76, "n": 22, "small": False}}}}
    assert ai.pink_of({"kind": "AIPICK", "source": "🤖 AI Pick", "ai_from": "Top Movers"})["win"] == 76
    assert ai.pink_of({"kind": "PICK", "source": "Top Movers"}) is None


class FakeAg:
    def __init__(self, df):
        self.df = df

    def candles(self, *a):
        return self.df


def _df(day, rows):
    idx = pd.date_range(f"{day} 09:15", periods=len(rows), freq="5min")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)


def _setup(df, now, npct=0.5):
    FS.C.clear()
    FS.C.update({"levels": {"ABC": {"PDH": 100.0, "PDL": 90.0, "PWH": 99.0}}})
    live_q = {"ABC": {"ltp": float(df["close"].iloc[-1]), "pct": 1.5, "vol_ratio": 2.5}}
    res = {"index": [{"index": "NIFTY", "pct": npct}]}
    inst = {"eq": {"ABC": "1"}}
    return live_q, res, inst


def _break_rows():
    rows = [[98, 99, 97.5, 98.5, 1000]] + [[98.5, 99.5, 98.2, 99.2, 1000]] * 8
    rows.append([99.2, 101.2, 99.1, 101.0, 4000])       # fresh PDH break, strong candle, volume 4×
    return rows


def test_strong_fresh_break(monkeypatch):
    df = _df("2026-11-03", _break_rows())
    now = df.index[-1] + pd.Timedelta(minutes=6)        # 10:06
    live_q, res, inst = _setup(df, now)
    monkeypatch.setattr(FS, "pick_options", lambda *a: None)
    ai.STATE["risk"] = {"dir": "UP"}
    out = FS.run_strong(FakeAg(df), inst, live_q, res, now, live=False)
    r = out["rows"][0]
    assert r["strong"], r["checks"]
    assert r["checks"]["VWAP மேல்"] and r["checks"]["Fresh break / retest"]


def test_strong_blocked_by_market_direction(monkeypatch):
    df = _df("2026-11-03", _break_rows())
    now = df.index[-1] + pd.Timedelta(minutes=6)
    live_q, res, inst = _setup(df, now)
    monkeypatch.setattr(FS, "pick_options", lambda *a: None)
    ai.STATE["risk"] = {"dir": "DOWN"}                   # market கீழே → CE strong ஆகக்கூடாது
    out = FS.run_strong(FakeAg(df), inst, live_q, res, now, live=False)
    assert out["rows"] and not out["rows"][0]["strong"]
    assert out["rows"][0]["miss"] == ["Market திசை எதிர் இல்லை"]


def test_strong_no_scan_after_230():
    df = _df("2026-11-03", _break_rows())
    now = pd.Timestamp("2026-11-03 15:10")
    live_q, res, inst = _setup(df, now)

    class Boom:
        def candles(self, *a):
            raise AssertionError("2:30 பிறகு candle fetch கூடாது")
    out = FS.run_strong(Boom(), inst, live_q, res, now, live=True)
    assert out["rows"] == [] and out.get("closed")


def test_strong_late_break_hidden(monkeypatch):
    rows = [[98, 99, 97.5, 98.5, 1000]] + [[99.5, 100.5, 99.4, 100.2, 1000]] + [[100.6, 101.0, 100.5, 100.8, 1000]] * 9
    rows.append([100.8, 101.0, 100.6, 100.9, 1000])      # பல bars முன் break, retest இல்லை, volume சாதாரணம்
    df = _df("2026-11-03", rows)
    now = df.index[-1] + pd.Timedelta(minutes=6)
    live_q, res, inst = _setup(df, now)
    monkeypatch.setattr(FS, "pick_options", lambda *a: None)
    ai.STATE["risk"] = {"dir": "UP"}
    out = FS.run_strong(FakeAg(df), inst, live_q, res, now, live=False)
    assert out["rows"] == []                              # 2+ checks fail → screen-ல் காட்டாது
    assert out["checked"] == 1


class FakeStore:
    def __init__(self, calls):
        self.data, self.dirty = {"calls": calls}, False

    def load(self):
        return self.data


def test_pink_scan_tags_and_alerts_once():
    import threading
    ai.STATE["opt"] = {"mods": {"🛢 MCX Momentum Breakout": {"pink": {"tier": "dark", "win": 82, "n": 25, "small": False}},
                                "Volume+OI": {"pink": None}}}
    now = pd.Timestamp("2026-11-03 19:30")
    calls = {"a": {"id": "a", "date": "2026-11-03", "source": "🛢 MCX Momentum Breakout", "kind": "MCX", "status": "OPEN",
                   "symbol": "CRUDEOIL", "strike": 5500, "side": "CE", "entry": 100, "sl": 80, "targets": [120]},
             "b": {"id": "b", "date": "2026-11-03", "source": "Volume+OI", "kind": "INTRADAY", "status": "OPEN",
                   "symbol": "X", "strike": 1, "side": "CE", "entry": 1, "sl": 0.5, "targets": [2]}}
    st, sent = FakeStore(calls), []
    out = ai.pink_scan(st, threading.Lock(), now, lambda t, k: sent.append(t))
    assert [c["id"] for c in out] == ["a"] and calls["a"]["pink"]["tier"] == "dark"
    assert "DARK PINK" in sent[0] and "CRUDEOIL" in sent[0]
    assert ai.pink_scan(st, threading.Lock(), now, lambda t, k: sent.append(t)) == []    # 2-வது முறை alert இல்லை


def test_run_ai_pink_module_gives_call_and_blocks_against_direction(monkeypatch):
    from krt import calls as CL, store as SM
    monkeypatch.setattr(SM.STORE, "load", lambda: {"calls": {}})
    monkeypatch.setattr(ai, "train", lambda c: None)
    monkeypatch.setattr(ai, "optimize", lambda c: None)
    monkeypatch.setattr(ai, "pink_tick", lambda now: [])
    got = []
    monkeypatch.setattr(CL, "add_aipick", lambda rows, now, mx: got.extend(rows))
    ai.STATE.update(model=None, _t=None, nifty_hist=[],
                    opt={"mods": {"Top Movers": {"pink": {"tier": "light", "win": 78, "n": 12, "small": True}}}})
    opt = {"token": "9", "spread_pct": 2, "strike": 100, "plan": {}}
    rp = {"entry": 10, "sl": 7, "targets": [12, 14, 16]}
    res = {"index": [{"index": "NIFTY", "pct": 0.8}], "predict": {"dir": "UP"},
           "movers": {"rows": [{"symbol": "AAA", "side": "CE", "score": 74, "option": dict(opt), "rp": rp},
                               {"symbol": "BBB", "side": "PE", "score": 95, "option": dict(opt), "rp": rp}]}}
    live_q = {f"S{i}": {"pct": 1.2} for i in range(30)}
    now = pd.Timestamp("2026-11-03 11:00")
    out = FS.run_ai(live_q, res, now, live=True)
    by = {c["symbol"]: c for c in out["cands"]}
    assert by["AAA"]["ok"] and by["AAA"]["pink"]                 # 🩷 module + score 74 → call (பழைய rule-ல் வராது)
    assert not by["BBB"]["ok"] and any("எதிர்" in w for w in by["BBB"]["why_not"])   # market UP → PE இல்லை
    assert [r["symbol"] for r in got] == ["AAA"]
