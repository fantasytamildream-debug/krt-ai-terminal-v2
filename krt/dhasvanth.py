"""🏹 DHASVANTH — the 5 money-making strategies, upgraded to a "9.5 / 10" checklist.

Strategies: Gamma Unwind Classic · V4 ICT Silver Bullet · Index OI · Order Flow + Profile · 5-min ORB.
Every call these 5 produce is checked ONCE, at signal time, against the extra rules below and the result is frozen
(so the grade can never be changed after the outcome is known). Nothing is blocked anywhere else in the terminal —
the no-limits rule stays — Dhasvanth only grades, ranks, sizes and guides.

Grade:  9.5 PRO  = every known rule passes (and ≥70% of the rules had data)
        TAKE     = rating ≥ 7 and no critical rule failed
        CAUTION  = rating < 7, no critical fail
        SKIP     = a critical rule failed (the call is still shown and tracked — so we can prove whether skipping helps)
A rule with no data scores nothing and is shown as "no data" — never guessed.
Results: every call is tracked by the normal call engine; here they are split by grade, market, trend / range day and
week (R-multiple + expectancy), so the filter itself is measured.
"""
import datetime as dt
import math

import numpy as np
import pandas as pd

IDX = ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY")
OPEN = ("OPEN", "T1 HIT", "T2 HIT")
CFG = {"risk_cap": 2500, "charges": 150, "sb_wins": [("10:00", "11:00"), ("13:30", "14:30")], "sb_first_min": 25,
       "orb_cut": "11:45", "orb_min": 0.35, "orb_max": 1.5, "rvol": 1.5, "gu_prem_sl": 0.40, "mp_dist": 0.8,
       "pcr_hi": 1.5, "pcr_lo": 0.65, "max_attempts": 2, "keep_days": 45}

STRATS = [
    {"key": "GU", "name": "Gamma Unwind Classic", "icon": "🎯", "markets": ["Stock"],
     "how": "Option writers cover after a stock breaks its zone → OI falls, premium jumps. Targets +25/50/75/100%.",
     "rules": ["Wall / gamma-flip context", "Volume expanding + OI falling on the unwound side", "IV not already stretched (≤1.5× 20-day HV)",
               "Spot ≥0.8% from max pain in trade direction", "Expiry day: no entry after 2:00 PM (exit by 2:45)",
               "Risk ≤ ₹2,500/lot and premium SL ≤ 40%"]},
    {"key": "SB", "name": "V4 ICT Silver Bullet", "icon": "⚡", "markets": ["Index", "Commodity"],
     "how": "Stop hunt beyond a key high/low → structure shift → displacement → FVG retest, inside the Silver Bullet window.",
     "rules": ["HTF bias: 15m or 1H agrees (opposite = skip)", "Displacement body ≥1.5× average and close beyond the last swing",
               "Only the FIRST FVG after displacement; entry near its 50%", "First 25 min of the window only",
               "Open range (India / London / NY) broken in trade direction", "Previous 2 Silver Bullets same direction not both failed"]},
    {"key": "IOI", "name": "Index OI", "icon": "📊", "markets": ["Index"],
     "how": "Trade the side option writers lean to: PCR + biggest PE (support) / CE (resistance) walls.",
     "rules": ["OI change in last 15–30 min supports the side", "Wall shifted in trade direction", "Market breadth (advance / decline) agrees",
               "VWAP side + previous-day high/low break", "PCR extreme only with price confirmation", "5-min and 15-min OI change agree"]},
    {"key": "OF", "name": "Order Flow + Profile", "icon": "🥈", "markets": ["Commodity", "Index"],
     "how": "Price accepted outside yesterday-today value area with volume and buying/selling pressure. SL at POC.",
     "rules": ["Real aggressor delta (not available → half size)", "Closed outside VAH/VAL and held the retest 2 candles",
               "No delta divergence", "Trend / neutral day (range day = skip)", "No major data release ±30 min (EIA, NFP…)",
               "Results tracked per commodity (Gold / Crude separate)"]},
    {"key": "ORB", "name": "5-min ORB", "icon": "⏱", "markets": ["Stock"],
     "how": "Break of the first 5-minute range with volume. SL other side, targets 1×/2×/3× range.",
     "rules": ["Range size 0.35%–1.5%", "Relative volume ≥1.5× for this time of day", "Retest entry (price near the breakout level, not chased)",
               "VWAP / open side + sector + index agree", "Only the first breakout per stock per day", "Next level ≥2R away after costs",
               "No ORB entry after 11:45"]},
]
SKEY = {s["key"]: s for s in STRATS}
STATE = {"time": None, "err": None}
HIST = {}            # index → [(ts, ce_oi, pe_oi, support, resistance, spot)]
CHAINS = {}          # stock|expiry|minute → chain rows


def strat_of(c):
    src, kind = str(c.get("source") or ""), c.get("kind")
    if kind == "GU-CLASSIC":
        return "GU"
    if "Silver Bullet" in src:
        return "SB"
    if src == "Index OI":
        return "IOI"
    if "Order Flow + Profile" in src:
        return "OF"
    if src == "5-min ORB":
        return "ORB"
    return None


def market_of(c):
    if c.get("exch") == "MCX":
        return "Commodity"
    return "Index" if c.get("symbol") in IDX else "Stock"


def _f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def _hm(c):
    return str(c.get("time") or "00:00")[:5]


def _sig_ts(c):
    try:
        return pd.Timestamp(c.get("signal_time") or f"{c['date']} {_hm(c)}")
    except Exception:
        return None


def R(name, ok, why, crit=False):
    return {"name": name, "ok": ok, "why": why, "crit": crit}


# ───────────────────────── frames helpers (index + commodity, from the V4 / commodity caches — no extra API calls) ─────────────────────────
def frames_for(c):
    try:
        if c.get("exch") == "MCX":
            from .commodity import FR
        else:
            from .v4 import FR
        x = FR.get(c.get("symbol"))
        return x[1] if x else None
    except Exception:
        return None


def _cut(df, ts):
    if df is None or ts is None or getattr(df, "empty", True):
        return df
    return df[df.index <= ts]


def _swings(df, n=2):
    hi, lo = [], []
    h, l = df["high"].values, df["low"].values
    for i in range(n, len(df) - n):
        if h[i] == max(h[i - n:i + n + 1]):
            hi.append((i, h[i]))
        if l[i] == min(l[i - n:i + n + 1]):
            lo.append((i, l[i]))
    return hi, lo


