"""👑 JACKPOT MANNAN — 3 தனி engines, ஒவ்வொன்றிலும் 10 strategies:
  🛢 Mannan Commodity (MCX) · 📊 Mannan Index (NIFTY / BANKNIFTY / FINNIFTY / SENSEX) · 📈 Mannan Stock Options (F&O stocks)

எப்படி வேலை செய்யும் (நேர்மையா):
  • ஒவ்வொரு symbol-க்கும் 10 strategies ஒரே நேரத்தில் ஓடும் → ஒவ்வொன்றும் CE / PE / வாக்கு இல்லை.
  • BEST SETUP மட்டும்: ≥2 strategies ஒரே பக்கம் + எதிர் பக்கம் 0 + score ≥75 + market திசை எதிர் இல்லை (NSE) +
    meta-label filter (backtest win வாய்ப்பு ≥50%, data போதுமானா) → அப்போ தான் call. நாளைக்கு segment-க்கு max calls.
  • Meta-labeling = ஒவ்வொரு strategy-யையும் முந்தைய நாட்களின் 5-min bars-ல் replay பண்ணி triple-barrier
    (Target 1.5R · SL 1R · 1 மணி நேரம்) result → win %. இது statistics — deep-learning ML இல்லை.
  • சில strategies "structure" (Debit spread, Covered call) — தனி signal இல்லை, call-க்கு defined-risk வழி காட்டும்.
  • Earnings calendar / EIA holiday calendar data இல்லை → gap+volume proxy / வழக்கமான US நேரம் பயன்படுத்தப்படுது.
  Paper / alert மட்டும். Guarantee இல்லை.
"""
import datetime as dt
import math
import threading

import numpy as np
import pandas as pd

from . import v4 as V

SEG = {
    "CMD": {"kind": "MANNAN-CMD", "src": "👑 Mannan Commodity", "label": "🛢 Mannan Commodity", "max_day": 10 ** 6, "min_score": 75, "min_agree": 2},
    "IDX": {"kind": "MANNAN-IDX", "src": "👑 Mannan Index", "label": "📊 Mannan Index", "max_day": 10 ** 6, "min_score": 75, "min_agree": 2},
    "STK": {"kind": "MANNAN-STK", "src": "👑 Mannan Stock Options", "label": "📈 Mannan Stock Options", "max_day": 10 ** 6, "min_score": 75, "min_agree": 2},
}
KINDS = tuple(v["kind"] for v in SEG.values())
CFG = {"meta_min_p": 0.50, "meta_min_n": 10, "bt_days": 3, "tp_r": 1.5, "bar_limit": 12, "nse_start": "09:45", "nse_end": "14:30",
       "mcx_start": "09:30", "mcx_end": "23:00", "max_stock_check": 12, "iv_expensive": 1.5, "iv_skip": 2.2}

# (key, name, best market, type) — type: signal = CE/PE வாக்கு · filter = call-ஐ வடிகட்டும் · structure = trade வடிவம்
STRATS = {
    "CMD": [("TSMOM", "Time-Series Momentum / CTA Trend", "Strong Trend", "signal"),
            ("CARRY", "Commodity Carry + Term Structure", "Futures Swing", "signal"),
            ("VOLTREND", "Volatility-Adjusted Trend Following", "Volatile Trend", "signal"),
            ("DONCHIAN", "Donchian Breakout + ATR Filter", "Breakout", "signal"),
            ("AVWAP", "Anchored VWAP + Volume Profile", "Intraday Pullback", "signal"),
            ("SWEEP", "Liquidity Sweep + MSS + FVG", "Reversal", "signal"),
            ("EIA", "Inventory / EIA Event Momentum", "Crude Oil / Natural Gas", "signal"),
            ("RV", "Cross-Commodity Relative Value", "Gold–Silver / Energy", "signal"),
            ("VWAP2SD", "VWAP 2σ Mean Reversion", "Sideways", "signal"),
            ("OFI", "Order Flow Imbalance + Absorption", "Liquid Future", "signal")],
    "IDX": [("MTF", "Regime + MTF Trend Pullback", "Trending", "signal"),
            ("GEX", "Gamma Flip (GEX) Momentum", "Negative Gamma", "signal"),
            ("SWEEP", "Liquidity Sweep + MSS + FVG", "Reversal", "signal"),
            ("AVWAP", "Anchored VWAP + Volume Profile", "Intraday Pullback", "signal"),
            ("ORB", "Opening Range Breakout + Retest", "Trending Open", "signal"),
            ("VWAP2SD", "VWAP 2σ Mean Reversion", "Sideways", "signal"),
            ("OIREPO", "OI Repositioning + Structure Break", "Index Options", "signal"),
            ("VOLCOMP", "Volatility Compression + Expansion", "Breakout", "signal"),
            ("OFDELTA", "Order Flow Delta + Absorption", "Index Futures", "signal"),
            ("META", "ML Meta-Labeling + Triple Barrier", "Signal Filtering", "filter")],
    "STK": [("RS", "Relative Strength vs NIFTY Leader", "Trend Day", "signal"),
            ("MTF", "Regime + MTF + VWAP Pullback", "Trending", "signal"),
            ("EARN", "Earnings IV Crush / Defined-Risk Spread", "Post Earnings", "signal"),
            ("UNUSUAL", "Unusual Volume + OI + Price Confirmation", "Momentum", "signal"),
            ("SWEEP", "Liquidity Sweep + MSS + FVG", "Reversal", "signal"),
            ("ATRBRK", "Volatility Expansion + ATR Breakout", "High Momentum", "signal"),
            ("SPREAD", "Bull Call / Bear Put Debit Spread", "Directional", "structure"),
            ("COVERED", "Covered Call + Stock Selection", "Holding / Income", "structure"),
            ("PAIRS", "Pairs / Sector Relative-Value", "Relative Performance", "signal"),
            ("METAIV", "ML Meta-Labeling + IV Filter", "Signal Selection", "filter")],
}
PAIRS = [("HDFCBANK", "ICICIBANK"), ("TCS", "INFY"), ("AXISBANK", "KOTAKBANK"), ("TATASTEEL", "JSWSTEEL"), ("HCLTECH", "WIPRO"),
         ("BAJFINANCE", "BAJAJFINSV"), ("MARUTI", "M&M"), ("SBIN", "BANKBARODA"), ("ONGC", "OIL"), ("HINDALCO", "VEDL"),
         ("ULTRACEMCO", "GRASIM"), ("SUNPHARMA", "CIPLA"), ("DRREDDY", "LUPIN"), ("BPCL", "HINDPETRO")]
RV_PAIRS = [("GOLD", "SILVER"), ("CRUDEOIL", "NATURALGAS")]
STATE = {s: {"time": None, "rows": [], "err": None, "covered": []} for s in SEG}
STATE["bt"] = {}
LK = threading.Lock()


# ───────────────────────── context ─────────────────────────
def _vol(df):
    return df["fvol"].fillna(0) if "fvol" in df and float(df["fvol"].fillna(0).sum()) > 0 else df["volume"].fillna(0)


def build(m5, m15=None, h1=None, d1=None, extra=None):
    """5-min bars (பல நாள், இன்று கடைசி) → strategies-க்கு தேவையான எல்லாம். None = போதுமான data இல்லை."""
    if m5 is None or len(m5) < 30:
        return None
    m5 = m5.copy()
    if "fvol" not in m5 or float(m5["fvol"].fillna(0).sum()) <= 0:
        m5["fvol"] = m5["volume"]
    days = sorted(set(m5.index.date))
    td = m5[m5.index.date == days[-1]]
    if len(td) < 3:
        return None
    prev = m5[m5.index.date == days[-2]] if len(days) >= 2 else None
    m15 = m15 if m15 is not None and len(m15) else V._resample(m5, "15min", offset=_offset(m5))
    h1 = h1 if h1 is not None and len(h1) else V._resample(m5, "60min", offset=_offset(m5))
    a5 = float(V.atr(m5).iloc[-1] or 0) or float((m5["high"] - m5["low"]).tail(14).mean() or 1e-6)
    vw, sd = V.session_vwap(td)
    hi5, lo5 = V.swings(m5.tail(120))
    pdh = float(prev["high"].max()) if prev is not None and len(prev) else None
    pdl = float(prev["low"].min()) if prev is not None and len(prev) else None
    levels = [("PDL", pdl, "low"), ("Equal lows", V.equal_levels(lo5), "low"), ("Swing low", lo5[-2][1] if len(lo5) > 1 else None, "low"),
              ("PDH", pdh, "high"), ("Equal highs", V.equal_levels(hi5), "high"), ("Swing high", hi5[-2][1] if len(hi5) > 1 else None, "high")]
    v = _vol(m5)
    vb = float(v.iloc[-21:-1].mean() or 0)
    cross = int(((td["close"] > vw) != (td["close"].shift() > vw.shift())).iloc[1:].sum()) if len(td) > 2 else 0
    e15 = V.ema(m15["close"], 20) if len(m15) else pd.Series(dtype=float)
    X = {"m5": m5, "td": td, "m15": m15, "h1": h1, "d1": d1, "px": float(td["close"].iloc[-1]), "atr": a5,
         "vw": vw, "sd": sd, "vwap": float(vw.iloc[-1]), "sdv": float(sd.iloc[-1] or 0), "pdh": pdh, "pdl": pdl, "levels": levels,
         "vx": float(v.iloc[-1] / vb) if vb else 0.0, "vbase": vb, "cross": cross,
         "slope15": float(e15.iloc[-1] - e15.iloc[-4]) if len(e15) > 4 else 0.0, "t": m5.index[-1]}
    X["h1trend"] = _trend(h1)
    X["regime"] = "SIDEWAYS" if (cross >= 4 and abs(X["px"] - X["vwap"]) < 1.0 * a5) else \
        ("UP" if X["h1trend"] == "UP" and X["px"] > X["vwap"] else "DOWN" if X["h1trend"] == "DOWN" and X["px"] < X["vwap"] else "MIXED")
    X.update(extra or {})
    return X


