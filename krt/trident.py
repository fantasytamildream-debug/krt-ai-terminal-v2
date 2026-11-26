"""🔱 KRT TRIDENT AI — Triple Market Alpha Engine (Index · Stock · Commodity).

Strategy ideas from Kakushadze & Serur, "151 Trading Strategies" (2018) — implemented on the terminal's own live data:
  §3.1 price momentum · §3.2 earnings momentum · §3.4 low volatility · §3.5 implied volatility · §3.6 multifactor ·
  §3.7 residual momentum · §3.9 mean reversion · §3.13 three moving averages · §3.14 support & resistance · §3.15 channel ·
  §3.17 single-stock KNN · §3.20 alpha combos · §4.1 sector momentum rotation · §7.5 volatility skew · §9.1 roll yields ·
  §10.3 contrarian (mean reversion) · §10.4 futures trend following · §19.5 economic announcements.

Honesty rules built in:
  · every strategy returns a value in [-1, +1] (− = PE side, + = CE side) or None when its data is missing; a market needs ≥60 %
    of the weight covered, otherwise NO TRADE. Missing data is never filled with guesses.
  · closed candles only (the forming candle is dropped) · stale data (> 12 min) → NO TRADE.
  · the AI Quality Score (0–100) ranks setups — it is NOT a win-rate. Calls only at ≥85 with the risk filters passing
    (1-lot risk ≤ ₹2,500 · reward:risk ≥ 2 at T2 · liquid option · no expiry-day decay trap · no duplicate).
  · the backtest runs on the UNDERLYING (index / stock / commodity-future candles) because expired-option history is not
    available from Angel — results are in R (risk units) with slippage, in-sample vs out-of-sample (walk-forward), never invented.
"""
import math
import threading

import numpy as np
import pandas as pd

W_INDEX = {"momentum": 20, "sr": 20, "trend": 15, "meanrev": 10, "iv": 10, "skew": 10, "ma3": 10, "combo": 5}
W_STOCK = {"momentum": 20, "multifactor": 15, "earnings": 15, "sector": 15, "sr": 10, "residual": 10, "iv": 10, "knn": 5}
W_COMM = {"trend": 25, "momentum": 20, "channel": 15, "meanrev": 10, "sr": 10, "events": 10, "iv": 5, "roll": 5}
NAMES = {"momentum": "Price momentum §3.1", "sr": "Support & resistance §3.14", "trend": "Futures trend following §10.4",
         "meanrev": "Mean reversion §3.9/§10.3", "iv": "Implied volatility §3.5", "skew": "Volatility skew §7.5", "ma3": "Three moving averages §3.13",
         "combo": "Alpha combos §3.20", "multifactor": "Multifactor §3.6", "earnings": "Earnings momentum §3.2", "sector": "Sector momentum rotation §4.1",
         "residual": "Residual momentum §3.7", "knn": "Machine learning KNN §3.17", "channel": "Channel trading §3.15",
         "events": "Economic announcements §19.5", "roll": "Roll yield §9.1"}
CFG = {"call": 85, "elite": 90, "watch": 75, "risk": 2500, "rr": 2.0, "cover": 0.60, "stale_min": 12, "slip_r": 0.05}
STATE = {"time": None, "regime": {}, "index": [], "stock": [], "comm": [], "watch": [], "err": None, "bt": None, "bt_time": None, "learned": {}}
LOCK = threading.Lock()


# ───────────────────────── helpers ─────────────────────────
def _clip(x, a=-1.0, b=1.0):
    try:
        return float(max(a, min(b, x)))
    except Exception:
        return None


def _ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def _atr(d, n=14):
    pc = d["close"].shift()
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=3).mean()


def resample(d, rule):
    """5-min → 15 / 60-min bars aligned to 09:15, keeping only COMPLETE bars (a forming 15 / 60-min bar is dropped)."""
    if d is None or d.empty:
        return d
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in d.columns:
        agg["volume"] = "sum"
    r = d.resample(rule, label="left", closed="left", origin="start_day", offset="15min").agg(agg).dropna(subset=["close"])
    step = d.index.to_series().diff().median() if len(d) > 2 else pd.Timedelta(minutes=5)
    last_close = d.index[-1] + (step if pd.notna(step) else pd.Timedelta(minutes=5))
    return r[r.index + pd.Timedelta(rule) <= last_close]


def combine(comps, weights, regime=None):
    """Adaptive weighted vote. Regime changes the weights (no forcing every strategy to agree). → (s in [-1,1], coverage, used weights)."""
    w = dict(weights)
    if regime in ("SIDEWAYS", "LOW VOLATILITY"):
        for k in ("meanrev", "sr", "channel"):
            if k in w:
                w[k] *= 1.8
        for k in ("momentum", "trend"):
            if k in w:
                w[k] *= 0.6
    elif regime in ("BULLISH TREND", "BEARISH TREND"):
        for k in ("momentum", "trend", "ma3", "residual", "sector"):
            if k in w:
                w[k] *= 1.3
        if "meanrev" in w:
            w["meanrev"] *= 0.3
    elif regime == "BREAKOUT":
        for k in ("sr", "channel", "momentum"):
            if k in w:
                w[k] *= 1.4
    tot = sum(w.values())
    cov = sum(w[k] for k, v in comps.items() if v is not None and k in w)
    if not tot or not cov:
        return 0.0, 0.0, w
    s = sum(w[k] * v for k, v in comps.items() if v is not None and k in w) / cov
    return float(s), cov / tot, w


