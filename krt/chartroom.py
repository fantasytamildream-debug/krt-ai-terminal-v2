"""📈 CHART ROOM — top 2 open calls-ன் underlying 5-min chart + auto chart analysis.
Auto-draw: support / resistance (pivot clusters) · trendlines (கடைசி swing highs / lows) · VWAP · EMA20 · volume.
Pattern: ascending / descending / symmetrical triangle · rising / falling channel · range · double top / bottom · bull / bear flag.
Prediction: "இந்த level மேல் 5-min close ஆனா ⬆ target · இந்த level கீழ் ஆனா ⬇" → ஒவ்வொரு prediction-ம் track (break ஆச்சா, எந்த பக்கம், target வந்துச்சா)
→ accuracy table. Rule-based geometry — AI prediction / guarantee இல்லை.
"""
import numpy as np
import pandas as pd

from .instruments import INDEX_SPOT

STATE = {"time": None, "charts": [], "err": None}


def _atr(h, l, c, n=14):
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(tr[-n:].mean()) if len(tr) else 0.0


def pivots(h, l, w=3):
    hi, lo = [], []
    for i in range(w, len(h) - w):
        if h[i] == max(h[i - w:i + w + 1]):
            hi.append((i, float(h[i])))
        if l[i] == min(l[i - w:i + w + 1]):
            lo.append((i, float(l[i])))
    return hi, lo


def levels(hi, lo, atr, px):
    pts = sorted([p for _, p in hi] + [p for _, p in lo])
    cl = []
    for p in pts:
        if cl and abs(p - cl[-1][-1]) <= 0.35 * atr:
            cl[-1].append(p)
        else:
            cl.append([p])
    lv = [{"price": round(float(np.mean(c)), 2), "touches": len(c)} for c in cl if len(c) >= 2]
    up = sorted([x for x in lv if x["price"] > px], key=lambda x: x["price"])[:2]
    dn = sorted([x for x in lv if x["price"] <= px], key=lambda x: -x["price"])[:2]
    return up, dn


def fit(points):
    if len(points) < 2:
        return None
    x = np.array([p[0] for p in points], float)
    y = np.array([p[1] for p in points], float)
    m, b = np.polyfit(x, y, 1) if len(points) > 2 else ((y[1] - y[0]) / ((x[1] - x[0]) or 1), y[0] - (y[1] - y[0]) / ((x[1] - x[0]) or 1) * x[0])
    return float(m), float(b)


