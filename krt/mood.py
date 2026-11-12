"""🌡 MARKET MOOD — 0-100 gauge for NIFTY · BANKNIFTY · FINNIFTY · SENSEX · Overall · MCX, built from REAL market data
(not social posts — X/Twitter has no free API): price move · 15-min momentum · breadth · option OI bias / PCR · futures buyers vs sellers
(footprint delta) · news bias · India VIX. A component with no data is skipped (never faked). 0-20 very bearish · 20-40 bearish ·
40-60 neutral · 60-80 bullish · 80-100 very bullish. Also sector mood and the best calls with buyer interest.
"""
NAMES = ["Overall", "NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "CRUDEOIL", "GOLD", "SILVER", "NATURALGAS"]
MCX = ("CRUDEOIL", "GOLD", "SILVER", "NATURALGAS")
W = {"price": 25, "momentum": 20, "breadth": 15, "oi": 15, "flow": 15, "news": 10, "vix": 10}
H = {}                    # name → [(ts, price)] for momentum
STATE = {"time": None, "idx": {}, "sectors": [], "calls": []}


def _clip(x):
    return max(-1.0, min(1.0, x))


def label(s):
    return "Very bearish" if s < 20 else "Bearish" if s < 40 else "Neutral" if s < 60 else "Bullish" if s < 80 else "Very bullish"


def _push(name, ts, px):
    L = H.setdefault(name, [])
    L.append((ts, px))
    while L and (ts - L[0][0]).total_seconds() > 40 * 60:
        L.pop(0)


def _chg(name, now, mins=15):
    L = H.get(name) or []
    old = next((v for t, v in reversed(L) if (now - t).total_seconds() >= mins * 60), None)
    return (L[-1][1] / old - 1) * 100 if L and old else None


def score(parts):
    """parts: {name: value -1..+1 or None} → (0-100, bull/neutral/bear weight shares, used parts)."""
    use = {k: v for k, v in parts.items() if v is not None}
    if not use:
        return None, {}, {}
    tw = sum(W[k] for k in use)
    s = 50 + 50 * sum(W[k] * v for k, v in use.items()) / tw
    br = {"bull": round(sum(W[k] for k, v in use.items() if v > 0.15) / tw * 100), "bear": round(sum(W[k] for k, v in use.items() if v < -0.15) / tw * 100)}
    br["neutral"] = 100 - br["bull"] - br["bear"]
    return round(s, 1), br, use


def _oi(x):
    b = str((x or {}).get("bias") or "")
    v = 0.6 if "BULL" in b else -0.6 if "BEAR" in b else 0.0 if b else None
    pcr = (x or {}).get("pcr")
    if pcr:
        v = _clip((v or 0) + _clip((float(pcr) - 1.0) / 0.5) * 0.4)
    return v


def _news(row):
    if not row:
        return None
    k = {"CONFIRMED": 1.0, "BIAS": 0.6, "CONFLICT": 0.2, "WEAK": 0.2}.get(row.get("status"), 0.3)
    return k if row.get("side") == "CE" else -k


def update(now, ticks, risk=None, idx_rows=None, fp_bars=None, news=None, money=None, hist=None):
    """Every minute. ticks = TICK['items'] · risk = breadth · idx_rows = index OI rows · fp_bars = footprint view · news = news radar focus ·
    money = money machine (sectors, OI trend) · hist = STORE mood history {date: {name: [[HH:MM, score]]}}."""
    day, hm = str(now.date()), now.strftime("%H:%M")
    for n, t in (ticks or {}).items():
        if (t or {}).get("ltp"):
            _push(n, now, float(t["ltp"]))
    risk = risk or {}
    breadth = _clip(((risk.get("up") or 0) - (risk.get("dn") or 0)) / 50) if risk.get("up") is not None else None
    vix_t = (ticks or {}).get("INDIA VIX") or {}
    vix = _clip(-float(vix_t["pct"]) / 5) if vix_t.get("pct") is not None else None
    ix = {x.get("index"): x for x in idx_rows or []}
    nw = {r["symbol"]: r for r in news or [] if r.get("index")}
    out = {}
    for n in NAMES[1:]:
        t = (ticks or {}).get(n) or {}
        mcx = n in MCX
        mom = _chg(n, now)
        fp = ((fp_bars or {}).get(n) or {}).get(1) or {}
        flow = _clip((fp.get("an") or {}).get("delta_pct", 0) / 60) if fp.get("an") else None
        parts = {"price": _clip(float(t["pct"]) / 1.0) if t.get("pct") is not None else None, "momentum": _clip(mom / 0.4) if mom is not None else None,
                 "breadth": None if mcx else breadth, "oi": None if mcx else _oi(ix.get(n)), "flow": flow,
                 "news": None if mcx else _news(nw.get(n)), "vix": None}
        if parts["price"] is None and parts["momentum"] is None:
            continue                                   # no own price data → no gauge (market-wide breadth alone must not fake one)
        out[n] = parts
    nse = [out[k] for k in ("NIFTY", "BANKNIFTY", "SENSEX") if out.get(k)]
    agg = {}
    for k in W:
        vals = [p[k] for p in nse if p.get(k) is not None]
        agg[k] = sum(vals) / len(vals) if vals else None
    agg["breadth"] = breadth
    agg["vix"] = vix
    ot = (money or {}).get("oi") or {}
    if ot.get("bull_pct") is not None:
        agg["oi"] = _clip(((agg.get("oi") or 0) + (ot["bull_pct"] - 50) / 50) / 2)
    out["Overall"] = agg
    H_ = hist if hist is not None else {}
    HD = H_.setdefault(day, {})
    res = {}
    for n in NAMES:
        s, br, use = score(out.get(n) or {})
        if s is None:
            continue
        L = HD.setdefault(n, [])
        prev = L[-1][1] if L else None
        if not L or L[-1][0][:4] != hm[:4]:                      # one point per 10 minutes
            L.append([hm, s])
        else:
            L[-1] = [hm, s]
        hours = {}
        for h, v in L:
            hours.setdefault(h[:2], []).append(v)
        hr = {h: round(sum(v) / len(v)) for h, v in hours.items()}
        peak = max(hr.items(), key=lambda x: x[1]) if hr else None
        low = min(hr.items(), key=lambda x: x[1]) if hr else None
        day_avg = round(sum(v for _, v in L) / len(L), 1)
        lab = label(s)
        if peak and low and peak[0] != low[0]:
            say = (f"Mood was most bullish around {_h12(peak[0])} ({peak[1]}) and most bearish around {_h12(low[0])} ({low[1]}); "
                   f"it is {lab.lower()} at {round(s)} now.")
        else:
            say = f"Mood is {lab.lower()} at {round(s)} now — " + ("only a few data points so far today." if len(L) < 4 else "steady all day.")
        res[n] = {"score": s, "label": lab, "vs_last": None if prev is None else round(s - prev, 1), "day_avg": day_avg, "breakdown": br,
                  "parts": {k: round(v * 100) for k, v in use.items()}, "signals": len(use), "hours": hr, "say": say,
                  "price": ((ticks or {}).get(n) or {}).get("ltp"), "pct": ((ticks or {}).get(n) or {}).get("pct")}
    for d in sorted(H_)[:-5]:
        H_.pop(d, None)
    secs = []
    for x in (money or {}).get("sectors") or []:
        n_ = x.get("n") or 0
        v = _clip(0.6 * _clip(float(x.get("pct") or 0) / 1.5) + 0.4 * (((x.get("up") or 0) / n_ * 2 - 1) if n_ else 0))
        s = round(50 + 50 * v, 1)
        secs.append({"sector": x["sector"], "score": s, "label": label(s), "pct": x.get("pct"), "up": x.get("up"), "n": n_})
    secs.sort(key=lambda r: -r["score"])
    STATE.update(time=now.strftime("%I:%M %p"), idx=res, sectors=secs or STATE.get("sectors") or [])     # keep last sectors while a scan is running
    return res


def _h12(h):
    h = int(h)
    return f"{(h - 1) % 12 + 1} {'AM' if h < 12 else 'PM'}"


def best_calls(brain_rows, calls, guides, money_rows, hist_fn, n=6):
    """Best open calls (Brain order) + buyer interest + how far targets are + past T1 reach."""
    oi = {r.get("symbol"): r.get("oi") for r in money_rows or []}
    out = []
    for r in [x for x in brain_rows or [] if x.get("decision") in ("TAKE", "WATCH")][:n]:
        c = calls.get(r["id"]) or {}
        g = guides.get(c.get("symbol")) or {}
        ltp = float(c.get("ltp") or 0)
        tg = c.get("targets") or []
        buyers = []
        if g.get("flow"):
            buyers.append(g["flow"])
        if c.get("vol_ratio"):
            buyers.append(f"volume {float(c['vol_ratio']):.1f}× normal")
        if oi.get(c.get("symbol")):
            buyers.append(f"OI: {oi[c['symbol']]}")
        h = hist_fn(c.get("symbol"), c.get("side"), c.get("strike")) or {}
        a = h.get("all") or {}
        out.append({"id": r["id"], "symbol": c.get("symbol"), "strike": c.get("strike"), "side": c.get("side"), "decision": r["decision"], "score": r.get("score"),
                    "entry": c.get("entry"), "sl": c.get("sl"), "ltp": ltp, "targets": tg,
                    "to_targets": [round((t / ltp - 1) * 100, 1) if ltp else None for t in tg], "buyers": buyers,
                    "t1_rate": round(a["t1"] / a["n"] * 100) if a.get("n") else None, "t1_n": a.get("n", 0), "say": r.get("say")})
    STATE["calls"] = out
    return out
