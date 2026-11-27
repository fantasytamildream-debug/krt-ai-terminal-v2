"""🌍 v150 WORLD TOP STRATEGIES — 12 well-known trading METHODS as measurable rules (not advice from the people named).

Every method works on closed candles only: 1-hour trend · 15-min setup · 5-min entry. Each returns a side (CE / PE), the underlying
trigger price and the underlying invalidation (stop). A setup becomes a call only when:
  • the method suits the current regime of that instrument (unsuitable methods are switched off),
  • the method passed the walk-forward backtest (in-sample AND out-of-sample expectancy > 0 after costs),
  • the 100-point Global Consensus Score is ≥ 85 and nothing conflicts,
  • 1 lot risk ≤ ₹2,500 and planned R:R ≥ 1:2, live data, market open, risk lock off.
Scores are rule-based setup quality — NOT a win probability.
"""
import time

import numpy as np
import pandas as pd

from .trident import resample, _ema, _atr

# key, display name, method family (1-12), correlation group (independent confirmations = distinct groups)
METHODS = [
    ("vol_breakout", "Volatility Breakout", 1, "Larry Williams", "BREAKOUT"),
    ("holy_grail", "Holy Grail", 2, "Linda Bradford Raschke", "TREND"),
    ("turtle_soup", "Turtle Soup", 2, "Linda Bradford Raschke", "REVERSAL"),
    ("vcp", "VCP Breakout + RS", 3, "Mark Minervini", "BREAKOUT"),
    ("canslim", "CAN SLIM Momentum (price/volume proxy)", 4, "William O'Neil", "TREND"),
    ("wyckoff", "Spring / Upthrust", 5, "Richard Wyckoff", "REVERSAL"),
    ("ict", "Liquidity Sweep + CHOCH + FVG", 6, "ICT", "REVERSAL"),
    ("orb", "Opening Range Breakout", 7, "Toby Crabel", "BREAKOUT"),
    ("turtle", "Turtle Trend Following", 8, "Richard Dennis", "TREND"),
    ("darvas", "Darvas Box Breakout", 9, "Nicolas Darvas", "BREAKOUT"),
    ("bb_squeeze", "Bollinger Squeeze", 10, "John Bollinger", "BREAKOUT"),
    ("weinstein", "Stage Analysis", 11, "Stan Weinstein", "TREND"),
    ("vwap_mom", "VWAP + RVOL + Momentum", 12, "Quantitative", "FLOW"),
    ("vwap_mr", "VWAP Mean Reversion", 12, "Quantitative", "FLOW"),
]
MKEY = {m[0]: m for m in METHODS}
GROUP = {m[0]: m[4] for m in METHODS}
STOCK_ONLY = {"vcp", "canslim"}
DAILY = {"vcp", "canslim", "weinstein"}
# 4 · adaptive market intelligence — which methods are allowed in which regime
REGIME_OK = {
    "TRENDING": {"turtle", "vcp", "holy_grail", "darvas", "weinstein", "canslim", "vwap_mom"},
    "SIDEWAYS": {"ict", "turtle_soup", "vwap_mr"},
    "BREAKOUT": {"orb", "vol_breakout", "bb_squeeze", "vwap_mom"},
    "REVERSAL": {"wyckoff", "ict", "turtle_soup"},
}
# terminal sources that are the SAME idea as a global method → not counted twice (no correlated double scoring)
CORR = {"5-min orb": "orb", "orb": "orb", "ict silver bullet": "ict", "sweep+choch": "ict", "smc": "ict", "breakout ce": "darvas",
        "breakout/breakdown": "darvas", "vcp": "vcp", "pre-breakout": "bb_squeeze", "vwap": "vwap_mom"}
CFG = {"mode": "all", "elite": 95, "aplus": 90, "a": 85, "risk": 2500, "rr": 2.0, "max_day": 3, "cost_r": 0.15, "spread_max": 3.0}
COST_NOTE = ("costs per trade = 0.15R (≈ ₹47 brokerage+GST, STT/exchange/stamp ≈ 0.15 % of premium turnover, 1 % slippage each side "
             "on a ~₹15k premium / ₹2k risk lot). Option P&L ≈ underlying R × delta; intraday theta ignored.")
STATE = {"bt": None, "bt_time": None, "enabled": {}, "picks": [], "watch": [], "time": None, "err": None, "log": {}}


# ───────────────────────── indicators ─────────────────────────
def _adx(d, n=14):
    if d is None or len(d) < n * 2:
        return None
    h, l, c = d["high"], d["low"], d["close"]
    up, dn = h.diff(), -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(pdm, index=d.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    ndi = 100 * pd.Series(ndm, index=d.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)).fillna(0)
    return float(dx.ewm(alpha=1 / n, adjust=False).mean().iloc[-1])


def _daily_from(d5):
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in d5.columns:
        agg["volume"] = "sum"
    return d5.resample("1D").agg(agg).dropna(subset=["close"])