def _offset(df):
    t = df.index[-1]
    return "9h0min" if t.hour >= 16 or (df.index.hour < 9).any() or (df.index.time == dt.time(9, 0)).any() else "9h15min"


def _trend(df):
    if df is None or len(df) < 30:
        return "FLAT"
    c = df["close"]
    e20, e50 = V.ema(c, 20).iloc[-1], V.ema(c, min(50, len(c) - 1)).iloc[-1]
    return "UP" if c.iloc[-1] > e20 > e50 else "DOWN" if c.iloc[-1] < e20 < e50 else "FLAT"


def _sig(side, sl, why):
    return {"side": side, "sl": round(float(sl), 2) if sl is not None else None, "why": why}


def _sl_swing(X, side, n=3):
    m = X["m5"].tail(n)
    return float(m["low"].min()) - 0.2 * X["atr"] if side == "CE" else float(m["high"].max()) + 0.2 * X["atr"]


# ───────────────────────── strategies (shared) ─────────────────────────
def s_sweep(X):
    """💧 Liquidity sweep (PDH/PDL/equal/swing wick தாண்டி close உள்ளே) → அதே பக்கம் MSS (BOS/CHOCH) → அதே பக்கம் FVG."""
    m5 = X["m5"]
    sw = V.sweep(m5, X["levels"], look=12)
    if not sw:
        return None
    side = sw["side"]
    st = V.structure(m5.tail(60))
    ev = (st.get("choch_up") or st.get("bos_up")) if side == "CE" else (st.get("choch_dn") or st.get("bos_dn"))
    if not ev or ev[0] < sw["t"]:
        return None
    fv = [f for f in V.fvgs(m5, 20) if f["side"] == side and f["t"] >= sw["t"]]
    if not fv:
        return None
    tail = m5[m5.index >= pd.Timestamp(sw["t"])]
    sl = float(tail["low"].min()) - 0.1 * X["atr"] if side == "CE" else float(tail["high"].max()) + 0.1 * X["atr"]
    return _sig(side, sl, f"{sw['level']} {sw['price']} sweep → MSS {ev[1]:.1f} → FVG {fv[-1]['lo']:.1f}–{fv[-1]['hi']:.1f}")


def s_avwap(X):
    """⚓ Anchored VWAP (இன்றைய low / high-ல் இருந்து) + Volume profile POC/VAL — trend-ல் pullback தொட்டு மறுபடி ஏறினா."""
    td, a = X["td"], X["atr"]
    if len(td) < 8:
        return None
    up = X["px"] > X["vwap"] and X["slope15"] > 0
    dn = X["px"] < X["vwap"] and X["slope15"] < 0
    if not (up or dn):
        return None
    side = "CE" if up else "PE"
    i0 = int(np.argmin(td["low"].values)) if up else int(np.argmax(td["high"].values))
    seg = td.iloc[i0:]
    if len(seg) < 4:
        return None
    tp = (seg["high"] + seg["low"] + seg["close"]) / 3
    w = _vol(seg).replace(0, np.nan).fillna(1)
    av = float((tp * w).sum() / w.sum())
    vp = V.volume_profile(td) or {}
    zone = [x for x in (av, vp.get("poc"), vp.get("val") if up else vp.get("vah")) if x]
    last, prv = td.iloc[-1], td.iloc[-2]
    if up:
        touch = any(abs(float(min(last["low"], prv["low"])) - z) <= 0.35 * a for z in zone)
        ok = touch and last["close"] > last["open"] and last["close"] > prv["high"] and last["close"] > av
    else:
        touch = any(abs(float(max(last["high"], prv["high"])) - z) <= 0.35 * a for z in zone)
        ok = touch and last["close"] < last["open"] and last["close"] < prv["low"] and last["close"] < av
    if not ok:
        return None
    return _sig(side, _sl_swing(X, side), f"AVWAP {av:.1f}" + (f" · POC {vp['poc']}" if vp.get("poc") else "") + " pullback → resume")


def s_vwap2sd(X):
    """〰 VWAP ±2σ தாண்டி திரும்ப band உள்ளே close (rejection wick) — sideways நாள் மட்டும்."""
    td = X["td"]
    if X["regime"] != "SIDEWAYS" and X["cross"] < 3 or len(td) < 10 or not X["sdv"]:
        return None
    vw, sd = X["vw"], X["sd"]
    p, l_ = td.iloc[-2], td.iloc[-1]
    up2, dn2 = float(vw.iloc[-2] + 2 * sd.iloc[-2]), float(vw.iloc[-2] - 2 * sd.iloc[-2])
    rng = float(l_["high"] - l_["low"]) or 1e-9
    if p["high"] > up2 and l_["close"] < float(vw.iloc[-1] + 2 * sd.iloc[-1]) and (l_["high"] - max(l_["open"], l_["close"])) / rng >= 0.35:
        return _sig("PE", max(p["high"], l_["high"]) + 0.2 * X["atr"], f"+2σ {up2:.1f} reject → VWAP {X['vwap']:.1f} target")
    if p["low"] < dn2 and l_["close"] > float(vw.iloc[-1] - 2 * sd.iloc[-1]) and (min(l_["open"], l_["close"]) - l_["low"]) / rng >= 0.35:
        return _sig("CE", min(p["low"], l_["low"]) - 0.2 * X["atr"], f"−2σ {dn2:.1f} reject → VWAP {X['vwap']:.1f} target")
    return None


def s_donchian(X, n=20):
    """📦 15-min Donchian 20 breakout + ATR விரிவு (ATR now ≥1.1× avg) + body ≥0.5 ATR."""
    m = X["m15"]
    if m is None or len(m) < n + 15:
        return None
    a = V.atr(m)
    hi, lo = float(m["high"].iloc[-n - 1:-1].max()), float(m["low"].iloc[-n - 1:-1].min())
    last, an = m.iloc[-1], float(a.iloc[-1] or 0)
    if not an or an < 1.1 * float(a.iloc[-21:-1].mean() or 0):
        return None
    body = abs(float(last["close"] - last["open"]))
    if last["close"] > hi and body >= 0.5 * an:
        return _sig("CE", max(float(last["low"]), (hi + lo) / 2), f"15m Donchian {n} high {hi:.1f} break · ATR விரிவு")
    if last["close"] < lo and body >= 0.5 * an:
        return _sig("PE", min(float(last["high"]), (hi + lo) / 2), f"15m Donchian {n} low {lo:.1f} break · ATR விரிவு")
    return None


def s_volcomp(X):
    """🗜 Bollinger bandwidth கடைசி 150-ல் கீழ் 20% (compression) → 1.5 ATR range candle band-க்கு வெளியே close (expansion)."""
    m = X["m5"]
    if len(m) < 160:
        return None
    c = m["close"]
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    bw = (4 * sd / mid).dropna()
    if len(bw) < 150 or float(bw.iloc[-7:-1].min()) > float(bw.iloc[-150:].quantile(0.2)):
        return None
    last = m.iloc[-1]
    if float(last["high"] - last["low"]) < 1.5 * X["atr"]:
        return None
    if last["close"] > mid.iloc[-1] + 2 * sd.iloc[-1]:
        return _sig("CE", float(last["low"]), "Squeeze (low bandwidth) → upper band expansion")
    if last["close"] < mid.iloc[-1] - 2 * sd.iloc[-1]:
        return _sig("PE", float(last["high"]), "Squeeze (low bandwidth) → lower band expansion")
    return None


def s_orb(X, bars=3, until="12:30"):
    """🔔 Opening range (முதல் 15 நிமிடம்) 5m close-ல் break → OR edge retest → மறுபடி edge-க்கு மேல் close."""
    td = X["td"]
    if len(td) < bars + 3 or td.index[-1].strftime("%H:%M") > until:
        return None
    orh, orl = float(td["high"].iloc[:bars].max()), float(td["low"].iloc[:bars].min())
    rest, a = td.iloc[bars:], X["atr"]
    for side, edge in (("CE", orh), ("PE", orl)):
        ce = side == "CE"
        brk = rest[(rest["close"] > edge) if ce else (rest["close"] < edge)]
        if brk.empty:
            continue
        after = rest[rest.index > brk.index[0]]
        if after.empty:
            continue
        last = after.iloc[-1]
        tests = after[(after["low"] <= edge + 0.15 * a) if ce else (after["high"] >= edge - 0.15 * a)]
        if tests.empty or tests.index[-1] < after.index[-2 if len(after) > 1 else -1]:
            continue
        held = (last["close"] > edge and last["close"] > last["open"]) if ce else (last["close"] < edge and last["close"] < last["open"])
        if held:
            return _sig(side, (edge - 0.5 * a) if ce else (edge + 0.5 * a), f"OR {orl:.1f}–{orh:.1f} break → retest {edge:.1f} hold")
    return None


