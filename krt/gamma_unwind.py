"""🚀 GAMMA-UNWIND V3 PRO — NSE F&O stock options, alert-only (order எதுவும் போடாது).
Engine A INTRADAY + Engine B HOLDING — தனித்தனி strikes, score, SL, exit, stats.
Zone (daily S/D, 10-bar pivot, ATR50) + structure + OI unwinding (5/15/30 min, peak drop, velocity)
+ volume/consolidation (option 5-min) + underlying 15-min breakout + VWAP + regime + liquidity/greeks + risk.
Scores/thresholds = ஆரம்ப hypothesis மட்டும்; backtest செய்யப்படவில்லை. OI குறைவு = writers cover என்று நிரூபணம் இல்லை."""
import numpy as np
import pandas as pd
from .instruments import ist_today
from .optmath import greeks_from_price, r05
from .telegram import send as tg

CFG = {
    "approach_base": 2.5,        # % (configurable baseline)
    "oi_drop": 7.0,              # % from session peak
    "max_contracts": 20,
    "max_entries_day": 3,
    "stock_cooldown_min": 60,
    "sl_pause_after": 2,         # இன்று 2 SL ஆனால் புது ENTRY நிறுத்து
    "max_spread_pct": 5.0,
    "min_value": 1e5,            # ₹ traded value
    "risk_cap": 2500,
    "charges": 150,
    "stale_sec": 180,
    "armed_expiry_min": 30,
    "pro": 85, "strong": 70,
}
ENG = {
    "INTRADAY": {"targets": [0.15, 0.25, 0.40], "min_dte": 1, "kind": "GU-INTRADAY"},
    "HOLDING": {"targets": [0.20, 0.40, 0.60], "min_dte": 8, "kind": "GU-HOLDING"},
}
ST = {"day": None, "sel": {}, "zones": [], "contracts": [], "signals": {}, "armed": {}, "last": None,
      "health": {}, "regime": {}, "entries": 0, "cool": {}}


def _atr(h, l, c, n):
    if len(c) < 2:
        return 0.0
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(tr[-n:].mean())


def _tdays(a, b):
    return max(0, len(pd.bdate_range(a, b)) - 1)


def _f(x):
    try:
        return float(x)
    except Exception:
        return 0.0


def _fresh(q, now):
    t = pd.to_datetime((q or {}).get("exchFeedTime"), dayfirst=True, errors="coerce")
    if pd.isna(t):
        return False
    return abs((now - t).total_seconds()) <= CFG["stale_sec"]


# ---------------- 3. Smart supply/demand + structure
def structure(h, l, c):
    W = 5
    ph = [i for i in range(W, len(h) - W) if h[i] == h[i - W:i + W + 1].max()]
    pl = [i for i in range(W, len(l) - W) if l[i] == l[i - W:i + W + 1].min()]
    st = "SIDEWAYS"
    if len(ph) >= 2 and len(pl) >= 2:
        if h[ph[-1]] > h[ph[-2]] and l[pl[-1]] > l[pl[-2]]:
            st = "BULL"
        elif h[ph[-1]] < h[ph[-2]] and l[pl[-1]] < l[pl[-2]]:
            st = "BEAR"
    bos = choch = sweep = None
    if ph and c[-1] > h[ph[-1]]:
        bos, choch = "BOS-UP", ("CHOCH-UP" if st == "BEAR" else None)
    if pl and c[-1] < l[pl[-1]]:
        bos, choch = "BOS-DOWN", ("CHOCH-DOWN" if st == "BULL" else None)
    if ph and h[-1] > h[ph[-1]] and c[-1] < h[ph[-1]]:
        sweep = "Sweep above high"
    if pl and l[-1] < l[pl[-1]] and c[-1] > l[pl[-1]]:
        sweep = "Sweep below low"
    return {"trend": st, "bos": bos, "choch": choch, "sweep": sweep}


