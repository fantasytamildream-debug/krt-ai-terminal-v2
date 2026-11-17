"""🧠 JARVIS BRAIN — the layer that knows the whole terminal and learns from its own results.

1. MARKET REGIME   live NIFTY % + breadth + deep-scan trend + crash radar → TRENDING UP / TRENDING DOWN / RANGE / VOLATILE
2. STRATEGY × REGIME  from every closed call: which module made money in which regime → "use today" / "avoid today"
                     (walk-forward safe: only closed calls, recomputed every 30 min, needs 8+ calls before it trusts a cell)
3. AUTO-LEARNING   factor lessons from closed calls (volume, time of day, side vs market, market type, stock CE/PE …):
                     a factor value that kept losing (15+ calls, ≤ −₹400/call) becomes a score penalty, one that kept winning a bonus.
                     Penalties / bonuses are capped (±10) and re-learned from new results every 30 min — mistakes correct themselves.
4. MISTAKE JOURNAL every SL today is diagnosed (against breadth/NIFTY, low volume, late/early entry, tight SL, weak module …)
                     → "what to do next time" + which mistake repeated most.
5. LEVEL MAP       per stock: PDH/PDL · PWH/PWL · PMH/PML · PQH/PQL · ORB high/low → Broken / Safe, MTF, priority signal,
                     BUY ABOVE / SELL BELOW / SL / R:R / qty for ₹2,500 risk (the panel from your TradingView indicator).
6. ASK             answers from all of the above + big players + radar + Dhasvanth + Best Mode, in plain English.
Honest: everything is computed from the terminal's real data and your past calls — it is a disciplined assistant, not a fortune teller.
"""
import math
import time

import pandas as pd

IDX = ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY")
OPEN = ("OPEN", "T1 HIT", "T2 HIT")
CFG = {"min_cell": 8, "min_factor": 15, "bad_exp": -400, "good_exp": 300, "cap": 10, "relearn": 1800, "risk": 2500}
STATE = {"t": 0, "regime": None, "matrix": {}, "lessons": [], "mistakes": {}, "levels": {}, "learned_at": None, "use": [], "avoid": []}


def _f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None


# ───────────── 1. regime ─────────────
def regime(nifty_pct=None, breadth=None, trend=None, crash=None):
    why = []
    np_ = _f(nifty_pct) or 0.0
    up, dn = breadth or (None, None)
    ad = (up / max(dn, 1)) if up is not None else None
    if nifty_pct is not None:
        why.append(f"NIFTY {np_:+.2f}%")
    if ad is not None:
        why.append(f"breadth {up} up / {dn} down (A/D {ad:.2f})")
    if trend:
        why.append(f"scan trend {trend}")
    cr = crash or {}
    if cr.get("level") == "ALERT":
        why.append(f"crash radar ALERT {cr.get('side')}")
        return {"label": "VOLATILE", "dir": cr.get("side"), "why": why}
    if np_ >= 0.4 and (ad is None or ad >= 1.1):
        lab = "TRENDING UP"
    elif np_ <= -0.4 and (ad is None or ad <= 0.9):
        lab = "TRENDING DOWN"
    elif ad is not None and ((np_ > 0.2 and ad < 0.8) or (np_ < -0.2 and ad > 1.25)):
        lab = "VOLATILE"
        why.append("index and stocks disagree (heavyweights moving the index)")
    elif trend and "TRENDING" in str(trend) and abs(np_) >= 0.25:
        lab = str(trend).upper()
    else:
        lab = "RANGE"
    d = "UP" if "UP" in lab else "DOWN" if "DOWN" in lab else None
    return {"label": lab, "dir": d, "why": why}


ADVICE = {"TRENDING UP": "Trend day up — CE on pullbacks to VWAP / broken levels; avoid fading the move with PE.",
          "TRENDING DOWN": "Trend day down — PE on pullbacks; stock CE only for clear relative-strength names.",
          "RANGE": "Range day — breakouts fail often: take only A-grade setups at range edges, book quickly at T1.",
          "VOLATILE": "Index and stocks disagree / crash risk — trade small, index options over stock options, wait for confirmation."}


# ───────────── 2 + 3. learning ─────────────
def _mk(c):
    return "MCX" if c.get("exch") == "MCX" else "INDEX" if c.get("symbol") in IDX else "STOCK"