def s_mtf(X):
    """🧭 1H EMA20>50 + 15m EMA rising + 5m EMA20 / VWAP-க்கு pullback → முந்தைய bar high-ஐ தாண்டி close."""
    m5, a = X["m5"], X["atr"]
    e5 = V.ema(m5["close"], 20)
    l_, p = m5.iloc[-1], m5.iloc[-2]
    for side in ("CE", "PE"):
        ce = side == "CE"
        if X["h1trend"] != ("UP" if ce else "DOWN") or (X["slope15"] > 0) != ce:
            continue
        zone = [float(e5.iloc[-1]), X["vwap"]]
        ext = min(l_["low"], p["low"]) if ce else max(l_["high"], p["high"])
        touch = any(abs(float(ext) - z) <= 0.3 * a for z in zone)
        go = (l_["close"] > p["high"] and l_["close"] > e5.iloc[-1]) if ce else (l_["close"] < p["low"] and l_["close"] < e5.iloc[-1])
        if touch and go:
            return _sig(side, _sl_swing(X, side), f"1H {X['h1trend']} · 15m slope {X['slope15']:+.1f} · EMA20/VWAP pullback → resume")
    return None


def s_ofabs(X, imb=None):
    """⚖ Order flow: கடைசி 3 bars delta proxy (close-open)/range × volume + absorption (அதிக volume, சின்ன range, day extreme அருகில்)."""
    td, a = X["td"], X["atr"]
    if len(td) < 8 or not X["vbase"]:
        return None
    v = _vol(td)
    rng = (td["high"] - td["low"]).replace(0, np.nan)
    d = ((td["close"] - td["open"]) / rng * v).fillna(0)
    dn = float(d.tail(3).sum() / max(float(v.tail(3).sum()), 1))
    lo, hi = float(td["low"].min()), float(td["high"].max())
    for side in ("CE", "PE"):
        ce = side == "CE"
        flow = dn >= 0.3 if ce else dn <= -0.3
        if imb is not None:
            flow = flow or (imb >= 1.3 if ce else imb <= 0.77)
        if not flow:
            continue
        for i in range(len(td) - 4, len(td) - 1):
            if i < 1:
                continue
            b = td.iloc[i]
            absorb = float(v.iloc[i]) >= 1.8 * X["vbase"] and float(b["high"] - b["low"]) <= 0.6 * a
            near = (b["low"] <= lo + 0.5 * a) if ce else (b["high"] >= hi - 0.5 * a)
            conf = (td["close"].iloc[-1] > b["high"]) if ce else (td["close"].iloc[-1] < b["low"])
            if absorb and near and conf:
                return _sig(side, (float(b["low"]) - 0.2 * a) if ce else (float(b["high"]) + 0.2 * a),
                            f"Absorption {td.index[i].strftime('%H:%M')} · delta {dn:+.2f}" + (f" · bid/ask {imb:.2f}" if imb else ""))
    return None


# ───────────────────────── commodity-only ─────────────────────────
def _d1_ret(d1, n):
    c = d1["close"].values
    return float(c[-1] / c[-n - 1] - 1) if len(c) > n else None


def s_tsmom(X):
    """📈 CTA time-series momentum: 20/60/120-நாள் returns ஒரே sign (இருக்கிறவை எல்லாம்) + 1H trend அதே பக்கம்."""
    d1 = X.get("d1")
    if d1 is None or len(d1) < 25:
        return None
    rs = [r for r in (_d1_ret(d1, 20), _d1_ret(d1, 60), _d1_ret(d1, 120)) if r is not None]
    if len(rs) < 1 or not (all(r > 0 for r in rs) or all(r < 0 for r in rs)):
        return None
    side = "CE" if rs[0] > 0 else "PE"
    if X["h1trend"] != ("UP" if side == "CE" else "DOWN"):
        return None
    m = X["m15"].tail(8)
    sl = float(m["low"].min()) if side == "CE" else float(m["high"].max())
    return _sig(side, sl, "Returns " + " / ".join(f"{r * 100:+.1f}%" for r in rs) + " (20/60/120d) · 1H அதே திசை")


def s_voltrend(X):
    """📉 Vol-adjusted trend: 20-நாள் return ÷ (daily vol × √20) = t-stat ≥1 + 1H & VWAP அதே பக்கம்."""
    d1 = X.get("d1")
    if d1 is None or len(d1) < 25:
        return None
    lr = np.log(d1["close"]).diff().dropna()
    vol = float(lr.tail(20).std() or 0)
    if not vol:
        return None
    t = float(np.log(d1["close"].iloc[-1] / d1["close"].iloc[-21])) / (vol * math.sqrt(20))
    side = "CE" if t >= 1 else "PE" if t <= -1 else None
    if not side or X["h1trend"] != ("UP" if side == "CE" else "DOWN") or ((X["px"] > X["vwap"]) != (side == "CE")):
        return None
    return _sig(side, _sl_swing(X, side, 6), f"t-stat {t:+.2f} (vol {vol * 100:.1f}%/day) · 1H + VWAP அதே பக்கம்")


def s_carry(X):
    """🏷 Carry: அடுத்த மாத future vs இந்த மாதம் — backwardation = CE carry · steep contango = PE carry; intraday trend ஒத்துப்போனா மட்டும்."""
    near, nxt, days = X.get("near_px"), X.get("next_px"), X.get("roll_days")
    if not (near and nxt and days):
        return None
    ann = (nxt / near - 1) * 365 / max(days, 1) * 100
    side = "CE" if ann <= -2 else "PE" if ann >= 8 else None
    if not side or (X["slope15"] > 0) != (side == "CE") or ((X["px"] > X["vwap"]) != (side == "CE")):
        return None
    return _sig(side, _sl_swing(X, side, 6), f"Term structure {ann:+.1f}%/yr ({'backwardation' if ann < 0 else 'contango'}) · trend அதே")


EIA = {"CRUDEOIL": (2, "Crude EIA (Wed)"), "NATURALGAS": (3, "Nat-gas storage (Thu)")}


def eia_time(name, day):
    """US 10:30 New York → IST (DST தானா). Holiday shift data இல்லை."""
    if name not in EIA or day.weekday() != EIA[name][0]:
        return None
    try:
        from zoneinfo import ZoneInfo
        t = dt.datetime.combine(day, dt.time(10, 30), tzinfo=ZoneInfo("America/New_York")).astimezone(ZoneInfo("Asia/Kolkata"))
        return pd.Timestamp(t.replace(tzinfo=None))
    except Exception:
        return pd.Timestamp(dt.datetime.combine(day, dt.time(20, 0)))


def s_eia(X, name):
    """🛢 EIA / storage report: release-க்கு பிறகு முதல் 5-min candle range → 5–60 நிமிடத்தில் volume ≥1.5× உடன் close-ல் break."""
    rt = eia_time(name, X["t"].date())
    if rt is None:
        return None
    td = X["td"]
    rb = td[(td.index >= rt) & (td.index < rt + pd.Timedelta(minutes=5))]
    after = td[td.index >= rt + pd.Timedelta(minutes=5)]
    if rb.empty or after.empty or X["t"] > rt + pd.Timedelta(minutes=60):
        return None
    hi, lo = float(rb["high"].max()), float(rb["low"].min())
    l_ = after.iloc[-1]
    if X["vx"] < 1.5:
        return None
    if l_["close"] > hi:
        return _sig("CE", lo, f"{EIA[name][1]} {rt.strftime('%H:%M')} release candle {lo:.1f}–{hi:.1f} மேல் break")
    if l_["close"] < lo:
        return _sig("PE", hi, f"{EIA[name][1]} {rt.strftime('%H:%M')} release candle {lo:.1f}–{hi:.1f} கீழ் break")
    return None


def rv_z(a_h1, b_h1):
    """A/B ratio (1H closes) z-score + கடைசி 2 bars-ல் திரும்புதா."""
    j = pd.concat([a_h1["close"].rename("a"), b_h1["close"].rename("b")], axis=1).dropna()
    if len(j) < 40:
        return None, None
    r = np.log(j["a"] / j["b"])
    z = float((r.iloc[-1] - r.iloc[:-1].mean()) / (r.iloc[:-1].std() or 1e-9))
    return round(z, 2), float(r.iloc[-1] - r.iloc[-3])


def s_rv(X, name, rv):
    """⚖ Gold/Silver · Crude/NatGas ratio |z| ≥2 + ratio திரும்ப ஆரம்பிச்சா → மலிவான leg CE / விலை அதிகமான leg PE (single-leg)."""
    for (a, b), (z, turn) in (rv or {}).items():
        if z is None or name not in (a, b) or abs(z) < 2:
            continue
        if z >= 2 and turn < 0:          # A விலை அதிகம் → A PE / B CE
            side = "PE" if name == a else "CE"
        elif z <= -2 and turn > 0:
            side = "CE" if name == a else "PE"
        else:
            continue
        return _sig(side, _sl_swing(X, side, 6), f"{a}/{b} ratio z {z:+.2f} → mean revert ({'திரும்புது' if turn else ''})")
    return None


# ───────────────────────── index-only ─────────────────────────
def s_gex(X):
    """💥 Gamma flip: negative gamma zone-ல் spot flip-ஐ 5m close-ல் தாண்டினா dealers hedging → momentum."""
    g = X.get("gex") or {}
    flip = g.get("flip")
    if not flip or "NEG" not in str(g.get("zone", "")).upper():
        return None
    c = X["m5"]["close"]
    if c.iloc[-1] > flip and c.iloc[-3:-1].min() <= flip:
        return _sig("CE", flip - 0.5 * X["atr"], f"Spot flip {flip} மேல் · negative gamma")
    if c.iloc[-1] < flip and c.iloc[-3:-1].max() >= flip:
        return _sig("PE", flip + 0.5 * X["atr"], f"Spot flip {flip} கீழ் · negative gamma")
    return None