def quality(s, conf_pts, coverage):
    """Quality Score 0–100 = strength of the weighted vote + confirmations, scaled down when data coverage is partial."""
    base = 50 + 45 * abs(s)
    sc = (base + conf_pts) * (0.85 + 0.15 * coverage)
    return int(max(0, min(100, round(sc))))


def band(q):
    return "ELITE" if q >= CFG["elite"] else "HIGH QUALITY" if q >= CFG["call"] else "WATCHLIST" if q >= CFG["watch"] else "REJECT"


def regime_of(d5, d60=None):
    """Market condition from closed candles: trend (1h EMA20 slope + price), volatility (ATR percentile), range position, breakout, reversal."""
    if d5 is None or len(d5) < 30:
        return "UNKNOWN", []
    d60 = d60 if d60 is not None else resample(d5, "60min")
    c = d5["close"]
    why = []
    a = _atr(d5, 14)
    apct = float((a.rank(pct=True)).iloc[-1]) if len(a.dropna()) > 20 else 0.5
    day = d5[d5.index.date == d5.index[-1].date()]
    if len(d60) >= 22:
        e20 = _ema(d60["close"], 20)
        slope = (e20.iloc[-1] / e20.iloc[-4] - 1) * 100
    else:
        slope = 0.0
    hi, lo = day["high"].max(), day["low"].min()
    prev = d5[d5.index.date < d5.index[-1].date()]
    pdh, pdl = (prev[prev.index.date == prev.index[-1].date()]["high"].max(), prev[prev.index.date == prev.index[-1].date()]["low"].min()) if len(prev) else (None, None)
    pos = (c.iloc[-1] - lo) / (hi - lo) if hi > lo else 0.5
    r60 = (c.iloc[-1] / c.iloc[-13] - 1) * 100 if len(c) > 13 else 0
    rday = (c.iloc[-1] / day["open"].iloc[0] - 1) * 100 if len(day) else 0
    why += [f"1h EMA20 slope {slope:+.2f}%", f"ATR percentile {apct * 100:.0f}", f"day {rday:+.2f}%", f"last hour {r60:+.2f}%"]
    if pdh and (c.iloc[-1] > pdh or c.iloc[-1] < pdl) and abs(r60) >= 0.25:
        return "BREAKOUT", why + [f"beyond yesterday's {'high' if c.iloc[-1] > pdh else 'low'}"]
    if rday * r60 < 0 and abs(r60) >= 0.35 and abs(rday) >= 0.4:
        return "REVERSAL", why + ["last hour against the day's move"]
    if apct >= 0.85:
        return "HIGH VOLATILITY", why
    if slope >= 0.12 and pos >= 0.5:
        return "BULLISH TREND", why
    if slope <= -0.12 and pos <= 0.5:
        return "BEARISH TREND", why
    if apct <= 0.2:
        return "LOW VOLATILITY", why
    return "SIDEWAYS", why


# ───────────────────────── strategy components (closed candles) ─────────────────────────
def c_momentum(d5):
    c = d5["close"]
    if len(c) < 40:
        return None
    r = c.pct_change(12)
    sd = r.rolling(300, min_periods=60).std().iloc[-1]
    if not sd or np.isnan(sd):
        return None
    return _clip(r.iloc[-1] / sd / 2)


def c_sr(d5, extra=None):
    """Break / hold of yesterday's high-low and today's range; bounce or rejection at a known level (± points)."""
    if len(d5) < 20:
        return None
    day = d5[d5.index.date == d5.index[-1].date()]
    prev = d5[d5.index.date < d5.index[-1].date()]
    if prev.empty or len(day) < 2:
        return None
    pd_ = prev[prev.index.date == prev.index[-1].date()]
    pdh, pdl = pd_["high"].max(), pd_["low"].min()
    c, c3 = day["close"].iloc[-1], day["close"].iloc[-4] if len(day) >= 4 else day["open"].iloc[0]
    a = float(_atr(d5).iloc[-1] or 0) or (pdh - pdl) / 10
    if c > pdh:
        return 1.0 if c3 <= pdh else 0.6
    if c < pdl:
        return -1.0 if c3 >= pdl else -0.6
    lv = [x for x in (extra or []) if x]
    lo, hi = day["low"].iloc[-1], day["high"].iloc[-1]
    for L in lv + [pdh, pdl]:
        if abs(lo - L) <= 0.3 * a and c > L and day["close"].iloc[-1] > day["open"].iloc[-1]:
            return 0.5
        if abs(hi - L) <= 0.3 * a and c < L and day["close"].iloc[-1] < day["open"].iloc[-1]:
            return -0.5
    return 0.0