def _factors(c):
    """Feature values of one call (only what was known at signal time)."""
    out = {"market": _mk(c), "market+side": f"{_mk(c)} {c.get('side')}"}
    vr = _f(c.get("vol_ratio"))
    if vr is not None:
        out["volume"] = "<1.5×" if vr < 1.5 else "1.5–2.5×" if vr < 2.5 else "≥2.5×"
    t = str(c.get("time") or "")[:5]
    if t:
        out["time"] = ("before 9:45" if t < "09:45" else "9:45–11:00" if t < "11:00" else "11:00–13:30" if t < "13:30"
                       else "13:30–14:30" if t < "14:30" else "after 14:30")
    f = c.get("feat") if isinstance(c.get("feat"), dict) else {}
    np_ = _f(f.get("nifty_pct"))
    if np_ is not None and _mk(c) != "MCX":
        out["vs NIFTY"] = "with NIFTY" if (np_ >= 0) == (c.get("side") == "CE") else "against NIFTY"
    e, sl = _f(c.get("entry")), _f(c.get("sl0") or c.get("sl"))
    if e and sl and e > sl:
        p = (e - sl) / e * 100
        out["SL size"] = "SL <12%" if p < 12 else "SL 12–20%" if p < 20 else "SL ≥20%"
    if c.get("regime"):
        out["regime"] = c["regime"]
    return out


def learn(calls):
    closed = [c for c in calls if c.get("kind") != "PICK" and not c.get("shadow") and c.get("status") not in OPEN and c.get("status") != "VOID"
              and c.get("pnl_lot") is not None]
    M, F = {}, {}
    for c in closed:
        p = c["pnl_lot"] or 0
        cell = M.setdefault((c.get("source") or c.get("kind"), c.get("regime") or "UNKNOWN"), [0, 0, 0.0])
        cell[0] += 1
        cell[1] += p > 0
        cell[2] += p
        for k, v in _factors(c).items():
            x = F.setdefault((k, v), [0, 0, 0.0])
            x[0] += 1
            x[1] += p > 0
            x[2] += p
    matrix = {}
    for (src, rg), (n, w, net) in M.items():
        matrix.setdefault(src, {})[rg] = {"n": n, "win": round(w / n * 100), "exp": round(net / n), "net": round(net)}
    lessons = []
    for (k, v), (n, w, net) in F.items():
        if n < CFG["min_factor"]:
            continue
        exp = net / n
        if exp <= CFG["bad_exp"] or exp >= CFG["good_exp"]:
            pts = max(-CFG["cap"], min(CFG["cap"], round(exp / 150)))
            lessons.append({"factor": k, "value": v, "n": n, "win": round(w / n * 100), "exp": round(exp), "pts": pts,
                            "text": (f"❌ {k} = {v}: lost ₹{-exp:,.0f}/call over {n} calls ({round(w / n * 100)}% win) → {pts} pts" if exp < 0 else
                                     f"✅ {k} = {v}: made ₹{exp:,.0f}/call over {n} calls ({round(w / n * 100)}% win) → +{pts} pts")})
    lessons.sort(key=lambda x: x["exp"])
    return matrix, lessons


def for_regime(matrix, label):
    use, avoid = [], []
    for src, cells in matrix.items():
        c = cells.get(label)
        if not c or c["n"] < CFG["min_cell"]:
            continue
        (use if c["exp"] > 0 and c["win"] >= 45 else avoid if c["exp"] < 0 else []).append({"module": src, **c})
    use.sort(key=lambda r: -r["exp"])
    avoid.sort(key=lambda r: r["exp"])
    return use[:8], avoid[:8]


def adjust(c, lessons=None, matrix=None, label=None):
    """Score adjustment for a live call from the learned lessons + strategy-in-this-regime record. → (delta, notes)."""
    lessons = STATE["lessons"] if lessons is None else lessons
    matrix = STATE["matrix"] if matrix is None else matrix
    label = label or ((STATE.get("regime") or {}).get("label"))
    fx = _factors(c)
    fx["regime"] = label or fx.get("regime")
    d, notes = 0, []
    for L in lessons:
        if fx.get(L["factor"]) == L["value"] and L["factor"] != "regime":
            d += L["pts"]
            notes.append(f"{'+' if L['pts'] > 0 else ''}{L['pts']} {L['factor']} {L['value']} (₹{L['exp']:,}/call history)")
    cell = (matrix.get(c.get("source") or c.get("kind")) or {}).get(label or "")
    if cell and cell["n"] >= CFG["min_cell"]:
        p = 6 if cell["exp"] > 0 and cell["win"] >= 50 else -8 if cell["exp"] < 0 else 0
        if p:
            d += p
            notes.append(f"{'+' if p > 0 else ''}{p} module in a {label} market: {cell['win']}% win, ₹{cell['exp']:,}/call ({cell['n']} calls)")
    d = max(-20, min(15, d))
    return d, notes


