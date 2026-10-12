"""👑 ELITE SETUP — உங்கள் 2 Chartink scanner rules, Angel One data-வில் நாமே கணக்கிடுவது.
S1 = "GROK BEST ONE HOLDING 1 MONTH" (weekly momentum)  → ELITE HOLDING (1 வாரம் – 1 மாதம்)
S2 = "FINAL SCANER MASTER VERSION" (weekly+daily+15-min) → ELITE INTRADAY
இரண்டும் pass = 👑 ELITE JACKPOT (green alert).
Bullish rules → CE. அதே rules தலைகீழ் (mirror) → PE (தனி label).
Confidence = rules + extra filters (NIFTY regime, RS, OI buildup, extension, RSI zone, R:R). Win-rate guarantee இல்லை."""
import numpy as np
import pandas as pd

INTRA_WINDOW = (9 * 60 + 30, 14 * 60 + 30)


def ema(x, n):
    return pd.Series(x, dtype=float).ewm(span=n, adjust=False).mean().values


def sma(x, n):
    return pd.Series(x, dtype=float).rolling(n).mean().values


def rsi(x, n=14):
    s = pd.Series(x, dtype=float)
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    out = pd.Series(50.0, index=s.index)
    nz = dn > 0
    out[nz] = 100 - 100 / (1 + up[nz] / dn[nz])
    out[(dn == 0) & (up > 0)] = 100.0
    return out.values


def weekly(bars, today_q, session):
    """Daily bars + இன்றைய quote → weekly OHLCV (நடப்பு வாரம் running, Chartink போலவே)."""
    df = pd.DataFrame({"open": bars.get("o") or bars["c"], "high": bars["h"], "low": bars["l"], "close": bars["c"],
                       "volume": bars["v"]}, index=pd.to_datetime(bars["t"]))
    if today_q and today_q.get("ltp"):
        df.loc[pd.Timestamp(session)] = [today_q.get("open") or today_q["ltp"], today_q.get("high") or today_q["ltp"],
                                         today_q.get("low") or today_q["ltp"], today_q["ltp"], today_q.get("volume") or 0]
    w = df.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    return w


def s1_rules(w, side):
    """GROK BEST ONE HOLDING (weekly)."""
    if len(w) < 22:
        return None
    c, o, v = w["close"].values, w["open"].values, w["volume"].values
    sm, vs, r = sma(c, 20)[-1], sma(v, 20)[-1], rsi(c)[-1]
    chg = (c[-1] - c[-2]) / c[-2]
    if side == "CE":
        rules = {"W close > W SMA20": c[-1] > sm, "W change > 4%": chg > 0.04, "W volume > 1.5× SMA20": v[-1] > 1.5 * vs,
                 "W RSI > 60": r > 60, "W close > 1w close": c[-1] > c[-2], "1w > 2w close": c[-2] > c[-3],
                 "2w > 3w close": c[-3] > c[-4], "W open ≤ 1w close": o[-1] <= c[-2], "W close ≥ 1w open": c[-1] >= o[-2]}
    else:
        rules = {"W close < W SMA20": c[-1] < sm, "W change < −4%": chg < -0.04, "W volume > 1.5× SMA20": v[-1] > 1.5 * vs,
                 "W RSI < 40": r < 40, "W close < 1w close": c[-1] < c[-2], "1w < 2w close": c[-2] < c[-3],
                 "2w < 3w close": c[-3] < c[-4], "W open ≥ 1w close": o[-1] >= c[-2], "W close ≤ 1w open": c[-1] <= o[-2]}
    return {k: bool(x) for k, x in rules.items()}, {"w_rsi": round(float(r), 1), "w_chg": round(chg * 100, 2)}


