"""🔥 CALL OF THE DAY + 🏆 TOP 5 — site-ல் உள்ள எல்லா engines-ல் இருந்தும் (AI Lab ENTER · AI TAKE calls · DSK) நாளைக்கு max 5 strong picks.
முதல்ல lock ஆனது = Call of the Day. Lock ஆன நேரம் / entry / SL / T1-T3 நிரந்தரமா save → T1 → SL entry · T2 → SL T1 · T3 done · SL · 3:20 exit.
நேர்மை: confidence = score (probability இல்லை). Paper மட்டும்.
"""
import pandas as pd

CFG = {"max": 5, "min_conf": 80, "start": "09:30", "end": "14:15", "eod": "15:20"}
OPEN = ("OPEN", "T1 HIT", "T2 HIT")
STATE = {"time": None, "today": [], "err": None}


def candidates(calls, now):
    from .ai import STATE as AST
    from .ailab import AUTO, STATE as LAB, decide
    mdir = (AST.get("risk") or {}).get("dir")
    day = str(now.date())
    out = []
    for e in (LAB.get("enter") or {}).get("rows") or []:
        cv = ((e.get("chain") or {}).get("verdict")) or ""
        if e.get("status") != "OK" or (e.get("confidence") or 0) < CFG["min_conf"] or cv.startswith("⛔") or not e.get("token"):
            continue
        out.append({"src": e.get("src"), "symbol": e["symbol"], "side": e["side"], "strike": e.get("strike"), "expiry": e.get("expiry"), "lot": e.get("lot"),
                    "token": e["token"], "exch": e.get("exch", "NFO"), "contract": e.get("contract"), "entry": e.get("ltp") or e.get("entry"), "sl": e.get("sl"),
                    "targets": list(e.get("targets") or []), "conf": e.get("confidence"), "why": [w for w in [e.get("text")] + list(e.get("why") or [])[:2] if w],
                    "chain": cv})
    for c in calls:
        if c.get("date") != day or c.get("status") != "OPEN" or c.get("shadow") or c.get("kind") == "PICK" or c.get("exch") == "MCX" or not c.get("token"):
            continue
        conf = None
        if c.get("kind") == "DSK":
            conf = (c.get("dsk") or {}).get("score")
        elif decide(c, AUTO.get(c["id"]), mdir) == "TAKE":
            conf = int(min(95, (c.get("score") or 70) + (10 if c.get("pink") else 0)))
        if not conf or conf < CFG["min_conf"]:
            continue
        out.append({"src": c.get("source_label") or c.get("source") or c.get("kind"), "symbol": c["symbol"], "side": c["side"], "strike": c.get("strike"),
                    "expiry": c.get("expiry"), "lot": c.get("lot"), "token": c["token"], "exch": c.get("exch", "NFO"), "contract": c.get("contract"),
                    "entry": c.get("ltp") or c.get("entry"), "sl": c.get("sl"), "targets": list(c.get("targets") or []), "conf": conf,
                    "why": [w for w in [(AUTO.get(c["id"]) or {}).get("txt"), c.get("guide")] if w], "from_call": c["id"]})
    out.sort(key=lambda x: -(x["conf"] or 0))
    return out


def track(rec, ltp, hm):
    if rec["status"] not in OPEN or not ltp:
        return False
    rec["ltp"] = round(float(ltp), 2)
    tg, ch = rec.get("targets") or [], False
    for i, t in enumerate(tg[:3]):
        tag = f"T{i + 1}"
        if ltp >= t and not any(h.startswith(tag + " ") for h in rec["hits"]):
            rec["hits"].append(f"{tag} {hm}")
            ch = True
            if i == 0:
                rec["sl"], rec["status"] = rec["entry"], "T1 HIT"           # T1 → SL entry-க்கு
            elif i == 1:
                rec["sl"], rec["status"] = tg[0], "T2 HIT"                  # T2 → SL T1-க்கு
            else:
                rec.update(status="T3 DONE", exit=round(ltp, 2), exit_time=hm)
    if rec["status"] in OPEN and rec.get("sl") and ltp <= rec["sl"]:
        rec.update(status="TRAIL SL" if rec["hits"] else "SL HIT", exit=round(float(rec["sl"]), 2), exit_time=hm)
        ch = True
    px = rec.get("exit") if rec["status"] not in OPEN else ltp
    rec["pnl_lot"] = round((float(px) - float(rec["entry"])) * (rec.get("lot") or 1))
    return ch


