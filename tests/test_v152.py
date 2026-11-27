"""v152: module autopilot · desk breadth fix · Jackpot Mannan name clash · time badges · brain advice."""
import re
from krt import autopilot as AP


def _c(src, date, pnl=None, status="SL HIT"):
    return {"source": src, "date": date, "time": "10:00", "kind": "INTRADAY", "pnl_lot": pnl, "status": status}


def test_autopilot_loosens_per_day_without_setup():
    AP.AP["lvl"] = {k: 0 for k in AP.TARGETS}
    H = {}
    calls = [_c("Gamma Unwind Classic", "2026-11-17", 500, "T3 DONE"), _c("V4 ⚡ ICT Silver Bullet", "2026-11-25", 800, "TRAIL SL"),
             _c("🛢 ⚡ ICT Silver Bullet", "2026-11-26", 100, "TRAIL SL")]
    st = AP.update(calls, "2026-11-27", H)
    m = st["modules"]
    assert m["GU"]["level"] == 3 and m["SILVER"]["level"] == 1 and m["INDEXJP"]["level"] == 3
    assert AP.level("SILVER") == 1 and H["2026-11-27"]["GU"] == 3


def test_autopilot_steps_back_after_losses():
    H = {"2026-11-24": {"GU": 2}, "2026-11-25": {"GU": 2}, "2026-11-26": {"GU": 3}}
    calls = [_c("Gamma Unwind Classic", "2026-11-24", -900), _c("Gamma Unwind Classic", "2026-11-25", -800),
             _c("Gamma Unwind Classic", "2026-11-26", 1500, "T3 DONE")]
    AP.AP["lvl"]["GU"] = 3
    st = AP.update(calls, "2026-11-27", H)
    assert st["modules"]["GU"]["level"] == 0 and "stepped back" in st["modules"]["GU"]["note"]


def test_gu_and_silver_use_autopilot():
    src = open("krt/gamma_unwind.py", encoding="utf-8").read()
    assert '_apl("GU")' in src and "0.25 * apl" in src
    v4 = open("krt/v4.py", encoding="utf-8").read()
    assert '_apl("SILVER")' in v4 and '["09:45", "11:30"]' in v4
    fs = open("krt/fullscan.py", encoding="utf-8").read()
    assert '75 - 4 * _apl("INDEXJP")' in fs


def test_no_duplicate_js_functions():
    h = open("web/index.html", encoding="utf-8").read()
    names = re.findall(r"function ([A-Za-z0-9_]+)\(", h)
    dup = sorted({n for n in names if names.count(n) > 1})
    assert dup == [], dup
    assert "function mnBoxHTML(M)" in h and "function mannanHTML(s)" in h and "function optimHTML(f)" in h


def test_desk_state_breadth_tuple(monkeypatch):
    import server as S
    import krt.calls as K
    monkeypatch.setattr(K, "breadth_now", lambda: (118, 99))
    monkeypatch.setattr(S, "load_inst", lambda p: {"eq": {}, "mcx_fut": {}})
    monkeypatch.setattr(S, "_tri_d5", lambda *a, **k: None)
    d = S.desk_state()
    assert d["breadth"] == {"up": 118, "down": 99}
