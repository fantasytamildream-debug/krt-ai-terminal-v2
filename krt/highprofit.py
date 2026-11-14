"""💰 HIGH-PROFIT STRATEGIES — the modules that REALLY made money in your closed paper calls, and today's calls from them.

A module qualifies when: 10+ closed calls · win rate ≥ 55% · positive average P/L per call · profit factor ≥ 1.5.
(Today these are typically V4 ⚡ ICT Silver Bullet, Gamma Unwind Classic, Index OI, Order Flow + Profile …)
Ranked by average profit per call. Every call from these modules today goes in the box (no limit) with a Paper button.
Rising alerts: an open call whose premium is climbing fast gets a 🚀 tag (see riser.py).
Honest: past results ≠ future results; a strategy's edge can fade — the table updates every minute.
"""
OPEN = ("OPEN", "T1 HIT", "T2 HIT")
CFG = {"min_n": 10, "min_win": 55, "min_pf": 1.5}


def module_table(calls):
    st = {}
    for c in calls:
        if c.get("shadow") or c.get("status") in OPEN or c.get("status") == "VOID" or c.get("kind") == "PICK" or c.get("pnl_lot") is None:
            continue
        m = st.setdefault(c.get("source") or c.get("kind"), {"n": 0, "w": 0, "gw": 0.0, "gl": 0.0, "net": 0.0})
        p = c.get("pnl_lot") or 0
        m["n"] += 1
        m["w"] += int(p > 0)
        m["net"] += p
        m["gw" if p > 0 else "gl"] += abs(p)
    out = []
    for k, m in st.items():
        win = round(m["w"] / m["n"] * 100) if m["n"] else 0
        pf = round(m["gw"] / m["gl"], 2) if m["gl"] else (9.0 if m["gw"] else 0.0)
        exp = round(m["net"] / m["n"]) if m["n"] else 0
        out.append({"module": k, "n": m["n"], "win": win, "pf": pf, "exp": exp, "net": round(m["net"]),
                    "ok": m["n"] >= CFG["min_n"] and win >= CFG["min_win"] and exp > 0 and pf >= CFG["min_pf"]})
    out.sort(key=lambda r: (-r["ok"], -r["exp"]))
    return out


def report(D, day, risers=None):
    calls = list(((D or {}).get("calls") or {}).values())
    T = module_table(calls)
    good = {r["module"]: r for r in T if r["ok"]}
    rise = {r["id"]: r for r in risers or []}
    today = []
    for c in sorted([c for c in calls if c.get("date") == day and not c.get("shadow") and c.get("kind") != "PICK"
                     and (c.get("source") or c.get("kind")) in good], key=lambda c: str(c.get("time") or ""), reverse=True):
        m = good[c.get("source") or c.get("kind")]
        today.append({**{k: c.get(k) for k in ("id", "time", "symbol", "strike", "side", "entry", "sl", "targets", "ltp", "exit", "status", "pnl_lot",
                                               "hits", "lot", "exch", "source", "source_label", "risk_warn")},
                      "m_win": m["win"], "m_pf": m["pf"], "m_exp": m["exp"], "m_n": m["n"], "rising": rise.get(c["id"])})
    done = [c for c in today if c["status"] not in OPEN]
    return {"modules": [r for r in T if r["ok"]], "near": [r for r in T if not r["ok"] and r["n"] >= 5 and r["exp"] > 0][:6], "today": today,
            "stats": {"n": len(done), "win": round(sum((c["pnl_lot"] or 0) > 0 for c in done) / len(done) * 100) if done else None,
                      "net": round(sum(c["pnl_lot"] or 0 for c in done))}, "cfg": CFG}