def c_trend(d15):
    if d15 is None or len(d15) < 55:
        return None
    e20, e50 = _ema(d15["close"], 20), _ema(d15["close"], 50)
    a = float(_atr(d15).iloc[-1] or 0)
    if not a:
        return None
    gap = (e20.iloc[-1] - e50.iloc[-1]) / a
    slope = (e20.iloc[-1] - e20.iloc[-4]) / a
    return _clip(0.6 * gap + 0.8 * slope)


def c_meanrev(d15):
    if d15 is None or len(d15) < 25:
        return None
    c = d15["close"]
    m, sd = c.rolling(20).mean().iloc[-1], c.rolling(20).std().iloc[-1]
    if not sd:
        return None
    z = (c.iloc[-1] - m) / sd
    return _clip(-z / 2.5) if abs(z) >= 1.5 else 0.0


def c_ma3(d15):
    if d15 is None or len(d15) < 55:
        return None
    c = d15["close"]
    e9, e21, e50 = _ema(c, 9).iloc[-1], _ema(c, 21).iloc[-1], _ema(c, 50).iloc[-1]
    p = c.iloc[-1]
    if p > e9 > e21 > e50:
        return 1.0
    if p < e9 < e21 < e50:
        return -1.0
    if e9 > e21 > e50:
        return 0.4
    if e9 < e21 < e50:
        return -0.4
    return 0.0


def c_channel(d15, n=20):
    if d15 is None or len(d15) < n + 2:
        return None
    hi, lo = d15["high"].iloc[-n - 1:-1].max(), d15["low"].iloc[-n - 1:-1].min()
    c = d15["close"].iloc[-1]
    if c > hi:
        return 1.0
    if c < lo:
        return -1.0
    pos = (c - lo) / (hi - lo) if hi > lo else 0.5
    return _clip((0.5 - pos) * 0.8) if (pos <= 0.1 or pos >= 0.9) else 0.0       # channel edges → fade


def c_combo(comps):
    v = [math.copysign(1, x) for k, x in comps.items() if x not in (None, 0) and k != "combo"]
    return _clip(sum(v) / len(v)) if len(v) >= 3 else None


def confirmations(d5, d15, d60, side, extra=None):
    """MTF (1h · 15m · 5m) · VWAP-proxy · liquidity sweep · BOS / CHOCH · FVG · breakout candle. → (points, list)."""
    out, pts = [], 0
    up = side == "CE"
    try:
        h = 1 if (len(d60) >= 22 and _ema(d60["close"], 20).diff().iloc[-1] > 0) else -1
        m = 1 if (len(d15) >= 22 and d15["close"].iloc[-1] > _ema(d15["close"], 20).iloc[-1]) else -1
        f = 1 if d5["close"].iloc[-1] > d5["close"].iloc[-4] else -1
        want = 1 if up else -1
        agree = sum(1 for x in (h, m, f) if x == want)
        if agree == 3:
            pts += 6
            out.append(("MTF 1h · 15m · 5m aligned", True))
        elif h != want:
            pts -= 8
            out.append(("1h trend against", False))
        else:
            out.append((f"MTF {agree}/3", None))
    except Exception:
        pass
    day = d5[d5.index.date == d5.index[-1].date()]
    if len(day) >= 3:
        tp = (day["high"] + day["low"] + day["close"]) / 3
        vw = (tp * day["volume"]).sum() / day["volume"].sum() if "volume" in day and day["volume"].sum() > 0 else tp.mean()
        ok = day["close"].iloc[-1] > vw if up else day["close"].iloc[-1] < vw
        pts += 4 if ok else -5
        out.append((f"{'above' if day['close'].iloc[-1] > vw else 'below'} VWAP {vw:,.1f}", ok))
    if len(d5) >= 12:
        w = d5.iloc[-12:-1]
        last = d5.iloc[-1]
        if up and last["low"] < w["low"].min() and last["close"] > w["low"].min():
            pts += 4
            out.append(("liquidity sweep of the lows, closed back above", True))
        if not up and last["high"] > w["high"].max() and last["close"] < w["high"].max():
            pts += 4
            out.append(("liquidity sweep of the highs, closed back below", True))
        sw_hi, sw_lo = d5["high"].iloc[-25:-3].max() if len(d5) >= 25 else None, d5["low"].iloc[-25:-3].min() if len(d5) >= 25 else None
        if sw_hi and up and last["close"] > sw_hi:
            pts += 4
            out.append(("BOS — close above the last swing high", True))
        if sw_lo and not up and last["close"] < sw_lo:
            pts += 4
            out.append(("BOS — close below the last swing low", True))
    if len(d5) >= 5:
        a, c = d5.iloc[-3], d5.iloc[-1]
        if up and c["low"] > a["high"]:
            pts += 3
            out.append(("bullish fair value gap", True))
        if not up and c["high"] < a["low"]:
            pts += 3
            out.append(("bearish fair value gap", True))
        rng = (d5["high"] - d5["low"]).iloc[-21:-1].mean()
        b = d5.iloc[-1]
        if rng and (b["high"] - b["low"]) >= 1.5 * rng and ((b["close"] > b["open"]) == up):
            pts += 3
            out.append(("strong breakout candle (1.5× range)", True))
    for e in extra or []:
        pts += e[1]
        out.append((e[0], e[1] > 0))
    return pts, out


