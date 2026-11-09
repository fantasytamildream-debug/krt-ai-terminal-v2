"""🧪 AI LAB — history data வச்சு முடிவு (rule + statistics; LLM இல்லை, guarantee இல்லை):

  🎯 Best Strike Selector + Greeks Intelligence — ATM / ITM / OTM ஒப்பீடு: liquidity (spread, OI), delta, theta, IV, risk-reward
  📍 Level Lab — "VBL 430 break ஆனா profit வருமா?" → அந்த level-ல் கடந்த நாட்களில் என்ன நடந்தது (break held / failed / rejected),
     strong-up நாட்களுக்கு பிறகு என்ன ஆச்சு → CE plan (மேல் close + volume) / PE plan (rejection) + strike
  🔭 Pre-Breakout Radar — volume compression + price consolidation + 20-நாள் level அருகில் + OI → watchlist → break + volume = call
  ⚔ Strategy Battle Lab — strategy குடும்பம் × market condition, chronological out-of-sample (முதல் 70% / கடைசி 30%)
  🎓 Learning Engine — முடிந்த calls-ல் எந்த condition வேலை செய்யுது / எது நஷ்டம்
  🧠 Regime Brain — இப்போதைய regime → அதில் வேலை செய்த strategies
  🏦 OI Flow — futures price + OI + OI change → buildup / unwinding
"""
import datetime as dt
import math

import numpy as np
import pandas as pd

from .optmath import bs, greeks_from_price, iv as _iv, years_to_expiry

OPEN = ("OPEN", "T1 HIT", "T2 HIT", "T3 HIT", "T4 HIT")
STATE = {"prebreak": {"time": None, "rows": [], "log": []}}


# ───────────────────────── 🎯 BEST STRIKE + GREEKS ─────────────────────────
def _depth(q):
    d = q.get("depth") or {}
    b = ((d.get("buy") or [{}])[0] or {}).get("price")
    a = ((d.get("sell") or [{}])[0] or {}).get("price")
    return float(b or 0) or None, float(a or 0) or None


def score_strike(c):
    """ஒரு strike-க்கு 100 மதிப்பெண் — liquidity 30 · delta 25 · theta 15 · RR 25 · risk ≤₹2,500 5."""
    sc, why = 0, []
    sp = c.get("spread_pct")
    s1 = 30 if sp is not None and sp <= 1 else 20 if sp is not None and sp <= 2 else 10 if sp is not None and sp <= 4 else 0
    sc += s1
    why.append(f"spread {sp}%" if sp is not None else "depth இல்லை")
    d = c.get("delta") or 0
    s2 = 25 if 0.45 <= d <= 0.65 else 15 if 0.35 <= d <= 0.75 else 5
    sc += s2
    th = c.get("theta_pct")
    s3 = 15 if th is not None and th <= 3 else 10 if th is not None and th <= 6 else 5 if th is not None and th <= 10 else 0
    sc += s3
    rr = c.get("rr")
    s4 = 25 if rr and rr >= 2 else 18 if rr and rr >= 1.5 else 10 if rr and rr >= 1 else 0
    sc += s4
    s5 = 5 if c.get("risk_lot") is not None and c["risk_lot"] <= 2500 else 0
    sc += s5
    if (c.get("oi") or 0) > 0:
        sc += min(5, int(math.log10(max(c["oi"], 1))))       # OI bonus (max 5)
    return min(100, sc), why


def best_strike(ag, inst, name, side, spot, now, ul_sl, ul_tgt, min_days=2, hold_days=0, each=2):
    """ATM ± `each` strikes (ITM / OTM) quote + Greeks + target/SL-ல் premium reprice → score → best."""
    from .instruments import contracts
    exp, rows = contracts(inst, name, min_days)
    rows = sorted([r for r in rows or [] if r[4] == side], key=lambda r: float(r[3]))
    if not rows or not spot:
        return {"err": "contracts இல்லை", "rows": []}
    i0 = min(range(len(rows)), key=lambda i: abs(float(rows[i][3]) - spot))
    pick = rows[max(0, i0 - each): i0 + each + 1]
    by = {}
    for r in pick:
        by.setdefault(r[6] if len(r) > 6 else "NFO", []).append(r[0])
    qs = {}
    for ex, toks in by.items():
        try:
            qs.update(ag.quotes({ex: toks}) or {})
        except Exception:
            pass
    now_d = now.to_pydatetime() if hasattr(now, "to_pydatetime") else now
    T = years_to_expiry(exp, now_d)
    T2 = max(T - (2 / 24 + hold_days) / 365, 1 / (365 * 24))
    out = []
    for r in pick:
        q = qs.get(r[0]) or {}
        ltp = float(q.get("ltp") or 0)
        if ltp <= 0:
            continue
        K, lot = float(r[3]), int(r[5])
        bid, ask = _depth(q)
        sp = round((ask - bid) / ((ask + bid) / 2) * 100, 2) if bid and ask and ask >= bid else None
        g = greeks_from_price(ltp, spot, K, exp, side, now_d)
        sig = _iv(ltp, spot, K, T, side)
        p_t, p_sl = bs(ul_tgt, K, T2, sig, side), bs(ul_sl, K, T2, sig, side)
        rr = round((p_t - ltp) / (ltp - p_sl), 2) if ltp > p_sl else None
        dS = spot * 0.01                                       # gamma ≈ 1% move-ல் delta மாற்றம்
        from .optmath import delta as _dl
        gam = abs(_dl(spot + dS, K, T, sig, side)) - abs(_dl(spot - dS, K, T, sig, side))
        mny = "ATM" if r is rows[i0] else ("ITM" if (K < spot) == (side == "CE") else "OTM")
        c = {"strike": K, "token": r[0], "contract": r[1], "expiry": exp, "lot": lot, "exch": r[6] if len(r) > 6 else "NFO", "type": side,
             "ltp": ltp, "bid": bid, "ask": ask, "spread_pct": sp, "oi": int(float(q.get("opnInterest") or 0)), "volume": int(float(q.get("tradeVolume") or 0)),
             "iv": g["iv"], "delta": g["delta"], "theta_pct": g["theta_pct"], "gamma_1pct": round(gam, 3), "moneyness": mny,
             "prem_target": round(p_t, 2), "prem_sl": round(p_sl, 2), "rr": rr, "risk_lot": round((ltp - p_sl) * lot) if ltp > p_sl else None}
        c["score"], c["why"] = score_strike(c)
        out.append(c)
    out.sort(key=lambda c: -c["score"])
    best = out[0] if out else None
    expl = None
    if best:
        expl = (f"{best['moneyness']} {best['strike']:g} {side} — delta {best['delta']} (₹1 stock move = ₹{best['delta']:.2f} premium), "
                f"theta {best['theta_pct']}%/நாள், IV {best['iv']}%, spread {best['spread_pct']}%, RR {best['rr']} "
                f"(target-ல் ₹{best['prem_target']} · SL-ல் ₹{best['prem_sl']}) · 1 lot risk ₹{best['risk_lot']}")
    return {"expiry": exp, "rows": out, "best": best, "explain": expl}