def context(d5, dd=None):
    """d5: 5-min OHLC(V) (several days, closed bars). dd: daily bars up to YESTERDAY (or None → built from d5)."""
    if d5 is None or len(d5) < 20:
        return None
    d5 = d5.sort_index()
    day = d5.index[-1].date()
    T = d5[d5.index.date == day]
    P = d5[d5.index.date < day]
    if not len(T):
        return None
    if dd is None or not len(dd):
        dd = _daily_from(P) if len(P) else None
    else:
        dd = dd[dd.index.date < day] if hasattr(dd.index[0], "date") else dd
    hv = "volume" in d5.columns and float(d5["volume"].tail(50).sum() or 0) > 0
    X = {"d5": d5, "T": T, "P": P, "dd": dd, "day": day, "px": float(T["close"].iloc[-1]), "open": float(T["open"].iloc[0]),
         "hm": T.index[-1].strftime("%H:%M"), "hv": hv}
    if dd is not None and len(dd):
        X["pdh"], X["pdl"], X["pdc"] = float(dd["high"].iloc[-1]), float(dd["low"].iloc[-1]), float(dd["close"].iloc[-1])
    tp = (T["high"] + T["low"] + T["close"]) / 3
    if hv and float(T["volume"].sum() or 0) > 0:
        vw = (tp * T["volume"]).cumsum() / T["volume"].cumsum().replace(0, np.nan)
    else:
        vw = tp.expanding().mean()
    X["vwap_s"] = vw.ffill()
    X["vwap"] = float(X["vwap_s"].iloc[-1])
    X["d15"] = resample(d5, "15min")
    X["d60"] = resample(d5, "60min")
    a15 = _atr(X["d15"]) if X["d15"] is not None and len(X["d15"]) > 5 else None
    X["atr15"] = float(a15.iloc[-1]) if a15 is not None and pd.notna(a15.iloc[-1]) else float((T["high"] - T["low"]).mean() * 2)
    X["rvol"] = None
    if hv and len(P):
        n = len(T)
        cums = [float(g["volume"].iloc[:n].sum()) for _, g in P.groupby(P.index.date)][-5:]
        base = np.mean([c for c in cums if c > 0]) if any(c > 0 for c in cums) else 0
        X["rvol"] = round(float(T["volume"].sum()) / base, 2) if base else None
    return X


def _sig(side, inv, why, trig=None):
    return {"side": side, "inv": round(float(inv), 2), "why": why, "trigger": round(float(trig), 2) if trig is not None else None}


# ───────────────────────── the 12 methods (14 rules) ─────────────────────────
def m_vol_breakout(X):
    """Larry Williams: today's open ± 0.6 × yesterday's range; fresh cross on a closed 5-min bar."""
    if "pdh" not in X or len(X["T"]) < 3:
        return None
    r1 = X["pdh"] - X["pdl"]
    up, dn = X["open"] + 0.6 * r1, X["open"] - 0.6 * r1
    c = X["T"]["close"]
    prev = c.iloc[-4:-1]
    if X["px"] > up and (prev <= up).any():
        return _sig("CE", max(X["open"], up - 0.35 * r1), f"close {X['px']:.2f} broke open+0.6×range {up:.2f}", up)
    if X["px"] < dn and (prev >= dn).any():
        return _sig("PE", min(X["open"], dn + 0.35 * r1), f"close {X['px']:.2f} broke open−0.6×range {dn:.2f}", dn)
    return None


def m_holy_grail(X):
    """Raschke Holy Grail: 15-min ADX > 30, first pullback to EMA20 that closes back in the trend direction."""
    d = X["d15"]
    if d is None or len(d) < 30:
        return None
    adx = _adx(d)
    if adx is None or adx < 30:
        return None
    e = _ema(d["close"], 20)
    c, h, l = d["close"], d["high"], d["low"]
    if e.iloc[-1] > e.iloc[-5] and c.iloc[-1] > e.iloc[-1] and l.iloc[-3:].min() <= e.iloc[-1] * 1.002 and c.iloc[-1] > h.iloc[-2]:
        return _sig("CE", l.iloc[-3:].min(), f"ADX {adx:.0f} uptrend · pullback held EMA20 {e.iloc[-1]:.2f}", h.iloc[-2])
    if e.iloc[-1] < e.iloc[-5] and c.iloc[-1] < e.iloc[-1] and h.iloc[-3:].max() >= e.iloc[-1] * 0.998 and c.iloc[-1] < l.iloc[-2]:
        return _sig("PE", h.iloc[-3:].max(), f"ADX {adx:.0f} downtrend · pullback rejected EMA20 {e.iloc[-1]:.2f}", l.iloc[-2])
    return None


def m_turtle_soup(X):
    """Raschke Turtle Soup: a new 20-bar (15-min) low/high that fails — close back inside within 2 bars (false breakout)."""
    d = X["d15"]
    if d is None or len(d) < 25:
        return None
    lo20, hi20 = float(d["low"].iloc[-22:-2].min()), float(d["high"].iloc[-22:-2].max())
    c = float(d["close"].iloc[-1])
    lo2, hi2 = float(d["low"].iloc[-2:].min()), float(d["high"].iloc[-2:].max())
    if lo2 < lo20 and c > lo20:
        return _sig("CE", lo2, f"20-bar low {lo20:.2f} broken to {lo2:.2f} and reclaimed (sellers trapped)", lo20)
    if hi2 > hi20 and c < hi20:
        return _sig("PE", hi2, f"20-bar high {hi20:.2f} broken to {hi2:.2f} and lost (buyers trapped)", hi20)
    return None


