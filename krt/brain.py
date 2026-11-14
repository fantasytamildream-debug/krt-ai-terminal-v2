"""🧠 KRT BRAIN — free trading AI that runs on your own server (no API, no cost).

It is not a general chatbot like Fable — it is a specialist: expert trading rules written as code + your modules' REAL results
+ a machine-learning model trained on your own closed calls (used ONLY if it beats the baseline in walk-forward testing).

For every open call:  hard blockers → confirmations → score → TAKE / WATCH / SKIP with plain-English reasons.
  Blockers: premium already +5% (late) · near SL · against NIFTY (not MCX) · module loses money in real results (15+ trades) ·
            no volume confirmation · crash radar against the side
  Confirmations: chart 15-method TAKE · prev day/week/month level broken · footprint agrees · proven module · Sniper PRIORITY ·
                 AI Lab TAKE · volume >= 2x · candlestick pattern in the call's direction
  Score = 45% best-pick score + 35% module's real win rate (Wilson lower bound — small samples count less) + 20% ML (if ON)
  TAKE = no blocker + 2+ confirmations + score >= 72 (max 3 a day) · GOLD = TAKE + 4+ confirmations + proven module + score >= 85
Honest: no AI can promise profit. Judge it by the results table.
"""
import math

import numpy as np

OPEN = ("OPEN", "T1 HIT", "T2 HIT")
CFG = {"pick": 72, "gold": 85, "max_day": 10 ** 6, "min_conf": 2, "late_pct": 5}
STATE = {"time": None, "rows": [], "model": None}


def wilson(w, n, z=1.96):
    if not n:
        return 0.0
    p = w / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def module_table(calls):
    T = {}
    for c in calls:
        if c.get("shadow") or c.get("kind") == "PICK" or c.get("status") in OPEN or c.get("status") == "VOID":
            continue
        m = T.setdefault(c.get("source") or c.get("kind"), {"n": 0, "w": 0, "net": 0.0, "gw": 0.0, "gl": 0.0})
        p = float(c.get("pnl_lot") or 0)
        m["n"] += 1
        m["w"] += int(p > 0)
        m["net"] += p
        m["gw" if p > 0 else "gl"] += abs(p)
    for m in T.values():
        m["win"] = round(m["w"] / m["n"] * 100) if m["n"] else None
        m["exp"] = round(m["net"] / m["n"]) if m["n"] else 0
        m["pf"] = round(m["gw"] / m["gl"], 2) if m["gl"] else (9.0 if m["gw"] else 0.0)
        m["lb"] = round(wilson(m["w"], m["n"]), 3)
        m["proven"] = m["n"] >= 15 and m["exp"] > 0 and m["pf"] >= 1.5
    return T


def ml_prob(c, M):
    if not M or not M.get("m") or not (M.get("wf") or {}).get("useful"):
        return None
    try:
        from .dsk import feats
        return float(M["m"].predict([feats(c)])[0])
    except Exception:
        return None