def htf_bias(fr, ts):
    from . import v4 as V
    out = {}
    try:
        m15 = _cut(fr["15M"], ts).tail(80)
        out["15m"] = V.structure(m15).get("trend") if len(m15) > 10 else None
    except Exception:
        out["15m"] = None
    try:
        h1 = _cut(fr["1H"], ts)["close"]
        e20, e50 = V.ema(h1, 20).iloc[-1], V.ema(h1, 50).iloc[-1]
        out["1H"] = "UP" if h1.iloc[-1] > e20 > e50 else "DOWN" if h1.iloc[-1] < e20 < e50 else "FLAT"
    except Exception:
        out["1H"] = None
    return out


def displacement_check(m3, ce):
    """Strongest candle in trade direction in the last 10 bars: body vs 20-bar average body, and close beyond the previous swing."""
    if m3 is None or len(m3) < 25:
        return None, "not enough 3-min candles", None
    body = (m3["close"] - m3["open"]).abs()
    avg = float(body.iloc[-30:-10].mean() or 0)
    last = m3.tail(10)
    best, bi = None, None
    for i in range(len(m3) - 10, len(m3)):
        r = m3.iloc[i]
        if (r["close"] > r["open"]) == ce and (best is None or abs(r["close"] - r["open"]) > best):
            best, bi = abs(r["close"] - r["open"]), i
    if best is None or not avg:
        return False, "no candle in trade direction", None
    ratio = best / avg
    hi, lo = _swings(m3.iloc[:bi])
    sw = (hi[-1][1] if hi else None) if ce else (lo[-1][1] if lo else None)
    if sw is None and bi >= 5:                                   # no clean pivot → the recent 20-bar extreme before the candle
        prev = m3.iloc[max(0, bi - 20):bi]
        sw = float(prev["high"].max()) if ce else float(prev["low"].min())
    cl = float(m3["close"].iloc[bi])
    beyond = sw is not None and (cl > sw if ce else cl < sw)
    ok = ratio >= 1.5 and beyond
    _ = last
    return ok, f"body {ratio:.1f}× avg · close {cl:g} {'beyond' if beyond else 'not beyond'} swing {sw if sw is None else round(sw, 2)}", bi


def fvg_check(m3, ce, bi, px):
    if m3 is None or bi is None:
        return None, "no displacement candle", None
    sub = m3.iloc[max(0, bi - 1):]
    gaps = []
    for i in range(2, len(sub)):
        a, c_ = sub.iloc[i - 2], sub.iloc[i]
        if ce and c_["low"] > a["high"]:
            gaps.append((float(a["high"]), float(c_["low"])))
        if not ce and c_["high"] < a["low"]:
            gaps.append((float(c_["high"]), float(a["low"])))
    if not gaps:
        return False, "no FVG after displacement", None
    lo, hi = gaps[0]
    mid = round((lo + hi) / 2, 2)
    first = len(gaps) == 1
    near = px is not None and abs(px - mid) <= max(hi - lo, 1e-9) * 1.5
    ok = first and near
    return ok, (f"{len(gaps)} FVG{'s' if len(gaps) > 1 else ''} after displacement ({'first only ✓' if first else 'multiple — skip'}) · "
                f"50% = {mid}" + ("" if px is None else f" · price {round(px, 2)} {'near it' if near else 'chased away from it'}")), mid


def open_ranges(c, ts):
    """Open ranges before the signal: India open (NSE 9:15 / MCX 9:00), London 08:00 and New York 09:30 local, converted to IST (DST aware)."""
    from zoneinfo import ZoneInfo
    day = ts.date()
    ist = ZoneInfo("Asia/Kolkata")
    out = [("India open", pd.Timestamp(f"{day} {'09:00' if c.get('exch') == 'MCX' else '09:15'}"))]
    for nm, tz, hm in (("London open", "Europe/London", (8, 0)), ("New York open", "America/New_York", (9, 30))):
        t = dt.datetime(day.year, day.month, day.day, hm[0], hm[1], tzinfo=ZoneInfo(tz)).astimezone(ist).replace(tzinfo=None)
        out.append((nm, pd.Timestamp(t)))
    return [(n, t) for n, t in out if t + pd.Timedelta(minutes=15) <= ts]


def or_check(c, fr, ts, ce):
    try:
        m1 = _cut(fr["1M"], ts)
    except Exception:
        return None, "no 1-min data"
    rs = open_ranges(c, ts)
    if not rs or m1 is None or m1.empty:
        return None, "no open range finished yet"
    nm, t0 = rs[-1]
    w = m1[(m1.index >= t0) & (m1.index < t0 + pd.Timedelta(minutes=15))]
    if w.empty:
        return None, f"{nm} range: no candles (market closed then)"
    hi, lo, px = float(w["high"].max()), float(w["low"].min()), float(m1["close"].iloc[-1])
    ok = px > hi if ce else px < lo
    return ok, f"{nm} 15-min range {round(lo, 2)}–{round(hi, 2)} · price {round(px, 2)} {'broke it in trade direction' if ok else 'not broken in trade direction'}"


def delta_proxy(df):
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    vol = df["fvol"] if "fvol" in df else df.get("volume")
    if vol is None:
        return None
    return ((df["close"] - df["open"]) / rng * vol.fillna(0)).fillna(0)