# ───────────────────────── 📍 LEVEL LAB ─────────────────────────
def _atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def level_history(d1, m5, level, tol=0.003):
    """அந்த level-க்கு கடந்த காலத்தில் வந்த ஒவ்வொரு தடவையும் என்ன ஆச்சு."""
    out = {"daily": {"n": 0, "break": 0, "held": 0, "reject": 0, "after_break3": [], "after_reject3": []},
           "m5": {"n": 0, "held": 0, "failed": 0, "reject": 0, "stall": 0, "events": []}}
    if d1 is not None and len(d1) > 5:
        c, h = d1["close"].values, d1["high"].values
        for i in range(1, len(d1) - 1):
            if c[i - 1] < level and h[i] >= level * (1 - tol):
                D = out["daily"]
                D["n"] += 1
                r3 = (c[min(i + 3, len(c) - 1)] / c[i] - 1) * 100
                if c[i] >= level * 1.002:
                    D["break"] += 1
                    D["after_break3"].append(round(r3, 2))
                    if c[i + 1] >= level:
                        D["held"] += 1
                elif h[i] >= level:
                    D["reject"] += 1
                    D["after_reject3"].append(round(r3, 2))
    if m5 is not None and len(m5) > 30:
        a = float(_atr(m5).dropna().median() or 0) or float((m5["high"] - m5["low"]).median())
        c, h, l = m5["close"].values, m5["high"].values, m5["low"].values
        last = -99
        for i in range(3, len(m5) - 13):
            if i - last < 12 or not (h[i] >= level * (1 - tol / 3) and max(c[i - 3:i]) < level):
                continue
            last = i
            M = out["m5"]
            M["n"] += 1
            fut = range(i, i + 13)
            brk = next((k for k in fut if c[k] >= level * 1.001), None)
            if brk is not None:
                ok = False
                for k in range(brk, i + 13):
                    if h[k] >= level + a:
                        ok = True
                        break
                    if c[k] < level - 0.3 * a:
                        break
                M["held" if ok else "failed"] += 1
                res = "HELD" if ok else "FAILED"
            else:
                drop = min(l[k] for k in fut) <= level - a
                M["reject" if drop else "stall"] += 1
                res = "REJECTED" if drop else "STALL"
            M["events"].append({"time": str(m5.index[i])[:16], "result": res})
        out["m5"]["atr5"] = round(a, 2)
        out["m5"]["events"] = out["m5"]["events"][-12:]
    return out


def strong_up_stats(d1):
    """கடந்த 'strong up' நாட்கள் (≥+3%, volume ≥1.5×) → அடுத்த நாள் என்ன ஆச்சு."""
    if d1 is None or len(d1) < 25:
        return None
    r = d1["close"].pct_change() * 100
    vx = d1["volume"] / d1["volume"].rolling(20).mean()
    idx = [i for i in range(20, len(d1) - 1) if r.iloc[i] >= 3 and vx.iloc[i] >= 1.5]
    nxt = [round(float(r.iloc[i + 1]), 2) for i in idx]
    if not nxt:
        return {"n": 0}
    return {"n": len(nxt), "next_up": round(sum(x > 0 for x in nxt) / len(nxt) * 100), "next_avg": round(sum(nxt) / len(nxt), 2), "last": nxt[-5:]}


def _pct(a, b):
    return round(a / b * 100) if b else None


def level_lab(ag, inst, sym, level, now, live_ltp=None, live_vr=None):
    from .instruments import INDEX_SPOT
    sym = sym.upper().strip()
    if sym in INDEX_SPOT:
        ex, tok = INDEX_SPOT[sym]
    else:
        ex, tok = "NSE", (inst.get("eq") or {}).get(sym)
    if not tok:
        return {"err": f"{sym} — symbol கிடைக்கல (NSE F&O / index பெயர் சரியா?)"}
    d1 = ag.candles(ex, tok, "ONE_DAY", now - pd.Timedelta(days=400), now)
    m5 = ag.candles(ex, tok, "FIVE_MINUTE", now - pd.Timedelta(days=25), now)
    d1 = d1 if d1 is not None and not d1.empty else None
    m5 = m5 if m5 is not None and not m5.empty else None
    if d1 is None:
        return {"err": "Daily data வரல"}
    return analyse_level(sym, float(level), d1, m5, live_ltp, live_vr, ag, inst, now)


