"""v122: SMC/ICT engine — non-repainting swings, sweep → MSS → retest → ENTRY CONFIRMED, BOS + OB, boxes, risk cap."""
import pandas as pd

from krt import smc as S


def mk(path, start="2026-11-18 09:15", vol=1000):
    """path: list of (open, high, low, close) → 5-min DataFrame."""
    idx = pd.date_range(start, periods=len(path), freq="5min")
    return pd.DataFrame([{"open": o, "high": h, "low": l, "close": c, "volume": vol} for o, h, l, c in path], index=idx)


def bearish_sweep_path():
    P = []
    px = 100.0
    for i in range(20):                                   # drift up with small swings
        o = px
        c = px + (0.4 if i % 4 < 2 else -0.3)
        P.append((o, max(o, c) + 0.2, min(o, c) - 0.2, c))
        px = c
    # clear swing high at 103.5 then pull back to make a swing low ~101.8
    for o, h, l, c in [(px, 103.3, px - 0.1, 103.0), (103.0, 103.5, 102.7, 102.9), (102.9, 103.0, 102.2, 102.3), (102.3, 102.4, 101.8, 102.0),
                       (102.0, 102.6, 101.9, 102.5), (102.5, 102.9, 102.4, 102.8), (102.8, 103.1, 102.7, 103.0)]:
        P.append((o, h, l, c))
    # SWEEP: wick above 103.5 to 104.0, close back below at 103.2
    P.append((103.0, 104.0, 102.9, 103.2))
    # bearish displacement → closes below the swing low 101.8 (MSS) leaving an FVG
    P.append((103.2, 103.25, 102.4, 102.45))
    P.append((102.45, 102.5, 101.0, 101.1))
    P.append((101.1, 101.2, 100.6, 100.7))
    # retest up into the FVG (102.4–102.5 area) and red rejection close
    P.append((100.7, 101.4, 100.6, 101.3))
    P.append((101.3, 102.7, 101.2, 101.25))
    # move down afterwards
    for k in range(6):
        b = 101.5 - k * 0.6
        P.append((b, b + 0.1, b - 0.6, b - 0.5))
    return P


def test_swings_confirmed_only_after_k_bars():
    df = mk(bearish_sweep_path())
    sw = S.swings(df)
    assert all(s["conf"] == s["i"] + 2 for s in sw)
    # analysing a prefix never shows a swing whose confirmation bar is missing (no repaint / no look-ahead)
    cut = 32
    an = S.analyse(df.iloc[:cut])
    known = {(e["i"], e["name"]) for e in an["events"]}
    an_full = S.analyse(df)
    early = {(e["i"], e["name"]) for e in an_full["events"] if e["i"] < cut and e["name"] not in ("Bullish OB", "Bearish OB")}
    assert early <= known | {(e["i"], e["name"]) for e in an["events"]}


def test_prefix_events_do_not_change_later():
    df = mk(bearish_sweep_path())
    for cut in range(30, len(df)):
        a1 = S.analyse(df.iloc[:cut])
        a2 = S.analyse(df.iloc[:cut + 1])
        e1 = [(e["i"], e["name"], e["side"]) for e in a1["events"] if e["name"] not in ("Bullish OB", "Bearish OB")]
        e2 = [(e["i"], e["name"], e["side"]) for e in a2["events"] if e["i"] < cut and e["name"] not in ("Bullish OB", "Bearish OB")]
        assert e1 == e2, cut


def test_bearish_sweep_reversal_confirmed():
    df = mk(bearish_sweep_path())
    an = S.analyse(df, {"PDH": 110, "PDL": 90})
    names = [e["name"] for e in an["events"]]
    assert "BSL sweep" in names
    assert any(n in names for n in ("MSS", "CHOCH", "BOS"))
    sts = S.setups(an, "AAA")
    sr = [s for s in sts if s["kind"] == "Sweep reversal" and s["side"] == "PE"]
    assert sr, [(s["kind"], s["side"], s["state"]) for s in sts]
    s = sr[0]
    assert s["state"] in ("ENTRY CONFIRMED", "TARGET HIT", "STOPLOSS HIT"), s.get("why")
    assert s["sl"] > 104.0                                  # beyond the sweep high + buffer
    assert s["targets"][0] < s["entry"] and s["rr"] is not None


