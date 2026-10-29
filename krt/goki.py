"""👑 GOKI MANNAN JACKPOT RADAR
CE = உங்கள் Chartink "FINAL SCANER MASTER VERSION" (9 rules — Elite S2 அதே rules)
PE = உங்கள் Chartink "DOW EARANGUM" (15-min PDL fresh breakdown + red candle + volume 3× + VWAP கீழ் + RSI<40 + price>50 + vol>5L + mcap>1000)
→ ஒவ்வொரு setup-க்கும் rule-based "AI analysis" score (scanner match, 15m volume / institution proxy, futures OI build-up,
  NIFTY direction, RS, chart extension, candle strength, room to next level, option liquidity) → top 3 = Jackpot Radar.
நேர்மை: Chartink-ஐ நேரடியா call பண்ணல — அதே rules Angel One data-வில் நாமே கணக்கிடுறோம் (VWAP / RSI கணக்கில் சின்ன வித்தியாசம் வரலாம்).
Market cap data இல்லை → F&O stocks எல்லாம் ₹1,000 Cr-க்கு மேல் என்று எடுத்துக்கொள்ளப்படுது. Score = ranking, win probability இல்லை.
"""
import numpy as np
import pandas as pd

from .elite import ema, rsi, sma

STATE = {"radar": None}


def dow_rules(df15, session, now, pdl, ltp, day_vol):
    """DOW EARANGUM (completed 15-min candles மட்டும்)."""
    df = df15[df15.index + pd.Timedelta(minutes=15) <= now]
    if len(df) < 25 or not pdl:
        return None
    today = df[df.index.normalize() == pd.Timestamp(session)]
    if len(today) < 1:
        return None
    c, o, v = df["close"].values, df["open"].values, df["volume"].values
    tp = (today["high"] + today["low"] + today["close"]) / 3
    vwap = float((tp * today["volume"]).sum() / max(today["volume"].sum(), 1))
    r = rsi(c)[-1]
    vs = sma(v, 20)[-1]
    rules = {"15m close < PDL": c[-1] < pdl,
             "[-1] 15m close ≥ PDL (fresh break)": c[-2] >= pdl,
             "Red candle (close < open)": c[-1] < o[-1],
             "15m volume > 3× SMA20": bool(vs) and v[-1] > 3 * vs,
             "15m close < VWAP": c[-1] < vwap,
             "15m RSI < 40": r < 40,
             "Daily close > 50": ltp > 50,
             "Daily volume > 5 lakh": day_vol > 500000,
             "Market cap > 1000 Cr (F&O — assumed)": True}
    bar = df.iloc[-1]
    rng = float(bar["high"] - bar["low"]) or 1e-9
    info = {"vwap": round(vwap, 2), "rsi15": round(float(r), 1), "close15": float(c[-1]), "bar": str(df.index[-1])[11:16],
            "vol_x": round(float(v[-1] / vs), 2) if vs else 0, "body": round(abs(float(bar["close"] - bar["open"])) / rng, 2),
            "hi15": float(bar["high"]), "lo15": float(bar["low"])}
    return {k: bool(x) for k, x in rules.items()}, info


def analyse(r, side, bu_tag, nifty_pct, nret, f, lv, edge=None):
    """Rule-based 'AI analysis' → score 0–100 + checklist."""
    ce = side == "CE"
    chk, sc = {}, 0
    rules = r["rules"]
    n_ok = sum(rules.values())
    full = n_ok == len(rules)
    sc += 35 if full else 20 if n_ok == len(rules) - 1 else 0
    chk[f"Scanner {n_ok}/{len(rules)}"] = full
    vx = (r.get("info") or {}).get("vol_x") or 0
    sc += 20 if vx >= 5 else 15 if vx >= 3 else 8 if vx >= 2 else 0
    chk[f"15m volume {vx}× (institution proxy)"] = vx >= 3
    if (r.get("vol_ratio") or 0) >= 2:
        sc += 5
    k = bu_tag.get(r["symbol"], "")
    oi_ok = (ce and k in ("Long Built Up", "Short Covering")) or (not ce and k in ("Short Built Up", "Long Unwinding"))
    if oi_ok:
        sc += 15
    chk[f"Futures OI: {k or 'தெரியல'}"] = oi_ok
    nd = (nifty_pct >= 0.2) if ce else (nifty_pct <= -0.2)
    na = (nifty_pct <= -0.2) if ce else (nifty_pct >= 0.2)
    sc += 10 if nd else -10 if na else 0
    chk[f"NIFTY {nifty_pct:+.2f}% {'ஒத்துப்போகுது' if nd else 'எதிர்' if na else 'flat'}"] = nd
    rs = (r["price"] / f["c20"] - 1 - nret) if f.get("c20") else 0
    rs_ok = (rs > 0) == ce
    if rs_ok:
        sc += 5
    chk[f"RS vs NIFTY {rs * 100:+.1f}%"] = rs_ok
    atr = f.get("atr") or r["price"] * 0.02
    vw = (r.get("info") or {}).get("vwap") or r["price"]
    ext = abs(r["price"] - vw) / atr if atr else 0
    sc += 10 if ext <= 1.0 else 0 if ext <= 2 else -10
    chk[f"VWAP-ல் இருந்து {ext:.1f} ATR (late இல்லை)"] = ext <= 1.0
    body = (r.get("info") or {}).get("body") or 0
    if body >= 0.6:
        sc += 5
    chk[f"Candle body {int(body * 100)}%"] = body >= 0.6
    nxt = [lv.get(x) for x in (("PWH", "PMH") if ce else ("PWL", "PML")) if lv.get(x)]
    nxt = [x for x in nxt if (x > r["price"]) == ce]
    room = (min(abs(x - r["price"]) for x in nxt) / atr) if (nxt and atr) else 9
    if room >= 1:
        sc += 5
    chk[f"அடுத்த level வரை {min(room, 9):.1f} ATR room"] = room >= 1
    r["score"] = int(max(0, min(100, sc)))
    r["chk"], r["rs"], r["ext_atr"], r["oi"] = chk, round(rs * 100, 2), round(ext, 2), k
    r["atr"] = atr
    return r


