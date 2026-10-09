"""GAMMA-UNWIND scanner — order போடாது, alert + paper tracking மட்டும்.
1) Selection (09:20 & 13:15): F&O stocks, daily Supply/Demand zones (10-bar pivots, ATR(50) width).
   Price zone edge-க்கு 2.5%-க்குள் → Resistance: BREAKOUT-CE, Support: BREAKDOWN-PE.
   Expiry 7 trading days-க்குள் → current month (EXPIRY-*) + next month.
   Strikes: edge-ல் இருந்து 2.5%-க்குள் OTM, highest OI top 2 (HOI-1/2), OI ≥ 50 lots, turnover ≥ ₹1 lakh.
2) Live (option 5-min candles + 5-min OI): A OI unwind ≥7% from day peak · B volume build (3-ல் 2 bars > 20-bar avg)
   · C 6-bar range ≤ ATR(14) · H no dead bars → ARMED.
   Trigger: consolidation high volume-உடன் break, அல்லது low-க்கு கீழ் போய் mid-க்கு மேல் close (shakeout). SL = consolidation low.
3) Tier (Zone, Liquidity, Direction VWAP/30-min drift, Premium/unwind): 4/4 ENTRY · 3/4 STRONG WATCHLIST · ≤2 WATCHLIST.
Backtest / win-rate இல்லை — paper trade செய்து பாருங்க."""
import numpy as np
import pandas as pd
from .instruments import ist_today
from .telegram import send as tg

ST = {"day": None, "sel": {}, "watch": [], "contracts": [], "signals": {}, "last": None, "err": None}
APPROACH, OI_UNWIND = 2.5, 7.0


def _atr(h, l, c, n):
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(tr[-n:].mean()) if len(tr) >= n else float(tr.mean())


def zones(bars):
    """Volatility Supply/Demand zones (port): 10-bar pivot high/low, width = ATR(50). Unbroken zones மட்டும்."""
    h, l, c = (np.array(bars[k], float) for k in ("h", "l", "c"))
    n = len(c)
    if n < 40:
        return None, None, 0
    atr = _atr(h, l, c, 50)
    sup, dem = [], []
    for i in range(10, n - 10):
        if h[i] == h[i - 10:i + 11].max():
            top, bot = h[i], h[i] - atr
            if not (c[i + 1:] > top).any():          # உடையாத supply
                sup.append((bot, top, bars["t"][i]))
        if l[i] == l[i - 10:i + 11].min():
            bot, top = l[i], l[i] + atr
            if not (c[i + 1:] < bot).any():          # உடையாத demand
                dem.append((bot, top, bars["t"][i]))
    last = c[-1]
    s = min([z for z in sup if z[0] >= last * 0.97] or [None], key=lambda z: z[0] if z else 0) if sup else None
    d = max([z for z in dem if z[1] <= last * 1.03] or [None], key=lambda z: z[1] if z else 0) if dem else None
    return s, d, atr


def _tdays(a, b):
    return max(0, len(pd.bdate_range(a, b)) - 1)