def s_oirepo(X):
    """🔄 ATM அருகில் OI மாற்றம்: PE writing / CE unwinding = bullish (மறுபக்கம் bearish) + கடைசி 6 bars-ல் அதே பக்கம் BOS/CHOCH."""
    oi = X.get("oi")
    if not oi:
        return None
    ce_, pe_ = oi.get("ce_chg") or 0, oi.get("pe_chg") or 0
    bull = (pe_ > 0 and pe_ >= 1.3 * max(ce_, 1)) or (ce_ < 0 and pe_ >= 0)
    bear = (ce_ > 0 and ce_ >= 1.3 * max(pe_, 1)) or (pe_ < 0 and ce_ >= 0)
    if bull == bear:
        return None
    side = "CE" if bull else "PE"
    st = V.structure(X["m5"].tail(60))
    ev = (st.get("choch_up") or st.get("bos_up")) if bull else (st.get("choch_dn") or st.get("bos_dn"))
    if not ev or pd.Timestamp(ev[0]) < X["m5"].index[-7]:
        return None
    return _sig(side, _sl_swing(X, side, 4), f"OI: CE {ce_:+,} · PE {pe_:+,} → {'PE writing / CE unwind' if bull else 'CE writing / PE unwind'} + structure break {ev[1]:.1f}")


# ───────────────────────── stock-only ─────────────────────────
def s_rs(X):
    """🏆 Relative strength: stock − NIFTY ≥ ±1.5% + VWAP + 15m slope + day open-க்கு மேல்/கீழ்."""
    sp, npct = X.get("pct"), X.get("npct")
    if sp is None or npct is None:
        return None
    rs, o = sp - npct, float(X["td"]["open"].iloc[0])
    if rs >= 1.5 and X["px"] > X["vwap"] and X["slope15"] > 0 and X["px"] > o:
        return _sig("CE", max(X["vwap"] - 0.3 * X["atr"], _sl_swing(X, "CE", 6)), f"RS vs NIFTY {rs:+.1f}% · VWAP மேல்")
    if rs <= -1.5 and X["px"] < X["vwap"] and X["slope15"] < 0 and X["px"] < o:
        return _sig("PE", min(X["vwap"] + 0.3 * X["atr"], _sl_swing(X, "PE", 6)), f"RS vs NIFTY {rs:+.1f}% · VWAP கீழ்")
    return None


def s_earn(X):
    """📣 Results / event day proxy: gap ≥3% + day volume ≥2.5× → 10:15 பிறகு முதல் 30-min range-ஐ gap பக்கம் தாண்டினா. IV crush → spread பரிந்துரை."""
    d1, td = X.get("d1"), X["td"]
    if d1 is None or len(d1) < 2 or len(td) < 7 or td.index[-1].strftime("%H:%M") < "10:15":
        return None
    pc = float(d1["close"].iloc[-1]) if d1.index[-1].date() < td.index[-1].date() else float(d1["close"].iloc[-2])
    gap = float(td["open"].iloc[0]) / pc - 1 if pc else 0
    if abs(gap) < 0.03 or (X.get("vr") or 0) < 2.5:
        return None
    h30, l30 = float(td["high"].iloc[:6].max()), float(td["low"].iloc[:6].min())
    if gap > 0 and X["px"] > h30:
        return _sig("CE", l30, f"Event gap {gap * 100:+.1f}% · vol {X.get('vr')}× · 30m high {h30:.1f} break (IV crush → spread நல்லது)")
    if gap < 0 and X["px"] < l30:
        return _sig("PE", h30, f"Event gap {gap * 100:+.1f}% · vol {X.get('vr')}× · 30m low {l30:.1f} break (IV crush → spread நல்லது)")
    return None


def s_unusual(X):
    """🚨 Day volume ≥3× + futures OI build-up அதே பக்கம் + கடைசி 1 மணி high/low-ஐ 5m close-ல் தாண்டல்."""
    vr, oi = X.get("vr") or 0, X.get("oi_tag") or ""
    if vr < 3:
        return None
    m = X["m5"]
    hi, lo = float(m["high"].iloc[-13:-1].max()), float(m["low"].iloc[-13:-1].min())
    c = X["px"]
    if c > hi and oi in ("Long Built Up", "Short Covering"):
        return _sig("CE", _sl_swing(X, "CE", 4), f"Volume {vr}× · OI {oi} · 1h high {hi:.1f} break")
    if c < lo and oi in ("Short Built Up", "Long Unwinding"):
        return _sig("PE", _sl_swing(X, "PE", 4), f"Volume {vr}× · OI {oi} · 1h low {lo:.1f} break")
    return None


def s_atrbrk(X):
    """⚡ இன்றைய range ≥1.3× daily ATR14 (expansion) + கடைசி 1 மணி high/low break + 5m candle ≥1.2 ATR."""
    d1, td, m = X.get("d1"), X["td"], X["m5"]
    if d1 is None or len(d1) < 16:
        return None
    pc = d1["close"].shift()
    tr = pd.concat([d1["high"] - d1["low"], (d1["high"] - pc).abs(), (d1["low"] - pc).abs()], axis=1).max(axis=1)
    datr = float(tr.tail(14).mean() or 0)
    if not datr or float(td["high"].max() - td["low"].min()) < 1.3 * datr:
        return None
    l_ = m.iloc[-1]
    if float(l_["high"] - l_["low"]) < 1.2 * X["atr"]:
        return None
    hi, lo = float(m["high"].iloc[-13:-1].max()), float(m["low"].iloc[-13:-1].min())
    if l_["close"] > hi:
        return _sig("CE", float(l_["low"]), f"Day range {float(td['high'].max() - td['low'].min()) / datr:.1f}× ATR · 1h high break")
    if l_["close"] < lo:
        return _sig("PE", float(l_["high"]), f"Day range {float(td['high'].max() - td['low'].min()) / datr:.1f}× ATR · 1h low break")
    return None


def pairs_z(bars, a, b, la=None, lb=None):
    """Daily closes (C['bars']) ratio z-score 60 நாள் + இன்றைய live price."""
    A, B = (bars or {}).get(a), (bars or {}).get(b)
    if not A or not B:
        return None
    sa, sb = pd.Series(A["c"], index=A["t"]), pd.Series(B["c"], index=B["t"])
    j = pd.concat([sa.rename("a"), sb.rename("b")], axis=1).dropna().tail(60)
    if len(j) < 30:
        return None
    r = np.log(j["a"] / j["b"])
    now_r = math.log(la / lb) if la and lb else float(r.iloc[-1])
    return round(float((now_r - r.mean()) / (r.std() or 1e-9)), 2)


def s_pairs(X):
    """👯 Pairs: daily ratio z ≥ ±2 + இன்று laggard மேல் போகுது (convergence ஆரம்பம்) → laggard CE / leader PE."""
    sym, P = X.get("symbol"), X.get("pairs") or {}
    for (a, b), z in P.items():
        if z is None or sym not in (a, b) or abs(z) < 2:
            continue
        cheap = b if z >= 2 else a                 # z ≥2 → A விலை அதிகம்
        side = "CE" if sym == cheap else "PE"
        if (X["slope15"] > 0) != (side == "CE"):
            continue
        return _sig(side, _sl_swing(X, side, 6), f"{a}/{b} ratio z {z:+.2f} → {cheap} மலிவு")
    return None


# ───────────────────────── segment → strategies ─────────────────────────
def fns(seg, name=None):
    """seg-க்கு (key → fn(X)) — எல்லாம் X மட்டும் வாங்கும் (backtest-க்கும் இதே)."""
    if seg == "CMD":
        return {"TSMOM": s_tsmom, "CARRY": s_carry, "VOLTREND": s_voltrend, "DONCHIAN": s_donchian, "AVWAP": s_avwap,
                "SWEEP": s_sweep, "EIA": lambda X: s_eia(X, name), "RV": lambda X: s_rv(X, name, X.get("rv")),
                "VWAP2SD": s_vwap2sd, "OFI": lambda X: s_ofabs(X, X.get("imb"))}
    if seg == "IDX":
        return {"MTF": s_mtf, "GEX": s_gex, "SWEEP": s_sweep, "AVWAP": s_avwap, "ORB": s_orb, "VWAP2SD": s_vwap2sd,
                "OIREPO": s_oirepo, "VOLCOMP": s_volcomp, "OFDELTA": lambda X: s_ofabs(X)}
    return {"RS": s_rs, "MTF": s_mtf, "EARN": s_earn, "UNUSUAL": s_unusual, "SWEEP": s_sweep, "ATRBRK": s_atrbrk, "PAIRS": s_pairs}


BT_OK = {"CMD": ("DONCHIAN", "AVWAP", "SWEEP", "VWAP2SD", "OFI"), "IDX": ("MTF", "SWEEP", "AVWAP", "ORB", "VWAP2SD", "VOLCOMP", "OFDELTA"),
         "STK": ("MTF", "SWEEP")}          # முந்தைய bars-ல் மட்டும் கணக்கிட முடியும் strategies (OI / GEX / daily live data தேவை இல்லாதவை)


def evaluate(seg, X, name=None):
    out = {}
    for k, fn in fns(seg, name).items():
        try:
            out[k] = fn(X)
        except Exception as e:
            out[k] = {"err": str(e)[:60]}
    return out


