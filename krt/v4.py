"""KRT AI TERMINAL V4 — FULL ACTIVE MULTI-STRATEGY INDEX SCANNER (Gamma Blast-ன் upgrade).
NIFTY · BANKNIFTY · FINNIFTY · SENSEX → regime → 5 strategies → FORMING / READY / CONFIRMED → strike → premium trigger → call.

நேர்மை குறிப்புகள் (website-லும் காட்டப்படும்):
  • Completed candles மட்டும் (future candle leakage இல்லை). Angel REST candles — tick data இல்லை.
  • Index spot-க்கு volume இல்லை → near-month index FUTURES volume (instrument master-ல் கிடைத்தால்). இல்லைன்னா volume checks "data இல்லை".
  • "Order flow" = volume-based PROXY (candle body × volume). Real bid/ask trade-level order flow இல்லை.
  • GEX = option chain-ல் இருந்து ESTIMATE. Dealer positioning verified இல்லை.
  • Score = ranking மட்டும், win probability இல்லை.
"""
import json
import math
import threading
from pathlib import Path

import numpy as np
import pandas as pd

from .instruments import INDEX_SPOT, INDEX_OPT_EXCH

ROOT = Path(__file__).resolve().parent.parent
SET_FILE = ROOT / "data" / "v4_settings.json"
STRATS = ["CQSMC", "ORDERFLOW", "GAMMA", "SILVER", "VWAPMR"]
SNAME = {"CQSMC": "🥇 CQSMC PRO", "ORDERFLOW": "🥈 Order Flow + Profile", "GAMMA": "🥉 Gamma Squeeze",
         "SILVER": "⚡ ICT Silver Bullet", "VWAPMR": "💎 VWAP Mean Reversion"}
DEFAULT = {
    "indices": {"NIFTY": True, "BANKNIFTY": True, "SENSEX": True, "FINNIFTY": True},
    "strategies": {k: True for k in STRATS},
    "scan_mode": "FULL ACTIVE", "timeframes": ["1M", "3M", "5M", "15M", "1H"],
    "min_score": 85, "watch_score": 70, "min_rr": 2.0, "max_risk": 2500, "min_t1_rs": 1500,
    "early_detection": True, "entry_confirmation": True, "duplicate_filter": True,
    "telegram": False, "auto_trading": False,
    "silver_windows": [["10:00", "11:00"], ["13:30", "14:30"]],      # Indian session-க்கு adapt — backtest-ல் tune பண்ணணும்
    "weights": {"trend": 15, "liquidity": 20, "bos": 15, "volume": 15, "gamma": 15, "vwap": 10, "option": 10},
    "premium_trigger_pct": 2.0, "dup_minutes": 45, "stale_minutes": 3,
}
LOCK = threading.Lock()
STATE = {"t": None, "indices": {}, "setups": [], "errors": [], "bt": None, "bt_running": False, "pending": {}, "last_sig": {},
         "prog": "", "tried": None}
NODATA = {}     # idx → காரணம்
CACHE = {}      # idx → {"day", "m1", "f5"} — முந்தைய நாட்கள் data ஒரு நாளைக்கு ஒருமுறை மட்டும் fetch