# ───────────────────────── per-strategy rules ─────────────────────────
def rules_sb(c, ctx, ts):
    ce = c["side"] == "CE"
    fr = frames_for(c)
    out = []
    if not fr:
        b = None
        out.append(R("HTF bias (15m / 1H)", None, "no candle cache for this symbol yet", True))
    else:
        b = htf_bias(fr, ts)
        want = "UP" if ce else "DOWN"
        opp = "DOWN" if ce else "UP"
        if b.get("15m") is None and b.get("1H") is None:
            out.append(R("HTF bias (15m / 1H)", None, "not enough history", True))
        else:
            ok = want in (b.get("15m"), b.get("1H")) and opp not in (b.get("15m"), b.get("1H"))
            out.append(R("HTF bias (15m / 1H)", ok, f"15m {b.get('15m')} · 1H {b.get('1H')} · trade {want}", True))
    m3 = _cut(fr["3M"], ts) if fr else None
    d_ok, d_why, bi = displacement_check(m3, ce) if fr else (None, "no candles", None)
    out.append(R("Displacement ≥1.5× + close beyond swing", d_ok, d_why, True))
    px = float(m3["close"].iloc[-1]) if m3 is not None and len(m3) else _f(c.get("ul_price"))
    f_ok, f_why, mid = fvg_check(m3, ce, bi, px) if fr else (None, "no candles", None)
    out.append(R("First FVG only · entry near 50%", f_ok, f_why))
    hm = _hm(c)
    win = next(((a, b_) for a, b_ in CFG["sb_wins"] if a <= hm <= b_), None)
    if win:
        a = pd.Timestamp(f"2000-01-01 {win[0]}")
        late = (pd.Timestamp(f"2000-01-01 {hm}") - a).total_seconds() / 60
        out.append(R("First 25 min of the window", late <= CFG["sb_first_min"], f"signal {hm} = {int(late)} min into {win[0]}–{win[1]}", True))
    else:
        out.append(R("First 25 min of the window", False, f"signal {hm} is outside the Silver Bullet windows", True))
    o_ok, o_why = or_check(c, fr, ts, ce) if fr else (None, "no candles")
    out.append(R("Open range broken in trade direction", o_ok, o_why))
    prev = [x for x in ctx["calls"] if strat_of(x) == "SB" and x["side"] == c["side"] and x["id"] != c["id"]
            and str(x.get("signal_time") or "") < str(c.get("signal_time") or "") and x.get("status") not in OPEN and x.get("status") != "VOID"]
    prev.sort(key=lambda x: str(x.get("signal_time") or ""))
    last2 = prev[-2:]
    if len(last2) < 2:
        out.append(R("Last 2 same-direction Silver Bullets not both failed", True, f"only {len(last2)} earlier closed {c['side']} Silver Bullet(s)"))
    else:
        both = all((x.get("pnl_lot") or 0) <= 0 for x in last2)
        out.append(R("Last 2 same-direction Silver Bullets not both failed", not both,
                     " · ".join(f"{x['date']} {x['symbol']} {'loss' if (x.get('pnl_lot') or 0) <= 0 else 'win'}" for x in last2), True))
    return out, {"fvg_mid": mid, "htf": b}


def stock_chain(ag, inst, sym, expiry, now):
    """Option chain for one stock (one quote call, ~25 strikes) — only for Gamma Unwind calls. Fetched OUTSIDE the calls lock
    (ag given); inside the lock ag=None and only the fresh (≤5 min) cache is used."""
    key = f"{sym}|{expiry}"
    hit = CHAINS.get(key)
    if hit and abs((now - hit[0]).total_seconds()) <= 300:
        return hit[1], hit[2]
    if not ag or not inst:
        return None, None
    from .instruments import contracts
    from .fullscan import C as FSC
    exp, rows = contracts(inst, sym, 0)
    rows = [r for r in rows if str(r[2]) == str(expiry)] or rows
    spot = _f(((FSC.get("live_q") or {}).get(sym) or {}).get("ltp"))
    if not rows or not spot:
        return None, spot
    ks = sorted({float(r[3]) for r in rows})
    atm = min(ks, key=lambda k: abs(k - spot))
    i = ks.index(atm)
    win = set(ks[max(0, i - 12): i + 13])
    sel = [r for r in rows if float(r[3]) in win]
    q = ag.quotes({sel[0][6] if len(sel[0]) > 6 else "NFO": [r[0] for r in sel]}) or {}
    ch = {}
    for r in sel:
        qq = q.get(r[0]) or {}
        d = qq.get("depth") or {}
        bid = _f(((d.get("buy") or [{}])[0] or {}).get("price"))
        ask = _f(((d.get("sell") or [{}])[0] or {}).get("price"))
        ch.setdefault(float(r[3]), {"strike": float(r[3])})[r[4]] = {"oi": _f(qq.get("opnInterest")) or 0, "ltp": _f(qq.get("ltp")), "bid": bid, "ask": ask}
    out = [ch[k] for k in sorted(ch)]
    if len(CHAINS) > 60:
        CHAINS.clear()
    CHAINS[key] = (now, out, spot)
    return out, spot


def prefetch(calls, G, now, ag, inst):
    """Before taking the calls lock: fetch stock chains for today's ungraded Gamma Unwind calls (max 3 per run)."""
    day = str(now.date())
    n = 0
    for c in calls:
        if n >= 3 or c.get("date") != day or strat_of(c) != "GU" or c["id"] in G:
            continue
        try:
            stock_chain(ag, inst, c["symbol"], c.get("expiry"), now)
        except Exception:
            pass
        n += 1


def max_pain(rows):
    ks = [r["strike"] for r in rows]
    if not ks:
        return None
    best, bp = None, None
    for P in ks:
        pay = sum((r.get("CE") or {}).get("oi", 0) * max(0, P - r["strike"]) + (r.get("PE") or {}).get("oi", 0) * max(0, r["strike"] - P) for r in rows)
        if best is None or pay < best:
            best, bp = pay, P
    return bp


def hv20(cl):
    if not cl or len(cl) < 22:
        return None
    r = np.diff(np.log(np.array(cl[-21:], dtype=float)))
    return float(np.std(r, ddof=1) * math.sqrt(252))