# ───────────────────────── meta-labeling (triple barrier replay) ─────────────────────────
def triple_barrier(m5, i, side, sl, atr, tp_r=None, limit=None):
    """bar i close-ல் entry → +tp_r×R target · SL · `limit` bars (அதே நாள்) → 1 win / 0 loss."""
    tp_r, limit = tp_r or CFG["tp_r"], limit or CFG["bar_limit"]
    e = float(m5["close"].iloc[i])
    R = min(max(abs(e - (sl if sl else e - atr)), 0.5 * atr), 2.0 * atr)
    ce = side == "CE"
    tp, sp = (e + tp_r * R, e - R) if ce else (e - tp_r * R, e + R)
    day = m5.index[i].date()
    j = i
    for j in range(i + 1, min(len(m5), i + 1 + limit)):
        b = m5.iloc[j]
        if b.name.date() != day:
            break
        hit_sl = b["low"] <= sp if ce else b["high"] >= sp
        hit_tp = b["high"] >= tp if ce else b["low"] <= tp
        if hit_sl:
            return 0
        if hit_tp:
            return 1
    c = float(m5["close"].iloc[min(j, len(m5) - 1)])
    return int((c - e) > 0 if ce else (e - c) > 0)


def backtest(seg, m5, name=None, extra=None, step=2):
    """முந்தைய `bt_days` நாட்களின் 5-min bars-ல் replay → {key: [n, wins]}."""
    days = sorted(set(m5.index.date))[:-1][-CFG["bt_days"]:]
    keys = BT_OK[seg]
    st = {k: [0, 0] for k in keys}
    if not days:
        return st
    m15f = V._resample(m5, "15min", offset=_offset(m5))
    h1f = V._resample(m5, "60min", offset=_offset(m5))
    F = fns(seg, name)
    idx = [i for i, t in enumerate(m5.index) if t.date() in days]
    last_sig = {}
    for i in idx[8::step]:
        t = m5.index[i]
        sub = m5.iloc[: i + 1].tail(400)
        X = build(sub, m15f[m15f.index + pd.Timedelta(minutes=15) <= t + pd.Timedelta(minutes=5)],
                  h1f[h1f.index + pd.Timedelta(minutes=60) <= t + pd.Timedelta(minutes=5)], None, extra)
        if not X:
            continue
        for k in keys:
            try:
                s = F[k](X)
            except Exception:
                s = None
            if not s or not s.get("side"):
                continue
            if last_sig.get(k) and (t - last_sig[k]).total_seconds() < 1800:      # ஒரே signal-ஐ திரும்ப திரும்ப count பண்ணாது
                continue
            last_sig[k] = t
            st[k][0] += 1
            st[k][1] += triple_barrier(m5, i, s["side"], s.get("sl"), X["atr"])
    return st


def bt_get(seg, sym, m5, name=None, extra=None, day=None):
    """நாளுக்கு ஒருமுறை symbol-க்கு backtest (cache)."""
    key = f"{seg}|{sym}|{day}"
    B = STATE["bt"]
    if key not in B:
        try:
            B[key] = backtest(seg, m5, name, extra)
        except Exception:
            B[key] = {}
        for k_ in [k_ for k_ in B if not k_.endswith(str(day))]:
            B.pop(k_, None)
    return B[key]


def seg_stats(seg, live=None):
    """Segment-ன் எல்லா symbols backtest + live முடிந்த calls → strategy-க்கு {bt_n, bt_w, live_n, live_w, live_net, p}."""
    out = {k: {"bt_n": 0, "bt_w": 0, "live_n": 0, "live_w": 0, "live_net": 0} for k, *_ in STRATS[seg]}
    for key, st in STATE["bt"].items():
        if key.startswith(seg + "|"):
            for k, (n, w) in (st or {}).items():
                out[k]["bt_n"] += n
                out[k]["bt_w"] += w
    for c in live or []:
        for k in ((c.get("mannan") or {}).get("strats") or []):
            if k in out:
                out[k]["live_n"] += 1
                out[k]["live_w"] += int((c.get("pnl_lot") or 0) > 0)
                out[k]["live_net"] += c.get("pnl_lot") or 0
    for k, v in out.items():
        n, w = v["bt_n"] + v["live_n"] * 2, v["bt_w"] + v["live_w"] * 2          # live result-க்கு 2× weight
        v["p"] = round((w + 1) / (n + 2), 3) if n else None
        v["n"] = v["bt_n"] + v["live_n"]
        v["tested"] = v["n"] >= CFG["meta_min_n"]
    return out


def meta_p(seg, keys, stats):
    """வாக்கு போட்ட strategies-ன் sample-weighted win வாய்ப்பு. data போதலைன்னா None (= Test needed)."""
    xs = [(stats[k]["p"], stats[k]["n"]) for k in keys if k in stats and stats[k]["p"] is not None and stats[k]["n"] >= 3]
    tot = sum(n for _, n in xs)
    if tot < CFG["meta_min_n"]:
        return None, tot
    return round(sum(p * n for p, n in xs) / tot, 3), tot


# ───────────────────────── confluence → best setup ─────────────────────────
def confluence(seg, sigs, X, stats, mdir=None):
    """→ row: side, votes, opp, score, meta_p, ok, why_not."""
    votes = {"CE": [], "PE": []}
    for k, s in sigs.items():
        if s and s.get("side") in votes:
            votes[s["side"]].append(k)
    side = "CE" if len(votes["CE"]) > len(votes["PE"]) else "PE" if len(votes["PE"]) > len(votes["CE"]) else None
    row = {"votes": votes, "side": side, "regime": X.get("regime"), "px": round(X["px"], 2), "atr": round(X["atr"], 2),
           "vwap": round(X["vwap"], 2), "time": X["t"].strftime("%H:%M") if hasattr(X["t"], "strftime") else str(X["t"])}
    if not side:
        row.update(score=0, ok=False, why_not=["எந்த பக்கமும் வாக்கு இல்லை / சமம்"])
        return row
    agree, opp = votes[side], votes["PE" if side == "CE" else "CE"]
    mp, mn = meta_p(seg, agree, stats)
    fit = int((X.get("regime") == "SIDEWAYS") == ("VWAP2SD" in agree)) if agree else 0
    sc = 35 + 15 * len(agree) - 20 * len(opp) + 5 * fit + (round((mp - 0.5) * 60) if mp is not None else 0)
    if mdir and seg != "CMD":
        sc += 5 if (mdir == "UP") == (side == "CE") else -15
    sc = int(max(0, min(100, sc)))
    sls = [sigs[k]["sl"] for k in agree if sigs[k].get("sl")]
    ce = side == "CE"
    sl = (max(s for s in sls if s < X["px"]) if any(s < X["px"] for s in sls) else None) if ce else \
        (min(s for s in sls if s > X["px"]) if any(s > X["px"] for s in sls) else None)
    if sl is None:
        sl = X["px"] - X["atr"] if ce else X["px"] + X["atr"]
    if abs(X["px"] - sl) < 0.4 * X["atr"]:                 # மிக நெருக்கம் → noise
        sl = X["px"] - 0.6 * X["atr"] if ce else X["px"] + 0.6 * X["atr"]
    why_not = []
    if len(agree) < SEG[seg]["min_agree"]:
        why_not.append(f"{len(agree)} strategy மட்டும் ({SEG[seg]['min_agree']} வேணும்)")
    if opp:
        why_not.append(f"எதிர் பக்கம் {', '.join(opp)}")
    if sc < SEG[seg]["min_score"]:
        why_not.append(f"score {sc} < {SEG[seg]['min_score']}")
    if mp is not None and mp < CFG["meta_min_p"]:
        why_not.append(f"meta-label {round(mp * 100)}% < {round(CFG['meta_min_p'] * 100)}%")
    if mdir and seg != "CMD" and (mdir == "UP") != ce:
        why_not.append(f"Market திசை {'⬆' if mdir == 'UP' else '⬇'} எதிர்")
    row.update(score=sc, agree=agree, opp=opp, meta_p=mp, meta_n=mn, sl=round(sl, 2), ok=not why_not, why_not=why_not,
               why=[f"{k}: {sigs[k]['why']}" for k in agree])
    return row


def _hm_ok(seg, now):
    hm = now.strftime("%H:%M")
    return (CFG["mcx_start"] <= hm <= CFG["mcx_end"]) if seg == "CMD" else (CFG["nse_start"] <= hm <= CFG["nse_end"])


def _ul_targets(px, sl, side, n=(1.0, 2.0, 3.0)):
    R = abs(px - sl)
    s = 1 if side == "CE" else -1
    return [round(px + s * k * R, 2) for k in n]