def m_vcp(X, rs=None):
    """Minervini VCP: near the high, 3 shrinking ranges, volume drying, RS ≥ 70 → buy only the pivot break (≥1.5× volume)."""
    dd = X["dd"]
    if dd is None or len(dd) < 60:
        return None
    c = dd["close"]
    hi50 = float(dd["high"].tail(50).max())
    if float(c.iloc[-1]) < 0.88 * hi50:
        return None
    rg = [float((dd["high"].iloc[a:b].max() - dd["low"].iloc[a:b].min()) / c.iloc[-1]) for a, b in ((-30, -20), (-20, -10), (-10, None))]
    if not (rg[0] > rg[1] > rg[2]):
        return None
    if "volume" in dd.columns and float(dd["volume"].tail(50).mean() or 0) > 0 and float(dd["volume"].tail(10).mean()) > float(dd["volume"].tail(50).mean()):
        return None
    if rs is not None and rs < 70:
        return None
    pivot = float(dd["high"].tail(10).max())
    if X["px"] > pivot and (X["rvol"] is None or X["rvol"] >= 1.5):
        inv = max(float(dd["low"].tail(5).min()), pivot * 0.97)
        return _sig("CE", inv, f"VCP ranges {rg[0] * 100:.1f}%→{rg[1] * 100:.1f}%→{rg[2] * 100:.1f}% · pivot {pivot:.2f} broken"
                    + (f" · RS {rs}" if rs else ""), pivot)
    return None


def m_canslim(X, rs=None):
    """O'Neil CAN SLIM (price/volume part only — earnings data is not available): N (near new high) · L (leader, 3-month return
    ≥ 15 % / RS ≥ 80) · S (volume ≥ 1.5×) · M (handled by market filter) → breakout above yesterday's high."""
    dd = X["dd"]
    if dd is None or len(dd) < 70:
        return None
    c = dd["close"]
    if float(c.iloc[-1]) < 0.95 * float(dd["high"].tail(250).max()):
        return None
    r63 = float(c.iloc[-1] / c.iloc[-64] - 1) if len(c) > 64 else 0
    if r63 < 0.15 and not (rs and rs >= 80):
        return None
    s50, sl_ = float(c.tail(50).mean()), float(c.tail(min(200, len(c))).mean())
    if s50 < sl_:
        return None
    if X["px"] > X["pdh"] and (X["rvol"] is None or X["rvol"] >= 1.5):
        a = float(_atr(dd).iloc[-1])
        return _sig("CE", max(X["pdl"], X["px"] - 1.5 * a), f"3-month +{r63 * 100:.0f}% · near 52-week high · above PDH {X['pdh']:.2f}", X["pdh"])
    return None


def m_wyckoff(X):
    """Wyckoff: inside a trading range (≤ 4 ATR wide) a spring (break of range low, close back inside on volume) / upthrust."""
    d = X["d15"]
    if d is None or len(d) < 40:
        return None
    hi, lo = float(d["high"].iloc[-32:-2].max()), float(d["low"].iloc[-32:-2].min())
    if hi - lo > 4 * X["atr15"]:
        return None
    c, o = float(d["close"].iloc[-1]), float(d["open"].iloc[-1])
    vok = True
    if "volume" in d.columns and float(d["volume"].tail(30).mean() or 0) > 0:
        vok = float(d["volume"].iloc[-2:].max()) >= 1.2 * float(d["volume"].iloc[-32:-2].mean())
    lo2, hi2 = float(d["low"].iloc[-2:].min()), float(d["high"].iloc[-2:].max())
    if lo2 < lo and c > lo and c > o and vok:
        return _sig("CE", lo2, f"spring under range low {lo:.2f} → closed back inside (accumulation)", lo)
    if hi2 > hi and c < hi and c < o and vok:
        return _sig("PE", hi2, f"upthrust over range high {hi:.2f} → closed back inside (distribution)", hi)
    return None


def m_ict(X):
    """ICT: sweep of PDH/PDL or the session high/low → change of character (close beyond the last swing) → FVG left behind."""
    T = X["T"]
    if len(T) < 10:
        return None
    w = T.iloc[-8:]
    before = T.iloc[:-8]
    lo_lvl = min([v for v in (X.get("pdl"), float(before["low"].min()) if len(before) else None) if v])
    hi_lvl = max([v for v in (X.get("pdh"), float(before["high"].max()) if len(before) else None) if v])
    j = int(np.argmin(w["low"].values))
    k = int(np.argmax(w["high"].values))
    c = X["px"]
    sb = "10:00" <= X["hm"] <= "11:00" or "13:30" <= X["hm"] <= "14:30"

    def fvg(seg, up):
        for i in range(2, len(seg)):
            if up and seg["low"].iloc[i] > seg["high"].iloc[i - 2]:
                return True
            if not up and seg["high"].iloc[i] < seg["low"].iloc[i - 2]:
                return True
        return False
    if float(w["low"].iloc[j]) < lo_lvl and j < len(w) - 1:
        sw_hi = float(T["high"].iloc[max(0, len(T) - 8 + j - 4): len(T) - 8 + j + 1].max())
        if c > sw_hi:
            f = fvg(w.iloc[j:], True)
            return _sig("CE", float(w["low"].iloc[j]), f"swept {lo_lvl:.2f} → CHOCH above {sw_hi:.2f}" + (" · FVG" if f else "")
                        + (" · Silver Bullet window" if sb else ""), sw_hi)
    if float(w["high"].iloc[k]) > hi_lvl and k < len(w) - 1:
        sw_lo = float(T["low"].iloc[max(0, len(T) - 8 + k - 4): len(T) - 8 + k + 1].min())
        if c < sw_lo:
            f = fvg(w.iloc[k:], False)
            return _sig("PE", float(w["high"].iloc[k]), f"swept {hi_lvl:.2f} → CHOCH below {sw_lo:.2f}" + (" · FVG" if f else "")
                        + (" · Silver Bullet window" if sb else ""), sw_lo)
    return None


