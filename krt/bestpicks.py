"""🤖 AI BEST PICKS + 🪙 GOLDEN CALLS — every open call scored with ALL analyses, best ones picked with time, results tracked.

Score (0-100) = Sniper SQS (price action / order flow / volume+VWAP / options / regime / risk)
   + chart 15-method verdict (TAKE +10 · AVOID -20) + AI Lab decision (TAKE +8 · SKIP -12)
   + previous day / week / month high-low break in call direction (+4 each)
   + volume >= 2x (+5) + footprint agrees (+8 / opposite -8)
   + entry state (in entry zone +5 · already ran > 5% -15 · near SL -30)
PICK   = score >= 75, not late, not near SL  (max 6 a day)
GOLDEN = score >= 88 + chart TAKE + >= 1 level broken + (AI Lab TAKE or proven module)
Honest: weights are rules, not a guarantee — the results table below shows the real win %.
"""
OPEN = ("OPEN", "T1 HIT", "T2 HIT")
CFG = {"pick": 75, "golden": 88, "max_day": 10 ** 6}
STATE = {"time": None, "rows": [], "new": []}


def strike_history(calls, symbol, side, strike=None):
    """How many past calls on this stock + side hit T1 vs SL (and on this exact strike)."""
    def st(L):
        done = [c for c in L if c.get("status") not in OPEN and c.get("status") != "VOID"]
        t1 = sum(1 for c in done if any(str(h).startswith("T1") for h in c.get("hits") or []) or str(c.get("status", "")).startswith("T"))
        sl = sum(1 for c in done if "SL" in str(c.get("status", "")) and not c.get("hits"))
        return {"n": len(done), "t1": t1, "sl": sl, "win": round(sum((c.get("pnl_lot") or 0) > 0 for c in done) / len(done) * 100) if done else None}
    mine = [c for c in calls if c.get("symbol") == symbol and c.get("side") == side and not c.get("shadow") and c.get("kind") != "PICK"]
    out = {"all": st(mine)}
    if strike is not None:
        out["strike"] = st([c for c in mine if c.get("strike") == strike])
    return out


def level_breaks(levels, px, side):
    if not levels or not px:
        return []
    keys = ("PDH", "PWH", "PMH") if side == "CE" else ("PDL", "PWL", "PML")
    name = {"PDH": "prev-day high", "PWH": "prev-week high", "PMH": "prev-month high", "PDL": "prev-day low", "PWL": "prev-week low", "PML": "prev-month low"}
    out = []
    for k in keys:
        v = levels.get(k)
        if v and ((px > v) if side == "CE" else (px < v)):
            out.append(f"{name[k]} {v:g} broken")
    return out


def score_one(c, q, chart_row, lab, levels, ul_px, guide, proven):
    sc = float(q.get("score") or 50)
    why = []
    ce = c.get("side") != "PE"
    vd = (chart_row or {}).get("verdict")
    if vd == "TAKE":
        sc += 10
        why.append(f"chart 15-method TAKE ({(chart_row or {}).get('mscore')}/100)")
    elif vd == "AVOID":
        sc -= 20
        why.append("chart says AVOID")
    lv = (lab or {}).get("verdict")
    if lv == "TAKE":
        sc += 8
        why.append("AI Lab TAKE")
    elif lv == "SKIP":
        sc -= 12
        why.append("AI Lab SKIP")
    br = level_breaks(levels, ul_px, c.get("side")) if c.get("exch") != "MCX" else []
    sc += 4 * len(br)
    why += br
    vr = float(c.get("vol_ratio") or 0)
    if vr >= 2:
        sc += 5
        why.append(f"volume {vr:.1f}x")
    g = guide or {}
    if g:
        if g.get("side") == c.get("side") and g.get("k") in ("BUY", "RISK", "STRIKE"):
            sc += 8
            why.append("footprint buyers" if ce else "footprint sellers")
        elif g.get("side") and g.get("side") != c.get("side") and g.get("k") in ("BUY", "RISK", "STRIKE", "WAIT"):
            sc -= 8
            why.append("footprint against")
    e, sl, ltp = float(c.get("entry") or 0), float(c.get("sl") or 0), float(c.get("ltp") or 0)
    state = "ENTER"
    if e and ltp:
        mv = (ltp - e) / e * 100
        if sl and ltp <= sl + (e - sl) * 0.25:
            sc -= 30
            state = "NEAR SL"
        elif mv > 5:
            sc -= 15
            state = f"LATE +{mv:.0f}%"
        else:
            sc += 5
    sc = max(0, min(100, round(sc)))
    if state == "NEAR SL":           # SL அருகில் — மற்ற analysis எவ்வளவு நல்லா இருந்தாலும் high score காட்டக்கூடாது
        sc = min(sc, 40)
    elif state.startswith("LATE"):
        sc = min(sc, 70)
    golden = sc >= CFG["golden"] and vd == "TAKE" and len(br) >= 1 and (lv == "TAKE" or proven)
    return {"score": sc, "why": why, "state": state, "golden": bool(golden), "breaks": br}