def zones(bars):
    """Volatility S/D zones (10-bar pivot, ATR50 width) + freshness/tests/age/displacement/creation volume → rank."""
    h, l, c, v = (np.array(bars[k], float) for k in ("h", "l", "c", "v"))
    n = len(c)
    if n < 40:
        return [], 0.0
    atr = _atr(h, l, c, 50)
    out = []
    for i in range(10, n - 10):
        for kind in ("SUPPLY", "DEMAND"):
            if kind == "SUPPLY" and h[i] == h[i - 10:i + 11].max():
                top, bot = h[i], h[i] - atr
                if (c[i + 1:] > top).any():
                    continue
                tests = int(((h[i + 11:] >= bot) & (c[i + 11:] <= top)).sum())
            elif kind == "DEMAND" and l[i] == l[i - 10:i + 11].min():
                bot, top = l[i], l[i] + atr
                if (c[i + 1:] < bot).any():
                    continue
                tests = int(((l[i + 11:] <= top) & (c[i + 11:] >= bot)).sum())
            else:
                continue
            disp = float(np.abs(np.diff(c[i:i + 6])).max()) / atr if atr else 0
            vol_at = float(v[i] / max(v[max(0, i - 20):i].mean(), 1))
            age = n - 1 - i
            fresh = 1.0 if tests == 0 else 0.7 if tests == 1 else 0.4 if tests == 2 else 0.2
            rank = 40 * fresh + 25 * min(disp / 1.5, 1) + 20 * min(vol_at / 2, 1) + 15 * (1 if age <= 60 else 0.5)
            out.append({"kind": kind, "bot": round(float(bot), 2), "top": round(float(top), 2), "date": bars["t"][i],
                        "tests": tests, "age": age, "displacement": round(disp, 2), "vol_at": round(vol_at, 2),
                        "rank": int(rank)})
    return out, atr


# ---------------- selection (09:20 / 13:15)
def select(ag, inst, C, ltp_of, now, regime):
    today = ist_today()
    cands = []
    for n, bars in (C.get("bars") or {}).items():
        ltp = ltp_of.get(n)
        if not ltp:
            continue
        zs, atr = zones(bars)
        if not zs:
            continue
        thr = min(CFG["approach_base"], max(1.0, 1.5 * atr / ltp * 100))   # adaptive proximity
        h, l, c = (np.array(bars[k], float) for k in ("h", "l", "c"))
        stc = structure(h, l, c)
        lv = (C.get("levels") or {}).get(n) or {}
        for z in zs:
            side = "CE" if z["kind"] == "SUPPLY" else "PE"
            edge = z["bot"] if side == "CE" else z["top"]
            dist = (edge - ltp) / ltp * 100 if side == "CE" else (ltp - edge) / ltp * 100
            inside = z["bot"] <= ltp <= z["top"]
            if not (inside or 0 <= dist <= thr):
                continue
            cands.append({"symbol": n, "side": side, "setup": "BREAKOUT-CE" if side == "CE" else "BREAKDOWN-PE",
                          "zone": [z["bot"], z["top"]], "edge": edge, "dist": round(dist, 2), "thr": round(thr, 2),
                          "ltp": float(ltp), "zone_rank": z["rank"], "tests": z["tests"], "age": z["age"],
                          "displacement": z["displacement"], "zone_date": z["date"], "structure": stc,
                          "levels": {k: lv.get(k) for k in ("PDH", "PDL", "PWH", "PWL", "PMH", "PML")},
                          "ul_token": inst["eq"].get(n)})
    best = {}
    for c_ in cands:
        k = (c_["symbol"], c_["side"])
        if k not in best or c_["zone_rank"] > best[k]["zone_rank"]:
            best[k] = c_
    cands = sorted(best.values(), key=lambda x: (-x["zone_rank"], abs(x["dist"])))[:15]
    want = []
    for w in cands:
        for r in inst["opts"].get(w["symbol"], []):
            if r[4] != w["side"]:
                continue
            k = r[3]
            otm = k > w["ltp"] if w["side"] == "CE" else k < w["ltp"]
            if otm and abs(k - w["edge"]) / w["edge"] * 100 <= max(w["thr"], 2.5):
                want.append((w, r))
    toks = {}
    for _, r in want:
        toks.setdefault(r[6], []).append(r[0])
    qs = ag.quotes(toks) if toks else {}
    groups = {}
    for w, r in want:
        q = qs.get(r[0]) or {}
        dte = _tdays(today, pd.Timestamp(r[2]).date())
        eng = "HOLDING" if dte >= ENG["HOLDING"]["min_dte"] else "INTRADAY" if dte >= ENG["INTRADAY"]["min_dte"] else None
        if not eng:
            continue
        oi, lot, ltp = _f(q.get("opnInterest")), r[5] or 1, _f(q.get("ltp"))
        d = q.get("depth") or {}
        bid = _f(((d.get("buy") or [{}])[0] or {}).get("price"))
        ask = _f(((d.get("sell") or [{}])[0] or {}).get("price"))
        spread = (ask - bid) / ((ask + bid) / 2) * 100 if bid and ask else 99
        value = _f(q.get("tradeVolume")) * (_f(q.get("avgPrice")) or ltp)
        if oi < 50 * lot or value < CFG["min_value"] or spread > CFG["max_spread_pct"] or ltp <= 0:
            continue
        try:
            gk = greeks_from_price(ltp, w["ltp"], r[3], r[2], w["side"], now.to_pydatetime())
        except Exception:
            gk = {"iv": None, "delta": None, "theta_pct": None}
        dlt = gk.get("delta") or 0
        th = gk.get("theta_pct") if gk.get("theta_pct") is not None else 99
        rank = (30 * (1 - min(spread / CFG["max_spread_pct"], 1)) + 15 * min(value / 1e7, 1) + 20 * min(oi / (500 * lot), 1)
                + 25 * (1 if 0.2 <= dlt <= 0.45 else 0.4) + 10 * (1 if th <= (10 if eng == "INTRADAY" else 6) else 0))
        groups.setdefault((w["symbol"], w["side"], eng), []).append(
            {**{k: w[k] for k in ("symbol", "side", "setup", "zone", "edge", "zone_rank", "structure", "ul_token", "levels")},
             "engine": eng, "token": r[0], "exch": r[6], "contract": r[1], "strike": r[3], "expiry": r[2], "lot": lot,
             "dte": dte, "oi": int(oi), "value": round(value), "spread": round(spread, 2), "bid": bid, "ask": ask,
             "ltp": ltp, "greeks": gk, "strike_rank": int(rank)})
    cons = []
    for k, lst in groups.items():
        lst.sort(key=lambda x: -x["strike_rank"])
        for i, x in enumerate(lst[:2]):
            x["pick"] = f"#{i+1}"
            cons.append(x)
    cons.sort(key=lambda x: -(x["zone_rank"] + x["strike_rank"]))
    return cands, cons[:CFG["max_contracts"]]