def rules_gu(c, ctx, ts, ag=None, inst=None):
    ce = c["side"] == "CE"
    out = []
    rows, spot = (None, None)
    try:
        rows, spot = stock_chain(ag, inst, c["symbol"], c.get("expiry"), ts)
    except Exception:
        rows = None
    spot = spot or _f(((ctx.get("live_q") or {}).get(c["symbol"]) or {}).get("ltp"))
    if rows:
        cw = max(rows, key=lambda r: (r.get("CE") or {}).get("oi", 0))["strike"]
        pw = max(rows, key=lambda r: (r.get("PE") or {}).get("oi", 0))["strike"]
        flip = None
        try:
            from .v3 import gex_index
            g = gex_index({"index": c["symbol"], "spot": spot, "expiry": c.get("expiry"), "chain": rows}, ts)
            flip = g.get("flip")
        except Exception:
            pass
        wall = cw if ce else pw
        broke = spot > wall if ce else spot < wall
        dist = abs(wall - spot) / spot * 100
        fok = None if not flip else (spot > flip if ce else spot < flip)
        ok = (broke or dist >= 1.0) and fok is not False
        out.append(R("Wall / gamma-flip context", ok, f"{'CE' if ce else 'PE'} wall {wall:g} ({'broken' if broke else f'{dist:.1f}% away'})"
                     + (f" · gamma flip ≈{flip:g} ({'right side' if fok else 'wrong side'})" if flip else " · gamma flip not estimable")))
        mp = max_pain(rows)
        d = (spot - mp) / mp * 100 if mp else None
        mok = None if d is None else (d >= CFG["mp_dist"] if ce else -d >= CFG["mp_dist"])
        out.append(R("Spot ≥0.8% from max pain (trade side)", mok, f"max pain {mp:g} · spot {spot:g} ({d:+.2f}%)" if d is not None else "no max pain"))
    else:
        out.append(R("Wall / gamma-flip context", None, "stock option chain not available right now"))
        out.append(R("Spot ≥0.8% from max pain (trade side)", None, "stock option chain not available right now"))
    lq = (ctx.get("live_q") or {}).get(c["symbol"]) or {}
    vr = _f(c.get("vol_ratio")) or _f(lq.get("vol_ratio"))
    drop = (c.get("gu") or {}).get("drop")
    if vr is None and drop is None:
        out.append(R("Volume expanding + OI falling", None, "no volume / OI data", True))
    else:
        ok = (vr or 0) >= 1.5 and (drop or 0) >= 4
        out.append(R("Volume expanding + OI falling", ok, f"stock volume {vr or 0}× · option OI −{drop or 0}% from peak", True))
    bars = (ctx.get("bars") or {}).get(c["symbol"]) or {}
    hv = hv20(bars.get("c") or [])
    iv = None
    try:
        from .optmath import greeks_from_price
        if spot and c.get("entry"):
            iv = greeks_from_price(float(c["entry"]), spot, float(c["strike"]), c["expiry"], c["side"], ts.to_pydatetime())[0]
    except Exception:
        iv = None
    if iv and hv:
        out.append(R("IV not stretched (≤1.5× HV20)", iv <= 1.5 * hv, f"IV {iv * 100:.0f}% vs 20-day HV {hv * 100:.0f}% ({iv / hv:.1f}×)"))
    else:
        out.append(R("IV not stretched (≤1.5× HV20)", None, "IV / HV not computable"))
    exp_day = str(c.get("expiry")) == str(ts.date())
    out.append(R("Expiry-day 2:00 PM cutoff", not (exp_day and _hm(c) > "14:00"),
                 "expiry today — exit by 2:45 PM" if exp_day else "not expiry day", True))
    e, sl, lot = _f(c.get("entry")), _f(c.get("sl0") or c.get("sl")), _f(c.get("lot"))
    if e and sl and lot:
        risk, pct = (e - sl) * lot, (e - sl) / e
        out.append(R("Risk ≤ ₹2,500/lot · premium SL ≤40%", risk <= CFG["risk_cap"] and pct <= CFG["gu_prem_sl"] + 1e-9,
                     f"risk ₹{risk:,.0f}/lot · SL {pct * 100:.0f}% of premium", True))
    else:
        out.append(R("Risk ≤ ₹2,500/lot · premium SL ≤40%", None, "plan incomplete", True))
    return out, {}


def oi_sample(full, now):
    for x in (full or {}).get("index") or []:
        ch = x.get("chain") or []
        if not ch or not x.get("index"):
            continue
        ce = sum((r.get("CE") or {}).get("oi", 0) for r in ch)
        pe = sum((r.get("PE") or {}).get("oi", 0) for r in ch)
        L = HIST.setdefault(x["index"], [])
        if L and L[-1][1] == ce and L[-1][2] == pe:
            continue
        L.append((now, ce, pe, x.get("support"), x.get("resistance"), x.get("spot")))
        while L and (now - L[0][0]).total_seconds() > 3 * 3600:
            L.pop(0)


def _ago(L, ts, mins):
    c = [r for r in L if r[0] <= ts - pd.Timedelta(minutes=mins)]
    return c[-1] if c else None