# ───────────────────────── engines ─────────────────────────
def index_eval(name, d5, ix=None, now=None, extra_levels=None):
    """d5: 5-min OHLC (history + today, closed candles only). ix: live index row from the deep scan (chain, pcr, support…)."""
    if d5 is None or len(d5) < 60:
        return {"market": name, "engine": "INDEX", "status": "NO TRADE", "why": "not enough candle history"}
    d15, d60 = resample(d5, "15min"), resample(d5, "60min")
    reg, rwhy = regime_of(d5, d60)
    comps = {"momentum": c_momentum(d5), "sr": c_sr(d5, [ix.get("support"), ix.get("resistance")] if ix else extra_levels),
             "trend": c_trend(d15), "meanrev": c_meanrev(d15), "ma3": c_ma3(d15), "iv": None, "skew": None}
    ivs = {}
    if ix and ix.get("chain") and now is not None:
        try:
            from .command import _greeks
            spot, exp = float(ix.get("spot") or d5["close"].iloc[-1]), ix.get("expiry")
            ch = sorted(ix["chain"], key=lambda r: abs(r["strike"] - spot))
            atm = ch[0]
            gc = _greeks((atm.get("CE") or {}).get("ltp"), spot, atm["strike"], exp, "CE", now)
            gp = _greeks((atm.get("PE") or {}).get("ltp"), spot, atm["strike"], exp, "PE", now)
            if gc.get("iv") and gp.get("iv"):
                ivs["atm_ce"], ivs["atm_pe"] = gc["iv"], gp["iv"]
                comps["iv"] = _clip((gc["iv"] - gp["iv"]) / 2.0)              # call-put IV spread (§3.5)
            otm_c = min((r for r in ch if r["strike"] >= spot * 1.015), key=lambda r: abs(r["strike"] - spot * 1.02), default=None)
            otm_p = min((r for r in ch if r["strike"] <= spot * 0.985), key=lambda r: abs(r["strike"] - spot * 0.98), default=None)
            if otm_c and otm_p:
                a = _greeks((otm_c.get("CE") or {}).get("ltp"), spot, otm_c["strike"], exp, "CE", now).get("iv")
                b = _greeks((otm_p.get("PE") or {}).get("ltp"), spot, otm_p["strike"], exp, "PE", now).get("iv")
                if a and b:
                    ivs["skew"] = round(b - a, 1)
                    comps["skew"] = _clip((b - a - 2.0) / 5.0)                  # put-rich skew → long risk reversal = bullish lean (§7.5)
        except Exception:
            pass
    comps["combo"] = c_combo(comps)
    s, cov, w = combine(comps, W_INDEX, reg)
    side = "CE" if s > 0 else "PE"
    extra = []
    if ix:
        pcr = ix.get("pcr")
        if pcr:
            if (side == "CE" and pcr >= 1.1) or (side == "PE" and pcr <= 0.8):
                extra.append((f"PCR {pcr} supports {side}", 3))
            elif (side == "CE" and pcr <= 0.7) or (side == "PE" and pcr >= 1.3):
                extra.append((f"PCR {pcr} against", -4))
        try:
            ch = ix.get("chain") or []
            spot = float(ix.get("spot") or 0)
            near = [r for r in ch if abs(r["strike"] - spot) <= spot * 0.01]
            ce_add = sum(((r.get("CE") or {}).get("chg") or 0) for r in near)
            pe_add = sum(((r.get("PE") or {}).get("chg") or 0) for r in near)
            if ce_add or pe_add:
                bull = pe_add > ce_add
                extra.append((f"OI change near ATM: puts {pe_add / 1e5:+.1f} L vs calls {ce_add / 1e5:+.1f} L ({'put writers → support' if bull else 'call writers → resistance'})",
                              3 if bull == (side == "CE") else -4))
        except Exception:
            pass
    pts, conf = confirmations(d5, d15, d60, side, extra)
    q = quality(s, pts, cov)
    st = "NO TRADE" if cov < CFG["cover"] else band(q)
    return {"market": name, "engine": "INDEX", "side": side, "score": q, "status": st, "regime": reg, "regime_why": rwhy, "s": round(s, 3),
            "coverage": round(cov * 100), "comps": {k: (None if v is None else round(v, 2)) for k, v in comps.items()},
            "lead": max(((k, abs(v) * w.get(k, 0)) for k, v in comps.items() if v is not None and k != "combo"), key=lambda x: x[1], default=(None, 0))[0],
            "conf": conf, "ivs": ivs, "spot": round(float(d5["close"].iloc[-1]), 2), "bar": d5.index[-1].strftime("%H:%M"),
            "inv": _invalidation(d5, side)}


def _invalidation(d5, side):
    """Underlying stop: beyond the last 6 closed candles' swing, at least 0.8 ATR away."""
    a = float(_atr(d5).iloc[-1] or 0)
    c = float(d5["close"].iloc[-1])
    if side == "CE":
        return round(min(d5["low"].iloc[-6:].min(), c - 0.8 * a), 2)
    return round(max(d5["high"].iloc[-6:].max(), c + 0.8 * a), 2)


