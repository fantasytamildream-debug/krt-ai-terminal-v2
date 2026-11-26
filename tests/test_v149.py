"""v149: brake is warn-only (calls never hidden) · Mannan box ranks the best pick A→Z."""
import datetime as dt
import server as S
import krt.calls as K


def test_rank_prefers_volume_sector_buyers_big(monkeypatch):
    from krt import fullscan as FSm, bigvol as BV, money as MO
    day = str(S.now_ist().date())
    hm = S.now_ist().strftime("%H:%M")
    monkeypatch.setitem(FSm.C, "live_q", {"AAA": {"vol_ratio": 3.2, "pct": 1.4}, "BBB": {"vol_ratio": 0.7, "pct": -0.8}})
    secs = [{"sector": f"S{i}", "pct": 2 - i * 0.4} for i in range(8)]
    monkeypatch.setitem(S.STATE, "full", {"money": {"sectors": secs}})
    monkeypatch.setitem(MO.SECTOR, "AAA", "S0")
    monkeypatch.setitem(MO.SECTOR, "BBB", "S7")
    BV.FEED.clear(); BV.EARLY.clear()
    BV.FEED["AAA|x"] = {"date": day, "time": hm, "symbol": "AAA", "side": "CE"}
    seq = iter([{"T1": {"oi": 1000, "vol": 100, "ltp": 10}, "T2": {"oi": 1000, "vol": 100, "ltp": 10}},
                {"T1": {"oi": 1100, "vol": 9000, "ltp": 12}, "T2": {"oi": 1100, "vol": 200, "ltp": 9}}])
    monkeypatch.setattr(S, "opt_quotes", lambda items: next(seq))
    S.MNOI.clear()
    rows = [{"id": "a", "status": "OPEN", "verdict": "TAKE", "symbol": "AAA", "side": "CE", "token": "T1", "exch": "NFO", "src": "5-min ORB"},
            {"id": "b", "status": "OPEN", "verdict": "TAKE", "symbol": "BBB", "side": "CE", "token": "T2", "exch": "NFO", "src": "5-min ORB"}]
    cmap = {"a": {"source": "5-min ORB", "lot": 50, "risk": 2000}, "b": {"source": "5-min ORB", "lot": 50, "risk": 4000, "brake": "lunch chop"}}
    tiers = {"5-min ORB": {"win": 55}}
    try:
        S._mn_rank([dict(r) for r in rows], cmap, 0.4, tiers, day)          # first look (baseline OI)
        best = S._mn_rank(rows, cmap, 0.4, tiers, day)
    finally:
        BV.FEED.clear()
    assert best[0]["symbol"] == "AAA" and best[0]["score"] >= 70
    g = " ".join(best[0]["good"])
    assert "volume" in g and "sector" in g and "buyers entering" in g and "big buyers" in g
    b = [x for x in best if x["symbol"] == "BBB"][0]
    assert b["score"] < 60 and any("writers" in x for x in b["bad"]) and any("🧯" in x for x in b["bad"])


def test_brake_is_warning_only():
    src = open(K.__file__, encoding="utf-8").read()
    assert 'c["brake"] = bk_[1]' in src and "shadow_code=bk_[0]" not in src