def analyse_level(sym, level, d1, m5, ltp=None, vr=None, ag=None, inst=None, now=None):
    H = level_history(d1, m5, level)
    su = strong_up_stats(d1)
    ltp = float(ltp or (m5["close"].iloc[-1] if m5 is not None else d1["close"].iloc[-1]))
    atr_d = float(_atr(d1).iloc[-1] or ltp * 0.02)
    hi52, lo52 = float(d1["high"].tail(250).max()), float(d1["low"].tail(250).min())
    r20 = round((d1["close"].iloc[-1] / d1["close"].iloc[-21] - 1) * 100, 2) if len(d1) > 21 else None
    r5 = round((d1["close"].iloc[-1] / d1["close"].iloc[-6] - 1) * 100, 2) if len(d1) > 6 else None
    D, M = H["daily"], H["m5"]
    touch_d = D["break"] + D["reject"]                    # level-ஐ உண்மையா தொட்ட நாட்கள் மட்டும் (அருகில் வந்து தொடாதது கணக்கில் இல்லை)
    D["touch"] = touch_d
    p_hold = _pct(M["held"], M["n"]) if M["n"] else _pct(D["held"], touch_d)
    p_rej = _pct(M["reject"] + M["failed"], M["n"]) if M["n"] else _pct(D["reject"] + (D["break"] - D["held"]), touch_d)
    n_ev = M["n"] or touch_d
    ce_sl, ce_t = round(level - 0.25 * atr_d, 2), round(level + 0.6 * atr_d, 2)
    pe_sl, pe_t = round(level + 0.25 * atr_d, 2), round(level - 0.6 * atr_d, 2)
    pos = "ABOVE" if ltp > level * 1.001 else "BELOW" if ltp < level * 0.999 else "AT"
    lean = None
    if n_ev >= 4 and p_hold is not None and p_rej is not None:
        lean = "CE" if p_hold >= 55 else "PE" if p_rej >= 60 else None
    bias_txt = ("கடந்த காலத்தில் இந்த level break ஆனப்போ பெரும்பாலும் hold ஆச்சு → CE பக்கம் சாதகம்" if lean == "CE" else
                "கடந்த காலத்தில் இந்த level-ல் பெரும்பாலும் reject ஆச்சு → PE பக்கம் சாதகம் (break confirm ஆனா மட்டும் CE)" if lean == "PE" else
                "history தெளிவா ஒரு பக்கம் சாயல (அல்லது sample குறைவு) → confirmation candle மட்டும் follow பண்ணுங்க")
    plan = {"ce": {"trigger": f"5-min candle {level:g}-க்கு மேல் close + volume ≥1.5×", "ul_sl": ce_sl, "ul_target": ce_t},
            "pe": {"trigger": f"{level:g}-ஐ தொட்டு மேல் wick விட்டு கீழ் close (rejection) அல்லது {round(level - 0.1 * atr_d, 2):g}-க்கு கீழ் 5-min close",
                   "ul_sl": pe_sl, "ul_target": pe_t}}
    if ag is not None and inst is not None and now is not None:
        for side, k in (("CE", "ce"), ("PE", "pe")):
            try:
                bsr = best_strike(ag, inst, sym, side, level, now, plan[k]["ul_sl"], plan[k]["ul_target"])
                plan[k]["strike"] = bsr.get("best")
                plan[k]["strikes"] = bsr.get("rows")
                plan[k]["strike_explain"] = bsr.get("explain")
            except Exception as e:
                plan[k]["strike_err"] = str(e)[:100]
    vr_ok = vr is not None and vr >= 1.5
    if pos == "ABOVE" and vr_ok:
        now_txt = f"✅ {level:g}-க்கு மேல் volume {vr}×-உடன் — CE trigger நடந்திருக்கலாம் (5-min close-ஐ check பண்ணுங்க)"
    elif pos == "ABOVE":
        now_txt = f"⚠ {level:g}-க்கு மேல் ஆனா volume {vr or '–'}× — confirm இல்லை, fake break ஆகலாம்"
    elif pos == "AT":
        now_txt = f"👀 {level:g}-ல் இருக்கு — அடுத்த 5-min candle தான் முடிவு (மேல் close + volume = CE · rejection = PE)"
    else:
        now_txt = f"⏳ {level:g}-க்கு கீழ் ({(level / ltp - 1) * 100:.2f}% தூரம்) — level-க்கு வரும் வரை காத்திருங்க"
    honest = (f"கடந்த {n_ev} தடவை இந்த level-க்கு வந்தது" + (f": {p_hold}% break hold · {p_rej}% reject/fail" if n_ev else "") +
              (" — ⚠ sample குறைவு (10-க்கு கீழ்), நம்பகம் குறைவு" if n_ev < 10 else "") +
              ". இது 'கண்டிப்பா profit' இல்லை — probability மட்டும். SL எப்போதும் கட்டாயம்.")
    return {"symbol": sym, "level": level, "ltp": round(ltp, 2), "pos": pos, "vr": vr, "atr_d": round(atr_d, 2), "hi52": hi52, "lo52": lo52,
            "r20": r20, "r5": r5, "hist": H, "strong_up": su, "p_hold": p_hold, "p_reject": p_rej, "n_events": n_ev, "lean": lean,
            "bias": bias_txt, "now": now_txt, "plan": plan, "honest": honest,
            "near_52w_high": hi52 and (hi52 - ltp) / hi52 * 100 <= 3}


# ───────────────────────── 🔭 PRE-BREAKOUT RADAR ─────────────────────────
def _bars_df(b):
    if not b or not b.get("c"):
        return None
    return pd.DataFrame({"open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"], "volume": b.get("v") or [0] * len(b["c"])},
                        index=pd.to_datetime(b["t"]))