def analyse(df):
    o, h, l, c, v = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    n = len(c)
    atr = _atr(h, l, c) or (c[-1] * 0.003)
    px = float(c[-1])
    hi, lo = pivots(h, l)
    hi, lo = [p for p in hi if p[0] >= n - 60], [p for p in lo if p[0] >= n - 60]
    up_lv, dn_lv = levels(hi, lo, atr, px)
    U, L = fit(hi[-3:]), fit(lo[-3:])
    x_now = n - 1
    flat = 0.04 * atr
    pat, bias, why = "No clear pattern", None, []
    u_now = U[0] * x_now + U[1] if U else (up_lv[0]["price"] if up_lv else float(h[-20:].max()))
    l_now = L[0] * x_now + L[1] if L else (dn_lv[0]["price"] if dn_lv else float(l[-20:].min()))
    su, sl = (U[0] if U else 0), (L[0] if L else 0)
    trend_before = "UP" if c[-1] > c[max(0, n - 40)] else "DOWN"
    # pole + flag
    pole = c[-12] - c[-20] if n > 20 else 0
    if n > 20 and abs(pole) > 3 * atr and (h[-10:].max() - l[-10:].min()) < 0.5 * abs(pole):
        pat = "Bull flag" if pole > 0 else "Bear flag"
        bias = "UP" if pole > 0 else "DOWN"
        why.append(f"Pole {abs(pole) / atr:.1f} ATR · சின்ன consolidation")
        u_now, l_now = float(h[-10:].max()), float(l[-10:].min())
    elif len(hi) >= 2 and abs(hi[-1][1] - hi[-2][1]) <= 0.3 * atr and px < hi[-1][1] and hi[-1][0] - hi[-2][0] >= 5:
        neck = float(l[hi[-2][0]:hi[-1][0] + 1].min())
        pat, bias, l_now, u_now = "Double top", "DOWN", neck, max(hi[-1][1], hi[-2][1])
        why.append(f"இரண்டு high ~{hi[-1][1]:.2f} · neckline {neck:.2f}")
    elif len(lo) >= 2 and abs(lo[-1][1] - lo[-2][1]) <= 0.3 * atr and px > lo[-1][1] and lo[-1][0] - lo[-2][0] >= 5:
        neck = float(h[lo[-2][0]:lo[-1][0] + 1].max())
        pat, bias, u_now, l_now = "Double bottom", "UP", neck, min(lo[-1][1], lo[-2][1])
        why.append(f"இரண்டு low ~{lo[-1][1]:.2f} · neckline {neck:.2f}")
    elif len(hi) >= 3 and hi[-2][1] > hi[-1][1] + 0.3 * atr and hi[-2][1] > hi[-3][1] + 0.3 * atr and abs(hi[-1][1] - hi[-3][1]) <= 0.6 * atr:
        neck = float(min(l[hi[-3][0]:hi[-2][0] + 1].min(), l[hi[-2][0]:hi[-1][0] + 1].min()))
        pat, bias, l_now, u_now = "Head & shoulders", "DOWN", neck, hi[-1][1]
        why.append(f"Head {hi[-2][1]:.2f} · shoulders ~{hi[-1][1]:.2f} · neckline {neck:.2f}")
    elif len(lo) >= 3 and lo[-2][1] < lo[-1][1] - 0.3 * atr and lo[-2][1] < lo[-3][1] - 0.3 * atr and abs(lo[-1][1] - lo[-3][1]) <= 0.6 * atr:
        neck = float(max(h[lo[-3][0]:lo[-2][0] + 1].max(), h[lo[-2][0]:lo[-1][0] + 1].max()))
        pat, bias, u_now, l_now = "Inverse head & shoulders", "UP", neck, lo[-1][1]
        why.append(f"Head {lo[-2][1]:.2f} · shoulders ~{lo[-1][1]:.2f} · neckline {neck:.2f}")
    elif U and L and su > flat and sl > flat and sl > su * 1.3:
        pat, bias = "Rising wedge", "DOWN"
        why.append("இரண்டு line-ம் மேலே, ஆனா நெருங்குது — bearish wedge")
    elif U and L and su < -flat and sl < -flat and su < sl * 1.3:
        pat, bias = "Falling wedge", "UP"
        why.append("இரண்டு line-ம் கீழே, ஆனா நெருங்குது — bullish wedge")
    elif U and L:
        if abs(su) < flat and sl > flat:
            pat, bias = "Ascending triangle", "UP"
        elif su < -flat and abs(sl) < flat:
            pat, bias = "Descending triangle", "DOWN"
        elif su < -flat and sl > flat:
            pat, bias = "Symmetrical triangle", trend_before
        elif su > flat and sl > flat:
            pat, bias = "Rising channel", "UP"
        elif su < -flat and sl < -flat:
            pat, bias = "Falling channel", "DOWN"
        elif abs(su) < flat and abs(sl) < flat:
            pat, bias = "Range / rectangle", trend_before
        why.append(f"Upper line slope {su / atr:+.2f} ATR/bar · lower {sl / atr:+.2f}")
    height = max(u_now - l_now, atr)
    # indicators
    td = df[df.index.date == df.index[-1].date()]
    tp = (td["high"] + td["low"] + td["close"]) / 3
    vw = (tp * td["volume"]).cumsum() / td["volume"].replace(0, np.nan).cumsum()
    ema20 = pd.Series(c).ewm(span=20, adjust=False).mean().values
    above_vwap = px > float(vw.iloc[-1]) if len(vw) and not np.isnan(vw.iloc[-1]) else None
    if above_vwap is not None:
        why.append("Price VWAP-க்கு மேல்" if above_vwap else "Price VWAP-க்கு கீழ்")
    vx = float(v[-1] / v[-21:-1].mean()) if n > 21 and v[-21:-1].mean() else 0
    if vx:
        why.append(f"கடைசி candle volume {vx:.1f}×")
    up_t, dn_t = round(u_now + height, 2), round(l_now - height, 2)
    txt = (f"{pat}: {round(u_now, 2)} மேல் 5-min close ஆனா ⬆ target {up_t} · {round(l_now, 2)} கீழ் close ஆனா ⬇ target {dn_t}."
           + (f" Bias {('⬆ மேலே' if bias == 'UP' else '⬇ கீழே')} ({'trend' if pat in ('Range / rectangle', 'Symmetrical triangle') else 'pattern'})." if bias else ""))
    st_ = structure_engine(hi, lo, c, atr)
    lq_ = liquidity_engine(o, h, l, c, hi, lo, atr)
    fib_ = fib_engine(h, l)
    cdl_ = candle_engine(o, h, l, c, atr)
    mtf_ = mtf_engine(df)
    base = {"pattern": pat, "bias": bias, "up_level": round(u_now, 2), "dn_level": round(l_now, 2)}
    se_ = smart_entry(base, st_, lq_, mtf_, cdl_, fib_, px, atr, round(vx, 2))
    return {"structure": st_, "liquidity": lq_, "fib": fib_, "candles": cdl_, "mtf": mtf_, "smart": se_,
            "pattern": pat, "bias": bias, "trend_before": trend_before, "up_level": round(u_now, 2), "dn_level": round(l_now, 2), "up_target": up_t, "dn_target": dn_t,
            "height": round(height, 2), "atr": round(atr, 2), "px": round(px, 2), "text": txt, "why": why,
            "lines": {"upper": [U[0], U[1]] if U else None, "lower": [L[0], L[1]] if L else None},
            "sr_up": up_lv, "sr_dn": dn_lv, "vwap": [None if np.isnan(x) else round(float(x), 2) for x in vw.values],
            "ema20": [round(float(x), 2) for x in ema20], "vol_x": round(vx, 2)}


