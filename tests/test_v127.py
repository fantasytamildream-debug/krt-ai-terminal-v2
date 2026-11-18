"""v127: expert-style method screens + consensus."""
from krt import experts as EX


def LQ():
    return {"AAA": {"ltp": 110, "pct": -1.5, "vol_ratio": 2.0, "high": 113, "low": 109.5, "vwap": 111.5},
            "BBB": {"ltp": 50, "pct": 2.0, "vol_ratio": 2.2, "high": 50.2, "low": 48.5, "vwap": 49.4}}


def test_pa_oi_trades_only_with_market():
    lv = {"AAA": {"PDL": 110.5, "PDH": 116}, "BBB": {"PDH": 49.8}}
    oi = {"AAA": "Short Built Up", "BBB": "Long Built Up"}
    down = EX.price_action_oi(LQ(), lv, oi, -0.7)
    assert [p["symbol"] for p in down] == ["AAA"] and down[0]["side"] == "PE" and down[0]["score"] >= 70
    up = EX.price_action_oi(LQ(), lv, oi, 0.6)
    assert [p["symbol"] for p in up] == ["BBB"] and up[0]["side"] == "CE"


def test_quality_rank_needs_strong_sector_and_rs():
    secs = {"IT": 1.2, "Bank": -0.5, "Metal": -1.5, "Auto": 0.4, "Pharma": 0.2, "Energy": -0.1}
    sector_of = {"BBB": "IT", "AAA": "Metal"}
    sma = {"BBB": {"c": 50, "s20": 48, "s50": 45}}
    r = EX.quality_rank(LQ(), secs, sector_of, {"BBB": "Long Built Up"}, 0.4, {"BBB": 88}, sma)
    assert r and r[0]["symbol"] == "BBB" and r[0]["side"] == "CE"
    r = EX.quality_rank(LQ(), secs, sector_of, {}, -0.4, {}, {})
    assert r and r[0]["symbol"] == "AAA" and r[0]["side"] == "PE"


def test_vcp_long_only_and_rs_filter():
    pb = [{"symbol": "BBB", "side": "CE", "status": "BREAKING", "score": 80, "comp": 0.6, "bw_pct": 12, "vol_dry": 0.7, "nr7": True,
           "level": 49.8, "dist": 0.3, "ul_sl": 48.9, "ul_target": 51.2},
          {"symbol": "AAA", "side": "PE", "status": "BREAKING", "score": 90},
          {"symbol": "CCC", "side": "CE", "status": "NEAR", "score": 90, "level": 10}]
    r = EX.vcp_breakout(pb, {"BBB": 85, "CCC": 40}, {}, LQ())
    assert [p["symbol"] for p in r] == ["BBB"] and "BREAKING" in " ".join(r[0]["why"])


def test_consensus_needs_two_engines():
    r = EX.consensus([("A", 2, [("X", "CE"), ("Y", "PE")]), ("B", 1, [("X", "CE")]), ("C", 2, [("Z", "CE")])], "CE")
    assert [p["symbol"] for p in r] == ["X"] and "2 engines agree" in r[0]["why"][0]
