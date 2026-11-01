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
    return {"pattern": pat, "bias": bias, "up_level": round(u_now, 2), "dn_level": round(l_now, 2), "up_target": up_t, "dn_target": dn_t,
            "height": round(height, 2), "atr": round(atr, 2), "px": round(px, 2), "text": txt, "why": why,
            "lines": {"upper": [U[0], U[1]] if U else None, "lower": [L[0], L[1]] if L else None},
            "sr_up": up_lv, "sr_dn": dn_lv, "vwap": [None if np.isnan(x) else round(float(x), 2) for x in vw.values],
            "ema20": [round(float(x), 2) for x in ema20], "vol_x": round(vx, 2)}


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


def run_once(ag, inst, store, now):
    day = str(now.date())
    d = store.load()
    P = d.setdefault("chart_preds", {})
    hist = d.setdefault("chart_hist", [])
    top = pick_top2(list((d.get("calls") or {}).values()), day)
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
        key = f"{day}|{c['symbol']}"
        track(P, key, df, now)
        cur = P.get(key)
        if not cur or cur["status"] in ("TARGET ✓", "FAILED", "NO BREAK"):
            if cur:
                hist.append(cur)
            P[key] = {"symbol": c["symbol"], "date": day, "time": now.strftime("%H:%M"), "time_full": str(now), "pattern": a["pattern"],
                      "bias": a["bias"], "up_level": a["up_level"], "dn_level": a["dn_level"], "up_target": a["up_target"],
                      "dn_target": a["dn_target"], "atr": a["atr"], "status": "WATCH", "px": a["px"], "call": f"{c['symbol']} {c['strike']} {c['side']}"}
        tail = df.tail(80)
        charts.append({"call": {k: c.get(k) for k in ("id", "symbol", "strike", "side", "entry", "sl", "targets", "ltp", "status", "source", "time")},
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
    STATE.update(time=now.strftime("%H:%M:%S"), charts=charts, acc=acc, by_pattern=by,
                 preds=sorted(allp, key=lambda p: p.get("time_full", ""), reverse=True)[:60], err=None)
    return STATE