def _knn_daily(d, k=25):
    """§3.17 single-stock KNN on daily bars: features (5d, 20d return, volatility, distance from 20d high) → share of neighbours whose
    next day closed up. Uses only past rows (no peeking). → value in [-1, 1] or None."""
    if d is None or len(d) < 120:
        return None
    c = d["close"]
    F = pd.DataFrame({"r5": c.pct_change(5), "r20": c.pct_change(20), "vol": c.pct_change().rolling(20).std(),
                      "dh": c / c.rolling(20).max() - 1}).dropna()
    y = (c.shift(-1) / c - 1).reindex(F.index)
    X, Y = F.iloc[:-1], y.iloc[:-1].dropna()
    X = X.loc[Y.index]
    if len(X) < 60:
        return None
    mu, sd = X.mean(), X.std().replace(0, 1)
    Z = ((X - mu) / sd).values
    q = ((F.iloc[-1] - mu) / sd).values
    idx = np.argsort(np.sqrt(((Z - q) ** 2).sum(axis=1)))[:k]
    p = float((Y.values[idx] > 0).mean())
    return _clip((p - 0.5) * 4)


def stock_eval(sym, d, q, nifty_d, sector_rank, oi_kind=None, ev=None, prebreak=None, news=None):
    """d: daily bars (closed) · q: live quote {ltp, pct, vol_ratio, vwap, high, low} · nifty_d: NIFTY daily closes."""
    if d is None or len(d) < 70 or not q or not q.get("ltp"):
        return {"market": sym, "engine": "STOCK", "status": "NO TRADE", "why": "not enough data"}
    c = d["close"].astype(float)
    ltp = float(q["ltp"])
    r63 = ltp / c.iloc[-63] - 1 if len(c) > 63 else None
    r20 = ltp / c.iloc[-20] - 1
    vol20 = c.pct_change().tail(20).std() or 0.02
    comps = {}
    comps["momentum"] = _clip(((r63 or r20) / (vol20 * math.sqrt(63)) if r63 is not None else r20 / (vol20 * math.sqrt(20))) / 2)
    lowvol = _clip((0.02 - vol20) / 0.01)
    comps["multifactor"] = _clip(0.6 * (comps["momentum"] or 0) + 0.4 * (lowvol or 0) * (1 if (comps["momentum"] or 0) >= 0 else -1))
    comps["earnings"] = None
    if ev and ev.get("reaction") is not None:
        comps["earnings"] = _clip(ev["reaction"] / 5)
    elif ev and ev.get("drift") is not None:
        comps["earnings"] = _clip(ev["drift"] / 5)
    comps["sector"] = None if sector_rank is None else _clip((0.5 - sector_rank) * 2.5)          # rank 0 = strongest
    hi20, lo20 = d["high"].iloc[-20:].max(), d["low"].iloc[-20:].min()
    comps["sr"] = 1.0 if ltp > hi20 else -1.0 if ltp < lo20 else _clip(((ltp - lo20) / (hi20 - lo20) - 0.5) * 0.8) if hi20 > lo20 else 0.0
    comps["residual"] = None
    if nifty_d is not None and len(nifty_d) >= 61:
        try:
            s_r = c.pct_change().tail(60).values
            n_r = nifty_d.pct_change().reindex(c.index).tail(60).values
            ok = ~(np.isnan(s_r) | np.isnan(n_r))
            if ok.sum() >= 40:
                beta = np.polyfit(n_r[ok], s_r[ok], 1)[0]
                res = s_r[ok] - beta * n_r[ok]
                comps["residual"] = _clip(res[-20:].sum() / (res.std() * math.sqrt(20) + 1e-9) / 2)
        except Exception:
            pass
    comps["iv"] = None
    comps["knn"] = _knn_daily(d)
    s, cov, w = combine(comps, W_STOCK)
    side = "CE" if s > 0 else "PE"
    extra = []
    rel = (q.get("pct") or 0) - (nifty_d.pct_change().iloc[-1] * 100 if nifty_d is not None and len(nifty_d) > 1 else 0)
    if (side == "CE" and rel >= 1) or (side == "PE" and rel <= -1):
        extra.append((f"relative strength vs NIFTY {rel:+.1f}%", 4))
    elif (side == "CE" and rel <= -1) or (side == "PE" and rel >= 1):
        extra.append((f"weaker than NIFTY ({rel:+.1f}%)" if side == "CE" else f"stronger than NIFTY ({rel:+.1f}%)", -5))
    vr = q.get("vol_ratio") or 0
    if vr >= 1.5:
        extra.append((f"unusual volume {vr}×", 4))
    good = {"CE": ("Long Built Up", "Short Covering"), "PE": ("Short Built Up", "Long Unwinding")}
    if oi_kind:
        extra.append((f"OI: {oi_kind}", 4 if oi_kind in good[side] else -4))
    vw = q.get("vwap")
    if vw:
        ok = ltp > vw if side == "CE" else ltp < vw
        extra.append((f"{'above' if ltp > vw else 'below'} VWAP {vw:g}", 3 if ok else -5))
    if prebreak and prebreak.get("side") == side:
        extra.append((f"early breakout: {prebreak.get('status')}", 3))
    if news and news.get("side") == side:
        extra.append((f"news catalyst: {str(news.get('news') or '')[:60]}", 3))
    pts = sum(e[1] for e in extra)
    qsc = quality(s, pts, cov)
    st = "NO TRADE" if cov < CFG["cover"] else band(qsc)
    a = float(_atr(d).iloc[-1] or ltp * 0.02)
    return {"market": sym, "engine": "STOCK", "side": side, "score": qsc, "status": st, "s": round(s, 3), "coverage": round(cov * 100),
            "comps": {k: (None if v is None else round(v, 2)) for k, v in comps.items()},
            "lead": max(((k, abs(v) * w.get(k, 0)) for k, v in comps.items() if v is not None), key=lambda x: x[1], default=(None, 0))[0],
            "conf": [(e[0], e[1] > 0) for e in extra], "spot": ltp,
            "inv": round(ltp - 0.6 * a, 2) if side == "CE" else round(ltp + 0.6 * a, 2)}