# ───────────── V2 engines (TrendSpider-style) ─────────────
def structure_engine(hi, lo, c, atr):
    """1. Market Structure: HH / HL / LH / LL labels + BOS / CHOCH."""
    piv = sorted([(i, p, "H") for i, p in hi] + [(i, p, "L") for i, p in lo])
    labels, last_h, last_l, trend = [], None, None, None
    for i, p, t in piv:
        if t == "H":
            lab = "HH" if last_h is not None and p > last_h else "LH" if last_h is not None else "H"
            last_h = p
        else:
            lab = "HL" if last_l is not None and p > last_l else "LL" if last_l is not None else "L"
            last_l = p
        labels.append({"i": i, "price": round(p, 2), "label": lab})
    seq = [x["label"] for x in labels[-4:]]
    if seq.count("HH") + seq.count("HL") >= 3:
        trend = "UP"
    elif seq.count("LH") + seq.count("LL") >= 3:
        trend = "DOWN"
    events = []
    px = c[-1]
    if last_h is not None and px > last_h:
        events.append({"type": "BOS ⬆" if trend == "UP" else "CHOCH ⬆", "price": round(last_h, 2), "side": "UP"})
    if last_l is not None and px < last_l:
        events.append({"type": "BOS ⬇" if trend == "DOWN" else "CHOCH ⬇", "price": round(last_l, 2), "side": "DOWN"})
    return {"labels": labels[-10:], "trend": trend or "SIDE", "events": events, "last_h": last_h, "last_l": last_l}