# ───────────── 4. mistake journal ─────────────
def diagnose(c, breadth=None, nifty_pct=None, weak=()):
    why = []
    vr = _f(c.get("vol_ratio"))
    if vr is not None and vr < 1.5:
        why.append(("low volume", f"volume only {vr}× — wait for ≥1.5×"))
    t = str(c.get("time") or "")[:5]
    if t and t < "09:45":
        why.append(("too early", "entered in the opening noise (before 9:45) — wait for the first 30 min range"))
    if t and t >= "14:00" and c.get("exch") != "MCX":
        why.append(("too late", "entered after 2 PM — little time left to reach targets"))
    f = c.get("feat") if isinstance(c.get("feat"), dict) else {}
    np_ = _f(f.get("nifty_pct"))
    if np_ is not None and _mk(c) == "STOCK" and ((np_ < -0.2 and c.get("side") == "CE") or (np_ > 0.2 and c.get("side") == "PE")):
        why.append(("against NIFTY", f"NIFTY was {np_:+.2f}% at the signal — trade with the index"))
    for w in c.get("risk_warn") or []:
        wl = str(w).lower()
        if "breadth" in wl or "against market" in wl:
            why.append(("against the market", str(w)))
            break
    e, sl = _f(c.get("entry")), _f(c.get("sl0") or c.get("sl"))
    if e and sl and e > sl and (e - sl) / e < 0.12:
        why.append(("SL too tight", f"SL only {round((e - sl) / e * 100)}% of premium — normal noise hits it"))
    if _mk(c) == "STOCK" and c.get("side") == "PE":
        why.append(("stock PE", "stock PE lost money in your history unless the market is clearly falling"))
    if (c.get("source") or c.get("kind")) in weak:
        why.append(("weak module", f"{c.get('source')} has a losing record"))
    if (_f(c.get("mfe_pct")) or 0) < 2:
        why.append(("no follow-through", "price never moved in favour — the breakout / signal was false from the start"))
    if not why:
        why.append(("normal loss", "setup was valid — a normal loss; the plan (SL) did its job"))
    return why


def mistakes(calls, day, weak=()):
    L = [c for c in calls if c.get("date") == day and c.get("status") == "SL HIT" and c.get("kind") != "PICK" and not c.get("shadow")]
    rows, cnt = [], {}
    for c in sorted(L, key=lambda c: str(c.get("exit_time") or ""), reverse=True):
        d = diagnose(c, weak=weak)
        for k, _ in d:
            cnt[k] = cnt.get(k, 0) + 1
        rows.append({"time": c.get("time"), "symbol": c["symbol"], "strike": c.get("strike"), "side": c.get("side"), "source": c.get("source"),
                     "pnl": c.get("pnl_lot"), "why": [t for _, t in d], "tags": [k for k, _ in d]})
    top = sorted(cnt.items(), key=lambda kv: -kv[1])
    fix = {"low volume": "skip calls under 1.5× volume", "against NIFTY": "only trade with the index direction",
           "against the market": "check breadth before stock CE", "too late": "no new stock entries after 2 PM",
           "too early": "wait until 9:45", "SL too tight": "use structure SL ≥12% of premium", "stock PE": "stock PE only on clear down days",
           "weak module": "ignore modules with a losing record", "no follow-through": "enter on retest / confirmation, not the first breakout candle"}
    return {"n": len(L), "loss": round(sum(c.get("pnl_lot") or 0 for c in L)), "rows": rows[:20], "top": top[:5],
            "next_time": [f"{k} ×{v} → {fix.get(k, 'keep following the plan')}" for k, v in top[:4] if k != "normal loss"]}


# ───────────── 5. level map ─────────────
def quarter_levels(bars):
    try:
        t = pd.to_datetime(bars["t"])
        df = pd.DataFrame({"h": bars["h"], "l": bars["l"]}, index=t)
        q = df.index.to_period("Q")
        cur = pd.Timestamp.now().to_period("Q")
        done = df[q < cur]
        if done.empty:
            return {}
        last = done.index.to_period("Q")[-1]
        blk = done[done.index.to_period("Q") == last]
        return {"PQH": float(blk["h"].max()), "PQL": float(blk["l"].min())}
    except Exception:
        return {}


