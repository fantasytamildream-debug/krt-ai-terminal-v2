"""Swing (5 / 10 நாள் holding) picks — daily chart rules:
trend (EMA20 > EMA50, EMA20 ஏறுமுகம்), PDH/PWH/PMH break, relative strength, volume,
அடுத்த resistance வரை இடம், ATR அடிப்படையில் SL / T1–T5. Profit guarantee இல்லை."""
import pandas as pd
from .optmath import plan as prem_plan
from .config import load_settings

MULT = {5: [0.75, 1.25, 1.75, 2.25, 3.0], 10: [1, 2, 3, 4, 5]}
SLM = {5: 1.5, 10: 2.0}


def swing_picks(ag, inst, universe, C, idx, trend, now, session):
    from .fullscan import pick_options, stars
    nd = C.get("nifty_daily")
    nifty = next((x for x in idx if x.get("index") == "NIFTY"), {})
    n_ret = 0.0
    if nd is not None and not nd.empty and nifty.get("spot"):
        past = nd[nd.index < session]["close"]
        if len(past) > 21:
            n_ret = nifty["spot"] / float(past.iloc[-21]) - 1
    cands = []
    for u in universe:
        n, ltp = u["symbol"], u["ltp"]
        f, lv = (C.get("feat") or {}).get(n), C["levels"].get(n)
        if not f or not lv or not ltp or f["atr"] <= 0 or u["vol_ratio"] < 1.2:
            continue
        atr, rs = f["atr"], (ltp / f["c20"] - 1) - n_ret
        for side in ("CE", "PE"):
            if side == "CE":
                ok = ltp > f["ema20"] > f["ema50"] and f["ema20"] > f["ema20_5"]
                broke = [k for k in ("PMH", "PWH", "PDH") if lv.get(k) and ltp > lv[k]]
                above = sorted(x for x in (C["swings"].get(n) or []) + [f["hi52"]] if x > ltp * 1.002)
                nxt = above[0] if above else None
            else:
                ok = ltp < f["ema20"] < f["ema50"] and f["ema20"] < f["ema20_5"]
                broke = [k for k in ("PML", "PWL", "PDL") if lv.get(k) and ltp < lv[k]]
                below = sorted((x for x in (C["swings"].get(n) or []) + [f["lo52"]] if x < ltp * 0.998), reverse=True)
                nxt = below[0] if below else None
            if not ok or not broke:
                continue
            ref = lv[broke[0]] if broke[0][1] in "MW" else lv[broke[-1]]
            ref = max(lv[k] for k in broke) if side == "CE" else min(lv[k] for k in broke)
            ext = abs(ltp - ref) / atr
            if ext > 1.5:
                continue
            room = abs(nxt - ltp) / atr if nxt else 5.0
            srs = rs if side == "CE" else -rs
            sc = 25
            sc += max(0.0, min(srs * 100 / 5, 1)) * 20
            sc += min(u["vol_ratio"] / 2, 1) * 15
            sc += 20 if broke[0] in ("PMH", "PML") else 15 if broke[0] in ("PWH", "PWL") else 8
            sc += 10 if ext <= 0.5 else 5 if ext <= 1 else 0
            sc += min(room / 3, 1) * 10
            sc += 10 if (trend == "TRENDING UP" and side == "CE") or (trend == "TRENDING DOWN" and side == "PE") else 0
            sc = int(min(100, round(sc)))
            if sc < 65:
                continue
            hold = 10 if sc >= 80 and broke[0][1] in "MW" else 5
            sgn = 1 if side == "CE" else -1
            sl = round(ltp - sgn * SLM[hold] * atr, 2)
            tg = [round(ltp + sgn * m * atr, 2) for m in MULT[hold]]
            reasons = [f"{'+'.join(broke)} break", "EMA20>EMA50 trend" if side == "CE" else "EMA20<EMA50 trend",
                       f"RS vs NIFTY {srs*100:+.1f}%", f"Vol {u['vol_ratio']}×",
                       f"அடுத்த {'resistance' if side=='CE' else 'support'} {nxt:.1f}" if nxt else "52-week level வரை தடை இல்லை"]
            cands.append({"strong": sc >= 85, "symbol": n, "side": side, "price": ltp, "pct": u["pct"], "vol_ratio": u["vol_ratio"],
                          "levels": broke, "ref_level": round(ref, 2), "sl": sl, "targets": tg, "atr": round(atr, 2),
                          "hold": hold, "min_days": int(hold * 1.4) + 5, "score": sc, "stars": stars(sc),
                          "confidence": "HIGH" if sc >= 80 else "MEDIUM", "reasons": reasons, "status": "SWING"})
    cands.sort(key=lambda r: -r["score"])
    seen, out = set(), {"10": [], "5": []}
    for r in cands:
        if r["symbol"] in seen:
            continue
        key = str(r["hold"])
        if len(out[key]) < 3:
            out[key].append(r)
            seen.add(r["symbol"])
    picks = out["10"] + out["5"]
    pick_options(ag, inst, picks)
    cfg = load_settings().get("risk", {})
    for r in picks:
        o = r.get("option")
        if not o or "none" in o:
            continue
        try:
            o["plan"] = prem_plan(o.get("ask") or o.get("ltp"), r["price"], o["strike"], o["expiry"], o["type"],
                                  r["sl"], r["targets"], now.to_pydatetime(), o["lot"],
                                  cfg.get("charges_slippage", 150), cfg.get("max_risk_per_trade", 2500),
                                  hold_days=r["hold"] * 0.7, sl_days=2)
            from .calls import calibrate_plan
            calibrate_plan("Swing", o["plan"])
        except Exception:
            o["plan"] = None
    return out