def rules_ioi(c, ctx, ts):
    ce = c["side"] == "CE"
    out = []
    L = [r for r in HIST.get(c["symbol"], []) if r[0] <= ts + pd.Timedelta(minutes=1)]
    now_ = L[-1] if L else None

    def net(a, b):
        if not a or not b or not a[1] or not a[2]:
            return None
        return (b[2] / a[2] - 1) * 100 - (b[1] / a[1] - 1) * 100       # PE OI growth % minus CE OI growth %
    b30 = _ago(L, ts, 15) and (_ago(L, ts, 30) or _ago(L, ts, 15))
    n30 = net(b30, now_)
    if n30 is None:
        out.append(R("OI change last 15–30 min supports side", None, "OI history still building (needs 15+ min of samples)", True))
    else:
        out.append(R("OI change last 15–30 min supports side", n30 > 0.5 if ce else n30 < -0.5,
                     f"PE OI growth minus CE OI growth = {n30:+.1f} pts ({'puts' if n30 > 0 else 'calls'} being written faster)", True))
    if b30 and now_ and b30[3] is not None and now_[3] is not None:
        if ce:
            ok = now_[3] > b30[3] or (now_[4] or 0) > (b30[4] or 0)
            out.append(R("Wall shifted in trade direction", ok, f"support {b30[3]}→{now_[3]} · resistance {b30[4]}→{now_[4]}"))
        else:
            ok = (now_[4] or 0) < (b30[4] or 0) or (now_[3] or 1e12) < (b30[3] or 1e12)
            out.append(R("Wall shifted in trade direction", ok, f"resistance {b30[4]}→{now_[4]} · support {b30[3]}→{now_[3]}"))
    else:
        out.append(R("Wall shifted in trade direction", None, "wall history still building"))
    lq = ctx.get("live_q") or {}
    up = sum(1 for q in lq.values() if (q.get("pct") or 0) > 0)
    dn = sum(1 for q in lq.values() if (q.get("pct") or 0) < 0)
    if up + dn < 20:
        out.append(R("Breadth (advance / decline) agrees", None, "breadth data not loaded"))
    else:
        ad = up / max(dn, 1)
        out.append(R("Breadth (advance / decline) agrees", ad >= 1.2 if ce else ad <= 0.83, f"{up} up / {dn} down (A/D {ad:.2f})"))
    fr = frames_for(c)
    if fr:
        try:
            from . import v4 as V
            m5 = _cut(fr["5M"], ts)
            days = sorted(set(m5.index.date))
            td = m5[m5.index.date == days[-1]]
            prev = m5[m5.index.date == days[-2]] if len(days) > 1 else None
            vw = float(V.session_vwap(td)[0].iloc[-1])
            px = float(td["close"].iloc[-1])
            pdh, pdl = (float(prev["high"].max()), float(prev["low"].min())) if prev is not None and len(prev) else (None, None)
            vok = px > vw if ce else px < vw
            lvl = pdh if ce else pdl
            lok = None if lvl is None else (px > lvl if ce else px < lvl)
            out.append(R("VWAP side + prev-day high/low break", bool(vok and lok) if lok is not None else vok,
                         f"price {px:g} vs VWAP {vw:.1f} ({'ok' if vok else 'wrong side'})" + (f" · {'PDH' if ce else 'PDL'} {lvl:g} {'broken' if lok else 'not broken'}" if lvl else "")))
            b = htf_bias(fr, ts)
        except Exception as e:
            out.append(R("VWAP side + prev-day high/low break", None, f"calc error {str(e)[:40]}"))
            b = {}
    else:
        out.append(R("VWAP side + prev-day high/low break", None, "no candle cache"))
        b = {}
    row = (ctx.get("idx") or {}).get(c["symbol"]) or {}
    pcr = _f(row.get("pcr"))
    if pcr is None:
        out.append(R("PCR extreme only with price confirmation", None, "no PCR", True))
    else:
        ext = pcr >= CFG["pcr_hi"] or pcr <= CFG["pcr_lo"]
        conf = b.get("15m") == ("UP" if ce else "DOWN")
        out.append(R("PCR extreme only with price confirmation", (not ext) or conf,
                     f"PCR {pcr} {'EXTREME' if ext else 'normal tilt'}" + (f" · 15m structure {b.get('15m')} {'confirms' if conf else 'does not confirm'}" if ext else ""), True))
    n5, n15 = net(_ago(L, ts, 5), now_), net(_ago(L, ts, 15), now_)
    if n5 is None or n15 is None:
        out.append(R("5-min + 15-min OI agree", None, "OI history still building"))
    else:
        ok = (n5 > 0 and n15 > 0) if ce else (n5 < 0 and n15 < 0)
        out.append(R("5-min + 15-min OI agree", ok, f"5-min {n5:+.1f} pts · 15-min {n15:+.1f} pts"))
    return out, {}


def us_events(ts):
    """Scheduled US releases that move MCX (times are New York, converted to IST, DST aware)."""
    from zoneinfo import ZoneInfo
    ist, ny = ZoneInfo("Asia/Kolkata"), ZoneInfo("America/New_York")
    d = ts.date()
    ev = []

    def at(day, h, m, name):
        t = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=ny).astimezone(ist).replace(tzinfo=None)
        ev.append((name, pd.Timestamp(t)))
    for k in (-1, 0):
        day = d + dt.timedelta(days=k)
        if day.weekday() == 2:
            at(day, 10, 30, "EIA crude inventory")
        if day.weekday() == 3:
            at(day, 10, 30, "EIA natural gas storage")
        if day.weekday() == 4 and day.day <= 7:
            at(day, 8, 30, "US jobs report (NFP)")
    return ev


def rules_of(c, ctx, ts):
    ce = c["side"] == "CE"
    out = [R("Real aggressor delta", False, "Angel gives no buy/sell aggressor data — delta is a volume proxy → trade HALF size")]
    fr = frames_for(c)
    if not fr:
        out += [R("Closed outside VAH/VAL + held retest 2 candles", None, "no candle cache", True), R("No delta divergence", None, "no candle cache"),
                R("Trend / neutral day (not range)", None, "no candle cache", True)]
    else:
        from . import v4 as V
        m5 = _cut(fr["5M"], ts)
        days = sorted(set(m5.index.date))
        two = m5[m5.index.date >= days[-2]] if len(days) >= 2 else m5
        vp = V.volume_profile(two)
        td = m5[m5.index.date == days[-1]]
        if not vp or len(td) < 4:
            out.append(R("Closed outside VAH/VAL + held retest 2 candles", None, "profile not computable", True))
        else:
            lvl = vp["vah"] if ce else vp["val"]
            cl, lo, hi = td["close"].values, td["low"].values, td["high"].values
            outside2 = all(x > lvl for x in cl[-2:]) if ce else all(x < lvl for x in cl[-2:])
            touch = any((lo[i] <= lvl * 1.001 and cl[i] > lvl) if ce else (hi[i] >= lvl * 0.999 and cl[i] < lvl) for i in range(max(0, len(cl) - 6), len(cl) - 1))
            out.append(R("Closed outside VAH/VAL + held retest 2 candles", bool(outside2 and touch),
                         f"{'VAH' if ce else 'VAL'} {lvl} · last 2 closes {'outside' if outside2 else 'not outside'} · retest {'held' if touch else 'not seen yet'}", True))
        dp = delta_proxy(td)
        if dp is None or len(td) < 13:
            out.append(R("No delta divergence", None, "not enough candles"))
        else:
            cl = td["close"].values
            newx = cl[-1] >= cl[-12:].max() if ce else cl[-1] <= cl[-12:].min()
            d3, p3 = float(dp.iloc[-3:].sum()), float(dp.iloc[-6:-3].sum())
            div = newx and ((d3 < p3) if ce else (d3 > p3))
            out.append(R("No delta divergence", not div, f"price {'at a new ' + ('high' if ce else 'low') if newx else 'not at a new extreme'} · delta last 3 {d3:,.0f} vs prev 3 {p3:,.0f}"))
        ib = td[td.index < td.index[0] + pd.Timedelta(minutes=60)]
        ibr = float(ib["high"].max() - ib["low"].min()) if len(ib) else 0
        dr = float(td["high"].max() - td["low"].min())
        if not ibr:
            out.append(R("Trend / neutral day (not range)", None, "first hour not complete", True))
        else:
            k = dr / ibr
            typ = "TREND day" if k >= 1.8 else "NEUTRAL day" if k >= 1.3 else "RANGE day"
            out.append(R("Trend / neutral day (not range)", k >= 1.3, f"day range {k:.1f}× first-hour range → {typ}", True))
    if c.get("exch") == "MCX":
        near = [(n, t) for n, t in us_events(ts) if abs((ts - t).total_seconds()) <= 1800]
        out.append(R("No major data release ±30 min", not near, ("near " + ", ".join(f"{n} {t.strftime('%H:%M')}" for n, t in near)) if near else
                     "no EIA / NFP release within 30 min", True))
        out.append(R("Commodity tracked separately", True, f"results kept under {c['symbol']} only"))
    else:
        out.append(R("No major data release ±30 min", None, "index: no scheduled-release list"))
    return out, {}