def run(D, now, sniper_rows, charts_table, lab_auto, levels, live_q, guides, proven, send=None):
    """Every 60 s: score all open calls; new PICK / GOLDEN saved with the time it was picked (push + voice)."""
    day = str(now.date())
    calls = list((D.get("calls") or {}).values())
    J = D.setdefault("best_picks", {})
    sq = {r["id"]: r for r in sniper_rows or []}
    ct = {r["id"]: r for r in charts_table or []}
    rows = []
    for c in calls:
        if c.get("date") != day or c.get("status") not in OPEN or c.get("shadow") or c.get("kind") == "PICK":
            continue
        q = sq.get(c["id"]) or {}
        ul = ((live_q or {}).get(c["symbol"]) or {}).get("ltp") or c.get("ul_price")
        r = score_one(c, q, ct.get(c["id"]), (lab_auto or {}).get(c["id"]), (levels or {}).get(c["symbol"]), ul, (guides or {}).get(c["symbol"]),
                      (c.get("source") in (proven or set())))
        r.update(id=c["id"], symbol=c["symbol"], side=c.get("side"), strike=c.get("strike"), sqs=q.get("tier"))
        rows.append(r)
    rows.sort(key=lambda r: -r["score"])
    today = [p for p in J.values() if p["date"] == day]
    new = []
    for r in rows:
        if r["id"] in J:
            if r["golden"] and not J[r["id"]].get("golden"):
                J[r["id"]].update(golden=True, golden_time=now.strftime("%H:%M"))
                new.append(J[r["id"]])
            continue
        if r["score"] < CFG["pick"] or r["state"] != "ENTER" or len(today) >= CFG["max_day"]:
            continue
        c = D["calls"][r["id"]]
        p = {"id": r["id"], "date": day, "time": now.strftime("%H:%M"), "score": r["score"], "golden": r["golden"], "why": r["why"][:5],
             "symbol": c["symbol"], "side": c.get("side"), "strike": c.get("strike"), "entry": c.get("entry"), "sl": c.get("sl"), "targets": c.get("targets"),
             "lot": c.get("lot"), "source": c.get("source_label") or c.get("source"), "hist": strike_history(calls, c["symbol"], c.get("side"), c.get("strike"))}
        J[r["id"]] = p
        today.append(p)
        new.append(p)
    if send:
        for p in new:
            try:
                head = ("🪙 GOLDEN CALL" if p.get("golden") else "🤖 AI BEST PICK")
                send(f"{head} · {p['symbol']} {p['strike']:g} {p['side']}\nBuy ₹{p['entry']} · SL ₹{p['sl']} · T1/T2/T3 " + " / ".join(str(t) for t in p.get("targets") or [])
                     + f"\nScore {p['score']}/100 · " + " · ".join(p.get("why") or [])[:160], f"bp|{p['id']}|{p.get('golden')}", True)
            except Exception:
                pass
    STATE.update(time=now.strftime("%I:%M %p"), rows=rows[:25], new=[p["id"] for p in new])
    return new


def report(D, day):
    calls = (D or {}).get("calls") or {}
    J = (D or {}).get("best_picks") or {}
    out = []
    for p in sorted(J.values(), key=lambda p: (p["date"], p["time"]), reverse=True)[:120]:
        c = calls.get(p["id"]) or {}
        out.append({**p, "status": c.get("status"), "ltp": c.get("ltp"), "exit": c.get("exit"), "pnl_lot": c.get("pnl_lot") or 0, "hits": c.get("hits") or []})
    done = [p for p in out if p["status"] and p["status"] not in OPEN]

    def st(L):
        return {"n": len(L), "win": round(sum(p["pnl_lot"] > 0 for p in L) / len(L) * 100) if L else None, "net": round(sum(p["pnl_lot"] for p in L))}
    return {"time": STATE["time"], "today": [p for p in out if p["date"] == day], "history": out, "live": STATE["rows"],
            "stats": {"all": st(done), "golden": st([p for p in done if p.get("golden")])}, "cfg": CFG}