def s2_daily(w, f, lv, ltp, side):
    """FINAL SCANER — weekly + daily பகுதி (stage 1, API call இல்லை)."""
    if len(w) < 22 or not f.get("ema200"):
        return None
    c = w["close"].values
    sm, r = sma(c, 20)[-1], rsi(c)[-1]
    if side == "CE":
        return {"W close > W SMA20": c[-1] > sm, "W RSI > 60": r > 60, "D close > EMA200": ltp > f["ema200"],
                "D EMA20 > EMA50": f["ema20"] > f["ema50"], "D close > PDH": bool(lv.get("PDH")) and ltp > lv["PDH"]}
    return {"W close < W SMA20": c[-1] < sm, "W RSI < 40": r < 40, "D close < EMA200": ltp < f["ema200"],
            "D EMA20 < EMA50": f["ema20"] < f["ema50"], "D close < PDL": bool(lv.get("PDL")) and ltp < lv["PDL"]}


def s2_intraday(df15, session, now, side):
    """[0] 15-min: VWAP, EMA20, RSI14 > 60, volume > 1.8 × SMA10 — completed candles மட்டும் (repaint இல்லை)."""
    df = df15[df15.index + pd.Timedelta(minutes=15) <= now]
    if len(df) < 25:
        return None
    c, v = df["close"].values, df["volume"].values
    today = df[df.index.normalize() == pd.Timestamp(session)]
    if today.empty:
        return None
    tp = (today["high"] + today["low"] + today["close"]) / 3
    vwap = float((tp * today["volume"]).sum() / max(today["volume"].sum(), 1))
    e20, r, vs = ema(c, 20)[-1], rsi(c)[-1], sma(v, 10)[-1]
    last = c[-1]
    if side == "CE":
        rules = {"15m close > VWAP": last > vwap, "15m close > EMA20": last > e20, "15m RSI > 60": r > 60,
                 "15m volume > 1.8× SMA10": v[-1] > 1.8 * vs}
    else:
        rules = {"15m close < VWAP": last < vwap, "15m close < EMA20": last < e20, "15m RSI < 40": r < 40,
                 "15m volume > 1.8× SMA10": v[-1] > 1.8 * vs}
    return {k: bool(x) for k, x in rules.items()}, {"vwap": round(vwap, 2), "rsi15": round(float(r), 1),
                                                    "close15": float(last), "bar": str(df.index[-1])[11:16],
                                                    "vol_x": round(float(v[-1] / vs), 2) if vs else 0}