def prebreak_scan(bars, live_q, oi_tag=None, top=15):
    """Daily bars: ATR5/ATR20 சுருக்கம் · Bollinger width குறைவு · NR7 · volume dry-up · 20-நாள் high/low அருகில் · OI."""
    out = []
    for s, b in (bars or {}).items():
        d = _bars_df(b)
        if d is None or len(d) < 45:
            continue
        a5, a20 = float(_atr(d, 5).iloc[-1] or 0), float(_atr(d, 20).iloc[-1] or 0)
        if not a20:
            continue
        c = d["close"]
        bw = (4 * c.rolling(20).std() / c.rolling(20).mean()).dropna()
        bw_pct = float((bw.tail(60) <= bw.iloc[-1]).mean() * 100) if len(bw) >= 20 else 50
        rng = (d["high"] - d["low"]).tail(7)
        nr7 = bool(rng.iloc[-1] <= rng.min() + 1e-9)
        v5, v20 = float(d["volume"].tail(5).mean()), float(d["volume"].tail(20).mean() or 1)
        h20, l20 = float(d["high"].iloc[-21:-1].max()), float(d["low"].iloc[-21:-1].min())
        q = (live_q or {}).get(s) or {}
        ltp = float(q.get("ltp") or c.iloc[-1])
        sma20 = float(c.tail(20).mean())
        side = "CE" if (h20 - ltp) / h20 * 100 <= (ltp - l20) / l20 * 100 else "PE"
        lvl = h20 if side == "CE" else l20
        dist = abs(lvl - ltp) / lvl * 100
        comp = a5 / a20
        sc = 0
        sc += 35 if comp <= 0.6 else 25 if comp <= 0.75 else 10 if comp <= 0.9 else 0
        sc += 10 if bw_pct <= 15 else 5 if bw_pct <= 30 else 0
        sc += 25 if dist <= 1 else 15 if dist <= 2 else 5 if dist <= 3.5 else 0
        sc += 15 if v5 / v20 <= 0.75 else 8 if v5 / v20 <= 0.9 else 0
        sc += 5 if nr7 else 0
        tag = (oi_tag or {}).get(s, "")
        if (side == "CE" and tag in ("Long Built Up", "Short Covering")) or (side == "PE" and tag in ("Short Built Up", "Long Unwinding")):
            sc += 10
        sc += 5 if (ltp > sma20) == (side == "CE") else 0
        if sc < 50:
            continue
        vr = q.get("vol_ratio")
        brk = (ltp > lvl) if side == "CE" else (ltp < lvl)
        st = "BREAKING" if brk and (vr or 0) >= 1.5 else "FAKE?" if brk else "NEAR" if dist <= 0.7 else "WATCH"
        out.append({"symbol": s, "side": side, "level": round(lvl, 2), "ltp": round(ltp, 2), "dist": round(dist, 2), "score": min(100, sc),
                    "comp": round(comp, 2), "bw_pct": round(bw_pct), "vol_dry": round(v5 / v20, 2), "nr7": nr7, "oi": tag, "vr": vr, "status": st,
                    "atr": round(a20, 2), "ul_sl": round(lvl - 0.3 * a20 if side == "CE" else lvl + 0.3 * a20, 2),
                    "ul_target": round(lvl + 0.8 * a20 if side == "CE" else lvl - 0.8 * a20, 2),
                    "why": [f"ATR5/ATR20 {comp:.2f} (சுருக்கம்)", f"BB width {bw_pct:.0f}% percentile", f"volume dry {v5 / v20:.2f}×",
                            f"20-நாள் {'high' if side == 'CE' else 'low'} {lvl:.2f} ({dist:.1f}%)"] + (["NR7"] if nr7 else []) + ([f"OI {tag}"] if tag else [])})
    out.sort(key=lambda r: (r["status"] != "BREAKING", -r["score"]))
    return out[:top]


def prebreak_run(ag, inst, now, full=None, live=True, max_day=4):
    """Radar + BREAKING (score ≥70, 9:30–2:30) → best strike → call (kind PREBRK, நாளைக்கு max 4, symbol-க்கு ஒன்று)."""
    from . import fullscan as FS
    from .calls import CALLS_LOCK, STORE, _new
    from .optmath import plan as _plan
    bu = {}
    for kind, xs in ((full or {}).get("oi_buildup") or {}).items():
        for x in xs:
            bu[x["symbol"]] = kind
    rows = prebreak_scan(FS.C.get("bars") or {}, FS.C.get("live_q") or {}, bu)
    P = STATE["prebreak"]
    P.update(time=now.strftime("%I:%M:%S %p"), rows=rows)
    hm, day = now.strftime("%H:%M"), str(now.date())
    if not (live and ag and "09:30" <= hm <= "14:30"):
        return P
    with CALLS_LOCK:
        mine = [c for c in (STORE.load().get("calls") or {}).values() if c.get("date") == day and c.get("kind") == "PREBRK"]
    for r in [r for r in rows if r["status"] == "BREAKING" and r["score"] >= 70]:
        if len(mine) >= max_day or any(c["symbol"] == r["symbol"] for c in mine):
            continue
        bsr = best_strike(ag, inst, r["symbol"], r["side"], r["ltp"], now, r["ul_sl"], r["ul_target"], min_days=3)
        b = bsr.get("best")
        if not b or (b.get("score") or 0) < 50:
            P["log"].insert(0, {"time": hm, "symbol": r["symbol"], "result": "⛔ நல்ல strike இல்லை"})
            continue
        pl = _plan(b["ltp"], r["ltp"], b["strike"], b["expiry"], r["side"], r["ul_sl"], [r["ul_target"], r["ul_target"] + (r["ul_target"] - r["level"]) * 0.5,
                                                                                         r["ul_target"] + (r["ul_target"] - r["level"])],
                   now.to_pydatetime(), b["lot"])
        if not pl:
            continue
        opt = {"token": b["token"], "exch": b["exch"], "contract": b["contract"], "strike": b["strike"], "type": r["side"], "expiry": b["expiry"],
               "lot": b["lot"], "spread_pct": b["spread_pct"], "plan": dict(pl, money=False)}
        rr = {"symbol": r["symbol"], "side": r["side"], "price": r["ltp"], "sl": r["ul_sl"], "targets": [r["ul_target"]], "score": r["score"], "stars": 4,
              "vol_ratio": r["vr"], "reasons": ["🔭 Pre-breakout: " + " · ".join(r["why"][:4]), "🎯 " + (bsr.get("explain") or "")]}
        with CALLS_LOCK:
            d = STORE.load()
            c = _new("PREBRK", "🔭 Pre-Breakout Radar", rr, opt, now, day)
            if c and c["id"] not in d["calls"] and not c.get("shadow"):
                c.update(source_label="🔭 Pre-Breakout", intraday=True, strike_pick={k: b.get(k) for k in ("moneyness", "delta", "theta_pct", "iv", "rr", "score")})
                d["calls"][c["id"]] = c
                STORE.dirty = True
                mine.append(c)
                P["log"].insert(0, {"time": hm, "symbol": r["symbol"], "result": "✅ CALL"})
            else:
                P["log"].insert(0, {"time": hm, "symbol": r["symbol"], "result": "⛔ quality gate / duplicate"})
    del P["log"][30:]
    return P