def m_orb(X):
    """Crabel ORB: 09:15–09:45 range; first close beyond it (until 13:00); NR7 day before = stronger."""
    T = X["T"]
    if X["hm"] < "09:45" or X["hm"] > "13:00" or len(T) < 7:
        return None
    o = T[T.index.strftime("%H:%M") < "09:45"]
    if len(o) < 4:
        return None
    hi, lo = float(o["high"].max()), float(o["low"].min())
    mid = (hi + lo) / 2
    c = T["close"]
    nr7 = ""
    dd = X["dd"]
    if dd is not None and len(dd) >= 7:
        r = (dd["high"] - dd["low"]).tail(7)
        nr7 = " · NR7 day before" if float(r.iloc[-1]) <= float(r.min()) else ""
    if X["px"] > hi and (c.iloc[-4:-1] <= hi).any():
        return _sig("CE", mid, f"closed above opening range high {hi:.2f}{nr7}", hi)
    if X["px"] < lo and (c.iloc[-4:-1] >= lo).any():
        return _sig("PE", mid, f"closed below opening range low {lo:.2f}{nr7}", lo)
    return None


def m_turtle(X):
    """Dennis Turtle (System 1 on 1-hour bars): close beyond the 20-bar Donchian channel; stop = 10-bar opposite / 2 ATR."""
    d = X["d60"]
    if d is None or len(d) < 22:
        return None
    hi20, lo20 = float(d["high"].iloc[-21:-1].max()), float(d["low"].iloc[-21:-1].min())
    c, pc = float(d["close"].iloc[-1]), float(d["close"].iloc[-2])
    a = float(_atr(d).iloc[-1])
    if c > hi20 and pc <= hi20:
        return _sig("CE", max(float(d["low"].iloc[-10:].min()), c - 2 * a), f"1-hour close above 20-bar high {hi20:.2f}", hi20)
    if c < lo20 and pc >= lo20:
        return _sig("PE", min(float(d["high"].iloc[-10:].max()), c + 2 * a), f"1-hour close below 20-bar low {lo20:.2f}", lo20)
    return None


def m_darvas(X):
    """Darvas box on 15-min bars: a top that held ≥ 3 bars, a floor under it, box ≤ 3 ATR → close above the box (below = breakdown)."""
    d = X["d15"]
    if d is None or len(d) < 25:
        return None
    seg = d.iloc[-17:-1]
    it = int(np.argmax(seg["high"].values))
    ib = int(np.argmin(seg["low"].values))
    top, bot = float(seg["high"].iloc[it]), float(seg["low"].iloc[ib])
    if top - bot > 3 * X["atr15"]:
        return None
    c, pc = float(d["close"].iloc[-1]), float(d["close"].iloc[-2])
    if it <= len(seg) - 4 and c > top and pc <= top:
        return _sig("CE", max(bot, c - 1.5 * X["atr15"]), f"box {bot:.2f}–{top:.2f} → breakout", top)
    if ib <= len(seg) - 4 and c < bot and pc >= bot:
        return _sig("PE", min(top, c + 1.5 * X["atr15"]), f"box {bot:.2f}–{top:.2f} → breakdown", bot)
    return None


def _bbw(d):
    m = d["close"].rolling(20).mean()
    s = d["close"].rolling(20).std()
    return m, s, (4 * s / m)


def m_bb_squeeze(X):
    """Bollinger squeeze (15-min): band width at its lowest 20 % of the last 120 bars, then a close outside the band."""
    d = X["d15"]
    if d is None or len(d) < 45:
        return None
    m, s, w = _bbw(d)
    ww = w.dropna().tail(120)
    if len(ww) < 25:
        return None
    if float(w.iloc[-6:-1].min()) > float(ww.quantile(0.2)):
        return None
    up, dn = float(m.iloc[-1] + 2 * s.iloc[-1]), float(m.iloc[-1] - 2 * s.iloc[-1])
    c, pc = float(d["close"].iloc[-1]), float(d["close"].iloc[-2])
    pup, pdn = float(m.iloc[-2] + 2 * s.iloc[-2]), float(m.iloc[-2] - 2 * s.iloc[-2])
    if c > up and pc <= pup:
        return _sig("CE", float(m.iloc[-1]), f"squeeze (width in lowest 20 %) → close above upper band {up:.2f}", up)
    if c < dn and pc >= pdn:
        return _sig("PE", float(m.iloc[-1]), f"squeeze → close below lower band {dn:.2f}", dn)
    return None


def m_weinstein(X):
    """Weinstein stages on daily bars: Stage 2 = above a rising 30-week (150-day) average + new 30-day high; Stage 4 = mirror."""
    dd = X["dd"]
    if dd is None or len(dd) < 60:
        return None
    n = min(150, len(dd) - 10)
    ma = dd["close"].rolling(n).mean()
    c = float(dd["close"].iloc[-1])
    hi30, lo30 = float(dd["high"].tail(30).max()), float(dd["low"].tail(30).min())
    if c > ma.iloc[-1] and ma.iloc[-1] > ma.iloc[-10] and X["px"] > hi30:
        return _sig("CE", max(float(dd["low"].tail(10).min()), hi30 * 0.96), f"Stage 2: above rising {n}-day avg · new 30-day high {hi30:.2f}", hi30)
    if c < ma.iloc[-1] and ma.iloc[-1] < ma.iloc[-10] and X["px"] < lo30:
        return _sig("PE", min(float(dd["high"].tail(10).max()), lo30 * 1.04), f"Stage 4: below falling {n}-day avg · new 30-day low {lo30:.2f}", lo30)
    return None