# ---------------- 4. OI engine
def _oi(ag, c, start, end):
    p = {"exchange": c["exch"], "symboltoken": c["token"], "interval": "FIVE_MINUTE",
         "fromdate": start.strftime("%Y-%m-%d %H:%M"), "todate": end.strftime("%Y-%m-%d %H:%M")}
    try:
        res = ag._call(lambda: ag.api.getOIData(p))
        return [_f(x.get("oi")) for x in (res.get("data") or []) if x.get("oi") is not None]
    except Exception:
        return []


def oi_metrics(oi, prem):
    if len(oi) < 4:
        return {"ok": False}
    peak, cur = max(oi), oi[-1]
    pct = lambda a, b: (b - a) / a * 100 if a else 0.0
    m = {"ok": True, "peak": int(peak), "now": int(cur), "drop": round((peak - cur) / peak * 100, 1) if peak else 0,
         "chg5": round(pct(oi[-2], cur), 2), "chg15": round(pct(oi[-4], cur), 2),
         "chg30": round(pct(oi[-7], cur), 2) if len(oi) >= 7 else None}
    v_now, v_prev = pct(oi[-2], cur), pct(oi[-3], oi[-2])
    m["velocity"] = round(v_now, 2)
    m["accel"] = bool(v_now < v_prev < 0)
    p15 = pct(prem[-4], prem[-1]) if len(prem) >= 4 else 0
    o15 = m["chg15"]
    if abs(o15) < 1 or abs(p15) < 1:
        m["class"] = "Ambiguous"
    elif p15 > 0 and o15 < 0:
        m["class"] = "Potential short covering"
    elif p15 < 0 and o15 < 0:
        m["class"] = "Potential long unwinding"
    elif p15 > 0:
        m["class"] = "Potential long buildup"
    else:
        m["class"] = "Potential short buildup"
    return m


def stock_ctx(ag, c, now):
    t0 = now.normalize() + pd.Timedelta(hours=9, minutes=15)
    df = ag.candles("NSE", c["ul_token"], "FIFTEEN_MINUTE", t0, now)
    if not df.empty:
        df = df[df.index + pd.Timedelta(minutes=15) <= now]
    if df.empty:
        return {}
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vwap = float((tp * df["volume"]).sum() / max(df["volume"].sum(), 1))
    cl = df["close"].values
    tr = "UP" if len(cl) >= 3 and cl[-1] > cl[-2] > cl[-3] else "DOWN" if len(cl) >= 3 and cl[-1] < cl[-2] < cl[-3] else "FLAT"
    return {"close15": float(cl[-1]), "vwap": round(vwap, 2), "trend15": tr}