def clean(o):
    """numpy → python (JSON-ல் np.bool_ "False" string ஆகாம)."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if np.isnan(o) else float(o)
    if isinstance(o, float) and math.isnan(o):
        return None
    return o


# ───────────────────────── settings ─────────────────────────
def settings():
    s = json.loads(json.dumps(DEFAULT))
    try:
        if SET_FILE.exists():
            u = json.loads(SET_FILE.read_text(encoding="utf-8"))
            for k, v in u.items():
                if isinstance(v, dict) and isinstance(s.get(k), dict):
                    s[k].update(v)
                else:
                    s[k] = v
    except Exception:
        pass
    s["auto_trading"] = False          # இந்த app order போடாது — எப்போதும் OFF
    return s


def save_settings(d):
    s = settings()
    for k in ("indices", "strategies"):
        if isinstance(d.get(k), dict):
            s[k].update({x: bool(v) for x, v in d[k].items() if x in s[k]})
    for k in ("min_score", "watch_score", "max_risk", "min_t1_rs", "premium_trigger_pct", "dup_minutes"):
        if d.get(k) is not None:
            s[k] = float(d[k])
    if d.get("min_rr") is not None:
        s["min_rr"] = max(1.0, float(d["min_rr"]))
    for k in ("early_detection", "entry_confirmation", "duplicate_filter", "telegram"):
        if k in d:
            s[k] = bool(d[k])
    s["max_risk"] = min(s["max_risk"], 2500)
    s["auto_trading"] = False
    SET_FILE.parent.mkdir(parents=True, exist_ok=True)
    SET_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    return s


# ───────────────────────── data ─────────────────────────
def _completed(df, now, minutes):
    if df is None or df.empty:
        return df
    end = pd.Timestamp(now).tz_localize(None) if pd.Timestamp(now).tzinfo else pd.Timestamp(now)
    return df[df.index + pd.Timedelta(minutes=minutes) <= end]


def _resample(m1, rule, offset=None):
    if m1 is None or m1.empty:
        return pd.DataFrame()
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "fvol" in m1:
        agg["fvol"] = "sum"
    out = []
    for _, g in m1.groupby(m1.index.date):
        r = g.resample(rule, origin="start_day", offset=offset or "9h15min", label="left", closed="left").agg(agg)
        out.append(r.dropna(subset=["close"]))
    return pd.concat(out) if out else pd.DataFrame()


def fut_token(inst, idx):
    f = (inst or {}).get("fut", {}).get(idx)
    return (f[3], f[0]) if f else None


def load_frames(ag, inst, idx, now):
    """1m spot → 3m/5m/15m/1h. முந்தைய 7 நாள் ஒருமுறை (cache) + இன்றைய 1m மட்டும் ஒவ்வொரு நிமிடமும் (வேகம், API load குறைவு)."""
    now_ = pd.Timestamp(now).tz_localize(None) if pd.Timestamp(now).tzinfo else pd.Timestamp(now)
    day0 = now_.normalize()
    ex, tok = INDEX_SPOT[idx]
    ft = fut_token(inst, idx)
    ch = CACHE.get(idx)
    if not ch or ch["day"] != day0:
        h1 = None
        for back in (7, 5, 3):        # Angel rate-limit / empty ஆனா சின்ன window-ல் மறுபடி
            start = (day0 - pd.Timedelta(days=back)) + pd.Timedelta(hours=9, minutes=15)
            h1 = ag.candles(ex, tok, "ONE_MINUTE", start, day0 - pd.Timedelta(minutes=1))
            if h1 is not None and not h1.empty:
                break
            import time as _t
            _t.sleep(1.0)
        if h1 is None or h1.empty:
            NODATA[idx] = f"{idx} முந்தைய நாட்கள் 1-min candles Angel-ல் இருந்து வரல (rate limit / API) — அடுத்த நிமிடம் மறுபடி try"
            return None
        f5h = ag.candles(ft[0], ft[1], "FIVE_MINUTE", start, day0 - pd.Timedelta(minutes=1)) if ft else pd.DataFrame()
        ch = CACHE[idx] = {"day": day0, "m1": h1, "f5": f5h}
    t0 = day0 + pd.Timedelta(hours=9, minutes=15)
    parts = [ch["m1"]]
    fparts = [ch["f5"]] if ch["f5"] is not None and not ch["f5"].empty else []
    if now_ > t0:
        td = ag.candles(ex, tok, "ONE_MINUTE", t0, now_)
        if td is not None and not td.empty:
            parts.append(td)
        if ft:
            tf = ag.candles(ft[0], ft[1], "FIVE_MINUTE", t0, now_)
            if tf is not None and not tf.empty:
                fparts.append(tf)
    m1 = pd.concat(parts)
    m1 = m1[~m1.index.duplicated(keep="last")].sort_index()
    m1 = _completed(m1, now_, 1).between_time("09:15", "15:29")
    if m1.empty:
        NODATA[idx] = f"{idx} இன்றைய candles இல்லை"
        return None
    NODATA.pop(idx, None)
    fr = {"1M": m1, "3M": _resample(m1, "3min"), "5M": _resample(m1, "5min"), "15M": _resample(m1, "15min"),
          "1H": _resample(m1, "60min")}
    fv = None
    if fparts:
        f5 = pd.concat(fparts)
        f5 = _completed(f5[~f5.index.duplicated(keep="last")].sort_index(), now_, 5)
        fv = f5["volume"] if not f5.empty else None
    if fv is not None:
        fr["5M"] = fr["5M"].join(fv.rename("fvol"), how="left")
    fr["has_vol"] = fv is not None and float(fr["5M"].get("fvol", pd.Series(dtype=float)).fillna(0).sum()) > 0
    fr["data_time"] = (m1.index[-1] + pd.Timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
    return fr


# ───────────────────────── indicators ─────────────────────────
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=3).mean()


def rsi(s, n=14):
    d = s.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(), (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def session_vwap(day_df):
    """Futures volume இருந்தா VWAP; இல்லைன்னா TWAP (equal weight) — label செய்யப்படும்."""
    tp = (day_df["high"] + day_df["low"] + day_df["close"]) / 3
    w = day_df["fvol"].fillna(0) if "fvol" in day_df and day_df["fvol"].fillna(0).sum() > 0 else pd.Series(1.0, index=day_df.index)
    cw = w.cumsum().replace(0, np.nan)
    vw = (tp * w).cumsum() / cw
    var = ((tp - vw) ** 2 * w).cumsum() / cw
    return vw, np.sqrt(var)


def swings(df, n=2):
    hi, lo = [], []
    h, l = df["high"].values, df["low"].values
    for i in range(n, len(df) - n):
        if h[i] == max(h[i - n:i + n + 1]):
            hi.append((df.index[i], h[i]))
        if l[i] == min(l[i - n:i + n + 1]):
            lo.append((df.index[i], l[i]))
    return hi, lo


def structure(df):
    """Swing-based BOS / CHOCH. → dict(trend, event, level, time)."""
    hi, lo = swings(df)
    out = {"trend": None, "bos_up": None, "bos_dn": None, "choch_up": None, "choch_dn": None, "last_hi": None, "last_lo": None}
    if len(hi) < 2 or len(lo) < 2:
        return out
    out["last_hi"], out["last_lo"] = hi[-1][1], lo[-1][1]
    trend = "UP" if (hi[-1][1] > hi[-2][1] and lo[-1][1] > lo[-2][1]) else "DOWN" if (hi[-1][1] < hi[-2][1] and lo[-1][1] < lo[-2][1]) else "RANGE"
    out["trend"] = trend
    after_hi = df[df.index > hi[-1][0]]
    after_lo = df[df.index > lo[-1][0]]
    up_x = after_hi[after_hi["close"] > hi[-1][1]]
    dn_x = after_lo[after_lo["close"] < lo[-1][1]]
    if not up_x.empty:
        out["choch_up" if trend == "DOWN" else "bos_up"] = (str(up_x.index[0]), hi[-1][1])
    if not dn_x.empty:
        out["choch_dn" if trend == "UP" else "bos_dn"] = (str(dn_x.index[0]), lo[-1][1])
    return out


def fvgs(df, look=30):
    out = []
    d = df.tail(look)
    for i in range(2, len(d)):
        a, c = d.iloc[i - 2], d.iloc[i]
        if c["low"] > a["high"]:
            out.append({"side": "CE", "lo": float(a["high"]), "hi": float(c["low"]), "t": str(d.index[i])})
        if c["high"] < a["low"]:
            out.append({"side": "PE", "lo": float(c["high"]), "hi": float(a["low"]), "t": str(d.index[i])})
    return out


def displacement(df, a_):
    """கடைசி 6 bars-ல் body ≥ 1.2×ATR candle."""
    d = df.tail(6)
    for t, r in d[::-1].iterrows():
        body = abs(r["close"] - r["open"])
        if a_ and body >= 1.2 * a_:
            return {"side": "CE" if r["close"] > r["open"] else "PE", "t": str(t), "body": round(body, 2)}
    return None


def order_block(df, side, look=20):
    d = df.tail(look)
    a_ = float(atr(df).iloc[-1] or 0)
    for i in range(len(d) - 1, 0, -1):
        r = d.iloc[i]
        if a_ and abs(r["close"] - r["open"]) >= 1.2 * a_ and ((r["close"] > r["open"]) == (side == "CE")):
            for j in range(i - 1, max(i - 4, -1), -1):
                p = d.iloc[j]
                if (p["close"] < p["open"]) == (side == "CE"):
                    return {"lo": float(p["low"]), "hi": float(p["high"]), "t": str(d.index[j])}
    return None


def sweep(df, levels, look=12):
    """Level-ஐ wick தாண்டி close உள்ளே = liquidity sweep. → (side_for_trade, level_name, t)."""
    d = df.tail(look)
    for t, r in d[::-1].iterrows():
        for name, lv, kind in levels:
            if lv is None:
                continue
            if kind == "low" and r["low"] < lv and r["close"] > lv:
                return {"side": "CE", "level": name, "price": round(lv, 2), "t": str(t)}
            if kind == "high" and r["high"] > lv and r["close"] < lv:
                return {"side": "PE", "level": name, "price": round(lv, 2), "t": str(t)}
    return None


def equal_levels(points, tol=0.0006):
    v = [p[1] for p in points[-8:]]
    for i in range(len(v) - 1, 0, -1):
        for j in range(i - 1, -1, -1):
            if abs(v[i] - v[j]) / v[j] <= tol:
                return round((v[i] + v[j]) / 2, 2)
    return None


def volume_profile(df, bins=24):
    w = df["fvol"].fillna(0) if "fvol" in df and df["fvol"].fillna(0).sum() > 0 else None
    if w is None or df.empty:
        return None
    lo, hi = float(df["low"].min()), float(df["high"].max())
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    vol = np.zeros(bins)
    for (_, r), v in zip(df.iterrows(), w.values):
        a, b = np.searchsorted(edges, r["low"], "right") - 1, np.searchsorted(edges, r["high"], "right") - 1
        a, b = max(0, a), min(bins - 1, max(a, b))
        vol[a:b + 1] += v / (b - a + 1)
    poc_i = int(vol.argmax())
    order = np.argsort(-vol)
    tot, acc, inva = vol.sum(), 0, []
    for i in order:
        acc += vol[i]
        inva.append(i)
        if acc >= 0.7 * tot:
            break
    mid = (edges[:-1] + edges[1:]) / 2
    mean = vol.mean()
    return {"poc": round(mid[poc_i], 2), "vah": round(edges[max(inva) + 1], 2), "val": round(edges[min(inva)], 2),
            "hvn": [round(mid[i], 2) for i in range(bins) if vol[i] >= 1.5 * mean][:5],
            "lvn": [round(mid[i], 2) for i in range(bins) if 0 < vol[i] <= 0.4 * mean][:5]}


# ───────────────────────── context ─────────────────────────
def context(fr, gex=None, chain_row=None):
    m5, m15, h1 = fr["5M"], fr["15M"], fr["1H"]
    days = sorted(set(m5.index.date))
    today = days[-1]
    td = m5[m5.index.date == today]
    prev = m5[m5.index.date == days[-2]] if len(days) >= 2 else None
    a5 = float(atr(m5).iloc[-1] or 0)
    vw, sd = session_vwap(td)
    px = float(td["close"].iloc[-1])
    h1c = h1["close"]
    htf = "UP" if (len(h1c) > 50 and h1c.iloc[-1] > ema(h1c, 20).iloc[-1] > ema(h1c, 50).iloc[-1]) else \
        "DOWN" if (len(h1c) > 50 and h1c.iloc[-1] < ema(h1c, 20).iloc[-1] < ema(h1c, 50).iloc[-1]) else "FLAT"
    e15 = ema(m15["close"], 20)
    slope15 = float(e15.iloc[-1] - e15.iloc[-4]) if len(e15) > 4 else 0
    st5 = structure(m5.tail(120))
    st3 = structure(fr["3M"].tail(120))
    hi5, lo5 = swings(m5.tail(120))
    pdh = float(prev["high"].max()) if prev is not None and not prev.empty else None
    pdl = float(prev["low"].min()) if prev is not None and not prev.empty else None
    # previous session last-hour liquidity
    psh = float(prev.between_time("14:15", "15:29")["high"].max()) if prev is not None and not prev.empty else None
    psl = float(prev.between_time("14:15", "15:29")["low"].min()) if prev is not None and not prev.empty else None
    eqh, eql = equal_levels(hi5), equal_levels(lo5)
    levels = [("PDL", pdl, "low"), ("Prev session low", psl, "low"), ("Equal lows", eql, "low"),
              ("Swing low", lo5[-2][1] if len(lo5) > 1 else None, "low"),
              ("PDH", pdh, "high"), ("Prev session high", psh, "high"), ("Equal highs", eqh, "high"),
              ("Swing high", hi5[-2][1] if len(hi5) > 1 else None, "high")]
    has_vol = fr.get("has_vol")
    vol_ratio = None
    if has_vol and len(td) >= 4:
        base = m5["fvol"].fillna(0).tail(60).mean()
        vol_ratio = round(float(td["fvol"].fillna(0).tail(3).mean() / base), 2) if base else None
    delta_proxy = None
    if has_vol:
        rng = (td["high"] - td["low"]).replace(0, np.nan)
        dp = ((td["close"] - td["open"]) / rng * td["fvol"].fillna(0)).fillna(0)
        delta_proxy = {"cum": float(dp.sum()), "last3": float(dp.tail(3).sum())}
    vwap_cross = int(((td["close"] > vw) != (td["close"].shift() > vw.shift())).iloc[1:].sum()) if len(td) > 2 else 0
    day_rng = float(td["high"].max() - td["low"].min())
    adr = float((m5.groupby(m5.index.date).apply(lambda g: g["high"].max() - g["low"].min())).iloc[:-1].tail(5).mean() or 0)
    mom = td.tail(3)
    momentum = ("UP" if (mom["close"] > mom["open"]).all() and mom["close"].iloc[-1] - mom["open"].iloc[0] > 1.5 * a5 else
                "DOWN" if (mom["close"] < mom["open"]).all() and mom["open"].iloc[0] - mom["close"].iloc[-1] > 1.5 * a5 else None)
    oi = None
    if chain_row:
        ch = chain_row.get("chain") or []
        spot = chain_row.get("spot") or px
        near = sorted(ch, key=lambda r: abs(r["strike"] - spot))[:5]
        oi = {"ce_chg": sum((r.get("CE") or {}).get("chg", 0) for r in near), "pe_chg": sum((r.get("PE") or {}).get("chg", 0) for r in near)}
    return {"px": px, "atr": a5, "vwap": float(vw.iloc[-1]), "sd": float(sd.iloc[-1] or 0), "htf": htf, "slope15": slope15,
            "st5": st5, "st3": st3, "pdh": pdh, "pdl": pdl, "psh": psh, "psl": psl, "eqh": eqh, "eql": eql, "levels": levels,
            "vol_ratio": vol_ratio, "has_vol": has_vol, "delta": delta_proxy, "vwap_cross": vwap_cross, "day_rng": day_rng,
            "adr": adr, "momentum": momentum, "rsi": float(rsi(m5["close"]).iloc[-1] or 50), "gex": gex, "oi": oi,
            "today": td, "m5": m5, "m3": fr["3M"], "last_t": str(m5.index[-1])}


def regime(cx):
    st = cx["st5"]["trend"]
    up = cx["htf"] == "UP" and cx["px"] > cx["vwap"] and cx["slope15"] > 0 and st != "DOWN"
    dn = cx["htf"] == "DOWN" and cx["px"] < cx["vwap"] and cx["slope15"] < 0 and st != "UP"
    if cx["momentum"] and cx["day_rng"] > 0.9 * (cx["adr"] or 1e9):
        return "HIGH MOMENTUM"
    if up:
        return "STRONG UPTREND"
    if dn:
        return "STRONG DOWNTREND"
    if sweep(cx["m5"], cx["levels"], look=6):
        return "LIQUIDITY REVERSAL"
    if cx["vwap_cross"] >= 4 and cx["day_rng"] < 0.8 * (cx["adr"] or 1e9):
        return "SIDEWAYS"
    return "UNCLEAR"


PREFERRED = {"STRONG UPTREND": ["CQSMC", "ORDERFLOW"], "STRONG DOWNTREND": ["CQSMC", "ORDERFLOW"], "SIDEWAYS": ["VWAPMR"],
             "LIQUIDITY REVERSAL": ["SILVER"], "HIGH MOMENTUM": ["GAMMA"], "UNCLEAR": []}


# ───────────────────────── strategies ─────────────────────────
def _stage(forming, ready, confirmed):
    return "CONFIRMED" if confirmed else "READY" if ready else "FORMING" if forming else None


def s_cqsmc(cx):
    side = "CE" if cx["htf"] == "UP" else "PE" if cx["htf"] == "DOWN" else None
    sw = sweep(cx["m5"], cx["levels"], look=24)
    if side is None and sw:
        side = sw["side"]
    if side is None:
        return None
    ce = side == "CE"
    st = cx["st5"]
    bos = (st["bos_up"] or st["choch_up"]) if ce else (st["bos_dn"] or st["choch_dn"])
    liq = bool(sw and sw["side"] == side)
    fv = [f for f in fvgs(cx["m5"]) if f["side"] == side]
    ob = order_block(cx["m5"], side)
    g = cx.get("gex") or {}
    gamma_ok = bool(g.get("flip") and ((cx["px"] > g["flip"]) if ce else (cx["px"] < g["flip"]))) or "NEGATIVE" in str(g.get("zone", ""))
    oi = cx.get("oi") or {}
    unwind = bool(oi) and ((oi.get("ce_chg", 0) < 0) if ce else (oi.get("pe_chg", 0) < 0))
    vol = cx["vol_ratio"] is not None and cx["vol_ratio"] >= 1.5
    vwap_ok = (cx["px"] > cx["vwap"]) if ce else (cx["px"] < cx["vwap"])
    retest = bool(fv) and ((cx["today"]["low"].tail(3).min() <= fv[-1]["hi"]) if ce else (cx["today"]["high"].tail(3).max() >= fv[-1]["lo"]))
    last = cx["today"].iloc[-1]
    close_dir = (last["close"] > last["open"]) if ce else (last["close"] < last["open"])
    chk = {"HTF trend": cx["htf"] == ("UP" if ce else "DOWN"), "Liquidity sweep": liq, "BOS / CHOCH": bool(bos),
           "Order block": bool(ob), "Fair value gap": bool(fv), "Gamma (est.)": gamma_ok, "OI unwinding": unwind,
           "Volume (FUT)": vol, "VWAP": vwap_ok}
    stage = _stage(liq or chk["HTF trend"], liq and bool(bos) and vwap_ok, liq and bool(bos) and vwap_ok and (retest or bool(ob)) and close_dir)
    sl = (min(sw["price"], (ob or {}).get("lo", sw["price"])) - 0.2 * cx["atr"]) if (ce and sw) else \
         (max(sw["price"], (ob or {}).get("hi", sw["price"])) + 0.2 * cx["atr"]) if sw else (cx["px"] - 1.5 * cx["atr"] if ce else cx["px"] + 1.5 * cx["atr"])
    return {"side": side, "stage": stage, "chk": chk, "spot_sl": round(sl, 2),
            "buckets": {"trend": chk["HTF trend"], "liquidity": liq, "bos": bool(bos), "volume": vol, "gamma": gamma_ok or unwind,
                        "vwap": vwap_ok}, "notes": [f"Sweep: {sw['level']} {sw['price']}" if sw else "Sweep இல்லை",
                                                   f"FVG {fv[-1]['lo']:.0f}–{fv[-1]['hi']:.0f}" if fv else "", f"OB {ob['lo']:.0f}–{ob['hi']:.0f}" if ob else ""]}


def s_orderflow(cx):
    if not cx["has_vol"]:
        return {"side": None, "stage": None, "chk": {"Futures volume": False}, "notes": ["Index FUT volume data இல்லை — strategy off"], "buckets": {}}
    two = cx["m5"][cx["m5"].index.date >= sorted(set(cx["m5"].index.date))[-2]]
    vp = volume_profile(two)
    if not vp:
        return None
    td, px = cx["today"], cx["px"]
    c2 = td["close"].tail(2)
    above, below = (c2 > vp["vah"]).all(), (c2 < vp["val"]).all()
    side = "CE" if px > vp["poc"] else "PE"
    ce = side == "CE"
    dp = cx["delta"] or {}
    delta_ok = (dp.get("last3", 0) > 0) if ce else (dp.get("last3", 0) < 0)
    vol = (cx["vol_ratio"] or 0) >= 1.5
    vwap_ok = (px > cx["vwap"]) if ce else (px < cx["vwap"])
    near = abs(px - (vp["vah"] if ce else vp["val"])) <= 0.5 * cx["atr"]
    accept = above if ce else below
    one = (td["close"].iloc[-1] > vp["vah"]) if ce else (td["close"].iloc[-1] < vp["val"])
    chk = {"Value area acceptance": bool(accept), "Delta proxy": delta_ok, "Breakout volume": vol, "VWAP": vwap_ok,
           "HVN/LVN path": True}
    stage = _stage(near or one, one and delta_ok, accept and delta_ok and vol)
    sl = (vp["poc"] if ce else vp["poc"])
    return {"side": side, "stage": stage, "chk": chk, "spot_sl": round(sl, 2), "profile": vp,
            "buckets": {"trend": cx["slope15"] > 0 if ce else cx["slope15"] < 0, "liquidity": bool(accept), "bos": one,
                        "volume": vol and delta_ok, "gamma": False, "vwap": vwap_ok},
            "notes": [f"POC {vp['poc']} · VAH {vp['vah']} · VAL {vp['val']}", "Delta = volume PROXY (real order flow இல்லை)"]}


def s_gamma(cx):
    g = cx.get("gex") or {}
    if not g or g.get("status") not in ("ESTIMATED", "UNVERIFIED") or not g.get("call_wall"):
        return {"side": None, "stage": None, "chk": {"GEX data": False}, "notes": ["GEX data இல்லை (deep scan முடியட்டும்)"], "buckets": {}}
    px, cw, pw, flip = cx["px"], g["call_wall"], g["put_wall"], g.get("flip")
    side = "CE" if (px >= cw - 0.002 * px or (flip and px > flip and cx["slope15"] > 0)) else "PE" if (px <= pw + 0.002 * px or (flip and px < flip)) else None
    if side is None:
        return {"side": None, "stage": None, "chk": {}, "notes": [f"Walls {pw}–{cw} நடுவில்"], "buckets": {}}
    ce = side == "CE"
    wall = cw if ce else pw
    last = cx["today"].iloc[-1]
    broke = (last["close"] > wall) if ce else (last["close"] < wall)
    near = abs(px - wall) <= 0.002 * px
    oi = cx.get("oi") or {}
    unwind = bool(oi) and ((oi.get("ce_chg", 0) < 0) if ce else (oi.get("pe_chg", 0) < 0))
    build = bool(oi) and ((oi.get("pe_chg", 0) > 0) if ce else (oi.get("ce_chg", 0) > 0))
    vol = (cx["vol_ratio"] or 0) >= 1.5
    mom = cx["momentum"] == ("UP" if ce else "DOWN")
    neg = "NEGATIVE" in str(g.get("zone", ""))
    chk = {"Wall break (5m close)": bool(broke), "Gamma flip side": bool(flip and ((px > flip) if ce else (px < flip))),
           "Negative gamma zone (est.)": neg, "OI unwinding": unwind, "OI build-up (opposite)": build,
           "Volume expansion": vol, "Momentum": mom}
    stage = _stage(near or broke, broke and (unwind or build), broke and (unwind or build) and (vol or mom))
    return {"side": side, "stage": stage, "chk": chk, "spot_sl": round(wall - 0.6 * cx["atr"] if ce else wall + 0.6 * cx["atr"], 2),
            "buckets": {"trend": mom, "liquidity": broke, "bos": broke, "volume": vol, "gamma": neg or unwind or build, "vwap": (px > cx["vwap"]) if ce else (px < cx["vwap"])},
            "notes": [f"Call wall {cw} · Put wall {pw} · flip ≈ {flip}", f"GEX {g.get('status')} · IV missing {g.get('missing_iv_pct')}%"]}


def _in_windows(t, wins):
    hm = t.strftime("%H:%M")
    return any(a <= hm <= b for a, b in wins)


def s_silver(cx, now, S):
    inwin = _in_windows(pd.Timestamp(now), S["silver_windows"])
    sw = sweep(cx["m3"], cx["levels"], look=20)
    if not sw:
        return {"side": None, "stage": None, "chk": {"Time window": inwin, "Liquidity sweep": False}, "notes": ["Sweep இல்லை"], "buckets": {}}
    side = sw["side"]
    ce = side == "CE"
    st = cx["st3"]
    mss = bool(st["choch_up"] or st["bos_up"]) if ce else bool(st["choch_dn"] or st["bos_dn"])
    disp = displacement(cx["m3"], float(atr(cx["m3"]).iloc[-1] or 0))
    disp_ok = bool(disp and disp["side"] == side)
    fv = [f for f in fvgs(cx["m3"], 20) if f["side"] == side]
    last = cx["m3"].iloc[-1]
    retest = bool(fv) and ((last["low"] <= fv[-1]["hi"] and last["close"] > fv[-1]["hi"]) if ce else (last["high"] >= fv[-1]["lo"] and last["close"] < fv[-1]["lo"]))
    chk = {"Time window": inwin, "Liquidity sweep": True, f"Swept: {sw['level']}": True, "Market structure shift": mss,
           "Displacement candle": disp_ok, "Fair value gap": bool(fv), "FVG retest": retest}
    stage = _stage(True, inwin and mss and bool(fv), inwin and mss and disp_ok and retest)
    sl = sw["price"] - 0.15 * cx["atr"] if ce else sw["price"] + 0.15 * cx["atr"]
    return {"side": side, "stage": stage, "chk": chk, "spot_sl": round(sl, 2),
            "buckets": {"trend": cx["htf"] == ("UP" if ce else "DOWN"), "liquidity": True, "bos": mss, "volume": disp_ok,
                        "gamma": False, "vwap": (cx["px"] > cx["vwap"]) if ce else (cx["px"] < cx["vwap"])},
            "notes": [f"Window {', '.join(a + '–' + b for a, b in S['silver_windows'])} IST (Indian session-க்கு backtest-ல் tune பண்ணணும்)"]}


def s_vwapmr(cx, reg):
    if reg in ("STRONG UPTREND", "STRONG DOWNTREND", "HIGH MOMENTUM"):
        return {"side": None, "stage": None, "chk": {"Sideways market": False}, "notes": [f"{reg} — mean reversion OFF"], "buckets": {}}
    px, vw, sd = cx["px"], cx["vwap"], cx["sd"]
    if not sd:
        return None
    z = (px - vw) / sd
    side = "CE" if z <= -1.5 else "PE" if z >= 1.5 else None
    if side is None:
        return {"side": None, "stage": None, "chk": {"VWAP ±2σ band": False}, "notes": [f"VWAP-ல் இருந்து {z:.1f}σ"], "buckets": {}}
    ce = side == "CE"
    td = cx["today"]
    r_ = cx["rsi"]
    rsi_ok = r_ <= 30 if ce else r_ >= 70
    rng_edge = (px <= td["low"].min() + 0.3 * cx["atr"]) if ce else (px >= td["high"].max() - 0.3 * cx["atr"])
    exh = False
    if cx["has_vol"] and len(td) >= 4:
        v = td["fvol"].fillna(0).tail(3).values
        exh = v[2] < v[1] < v[0]
    last, prev = td.iloc[-1], td.iloc[-2]
    rev = (last["close"] > prev["high"]) if ce else (last["close"] < prev["low"])
    chk = {"VWAP ±2σ band": abs(z) >= 2, "RSI extreme": rsi_ok, "Range edge": rng_edge, "Volume exhaustion": exh,
           "Reversal candle": rev, "Sideways regime": reg == "SIDEWAYS"}
    stage = _stage(abs(z) >= 1.5, abs(z) >= 2 and rsi_ok, abs(z) >= 2 and (rsi_ok or rng_edge) and rev and reg == "SIDEWAYS")
    sl = (td["low"].tail(6).min() - 0.3 * cx["atr"]) if ce else (td["high"].tail(6).max() + 0.3 * cx["atr"])
    return {"side": side, "stage": stage, "chk": chk, "spot_sl": round(float(sl), 2), "target_hint": round(vw, 2),
            "buckets": {"trend": reg == "SIDEWAYS", "liquidity": rng_edge, "bos": rev, "volume": exh, "gamma": "POSITIVE" in str((cx.get('gex') or {}).get('zone', '')),
                        "vwap": abs(z) >= 2}, "notes": [f"VWAP {vw:.1f} · {z:+.1f}σ · RSI {r_:.0f}"]}


def score(res, opt_ok, S):
    W = S["weights"]
    b = res.get("buckets") or {}
    sc = sum(W[k] for k in ("trend", "liquidity", "bos", "volume", "gamma", "vwap") if b.get(k))
    if opt_ok:
        sc += W["option"]
    return int(sc)


# ───────────────────────── option selection ─────────────────────────
def pick_strike(ag, inst, idx, side, spot, now):
    """ATM / 1 ITM / 1 OTM → delta 0.35–0.65, spread ≤1.5%, OI + volume. Expiry live master-ல் இருந்து (இன்று expiry 14:30 பிறகு → அடுத்தது)."""
    from .instruments import contracts
    from .optmath import greeks_from_price
    t = pd.Timestamp(now)
    min_days = 1 if t.hour * 60 + t.minute >= 14 * 60 + 30 else 0
    exp, cs = contracts(inst, idx, min_days)
    if not cs:
        return None, "Contracts இல்லை"
    if exp < str(t.date()):
        return None, "Expired contract"
    strikes = sorted({c[3] for c in cs})
    atm = min(strikes, key=lambda s: abs(s - spot))
    i = strikes.index(atm)
    cand = [strikes[j] for j in range(max(0, i - 1), min(len(strikes), i + 2))]
    rows = [c for c in cs if c[3] in cand and c[4] == side]
    qs = ag.quotes({INDEX_OPT_EXCH[idx]: [c[0] for c in rows]})
    best, why = None, []
    for c in rows:
        q = qs.get(c[0]) or {}
        ltp = float(q.get("ltp") or 0)
        d = q.get("depth") or {}
        try:
            bid = float((d.get("buy") or [{}])[0].get("price") or 0)
            ask = float((d.get("sell") or [{}])[0].get("price") or 0)
        except Exception:
            bid = ask = 0
        if ltp <= 0:
            continue
        spread = (ask - bid) / ltp * 100 if bid and ask else 99
        try:
            gk = greeks_from_price(ltp, spot, c[3], exp, side, t.to_pydatetime())
        except Exception:
            gk = {}
        dl = abs((gk or {}).get("delta") or 0.5)
        oi, vol = float(q.get("opnInterest") or 0), float(q.get("tradeVolume") or 0)
        mny = "ATM" if c[3] == atm else ("ITM" if (c[3] < atm) == (side == "CE") else "OTM")
        sc = (30 if 0.35 <= dl <= 0.65 else 10) + (30 if spread <= 1.0 else 15 if spread <= 1.5 else 0) + min(20, oi / 1e5) + min(20, vol / 1e6)
        o = {"token": c[0], "contract": c[1], "expiry": exp, "strike": c[3], "type": side, "lot": c[5], "exch": c[6],
             "ltp": ltp, "bid": bid, "ask": ask, "spread_pct": round(spread, 2), "delta": round(dl, 2),
             "iv": (gk or {}).get("iv"), "gamma": (gk or {}).get("gamma"), "oi": int(oi), "volume": int(vol), "moneyness": mny, "_sc": sc}
        if spread > 1.5:
            why.append(f"{c[3]:g}: spread {spread:.1f}%")
            if spread <= 3 and (not best or (best.get("wide") and sc > best["_sc"])):
                best = dict(o, wide=True)      # fallback — limit order மட்டும்
            continue
        if not best or best.get("wide") or sc > best["_sc"]:
            best = o
    return best, ("; ".join(why) or "Liquid strike இல்லை")


def option_plan(o, spot, spot_sl, S):
    """Spot SL → premium SL (delta approx). R = clamp(structure risk, ₹1,500, ₹max_risk). T1/T2/T3 = 1R/2R/3R (RR 1:2 at T2)."""
    lot, e, dl = o["lot"], o["ltp"], max(0.2, o.get("delta") or 0.5)
    pts = abs(spot - spot_sl)
    risk_struct = pts * dl * lot
    R = min(max(risk_struct, S["min_t1_rs"]), S["max_risk"])
    sl = round(round((e - R / lot) / 0.05) * 0.05, 2)
    if sl <= 0.05 or sl >= e:
        return None, "SL premium தவறு (entry-க்கு கீழே இருக்கணும்)"
    risk = (e - sl) * lot
    tg = [round(round((e + k * risk / lot) / 0.05) * 0.05, 2) for k in (1, 2, 3)]
    rr = (tg[1] - e) / (e - sl)
    if not (sl < e < tg[0] < tg[1] < tg[2]) or rr < S["min_rr"] - 1e-6:
        return None, f"RR {rr:.2f} < {S['min_rr']}"
    warn = (f"Structure SL மிக தூரம் (₹{risk_struct:,.0f}/lot) — ₹{S['max_risk']:,.0f} cap SL noise-ல் அடிக்கலாம் (reference plan மட்டும்)"
            if risk_struct > S["max_risk"] * 1.6 else "")
    trig = round(round(e * (1 + S["premium_trigger_pct"] / 100) / 0.05) * 0.05, 2)
    return {"warn": warn, "entry": e, "trigger": trig, "zone": [trig, round(trig * 1.03, 2)], "sl": sl, "targets": tg, "risk": round(risk),
            "rr_t2": round(rr, 2), "t_rs": [round((t - e) * lot) for t in tg], "struct_risk": round(risk_struct)}, ""


# ───────────────────────── main scan ─────────────────────────
def scan(ag, inst, full, now, live=True):
    """ஒரு cycle: 4 index × 5 strategies. → STATE update + confirmed signals list."""
    S = settings()
    t = pd.Timestamp(now)
    mins = t.hour * 60 + t.minute
    mkt_open = t.weekday() < 5 and 9 * 60 + 15 <= mins < 15 * 60 + 30
    gex_by = {g.get("index"): g for g in (full or {}).get("gex") or []}
    chain_by = {x.get("index"): x for x in (full or {}).get("index") or []}
    out_idx, setups, signals, errors = {}, [], [], []
    STATE["tried"] = t.strftime("%H:%M:%S")
    for idx in INDEX_SPOT:
        if not S["indices"].get(idx, True):
            out_idx[idx] = {"status": "OFF"}
            continue
        STATE["prog"] = f"{idx} candles load…"
        try:
            fr = load_frames(ag, inst, idx, t)
            STATE["prog"] = f"{idx} strategies…"
            if not fr or fr["5M"].empty or len(fr["5M"]) < 30:
                out_idx[idx] = {"status": "NO DATA", "error": NODATA.get(idx, "Candles போதுமானதாக இல்லை")}
                continue
            age = (t.tz_localize(None) if t.tzinfo else t) - pd.Timestamp(fr["data_time"])
            stale = mkt_open and age > pd.Timedelta(minutes=S["stale_minutes"])
            cx = context(fr, gex_by.get(idx), chain_by.get(idx))
            reg = regime(cx)
            res = {}
            if S["strategies"].get("CQSMC"):
                res["CQSMC"] = s_cqsmc(cx)
            if S["strategies"].get("ORDERFLOW"):
                res["ORDERFLOW"] = s_orderflow(cx)
            if S["strategies"].get("GAMMA"):
                res["GAMMA"] = s_gamma(cx)
            if S["strategies"].get("SILVER"):
                res["SILVER"] = s_silver(cx, t, S)
            if S["strategies"].get("VWAPMR"):
                res["VWAPMR"] = s_vwapmr(cx, reg)
            pref = list(PREFERRED.get(reg, []))
            # V4.1 confluence: regime UNCLEAR / எதுவும் preferred இல்லைன்னா — CONFIRMED strategy + அதே side-ல் வேறு ஒரு strategy READY/CONFIRMED இருந்தா அது preferred
            conf_side = {}
            for k_, r_ in res.items():
                if r_ and r_.get("side") and r_.get("stage") in ("READY", "CONFIRMED"):
                    conf_side.setdefault(r_["side"], []).append(k_)
            for k_, r_ in res.items():
                if (r_ and r_.get("stage") == "CONFIRMED" and k_ not in pref and len(conf_side.get(r_["side"], [])) >= 2
                        and not (k_ == "VWAPMR" and reg != "SIDEWAYS")):
                    pref.append(k_)
                    r_["confluence"] = True
            strat_rows = []
            for k, r in res.items():
                if not r:
                    continue
                r = dict(r)
                r["strategy"], r["name"], r["preferred"] = k, SNAME[k], k in pref
                if r.get("confluence"):
                    r.setdefault("notes", []).insert(0, "🤝 Confluence: 2+ strategies ஒரே side")
                sup = [k2 for k2, r2 in res.items() if k2 != k and r2 and r2.get("side") == r.get("side") and r2.get("stage")]
                r["support"] = sup
                r["score"] = score(r, False, S) if r.get("side") else 0
                strat_rows.append(r)
                if r.get("side") and r.get("stage") and (S["early_detection"] or r["stage"] == "CONFIRMED"):
                    setups.append({"index": idx, "side": r["side"], "strategy": k, "name": SNAME[k], "stage": r["stage"],
                                   "score": r["score"], "preferred": r["preferred"], "support": sup, "regime": reg,
                                   "chk": r["chk"], "notes": [n for n in r.get("notes", []) if n], "spot": round(cx["px"], 2),
                                   "spot_sl": r.get("spot_sl"), "time": t.strftime("%H:%M"), "data_time": fr["data_time"], "stale": stale,
                                   "confluence": bool(r.get("confluence")), "missing": [a for a, b in r["chk"].items() if not b]})
            out_idx[idx] = {"status": "STALE" if stale else "SCANNING" if mkt_open else "MARKET CLOSED", "regime": reg,
                            "preferred": [SNAME[k] for k in pref] or ["WAIT"], "spot": round(cx["px"], 2), "vwap": round(cx["vwap"], 2),
                            "atr5": round(cx["atr"], 2), "htf": cx["htf"], "vol": "FUT volume" if cx["has_vol"] else "volume இல்லை (TWAP)",
                            "vol_ratio": cx["vol_ratio"], "pdh": cx["pdh"], "pdl": cx["pdl"], "data_time": fr["data_time"],
                            "strategies": [{k_: v for k_, v in r.items() if k_ not in ("profile",)} | ({"profile": r["profile"]} if r.get("profile") else {})
                                           for r in strat_rows],
                            "chart": [[str(i_), round(float(r_["open"]), 2), round(float(r_["high"]), 2), round(float(r_["low"]), 2), round(float(r_["close"]), 2)]
                                      for i_, r_ in cx["today"].tail(60).iterrows()]}
        except Exception as e:
            errors.append(f"{idx}: {e}")
            out_idx[idx] = {"status": "ERROR", "error": str(e)}
    # ── option selection + premium trigger (preferred strategy மட்டும் entry) ──
    best = {}
    for s_ in setups:
        k = f"{s_['index']}|{s_['side']}"
        rank = ({"CONFIRMED": 3, "READY": 2, "FORMING": 1}[s_["stage"]], s_["preferred"], s_["score"] + 3 * len(s_["support"]))
        if k not in best or rank > best[k]["_rank"]:
            best[k] = dict(s_, _rank=rank)
    final = []
    for k, s_ in best.items():
        s_.pop("_rank", None)
        s_["status"] = {"FORMING": "SETUP FORMING", "READY": "ENTRY READY", "CONFIRMED": "ENTRY READY"}[s_["stage"]]
        s_["block"] = []
        if mkt_open and live and not s_["stale"]:
            try:
                o, why = pick_strike(ag, inst, s_["index"], s_["side"], s_["spot"], t)
            except Exception as e:
                o, why = None, str(e)
            if o:
                p, why2 = option_plan(o, s_["spot"], s_["spot_sl"], S)
                s_["option"] = {k2: v for k2, v in o.items() if k2 != "_sc"}
                s_["score"] = min(100, s_["score"] + (S["weights"]["option"] if p else 0))
                if p:
                    s_["plan"] = p
                    if p.get("warn"):
                        s_["block"].append(p["warn"])
                    if o.get("wide"):
                        s_["block"].append(f"Spread {o['spread_pct']}% — limit order மட்டும்")
                else:
                    s_["block"].append(why2)
            else:
                s_["block"].append("Option: " + why)
        if not s_["preferred"]:
            s_["block"].append(f"Market {s_['regime']} — இந்த strategy-க்கு entry இல்லை (support மட்டும்)" if s_["regime"] != "UNCLEAR"
                               else "Market UNCLEAR — 2 strategies ஒரே side-ல் confirm ஆகணும் (confluence)")
        if s_["score"] < S["min_score"]:
            s_["block"].append(f"Score {s_['score']} < {S['min_score']:.0f}")
        if not mkt_open:
            s_["block"].append("Market closed — live signal இல்லை")
        if s_["stale"]:
            s_["block"].append("Data stale")
        # premium trigger (option-க்கு தனி confirmation)
        pk = f"{s_['index']}|{s_['side']}|{s_['strategy']}"
        pend = STATE["pending"]
        if s_.get("plan") and not s_["block"] and s_["stage"] == "CONFIRMED":
            pv = pend.get(pk)
            if not S["entry_confirmation"]:
                s_["status"] = "ENTRY CONFIRMED"
            elif pv and s_["option"]["contract"] == pv["contract"] and pv["trigger"] <= s_["option"]["ltp"] <= pv["trigger"] * 1.03:
                s_["status"] = "ENTRY CONFIRMED"
                s_["plan"]["trigger_hit"] = pv["trigger"]
            elif pv and s_["option"]["contract"] == pv["contract"] and s_["option"]["ltp"] > pv["trigger"] * 1.03:
                s_["status"] = "ENTRY READY"
                s_["block"].append(f"Premium buying zone-ஐ தாண்டியது (₹{pv['trigger']}–{pv['trigger'] * 1.03:.2f}) — chase வேண்டாம்")
            else:
                if not pv or pv["contract"] != s_["option"]["contract"]:
                    pend[pk] = {"trigger": s_["plan"]["trigger"], "contract": s_["option"]["contract"], "t": t.strftime("%H:%M")}
                s_["status"] = "WAIT FOR PREMIUM TRIGGER"
                s_["plan"]["trigger"] = pend[pk]["trigger"]
        elif pk in pend and s_["stage"] != "CONFIRMED":
            pend.pop(pk, None)
        cls = "HIGH" if s_["score"] >= S["min_score"] else "WATCH" if s_["score"] >= S["watch_score"] else "SKIP"
        s_["class"] = cls
        if s_["status"] == "ENTRY CONFIRMED":
            last = STATE["last_sig"].get(pk)
            if S["duplicate_filter"] and last and (t - pd.Timestamp(last)) < pd.Timedelta(minutes=S["dup_minutes"]):
                s_["status"] = "DUPLICATE (filtered)"
            else:
                STATE["last_sig"][pk] = str(t)
                signals.append(s_)
        final.append(s_)
    try:
        journal_update(ag, final, t, mkt_open, live)
    except Exception as e:
        errors.append(f"journal: {e}")
    order = {"ENTRY CONFIRMED": 0, "WAIT FOR PREMIUM TRIGGER": 1, "ENTRY READY": 2, "SETUP FORMING": 3, "DUPLICATE (filtered)": 4}
    final.sort(key=lambda x: (order.get(x["status"], 5), -x["score"]))
    with LOCK:
        STATE.update(prog="", t=t.strftime("%Y-%m-%d %H:%M:%S"), indices=clean(out_idx), setups=clean(final), errors=errors, market_open=mkt_open,
                     settings=S)
    return clean(signals)


def _jstore():
    from .store import STORE
    d = STORE.load()
    return STORE, d.setdefault("v4j", [])


def journal_update(ag, final, t, mkt_open, live):
    """📋 V4 கொடுத்த setups என்ன ஆச்சு — READY/CONFIRMED + plan + score ≥60 ஆன ஒவ்வொரு setup-ம் paper-ல் track.
    Trigger ₹ தாண்டினா entry · SL hit → exit · T1 → SL entry · T2 → SL T1 · T3 exit · 3:20 exit · 45 நிமிடத்தில் trigger ஆகலைன்னா NOT TRIGGERED."""
    if not live:
        return
    STORE, J = _jstore()
    day = str(t.date())
    mins = t.hour * 60 + t.minute
    changed = False
    if mkt_open:
        for s_ in final:
            p, o = s_.get("plan"), s_.get("option")
            if not (p and o) or s_["stage"] not in ("READY", "CONFIRMED") or s_["score"] < 60 or mins > 14 * 60 + 30:
                continue
            key = f"{day}|{s_['index']}|{s_['side']}|{s_['strategy']}"
            if any(j["key"] == key and j["status"] in ("WAITING", "OPEN", "T1 HIT", "T2 HIT") for j in J):
                continue
            last = [j for j in J if j["key"] == key]
            if last and (t - pd.Timestamp(last[-1]["t_full"])) < pd.Timedelta(minutes=30):
                continue
            J.append({"key": key, "id": f"{key}|{t.strftime('%H%M')}", "date": day, "time": t.strftime("%H:%M"), "t_full": str(t),
                      "index": s_["index"], "side": s_["side"], "strategy": s_["strategy"], "name": s_["name"], "stage": s_["stage"],
                      "score": s_["score"], "regime": s_["regime"], "contract": o["contract"], "token": o["token"], "exch": o["exch"],
                      "strike": o["strike"], "expiry": o["expiry"], "lot": o["lot"], "trigger": p["trigger"], "zone": p["zone"],
                      "sl": p["sl"], "sl0": p["sl"], "targets": p["targets"], "entry": None, "ltp": o["ltp"], "status": "WAITING",
                      "hits": [], "pnl": 0, "exit_time": None, "confirmed": s_["status"] == "ENTRY CONFIRMED"})
            changed = True
    # பழைய SL→entry trail-ஐ புது lock rule-க்கு மாற்று (open: SL உயர்த்து · closed TRAIL SL (T1) ≤0: lock-ல் exit என re-calc)
    from .calls import lock_price as _lp
    for j in J:
        if j["date"] != day or not j.get("entry") or len(j.get("hits") or []) != 1:
            continue
        lk = _lp(j["entry"], j["targets"][0], j["lot"])
        if j["status"] == "T1 HIT" and j["sl"] < lk:
            j["sl"] = lk; changed = True
        elif str(j["status"]).startswith("TRAIL SL") and (j.get("pnl") or 0) <= 0 and not j.get("recalc"):
            j.update(sl=lk, exit=lk, pnl=round((lk - j["entry"]) * j["lot"]), recalc=True); changed = True
    act = [j for j in J if j["date"] == day and j["status"] in ("WAITING", "OPEN", "T1 HIT", "T2 HIT")]
    if act:
        toks = {}
        for j in act:
            toks.setdefault(j["exch"], []).append(j["token"])
        q = ag.quotes(toks)
        for j in act:
            ltp = float((q.get(j["token"]) or {}).get("ltp") or 0)
            if not ltp:
                continue
            j["ltp"] = ltp
            if j["status"] == "WAITING":
                if j["trigger"] <= ltp <= j["zone"][1]:
                    j.update(status="OPEN", entry=ltp, entry_time=t.strftime("%H:%M"))
                    try:
                        j["call_id"] = journal_to_call(j, t)
                    except Exception as e:
                        STATE.setdefault("errors", []).append(f"journal→call: {e}")
                elif (t - pd.Timestamp(j["t_full"])) > pd.Timedelta(minutes=45) or mins >= 15 * 60 + 15:
                    j.update(status="NOT TRIGGERED", exit_time=t.strftime("%H:%M"))
                changed = True
                continue
            e = j["entry"]
            if ltp <= j["sl"]:
                j.update(status="SL HIT" if not j["hits"] else f"TRAIL SL (T{len(j['hits'])})",
                         exit=(j["sl"] if j["hits"] else ltp), exit_time=t.strftime("%H:%M"))
            else:
                from .calls import lock_price
                for i, tg_ in enumerate(j["targets"]):
                    if i >= len(j["hits"]) and ltp >= tg_:
                        j["hits"].append(t.strftime("%H:%M"))
                        j["sl"] = lock_price(e, j["targets"][0], j["lot"]) if i == 0 else j["targets"][i - 1]
                if len(j["hits"]) == 3:
                    j.update(status="T3 DONE", exit=ltp, exit_time=t.strftime("%H:%M"))
                elif j["hits"]:
                    j["status"] = f"T{len(j['hits'])} HIT"
                if mins >= 15 * 60 + 20 and j["status"] in ("OPEN", "T1 HIT", "T2 HIT"):
                    j.update(status="EOD EXIT", exit=ltp, exit_time=t.strftime("%H:%M"))
            j["pnl"] = round(((j.get("exit") or ltp) - e) * j["lot"])
            changed = True
    if len(J) > 600:
        del J[:len(J) - 600]
    if changed:
        STORE.dirty = True
        try:
            STORE.save()
        except Exception:
            pass
    STATE["journal"] = clean([{k: v for k, v in j.items() if k not in ("token",)} for j in J[-120:]])


def journal_to_call(j, t):
    """V4 setup premium trigger ஆனதும் → Calls tab-லும் call (kind V4). அதே contract open-ஆ இருந்தா skip."""
    from .calls import CALLS_LOCK, STORE, _new, OPEN
    day = str(t.date())
    with CALLS_LOCK:
        d = STORE.load()
        if any(x["date"] == day and x["contract"] == j["contract"] and x["status"] in OPEN for x in d["calls"].values()):
            return None
        tg_ = [x for x in j["targets"]]
        opt = {"token": j["token"], "exch": j["exch"], "contract": j["contract"], "strike": j["strike"], "type": j["side"],
               "expiry": j["expiry"], "lot": j["lot"],
               "plan": {"entry": j["entry"], "sl": j["sl0"], "targets": tg_, "risk": round((j["entry"] - j["sl0"]) * j["lot"]),
                        "risk_ok": True, "money": True, "reward_ok": True, "v4": True}}
        r = {"symbol": j["index"], "price": None, "sl": None, "targets": [], "stars": 4, "confidence": f"V4 score {j['score']}",
             "reasons": [f"{j['name']} · {j['regime']} · {j['stage']}", f"Premium trigger ₹{j['trigger']} தாண்டி entry ₹{j['entry']}"]}
        c = _new("V4", f"V4 {j['name']}", r, opt, t, day)
        if not c:
            return None
        c.update(grade="A" if j["score"] >= 85 else "B", qcodes=[], qtext=[],
                 v4={"strategy": j["strategy"], "regime": j["regime"], "score": j["score"], "from": "setup trigger"},
                 revisions=[{"t": t.strftime("%H:%M"), "sl": j["sl0"], "targets": tg_, "why": "setup trigger"}])
        d["calls"][c["id"]] = c
        STORE.dirty = True
        return c["id"]


def to_calls(signals, now):
    """ENTRY CONFIRMED → calls.py tracking (kind V4). Plan V4-ன் சொந்த SL/targets (₹ rules override இல்லை)."""
    if not signals:
        return 0
    from .calls import CALLS_LOCK, STORE, _new, tg
    n = 0
    t = pd.Timestamp(now)
    day = str(t.date())
    with CALLS_LOCK:
        d = STORE.load()
        for s_ in signals:
            o, p = s_["option"], s_["plan"]
            opt = {"token": o["token"], "exch": o["exch"], "contract": o["contract"], "strike": o["strike"], "type": s_["side"],
                   "expiry": o["expiry"], "lot": o["lot"], "spread_pct": o["spread_pct"],
                   "plan": {"entry": o["ltp"], "sl": p["sl"], "targets": p["targets"], "risk": p["risk"], "risk_ok": True,
                            "money": True, "reward_ok": True, "v4": True}}
            r = {"symbol": s_["index"], "price": s_["spot"], "sl": s_["spot_sl"], "targets": [], "stars": 5,
                 "confidence": f"V4 score {s_['score']}",
                 "reasons": [f"{s_['name']} · {s_['regime']}"] + [f"✓ {k}" for k, v in s_["chk"].items() if v] +
                            ([f"Support: {', '.join(SNAME[x] for x in s_['support'])}"] if s_["support"] else [])}
            c = _new("V4", f"V4 {s_['name']}", r, opt, t, day)
            if not c or c["id"] in d["calls"]:
                continue
            if any(x["date"] == day and x["contract"] == c["contract"] and x["kind"] == "V4" and x["status"] in ("OPEN", "T1 HIT", "T2 HIT")
                   for x in d["calls"].values()):
                continue
            c.update(grade="A" if s_["score"] >= 85 else "B", qcodes=[], qtext=[], v4={"strategy": s_["strategy"], "regime": s_["regime"],
                     "score": s_["score"], "data_time": s_["data_time"], "trigger": p.get("trigger_hit"), "spot_sl": s_["spot_sl"]},
                     sl0=p["sl"], revisions=[{"t": t.strftime("%H:%M"), "sl": p["sl"], "targets": p["targets"], "why": "signal"}])
            d["calls"][c["id"]] = c
            STORE.dirty = True
            n += 1
            if settings().get("telegram"):
                tg(f"🔥 V4 {s_['name']} · {s_['index']} {o['strike']:g} {s_['side']}\nEntry above ₹{p.get('trigger_hit') or o['ltp']} · SL ₹{p['sl']} · T {p['targets']}", f"v4|{c['id']}")
        if n:
            STORE.save(force=True)
    return n


# ───────────────────────── backtest (spot, walk-forward) ─────────────────────────
def backtest(ag, inst, days=20, cost_rs=120, slip_pts=1.0, progress=None):
    """Walk-forward: ஒவ்வொரு completed 5-min bar-லும் அதுவரையிலான data மட்டும் → strategy CONFIRMED ஆனா spot-ல் entry (அடுத்த bar open).
    SL = strategy spot SL · T1/T2/T3 = 1R/2R/3R. 1-min bars-ல் exit check; ஒரே bar-ல் SL & target இரண்டும் → AMBIGUOUS (guess இல்லை).
    ₹ ≈ points × delta 0.5 × lot − cost (option premium history இல்லாததால் approximate). Old Gamma V3 historical option chain இல்லை → forward paper compare."""
    S = settings()
    end = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).floor("min")
    out = {"rows": [], "by": {}, "note": "", "days": days}
    lots = {}
    for idx in INDEX_SPOT:
        from .instruments import contracts
        _, cs = contracts(inst, idx, 0)
        lots[idx] = cs[0][5] if cs else 0
    for idx in INDEX_SPOT:
        if not S["indices"].get(idx, True):
            continue
        ex, tok = INDEX_SPOT[idx]
        start = (end - pd.Timedelta(days=int(days * 1.5) + 2)).normalize() + pd.Timedelta(hours=9, minutes=15)
        m1 = ag.candles(ex, tok, "ONE_MINUTE", start, end)
        if m1 is None or m1.empty:
            continue
        m1 = m1.between_time("09:15", "15:29")
        fut = fut_token(inst, idx)
        fv = None
        if fut:
            f5 = ag.candles(fut[0], fut[1], "FIVE_MINUTE", start, end)
            if f5 is not None and not f5.empty:
                fv = f5["volume"]
        dates = sorted(set(m1.index.date))
        open_tr = None
        for di, dday in enumerate(dates[3:], 3):
            if progress:
                progress(f"Backtest {idx} {dday}")
            day_bars = m1[m1.index.date == dday]
            for ts in pd.date_range(pd.Timestamp(dday) + pd.Timedelta(hours=9, minutes=45), pd.Timestamp(dday) + pd.Timedelta(hours=14, minutes=30), freq="5min"):
                if open_tr:
                    break
                hist = m1[(m1.index < ts) & (m1.index.date >= dates[max(0, di - 5)])]
                if len(hist) < 200:
                    continue
                fr = {"1M": hist, "3M": _resample(hist, "3min"), "5M": _resample(hist, "5min"), "15M": _resample(hist, "15min"), "1H": _resample(hist, "60min")}
                if fv is not None:
                    fr["5M"] = fr["5M"].join(fv.rename("fvol"), how="left")
                fr["has_vol"] = fv is not None
                try:
                    cx = context(fr)
                    reg = regime(cx)
                    cands = {"CQSMC": s_cqsmc(cx), "ORDERFLOW": s_orderflow(cx), "SILVER": s_silver(cx, ts, S), "VWAPMR": s_vwapmr(cx, reg)}
                except Exception:
                    continue
                for k, r in cands.items():
                    if not S["strategies"].get(k) or not r or r.get("stage") != "CONFIRMED" or not r.get("side"):
                        continue
                    if k not in PREFERRED.get(reg, []):
                        continue
                    sc = score(r, True, S)
                    if sc < S["min_score"]:
                        continue
                    nxt = m1[m1.index >= ts]
                    if nxt.empty:
                        continue
                    ce = r["side"] == "CE"
                    e = float(nxt["open"].iloc[0]) + (slip_pts if ce else -slip_pts)
                    sl = r["spot_sl"]
                    R = (e - sl) if ce else (sl - e)
                    if R <= 0:
                        continue
                    tgs = [e + k_ * R if ce else e - k_ * R for k_ in (1, 2, 3)]
                    open_tr = {"index": idx, "strategy": k, "regime": reg, "side": r["side"], "time": str(ts), "entry": round(e, 2),
                               "sl": round(sl, 2), "R": round(R, 2), "tg": [round(x, 2) for x in tgs], "score": sc}
                    break
            if open_tr:
                cur_sl, hit, res = open_tr["sl"], 0, None
                for t1, b in day_bars[day_bars.index >= pd.Timestamp(open_tr["time"])].iterrows():
                    ce = open_tr["side"] == "CE"
                    sl_touch = (b["low"] <= cur_sl) if ce else (b["high"] >= cur_sl)
                    nxt_t = open_tr["tg"][hit] if hit < 3 else None
                    tg_touch = nxt_t is not None and ((b["high"] >= nxt_t) if ce else (b["low"] <= nxt_t))
                    if sl_touch and tg_touch:
                        res = ("AMBIGUOUS", 0)
                        break
                    if sl_touch:
                        pts = (cur_sl - open_tr["entry"]) if ce else (open_tr["entry"] - cur_sl)
                        res = ("SL" if hit == 0 else f"TRAIL after T{hit}", pts)
                        break
                    if tg_touch:
                        hit += 1
                        cur_sl = open_tr["entry"] if hit == 1 else open_tr["tg"][hit - 2]
                        if hit == 3:
                            res = ("T3", 3 * open_tr["R"])
                            break
                    if t1.hour * 60 + t1.minute >= 15 * 60 + 20:
                        pts = (b["close"] - open_tr["entry"]) if ce else (open_tr["entry"] - b["close"])
                        res = ("EOD", pts)
                        break
                if res:
                    lot = lots.get(idx) or 0
                    rs = res[1] * 0.5 * lot - (cost_rs if res[0] != "AMBIGUOUS" else 0)
                    out["rows"].append(dict(open_tr, result=res[0], pts=round(res[1], 2), r_mult=round(res[1] / open_tr["R"], 2), rs=round(rs)))
                open_tr = None
    def stat(rows):
        rr = [r for r in rows if r["result"] != "AMBIGUOUS"]
        w = [r for r in rr if r["rs"] > 0]
        l_ = [r for r in rr if r["rs"] <= 0]
        eq, peak, dd = 0, 0, 0
        for r in rr:
            eq += r["rs"]
            peak = max(peak, eq)
            dd = min(dd, eq - peak)
        gw, gl = sum(r["rs"] for r in w), -sum(r["rs"] for r in l_)
        return {"signals": len(rows), "trades": len(rr), "ambiguous": len(rows) - len(rr), "win_rate": round(len(w) / len(rr) * 100) if rr else None,
                "avg_win": round(gw / len(w)) if w else 0, "avg_loss": round(-gl / len(l_)) if l_ else 0,
                "pf": round(gw / gl, 2) if gl else None, "max_dd": round(dd), "expectancy": round(sum(r["rs"] for r in rr) / len(rr)) if rr else 0,
                "net": round(sum(r["rs"] for r in rr))}
    rows = out["rows"]
    out["by"] = {"ALL": stat(rows),
                 **{f"Strategy · {SNAME[k]}": stat([r for r in rows if r["strategy"] == k]) for k in STRATS if k != "GAMMA"},
                 **{f"Index · {i}": stat([r for r in rows if r["index"] == i]) for i in INDEX_SPOT},
                 **{f"Regime · {g}": stat([r for r in rows if r["regime"] == g]) for g in sorted({r["regime"] for r in rows})}}
    out["note"] = (f"Spot walk-forward {days} நாள் · entry = அடுத்த bar open + {slip_pts} pt slippage · ₹ ≈ pts × 0.5 delta × lot − ₹{cost_rs} cost · "
                   "Gamma Squeeze backtest இல்லை (historical option chain / GEX இல்லை) · ஒரே 1-min bar-ல் SL & target = AMBIGUOUS (count மட்டும்).")
    out["t"] = str(end)
    return clean(out)