def m_vwap_mom(X):
    """Quant momentum: above a rising VWAP, EMA9 > EMA21 (5-min), close beyond the last 3 bars, relative volume ≥ 1.3×."""
    d = X["T"]
    if len(d) < 8:
        return None
    c = d["close"]
    e9, e21 = _ema(X["d5"]["close"], 9).iloc[-1], _ema(X["d5"]["close"], 21).iloc[-1]
    vs = X["vwap_s"]
    rv = X["rvol"]
    if rv is not None and rv < 1.3:
        return None
    if X["px"] > X["vwap"] and vs.iloc[-1] > vs.iloc[-6 if len(vs) > 6 else 0] and e9 > e21 and X["px"] > float(d["high"].iloc[-4:-1].max()):
        return _sig("CE", max(float(d["low"].iloc[-3:].min()), X["vwap"] * 0.998) if X["vwap"] < X["px"] else float(d["low"].iloc[-3:].min()),
                    f"above rising VWAP {X['vwap']:.2f} · EMA9>EMA21" + (f" · RVOL {rv}×" if rv else ""), float(d["high"].iloc[-4:-1].max()))
    if X["px"] < X["vwap"] and vs.iloc[-1] < vs.iloc[-6 if len(vs) > 6 else 0] and e9 < e21 and X["px"] < float(d["low"].iloc[-4:-1].min()):
        return _sig("PE", min(float(d["high"].iloc[-3:].max()), X["vwap"] * 1.002) if X["vwap"] > X["px"] else float(d["high"].iloc[-3:].max()),
                    f"below falling VWAP {X['vwap']:.2f} · EMA9<EMA21" + (f" · RVOL {rv}×" if rv else ""), float(d["low"].iloc[-4:-1].min()))
    return None


def m_vwap_mr(X):
    """Quant mean reversion (sideways days): 2σ stretched from VWAP and the first candle turning back toward it."""
    d = X["T"]
    if len(d) < 12:
        return None
    dev = d["close"] - X["vwap_s"]
    sd = float(dev.std() or 0)
    if not sd:
        return None
    c, o, pc = float(d["close"].iloc[-1]), float(d["open"].iloc[-1]), float(d["close"].iloc[-2])
    z = float(dev.iloc[-2]) / sd
    if z <= -2 and c > o and c > pc:
        return _sig("CE", float(d["low"].iloc[-3:].min()), f"{z:.1f}σ below VWAP {X['vwap']:.2f} → turning up (target VWAP)", c)
    if z >= 2 and c < o and c < pc:
        return _sig("PE", float(d["high"].iloc[-3:].max()), f"{z:.1f}σ above VWAP {X['vwap']:.2f} → turning down (target VWAP)", c)
    return None


FN = {"vol_breakout": m_vol_breakout, "holy_grail": m_holy_grail, "turtle_soup": m_turtle_soup, "vcp": m_vcp, "canslim": m_canslim,
      "wyckoff": m_wyckoff, "ict": m_ict, "orb": m_orb, "turtle": m_turtle, "darvas": m_darvas, "bb_squeeze": m_bb_squeeze,
      "weinstein": m_weinstein, "vwap_mom": m_vwap_mom, "vwap_mr": m_vwap_mr}


def regime(X, sigs=None):
    """TRENDING (15-min ADX ≥ 25 + EMA20 slope) · BREAKOUT (Bollinger width in lowest 20 %) · REVERSAL (a sweep / spring / soup just
    fired) · SIDEWAYS (none of these)."""
    d = X.get("d15")
    if d is None or len(d) < 30:
        return "SIDEWAYS", {}
    adx = _adx(d) or 0
    e = _ema(d["close"], 20)
    slope = float((e.iloc[-1] / e.iloc[-6] - 1) * 100) if len(e) > 6 else 0
    _, _, w = _bbw(d)
    ww = w.dropna().tail(120)
    pct = float((ww <= ww.iloc[-1]).mean()) if len(ww) > 20 else 0.5
    info = {"adx": round(adx, 1), "ema_slope_pct": round(slope, 2), "bb_width_pct": round(pct * 100)}
    if pct <= 0.2:
        return "BREAKOUT", info
    if adx >= 25 and abs(slope) >= 0.15:
        return "TRENDING", info
    if sigs and any(k in sigs for k in ("turtle_soup", "wyckoff", "ict")):
        return "REVERSAL", info
    return "SIDEWAYS", info


def evaluate(d5, dd=None, is_index=False, rs=None, d5_is_closed=True):
    """→ {regime, info, signals {key: sig}, allowed, off {key: reason}} or None."""
    X = context(d5, dd)
    if X is None:
        return None
    sigs = {}
    for k, f in FN.items():
        if is_index and k in STOCK_ONLY:
            continue
        try:
            s = f(X, rs) if k in ("vcp", "canslim") else f(X)
        except Exception:
            s = None
        if s:
            sigs[k] = s
    rg, info = regime(X, sigs)
    ok = REGIME_OK[rg]
    return {"regime": rg, "info": info, "signals": sigs, "allowed": sorted(k for k in sigs if k in ok),
            "off": {k: f"not suited to a {rg.lower()} market" for k in sigs if k not in ok}, "X": X}


# ───────────────────────── 100-point Global Consensus Score ─────────────────────────
def band(q):
    return "ELITE SETUP" if q >= CFG["elite"] else "A+ SETUP" if q >= CFG["aplus"] else "A GRADE SETUP" if q >= CFG["a"] else "WATCHLIST / NO TRADE"