def level_map(sym, px, levels, orb=None, bars=None, mtf=None):
    if not px or not levels:
        return None
    lv = dict(levels)
    lv.update(quarter_levels(bars) if bars else {})
    if orb and orb[0]:
        lv["ORB H"], lv["ORB L"] = orb[0], orb[1]
    rows = []
    for k in ("PDH", "PDL", "PWH", "PWL", "PMH", "PML", "PQH", "PQL", "ORB H", "ORB L"):
        v = _f(lv.get(k))
        if not v:
            continue
        hi = k.endswith("H")
        if hi:
            st = "Broken / Above ✅" if px > v else f"Resistance ({(v / px - 1) * 100:.1f}% away)"
        else:
            st = "Broken / Below 🔻" if px < v else "Safe ✅"
        rows.append({"level": k, "price": round(v, 2), "status": st, "broken": (px > v) if hi else (px < v), "hi": hi})
    above = [r["level"] for r in rows if r["hi"] and r["broken"] and not r["level"].startswith("ORB")]
    below = [r["level"] for r in rows if not r["hi"] and r["broken"] and not r["level"].startswith("ORB")]
    prio = (f"Above {'+'.join(above)}" if above and not below else f"Below {'+'.join(below)}" if below and not above else
            "Inside levels (no clean break)" if not above and not below else "Mixed")
    sup = sorted([r["price"] for r in rows if r["price"] < px], reverse=True)
    res = sorted([r["price"] for r in rows if r["price"] > px])
    buy_above = sup[0] if sup else None
    sell_below = sup[1] if len(sup) > 1 else (sup[0] * 0.995 if sup else None)
    tgt = res[0] if res else (px + (px - sell_below) * 2 if sell_below else None)
    rr = round((tgt - px) / (px - sell_below), 2) if tgt and sell_below and px > sell_below else None
    qty = int(CFG["risk"] // (px - sell_below)) if sell_below and px > sell_below else None
    tf = (mtf or {}).get("tf") or {}
    mtf_txt = " · ".join(f"{k} {'▲' if v == 'UP' else '▼' if v == 'DOWN' else '–'}" for k, v in tf.items()) if tf else None
    score = min(100, 40 + 10 * len(above) - 10 * len(below) + 5 * sum(1 for v in tf.values() if v == "UP") - 5 * sum(1 for v in tf.values() if v == "DOWN"))
    return {"symbol": sym, "px": px, "rows": rows, "priority": prio, "buy_above": buy_above, "sell_below": round(sell_below, 2) if sell_below else None,
            "target": round(tgt, 2) if tgt else None, "rr": rr, "qty": qty, "mtf": mtf_txt, "score": max(0, score),
            "bias": "CE" if above and not below else "PE" if below and not above else None}


# ───────────── run + report + ask ─────────────
def run(calls, now, ctx):
    """Called every minute (no lock needed: read-only on calls). Re-learns every 30 min."""
    rg = regime(ctx.get("nifty_pct"), ctx.get("breadth"), ctx.get("trend"), ctx.get("crash"))
    STATE["regime"] = rg
    if time.time() - STATE["t"] > CFG["relearn"] or not STATE["matrix"]:
        STATE["matrix"], STATE["lessons"] = learn(calls)
        STATE.update(t=time.time(), learned_at=now.strftime("%d %b %I:%M %p"), n_learned=sum(1 for c in calls if c.get("status") not in OPEN))
    lab = rg["label"]
    if not any(lab in cells for cells in STATE["matrix"].values()):
        lab = "RANGE"                             # no history for this regime yet (e.g. VOLATILE) → closest: RANGE
    STATE["regime_used"] = lab
    STATE["use"], STATE["avoid"] = for_regime(STATE["matrix"], lab)
    weak = {r["module"] for r in STATE["avoid"]}
    STATE["mistakes"] = mistakes(calls, str(now.date()), weak)
    lv = {}
    for sym in ctx.get("level_syms") or []:
        L = (ctx.get("levels") or {}).get(sym)
        px = _f(((ctx.get("live_q") or {}).get(sym) or {}).get("ltp"))
        m = level_map(sym, px, L, (ctx.get("orb") or {}).get(sym), (ctx.get("bars") or {}).get(sym), ((ctx.get("charts") or {}).get(sym) or {}).get("mtf"))
        if m:
            lv[sym] = m
    STATE["levels"] = lv
    STATE["ctx"] = {k: ctx.get(k) for k in ("bigvol", "radar", "dhas_top", "best", "rising")}
    return STATE


def report():
    rg = STATE.get("regime") or {}
    return {"regime": rg, "advice": ADVICE.get(rg.get("label"), ""), "use": STATE["use"], "avoid": STATE["avoid"],
            "lessons": (lambda L: L[:8] + [x for x in L[8:] if x["exp"] > 0][-4:])(STATE["lessons"]), "learned_at": STATE.get("learned_at"),
            "regime_used": STATE.get("regime_used"),
            "n_learned": STATE.get("n_learned"), "mistakes": STATE["mistakes"], "levels": list(STATE["levels"].values())[:8]}


def answer(q, jv_answer=None):
    import re as _re
    ql = " " + _re.sub(r"[^a-z0-9& ]", " ", str(q or "").lower()) + " "
    rg = STATE.get("regime") or {}
    cx = STATE.get("ctx") or {}
    lv = STATE.get("levels") or {}
    sym = next((s for s in list(lv) + [r.get("symbol") for r in (cx.get("bigvol") or {}).get("rows") or []] if s and f" {s.lower()} " in ql), None)
    if any(w in ql for w in (" market", " regime", " mood", " today ")) and not sym:
        u = ", ".join(f"{r['module']} ({r['win']}% · ₹{r['exp']:,}/call)" for r in STATE["use"][:3]) or "no module has 8+ calls in this regime yet"
        a = ", ".join(r["module"] for r in STATE["avoid"][:3]) or "none"
        bv = (cx.get("bigvol") or {}).get("summary") or {}
        return (f"Market now: {rg.get('label', '–')} ({'; '.join(rg.get('why') or [])}).\n{ADVICE.get(rg.get('label'), '')}\n"
                f"Best strategies in this market (your history): {u}. Avoid: {a}.\n"
                + (f"Big players today: {bv.get('buy', 0)} big BUY vs {bv.get('sell', 0)} big SELL spikes." if bv else ""))
    if any(w in ql for w in (" strategy", " which module", " use ")):
        return ("In a " + str(rg.get("label")) + " market your results say — USE: " +
                ("; ".join(f"{r['module']} {r['win']}% win ₹{r['exp']:,}/call ({r['n']})" for r in STATE["use"]) or "not enough data yet") +
                ". AVOID: " + ("; ".join(f"{r['module']} ₹{r['exp']:,}/call ({r['n']})" for r in STATE["avoid"]) or "none") + ".")
    if any(w in ql for w in (" mistake", " lesson", " learn", " wrong", " loss")):
        m = STATE.get("mistakes") or {}
        return (f"Today: {m.get('n', 0)} SL hits (₹{m.get('loss', 0):,}). Most common reasons: " +
                (", ".join(f"{k} ×{v}" for k, v in m.get("top") or []) or "none") + ".\nNext time: " + ("; ".join(m.get("next_time") or []) or "keep following the plan") +
                ".\nLearned rules now active: " + ("; ".join(L["text"] for L in STATE["lessons"][:4]) or "none yet"))
    if any(w in ql for w in (" big player", " whale", " big buy", " big sell", " accumulat")):
        rows = ((cx.get("bigvol") or {}).get("rows") or [])[:6]
        rad = (cx.get("radar") or [])[:3]
        return ("Latest big-player spikes: " + ("; ".join(f"{r['symbol']} {r['side']} {r['mult']}× at {r['time'][5:]}"
                                                          + (f" → watch {r['opt']['strike']:g} {r['opt']['side']}" if r.get("opt") else "") for r in rows) or "none yet") +
                ".\nAccumulation radar: " + ("; ".join(f"{r['symbol']} {r['side']} score {r['score']} ({r['stage']})" for r in rad) or "nothing strong yet") + ".")
    if sym and sym in lv:
        m = lv[sym]
        brk = ", ".join(f"{r['level']} {r['price']:g} {r['status']}" for r in m["rows"])
        return (f"{sym} @ ₹{m['px']:g} — {m['priority']} · bias {m['bias'] or 'none'} · MTF {m['mtf'] or 'n/a'}.\nLevels: {brk}.\n"
                f"BUY ABOVE ₹{m['buy_above']} · SELL BELOW ₹{m['sell_below']} · target ₹{m['target']} · R:R {m['rr']} · qty for ₹2,500 risk: {m['qty']}.")
    if any(w in ql for w in (" best", " take now", " what should")):
        top = (cx.get("dhas_top") or [])[:3]
        best = (cx.get("best") or [])[:3]
        return ("Best right now — Dhasvanth: " + ("; ".join(f"{r['symbol']} {r.get('strike') or ''} {r['side']} ({r['ev']['grade']})" for r in top) or "no PRO/TAKE call open") +
                ". AI best picks: " + ("; ".join(f"{p['symbol']} {p.get('strike') or ''} {p['side']} score {p.get('score')}" for p in best) or "none") +
                f". Market: {rg.get('label', '–')} — {ADVICE.get(rg.get('label'), '')}")
    return jv_answer(q) if jv_answer else "Ask me: market? · which strategy? · mistakes? · big players? · <STOCK> levels · best now?"