def scan(ag, inst, C, universe, bu_tag, nifty_pct, nret, now, session, live, elite_rows, max_15m=20):
    """Elite scan-ன் CE rows (FINAL SCANER MASTER) + DOW EARANGUM PE scan."""
    out = []
    bars_, feat_, lev_ = C.get("bars") or {}, C.get("feat") or {}, C.get("levels") or {}
    # CE — FINAL SCANER MASTER VERSION (Elite S2 = அதே 9 rules)
    for e in elite_rows or []:
        if e.get("side") != "CE" or len(e.get("s2") or {}) != 9:
            continue
        if sum(e["s2"].values()) < 8:
            continue
        f = feat_.get(e["symbol"]) or {}
        nm = "MASTER BLASTER" if (e.get("pct") or 0) >= 3 else "FINAL SCANER MASTER"     # Close/Open ≥ 1.03 → MASTER BLASTER
        r = {"symbol": e["symbol"], "side": "CE", "scanner": nm, "price": e["price"], "pct": e.get("pct"),
             "vol_ratio": e.get("vol_ratio"), "rules": dict(e["s2"]), "info": dict(e.get("s2_info") or {})}
        r["info"]["body"] = r["info"].get("body", 0.6)
        out.append(analyse(r, "CE", bu_tag, nifty_pct, nret, f, lev_.get(e["symbol"]) or {}))
    # PE — DOW EARANGUM: முதலில் daily pre-filter (இன்று PDL-க்கு கீழ் / அருகில், price > 50, volume > 5L)
    cands = []
    for u in universe:
        lv = lev_.get(u["symbol"]) or {}
        pdl = lv.get("PDL")
        if not pdl or u["ltp"] <= 50 or u.get("volume", 0) <= 500000:
            continue
        if u["ltp"] <= pdl * 1.003:
            cands.append(u)
    cands.sort(key=lambda u: -u["vol_ratio"])
    t0 = (pd.Timestamp(session) - pd.tseries.offsets.BDay(3)).normalize() + pd.Timedelta(hours=9, minutes=15)
    end = now if live else pd.Timestamp(session) + pd.Timedelta(hours=15, minutes=30)
    for u in cands[:max_15m]:
        tok = inst["eq"].get(u["symbol"])
        try:
            df = ag.candles("NSE", tok, "FIFTEEN_MINUTE", t0, end)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        lv = lev_.get(u["symbol"]) or {}
        res = dow_rules(df, session, end, lv.get("PDL"), u["ltp"], u.get("volume", 0))
        if not res or sum(res[0].values()) < 8:
            continue
        f = feat_.get(u["symbol"]) or {}
        r = {"symbol": u["symbol"], "side": "PE", "scanner": "DOW EARANGUM", "price": u["ltp"], "pct": u["pct"],
             "vol_ratio": u["vol_ratio"], "rules": res[0], "info": res[1]}
        out.append(analyse(r, "PE", bu_tag, nifty_pct, nret, f, lv))
    # SL / targets (underlying)
    for r in out:
        atr, inf = r["atr"], r["info"]
        if r["side"] == "CE":
            r["sl"] = round(min(inf.get("vwap") or r["price"], r["price"] - 0.5 * atr), 2)
        else:
            r["sl"] = round(max(inf.get("hi15") or r["price"], r["price"] + 0.5 * atr), 2)
        r["targets"] = []
        r["full"] = all(r["rules"].values())
        r["found"] = now.strftime("%H:%M")
    out.sort(key=lambda r: (-int(r["full"]), -r["score"]))
    return out