def comm_eval(name, fr, roll=None, events=None):
    """fr: commodity frames {"5M","15M","1H"} from the MCX module (closed 1-min candles resampled)."""
    if not fr or fr.get("5M") is None or len(fr["5M"]) < 60:
        return {"market": name, "engine": "COMMODITY", "status": "NO TRADE", "why": "not enough MCX candles"}
    d5, d15, d60 = fr["5M"], fr.get("15M"), fr.get("1H")
    reg, rwhy = regime_of(d5, d60)
    comps = {"trend": c_trend(d15), "momentum": c_momentum(d5), "channel": c_channel(d15), "meanrev": c_meanrev(d15), "sr": c_sr(d5),
             "events": None if events is None else events, "iv": None, "roll": roll}
    s, cov, w = combine(comps, W_COMM, reg)
    side = "CE" if s > 0 else "PE"
    pts, conf = confirmations(d5, d15, d60 if d60 is not None else resample(d5, "60min"), side)
    if fr.get("has_vol") and len(d5) > 21:
        v = d5["volume"]
        vr = v.iloc[-1] / max(1, v.iloc[-21:-1].mean())
        if vr >= 1.5:
            pts += 3
            conf.append((f"MCX volume {vr:.1f}×", True))
    q = quality(s, pts, cov)
    st = "NO TRADE" if cov < CFG["cover"] else band(q)
    return {"market": name, "engine": "COMMODITY", "side": side, "score": q, "status": st, "regime": reg, "regime_why": rwhy, "s": round(s, 3),
            "coverage": round(cov * 100), "comps": {k: (None if v is None else round(v, 2)) for k, v in comps.items()},
            "lead": max(((k, abs(v) * w.get(k, 0)) for k, v in comps.items() if v is not None), key=lambda x: x[1], default=(None, 0))[0],
            "conf": conf, "spot": round(float(d5["close"].iloc[-1]), 2), "bar": d5.index[-1].strftime("%H:%M"), "inv": _invalidation(d5, side),
            "missing": ["global commodity direction", "dollar index", "USD/INR", "inventory data", "economic calendar"]}


# ───────────────────────── option plan + risk ─────────────────────────
def plan_option(opt, spot, inv, lot, delta=0.5):
    """opt: {ltp, bid, ask, strike, expiry, ...}. Premium SL from the underlying invalidation × delta; targets 1.5R / 2R / 3R."""
    e = float(opt.get("ask") or opt.get("ltp") or 0)
    if not e or not spot or not inv:
        return None, "no live premium"
    dist = abs(spot - inv)
    r = max(e * 0.08, min(e * 0.45, abs(delta) * dist))
    sl = round(e - r, 2)
    risk = r * (lot or 1)
    T = [round(e + k * r, 2) for k in (1.5, 2.0, 3.0)]
    bid, ask = opt.get("bid"), opt.get("ask")
    spread = round((ask - bid) / ask * 100, 2) if ask and bid else None
    p = {"entry_zone": [round(e, 2), round(e * 1.02, 2)], "entry": round(e, 2), "sl": sl, "targets": T, "risk_lot": round(risk), "rr_t2": 2.0,
         "spread_pct": spread, "lot": lot}
    if risk > CFG["risk"]:
        return p, f"1-lot risk ₹{risk:,.0f} > ₹{CFG['risk']:,}"
    if spread is not None and spread > 3:
        return p, f"spread {spread}% (illiquid)"
    return p, None


# ───────────────────────── backtest (underlying, walk-forward) ─────────────────────────
def _sim_intraday(d5, i, side, inv, end_i):
    """Enter at close of bar i; R = |entry − inv|; target 2R; stop inv; exit at end_i close. → R multiple."""
    e = float(d5["close"].iloc[i])
    R = abs(e - inv)
    if R <= 0:
        return None
    tgt = e + 2 * R if side == "CE" else e - 2 * R
    for j in range(i + 1, end_i + 1):
        h, l = float(d5["high"].iloc[j]), float(d5["low"].iloc[j])
        if side == "CE":
            if l <= inv:
                return -1.0
            if h >= tgt:
                return 2.0
        else:
            if h >= inv:
                return -1.0
            if l <= tgt:
                return 2.0
    x = float(d5["close"].iloc[end_i])
    return ((x - e) if side == "CE" else (e - x)) / R