def select(ag, inst, C, ltp_of, contracts, now):
    """Approaching stocks + HOI strikes."""
    today = ist_today()
    watch, cand = [], []
    for n, bars in (C.get("bars") or {}).items():
        ltp = ltp_of.get(n)
        if not ltp:
            continue
        s, d, atr = zones(bars)
        for side, z in (("CE", s), ("PE", d)):
            if not z:
                continue
            edge = z[0] if side == "CE" else z[1]
            dist = (edge - ltp) / ltp * 100 if side == "CE" else (ltp - edge) / ltp * 100
            if dist > APPROACH or (side == "CE" and ltp > z[1]) or (side == "PE" and ltp < z[0]):
                continue
            cand.append({"symbol": n, "side": side, "setup": "BREAKOUT-CE" if side == "CE" else "BREAKDOWN-PE",
                         "zone": [round(float(z[0]), 2), round(float(z[1]), 2)], "zone_date": z[2],
                         "edge": round(float(edge), 2), "dist": round(float(dist), 2), "ltp": float(ltp)})
    cand.sort(key=lambda x: abs(x["dist"]))
    cand = cand[:20]
    rows = inst["opts"]
    want = []
    for w in cand:
        allc = [r for r in rows.get(w["symbol"], []) if r[4] == w["side"]]
        exps = sorted({r[2] for r in allc})
        if not exps:
            continue
        td = _tdays(today, pd.Timestamp(exps[0]).date())
        use = exps[:2] if td <= 7 else exps[:1]
        w["expiry_days"] = td
        w["expiries"] = use
        for e in use:
            tag = ("EXPIRY-" + w["side"]) if (e == exps[0] and td <= 7) else w["setup"]
            for r in allc:
                if r[2] != e:
                    continue
                k = r[3]
                otm = k > w["ltp"] if w["side"] == "CE" else k < w["ltp"]
                if otm and abs(k - w["edge"]) / w["edge"] * 100 <= APPROACH:
                    want.append((w, tag, r))
        watch.append(w)
    toks = {}
    for _, _, r in want:
        toks.setdefault(r[6], []).append(r[0])
    qs = ag.quotes(toks) if toks else {}
    by = {}
    for w, tag, r in want:
        q = qs.get(r[0]) or {}
        oi = float(q.get("opnInterest") or 0)
        lot = r[5] or 1
        turnover = float(q.get("tradeVolume") or 0) * float(q.get("avgPrice") or q.get("ltp") or 0)
        if oi < 50 * lot or turnover < 1e5:
            continue
        by.setdefault((w["symbol"], w["side"], r[2]), []).append(
            {"symbol": w["symbol"], "side": w["side"], "tag": tag, "token": r[0], "exch": r[6], "contract": r[1],
             "strike": r[3], "expiry": r[2], "lot": lot, "oi": int(oi), "turnover": round(turnover),
             "zone": w["zone"], "edge": w["edge"], "ul_token": inst["eq"].get(w["symbol"])})
    cons = []
    for k, lst in by.items():
        lst.sort(key=lambda x: -x["oi"])
        for i, x in enumerate(lst[:2]):
            x["hoi"] = f"HOI-{i+1}"
            cons.append(x)
    return watch, cons


def _oi_series(ag, c, start, end):
    p = {"exchange": c["exch"], "symboltoken": c["token"], "interval": "FIVE_MINUTE",
         "fromdate": start.strftime("%Y-%m-%d %H:%M"), "todate": end.strftime("%Y-%m-%d %H:%M")}
    try:
        res = ag._call(lambda: ag.api.getOIData(p))
        return [float(x.get("oi") or 0) for x in (res.get("data") or [])]
    except Exception:
        return []


def evaluate(ag, c, now, ul):
    """ஒரு option contract-க்கு A/B/C/H + trigger + tier."""
    t0 = now.normalize() + pd.Timedelta(hours=9, minutes=15)
    df = ag.candles(c["exch"], c["token"], "FIVE_MINUTE", t0, now)
    if not df.empty:
        df = df[df.index + pd.Timedelta(minutes=5) <= now]   # completed bars மட்டும்
    out = {"A": False, "B": False, "C": False, "H": False, "armed": False, "trigger": None}
    if len(df) < 8:
        out["note"] = "போதுமான 5-min bars இல்லை"
        return out
    oi = _oi_series(ag, c, t0, now)
    if oi:
        peak, cur = max(oi), oi[-1]
        out["oi_peak"], out["oi_now"] = int(peak), int(cur)
        out["oi_drop"] = round((peak - cur) / peak * 100, 1) if peak else 0
        out["A"] = out["oi_drop"] >= OI_UNWIND
    v = df["volume"].values
    avg20 = v[-21:-1].mean() if len(v) > 21 else v[:-1].mean()
    out["B"] = int((v[-3:] > avg20).sum()) >= 2
    h, l, cl = df["high"].values, df["low"].values, df["close"].values
    base_h, base_l = h[-7:-1].max(), l[-7:-1].min()
    atr14 = _atr(h, l, cl, 14)
    # Consolidation: trigger bar-க்கு முந்தைய 6 bars range ≤ ATR(14)
    out["C"] = bool((h[-7:-1].max() - l[-7:-1].min()) <= atr14) if atr14 else False
    out["H"] = bool((v[-7:] > 0).all() and avg20 > 0)
    out["A"], out["B"] = bool(out["A"]), bool(out["B"])
    out["armed"] = out["A"] and out["B"] and out["C"] and out["H"]
    out.update(cons_high=round(float(base_h), 2), cons_low=round(float(base_l), 2), ltp=round(float(cl[-1]), 2))
    mid = (base_h + base_l) / 2
    if cl[-1] > base_h and v[-1] > avg20:
        out["trigger"] = "BREAKOUT"
    elif l[-1] < base_l and cl[-1] > mid:
        out["trigger"] = "SHAKEOUT"
    # Tier checks
    ce = c["side"] == "CE"
    zone_ok = ul.get("ltp") and (abs(ul["ltp"] - c["edge"]) / c["edge"] * 100 <= APPROACH)
    liq_ok = c["oi"] >= 50 * c["lot"] and c["turnover"] >= 1e5
    dir_ok = False
    if ul.get("vwap") and ul.get("ltp"):
        dir_ok = (ul["ltp"] > ul["vwap"] or ul.get("drift30", 0) > 0) if ce else (ul["ltp"] < ul["vwap"] or ul.get("drift30", 0) < 0)
    prem_ok = out["A"]
    out["checks"] = {"Zone": bool(zone_ok), "Liquidity": bool(liq_ok), "Direction": bool(dir_ok), "Premium/Unwind": bool(prem_ok)}
    n = sum(out["checks"].values())
    out["score"] = n
    out["tier"] = "ENTRY" if n == 4 else "STRONG WATCHLIST" if n == 3 else "WATCHLIST"
    return out