def liquidity_engine(o, h, l, c, hi, lo, atr):
    """2. Liquidity: equal highs/lows · sweeps · supply/demand zones · FVG."""
    eq = []
    for arr, kind in ((hi, "EQH"), (lo, "EQL")):
        for a in range(len(arr) - 1):
            for b in range(a + 1, len(arr)):
                if abs(arr[a][1] - arr[b][1]) <= 0.15 * atr and arr[b][0] - arr[a][0] >= 4:
                    eq.append({"kind": kind, "price": round((arr[a][1] + arr[b][1]) / 2, 2), "i": arr[b][0]})
    eq = eq[-4:]
    sweeps = []
    n = len(c)
    for e in eq:
        for j in range(max(e["i"] + 1, n - 8), n):
            if e["kind"] == "EQH" and h[j] > e["price"] and c[j] < e["price"]:
                sweeps.append({"i": j, "price": e["price"], "side": "DOWN", "txt": "⚡ EQH sweep (sell-side trap)"})
            if e["kind"] == "EQL" and l[j] < e["price"] and c[j] > e["price"]:
                sweeps.append({"i": j, "price": e["price"], "side": "UP", "txt": "⚡ EQL sweep (buy-side trap)"})
    zones = []
    for j in range(3, n - 3):
        mv = c[j + 3] - c[j]
        if abs(mv) >= 2 * atr:
            zt = "DEMAND" if mv > 0 else "SUPPLY"
            z = {"kind": zt, "lo": round(float(min(o[j], c[j], l[j])), 2), "hi": round(float(max(o[j], c[j], h[j])), 2), "i": j}
            fut = l[j + 4:] if zt == "DEMAND" else h[j + 4:]
            mitig = bool(len(fut)) and ((fut.min() < z["lo"]) if zt == "DEMAND" else (fut.max() > z["hi"]))
            if not mitig:
                zones.append(z)
    zones = [z for z in zones if z["kind"] == "DEMAND"][-2:] + [z for z in zones if z["kind"] == "SUPPLY"][-2:]
    fvg = []
    for j in range(2, n):
        if l[j] > h[j - 2] and (l[j] - h[j - 2]) > 0.2 * atr:
            if l[j + 1:].min() > h[j - 2] if j + 1 < n else True:
                fvg.append({"kind": "BULL FVG", "lo": round(float(h[j - 2]), 2), "hi": round(float(l[j]), 2), "i": j})
        if h[j] < l[j - 2] and (l[j - 2] - h[j]) > 0.2 * atr:
            if h[j + 1:].max() < l[j - 2] if j + 1 < n else True:
                fvg.append({"kind": "BEAR FVG", "lo": round(float(h[j]), 2), "hi": round(float(l[j - 2]), 2), "i": j})
    return {"eq": eq, "sweeps": sweeps[-2:], "zones": zones, "fvg": fvg[-3:]}


def fib_engine(h, l, look=60):
    hh, ll = h[-look:], l[-look:]
    ih, il = int(hh.argmax()), int(ll.argmin())
    top, bot = float(hh.max()), float(ll.min())
    up = il < ih                       # low முதல் வந்து high → up leg
    rng = top - bot or 1
    lv = {}
    for r in (0.382, 0.5, 0.618, 0.786):
        lv[f"{r}"] = round(top - rng * r if up else bot + rng * r, 2)
    for r in (1.272, 1.618):
        lv[f"{r}"] = round(bot + rng * r if up else top - rng * r, 2)
    return {"leg": "UP" if up else "DOWN", "top": round(top, 2), "bot": round(bot, 2), "levels": lv}