# ───────────────────────── calls ─────────────────────────
def to_call(seg, row, opt, now):
    """Best setup → STORE call (kind MANNAN-*) · segment-க்கு நாளைக்கு max · symbol-க்கு ஒன்று (MCX: 2 மணி நேரத்துக்கு ஒன்று)."""
    from .calls import CALLS_LOCK, STORE, _new, tg
    S = SEG[seg]
    day = str(now.date())
    with CALLS_LOCK:
        d = STORE.load()
        mine = [x for x in d["calls"].values() if x["date"] == day and x["kind"] == S["kind"] and not x.get("shadow")]
        if len(mine) >= S["max_day"]:
            return None, f"இன்றைய max {S['max_day']} calls முடிந்தது"
        for x in mine:
            if x["symbol"] == row["symbol"] and (seg != "CMD" or (now - pd.Timestamp(x["signal_time"])).total_seconds() < 7200):
                return None, f"{row['symbol']} இன்று ஏற்கனவே Mannan call இருக்கு"
        rr = {"symbol": row["symbol"], "price": row["px"], "sl": row["sl"], "targets": row.get("ul_targets") or [], "stars": 5,
              "score": row["score"], "vol_ratio": row.get("vr"),
              "confidence": f"👑 {len(row['agree'])}/10 strategies · score {row['score']}" + (f" · meta {round(row['meta_p'] * 100)}%" if row.get("meta_p") else ""),
              "reasons": [f"👑 {S['label']} — {', '.join(row['agree'])}"] + row["why"][:5]}
        c = _new(S["kind"], S["src"], rr, opt, now, day)
        if not c:
            return None, _why_rejected(S["kind"], row["symbol"]) or "Plan / quality gate fail (SL / RR / நேரம்)"
        if c["id"] in d["calls"]:
            return None, "ஏற்கனவே உள்ள call"
        if c.get("shadow"):
            return None, c.get("shadow_why") or "module pause"
        c.update(grade="A", qcodes=[], qtext=[], source_label=S["label"], intraday=True,
                 mannan={"seg": seg, "strats": row["agree"], "score": row["score"], "meta_p": row.get("meta_p"), "regime": row.get("regime"),
                         "spread": row.get("spread"), "iv": row.get("iv")})
        d["calls"][c["id"]] = c
        STORE.dirty = True
        STORE.save(force=True)
    try:
        tg(f"👑 JACKPOT MANNAN · {S['label']}\nBUY {c['symbol']} {c['strike']:g} {c['side']} (exp {c['expiry']})\n"
           f"Strategies: {', '.join(row['agree'])} · score {row['score']}\nEntry ₹{c['entry']} · SL ₹{c['sl']} · T1/T2/T3 {' / '.join(str(t) for t in c['targets'])} (paper)",
           f"mannan|{c['id']}")
    except Exception:
        pass
    return c, None


def _why_rejected(kind, sym):
    """calls.py quality gate (_reject) பதிவு செய்த உண்மையான காரணம்."""
    try:
        from .calls import SKIPPED
        for x in reversed(SKIPPED.get("log") or []):
            if x.get("kind") == kind and x.get("symbol") == sym:
                return f"Quality gate {x.get('code')}: {x.get('detail') or ''}".strip()[:140]
    except Exception:
        pass
    return None


def _log(seg, now, r, result):
    L = STATE[seg].setdefault("log", [])
    if L and L[0].get("day") != str(now.date()):
        L.clear()
    L.insert(0, {"day": str(now.date()), "time": now.strftime("%H:%M"), "symbol": r.get("symbol"), "side": r.get("side"),
                 "score": r.get("score"), "agree": r.get("agree") or [], "result": result})
    del L[30:]


def _finish(seg, rows, now, plan_fn):
    """rows → score வரிசை. Top 2 BEST (ok) setups-க்கு எப்போதும் strike + entry / SL / targets (plan_fn) →
    call நேரம் + gates pass = CALL (ஒரு run-க்கு max 1) · இல்லைன்னா 📋 SETUP-ஆ save (அதுக்கும் result track ஆகும்)."""
    rows.sort(key=lambda r: (-int(r.get("ok", False)), -r.get("score", 0)))
    called = False
    for r in [r for r in rows if r.get("ok")][:2]:
        prev = _setup_today(seg, r, now)
        retry = prev and not prev.get("call") and str(prev.get("reason") or "").startswith(RETRY) and _hm_ok(seg, now) and not called
        if prev and not retry:                     # இன்று ஏற்கனவே save ஆன setup → மறுபடி strike தேட வேண்டாம்
            r["setup"] = prev
            r["call"] = prev.get("call")
            if not prev.get("call"):
                r.setdefault("why_not", []).append(prev.get("reason") or "setup ஏற்கனவே save")
            continue
        try:
            opt, err = plan_fn(r)
        except Exception as e:
            opt, err = None, f"strike: {e}"[:90]
        if not opt:
            r.setdefault("why_not", []).append(err)
            _log(seg, now, r, f"⛔ {err}")
            continue
        c, why = None, None
        if not _hm_ok(seg, now):
            why = "⏰ Call நேரம் முடிந்தது (" + (f"{CFG['mcx_start']}–{CFG['mcx_end']}" if seg == "CMD" else f"{CFG['nse_start']}–{CFG['nse_end']}") + ") — setup மட்டும், result track ஆகும்"
        elif called:
            why = RETRY + " — அடுத்த scan-ல் மறுபடி try"
        else:
            try:
                c, why = to_call(seg, r, opt, now)
            except Exception as e:
                c, why = None, f"call: {e}"[:90]
        if c:
            called = True
            r["call"] = c["id"]
            _log(seg, now, r, "✅ CALL")
        else:
            r.setdefault("why_not", []).append(why)
            _log(seg, now, r, f"⛔ {why}")
        r["setup"] = save_setup(seg, r, opt, now, c, why, prev if retry else None)
    STATE[seg].update(time=now.strftime("%H:%M:%S"), rows=rows[:12], err=None)
    return STATE[seg]


# ───────────────────────── 📋 SETUPS — call ஆகாத BEST setups-உம் strike + result-உடன் save ─────────────────────────
def _setups(d):
    return d.setdefault("mannan_setups", {})


def _setup_today(seg, r, now):
    from .store import STORE
    day = str(now.date())
    for x in _setups(STORE.load()).values():
        if x["seg"] == seg and x["date"] == day and x["symbol"] == r.get("symbol") and x["side"] == r.get("side"):
            if seg != "CMD" or (now - pd.Timestamp(x["date"] + " " + x["time"])).total_seconds() < 7200:
                return x
    return None


RETRY = "இந்த scan-ல் ஏற்கனவே 1 call"


def save_setup(seg, r, opt, now, call=None, reason=None, prev=None):
    """opt = plan_fn output (token / strike / plan) → STORE['mannan_setups'] (நிரந்தரம், max 400)."""
    from .calls import CALLS_LOCK, STORE
    p = (opt or {}).get("plan") or {}
    src = call or {}
    rec = {"id": f"{seg}|{now.date()}|{r['symbol']}|{r['side']}|{now.strftime('%H%M')}", "seg": seg, "date": str(now.date()),
           "time": now.strftime("%H:%M"), "symbol": r["symbol"], "side": r["side"], "score": r.get("score"), "strats": r.get("agree") or [],
           "meta_p": r.get("meta_p"), "token": (opt or {}).get("token"), "exch": (opt or {}).get("exch") or ("MCX" if seg == "CMD" else "NFO"),
           "contract": (opt or {}).get("contract"), "strike": (opt or {}).get("strike"), "expiry": (opt or {}).get("expiry"),
           "lot": (opt or {}).get("lot") or 1, "entry": src.get("entry") or p.get("entry"), "sl": src.get("sl") or p.get("sl"),
           "sl0": src.get("sl") or p.get("sl"), "targets": src.get("targets") or p.get("targets") or [], "ul_px": r.get("px"),
           "ul_sl": r.get("sl"), "status": "OPEN", "hits": [], "ltp": src.get("entry") or p.get("entry"), "pnl_lot": 0,
           "call": (call or {}).get("id"), "reason": None if call else reason, "spread": r.get("spread")}
    if prev:                                   # retry → அதே record (முதல் பார்த்த நேரம்) update
        rec.update(id=prev["id"], time=prev["time"])
    with CALLS_LOCK:
        d = STORE.load()
        S = _setups(d)
        S[rec["id"]] = rec
        for k in sorted(S, key=lambda k: S[k]["date"] + S[k]["time"])[:-400]:
            S.pop(k, None)
        STORE.dirty = True
    return rec


def track_setups(ag, now):
    """OPEN setups-ன் option LTP (ஒரு batched quote) → T1 (SL → entry) · T2 (SL → T1) · T3 · SL · EOD exit. ~30 sec-க்கு ஒருமுறை."""
    from .calls import CALLS_LOCK, STORE
    day, hm = str(now.date()), now.strftime("%H:%M")
    d = STORE.load()
    op = [x for x in _setups(d).values() if x["status"] in ("OPEN", "T1 HIT", "T2 HIT") and x.get("token")]
    if not op:
        return 0
    by = {}
    for x in op:
        by.setdefault(x["exch"], []).append(x["token"])
    qs = {}
    for ex, toks in by.items():
        try:
            qs.update(ag.quotes({ex: sorted(set(toks))}) or {})
        except Exception:
            pass
    n = 0
    with CALLS_LOCK:
        for x in op:
            q = qs.get(x["token"]) or {}
            ltp = float(q.get("ltp") or 0)
            stale_day = x["date"] < day
            eod = stale_day or (hm >= "23:20" if x["exch"] == "MCX" else hm >= "15:20")
            if not ltp and not eod:
                continue
            if ltp:
                x["ltp"] = ltp
            e, lot, tg = float(x["entry"] or 0), float(x["lot"] or 1), x.get("targets") or []
            for k, t in enumerate(tg[:3], 1):
                if ltp and ltp >= t and not any(h.startswith(f"T{k} ") for h in x["hits"]):
                    x["hits"].append(f"T{k} {hm}")
                    x["status"] = f"T{k} HIT"
                    x["sl"] = e if k == 1 else tg[k - 2]          # system rule: T1 → SL entry · T2 → SL T1
            if len(x["hits"]) >= 3:
                x.update(status="T3 DONE", exit=tg[2], exit_time=f"{day} {hm}")
            elif ltp and x.get("sl") and ltp <= float(x["sl"]):
                x.update(status="SL HIT" if not x["hits"] else "TRAIL SL", exit=ltp, exit_time=f"{day} {hm}")
            elif eod:
                x.update(status="EOD EXIT", exit=x.get("ltp"), exit_time=f"{day} {hm}")
            px = x.get("exit") if x["status"] not in ("OPEN", "T1 HIT", "T2 HIT") else x.get("ltp")
            x["pnl_lot"] = round(((px or e) - e) * lot)
            x["upd"] = hm
            n += 1
        if n:
            STORE.dirty = True
    return n