def verdict(c, bp=None, q=None, chart=None, lab=None, guide=None, mods=None, mdir=None, crash=None, M=None, candles=None):
    bp, q, chart, lab, guide, mods = bp or {}, q or {}, chart or {}, lab or {}, guide or {}, mods or {}
    ce = c.get("side") != "PE"
    want = "UP" if ce else "DOWN"
    block, conf, risk = [], [], []
    e, ltp, sl = float(c.get("entry") or 0), float(c.get("ltp") or 0), float(c.get("sl") or 0)
    mv = (ltp / e - 1) * 100 if e and ltp else 0
    if mv > CFG["late_pct"]:
        block.append(f"late — premium already {mv:+.0f}% above entry (don't chase)")
    if sl and ltp and ltp <= sl + (e - sl) * 0.25:
        block.append("premium is near the stop loss")
    if c.get("exch") != "MCX" and mdir and mdir != want:
        block.append(f"against market direction (NIFTY {mdir})")
    m = mods.get(c.get("source") or c.get("kind")) or {}
    if m.get("n", 0) >= 15 and m.get("exp", 0) < 0:
        block.append(f"this module loses money in your real results ({m['n']} trades · avg ₹{m['exp']:,}/trade)")
    vr = float(c.get("vol_ratio") or 0)
    fp_ok = guide.get("side") == c.get("side") and guide.get("k") in ("BUY", "RISK", "STRIKE")
    if vr < 1.2 and not fp_ok:
        block.append(f"no volume confirmation (volume {vr:.1f}x)")
    cr = crash or {}
    if cr.get("level") == "ALERT" and cr.get("side") and cr.get("side") != want:
        block.append(f"crash radar {cr.get('side')} alert against this side")
    if chart.get("verdict") == "TAKE":
        conf.append(f"chart 15-method TAKE ({chart.get('mscore')}/100)")
    elif chart.get("verdict") == "AVOID":
        risk.append("chart 15-method says AVOID")
    for b in bp.get("breaks") or []:
        conf.append(b)
    if fp_ok:
        conf.append("footprint: " + ("buyers stacking" if ce else "sellers stacking"))
    if m.get("proven"):
        conf.append(f"proven module ({m['win']}% win · PF {m['pf']} · {m['n']} trades)")
    if q.get("tier") == "PRIORITY":
        conf.append(f"Sniper PRIORITY ({q.get('score')}/100)")
    if lab.get("verdict") == "TAKE":
        conf.append("AI Lab history TAKE")
    elif lab.get("verdict") == "SKIP":
        risk.append("AI Lab history says SKIP")
    if vr >= 2:
        conf.append(f"volume {vr:.1f}x")
    for cd in candles or []:
        if cd.get("side") == want:
            conf.append(f"candle: {cd.get('name')}")
            break
    base = float(bp.get("score") or q.get("score") or 50)
    mod_sc = (m.get("lb") or 0) * 100 / 0.55 if m.get("n", 0) >= 10 else 50.0         # 95% lower bound 0.55 → 100
    p = ml_prob(c, M)
    sc = 0.45 * base + 0.35 * min(100, mod_sc) + 0.20 * (p * 100 if p is not None else base) + 3 * max(0, len(conf) - 2)
    sc = int(max(0, min(100, round(sc - 8 * len(risk)))))
    setup = [x for x in conf if not (x.startswith("proven module") or x.startswith("volume "))]   # proof from THIS chart, not just the module
    if block:
        dec = "SKIP"
    elif len(conf) >= CFG["min_conf"] and setup and sc >= CFG["pick"]:
        dec = "TAKE"
    elif sc >= CFG["pick"] - 10 and len(conf) >= 1:
        dec = "WATCH"
    else:
        dec = "SKIP"
    gold = dec == "TAKE" and len(conf) >= 4 and m.get("proven") and sc >= CFG["gold"]
    if dec != "TAKE" and not block and not setup and sc >= CFG["pick"] - 10:
        risk.append("no confirmation from the chart itself yet")
    if dec == "TAKE":
        say = f"{'GOLD — ' if gold else ''}TAKE: {len(conf)} confirmations — " + "; ".join(conf[:3])
    elif dec == "WATCH":
        say = f"WATCH: almost — needs {max(0, CFG['min_conf'] - len(conf)) or 1} more confirmation" + (f" ({'; '.join(risk)})" if risk else "")
    else:
        say = "SKIP: " + ("; ".join(block) if block else f"weak — score {sc}, {len(conf)} confirmation(s)")
    return {"id": c["id"], "decision": dec, "gold": bool(gold), "score": sc, "conf": conf, "block": block, "risk": risk, "say": say,
            "ml": round(p * 100) if p is not None else None, "module": {k: m.get(k) for k in ("n", "win", "exp", "pf", "proven")}}


SNAP_KEYS = ["chart", "broken", "footprint", "proven", "sniper", "lab", "volume", "candle"]
SNAP = {"t": 0, "m": {"on": False, "n": 0, "auc": None, "why": "collecting data"}}


def snapshot(v):
    """Full-analysis snapshot saved the FIRST time Brain sees a call (no hindsight) → training data for the learning model."""
    txt = " ".join(v.get("conf") or []).lower()
    return {"score": (v.get("score") or 0) / 100, "n_conf": len(v.get("conf") or []) / 6, "n_block": len(v.get("block") or []) / 3,
            "n_risk": len(v.get("risk") or []) / 3, "mod_win": ((v.get("module") or {}).get("win") or 45) / 100,
            **{f"has_{k}": float(k in txt) for k in SNAP_KEYS}}