def scan(ag, inst, C, universe, trend, bu_tag, nifty_ret20, now, session, live, max_15m=15):
    out = {"intraday": [], "holding": [], "jackpot": [], "almost": [], "checked": 0}
    mins = now.hour * 60 + now.minute
    stage = []
    for u in universe:
        n, ltp = u["symbol"], u["ltp"]
        bars, f, lv = (C.get("bars") or {}).get(n), (C.get("feat") or {}).get(n), (C.get("levels") or {}).get(n) or {}
        if not bars or not f or not ltp:
            continue
        q = {"ltp": ltp, "open": u.get("open"), "high": u.get("high"), "low": u.get("low"), "volume": u.get("volume")}
        try:
            w = weekly(bars, q, session)
        except Exception:
            continue
        for side in ("CE", "PE"):
            r1 = s1_rules(w, side)
            d2 = s2_daily(w, f, lv, ltp, side)
            if not r1 and not d2:
                continue
            row = {"symbol": n, "side": side, "mirror": side == "PE", "price": ltp, "pct": u["pct"],
                   "vol_ratio": u["vol_ratio"], "s1": r1[0] if r1 else {}, "s1_info": r1[1] if r1 else {},
                   "s2": dict(d2 or {}), "atr": f.get("atr"), "f": f, "lv": lv}
            row["s1_pass"] = bool(r1) and all(r1[0].values())
            d_ok = bool(d2) and all(d2.values())
            if row["s1_pass"] or d_ok or (d2 and sum(d2.values()) >= len(d2) - 1):
                row["d_ok"] = d_ok
                stage.append(row)
    # stage 2: 15-min (S2 daily pass ஆனவை மட்டும், volume அதிகமானவை முதலில்)
    need = sorted([r for r in stage if r.get("d_ok")], key=lambda r: -r["vol_ratio"])[:max_15m]
    t0 = (pd.Timestamp(session) - pd.tseries.offsets.BDay(3)).normalize() + pd.Timedelta(hours=9, minutes=15)
    for r in need:
        tok = inst["eq"].get(r["symbol"])
        df = ag.candles("NSE", tok, "FIFTEEN_MINUTE", t0, now if live else pd.Timestamp(session) + pd.Timedelta(hours=15, minutes=30))
        out["checked"] += 1
        if df.empty:
            continue
        res = s2_intraday(df, session, now if live else pd.Timestamp(session) + pd.Timedelta(hours=15, minutes=30), r["side"])
        if res:
            r["s2"].update(res[0])
            r["s2_info"] = res[1]
    for r in stage:
        s2_all = len(r["s2"]) == 9 and all(r["s2"].values())
        r["s2_pass"] = s2_all
        ce = r["side"] == "CE"
        # confidence
        conf, why = 50, []
        if r["s1_pass"] and s2_all:
            conf += 15; why.append("இரண்டு scanner-ம் pass")
        if (trend == "TRENDING UP" and ce) or (trend == "TRENDING DOWN" and not ce):
            conf += 10; why.append("NIFTY trend ஒத்துப்போகுது")
        elif trend not in ("RANGE-BOUND", "UNCLEAR — WAIT"):
            conf -= 10; why.append("NIFTY trend எதிர்")
        rs = (r["price"] / r["f"]["c20"] - 1 - nifty_ret20) if r["f"].get("c20") else 0
        if (rs > 0) == ce:
            conf += 10; why.append(f"NIFTY-ஐ விட {'வலிமை' if ce else 'பலவீனம்'} ({rs*100:+.1f}%)")
        k = bu_tag.get(r["symbol"], "")
        if (ce and k in ("Long Built Up", "Short Covering")) or (not ce and k in ("Short Built Up", "Long Unwinding")):
            conf += 5; why.append(f"Futures OI: {k}")
        atr = r.get("atr") or 0
        ext = abs(r["price"] - r["f"]["ema20"]) / atr if atr else 0
        if ext <= 2:
            conf += 5; why.append("EMA20-ல் இருந்து அதிக தூரம் இல்லை")
        else:
            conf -= 5; why.append(f"Extended ({ext:.1f} ATR) — late entry risk")
        rsi15 = (r.get("s2_info") or {}).get("rsi15")
        if rsi15 and ((60 <= rsi15 <= 75) if ce else (25 <= rsi15 <= 40)):
            conf += 5; why.append("15m RSI நல்ல zone")
        elif rsi15 and ((rsi15 > 80) if ce else (rsi15 < 20)):
            conf -= 5; why.append("15m RSI overbought/oversold")
        r["confidence"] = int(max(0, min(100, conf)))
        r["why"] = why
        r["jackpot"] = (r["s1_pass"] and s2_all) or (s2_all and r["confidence"] >= 85)
        r["label"] = "👑 ELITE JACKPOT" if r["jackpot"] else "ELITE" if r["confidence"] >= 70 else "ELITE (low conf)"
        r["stars"] = 5 if r["confidence"] >= 85 else 4 if r["confidence"] >= 70 else 3
        r["strong"] = r["jackpot"]
        r["status"] = "CONFIRMED"
        r["score"] = r["confidence"]
        r["in_window"] = INTRA_WINDOW[0] <= mins <= INTRA_WINDOW[1]
        # SL / targets (underlying)
        sgn = 1 if ce else -1
        if s2_all:
            vw = r["s2_info"]["vwap"]
            sl = min(vw, r["price"] - 0.4 * atr) if ce else max(vw, r["price"] + 0.4 * atr)
            r["sl"] = round(sl, 2)
            r["targets"] = []
        if r["s1_pass"]:
            r["hold_sl"] = round(r["price"] - sgn * 1.5 * atr, 2)
        for x in ("f", "lv"):
            r.pop(x, None)
        if s2_all:
            out["intraday"].append(r)
        if r["s1_pass"]:
            out["holding"].append(r)
        if not s2_all and not r["s1_pass"]:
            out["almost"].append(r)
    for k in ("intraday", "holding"):
        out[k].sort(key=lambda r: -r["confidence"])
    out["jackpot"] = [r for r in out["intraday"] + out["holding"] if r["jackpot"]]
    out["almost"] = sorted(out["almost"], key=lambda r: -(sum(r["s2"].values()) + sum(r["s1"].values())))[:12]
    return out