def _live_calls(seg):
    from .store import STORE
    k = SEG[seg]["kind"]
    return [c for c in (STORE.load().get("calls") or {}).values() if c.get("kind") == k and c.get("status") not in ("OPEN", "T1 HIT", "T2 HIT", "T3 HIT", "T4 HIT", "VOID")]


def _mdir():
    try:
        from .ai import STATE as AST
        return (AST.get("risk") or {}).get("dir")
    except Exception:
        return None


# ───────────────────────── 🛢 COMMODITY ─────────────────────────
D1 = {}


def _daily(ag, exch, tok, key, now, days=200):
    k = f"{key}|{now.date()}"
    if k not in D1:
        try:
            df = ag.candles(exch, tok, "ONE_DAY", now - pd.Timedelta(days=days), now)
            D1[k] = df[df.index.normalize() < now.normalize()] if df is not None and not df.empty else None
        except Exception:
            D1[k] = None
    return D1[k]


def run_commodity(ag, inst, now):
    """commodity.py-ன் 1-min frames (CM.FR) மறுபடி பயன்படுத்தும் → கூடுதல் 1-min API call இல்லை."""
    from . import commodity as CM
    with LK:
        fr_all = {n: f for n, (t, f) in (getattr(CM, "FR", {}) or {}).items() if (now - t).total_seconds() < 600}
        futs = {n: CM._fut(inst, n) for n in CM.CFG["watch"]}
        nxt = (inst.get("mcx_fut2") or {})
        toks = [f[0] for f in futs.values() if f] + [f[0] for n, f in nxt.items() if n in futs and f]
        qs = {}
        try:
            qs = ag.quotes({"MCX": toks}) or {} if toks else {}
        except Exception:
            pass
        rv = {}
        for a, b in RV_PAIRS:
            if a in fr_all and b in fr_all:
                rv[(a, b)] = rv_z(fr_all[a]["1H"], fr_all[b]["1H"])
        rows, items = [], []
        for name, fr in fr_all.items():
            f = futs.get(name)
            if not f:
                continue
            q, q2 = qs.get(f[0]) or {}, qs.get((nxt.get(name) or [None])[0]) or {}
            tb, ts = float(q.get("totBuyQuan") or 0), float(q.get("totSellQuan") or 0)
            extra = {"imb": round(tb / ts, 2) if tb and ts else None, "rv": rv, "near_px": float(q.get("ltp") or 0) or None,
                     "next_px": float(q2.get("ltp") or 0) or None,
                     "roll_days": (dt.date.fromisoformat(nxt[name][2]) - dt.date.fromisoformat(f[2])).days if nxt.get(name) else None,
                     "d1": _daily(ag, "MCX", f[0], name, now)}
            X = build(fr["5M"], fr["15M"], fr["1H"], extra["d1"], extra)
            if not X:
                continue
            bt_get("CMD", name, fr["5M"], name, None, now.date())
            items.append((name, X))
        stats = seg_stats("CMD", _live_calls("CMD"))          # இன்றைய backtest முடிஞ்ச பிறகு
        for name, X in items:
            sigs = evaluate("CMD", X, name)
            r = confluence("CMD", sigs, X, stats)
            r.update(symbol=name, label=CM.COMM[name][1], sigs={k: (v if v and v.get("side") else None) for k, v in sigs.items()})
            rows.append(r)

        def mk(r):
            o = CM.pick_option(ag, inst, r["symbol"], r["side"], r["px"], now)
            if not o:
                return None, "Option (liquid strike) கிடைக்கல"
            if o["spread_pct"] > CM.CFG["max_spread"]:
                return None, f"Spread {o['spread_pct']}%"
            p = CM.plan(o, r["px"], r["sl"])
            if p["risk_rs"] > CM.CFG["risk_cap"]:
                return None, f"Risk ₹{p['risk_rs']:,}/lot > ₹{CM.CFG['risk_cap']:,}"
            r["ul_targets"] = _ul_targets(r["px"], r["sl"], r["side"])
            opt = {"token": o["token"], "exch": "MCX", "contract": o["contract"], "strike": o["strike"], "type": r["side"],
                   "expiry": o["expiry"], "lot": o["mult"], "plan": {"entry": p["entry"], "sl": p["sl"], "targets": p["targets"], "risk": p["risk_rs"],
                                                                    "risk_ok": True, "money": True, "reward_ok": True, "v4": True}}
            r["option"] = {k: o.get(k) for k in ("strike", "expiry", "ltp", "spread_pct", "commodity")}
            r["plan"] = p
            return opt, None
        out = _finish("CMD", rows, now, mk)
        out["stats"] = stats
        out["rv"] = {f"{a}/{b}": z for (a, b), (z, _) in rv.items()}
        return out


# ───────────────────────── 📊 INDEX ─────────────────────────
def run_index(ag, inst, full, now):
    """V4 loop-ன் frames (V.FR) + deep scan-ன் option chain OI + GEX."""
    with LK:
        mdir = _mdir()
        I = {x.get("index"): x for x in (full or {}).get("index") or []}
        G = {g.get("index"): g for g in (full or {}).get("gex") or []}
        rows, items = [], []
        for idx in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"):
            t_fr = (getattr(V, "FR", {}) or {}).get(idx)
            fr = t_fr[1] if t_fr and (now - t_fr[0]).total_seconds() < 400 else None
            want = now.floor("5min").strftime("%Y-%m-%d %H:%M")
            if fr and str(fr.get("data_time") or "") < want:      # V4 frames-ல் கடைசி 5-min bar இன்னும் இல்லை → நேரடியா புது data
                fr = None
            if fr is None:
                try:
                    fr = V.load_frames(ag, inst, idx, now)
                except Exception:
                    fr = None
            if not fr:
                continue
            ch = I.get(idx) or {}
            near = sorted(ch.get("chain") or [], key=lambda r: abs(r["strike"] - (ch.get("spot") or 0)))[:5]
            oi = {"ce_chg": sum((r.get("CE") or {}).get("chg", 0) for r in near), "pe_chg": sum((r.get("PE") or {}).get("chg", 0) for r in near)} if near else None
            extra = {"oi": oi, "gex": G.get(idx)}
            X = build(fr["5M"], fr["15M"], fr["1H"], None, extra)
            if not X:
                continue
            bt_get("IDX", idx, fr["5M"], idx, None, now.date())
            items.append((idx, X))
        stats = seg_stats("IDX", _live_calls("IDX"))
        for idx, X in items:
            sigs = evaluate("IDX", X, idx)
            r = confluence("IDX", sigs, X, stats, mdir)
            r.update(symbol=idx, label=idx, sigs={k: (v if v and v.get("side") else None) for k, v in sigs.items()})
            r["meta_label"] = ("✓ pass" if r.get("meta_p") and r["meta_p"] >= CFG["meta_min_p"] else
                               "✗ block" if r.get("meta_p") is not None else "Test needed")
            rows.append(r)

        def mk(r):
            o, why = V.pick_strike(ag, inst, r["symbol"], r["side"], r["px"], now)
            if not o:
                return None, f"Strike: {why}"
            pl, why = V.option_plan(o, r["px"], r["sl"], V.settings())
            if not pl:
                return None, f"Plan: {why}"
            r["ul_targets"] = _ul_targets(r["px"], r["sl"], r["side"])
            opt = {"token": o["token"], "exch": o["exch"], "contract": o["contract"], "strike": o["strike"], "type": r["side"], "expiry": o["expiry"],
                   "lot": o["lot"], "spread_pct": o.get("spread_pct"),
                   "plan": {"entry": pl["entry"], "sl": pl["sl"], "targets": pl["targets"], "risk": pl["risk"], "risk_ok": True, "money": True, "reward_ok": True}}
            r["option"] = {k: o.get(k) for k in ("strike", "expiry", "ltp", "spread_pct", "delta", "iv")}
            return opt, None
        out = _finish("IDX", rows, now, mk)
        out["stats"] = stats
        return out


# ───────────────────────── 📈 STOCK OPTIONS ─────────────────────────
SK = {}          # symbol → {"day", "hist"} 5-min history cache


def _stock_m5(ag, tok, sym, now):
    day = str(now.date())
    ch = SK.get(sym)
    t0 = now.normalize() + pd.Timedelta(hours=9, minutes=15)
    if not ch or ch["day"] != day:
        h = ag.candles("NSE", tok, "FIVE_MINUTE", t0 - pd.Timedelta(days=7), t0 - pd.Timedelta(minutes=1))
        ch = SK[sym] = {"day": day, "hist": h if h is not None else pd.DataFrame()}
    td = ag.candles("NSE", tok, "FIVE_MINUTE", t0, now)
    parts = [x for x in (ch["hist"], td) if x is not None and not x.empty]
    if not parts:
        return None
    m5 = pd.concat(parts)
    m5 = m5[~m5.index.duplicated(keep="last")].sort_index()
    m5 = m5[m5.index + pd.Timedelta(minutes=5) <= now]
    return m5 if len(m5) and m5.index[-1].date() == now.date() else None


def _bars_df(b):
    if not b or not b.get("c"):
        return None
    return pd.DataFrame({"open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"], "volume": b.get("v") or [0] * len(b["c"])},
                        index=pd.to_datetime(b["t"]))


