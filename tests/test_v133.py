"""v133: 🗺 Level Roadmap (first-passage probabilities, levels, calibration) · stale-while-revalidate status sections."""
import time

import pandas as pd

import server as S
from krt import roadmap as RM


def test_touch_prob_basics():
    assert RM.touch_prob(0, 0, 0.04, 60) == 1.0
    near, far = RM.touch_prob(0.15, 0, 0.04, 60), RM.touch_prob(0.55, 0, 0.04, 60)
    assert 0.55 < near < 0.7 and far < 0.1                     # 2Φ(−a/σ√T)
    assert RM.touch_prob(0.3, 0.002, 0.04, 60) > RM.touch_prob(0.3, 0, 0.04, 60) > RM.touch_prob(0.3, -0.002, 0.04, 60)
    assert RM.touch_prob(0.3, 0, 0.04, 30) < RM.touch_prob(0.3, 0, 0.04, 60)


def _feed(name="NIFTY", start=25600, step=-0.6, mins=70, t0="2026-11-23 12:30"):
    RM.H.pop(name, None)
    RM.DAY.pop(name, None)
    t0 = pd.Timestamp(t0)
    px = start
    for i in range(mins * 6):
        px += step / 6 + (1.5 if i % 2 else -1.5)
        RM.push(name, t0 + pd.Timedelta(seconds=10 * i), px)
    return t0 + pd.Timedelta(minutes=mins), px


def test_build_levels_and_order():
    now, px = _feed()
    ix = {"chain": [{"strike": 25400.0, "PE": {"oi": 5_200_000}, "CE": {"oi": 10}}, {"strike": 25600.0, "CE": {"oi": 4_000_000}, "PE": {"oi": 5}}],
          "support": 25400}
    m = RM.build("NIFTY", px, now, ix, {"dir": "DOWN", "prob": 66}, 51)
    d, u = m["down"], m["up"]
    assert all(r["level"] % 50 == 0 for r in d + u) and d[0]["level"] < px < u[0]["level"]
    assert [r["p60"] for r in d] == sorted([r["p60"] for r in d], reverse=True)       # nearer = more likely
    assert all(r["p30"] <= r["p60"] for r in d + u)
    w = [r for r in d if r["level"] == 25400.0]
    assert w and any("PE OI wall" in t for t in w[0]["tags"]) and any("scan support" in t for t in w[0]["tags"])
    assert m["sigma_src"].startswith("live") and "accuracy 51%" in m["drift"]
    assert d[0]["then"]["level"] == d[1]["level"] and m["lines"][0].startswith("⬇")


def test_poor_accuracy_barely_moves_numbers():
    now, px = _feed()
    a = RM.build("NIFTY", px, now, {}, {"dir": "DOWN", "prob": 80}, 50)
    b = RM.build("NIFTY", px, now, {}, None, None)
    assert a["down"][1]["p60"] == b["down"][1]["p60"]
    c = RM.build("NIFTY", px, now, {}, {"dir": "DOWN", "prob": 80}, 64)
    assert c["down"][1]["p60"] > b["down"][1]["p60"] and c["up"][0]["p60"] < b["up"][0]["p60"]


def test_fallback_sigma_from_day_range():
    RM.H.pop("SENSEX", None)
    RM.seed_day("SENSEX", pd.Timestamp("2026-11-23 13:00"), 84000, 82700)
    m = RM.build("SENSEX", 82800, pd.Timestamp("2026-11-23 13:00"))
    assert "range" in m["sigma_src"] and m["down"][0]["level"] % 100 == 0


class _Store:
    def __init__(self):
        self.d, self.dirty = {}, False

    def load(self):
        return self.d


def test_calibration_track():
    st = _Store()
    now, px = _feed(mins=20, t0="2026-11-23 11:00")
    m = RM.build("NIFTY", px, now)
    RM.track(m, st, now)
    assert st.d["roadmap_log"][0]["status"] == "PENDING"
    t0 = pd.Timestamp(st.d["roadmap_log"][0]["slot"])
    for i in range(400):
        RM.push("NIFTY", t0 + pd.Timedelta(seconds=10 * i + 1), px - i * 0.5)          # steady fall over 66 min
    out = RM.track(m, st, t0 + pd.Timedelta(minutes=66))
    p = st.d["roadmap_log"][0]
    assert p["status"] == "DONE" and p["hit"][0] == 1 and out["maps"] == 1


def test_roadmap_endpoint_and_swr():
    S.RMC.update(t=0, d=None)
    d = S.roadmap_state()
    assert set(d["maps"]) == {"NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"}
    calls = []

    def slowsec():
        if calls:
            time.sleep(0.1)
        calls.append(1)
        return {"n": len(calls)}
    f = S._swr(slowsec, every=0)
    assert f() == {"n": 1}
    time.sleep(0.01)
    assert f() == {"n": 1}                                  # served instantly, refresh in background
    time.sleep(0.4)
    assert f()["n"] >= 2 and f.__name__ == "slowsec"


def test_verdict_one_clear_answer():
    now, px = _feed(step=-3)                                  # strong fall → momentum bias down
    m = RM.build("NIFTY", px, now, {}, None, None)
    V = m["verdict"]
    assert V["dir"] == "DOWN" and "falls to" in V["head"] or "leaning down" in V["head"]
    assert "above" in V["cancel"]
    now, px = _feed(step=0)
    assert RM.build("NIFTY", px, now, {}, None, None)["verdict"]["dir"] == "RANGE"