# ---------------- 6/8/9 evaluate one contract
def evaluate(ag, c, now, ul, q, regime):
    t0 = now.normalize() + pd.Timedelta(hours=9, minutes=15)
    df = ag.candles(c["exch"], c["token"], "FIVE_MINUTE", t0, now)
    if not df.empty:
        df = df[df.index + pd.Timedelta(minutes=5) <= now]
    ev = {"A": False, "B": False, "C": False, "H": False, "armed": False, "trigger": None, "hard": {}, "score": 0, "tier": "—"}
    if len(df) < 8:
        ev["note"] = "Trade இல்லை / போதுமான 5-min bars இல்லை"
        return ev
    o, h, l, cl, v = (df[k].values for k in ("open", "high", "low", "close", "volume"))
    oi = oi_metrics(_oi(ag, c, t0, now), cl)
    ev["oi"] = oi
    ev["A"] = bool(oi.get("ok") and oi["drop"] >= CFG["oi_drop"])
    avg20 = v[-21:-1].mean() if len(v) > 21 else v[:-1].mean()
    rv = float(v[-1] / avg20) if avg20 else 0
    ev["B"] = bool(int((v[-3:] > avg20).sum()) >= 2)
    base_h, base_l = float(h[-7:-1].max()), float(l[-7:-1].min())
    atr14 = _atr(h, l, cl, 14)
    rng6 = base_h - base_l
    prior = (h[-19:-7].max() - l[-19:-7].min()) if len(h) >= 19 else rng6
    ev["C"] = bool(atr14 and rng6 <= atr14)
    ev["H"] = bool((v[-7:] > 0).all() and avg20 > 0 and (cl > 0).all())
    ev["armed"] = ev["A"] and ev["B"] and ev["C"] and ev["H"]
    mid = (base_h + base_l) / 2
    body = abs(cl[-1] - o[-1]) / max(h[-1] - l[-1], 1e-9)
    rejections = int(((h[-13:-1] > base_h) & (cl[-13:-1] < base_h)).sum())
    if cl[-1] > base_h and v[-1] > avg20:
        ev["trigger"] = "PREMIUM BREAKOUT"
    elif l[-1] < base_l and cl[-1] > mid and v[-1] > avg20 * 0.8:
        ev["trigger"] = "SHAKEOUT-RECLAIM"
    ev.update(rv=round(rv, 2), cons_high=round(base_h, 2), cons_low=round(base_l, 2), ltp=round(float(cl[-1]), 2),
              compression=round(rng6 / prior, 2) if prior else None, body=round(float(body), 2), rejections=rejections)
    ce = c["side"] == "CE"
    ulc = ul.get("close15")
    ul_break = bool(ulc and ((ulc > c["edge"] and ulc > ul["vwap"]) if ce else (ulc < c["edge"] and ulc < ul["vwap"])))
    ev["ul_break"] = ul_break
    d = (q or {}).get("depth") or {}
    bid = _f(((d.get("buy") or [{}])[0] or {}).get("price"))
    ask = _f(((d.get("sell") or [{}])[0] or {}).get("price"))
    spread = (ask - bid) / ((ask + bid) / 2) * 100 if bid and ask else 99
    entry = r05(ask or ev["ltp"])
    sl = r05(base_l if ev["trigger"] == "PREMIUM BREAKOUT" else min(base_l, float(l[-1])))
    risk = round((entry - sl) * c["lot"] + CFG["charges"]) if entry > sl else 10 ** 9
    ev.update(entry=entry, sl=sl, risk=risk, spread=round(spread, 2))
    hard = {"Fresh data": _fresh(q, now), "Underlying breakout": ul_break,
            "Liquidity": spread <= CFG["max_spread_pct"] and c["oi"] >= 50 * c["lot"],
            "Expiry": c["dte"] >= ENG[c["engine"]]["min_dte"], "Risk ≤ cap": risk <= CFG["risk_cap"],
            "Data sane": bool(bid <= ask and entry > 0 and sl > 0)}
    ev["hard"] = hard
    gk = c.get("greeks") or {}
    sc = 0.0
    stc = (c.get("structure") or {}).get("trend")
    sc += 12 * c.get("zone_rank", 0) / 100 + (8 if (stc == "BULL" and ce) or (stc == "BEAR" and not ce) else 3 if stc == "SIDEWAYS" else 0)
    if oi.get("ok"):
        sc += 12 * min(oi["drop"] / 12, 1) + (4 if oi["chg15"] < 0 else 0) + (4 if oi.get("accel") else 0)
    sc += 8 * min(rv / 2, 1) + (7 if spread <= 2 else 4 if spread <= 4 else 0)
    vw_ok = bool(ulc) and ((ulc > ul["vwap"]) if ce else (ulc < ul["vwap"]))
    sc += (8 if vw_ok else 0) + (7 if ul.get("trend15") == ("UP" if ce else "DOWN") else 0)
    sc += (8 if ev["trigger"] else 0) + (4 if body >= 0.5 else 0) + (3 if rejections < 2 else 0)
    th = gk.get("theta_pct") if gk.get("theta_pct") is not None else 99
    iv_ = gk.get("iv") or 0
    sc += 4 + (3 if th <= (10 if c["engine"] == "INTRADAY" else 6) else 0) + (3 if 0 < iv_ < 60 else 0)
    rg = (regime or {}).get("trend")
    sc += 5 if (rg == "TRENDING UP" and ce) or (rg == "TRENDING DOWN" and not ce) else 2 if rg in ("RANGE-BOUND", None) else 0
    ev["score"] = int(round(min(sc, 100)))
    ev["hard_ok"] = all(hard.values())
    if ev["armed"] and ev["trigger"]:
        ev["tier"] = ("PRO ENTRY" if ev["hard_ok"] and ev["score"] >= CFG["pro"]
                      else "STRONG WATCHLIST" if ev["score"] >= CFG["strong"] else "WATCHLIST")
    return ev