def _stats(rs):
    rs = [r - CFG["slip_r"] for r in rs if r is not None]
    if not rs:
        return {"trades": 0}
    w = [r for r in rs if r > 0]
    l = [r for r in rs if r <= 0]
    eq = np.cumsum(rs)
    dd = float((np.maximum.accumulate(eq) - eq).max()) if len(eq) else 0.0
    return {"trades": len(rs), "wins": len(w), "losses": len(l), "win_pct": round(len(w) / len(rs) * 100, 1), "net_r": round(float(sum(rs)), 1),
            "pf": round(sum(w) / abs(sum(l)), 2) if l and sum(l) else None, "max_dd_r": round(dd, 1),
            "avg_win_r": round(float(np.mean(w)), 2) if w else None, "avg_loss_r": round(float(np.mean(l)), 2) if l else None}


def backtest_index(raw, min_score=None, step=1, learn=True):
    """raw: {name: 5-min OHLC}. Signals only at 15-min closes 09:45–14:30 on price-only strategies (no option-chain history exists).
    Walk-forward: first 60 % of days learn per-strategy edge → weights; last 40 % out-of-sample with those weights."""
    min_score = min_score or CFG["call"]
    out, per, learned = {}, {}, {}
    for name, d in (raw or {}).items():
        if d is None or len(d) < 600:
            continue
        d = d[["open", "high", "low", "close"]].copy()
        days = sorted(set(d.index.date))
        split = days[int(len(days) * 0.6)]
        sigs = []
        idx = np.arange(len(d))
        for i in idx[60::step]:
            t = d.index[i]
            if not (pd.Timestamp("09:45").time() <= t.time() <= pd.Timestamp("14:30").time()) or t.minute % 15 != 10:
                continue
            w = d.iloc[max(0, i - 600): i + 1]
            d15, d60 = resample(w, "15min"), resample(w, "60min")
            reg, _ = regime_of(w, d60)
            comps = {"momentum": c_momentum(w), "sr": c_sr(w), "trend": c_trend(d15), "meanrev": c_meanrev(d15), "ma3": c_ma3(d15), "iv": None, "skew": None}
            comps["combo"] = c_combo(comps)
            day_end = [j for j in range(i, min(len(d), i + 80)) if d.index[j].date() == t.date() and d.index[j].time() <= pd.Timestamp("15:15").time()]
            if not day_end:
                continue
            fwd = float(d["close"].iloc[min(i + 12, day_end[-1])] / d["close"].iloc[i] - 1)
            sigs.append({"i": i, "t": t, "reg": reg, "comps": comps, "end": day_end[-1], "fwd": fwd, "w": w})
        ins = [x for x in sigs if x["t"].date() < split]
        oos = [x for x in sigs if x["t"].date() >= split]
        wts = dict(W_INDEX)
        if learn and len(ins) >= 50:
            for k in ("momentum", "sr", "trend", "meanrev", "ma3", "combo"):
                v = [(x["comps"][k], x["fwd"]) for x in ins if x["comps"].get(k) not in (None, 0)]
                if len(v) >= 30:
                    hit = np.mean([1.0 if (a > 0) == (f > 0) else 0.0 for a, f in v])
                    wts[k] = round(W_INDEX[k] * max(0.25, min(2.0, 1 + (hit - 0.5) * 6)), 1)
            learned[name] = wts
        for part, rows, ww in (("in_sample", ins, W_INDEX), ("out_of_sample", oos, wts)):
            rs, last_day = [], {}
            for x in rows:
                s, cov, wu = combine(x["comps"], ww, x["reg"])
                side = "CE" if s > 0 else "PE"
                w = x["w"]
                pts, _ = confirmations(w, resample(w, "15min"), resample(w, "60min"), side)
                q = quality(s, pts, cov * (6 / 8))                       # IV + skew have no history → coverage is lower, honestly
                if q < min_score:
                    continue
                k = (x["t"].date(), side)
                if last_day.get(k, 0) >= 2:
                    continue
                last_day[k] = last_day.get(k, 0) + 1
                r = _sim_intraday(d, x["i"], side, _invalidation(w, side), x["end"])
                if r is None:
                    continue
                rs.append(r)
                lead = max(((kk, abs(v) * wu.get(kk, 0)) for kk, v in x["comps"].items() if v is not None and kk != "combo"), key=lambda z: z[1], default=(None, 0))[0]
                per.setdefault(lead or "?", []).append(r)
            out.setdefault(name, {})[part] = _stats(rs)
        out[name]["days"] = len(days)
        out[name]["from"], out[name]["to"] = str(days[0]), str(days[-1])
    allr = {}
    for name, v in out.items():
        for part in ("in_sample", "out_of_sample"):
            allr.setdefault(part, {"trades": 0})
    return {"markets": out, "by_strategy": {NAMES.get(k, k): _stats(v) for k, v in per.items()}, "learned": learned,
            "note": "Underlying-level backtest (index 5-min candles). Option premium history is not available, so results are in R "
                    "(1R = distance to the stop) after 0.05R slippage per trade. IV / skew / OI strategies cannot be backtested."}