# ───────────────────────── ⚔ BATTLE LAB · 🎓 LEARNING · 🧠 REGIME BRAIN ─────────────────────────
FAMILY = [("ICT / Liquidity", ("ict", "silver bullet", "sweep", "liquidity", "smc", "cosmc", "cqsmc", "order flow", "trap")),
          ("VWAP / Mean-Rev", ("vwap", "mean reversion", "vwap2sd", "reversal")),
          ("ORB / Opening", ("orb", "opening", "first 5")),
          ("Trend / Momentum", ("trend", "momentum", "movers", "breakout", "donchian", "tsmom", "money machine", "strong", "goki", "jackpot", "pre-break")),
          ("OI / Gamma", ("oi", "gamma", "volume+oi", "footprint", "index oi", "unwind")),
          ("News", ("news",)), ("Mannan", ("mannan",)), ("Chart pattern", ("chart", "pattern"))]


def family(c):
    s = f"{c.get('source') or ''} {c.get('source_label') or ''} {c.get('kind') or ''}".lower()
    for name, keys in FAMILY:
        if any(k in s for k in keys):
            return name
    return "Other"


def condition(c):
    r = str(c.get("regime") or "").upper()
    if "VOLAT" in r:
        return "VOLATILE"
    if "TREND" in r or "UP" in r.split() or "DOWN" in r.split():
        return "TRENDING"
    if "RANGE" in r or "SIDE" in r or "CHOP" in r:
        return "SIDEWAYS"
    return "UNKNOWN"


def _net(c):
    try:
        from .ai import charges
        return (c.get("pnl_lot") or 0) - charges(c)
    except Exception:
        return c.get("pnl_lot") or 0


def _st(xs):
    if not xs:
        return {"n": 0}
    net = [_net(c) for c in xs]
    w = sum(x > 0 for x in net)
    return {"n": len(xs), "win": round(w / len(xs) * 100), "net": round(sum(net)), "avg": round(sum(net) / len(xs))}


def battle_lab(calls, min_n=8):
    done = sorted([c for c in calls if not c.get("shadow") and c.get("status") not in OPEN and c.get("pnl_lot") is not None and c.get("kind") != "PICK"],
                  key=lambda c: str(c.get("exit_time") or f"{c.get('date')} {c.get('time')}"))
    fams = {}
    for c in done:
        fams.setdefault(family(c), []).append(c)
    rows = []
    for f, xs in fams.items():
        k = int(len(xs) * 0.7)
        ins, oos = xs[:k], xs[k:]
        a, b = _st(ins), _st(oos)
        stable = bool(b.get("n", 0) >= 5 and a.get("n", 0) >= 5 and abs((a.get("win") or 0) - (b.get("win") or 0)) <= 12 and (b.get("net") or 0) > 0)
        conds = {cn: _st([c for c in xs if condition(c) == cn]) for cn in ("TRENDING", "SIDEWAYS", "VOLATILE", "UNKNOWN")}
        rows.append({"family": f, "all": _st(xs), "in": a, "oos": b, "stable": stable, "cond": conds})
    rows.sort(key=lambda r: -(r["oos"].get("net") or -1e9))
    best = {}
    for cn in ("TRENDING", "SIDEWAYS", "VOLATILE"):
        cand = [(r["family"], r["cond"][cn]) for r in rows if r["cond"][cn].get("n", 0) >= min_n and (r["cond"][cn].get("avg") or 0) > 0]
        cand.sort(key=lambda x: -x[1]["avg"])
        best[cn] = [{"family": f, **s} for f, s in cand[:3]]
    return {"rows": rows, "best": best, "n": len(done)}


