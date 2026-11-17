"""🐋 BIG PLAYER ADVANCE CALLS — enter EARLY, right after big players do, before the move runs.

Every 5 minutes, a stock becomes an ADVANCE call when ALL of these line up:
  1. Fresh positions:   Long Built Up (CE) / Short Built Up (PE) — OI rising with price
  2. Big-player volume: at least one 5-min BUY (CE) / SELL (PE) spike ≥3× average in the last 60 minutes today
  3. Not chased yet:    price still within 1% of the big-player candle and the day move ≤3%
  4. Live market OK:    breadth / NIFTY / learned rules don't veto it (same check as every pick)
  5. Risk:              SL just beyond the big-player candle (low for CE / high for PE) → premium plan, ₹2,500/lot cap
The call shows WHEN big players bought (date · time · volume × · price), entry, SL, T1/T2/T3 — tracked like any call (paper).
Honest: big volume shows big money moved; it cannot prove who traded. Follow the SL.
"""
import pandas as pd

SRC = "🐋 Big Player Advance"
KIND = "ADVANCE"
CFG = {"min_mult": 3.0, "fresh_min": 60, "near_pct": 1.0, "max_move": 3.0}
STATE = {"time": None, "watch": [], "log": []}


def candidates(oi_rows, bv_get, live_q, now, market_ok=None):
    now = pd.Timestamp(now)
    day = str(now.date())
    out, watch = [], []
    for r in oi_rows or []:
        if r.get("kind") not in ("Long Built Up", "Short Built Up"):
            continue
        sym, side = r["symbol"], r["side"]
        bv = bv_get(sym) or {}
        want = "BUY" if side == "CE" else "SELL"
        fresh = [s for s in bv.get("spikes") or [] if s["time"][:10] == day and s["side"] == want and s["mult"] >= CFG["min_mult"]
                 and (now - pd.Timestamp(s["time"])).total_seconds() / 60 <= CFG["fresh_min"] + 5]
        q = (live_q or {}).get(sym) or {}
        px, pct = q.get("ltp"), q.get("pct")
        if not fresh or not px:
            continue
        sp = fresh[0]
        why = []
        dist = abs(px / sp["price"] - 1) * 100
        if dist > CFG["near_pct"]:
            why.append(f"price already {dist:.1f}% away from the big-player candle")
        if pct is not None and abs(pct) > CFG["max_move"]:
            why.append(f"day move {pct:+.1f}% — late")
        mk = market_ok({"symbol": sym, "side": side, "vol_ratio": q.get("vol_ratio"), "source": SRC, "kind": KIND}) if market_ok else None
        if mk:
            why.append(mk)
        sl = round(sp["low"] * 0.998, 2) if side == "CE" else round(sp["high"] * 1.002, 2)
        if (side == "CE" and sl >= px) or (side == "PE" and sl <= px):
            why.append("price is back through the big-player candle — signal failed")
        big = [s for s in bv.get("spikes") or [] if s["side"] == want][:4]
        row = {"symbol": sym, "side": side, "price": px, "sl": sl, "targets": [], "score": min(100, 60 + int(sp["mult"] * 3)),
               "stars": 4 if sp["mult"] >= 5 else 3, "vol_ratio": q.get("vol_ratio"),
               "reasons": [f"🐋 big {want} {sp['mult']}× at {sp['time'][5:]} @ ₹{sp['price']:g}", f"{r['kind']} (OI {r.get('oi_chg_pct')}%)"],
               "big": big, "pct": pct, "why_not": why}
        (watch if why else out).append(row)
    return out, watch


def run(ag, inst, now, oi_rows, bv_get, live_q, market_ok=None, send=None):
    from . import fullscan as FS, calls as CL
    rows, watch = candidates(oi_rows, bv_get, live_q, now, market_ok)
    STATE.update(time=pd.Timestamp(now).strftime("%d %b %I:%M %p"), watch=watch[:12])
    if not rows:
        return 0
    try:
        FS.pick_options(ag, inst, rows)
    except Exception as e:
        STATE["log"].insert(0, f"{pd.Timestamp(now):%H:%M} option pick failed: {str(e)[:60]}")
        return 0
    good = []
    for r in rows:
        o = r.get("option") or {}
        if "none" in o:
            continue
        FS.attach_plan(r, o, pd.Timestamp(now), SRC)
        if (o.get("plan") or {}).get("entry"):
            good.append(r)
    n = CL.add_simple(KIND, SRC, good, pd.Timestamp(now))
    if n:
        day = str(pd.Timestamp(now).date())
        by = {(r["symbol"], r["side"]): r for r in good}
        with CL.CALLS_LOCK:
            d = CL.STORE.load()
            for c in d["calls"].values():
                if c.get("date") == day and c.get("kind") == KIND and "big" not in c:
                    r = by.get((c["symbol"], c["side"]))
                    if r:
                        c["big"] = r["big"]
                        CL.STORE.dirty = True
                        if send and not c.get("shadow"):
                            b = r["big"][0]
                            try:
                                send(f"🐋 ADVANCE CALL · BUY {c['symbol']} {c.get('strike'):g} {c['side']} (exp {c.get('expiry')})\n"
                                     f"Big players {('bought' if c['side'] == 'CE' else 'sold')} {b['mult']}× at {b['time'][5:]} @ ₹{b['price']:g}\n"
                                     f"Entry ₹{c['entry']} · SL ₹{c['sl']} · T1/T2/T3 {' / '.join(str(t) for t in c['targets'])}", f"adv|{c['id']}", True)
                            except Exception:
                                pass
    return n


def report(calls, day):
    today = sorted([c for c in calls if c.get("date") == day and c.get("kind") == KIND], key=lambda c: c.get("time") or "", reverse=True)
    keep = ("id", "time", "date", "symbol", "strike", "side", "expiry", "entry", "sl", "targets", "ltp", "exit", "status", "pnl_lot", "hits", "lot",
            "big", "shadow", "shadow_why", "vol_ratio", "ul_price", "ul_sl")
    hist = [c for c in calls if c.get("kind") == KIND and c.get("status") not in ("OPEN", "T1 HIT", "T2 HIT") and c.get("pnl_lot") is not None]
    return {"time": STATE["time"], "calls": [{k: c.get(k) for k in keep} for c in today], "watch": STATE["watch"],
            "stats": {"n": len(hist), "win": round(sum(1 for c in hist if c["pnl_lot"] > 0) / len(hist) * 100) if hist else None,
                      "net": round(sum(c["pnl_lot"] for c in hist))}}