def score(ev, side, ext, enabled):
    """ext: nifty_pct, is_index, oi_kind, opt_flow, rs_pct, terminal [sources same side], terminal_opp, plan, plan_bad, spread, delta, dte,
    pcr. enabled: {method: 'on'|'off'|'untested'} from the walk-forward backtest. → dict(total, parts, band, why, reject)."""
    X, S = ev["X"], ev["signals"]
    sg = 1 if side == "CE" else -1
    why, warn, reject = [], [], None
    live = (lambda k: True) if CFG.get("mode") == "all" else (lambda k: enabled.get(k) in ("on", "recent"))   # v151: user → all methods ON
    same = [k for k in ev["allowed"] if S[k]["side"] == side and live(k)]
    opp = [k for k in ev["allowed"] if S[k]["side"] != side and live(k)]
    fired_not_on = [k for k in ev["allowed"] if S[k]["side"] == side and not live(k)]
    groups = sorted({GROUP[k] for k in same})
    p_g = min(25, 9 * len(groups) + 2 * (len(same) - len(groups))) if same else 0
    if opp and len(opp) >= len(same):
        reject = f"conflict: {', '.join(MKEY[k][1] for k in opp)} point the other way"
    elif opp:
        p_g = max(0, p_g - 5)
        warn.append(f"{len(opp)} method(s) on the other side")
    for k in same:
        why.append(f"🌍 {MKEY[k][1]} ({MKEY[k][3]}-style): {S[k]['why']}")
        st_ = enabled.get(k, "untested")
        if st_ in ("off", "weak"):
            warn.append(f"{MKEY[k][1]}: backtest weak (out-of-sample not profitable) — ON by your choice, use small size")
        elif st_ == "untested":
            warn.append(f"{MKEY[k][1]}: not enough backtest trades yet")
    for k in fired_not_on:
        warn.append(f"{MKEY[k][1]} fired but {'failed' if enabled.get(k) == 'off' else 'has no'} walk-forward test — not counted")
    # terminal strategies (drop the ones that are the same idea as a global method that already fired)
    fired = set(S)
    term = [t for t in dict.fromkeys(ext.get("terminal") or []) if CORR.get(_nk(t)) not in fired]
    topp = list(dict.fromkeys(ext.get("terminal_opp") or []))
    p_t = {0: 0, 1: 8, 2: 14}.get(len(term), 20)
    if len(topp) >= 2 and len(topp) > len(term):
        reject = reject or f"conflict: terminal strategies on the other side ({', '.join(topp[:3])})"
    if term:
        why.append(f"🖥 terminal strategies agree: {', '.join(term[:5])}")
    # price action + market direction (15)
    p_pa = 0
    npct = ext.get("nifty_pct")
    if ext.get("is_index"):
        d15 = X["d15"]
        if d15 is not None and len(d15) > 21 and (float(d15["close"].iloc[-1]) - float(_ema(d15["close"], 20).iloc[-1])) * sg > 0:
            p_pa += 5
    elif npct is not None and npct * sg >= 0.15:
        p_pa += 5
    elif npct is not None and npct * sg <= -0.3:
        warn.append(f"against NIFTY {npct:+.2f}%")
    if (X["px"] - X["vwap"]) * sg > 0:
        p_pa += 5
        why.append(f"{'above' if side == 'CE' else 'below'} VWAP {X['vwap']:.2f}")
    if "pdh" in X:
        T = X["T"]
        if side == "CE" and X["px"] > X["pdh"]:
            p_pa += 5
        elif side == "PE" and X["px"] < X["pdl"]:
            p_pa += 5
        elif side == "CE" and float(T["high"].max()) > X["pdh"] and X["px"] < X["pdh"]:
            p_pa = max(0, p_pa - 5)
            warn.append(f"false breakout: went above PDH {X['pdh']:.2f} and fell back")
        elif side == "PE" and float(T["low"].min()) < X["pdl"] and X["px"] > X["pdl"]:
            p_pa = max(0, p_pa - 5)
            warn.append(f"false breakdown: went below PDL {X['pdl']:.2f} and came back")
    # OI + option chain (15)
    p_oi = 0
    k_ = str(ext.get("oi_kind") or "").lower()
    if k_:
        if (side == "CE" and "long build" in k_) or (side == "PE" and "short build" in k_):
            p_oi += 8
            why.append(f"fresh OI: futures {ext['oi_kind']}")
        elif (side == "CE" and "short cover" in k_) or (side == "PE" and "long unwind" in k_):
            p_oi += 5
            why.append(f"futures {ext['oi_kind']}")
        else:
            warn.append(f"futures {ext['oi_kind']} (other side)")
    pcr = ext.get("pcr")
    if pcr and ext.get("is_index"):
        if (side == "CE" and pcr >= 1.1) or (side == "PE" and pcr <= 0.85):
            p_oi += 8
            why.append(f"option chain PCR {pcr}")
    f_ = ext.get("opt_flow")
    if f_ == "buyers":
        p_oi += 7
        why.append("buyers entering this option (OI ↑ premium ↑)")
    elif f_ == "sellers_exit":
        p_oi += 4
    elif f_ == "writers":
        warn.append("writers selling this option (OI ↑ premium ↓)")
    p_oi = min(15, p_oi)
    # volume + relative strength (10)
    p_v = 0
    rv = X["rvol"]
    if rv is not None:
        p_v += 5 if rv >= 2 else 4 if rv >= 1.5 else 2 if rv >= 1.2 else 0
        if rv >= 1.5:
            why.append(f"volume {rv}× normal")
    else:
        T = X["T"]
        rg = (T["high"] - T["low"])
        if len(rg) > 6 and float(rg.iloc[-1]) > 1.3 * float(rg.iloc[:-1].mean()):
            p_v += 3
    rsp = ext.get("rs_pct")
    if rsp is not None and not ext.get("is_index"):
        p_v += 5 if rsp * sg >= 0.5 else 2 if rsp * sg >= 0 else 0
        if rsp * sg >= 0.5:
            why.append(f"relative strength vs NIFTY {rsp:+.1f}%")
    elif ext.get("is_index"):
        p_v += 3
    p_v = min(10, p_v)
    # multi-timeframe (5): 1-hour trend · 15-min setup · 5-min entry
    agree = 0
    for d in (X["d60"], X["d15"]):
        if d is not None and len(d) > 21 and (float(d["close"].iloc[-1]) - float(_ema(d["close"], 20).iloc[-1])) * sg > 0:
            agree += 1
    T = X["T"]
    if len(T) > 2 and (X["px"] - (float(T["high"].iloc[-2]) if side == "CE" else float(T["low"].iloc[-2]))) * sg > 0:
        agree += 1
    p_m = 5 if agree == 3 else 3 if agree == 2 else 0
    if agree == 3:
        why.append("1-hour, 15-min and 5-min all agree")
    # option liquidity + risk-to-reward (10)
    p_l = 0
    plan, bad = ext.get("plan"), ext.get("plan_bad")
    if not plan:
        reject = reject or "no live option premium"
    else:
        if bad and "risk" in bad:
            reject = reject or f"1 lot risk ₹{plan['risk_lot']:,} > ₹{CFG['risk']:,} even on a cheaper strike"
        sp = plan.get("spread_pct")
        if sp is not None and sp > CFG["spread_max"]:
            reject = reject or f"bid-ask spread {sp}% — illiquid"
        p_l += 5 if sp is not None and sp <= 2 else 3 if sp is not None and sp <= 3 else 2
        if (plan.get("rr_t2") or 0) >= CFG["rr"] and plan.get("risk_lot", 9e9) <= CFG["risk"]:
            p_l += 5
        dl = ext.get("delta")
        if dl is not None and not 0.25 <= abs(dl) <= 0.75:
            p_l = max(0, p_l - 2)
            warn.append(f"delta {dl}")
        if ext.get("dte") == 0 and X["hm"] >= "13:00":
            reject = reject or "expiry day after 1 PM — theta too fast"
    raw = p_g + p_t + p_pa + p_oi + p_v + p_m + p_l
    # v151: data that does not exist for a market is left out, not counted as zero (MCX has no stock-futures OI build-up, no
    # NIFTY relative strength, no sector; indices have no stock futures OI) → score = points ÷ points possible × 100
    mx = 100
    if ext.get("market") == "COMMODITY":
        mx -= 8 + 5                      # futures OI build-up (8) · relative strength (5)
    elif ext.get("is_index"):
        mx -= 8 if not pcr else 0        # stock futures OI build-up (index has PCR instead)
    total = int(round(min(100, raw * 100 / mx)))
    if not same:
        reject = reject or "no global method fired on this side"
    return {"total": total, "band": band(total), "reject": reject, "why": why[:10], "warn": warn[:6], "groups": groups,
            "possible": mx, "raw": raw, "parts": {"global": p_g, "terminal": p_t, "price_action": p_pa, "oi_chain": p_oi, "volume_rs": p_v, "mtf": p_m, "liquidity_rr": p_l},
            "global_matches": [MKEY[k][1] for k in same], "terminal_matches": term}