def stock_ctx(ag, sym, token, now):
    t0 = now.normalize() + pd.Timedelta(hours=9, minutes=15)
    df = ag.candles("NSE", token, "FIVE_MINUTE", t0, now)
    if df.empty:
        return {}
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vwap = float((tp * df["volume"]).sum() / max(df["volume"].sum(), 1))
    ltp = float(df["close"].iloc[-1])
    drift = float(df["close"].iloc[-1] - df["close"].iloc[-7]) if len(df) > 7 else 0.0
    return {"vwap": round(vwap, 2), "ltp": ltp, "drift30": round(drift, 2)}


def run(ag, inst, C, ltp_of, contracts, now, max_contracts=24):
    day = str(now.date())
    mins = now.hour * 60 + now.minute
    if ST["day"] != day:
        ST.update(day=day, sel={}, watch=[], contracts=[], signals={})
    slot = "13:15" if mins >= 13 * 60 + 15 else "09:20" if mins >= 9 * 60 + 20 else None
    if slot and slot not in ST["sel"]:
        w, cons = select(ag, inst, C, ltp_of, contracts, now)
        ST["sel"][slot] = now.strftime("%H:%M")
        ST["watch"] = w
        keep = {x["contract"]: x for x in ST["contracts"]}
        for x in cons:
            keep.setdefault(x["contract"], x)
        ST["contracts"] = list(keep.values())
    ctx = {}
    for c in ST["contracts"][:max_contracts]:
        if c["symbol"] not in ctx and c.get("ul_token"):
            ctx[c["symbol"]] = stock_ctx(ag, c["symbol"], c["ul_token"], now)
        try:
            c["eval"] = evaluate(ag, c, now, ctx.get(c["symbol"], {}))
        except Exception as e:
            c["eval"] = {"note": str(e)}
        ev = c["eval"]
        if ev.get("armed") and ev.get("trigger"):
            key = f"{day}|{c['contract']}"
            if key not in ST["signals"]:
                e = ev["ltp"]
                ST["signals"][key] = {**{k: c[k] for k in ("symbol", "side", "tag", "hoi", "contract", "token", "exch",
                                                          "strike", "expiry", "lot", "zone", "edge", "ul_token")},
                                      "time": now.strftime("%H:%M"), "tier": ev["tier"], "score": ev["score"],
                                      "checks": ev["checks"], "trigger": ev["trigger"], "entry": e,
                                      "sl": ev["cons_low"], "targets": [round(e * 1.2, 2), round(e * 1.4, 2)],
                                      "ul_ltp": ctx.get(c["symbol"], {}).get("ltp"),
                                      "expiry_days": _tdays(now.date(), pd.Timestamp(c["expiry"]).date())}
                s = ST["signals"][key]
                if s["tier"] in ("ENTRY", "STRONG WATCHLIST"):
                    tg(f"⚡ GAMMA-UNWIND {s['tier']}\n{s['symbol']} {s['strike']} {s['side']} ({s['tag']}, {s['hoi']})\n"
                       f"Trigger: {s['trigger']} @ {s['time']}\nEntry {e} · SL {s['sl']} · T1 {s['targets'][0]} · T2 {s['targets'][1]}\n"
                       f"Zone {s['zone'][0]}–{s['zone'][1]} · Expiry {s['expiry']}\n(Paper/alert only — not advice)", key)
    ST["last"] = now.strftime("%H:%M")
    return snapshot()


def snapshot():
    return {"day": ST["day"], "selected": ST["sel"], "last": ST["last"], "watch": ST["watch"],
            "contracts": ST["contracts"], "signals": sorted(ST["signals"].values(), key=lambda s: s["time"], reverse=True)}