def candle_engine(o, h, l, c, atr):
    out = []
    b1, b0 = c[-2] - o[-2], c[-1] - o[-1]
    rng = h[-1] - l[-1] or 1e-9
    body = abs(b0)
    up_w, dn_w = h[-1] - max(o[-1], c[-1]), min(o[-1], c[-1]) - l[-1]
    if b1 < 0 < b0 and c[-1] > o[-2] and o[-1] <= c[-2]:
        out.append(("Bullish engulfing", "UP"))
    if b1 > 0 > b0 and c[-1] < o[-2] and o[-1] >= c[-2]:
        out.append(("Bearish engulfing", "DOWN"))
    if dn_w >= 2 * body and up_w <= body and rng > 0.5 * atr:
        out.append(("Hammer", "UP"))
    if up_w >= 2 * body and dn_w <= body and rng > 0.5 * atr:
        out.append(("Shooting star", "DOWN"))
    if body <= 0.1 * rng:
        out.append(("Doji (indecision)", None))
    if len(c) >= 3 and c[-3] < o[-3] and abs(c[-2] - o[-2]) < 0.3 * abs(c[-3] - o[-3]) and b0 > 0 and c[-1] > (o[-3] + c[-3]) / 2:
        out.append(("Morning star", "UP"))
    if len(c) >= 3 and c[-3] > o[-3] and abs(c[-2] - o[-2]) < 0.3 * abs(c[-3] - o[-3]) and b0 < 0 and c[-1] < (o[-3] + c[-3]) / 2:
        out.append(("Evening star", "DOWN"))
    return [{"name": a, "side": b} for a, b in out]


def mtf_engine(df):
    """3. Multi-timeframe: 5m · 15m · 1H · 4H trend (EMA20 vs EMA50 + price)."""
    out = {}
    for lab, rule in (("5m", None), ("15m", "15min"), ("1H", "60min"), ("4H", "240min")):
        d = df if rule is None else df.resample(rule, origin="start").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        cl = d["close"]
        if len(cl) < 8:
            out[lab] = "?"
            continue
        e20 = cl.ewm(span=min(20, len(cl) - 1), adjust=False).mean().iloc[-1]
        e50 = cl.ewm(span=min(50, len(cl) - 1), adjust=False).mean().iloc[-1]
        out[lab] = "UP" if cl.iloc[-1] > e20 > e50 else "DOWN" if cl.iloc[-1] < e20 < e50 else "SIDE"
    vals = [v for v in out.values() if v in ("UP", "DOWN")]
    align = vals[0] if vals and all(v == vals[0] for v in vals) and len(vals) >= 3 else None
    return {"tf": out, "aligned": align}