def _nk(s):
    import re
    s = re.sub(r"[^a-z0-9+\-/ ]", " ", str(s or "").lower())
    return " ".join(w for w in s.split() if w != "v4")


# ───────────────────────── backtest (walk-forward, costs) ─────────────────────────
def _sim(d5, i, side, inv, end_i, rr=2.0):
    e = float(d5["close"].iloc[i])
    R = abs(e - inv)
    if R <= e * 0.0005:
        return None
    tgt = e + rr * R if side == "CE" else e - rr * R
    for j in range(i + 1, end_i + 1):
        h, l = float(d5["high"].iloc[j]), float(d5["low"].iloc[j])
        if side == "CE":
            if l <= inv:
                return -1.0
            if h >= tgt:
                return rr
        else:
            if h >= inv:
                return -1.0
            if l <= tgt:
                return rr
    x = float(d5["close"].iloc[end_i])
    return ((x - e) if side == "CE" else (e - x)) / R


def stats(rs, cost=None):
    cost = CFG["cost_r"] if cost is None else cost
    rs = [r - cost for r in rs if r is not None]
    if not rs:
        return {"trades": 0}
    w = [r for r in rs if r > 0]
    l = [r for r in rs if r <= 0]
    eq = np.cumsum(rs)
    dd = float((np.maximum.accumulate(eq) - eq).max()) if len(eq) else 0.0
    return {"trades": len(rs), "win_pct": round(len(w) / len(rs) * 100, 1), "net_r": round(float(sum(rs)), 1),
            "exp_r": round(float(np.mean(rs)), 3), "pf": round(sum(w) / abs(sum(l)), 2) if l and sum(l) else None, "max_dd_r": round(dd, 1)}


