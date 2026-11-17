"""v120: alert time + date · ⚡ early big-player detector · V4 proven strategies become calls."""
import pandas as pd

from krt import bigvol as BV, v4 as V


def test_eff_min_proven_bar():
    S = V.settings()
    assert V.eff_min(S, "SILVER") == 60
    assert V.eff_min(S, "GAMMA") == 65
    assert V.eff_min(S, "CQSMC") <= S["min_score"]
    assert S["strategies"]["SILVER"] is True


def test_option_plan_cheap_premium_not_rejected():
    S = V.settings()
    o = {"lot": 75, "ltp": 12.0, "delta": 0.5}
    p, why = V.option_plan(o, 24000, 23960, S)
    assert p, why
    assert 0 < p["sl"] < 12.0 and p["note"].startswith("Cheap premium")
    assert p["warn"] == ""


def test_option_plan_far_sl_is_note_not_block():
    S = V.settings()
    o = {"lot": 75, "ltp": 200.0, "delta": 0.5}
    p, _ = V.option_plan(o, 24000, 23800, S)          # structure risk 7,500 > 4,000
    assert p and p["warn"] == "" and "capped" in p["note"]
    assert p["risk"] <= 2500 + 5


def test_feed_has_candle_end_and_seen():
    BV.FEED.clear()
    t = str(pd.Timestamp.now(tz="Asia/Kolkata").date()) + " 13:50"
    BV._feed_add("TESTSYM", [{"time": t, "side": "BUY", "mult": 3.0, "price": 100.0}], "NSE", {}, 101.0)
    r = BV.FEED[f"TESTSYM|{t}"]
    assert r["end"] == "13:55" and len(r["seen"]) == 8
    BV.FEED.clear()


def test_early_detector_fires_on_volume_burst():
    BV.EH.clear()
    BV.EARLY.clear()
    inst = {"fno": ["AAA"], "eq": {"AAA": "11"}}
    t0 = pd.Timestamp("2026-11-17 10:00")
    vol, px = 0, 100.0
    sent = []
    for i in range(10):                              # quiet: 1,000 shares a minute, flat price
        vol += 1000
        BV.early(None, inst, t0 + pd.Timedelta(minutes=i), quotes={"11": {"tradeVolume": vol, "ltp": px}})
    assert not BV.EARLY
    for i, px in ((10, 100.2), (11, 100.6)):         # burst: 20,000 a minute + price up
        vol += 20000
        BV.early(None, inst, t0 + pd.Timedelta(minutes=i), send=lambda m, k, p: sent.append(m),
                 quotes={"11": {"tradeVolume": vol, "ltp": px}})
    rows = list(BV.EARLY.values())
    assert rows and rows[0]["side"] == "BUY" and rows[0]["mult"] >= 5
    assert sent and "17 Nov" in sent[0] and "EARLY" in sent[0]
    n = len(BV.EARLY)                                # cooldown: no repeat alert next minute
    vol += 20000
    BV.early(None, inst, t0 + pd.Timedelta(minutes=12), quotes={"11": {"tradeVolume": vol, "ltp": 101.0}})
    assert len(BV.EARLY) == n
    BV.EH.clear()
    BV.EARLY.clear()


def test_module_health_lists_v4_strategies():
    from krt.calls import module_health
    rows = module_health({"calls": {}}, pd.Timestamp("2026-11-17 10:30"))
    srcs = {r["source"] for r in rows}
    assert "V4 ⚡ ICT Silver Bullet" in srcs
    sb = [r for r in rows if r["source"] == "V4 ⚡ ICT Silver Bullet"][0]
    assert "ACTIVE" in sb["status"]


def test_v4_source_ready_entry_path():
    src = open(V.__file__, encoding="utf-8").read()
    assert 'go_stage = s_["stage"] == "CONFIRMED" or (proven and s_["stage"] == "READY")' in src
    assert 'if s_["score"] < bar:' in src
