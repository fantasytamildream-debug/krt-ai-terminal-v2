"""v156: strike chart endpoint + 📈 Chart next to every 📝 Paper."""
import numpy as np
import pandas as pd
import server as S


def test_optchart_api(monkeypatch):
    idx = pd.date_range("2026-11-27 09:15", periods=60, freq="5min")
    c = 100 + np.arange(60) * 0.5
    df = pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c + 0.2, "volume": 100}, index=idx)

    class A:
        def candles(self, *a, **k):
            return df
    monkeypatch.setattr(S, "angel_configured", lambda: True)
    monkeypatch.setattr(S, "get_angel", lambda: A())
    monkeypatch.setattr(S, "opt_quotes", lambda items: {"123": {"ltp": 130.0, "bid": 129.5, "ask": 130.5, "oi": 5000}})
    S.OPCC.clear()
    r = S.optchart_api("123", "BFO", "5")
    assert r["ok"] and len(r["candles"]) == 60 and r["ltp"] == 130.0 and r["exch"] == "BFO"
    assert S.optchart_api("abc", "NFO", "5")["ok"] is False


def test_chart_button_everywhere():
    h = open("web/index.html", encoding="utf-8").read()
    assert "chartBtn(o)" in h and "chartFromCall(" in h and "function ocAddBtns()" in h and "if(OCCAP){ OCCAP=o||{}; return; }" in h
    for k in ("ENTRY ZONE", "STOP ZONE", "#2563eb", "#0f766e", "no lot fits ₹2,500"):
        assert k in h