# ---------------- main cycle
def run(ag, inst, C, ltp_of, now, regime, sl_today=0):
    day = str(now.date())
    mins = now.hour * 60 + now.minute
    if ST["day"] != day:
        ST.update(day=day, sel={}, zones=[], contracts=[], signals={}, armed={}, entries=0, cool={})
    ST["regime"] = regime
    slot = "13:15" if mins >= 13 * 60 + 15 else "09:20" if mins >= 9 * 60 + 20 else None
    health = {"api_fail": 0, "stale": 0, "checked": 0}
    t_start = pd.Timestamp.now()
    if slot and slot not in ST["sel"]:
        zl, cons = select(ag, inst, C, ltp_of, now, regime)
        ST["sel"][slot] = now.strftime("%H:%M")
        ST["zones"] = zl
        keep = {x["contract"]: x for x in ST["contracts"]}
        for x in cons:
            keep[x["contract"]] = {**keep.get(x["contract"], {}), **x}
        ST["contracts"] = sorted(keep.values(), key=lambda x: -(x["zone_rank"] + x["strike_rank"]))[:CFG["max_contracts"]]
    toks = {}
    for c in ST["contracts"]:
        toks.setdefault(c["exch"], []).append(c["token"])
    qs = ag.quotes(toks) if toks else {}
    ctx = {}
    for c in ST["contracts"]:
        if c["symbol"] not in ctx:
            try:
                ctx[c["symbol"]] = stock_ctx(ag, c, now)
            except Exception:
                ctx[c["symbol"]] = {}
                health["api_fail"] += 1
        q = qs.get(c["token"]) or {}
        if not _fresh(q, now):
            health["stale"] += 1
        try:
            c["eval"] = evaluate(ag, c, now, ctx[c["symbol"]], q, regime)
        except Exception as e:
            c["eval"] = {"note": f"error: {e}", "tier": "—"}
            health["api_fail"] += 1
        health["checked"] += 1
        ev = c["eval"]
        key = f"{day}|{c['contract']}"
        if ev.get("armed"):
            ST["armed"].setdefault(key, now.strftime("%H:%M"))
        a_at = ST["armed"].get(key)
        if a_at and not ev.get("trigger"):
            age = (now - pd.Timestamp(f"{day} {a_at}")).total_seconds() / 60
            ev["armed_status"] = "EXPIRED" if age > CFG["armed_expiry_min"] else f"ARMED {a_at}"
        if not (ev.get("armed") and ev.get("trigger")) or key in ST["signals"]:
            continue
        tier, block = ev["tier"], None
        if tier == "PRO ENTRY":
            same = [s for s in ST["signals"].values() if s["symbol"] == c["symbol"] and s["tier"] == "PRO ENTRY"]
            last = ST["cool"].get(c["symbol"])
            if ST["entries"] >= CFG["max_entries_day"]:
                block = "இன்றைய max ENTRY (3) அடைந்தது"
            elif sl_today >= CFG["sl_pause_after"]:
                block = "இன்று SL அதிகம் — cooldown"
            elif any(s["side"] != c["side"] for s in same):
                block = "முரண்பாடான CE/PE"
            elif last and (now - pd.Timestamp(f"{day} {last}")).total_seconds() / 60 < CFG["stock_cooldown_min"]:
                block = "Stock cooldown"
            if block:
                tier = "STRONG WATCHLIST"
            else:
                ST["entries"] += 1
                ST["cool"][c["symbol"]] = now.strftime("%H:%M")
        e = ev["entry"]
        tgs = [r05(e * (1 + x)) for x in ENG[c["engine"]]["targets"]]
        sig = {**{k: c[k] for k in ("symbol", "side", "setup", "engine", "pick", "contract", "token", "exch", "strike",
                                    "expiry", "dte", "lot", "zone", "edge", "ul_token")},
               "id": f"GU-{c['engine'][0]}-{day.replace('-', '')}-{len(ST['signals'])+1:03d}",
               "time": now.strftime("%H:%M"), "tier": tier, "block": block, "score": ev["score"], "hard": ev["hard"],
               "trigger": ev["trigger"], "entry": e, "entry_zone": [r05(e * 0.98), r05(e * 1.02)], "sl": ev["sl"],
               "targets": tgs, "risk": ev["risk"], "oi": ev.get("oi"), "rv": ev["rv"], "greeks": c.get("greeks"),
               "ul_close": ctx[c["symbol"]].get("close15")}
        ST["signals"][key] = sig
        if tier in ("PRO ENTRY", "STRONG WATCHLIST"):
            head = f"🔥 {sig['symbol']} {sig['strike']:g} {sig['side']} – {sig['engine']} " + ("CALL" if tier == "PRO ENTRY" else "STRONG WATCHLIST")
            tg("🚀 GAMMA-UNWIND V3 PRO\n\n" + head +
               f"\n\nEntry Zone: ₹{sig['entry_zone'][0]}–₹{sig['entry_zone'][1]}\n" +
               "".join(f"🎯 T{i+1}: ₹{t}\n" for i, t in enumerate(tgs)) +
               f"\n🛑 Must Follow SL: ₹{sig['sl']}\n\nOI Unwind: {(sig['oi'] or {}).get('drop', '–')}%\n"
               f"Relative Volume: {sig['rv']}x\nPro Score: {sig['score']}/100\nTrigger: {sig['trigger']} @ {sig['time']}\n"
               f"Risk: High Risk – 1 Lot (≈₹{sig['risk']})\nExpiry: {sig['expiry']}\n" +
               (f"⚠ {block}\n" if block else "") + "\nAlert only · not advice · ID " + sig["id"], key)
    health["seconds"] = round((pd.Timestamp.now() - t_start).total_seconds())
    health["time"] = now.strftime("%H:%M")
    ST["health"] = health
    ST["last"] = now.strftime("%H:%M")
    if health["checked"] and health["stale"] > max(3, health["checked"] // 2):
        tg(f"⚠ GAMMA-UNWIND data quality warning: {health['stale']}/{health['checked']} quotes stale", f"dq|{day}|{now:%H}")
    return snapshot()


def snapshot():
    sigs = sorted(ST["signals"].values(), key=lambda s: s["time"], reverse=True)
    cons = ST["contracts"]
    lead = sorted([c for c in cons if ((c.get("eval") or {}).get("oi") or {}).get("ok")],
                  key=lambda c: -c["eval"]["oi"]["drop"])[:10]
    return {"day": ST["day"], "selected": ST["sel"], "last": ST["last"], "zones": ST["zones"], "contracts": cons,
            "signals": sigs, "armed": [c for c in cons if (c.get("eval") or {}).get("armed")],
            "oi_leaders": lead, "health": ST["health"], "regime": ST["regime"], "entries": ST["entries"], "cfg": CFG}