# ───────────── V7: உங்கள் Chartink daily / weekly scanners ─────────────
def _daily_df(bars, u):
    """Completed daily bars + இன்றைய live candle (Chartink மாதிரி)."""
    if not bars or not bars.get("c"):
        return None
    df = pd.DataFrame({"open": bars["o"], "high": bars["h"], "low": bars["l"], "close": bars["c"], "volume": bars.get("v") or [0] * len(bars["c"])},
                      index=pd.to_datetime(bars["t"]))
    if u and u.get("ltp"):
        t = pd.Timestamp.now().normalize()
        if t not in df.index:
            df.loc[t] = [u.get("open") or u["ltp"], u.get("high") or u["ltp"], u.get("low") or u["ltp"], u["ltp"], u.get("volume") or 0]
    return df


def _weekly(df):
    return df.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()


def daily_scanners(df):
    """→ {scanner: (rules, info)} — CHAT HPY · GROK BEST ONE HOLDING 1 MONTH · MONSTER HOLDING (CE side)."""
    if df is None or len(df) < 60:
        return {}
    c, o, h, v = df["close"].values, df["open"].values, df["high"].values, df["volume"].values
    w = _weekly(df)
    if len(w) < 22:
        return {}
    wc, wo, wv = w["close"].values, w["open"].values, w["volume"].values
    s20, s50 = sma(c, 20)[-1], sma(c, 50)[-1]
    vs20 = sma(v.astype(float), 20)[-1]
    r = rsi(c)[-1]
    wr = rsi(wc)[-1]
    ws20 = sma(wc, 20)[-1]
    wvs20 = sma(wv.astype(float), 20)[-1]
    wchg = (wc[-1] - wc[-2]) / wc[-2] if wc[-2] else 0
    hi20_prev = h[-21:-1].max()
    info = {"vol_x": round(float(v[-1] / vs20), 2) if vs20 else 0, "body": round(abs(c[-1] - o[-1]) / max(h[-1] - df["low"].values[-1], 1e-9), 2),
            "vwap": float(c[-1]), "rsi_d": round(float(r), 1), "rsi_w": round(float(wr), 1), "wchg": round(wchg * 100, 2)}
    out = {}
    out["CHAT HPY"] = ({
        "Close > SMA20": c[-1] > s20, "SMA20 > SMA50": s20 > s50, "Close > Open": c[-1] > o[-1], "RSI(14) > 60": r > 60,
        "Volume > 1.5× SMA20": bool(vs20) and v[-1] > 1.5 * vs20, "Close > 20-day high": c[-1] > hi20_prev,
        "W close > W SMA20": wc[-1] > ws20, "W RSI > 55": wr > 55, "W close > last week": wc[-1] > wc[-2],
        "Close > 50": c[-1] > 50, "Avg volume > 2 lakh": vs20 > 200000}, info)
    out["GROK BEST ONE HOLDING"] = ({
        "W close > W SMA20": wc[-1] > ws20, "Week change > 4%": wchg > 0.04, "W volume > 1.5× SMA20": bool(wvs20) and wv[-1] > 1.5 * wvs20,
        "W RSI > 60": wr > 60, "W close > last week": wc[-1] > wc[-2], "1w > 2w close": wc[-2] > wc[-3], "2w > 3w close": wc[-3] > wc[-4],
        "W open ≤ last W close": wo[-1] <= wc[-2], "W close ≥ last W open": wc[-1] >= wo[-2]}, info)
    out["MONSTER HOLDING"] = ({
        "W close > W SMA20": wc[-1] > ws20, "Week change > 8%": wchg > 0.08, "W volume > 1.3× SMA20": bool(wvs20) and wv[-1] > 1.3 * wvs20,
        "W RSI > 60": wr > 60, "Close > SMA20": c[-1] > s20, "Close > SMA50": c[-1] > s50, "Volume > 2× SMA20": bool(vs20) and v[-1] > 2 * vs20,
        "W close ≥ W open": wc[-1] >= wo[-1], "Price 80–2500": 80 <= c[-1] <= 2500}, info)
    return {k: ({a: bool(b) for a, b in rr.items()}, inf) for k, (rr, inf) in out.items()}


def scan_daily(C, universe, bu_tag, nifty_pct, nret, now):
    """Daily / weekly scanners (local data — Angel call இல்லை) → holding candidates."""
    out = []
    bars_, feat_, lev_ = C.get("bars") or {}, C.get("feat") or {}, C.get("levels") or {}
    for u in universe:
        n = u["symbol"]
        try:
            res = daily_scanners(_daily_df(bars_.get(n), u))
        except Exception:
            continue
        for name, (rules, info) in res.items():
            ok = sum(rules.values())
            if ok < len(rules) - 1:
                continue
            f = feat_.get(n) or {}
            r = {"symbol": n, "side": "CE", "scanner": name, "price": u["ltp"], "pct": u["pct"], "vol_ratio": u["vol_ratio"],
                 "rules": rules, "info": info, "hold": 10 if "HOLDING" in name else 5}
            out.append(analyse(r, "CE", bu_tag, nifty_pct, nret, f, lev_.get(n) or {}))
    for r in out:
        atr = r["atr"]
        r["sl"] = round(r["price"] - 1.5 * atr, 2)
        r["targets"] = []
        r["full"] = all(r["rules"].values())
        r["found"] = now.strftime("%H:%M")
    return out