def learning(calls, min_n=10):
    """முடிந்த calls → (நேரம் · side · volume · grade · module family) buckets → நல்லது / மோசம்."""
    done = [c for c in calls if not c.get("shadow") and c.get("status") not in OPEN and c.get("pnl_lot") is not None and c.get("kind") != "PICK"]

    def tb(c):
        t = str(c.get("time") or "")
        return "9:15–10:00" if t < "10:00" else "10:00–11:30" if t < "11:30" else "11:30–13:30" if t < "13:30" else "13:30 பிறகு"

    def vb(c):
        v = c.get("vol_ratio") or 0
        return "volume <2×" if v < 2 else "volume 2–4×" if v < 4 else "volume 4×+"
    keys = {"நேரம்": tb, "Side": lambda c: c.get("side") or "?", "Volume": vb, "Grade": lambda c: f"Grade {c.get('grade') or '?'}",
            "Strategy": family, "Market": condition, "Pink": lambda c: "🩷 pink" if c.get("pink") else "pink இல்லை"}
    rows = []
    base = _st(done)
    for kname, fn in keys.items():
        g = {}
        for c in done:
            g.setdefault(fn(c), []).append(c)
        for v, xs in g.items():
            s = _st(xs)
            if s["n"] >= min_n:
                rows.append({"group": kname, "value": v, **s, "edge": (s["win"] - (base.get("win") or 0))})
    good = sorted([r for r in rows if r["avg"] > 0], key=lambda r: -r["avg"])[:6]
    bad = sorted([r for r in rows if r["avg"] <= 0], key=lambda r: r["avg"])[:6]
    tips = [f"✅ {r['group']} = {r['value']}: win {r['win']}% · ₹{r['avg']:+,}/call ({r['n']})" for r in good[:3]] + \
           [f"⛔ {r['group']} = {r['value']}: win {r['win']}% · ₹{r['avg']:+,}/call ({r['n']}) — தவிர்க்கவும்" for r in bad[:3]]
    return {"base": base, "good": good, "bad": bad, "tips": tips}


DEFAULT_FIT = {"TRENDING": ["Trend / Momentum", "ORB / Opening"], "SIDEWAYS": ["VWAP / Mean-Rev", "ICT / Liquidity"],
               "VOLATILE": ["ICT / Liquidity", "OI / Gamma"]}


def regime_brain(full, risk, battle):
    """இப்போதைய regime → அதில் history-ல் வேலை செய்த strategy families (data போதலைன்னா default rule)."""
    idx = {x.get("index"): x for x in (full or {}).get("index") or []}
    npct = (idx.get("NIFTY") or {}).get("pct")
    d, up, dn = (risk or {}).get("dir"), (risk or {}).get("up"), (risk or {}).get("dn")
    vel = abs((risk or {}).get("vel") or 0)
    if npct is not None and abs(npct) >= 1.2 and vel >= 0.25:
        rg = "VOLATILE"
    elif d in ("UP", "DOWN") and npct is not None and abs(npct) >= 0.4:
        rg = "TRENDING"
    elif npct is not None and abs(npct) < 0.35:
        rg = "SIDEWAYS"
    else:
        rg = "TRENDING" if d else "SIDEWAYS"
    bst = (battle or {}).get("best", {}).get(rg) or []
    src = "history" if bst else "default rule (data போதல)"
    fams = [b["family"] for b in bst] or DEFAULT_FIT[rg]
    avoid = {"TRENDING": "Counter-trend mean-reversion", "SIDEWAYS": "Breakout chase", "VOLATILE": "பெரிய size / tight SL"}[rg]
    return {"regime": rg, "dir": d, "nifty": npct, "breadth": [up, dn], "use": fams, "use_stats": bst, "source": src, "avoid": avoid,
            "txt": f"{rg}{(' ' + ('⬆' if d == 'UP' else '⬇')) if d and rg != 'SIDEWAYS' else ''} → {', '.join(fams)} பயன்படுத்துங்க · {avoid} தவிர்க்கவும் ({src})"}


OI_MEAN = {"Long Built Up": ("price ⬆ + OI ⬆", "புது buyers நுழையுறாங்க — bullish", "CE"),
           "Short Covering": ("price ⬆ + OI ⬇", "sellers வெளியேறுறாங்க — bullish ஆனா குறுகிய கால", "CE"),
           "Short Built Up": ("price ⬇ + OI ⬆", "புது sellers — bearish", "PE"),
           "Long Unwinding": ("price ⬇ + OI ⬇", "buyers வெளியேறுறாங்க — bearish ஆனா குறுகிய கால", "PE")}


def oi_flow(oi_buildup, live_q, calls=None, mdir=None):
    out = []
    for kind, rows in (oi_buildup or {}).items():
        m = OI_MEAN.get(kind)
        if not m:
            continue
        for r in rows[:10]:
            q = (live_q or {}).get(r["symbol"]) or {}
            oi, ch = r.get("oi") or 0, r.get("oi_chg") or 0
            ocp = round(ch / (oi - ch) * 100, 1) if oi and oi != ch else None
            vr = q.get("vol_ratio")
            pct = q.get("pct") if q.get("pct") is not None else r.get("pct")
            fresh = kind in ("Long Built Up", "Short Built Up")
            strong = bool(vr and vr >= 1.5 and ocp is not None and abs(ocp) >= 2 and pct is not None and abs(pct) >= 1)
            against = bool(mdir and (mdir == "UP") != (m[2] == "CE"))
            oc = next((c for c in (calls or []) if c.get("symbol") == r["symbol"] and c.get("status") in OPEN and not c.get("shadow")), None)
            if oc and oc.get("side") == m[2]:
                light, ltxt = ("🟢" if oc.get("action") == "ENTRY" and not against else "🟡"), f"Call இருக்கு: {oc['symbol']} {oc.get('strike')} {oc.get('side')} · " + \
                    ("entry zone-க்குள் ✅" if oc.get("action") == "ENTRY" else "late — pullback-க்கு காத்திருங்க" if oc.get("action") == "LATE" else str(oc.get("action") or ""))
            elif strong and fresh and not against:
                light, ltxt = "🟢", f"ENTRY ZONE — {m[2]} (OI {ocp:+}% + volume {vr}× + price {pct:+.2f}%) · strike-க்கு 📍 Lab"
            elif strong and not against:
                light, ltxt = "🟡", "Short covering / unwinding — குறுகிய கால move, 1 lot மட்டும்"
            elif against:
                light, ltxt = "🔴", f"Market திசை எதிர் — {m[2]} வேண்டாம்"
            else:
                light, ltxt = "🟡", "WATCH — volume / OI இன்னும் போதல"
            out.append({"symbol": r["symbol"], "kind": kind, "pattern": m[0], "meaning": m[1], "side": m[2], "pct": pct,
                        "oi": oi, "oi_chg": ch, "oi_chg_pct": ocp, "vr": vr, "strong": strong, "light": light, "ltxt": ltxt, "call": oc["id"] if oc else None})
    out.sort(key=lambda r: ({"🟢": 0, "🟡": 1, "🔴": 2}.get(r.get("light"), 3), -abs(r.get("oi_chg_pct") or 0)))
    return out[:30]


