"""🐋 v126 BIG-PLAYER ACTION — for every big BUY / SELL spike: which strike, its live premium, and a plain answer: TAKE / WAIT / LATE / AVOID.

Rules (from the spike candle itself + the live price — no guessing):
  BUY spike  → CE · confirmed when price trades ABOVE the spike candle's high · SL = below the spike candle's low
  SELL spike → PE · confirmed when price trades BELOW the spike candle's low  · SL = above the spike candle's high
  TAKE   confirmed, not more than 1 candle-range past the trigger, spike ≤ 45 min old, market not against (stocks)
  WAIT   not confirmed yet → "enter on a 5-min close above X"
  LATE   ran > 1 range past the trigger, or spike older than 45 min → don't chase
  AVOID  price broke the OTHER side of the spike candle (the big players lost) · ABSORB spikes are WAIT (no side yet)
Option plan = live premium ± delta 0.5 × the underlying distance (a MODEL estimate, labelled). Targets T1-T3 = 1R / 2R / 3R on the underlying.
"""
import pandas as pd


def advise(r, now_px, opt_ltp=None, mkt=None, now=None):
    side = r.get("side")
    hi, lo, px0 = r.get("high"), r.get("low"), r.get("price")
    o = r.get("opt") or {}
    if side not in ("BUY", "SELL") or not (hi and lo and hi > lo):
        return {"tag": "WAIT", "txt": "Big volume but no side yet (absorption) — wait for a break of the candle's high or low."}
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)
    try:
        age = (now - pd.Timestamp(f"{r['date']} {r.get('end') or r['time'][11:16]}")).total_seconds() / 60
    except Exception:
        age = None
    rng = hi - lo
    bull = side == "BUY"
    opt = "CE" if bull else "PE"
    px = now_px or px0
    trig = hi if bull else lo
    sl_ul = lo if bull else hi
    strike = f"{o['strike']:g} {opt}" if o.get("strike") else f"ATM {opt}"
    name = f"{r['symbol']} {strike}"
    plan = None
    if opt_ltp:
        d = 0.5
        e = float(opt_ltp)
        risk_ul = abs(px - sl_ul)
        sl_p = round(max(e - d * risk_ul, e * 0.5), 2)
        T = [round(e + d * k * max(risk_ul, rng), 2) for k in (1, 2, 3)]
        lot = o.get("lot") or 0
        plan = {"entry": round(e, 2), "sl": sl_p, "targets": T, "risk": round((e - sl_p) * float(lot)) if lot else None,
                "model": "premium ≈ LTP ± Δ0.5 × underlying move (estimate)"}
    mkt_against = (r.get("exch") != "MCX") and ((mkt == "BEAR" and bull) or (mkt == "BULL" and not bull))
    if (bull and px < lo) or (not bull and px > hi):
        return {"tag": "AVOID", "txt": f"Failed — price broke the other side of the spike candle ({'below' if bull else 'above'} {sl_ul:g}). Big players lost this one.", "plan": None}
    confirmed = px > trig if bull else px < trig
    ext = (px - trig) / rng if bull else (trig - px) / rng
    if age is not None and age > 45:
        return {"tag": "LATE", "txt": f"Spike was {int(age)} min ago — old news. Don't chase {name}.", "plan": plan}
    if confirmed and ext > 1.0:
        return {"tag": "LATE", "txt": f"Already ran {ext:.1f}× the candle range past {trig:g} — don't chase. Wait for a pullback near {trig:g}.", "plan": plan}
    if not confirmed:
        return {"tag": "WAIT", "txt": f"Not confirmed yet — BUY {name} only on a 5-min close {'above' if bull else 'below'} {trig:g}. SL {'below' if bull else 'above'} {sl_ul:g}.",
                "plan": plan}
    risk_txt = f" · 1-lot risk ≈ ₹{plan['risk']:,}" if plan and plan.get("risk") else ""
    if plan and plan.get("risk") and plan["risk"] > 2500:
        return {"tag": "AVOID", "txt": f"Confirmed, but 1 lot risks ₹{plan['risk']:,} (> ₹2,500). Skip or wait for a smaller SL.", "plan": plan}
    return {"tag": "TAKE", "txt": f"Confirmed — BUY {name}" + (f" near ₹{plan['entry']}" if plan else "") + f". SL: stock {'below' if bull else 'above'} {sl_ul:g}"
                                 + (f" (premium ≈ ₹{plan['sl']})" if plan else "") + risk_txt
                                 + (" · market is against it → 1 lot only" if mkt_against else ""), "plan": plan}