def rules_orb(c, ctx, ts):
    ce = c["side"] == "CE"
    out = []
    ut = [x for x in (c.get("ul_targets") or []) if _f(x)]
    px = _f(c.get("ul_price"))
    lvl = None
    if len(ut) >= 2:
        rng = abs(ut[1] - ut[0])
        lvl = ut[0] - rng if ce else ut[0] + rng
        pct = rng / lvl * 100 if lvl else None
        out.append(R("Range size 0.35%–1.5%", CFG["orb_min"] <= pct <= CFG["orb_max"], f"opening range {pct:.2f}% of price", True))
    else:
        out.append(R("Range size 0.35%–1.5%", None, "range not on the call", True))
    vr = _f(c.get("vol_ratio"))
    out.append(R("Relative volume ≥1.5× (time-of-day)", None if vr is None else vr >= CFG["rvol"], f"{vr}× normal volume for this time" if vr is not None else "no volume", True))
    if lvl and px:
        ext = abs(px - lvl) / lvl * 100
        out.append(R("Retest entry (not chased)", ext <= 0.3, f"price {ext:.2f}% from the breakout level {lvl:g}" + (" — wait for a retest" if ext > 0.3 else "")))
    else:
        out.append(R("Retest entry (not chased)", None, "levels missing"))
    lq = (ctx.get("live_q") or {}).get(c["symbol"]) or {}
    op = _f(lq.get("open"))
    ch = (ctx.get("charts") or {}).get(c["symbol"]) or {}
    vw = _f(ch.get("vwap"))
    ref, refn = (vw, "VWAP") if vw else (op, "today's open")
    side_ok = None if not (ref and px) else (px > ref if ce else px < ref)
    mdir = ctx.get("mdir")
    idx_ok = None if not mdir else (mdir == ("UP" if ce else "DOWN"))
    sec = (ctx.get("sector_of") or {}).get(c["symbol"])
    sec_ok = None if not sec or sec.get("score") is None else (sec["score"] >= 52 if ce else sec["score"] <= 48)
    parts = [p for p in (side_ok, idx_ok, sec_ok) if p is not None]
    out.append(R("VWAP/open + sector + index agree", None if not parts else all(parts),
                 f"{refn} {'ok' if side_ok else 'wrong side' if side_ok is False else 'n/a'} · index {mdir or 'n/a'} · sector "
                 + (f"{sec['name']} {sec['score']}" if sec and sec.get("score") is not None else "n/a")))
    earlier = [x for x in ctx["calls"] if strat_of(x) == "ORB" and x["symbol"] == c["symbol"] and x["date"] == c["date"] and x["id"] != c["id"]
               and str(x.get("signal_time") or "") < str(c.get("signal_time") or "")]
    out.append(R("First breakout per stock per day", not earlier, "first ORB call on this stock today" if not earlier else
                 f"{len(earlier)} earlier ORB call(s) today — second breakout skip", True))
    risk_ul = abs(px - _f(c.get("ul_sl"))) if px and _f(c.get("ul_sl")) else None
    lv = (ctx.get("levels") or {}).get(c["symbol"]) or {}
    cands = [_f(v) for k, v in lv.items() if _f(v)] + [_f(z.get("price")) for z in (ch.get("sr_up") if ce else ch.get("sr_dn")) or [] if isinstance(z, dict)]
    ahead = sorted([x for x in cands if x and ((x > px * 1.0005) if ce else (x < px * 0.9995))], key=lambda x: abs(x - px)) if px else []
    if not risk_ul:
        out.append(R("Next level ≥2R after costs", None, "risk unknown"))
    elif not ahead:
        out.append(R("Next level ≥2R after costs", True, "no known level in the way (open space)"))
    else:
        cost_pts = CFG["charges"] / max(_f(c.get("lot")) or 1, 1) / 0.5           # ₹ costs → underlying points (≈0.5 delta)
        room = abs(ahead[0] - px) - cost_pts
        out.append(R("Next level ≥2R after costs", room >= 2 * risk_ul, f"next level {ahead[0]:g} = {room / risk_ul:.1f}R after costs"))
    out.append(R("Before 11:45 AM", _hm(c) <= CFG["orb_cut"], f"signal {_hm(c)}", True))
    return out, {}


# ───────────────────────── common rules + grading ─────────────────────────
def common_rules(c, ctx, ts):
    ce = c["side"] == "CE"
    out = []
    mkt = market_of(c)
    cr = ctx.get("crash") or {}
    mdir = ctx.get("mdir")
    reg_bad = (cr.get("level") == "ALERT" and cr.get("side") == ("DOWN" if ce else "UP")) or (mdir and mkt != "Commodity" and mdir == ("DOWN" if ce else "UP"))
    late = _hm(c) > ("22:30" if mkt == "Commodity" else "14:30")
    news = next((r for r in ctx.get("results") or [] if r.get("symbol") == c["symbol"] and -1 <= (r.get("days") if r.get("days") is not None else 99) <= 1), None)
    vr = _f(c.get("vol_ratio"))
    low = mkt == "Stock" and vr is not None and vr < 1.0
    bad = [w for w, b in (("market against the trade", reg_bad), ("late entry", late), (f"results {news['date']}" if news else "", bool(news)),
                          ("low volume", low)) if b]
    out.append(R("No-trade conditions (regime · news · volume · time)", not bad, ", ".join(bad) if bad else "regime, news, volume, time all clear", True))
    same = [x for x in ctx["calls"] if strat_of(x) == strat_of(c) and x["symbol"] == c["symbol"] and x["date"] == c["date"] and x["id"] != c["id"]
            and str(x.get("signal_time") or "") < str(c.get("signal_time") or "")]
    out.append(R("Max 2 attempts per setup per day", len(same) < CFG["max_attempts"], f"attempt #{len(same) + 1} today", True))
    return out