def smart_entry(a, st, lq, mtf, cdl, fib, px, atr, vol_x):
    """4. Smart Entry: confluence score + entry / SL / T1-T3 (underlying)."""
    votes = {"UP": 0, "DOWN": 0}
    why = []

    def v(side, w, t):
        if side in votes:
            votes[side] += w
            why.append(("⬆ " if side == "UP" else "⬇ ") + t)
    if mtf["aligned"]:
        v(mtf["aligned"], 25, f"MTF aligned ({'/'.join(k for k in mtf['tf'])})")
    if st["trend"] in ("UP", "DOWN"):
        v(st["trend"], 10, f"Structure {st['trend']} (HH/HL / LH/LL)")
    for e in st["events"]:
        v(e["side"], 15, f"{e['type']} @ {e['price']}")
    for s_ in lq["sweeps"]:
        v(s_["side"], 10, s_["txt"])
    if a.get("bias"):
        v(a["bias"], 15, f"Pattern {a['pattern']}")
    for cd in cdl:
        if cd["side"]:
            v(cd["side"], 8, cd["name"])
    for z in lq["zones"]:
        if z["lo"] - 0.3 * atr <= px <= z["hi"] + 0.3 * atr:
            v("UP" if z["kind"] == "DEMAND" else "DOWN", 7, f"{z['kind']} zone {z['lo']}–{z['hi']}")
    if vol_x >= 1.5:
        lead = max(votes, key=votes.get)
        v(lead, 10, f"Volume {vol_x}× confirm")
    side = max(votes, key=votes.get)
    score = int(min(100, votes[side] - 0.5 * votes["DOWN" if side == "UP" else "UP"]))
    up = side == "UP"
    entry = a["up_level"] if up else a["dn_level"]
    if (up and (entry < px - 0.5 * atr or entry > px + 2 * atr)) or (not up and (entry > px + 0.5 * atr or entry < px - 2 * atr)):
        entry = px + (0.1 * atr if up else -0.1 * atr)        # level ஏற்கனவே தாண்டியாச்சு / ரொம்ப தூரம் → இப்போ price அருகில்
    sl = (st["last_l"] if up else st["last_h"]) or (entry - 1.2 * atr if up else entry + 1.2 * atr)
    if (up and sl >= entry) or (not up and sl <= entry):
        sl = entry - 1.2 * atr if up else entry + 1.2 * atr
    r = abs(entry - sl)
    fl = fib["levels"]
    t = [round(entry + k * r if up else entry - k * r, 2) for k in (1, 2, 3)]
    if fib["leg"] == ("UP" if up else "DOWN"):
        t[2] = fl.get("1.618", t[2]) if (fl.get("1.618", 0) > entry if up else fl.get("1.618", 1e12) < entry) else t[2]
    return {"side": side, "opt_side": "CE" if up else "PE", "score": max(0, score), "entry": round(entry, 2), "sl": round(float(sl), 2),
            "targets": t, "rr": round(abs(t[1] - entry) / r, 2) if r else None, "why": why[:8],
            "grade": "A" if score >= 75 else "B" if score >= 55 else "C"}


def _underlying(inst, c):
    s = c["symbol"]
    if s in INDEX_SPOT:
        return INDEX_SPOT[s]
    if c.get("exch") == "MCX":
        f = (inst.get("mcx_fut") or {}).get(s)
        return ("MCX", f[0]) if f else None
    t = (inst.get("eq") or {}).get(s)
    return ("NSE", t) if t else None


def pick_top2(calls, day):
    op = [c for c in calls if c["date"] == day and c["status"] in ("OPEN", "T1 HIT", "T2 HIT") and not c.get("shadow") and c["kind"] != "PICK"]
    op.sort(key=lambda c: (c.get("grade") == "A", c.get("ai_p") or 0, str(c.get("signal_time") or "")), reverse=True)
    seen, out = set(), []
    for c in op:
        if c["symbol"] in seen:
            continue
        seen.add(c["symbol"])
        out.append(c)
        if len(out) == 2:
            break
    return out


def track(preds, sym, df, now):
    """Active prediction-ஐ update: break · target · fail · expire."""
    p = preds.get(sym)
    if not p or p["status"] in ("TARGET ✓", "FAILED", "NO BREAK"):
        return
    c = float(df["close"].iloc[-1])
    hi, lo = float(df["high"].iloc[-1]), float(df["low"].iloc[-1])
    t = now.strftime("%H:%M")
    if p["status"] == "WATCH":
        if c > p["up_level"]:
            p.update(status="BROKE UP", break_time=t, break_px=round(c, 2), correct=(p["bias"] == "UP") if p["bias"] else None)
        elif c < p["dn_level"]:
            p.update(status="BROKE DOWN", break_time=t, break_px=round(c, 2), correct=(p["bias"] == "DOWN") if p["bias"] else None)
        elif (now - pd.Timestamp(p["time_full"])).total_seconds() > 3 * 3600:
            p.update(status="NO BREAK", end_time=t)
    elif p["status"] == "BROKE UP":
        if hi >= p["up_target"]:
            p.update(status="TARGET ✓", end_time=t, end_px=round(hi, 2))
        elif c < p["dn_level"] or c < p["up_level"] - p["atr"]:
            p.update(status="FAILED", end_time=t, end_px=round(c, 2))
    elif p["status"] == "BROKE DOWN":
        if lo <= p["dn_target"]:
            p.update(status="TARGET ✓", end_time=t, end_px=round(lo, 2))
        elif c > p["up_level"] or c > p["dn_level"] + p["atr"]:
            p.update(status="FAILED", end_time=t, end_px=round(c, 2))