def backtest_stocks(bars, nifty_d, sectors_of, hold=3, top=3, min_score=None):
    """Daily version of the stock engine (momentum, multifactor, sector rotation, S/R, residual, KNN — no earnings/IV history).
    Signal at day t close → enter t+1 open · stop 1 ATR · target 2 ATR · max `hold` days · best `top` per day."""
    min_score = min_score or CFG["call"]
    from .ailab import _bars_df
    D = {s: _bars_df(b) for s, b in (bars or {}).items()}
    D = {s: d for s, d in D.items() if d is not None and len(d) >= 150}
    if not D:
        return {"trades": 0}
    dates = sorted(set().union(*[set(d.index[-120:]) for d in D.values()]))
    rs, per = [], {}
    split = dates[int(len(dates) * 0.6)] if dates else None
    res = {"in_sample": [], "out_of_sample": []}
    sec_ret = {}
    for t in dates[:-hold - 1][::2]:
        cands = []
        sret = {}
        for s, d in D.items():
            if t not in d.index:
                continue
            i = d.index.get_loc(t)
            if i < 70:
                continue
            sec = (sectors_of or {}).get(s, "Others")
            sret.setdefault(sec, []).append(float(d["close"].iloc[i] / d["close"].iloc[i - 20] - 1))
        rank = {k: r for r, (k, _) in enumerate(sorted(((k, np.mean(v)) for k, v in sret.items()), key=lambda kv: -kv[1]))}
        nsec = max(1, len(rank) - 1)
        for s, d in D.items():
            if t not in d.index:
                continue
            i = d.index.get_loc(t)
            if i < 70:
                continue
            past = d.iloc[: i + 1]
            q = {"ltp": float(past["close"].iloc[-1]), "pct": float(past["close"].pct_change().iloc[-1] * 100),
                 "vol_ratio": float(past["volume"].iloc[-1] / max(1, past["volume"].iloc[-21:-1].mean()))}
            nd = nifty_d[nifty_d.index <= t] if nifty_d is not None else None
            r = stock_eval(s, past, q, nd, rank.get((sectors_of or {}).get(s, "Others"), nsec) / nsec)
            if r.get("score", 0) >= min_score and r["status"] != "NO TRADE":
                cands.append((r["score"], s, r, i))
        for _, s, r, i in sorted(cands, reverse=True)[:top]:
            d = D[s]
            if i + 1 >= len(d):
                continue
            e = float(d["open"].iloc[i + 1])
            a = float(_atr(d.iloc[: i + 1]).iloc[-1] or e * 0.02)
            up = r["side"] == "CE"
            stop, tgt = (e - a, e + 2 * a) if up else (e + a, e - 2 * a)
            out = None
            for j in range(i + 1, min(len(d), i + 1 + hold)):
                h, l = float(d["high"].iloc[j]), float(d["low"].iloc[j])
                if (up and l <= stop) or (not up and h >= stop):
                    out = -1.0
                    break
                if (up and h >= tgt) or (not up and l <= tgt):
                    out = 2.0
                    break
            if out is None:
                x = float(d["close"].iloc[min(len(d) - 1, i + hold)])
                out = ((x - e) if up else (e - x)) / a
            res["in_sample" if t < split else "out_of_sample"].append(out)
            per.setdefault(r.get("lead") or "?", []).append(out)
    return {"in_sample": _stats(res["in_sample"]), "out_of_sample": _stats(res["out_of_sample"]),
            "by_strategy": {NAMES.get(k, k): _stats(v) for k, v in per.items()}, "stocks": len(D),
            "note": "Daily-bar backtest on ~6 months of F&O stock candles; earnings and IV strategies have no history here. R after 0.05R slippage."}


def backtest_comm(frames_hist):
    """frames_hist: {name: 15-min OHLC of the current MCX future}. Same rules as live on 15-min closes; R after slippage."""
    out = {}
    for name, d15 in (frames_hist or {}).items():
        if d15 is None or len(d15) < 200:
            continue
        rs = []
        last = None
        for i in range(120, len(d15) - 1):
            w = d15.iloc[: i + 1]
            d60 = resample(w, "60min") if len(w) else None
            comps = {"trend": c_trend(w), "momentum": c_momentum(w), "channel": c_channel(w), "meanrev": c_meanrev(w), "sr": c_sr(w),
                     "events": None, "iv": None, "roll": None}
            reg, _ = regime_of(w, d60)
            s, cov, _w = combine(comps, W_COMM, reg)
            side = "CE" if s > 0 else "PE"
            pts, _ = confirmations(w, w, d60 if d60 is not None else w, side)
            if quality(s, pts, cov) < CFG["call"]:
                continue
            if last is not None and i - last < 8:
                continue
            last = i
            end = min(len(d15) - 1, i + 8)
            r = _sim_intraday(d15, i, side, _invalidation(w, side), end)
            if r is not None:
                rs.append(r)
        out[name] = _stats(rs)
        out[name]["from"], out[name]["to"] = str(d15.index[0].date()), str(d15.index[-1].date())
    return out