def size_plan(c, half=False):
    e, sl, lot = _f(c.get("entry")), _f(c.get("sl0") or c.get("sl")), _f(c.get("lot"))
    if not (e and sl and lot) or e <= sl:
        return {"lots": None, "risk_lot": None, "txt": "size: plan incomplete"}
    rl = (e - sl) * lot
    n = int(CFG["risk_cap"] // rl) if rl <= CFG["risk_cap"] else 0
    if half:
        n = n // 2
    txt = (f"{n} lot{'s' if n != 1 else ''} (structure SL = ₹{rl:,.0f}/lot, ₹2,500 budget{', halved for proxy delta' if half else ''})" if n
           else f"structure SL is ₹{rl:,.0f}/lot — above the ₹2,500 budget: 1 lot max or skip")
    return {"lots": n, "risk_lot": round(rl), "txt": txt}


def grade(rules):
    known = [r for r in rules if r["ok"] is not None]
    if not known:
        return {"rating": None, "grade": "NO DATA", "known": 0, "total": len(rules)}
    w = lambda r: 2 if r["crit"] else 1
    rating = round(10 * sum(w(r) for r in known if r["ok"]) / sum(w(r) for r in known), 1)
    crit_fail = [r["name"] for r in known if r["crit"] and not r["ok"]]
    cover = len(known) / len(rules)
    if crit_fail:
        g = "SKIP"
    elif rating >= 9.99 and cover >= 0.7:
        g = "9.5 PRO"
    elif rating >= 7:
        g = "TAKE"
    else:
        g = "CAUTION"
    return {"rating": rating, "grade": g, "known": len(known), "total": len(rules), "crit_fail": crit_fail}


def guidance(c, k, g, extra, sz):
    ce = c["side"] == "CE"
    G = g["grade"]
    head = {"9.5 PRO": "✅ Full-checklist setup — take it with the planned size.", "TAKE": "🟢 Good setup — take it, follow the plan.",
            "CAUTION": "🟡 Weak checklist — half size or wait for a better one.", "SKIP": "🔴 Skip — a critical rule failed: " + ", ".join(g.get("crit_fail") or []),
            "NO DATA": "⚪ Not enough data to grade — paper only."}[G]
    tips = []
    if k == "SB":
        if extra.get("fvg_mid"):
            tips.append(f"Better entry: limit order when the index pulls back to the FVG 50% ≈ {extra['fvg_mid']} (premium a little below the signal).")
        tips.append("SL beyond the swept level; T1 1R → move SL to entry; T2 2R → trail.")
    elif k == "GU":
        tips.append("The edge is the big move: keep the 40% premium SL, book 1/3 at +25%, 1/3 at +50%, trail the rest to +100%.")
        if str(c.get("expiry")) == str(c.get("date")):
            tips.append("Expiry day — force exit by 2:45 PM whatever the P/L.")
    elif k == "IOI":
        tips.append("Index SL at the OI wall; exit if the wall shifts against you (support moves down for CE / resistance up for PE).")
    elif k == "OF":
        tips.append("Delta here is a volume proxy → half size. Exit if price closes back inside the value area (below VAH for long / above VAL for short).")
    elif k == "ORB":
        tips.append("Enter on the retest of the breakout level, not the breakout candle. One attempt only — if SL hits, done for this stock today.")
    tips.append("Size: " + sz["txt"] + ".")
    return head, tips


def evaluate(c, ctx, ts, ag=None, inst=None):
    k = strat_of(c)
    fn = {"SB": rules_sb, "IOI": rules_ioi, "OF": rules_of, "ORB": rules_orb}.get(k)
    try:
        rules, extra = (rules_gu(c, ctx, ts, ag, inst) if k == "GU" else fn(c, ctx, ts))
    except Exception as e:
        rules, extra = [R("Checklist", None, f"calc error: {str(e)[:60]}")], {}
    rules += common_rules(c, ctx, ts)
    g = grade(rules)
    sz = size_plan(c, half=(k == "OF"))
    head, tips = guidance(c, k, g, extra, sz)
    trend = ctx.get("trend") or ""
    return {"strategy": k, "market": market_of(c), "rules": rules, **g, "size": sz, "head": head, "tips": tips,
            "day_type": "TREND" if "TRENDING" in trend else "RANGE" if "RANGE" in trend else "UNKNOWN", "graded_at": ts.strftime("%Y-%m-%d %H:%M"),
            "fvg_mid": extra.get("fvg_mid")}


def run(D, ctx, now, ag=None, inst=None, send=None):
    """Grade every new call of the 5 strategies (once, frozen). Called UNDER CALLS_LOCK — no lock-taking helpers inside."""
    oi_sample(ctx.get("full"), now)
    G = D.setdefault("dhas", {})
    day = str(now.date())
    new = []
    for c in ctx["calls"]:
        if c.get("kind") == "PICK" or c.get("shadow") or not strat_of(c) or c["id"] in G:
            continue
        if c.get("date") != day:
            continue                                  # older calls are shown as "not graded (before Dhasvanth)"
        ts = _sig_ts(c) or now
        G[c["id"]] = ev = evaluate(c, ctx, ts, ag, inst)
        new.append((c, ev))
    cut = str((now - pd.Timedelta(days=CFG["keep_days"])).date())
    for cid in [cid for cid in G if cid[:10] < cut]:
        G.pop(cid, None)
    for c, ev in new:
        if send and ev["grade"] == "9.5 PRO" and c.get("status") in OPEN:
            try:
                send(f"🏹 DHASVANTH 9.5 PRO · {SKEY[ev['strategy']]['name']}\n{c['symbol']} {c.get('strike')} {c['side']} · Entry ₹{c.get('entry')} · SL ₹{c.get('sl')} · "
                     f"T1 ₹{(c.get('targets') or [None])[0]}\n{ev['size']['txt']}", f"dhas|{c['id']}", True)
            except Exception:
                pass
    STATE["time"] = now.strftime("%I:%M:%S %p")
    return len(new)


# ───────────────────────── report ─────────────────────────
GORD = {"9.5 PRO": 0, "TAKE": 1, "CAUTION": 2, "NO DATA": 3, "SKIP": 4}


def _stats(rows):
    done = [c for c in rows if c.get("status") not in OPEN and c.get("status") != "VOID" and c.get("pnl_lot") is not None]
    if not done:
        return {"n": 0}
    pn = [c.get("pnl_lot") or 0 for c in done]
    gw, gl = sum(p for p in pn if p > 0), -sum(p for p in pn if p < 0)
    rs = []
    for c in done:
        e, sl, lot = _f(c.get("entry")), _f(c.get("sl0") or c.get("sl")), _f(c.get("lot"))
        if e and sl and lot and e > sl:
            rs.append((c.get("pnl_lot") or 0) / ((e - sl) * lot))
    return {"n": len(done), "win": round(sum(p > 0 for p in pn) / len(pn) * 100), "net": round(sum(pn)), "exp": round(sum(pn) / len(pn)),
            "pf": round(gw / gl, 2) if gl else (9.0 if gw else 0.0), "avg_r": round(sum(rs) / len(rs), 2) if rs else None}


def _week(d):
    y, w, _ = pd.Timestamp(d).isocalendar()
    return f"{y}-W{w:02d}"


def report(D, now):
    G = (D or {}).get("dhas") or {}
    calls = [c for c in ((D or {}).get("calls") or {}).values() if c.get("kind") != "PICK" and not c.get("shadow") and strat_of(c)]
    day = str(now.date())
    since = str((now - pd.Timedelta(days=30)).date())
    keep = ("id", "date", "time", "symbol", "strike", "side", "expiry", "entry", "sl", "targets", "ltp", "exit", "status", "pnl_lot", "hits", "lot", "exch",
            "source", "source_label", "risk_warn")
    boxes, top = [], []
    for S in STRATS:
        mine = [c for c in calls if strat_of(c) == S["key"]]
        rows = []
        for c in mine:
            ev = G.get(c["id"])
            r = {**{k: c.get(k) for k in keep}, "market": market_of(c), "ev": ev}
            rows.append(r)
        today = sorted([r for r in rows if r["date"] == day], key=lambda r: (GORD.get((r["ev"] or {}).get("grade"), 5), -((r["ev"] or {}).get("rating") or 0), r["time"] or ""))
        hist = sorted([r for r in rows if r["date"] >= since and r["status"] not in OPEN], key=lambda r: (r["date"], r["time"] or ""), reverse=True)
        graded = [r for r in rows if r["ev"]]
        by_grade = {g: _stats([r for r in graded if r["ev"]["grade"] == g]) for g in GORD}
        st = {"all": _stats(rows), "graded": _stats(graded), "by_grade": by_grade,
              "take": _stats([r for r in graded if r["ev"]["grade"] in ("9.5 PRO", "TAKE")]),
              "by_market": {m: _stats([r for r in rows if r["market"] == m]) for m in ("Index", "Stock", "Commodity")},
              "by_day": {t: _stats([r for r in graded if r["ev"].get("day_type") == t]) for t in ("TREND", "RANGE")},
              "by_symbol": ({s: _stats([r for r in rows if r["symbol"] == s]) for s in sorted({r["symbol"] for r in rows if r["market"] == "Commodity"})}
                            if S["key"] in ("OF", "SB") else {})}
        weeks = {}
        for r in rows:
            weeks.setdefault(_week(r["date"]), []).append(r)
        st["weekly"] = [{"week": w, **_stats(v)} for w, v in sorted(weeks.items(), reverse=True)[:8]]
        try:
            from .calls import SKIPPED as _SK
            rej = [dict(r) for r in (_SK.get("log") or []) if _SK.get("day") == day and strat_of({"source": r.get("source"), "kind": r.get("kind")}) == S["key"]][-12:]
        except Exception:
            rej = []
        boxes.append({**{k: S[k] for k in ("key", "name", "icon", "markets", "how", "rules")}, "today": today, "history": hist[:60], "stats": st,
                      "ai": box_ai(S, today, st), "rejects": rej[::-1]})
        top += [dict(r, strategy=S["key"], sname=S["name"]) for r in today if r["ev"] and r["ev"]["grade"] in ("9.5 PRO", "TAKE") and r["status"] in OPEN]
    top.sort(key=lambda r: (GORD.get(r["ev"]["grade"], 5), -(r["ev"].get("rating") or 0)))
    return {"time": STATE["time"], "boxes": boxes, "top": top[:10], "cfg": CFG}


def box_ai(S, today, st):
    a, t = st["all"], st["take"]
    L = []
    if a.get("n"):
        L.append(f"Record: {a['n']} closed · {a['win']}% win · PF {a['pf']} · ₹{a['exp']:,}/call" + (f" · {a['avg_r']}R avg" if a.get("avg_r") is not None else "") + ".")
    if t.get("n", 0) >= 5 and a.get("n"):
        better = (t.get("exp") or 0) > (a.get("exp") or 0)
        L.append(f"Dhasvanth TAKE/PRO calls: {t['n']} closed · {t['win']}% win · ₹{t['exp']:,}/call → the filter is {'HELPING' if better else 'NOT helping yet'}.")
    elif a.get("n"):
        L.append("The filter needs 5+ graded closed calls before it can prove itself — keep paper trading.")
    dt_ = st["by_day"]
    if dt_["TREND"].get("n", 0) >= 3 and dt_["RANGE"].get("n", 0) >= 3:
        L.append(f"Trend days {dt_['TREND']['win']}% win vs range days {dt_['RANGE']['win']}% win.")
    pro = [r for r in today if r["ev"] and r["ev"]["grade"] == "9.5 PRO"]
    tk = [r for r in today if r["ev"] and r["ev"]["grade"] == "TAKE"]
    if pro or tk:
        b = (pro or tk)[0]
        L.append(f"Today's best: {b['symbol']} {b.get('strike') or ''} {b['side']} ({b['ev']['grade']}, {b['ev']['rating']}/10).")
    elif today:
        L.append(f"{len(today)} call(s) today, none passed the checklist — wait for the next one.")
    else:
        L.append({"SB": "Watch 10:00–10:25 and 13:30–13:55 — that is when Silver Bullet calls are allowed.",
                  "GU": "Gamma Unwind fires 9:30–2:30 on stock zone breaks with OI falling — no call yet.",
                  "IOI": "Index OI needs PCR ≥1.2 or ≤0.8 with the OI trend agreeing — no call yet.",
                  "OF": "Order Flow needs acceptance outside the value area with volume — no call yet.",
                  "ORB": "ORB calls only come 9:20–11:45 on a clean first-5-min range break — no call yet."}[S["key"]])
    return L