def advice(a, side):
    """Chart pattern vs call side → எடுக்கலாமா?"""
    want = "UP" if side == "CE" else "DOWN"
    lvl = a["up_level"] if side == "CE" else a["dn_level"]
    tgt = a["up_target"] if side == "CE" else a["dn_target"]
    if a.get("bias") == want:
        return {"verdict": "TAKE", "text": f"✅ எடுக்கலாம் — {a['pattern']} {('⬆' if want == 'UP' else '⬇')} bias. Underlying {lvl} {'மேல்' if side == 'CE' else 'கீழ்'} 5-min close ஆனதும் entry · target {tgt}."}
    if a.get("bias") and a["bias"] != want:
        return {"verdict": "AVOID", "text": f"⛔ வேண்டாம் / wait — chart {a['pattern']} {('⬆' if a['bias'] == 'UP' else '⬇')} எதிர் பக்கம். {lvl} {'மேல்' if side == 'CE' else 'கீழ்'} clear break ஆனா மட்டும் பாருங்க."}
    return {"verdict": "WAIT", "text": f"⏳ Pattern தெளிவில்லை — {lvl} {'மேல்' if side == 'CE' else 'கீழ்'} break-க்கு காத்திருங்க."}


def run_once(ag, inst, store, now, extra=None, indices=None):
    day = str(now.date())
    d = store.load()
    P = d.setdefault("chart_preds", {})
    hist = d.setdefault("chart_hist", [])
    isy = {x["symbol"] for x in indices or []}
    top = list(indices or []) + [c for c in pick_top2([c for c in (d.get("calls") or {}).values() if c["symbol"] not in isy], day)]
    n_idx = len(indices or [])
    for x in extra or []:                     # open calls 2-க்கு குறைவுன்னா — Money Machine / Strong / Movers top setups
        if len(top) >= n_idx + 2:
            break
        if x.get("symbol") and x["symbol"] not in {c["symbol"] for c in top}:
            top.append(x)
    charts = []
    for c in top:
        u = _underlying(inst, c)
        if not u:
            continue
        try:
            df = ag.candles(u[0], u[1], "FIVE_MINUTE", now - pd.Timedelta(days=4), now)
            df = df[df.index + pd.Timedelta(minutes=5) <= now] if df is not None and not df.empty else df
        except Exception as e:
            STATE["err"] = str(e)[:120]
            continue
        if df is None or len(df) < 30:
            continue
        a = analyse(df)
        if c.get("is_index"):
            c["side"] = a["smart"]["opt_side"]
            o_ = (c.get("chain_opts") or {}).get(c["side"])
            if o_:
                c.update(strike=o_["strike"], entry=o_["entry"], sl=o_["sl"], targets=o_["targets"], ltp=o_["ltp"], token=o_["token"],
                         exch=o_["exch"], contract=o_["contract"], lot=o_["lot"], expiry=o_["expiry"])
        a["advice"] = advice(a, c.get("side") or "CE")
        if c.get("is_index") and c.get("token") and a["smart"]["score"] >= 75 and a["advice"]["verdict"] == "TAKE":
            try:
                from .calls import add_simple
                add_simple("CHART", "📈 Chart Room", [{"symbol": c["symbol"], "side": c["side"], "price": a["px"], "sl": a["smart"]["sl"], "score": a["smart"]["score"],
                                                     "stars": 5, "reasons": [f"📈 {a['pattern']} · smart {a['smart']['score']}"] + a["smart"]["why"][:5],
                                                     "option": {"token": c["token"], "exch": c["exch"], "contract": c["contract"], "strike": c["strike"],
                                                                "type": c["side"], "expiry": c["expiry"], "lot": c["lot"],
                                                                "plan": {"entry": c["entry"], "sl": c["sl"], "targets": c["targets"], "risk": 0,
                                                                         "risk_ok": True, "money": True, "reward_ok": True}}}], now, 4)
            except Exception as e:
                STATE["err"] = f"chart call: {e}"[:120]
        key = f"{day}|{c['symbol']}"
        track(P, key, df, now)
        cur = P.get(key)
        if not cur or cur["status"] in ("TARGET ✓", "FAILED", "NO BREAK"):
            if cur:
                hist.append(cur)
            P[key] = {"symbol": c["symbol"], "date": day, "time": now.strftime("%H:%M"), "time_full": str(now), "pattern": a["pattern"],
                      "bias": a["bias"], "up_level": a["up_level"], "dn_level": a["dn_level"], "up_target": a["up_target"],
                      "dn_target": a["dn_target"], "atr": a["atr"], "status": "WATCH", "px": a["px"], "call": f"{c['symbol']} {c.get('strike') or ''} {c.get('side')}",
                      "call_id": c.get("id"), "side": c.get("side"), "verdict": a["advice"]["verdict"], "smart": a["smart"]["score"],
                      "smart_side": a["smart"]["side"], "mtf": a["mtf"]["aligned"],
                      "opt": {k: c.get(k) for k in ("entry", "sl", "targets")}}
        tail = df.tail(80)
        charts.append({"is_index": bool(c.get("is_index")),
                       "call": {k: c.get(k) for k in ("id", "symbol", "strike", "side", "entry", "sl", "targets", "ltp", "status", "source", "time",
                                                       "expiry", "lot", "pnl_lot", "token", "exch", "contract")},
                       "candles": [[str(i)[11:16], round(float(r.open), 2), round(float(r.high), 2), round(float(r.low), 2), round(float(r.close), 2), float(r.volume)]
                                   for i, r in tail.iterrows()],
                       "offset": len(df) - len(tail), "analysis": a, "pred": P.get(key)})
    for k in [k for k in P if not k.startswith(day)]:
        hist.append(P.pop(k))
    del hist[:-300]
    store.dirty = True
    allp = hist + list(P.values())
    res_ = [p for p in allp if p["status"] in ("TARGET ✓", "FAILED", "BROKE UP", "BROKE DOWN")]
    dirk = [p for p in res_ if p.get("correct") is not None]
    acc = {"total": len(allp), "broke": len(res_), "dir_ok": sum(1 for p in dirk if p["correct"]), "dir_n": len(dirk),
           "target": sum(1 for p in allp if p["status"] == "TARGET ✓"), "failed": sum(1 for p in allp if p["status"] == "FAILED"),
           "nobreak": sum(1 for p in allp if p["status"] == "NO BREAK")}
    by = {}
    for p in allp:
        b = by.setdefault(p["pattern"], {"n": 0, "target": 0, "failed": 0, "dir_ok": 0, "dir_n": 0})
        b["n"] += 1
        b["target"] += p["status"] == "TARGET ✓"
        b["failed"] += p["status"] == "FAILED"
        if p.get("correct") is not None:
            b["dir_n"] += 1
            b["dir_ok"] += bool(p["correct"])
    bysym = {}
    for p in allp:
        b = bysym.setdefault(p["symbol"], {"n": 0, "target": 0, "failed": 0, "dir_ok": 0, "dir_n": 0})
        b["n"] += 1
        b["target"] += p["status"] == "TARGET ✓"
        b["failed"] += p["status"] == "FAILED"
        if p.get("correct") is not None:
            b["dir_n"] += 1
            b["dir_ok"] += bool(p["correct"])
    STATE.update(time=now.strftime("%H:%M:%S"), charts=charts, acc=acc, by_pattern=by, by_symbol=bysym,
                 preds=sorted(allp, key=lambda p: p.get("time_full", ""), reverse=True)[:60], err=None)
    return STATE