def snap_train(calls, min_n=200):
    """Logistic regression on saved snapshots · walk-forward (oldest 70% train → newest 30% test) · ON only if it clearly beats chance."""
    import time as _t
    if _t.time() - SNAP["t"] < 900 and SNAP["m"].get("n"):
        return SNAP["m"]
    rows = sorted([c for c in calls if c.get("brain_f") and c.get("status") not in OPEN and c.get("status") != "VOID" and c.get("pnl_lot") is not None],
                  key=lambda c: f"{c.get('date')} {c.get('time')}")
    n = len(rows)
    if n < min_n:
        SNAP.update(t=_t.time(), m={"on": False, "n": n, "auc": None, "why": f"learning: {n}/{min_n} closed calls with full analysis saved"})
        return SNAP["m"]
    keys = list(rows[0]["brain_f"].keys())
    X = np.c_[np.ones(n), np.array([[c["brain_f"].get(k, 0) for k in keys] for c in rows], float)]
    y = np.array([(c.get("pnl_lot") or 0) > 0 for c in rows], float)
    cut = int(n * 0.7)
    w = np.zeros(X.shape[1])
    for _ in range(800):
        pr = 1 / (1 + np.exp(-X[:cut] @ w))
        w -= 0.5 * (X[:cut].T @ (pr - y[:cut]) / cut + 0.01 * np.r_[0, w[1:]])
    pt, yt = 1 / (1 + np.exp(-X[cut:] @ w)), y[cut:]
    pos, neg = pt[yt == 1], pt[yt == 0]
    auc = float(np.mean([(a > b) + 0.5 * (a == b) for a in pos for b in neg])) if len(pos) and len(neg) else 0.5
    top = yt[pt >= np.quantile(pt, 0.67)]
    lift = float((top.mean() - yt.mean()) * 100) if len(top) else 0.0
    on = auc >= 0.58 and lift >= 5
    SNAP.update(t=_t.time(), m={"on": bool(on), "n": n, "auc": round(auc, 3), "lift": round(lift, 1), "w": w.tolist(), "keys": keys,
                               "why": (f"ON — out-of-sample AUC {auc:.2f}, best third wins {lift:+.0f} pts more" if on else
                                       f"OFF — out-of-sample AUC {auc:.2f} (needs 0.58) · lift {lift:+.0f} pts (needs +5) — not trusted yet")})
    return SNAP["m"]


def snap_prob(f, M):
    if not M.get("on"):
        return None
    w = M["w"]
    return float(1 / (1 + np.exp(-(w[0] + sum(wi * f.get(k, 0) for wi, k in zip(w[1:], M["keys"]))))))


def answer(q, now, risk=None):
    """Free instant answers from Brain's live verdicts (no LLM): best now · any symbol · market."""
    q = str(q or "").strip().lower()
    rows = STATE.get("rows") or []
    hit = next((r for r in rows if str(r.get("symbol", "")).lower() in q), None)
    if hit:
        return (f"{hit['symbol']} {hit['strike']:g} {hit['side']} → {hit['decision']} (score {hit['score']}/100).\n{hit['say']}"
                + (f"\nBlockers: {'; '.join(hit['block'])}" if hit.get("block") else "")
                + (f"\nConfirmations: {'; '.join(hit['conf'])}" if hit.get("conf") else "")
                + (f"\nRisks: {'; '.join(hit['risk'])}" if hit.get("risk") else ""))
    if any(w in q for w in ("market", "trend", "nifty", "crash", "direction")):
        r = risk or {}
        d = r.get("dir")
        return (f"Market: NIFTY {d or 'no clear direction'} · breadth up {r.get('up', '–')}% / down {r.get('dn', '–')}%. "
                + ("Only CE setups today." if d == "UP" else "Only PE setups today." if d == "DOWN" else "Take fewer trades and smaller size."))
    take = [r for r in rows if r["decision"] == "TAKE"]
    if take:
        return "Take now (best first):\n" + "\n".join(f"{i + 1}. {r['symbol']} {r['strike']:g} {r['side']} — {r['say']}" for i, r in enumerate(take[:3]))
    watch = [r for r in rows if r["decision"] == "WATCH"]
    return ("Nothing to take right now — no call has enough confirmations with a clean entry. Waiting is a trade too."
            + (f"\nClosest: {watch[0]['symbol']} {watch[0]['strike']:g} {watch[0]['side']} — {watch[0]['say']}" if watch else ""))