def stock_candidates(live_q, levels, n):
    """5-min fetch-க்கு முன் வடிகட்டல்: volume ≥1.5× + move ≥1% அல்லது PDH/PDL அருகில்."""
    out = []
    for s, q in (live_q or {}).items():
        ltp, vr, pct = q.get("ltp") or 0, q.get("vol_ratio") or 0, q.get("pct") or 0
        if ltp <= 50 or vr < 1.5:
            continue
        lv = (levels or {}).get(s) or {}
        near = any(lv.get(k) and abs(ltp - lv[k]) / lv[k] <= 0.006 for k in ("PDH", "PDL"))
        if abs(pct) >= 1.0 or near:
            out.append((vr * (1 + abs(pct) / 3), s))
    out.sort(reverse=True)
    return [s for _, s in out[:n]]


def hv20(d1):
    if d1 is None or len(d1) < 22:
        return None
    return float(np.log(d1["close"]).diff().tail(20).std() * math.sqrt(252))


def spread_plan(r, opt, alts):
    """Bull call / bear put debit spread: buy chosen strike · sell அடுத்த OTM strike (quote இருந்தா)."""
    side, k = r["side"], opt.get("strike")
    far = [a for a in (alts or []) if a.get("ltp") and ((a["strike"] > k) if side == "CE" else (a["strike"] < k))]
    if not far or not opt.get("ltp"):
        return None
    s = sorted(far, key=lambda a: abs(a["strike"] - k))[0]
    debit = round((opt.get("ask") or opt["ltp"]) - (s.get("bid") or s["ltp"]), 2)
    width = abs(s["strike"] - k)
    if debit <= 0 or debit >= width:
        return None
    lot = opt.get("lot") or 1
    return {"buy": k, "sell": s["strike"], "type": side, "debit": debit, "max_loss": round(debit * lot), "max_profit": round((width - debit) * lot),
            "rr": round((width - debit) / debit, 2), "breakeven": round(k + debit if side == "CE" else k - debit, 2)}


def run_stocks(ag, inst, full, live_q, now):
    from . import fullscan as FS
    from .optmath import greeks_from_price
    with LK:
        mdir = _mdir()
        npct = next((x.get("pct") for x in (full or {}).get("index") or [] if x.get("index") == "NIFTY"), 0) or 0
        bu = {}
        for kind, xs in ((full or {}).get("oi_buildup") or {}).items():
            for x in xs:
                bu[x["symbol"]] = kind
        bars = FS.C.get("bars") or {}
        levels = FS.C.get("levels") or {}
        pz = {}
        for a, b in PAIRS:
            if a in live_q and b in live_q:
                pz[(a, b)] = pairs_z(bars, a, b, live_q[a].get("ltp"), live_q[b].get("ltp"))
        cands = stock_candidates(live_q, levels, CFG["max_stock_check"])
        for (a, b), z in pz.items():                       # pair z ≥2 உள்ளவையும் check
            if z is not None and abs(z) >= 2:
                cands += [s for s in (a, b) if s not in cands]
        rows, items = [], []
        for sym in cands[: CFG["max_stock_check"] + 4]:
            tok = (inst.get("eq") or {}).get(sym)
            if not tok:
                continue
            try:
                m5 = _stock_m5(ag, tok, sym, now)
            except Exception:
                m5 = None
            if m5 is None:
                continue
            q = live_q.get(sym) or {}
            d1 = _bars_df(bars.get(sym))
            extra = {"symbol": sym, "pct": q.get("pct"), "npct": npct, "vr": q.get("vol_ratio"), "oi_tag": bu.get(sym, ""), "d1": d1,
                     "pairs": {k: v for k, v in pz.items() if sym in k}}
            X = build(m5, None, None, d1, extra)
            if not X:
                continue
            bt_get("STK", sym, m5, sym, None, now.date())
            items.append((sym, X, q, d1))
        stats = seg_stats("STK", _live_calls("STK"))
        for sym, X, q, d1 in items:
            sigs = evaluate("STK", X, sym)
            r = confluence("STK", sigs, X, stats, mdir)
            r.update(symbol=sym, label=sym, vr=q.get("vol_ratio"), oi=bu.get(sym, ""), hv=hv20(d1),
                     sigs={k: (v if v and v.get("side") else None) for k, v in sigs.items()})
            r["earn"] = bool(sigs.get("EARN"))
            rows.append(r)

        def mk(r):
            rr = {"symbol": r["symbol"], "side": r["side"], "price": r["px"], "sl": r["sl"], "targets": _ul_targets(r["px"], r["sl"], r["side"]), "min_days": 3}
            FS.pick_options(ag, inst, [rr])
            o = rr.get("option") or {}
            if "none" in o or not o.get("token"):
                return None, (o.get("none") or "Option இல்லை")[:90]
            FS.attach_plan(rr, o, now, SEG["STK"]["src"])
            o = rr.get("option") or o
            if not o.get("plan"):
                return None, "Option plan கணக்கிட முடியல"
            iv = None
            try:
                iv = (greeks_from_price(o["ltp"], r["px"], o["strike"], o["expiry"], o["type"], now.to_pydatetime()) or {}).get("iv")
                iv = iv / 100 if iv else None          # v87 fix: greeks_from_price IV = % (30.0) · HV = fraction (0.30) → முன்னாடி ratio 100× ஆகி calls block ஆச்சு
            except Exception:
                pass
            ratio = (iv / r["hv"]) if (iv and r.get("hv")) else None
            r["iv"] = {"iv": round(iv, 3) if iv else None, "hv": round(r["hv"], 3) if r.get("hv") else None, "ratio": round(ratio, 2) if ratio else None}
            r["spread"] = spread_plan(r, o, rr.get("option_alts"))
            if ratio and ratio >= CFG["iv_skip"] and not r["spread"]:
                return None, f"IV filter: IV/HV {ratio:.1f}× — premium மிக அதிகம், spread-உம் கிடைக்கல"
            if ratio and ratio >= CFG["iv_expensive"] or r.get("earn"):
                r.setdefault("why", []).append(f"METAIV: IV/HV {ratio or 0:.1f}× → debit spread நல்லது" if ratio else "EARN: IV crush risk → debit spread நல்லது")
            r["ul_targets"] = rr["targets"]
            r["option"] = {k: o.get(k) for k in ("strike", "expiry", "ltp", "spread_pct", "moneyness")}
            return o, None
        out = _finish("STK", rows, now, mk)
        out["stats"] = stats
        if "14:30" <= now.strftime("%H:%M") <= "15:20" or not STATE["STK"].get("covered"):
            out["covered"] = covered_calls(bars, live_q, inst)
        return out


def covered_calls(bars, live_q, inst, n=6):
    """🏦 Covered call ideas (holding / income): daily uptrend (close > SMA20 > SMA50) · HV20 < 35% · RSI 50–65 → stock + ~5% OTM next-month CE sell."""
    from .instruments import contracts
    out = []
    for s, b in (bars or {}).items():
        d = _bars_df(b)
        if d is None or len(d) < 55:
            continue
        c = d["close"]
        s20, s50 = c.rolling(20).mean().iloc[-1], c.rolling(50).mean().iloc[-1]
        px = (live_q.get(s) or {}).get("ltp") or float(c.iloc[-1])
        h = hv20(d)
        r = float(V.rsi(c).iloc[-1] or 50)
        if not (px > s20 > s50 and h and h < 0.35 and 50 <= r <= 65):
            continue
        try:
            exp, cs = contracts(inst, s, 20)
        except Exception:
            exp, cs = None, []
        ks = sorted({x[3] for x in cs if x[4] == "CE"})
        k = next((x for x in ks if x >= px * 1.05), None)
        out.append({"symbol": s, "px": round(px, 2), "hv": round(h * 100, 1), "rsi": round(r, 1), "trend": round((px / s50 - 1) * 100, 1),
                    "strike": k, "expiry": exp, "lot": (cs[0][5] if cs else None)})
    out.sort(key=lambda x: (x["hv"], -x["trend"]))
    return out[:n]


# ───────────────────────── report (website) ─────────────────────────
def report(live_px=None):
    from .store import STORE
    D = STORE.load()
    allc = [c for c in (D.get("calls") or {}).values() if c.get("kind") in KINDS]
    sets = sorted(_setups(D).values(), key=lambda x: x["date"] + x["time"], reverse=True)
    for r_ in [r for seg in SEG for r in (STATE[seg].get("rows") or [])]:
        lp = (live_px or {}).get(r_.get("symbol"))
        if lp:
            r_["live"] = round(float(lp), 2)
    allc.sort(key=lambda c: str(c.get("signal_time") or c.get("date", "") + " " + c.get("time", "")), reverse=True)
    segs = {}
    for seg, S in SEG.items():
        mine = [c for c in allc if c["kind"] == S["kind"]]
        closed = [c for c in mine if c.get("status") not in ("OPEN", "T1 HIT", "T2 HIT", "T3 HIT", "T4 HIT")]
        st = seg_stats(seg, closed)                   # எப்போதும் fresh (calls முடிஞ்சதும் உடனே update)
        segs[seg] = {"cfg": S, "time": STATE[seg].get("time"), "rows": STATE[seg].get("rows") or [], "err": STATE[seg].get("err"),
                     "strats": [{"key": k, "name": nm, "market": mk, "type": ty, **(st.get(k) or {})} for k, nm, mk, ty in STRATS[seg]],
                     "calls": mine[:300], "rv": STATE[seg].get("rv"), "covered": STATE[seg].get("covered") or [],
                     "log": STATE[seg].get("log") or [],
                     "setups": [x for x in sets if x["seg"] == seg][:200],
                     "near": [r for r in (STATE[seg].get("rows") or []) if not r.get("ok") and r.get("side") and len(r.get("agree") or []) >= 1][:4]}
    return {"segs": segs, "cfg": CFG}