def backtest_intraday(raw, step_min=30, max_days=130, log=None, pause=0.0):
    """raw: {name: 5-min OHLC (months)}. At every 30-min close 09:45–14:30 each method is checked on data up to that bar only; one trade
    per method per day; stop = the method's invalidation, target 2R, exit at 15:15. → trades per method (with date + regime)."""
    out = {k: [] for k in FN}
    comb = []
    for name, d in (raw or {}).items():
        if d is None or len(d) < 800:
            continue
        d = d.sort_index()
        days = sorted(set(d.index.date))[-max_days:]
        dd_all = _daily_from(d)
        for di, day in enumerate(days[6:], 6):
            win = d[(d.index.date >= days[di - 5]) & (d.index.date <= day)]
            ti = np.where(win.index.date == day)[0]
            if len(ti) < 60:
                continue
            dd = dd_all[dd_all.index.date < day]
            done = set()
            end_i = int(ti[-1]) - 2 if len(ti) > 70 else int(ti[-1])
            cdone = False
            for i in ti:
                hm = win.index[i].strftime("%H:%M")
                if hm < "09:45" or hm > "14:30" or (win.index[i].minute % step_min) != 0:
                    continue
                if pause:
                    time.sleep(pause)                 # let the web server breathe (one shared CPU)
                ev = evaluate(win.iloc[: i + 1], dd, is_index=True)
                if not ev:
                    continue
                agree = {}
                for k in ev["allowed"]:
                    if k in done:
                        continue
                    s = ev["signals"][k]
                    r = _sim(win, i, s["side"], s["inv"], end_i)
                    if r is not None:
                        out[k].append({"d": str(day), "r": round(r, 3), "rg": ev["regime"], "n": name})
                        done.add(k)
                    agree.setdefault(s["side"], set()).add(GROUP[k])
                if not cdone:
                    for sd, gs in agree.items():
                        if len(gs) >= 2 and not agree.get("PE" if sd == "CE" else "CE"):
                            ks = [k for k in ev["allowed"] if ev["signals"][k]["side"] == sd]
                            inv = ev["signals"][ks[0]]["inv"]
                            r = _sim(win, i, sd, inv, end_i)
                            if r is not None:
                                comb.append({"d": str(day), "r": round(r, 3), "rg": ev["regime"], "n": name})
                                cdone = True
                            break
        if log:
            log(f"worldtop bt {name}: done")
    return out, comb


def backtest_daily(bars_df, nifty_df=None, hold=5, last=120):
    """Daily methods (VCP · CAN SLIM proxy · Weinstein) on stocks' daily bars: setup from bars up to yesterday, entry when today's high
    crosses the trigger, stop = invalidation, target 2R, max 5 days (same-bar stop+target counts as a stop)."""
    out = {k: [] for k in ("vcp", "canslim", "weinstein")}
    for sym, d in (bars_df or {}).items():
        if d is None or len(d) < 80:
            continue
        d = d.sort_index()
        n = len(d)
        for t in range(max(70, n - last), n - 1):
            prev = d.iloc[:t]
            today = d.iloc[t]
            for k in out:
                X = {"dd": prev, "px": float(today["high"]), "pdh": float(prev["high"].iloc[-1]), "pdl": float(prev["low"].iloc[-1]), "rvol": None}
                try:
                    s = FN[k](X, None) if k != "weinstein" else FN[k](X)
                except Exception:
                    s = None
                if not s or s["side"] != "CE" and k != "weinstein":
                    continue
                trig = s.get("trigger") or float(today["open"])
                e = max(trig, float(today["open"])) if s["side"] == "CE" else min(trig, float(today["open"]))
                R = abs(e - s["inv"])
                if R <= e * 0.002:
                    continue
                tgt = e + 2 * R if s["side"] == "CE" else e - 2 * R
                r = None
                for j in range(t, min(n, t + hold)):
                    h, l = float(d["high"].iloc[j]), float(d["low"].iloc[j])
                    if (s["side"] == "CE" and l <= s["inv"]) or (s["side"] == "PE" and h >= s["inv"]):
                        r = -1.0
                        break
                    if (s["side"] == "CE" and h >= tgt) or (s["side"] == "PE" and l <= tgt):
                        r = 2.0
                        break
                if r is None:
                    x = float(d["close"].iloc[min(n - 1, t + hold - 1)])
                    r = ((x - e) if s["side"] == "CE" else (e - x)) / R
                out[k].append({"d": str(d.index[t].date()), "r": round(r, 3), "rg": "DAILY", "n": sym})
    return out


def walk_forward(trades, split=0.6, min_oos=8):
    """Per method: first 60 % of dates in-sample, last 40 % out-of-sample. 'on' only when BOTH expectancies > 0 after costs."""
    res, enabled = {}, {}
    for k, rows in trades.items():
        if not rows:
            res[k] = {"all": {"trades": 0}}
            enabled[k] = "untested"
            continue
        ds = sorted({r["d"] for r in rows})
        cut = ds[int(len(ds) * split)] if len(ds) > 3 else ds[-1]
        ins = [r["r"] for r in rows if r["d"] < cut]
        oos = [r["r"] for r in rows if r["d"] >= cut]
        rg = {}
        for r in rows:
            rg.setdefault(r["rg"], []).append(r["r"])
        a, b = stats(ins), stats(oos)
        res[k] = {"all": stats([r["r"] for r in rows]), "in": a, "oos": b, "regime": {g: stats(v) for g, v in rg.items()}, "cut": cut}
        if b.get("trades", 0) < min_oos:
            enabled[k] = "untested"
        else:
            enabled[k] = ("on" if (a.get("exp_r", -1) > 0 and b.get("exp_r", -1) > 0)
                          else "recent" if b.get("exp_r", -1) > 0 else "weak")
    return res, enabled