def report(calls, full, risk):
    from . import fullscan as FS
    b = battle_lab(calls)
    from .calls import STORE
    byid = {c["id"]: c for c in calls}
    day = max((c.get("date") or "" for c in calls), default="")
    return {"prebreak": STATE["prebreak"], "auto": STATE.get("auto") or {}, "battle": b, "learning": learning(calls), "brain": regime_brain(full, risk, b),
            "oi": oi_flow((full or {}).get("oi_buildup"), FS.C.get("live_q"), [c for c in calls if c.get("date") == day], (risk or {}).get("dir")),
            "picks": picks_journal(byid, STORE.load().get("ailab_picks") or {})}


# ───────────────────────── 🤖 AUTO LAB — ஒவ்வொரு call-க்கும் தானா history check ─────────────────────────
SYMC = {}          # (symbol, day) → {"d1", "m5", "t"}  — symbol-க்கு நாளுக்கு 1 daily + 15 நிமிடத்துக்கு 1 5-min fetch
AUTO = {}          # call id → verdict


def _mirror(df):
    """PE-க்கு: விலையை தலைகீழா (−) மாத்தி அதே 'level break hold' கணக்கு = support breakdown hold."""
    if df is None:
        return None
    return pd.DataFrame({"open": -df["open"], "high": -df["low"], "low": -df["high"], "close": -df["close"], "volume": df["volume"]}, index=df.index)


def _sym_data(ag, inst, sym, now):
    from .instruments import INDEX_SPOT
    day = str(now.date())
    for k in [k for k in SYMC if k[1] != day]:
        SYMC.pop(k, None)
    x = SYMC.get((sym, day))
    if x and (now - x["t"]).total_seconds() < 900:
        return x, False
    ex, tok = INDEX_SPOT[sym] if sym in INDEX_SPOT else ("NSE", (inst.get("eq") or {}).get(sym))
    if not tok:
        return None, False
    d1 = x["d1"] if x else ag.candles(ex, tok, "ONE_DAY", now - pd.Timedelta(days=400), now)
    m5 = ag.candles(ex, tok, "FIVE_MINUTE", now - pd.Timedelta(days=25), now)
    x = SYMC[(sym, day)] = {"d1": d1 if d1 is not None and not d1.empty else None, "m5": m5 if m5 is not None and not m5.empty else None, "t": now}
    return x, True


def call_verdict(c, d1, m5, ltp, vr):
    """Call-ன் underlying level (signal விலை) — கடந்த காலத்தில் அந்த level-ஐ அதே பக்கம் உடைச்சப்போ hold ஆச்சா / fail ஆச்சா."""
    level = float(c.get("ul_price") or 0)
    if not level or d1 is None:
        return None
    ce = c.get("side") == "CE"
    ltp = float(ltp or level)
    A = analyse_level(c["symbol"], level if ce else -level, d1 if ce else _mirror(d1), m5 if ce else _mirror(m5), ltp if ce else -ltp, vr)
    n, ph, pr = A["n_events"], A["p_hold"], A["p_reject"]
    hist = "LOW" if n < 4 else "OK" if (ph or 0) >= 55 else "BAD" if (pr or 0) >= 60 else "MIXED"
    beyond = round((ltp - level) / level * 100 * (1 if ce else -1), 2)
    late = beyond > max(1.5, 0.5 * A["atr_d"] / level * 100)
    trig = f"{level:g} {'மேல்' if ce else 'கீழ்'} 5-min close + volume ≥1.5× ஆனா எடுங்க"
    txt = {"OK": f"கடந்த {n} தடவை இந்த level-ஐ {'மேல்' if ce else 'கீழ்'} உடைச்சப்போ {ph}% hold ஆச்சு ✓",
           "BAD": f"கடந்த {n} தடவை இந்த level-ல் {pr}% fail / reject ஆச்சு ✗",
           "MIXED": f"கடந்த {n} தடவை: {ph}% hold · {pr}% fail — தெளிவில்லை",
           "LOW": f"இந்த level-க்கு history குறைவு ({n} தடவை) — confirmation மட்டும் நம்புங்க"}[hist]
    su = A.get("strong_up") or {}
    return {"id": c["id"], "symbol": c["symbol"], "side": c["side"], "strike": c.get("strike"), "level": round(level, 2), "ltp": round(ltp, 2),
            "hist": hist, "n": n, "p_hold": ph, "p_reject": pr, "beyond": beyond, "late": bool(late), "trigger": trig, "txt": txt,
            "strong_up": su if ce else None, "atr_d": A["atr_d"], "time": c.get("time")}