def run(D, now, inp, send=None):
    """inp: bp_rows, sniper_rows, charts_table, lab, guides, mdir, crash, candles (symbol → list). Saves TAKE picks with time (max 3/day)."""
    day = str(now.date())
    calls = list((D.get("calls") or {}).values())
    mods = module_table(calls)
    try:
        from .dsk import model as _model
        M = _model(calls)
    except Exception:
        M = None
    STATE["model"] = {"on": bool(M and (M.get("wf") or {}).get("useful")), "auc": (M.get("wf") or {}).get("auc") if M else None,
                      "n": M.get("n") if M else 0, "why": (M.get("wf") or {}).get("why") if M else "no data"}
    SM = snap_train(calls)
    STATE["snap"] = {k: v for k, v in SM.items() if k not in ("w", "keys")}
    bp = {r["id"]: r for r in inp.get("bp_rows") or []}
    sq = {r["id"]: r for r in inp.get("sniper_rows") or []}
    ct = {r["id"]: r for r in inp.get("charts_table") or []}
    rows = []
    for c in calls:
        if c.get("date") != day or c.get("status") not in OPEN or c.get("shadow") or c.get("kind") == "PICK":
            continue
        v = verdict(c, bp.get(c["id"]), sq.get(c["id"]), ct.get(c["id"]), (inp.get("lab") or {}).get(c["id"]), (inp.get("guides") or {}).get(c["symbol"]),
                    mods, inp.get("mdir"), inp.get("crash"), M, (inp.get("candles") or {}).get(c["symbol"]))
        v.update(symbol=c["symbol"], strike=c.get("strike"), side=c.get("side"), time=c.get("time"), source=c.get("source_label") or c.get("source"),
                 entry=c.get("entry"), sl=c.get("sl"), targets=c.get("targets"), ltp=c.get("ltp"))
        if not c.get("brain_f"):
            c["brain_f"] = snapshot(v)                     # learning data — first look only
        lp = snap_prob(c["brain_f"], SM)
        v["learned"] = None if lp is None else round(lp * 100)
        if lp is not None and lp < 0.40 and v["decision"] == "TAKE":     # learning model may only VETO, never push a weak setup in
            v.update(decision="WATCH", gold=False, say=f"WATCH: learning model — similar setups won only {round(lp * 100)}% before")
        rows.append(v)
    order = {"TAKE": 0, "WATCH": 1, "SKIP": 2}
    rows.sort(key=lambda r: (order[r["decision"]], -r["score"]))
    J = D.setdefault("brain_picks", {})
    today = [p for p in J.values() if p["date"] == day]
    new = []
    for r in rows:
        if r["decision"] != "TAKE":
            continue
        if r["id"] in J:
            if r["gold"] and not J[r["id"]].get("gold"):
                J[r["id"]].update(gold=True, gold_time=now.strftime("%H:%M"))
                new.append(J[r["id"]])
            continue
        if len(today) >= CFG["max_day"]:
            continue
        c = D["calls"][r["id"]]
        p = {"id": r["id"], "date": day, "time": now.strftime("%H:%M"), "score": r["score"], "gold": r["gold"], "conf": r["conf"][:6], "say": r["say"],
             "symbol": c["symbol"], "strike": c.get("strike"), "side": c.get("side"), "entry": c.get("entry"), "sl": c.get("sl"), "targets": c.get("targets"),
             "lot": c.get("lot"), "source": c.get("source_label") or c.get("source")}
        J[r["id"]] = p
        today.append(p)
        new.append(p)
    if send:
        for p in new:
            try:
                send(f"{'🪙 BRAIN GOLD' if p['gold'] else '🧠 BRAIN PICK'} · {p['symbol']} {p['strike']:g} {p['side']}\n"
                     f"Buy ₹{p['entry']} · SL ₹{p['sl']} · T1/T2/T3 " + " / ".join(str(t) for t in p.get("targets") or []) + f"\nScore {p['score']} · " + "; ".join(p["conf"][:3])[:150],
                     f"brain|{p['id']}|{p['gold']}", True)
            except Exception:
                pass
    STATE.update(time=now.strftime("%I:%M %p"), rows=rows[:30])
    return new


def report(D, day):
    calls = (D or {}).get("calls") or {}
    J = (D or {}).get("brain_picks") or {}
    out = []
    for p in sorted(J.values(), key=lambda p: (p["date"], p["time"]), reverse=True)[:120]:
        c = calls.get(p["id"]) or {}
        out.append({**p, "status": c.get("status"), "ltp": c.get("ltp"), "exit": c.get("exit"), "pnl_lot": c.get("pnl_lot") or 0, "hits": c.get("hits") or []})
    done = [p for p in out if p["status"] and p["status"] not in OPEN]

    def st(L):
        return {"n": len(L), "win": round(sum(p["pnl_lot"] > 0 for p in L) / len(L) * 100) if L else None, "net": round(sum(p["pnl_lot"] for p in L))}
    return {"time": STATE["time"], "model": STATE["model"], "snap": STATE.get("snap") or SNAP["m"] and {k: v for k, v in SNAP["m"].items() if k not in ("w", "keys")}, "rows": STATE["rows"], "today": [p for p in out if p["date"] == day], "history": out,
            "stats": {"all": st(done), "gold": st([p for p in done if p.get("gold")])}, "cfg": CFG}