def run(ag, now, calls, send=None):
    from .calls import CALLS_LOCK, STORE
    day, hm = str(now.date()), now.strftime("%H:%M")
    new = []
    with CALLS_LOCK:
        D = STORE.load()
        P = D.setdefault("day_picks", {})
        L = P.setdefault(day, [])
        if CFG["start"] <= hm <= CFG["end"] and len(L) < CFG["max"]:
            for x in candidates(calls, now):
                if len(L) >= CFG["max"]:
                    break
                if any(r["symbol"] == x["symbol"] for r in L) or not x.get("entry") or not x.get("sl") or len(x.get("targets") or []) < 1:
                    continue
                rec = {**x, "rank": len(L) + 1, "cotd": not L, "date": day, "time": hm, "status": "OPEN", "hits": [], "ltp": x["entry"], "pnl_lot": 0,
                       "sl0": x["sl"]}
                L.append(rec)
                new.append(rec)
                STORE.dirty = True
        live = [r for r in L if r["status"] in OPEN]
        if live and ag:
            toks = {}
            for r in live:
                toks.setdefault(r.get("exch", "NFO"), []).append(r["token"])
            try:
                qs = ag.quotes(toks) or {}
            except Exception:
                qs = {}
            for r in live:
                if track(r, (qs.get(r["token"]) or {}).get("ltp"), hm):
                    STORE.dirty = True
        if hm >= CFG["eod"]:
            for r in L:
                if r["status"] in OPEN:
                    r.update(status="EOD EXIT", exit=r.get("ltp"), exit_time=hm,
                             pnl_lot=round((float(r.get("ltp") or r["entry"]) - float(r["entry"])) * (r.get("lot") or 1)))
                    STORE.dirty = True
        for k in sorted(P)[:-60]:
            P.pop(k, None)
    for r in new:
        head = "🔥 CALL OF THE DAY" if r["cotd"] else f"🏆 TOP PICK #{r['rank']}"
        msg = (f"{head} · BUY {r['symbol']} {r.get('strike')} {r['side']}\nEntry ₹{r['entry']} · SL ₹{r['sl']} · T1/T2/T3 "
               + " / ".join(str(t) for t in r["targets"][:3]) + f" · confidence {r['conf']}/100\n{r.get('src') or ''}")
        if send:
            try:
                send(msg, f"daypick|{day}|{r['symbol']}", True)
            except Exception:
                pass
    STATE.update(time=now.strftime("%I:%M %p"), today=L)
    return L


def report(D, today):
    P = (D or {}).get("day_picks") or {}
    days = []
    for d in sorted(P, reverse=True)[:30]:
        L = P[d]
        cl = [r for r in L if r["status"] not in OPEN]
        w = sum((r.get("pnl_lot") or 0) > 0 for r in cl)
        days.append({"date": d, "n": len(L), "closed": len(cl), "win": w, "net": sum(r.get("pnl_lot") or 0 for r in cl),
                     "cotd": next((r for r in L if r.get("cotd")), None)})
    allc = [r for d in P for r in P[d] if r["status"] not in OPEN]
    cot = [r for r in allc if r.get("cotd")]
    st = lambda X: {"n": len(X), "win": round(sum((r.get("pnl_lot") or 0) > 0 for r in X) / len(X) * 100) if X else None,
                    "net": sum(r.get("pnl_lot") or 0 for r in X)}
    return {"today": P.get(today) or [], "days": days, "all": st(allc), "cotd": st(cot), "cfg": CFG}