def test_sweep_alone_is_not_a_trade():
    P = bearish_sweep_path()[:28]                          # stop right after the sweep candle
    an = S.analyse(mk(P))
    sts = [s for s in S.setups(an, "AAA") if s["kind"] == "Sweep reversal"]
    assert sts and all(s["state"] in ("PATTERN DETECTED", "EXPIRED", "INVALIDATED") for s in sts)
    assert all(not s.get("entry") for s in sts)


def test_option_plan_risk_cap_and_model_label():
    st = {"entry": 101.5, "sl": 104.3, "targets": [99.0, 97.0, 95.0]}
    p, why = S.option_plan(st, {}, 500, 12.0, 0.5, 60, 1.0)
    assert p["sl"] < 12.0 and p["targets"][0] > 12.0 and "estimate" in p["model"]
    assert why is None or "2,500" in why
    p2, why2 = S.option_plan(st, {}, 5000, 12.0, 0.5, 60, 1.0)
    assert "2,500" in why2
    p3, why3 = S.option_plan(st, {}, 500, 12.0, 0.5, 60, 8.0)
    assert "spread" in why3
    assert S.option_plan(st, {}, 500, None)[1] == "missing option quote"


def test_chart_payload_has_boxes():
    df = mk(bearish_sweep_path())
    an = S.analyse(df)
    sts = S.setups(an, "AAA")
    ch = S.chart_payload(an, sts)
    assert len(ch["candles"]) == len(df)
    assert any(z["k"] == "FVG" for z in ch["zones"])
    pos = [p for p in ch["pos"] if p["side"] == "PE"]
    assert pos and pos[0]["sl"] > pos[0]["entry"] > pos[0]["tp"]
    assert pos[0]["sweep"] and pos[0]["sweep"]["top"] >= 104.0


def test_run_vetoes_and_records():
    df = mk(bearish_sweep_path())

    class St:
        def __init__(self):
            self.d, self.dirty = {"calls": {}}, False

        def load(self):
            return self.d
    import threading
    st = St()
    out = S.run({"AAA": df}, df.index[-1], {"market_open": False, "levels": {}, "live_q": {}}, store=st, lock=threading.Lock())
    s = [x for x in out["setups"] if x["kind"] == "Sweep reversal"][0]
    assert "market closed — no live entry" in s["veto"] and s["decision"] != "TAKE"
    assert out["overview"][0]["mtf"]["5m"] in ("UP", "DOWN", "RANGE")
    assert any(r["pattern"] == "BSL sweep" for r in out["rows"])
    rec = st.d.get("smc") or {}
    assert rec and all(r["model"] == "smc-v1" for r in rec.values())
    first = dict(next(iter(rec.values())))
    S.run({"AAA": df}, df.index[-1], {"market_open": False}, store=st, lock=threading.Lock())
    again = next(iter(st.d["smc"].values()))
    assert {k: again[k] for k in ("entry", "sl", "targets", "recorded")} == {k: first[k] for k in ("entry", "sl", "targets", "recorded")}
    assert out["setups"][0]["explain"]


def test_bullish_mirror_gives_ce():
    P = [(200 - o, 200 - l, 200 - h, 200 - c) for o, h, l, c in bearish_sweep_path()]
    an = S.analyse(mk(P))
    assert "SSL sweep" in [e["name"] for e in an["events"]]
    s = [x for x in S.setups(an, "BBB") if x["kind"] == "Sweep reversal" and x["side"] == "CE"][0]
    assert s["state"] in ("ENTRY CONFIRMED", "TARGET HIT", "STOPLOSS HIT") and s["sl"] < 96.0 and s["targets"][0] > s["entry"]