def autolab_run(ag, inst, now, calls, full=None, max_fetch=4):
    """இன்றைய OPEN calls (pink / DSK / grade A முதலில்) → history verdict. API: புது symbol-க்கு மட்டும், ஒரு run-க்கு max 2."""
    from . import fullscan as FS
    day = str(now.date())
    idx = {x.get("index"): x for x in (full or {}).get("index") or []}
    for c in calls:                         # MCX: history check இல்லை (NSE data மட்டும்) — "checking…" என்று நிக்காம தெளிவா
        if c.get("date") == day and c.get("exch") == "MCX" and c.get("status") in OPEN and c["id"] not in AUTO:
            AUTO[c["id"]] = {"id": c["id"], "symbol": c["symbol"], "side": c.get("side"), "hist": "NA", "n": 0, "late": False,
                             "txt": "MCX — level history check இல்லை (commodity rules மட்டும்)", "trigger": "Entry zone-க்குள் மட்டும்", "level": None, "beyond": 0}
    todo = [c for c in calls if c.get("date") == day and c.get("status") in OPEN and not c.get("shadow") and c.get("exch") != "MCX"
            and c.get("ul_price") and c.get("kind") != "PICK"]
    todo.sort(key=lambda c: (not c.get("pink"), c.get("kind") != "DSK", c.get("grade") != "A", str(c.get("time") or "")), reverse=False)
    fetched = 0
    for c in todo:
        sym = c["symbol"]
        if (sym, day) not in SYMC or (now - SYMC[(sym, day)]["t"]).total_seconds() >= 900:
            if fetched >= max_fetch or not ag:
                continue
        try:
            x, new = _sym_data(ag, inst, sym, now)
        except Exception:
            continue
        fetched += int(bool(new))
        if not x:
            continue
        q = (FS.C.get("live_q") or {}).get(sym) or {}
        ltp = q.get("ltp") or (idx.get(sym) or {}).get("spot")
        try:
            v = call_verdict(c, x["d1"], x["m5"], ltp, q.get("vol_ratio"))
        except Exception:
            v = None
        if v:
            AUTO[c["id"]] = v
    for k in [k for k in AUTO if not k.startswith(day)]:
        AUTO.pop(k, None)
    try:
        journal_picks(calls, now)
    except Exception:
        pass
    STATE["auto"] = {"time": now.strftime("%I:%M %p"), "rows": dict(AUTO)}
    return STATE["auto"]


# ───────────────────────── 🏆 AI LAB PICKS — TAKE ஆன ஒவ்வொரு call-ம் date / time / targets-உடன் நிரந்தரமா ─────────────────────────
def decide(c, v, mdir):
    """Server-side (journal-க்கு): TAKE / WAIT / SKIP — frontend aiDecision-ன் அதே அடிப்படை."""
    if not c or c.get("status") not in OPEN or c.get("kind") == "PICK":
        return None
    ce = c.get("side") == "CE"
    if (v or {}).get("hist") == "BAD" or (v or {}).get("late") or (mdir and c.get("exch") != "MCX" and (mdir == "UP") != ce):
        return "SKIP"
    good = (v or {}).get("hist") == "OK" or (v and v.get("hist") in ("LOW", "MIXED", "NA") and (c.get("pink") or (c.get("grade") == "A" and (c.get("score") or 0) >= 80)))
    return "TAKE" if c.get("action") == "ENTRY" and good else "WAIT"


def journal_picks(calls, now):
    from .ai import STATE as AST
    from .calls import CALLS_LOCK, STORE
    mdir = (AST.get("risk") or {}).get("dir")
    day, hm = str(now.date()), now.strftime("%H:%M")
    new = []
    for c in calls:
        if c.get("date") != day:
            continue
        d = decide(c, AUTO.get(c["id"]), mdir)
        if d == "TAKE":
            new.append(c)
    if not new:
        return 0
    with CALLS_LOCK:
        D = STORE.load()
        J = D.setdefault("ailab_picks", {})
        n = 0
        for c in new:
            if c["id"] in J:
                continue
            v = AUTO.get(c["id"]) or {}
            J[c["id"]] = {"id": c["id"], "date": day, "time": hm, "symbol": c["symbol"], "strike": c.get("strike"), "side": c.get("side"),
                          "expiry": c.get("expiry"), "lot": c.get("lot"), "entry": c.get("ltp") or c.get("entry"), "sl": c.get("sl"),
                          "targets": c.get("targets") or [], "source": c.get("source_label") or c.get("source"), "hist": v.get("txt"),
                          "token": c.get("token"), "exch": c.get("exch")}
            n += 1
        for k in sorted(J, key=lambda k: J[k]["date"] + J[k]["time"])[:-500]:
            J.pop(k, None)
        if n:
            STORE.dirty = True
    return n


def picks_journal(calls_by_id, picks):
    """Journal rows + அந்த call-ன் இப்போதைய result (AI pick நேர entry-ல் இருந்து P/L)."""
    rows = []
    for p in sorted(picks.values(), key=lambda x: x["date"] + x["time"], reverse=True)[:200]:
        c = calls_by_id.get(p["id"]) or {}
        st = c.get("status") or "?"
        px = c.get("exit") if st not in OPEN else c.get("ltp")
        pl = round(((px or p["entry"]) - p["entry"]) * (p.get("lot") or 1)) if p.get("entry") else None
        rows.append({**p, "status": st, "ltp": px, "pnl_lot": pl, "hits": c.get("hits") or []})
    closed = [r for r in rows if r["status"] not in OPEN and r["pnl_lot"] is not None]
    w = sum(r["pnl_lot"] > 0 for r in closed)
    return {"rows": rows, "stats": {"n": len(closed), "win": round(w / len(closed) * 100) if closed else None, "net": sum(r["pnl_lot"] for r in closed)}}
