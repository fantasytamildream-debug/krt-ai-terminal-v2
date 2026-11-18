"""🏛 KRT COMMAND CENTER (V3.0 phase 1) — Top Movers → stock chart → real option chain → strike premium chart → Money Control.

Data rules (from the V3.0 spec):
  · Every number comes from Angel SmartAPI data the terminal already fetched (live quotes, instrument master, candles). Missing → None,
    shown as "–" / "no data" — never filled in.
  · Strikes, expiries and lot sizes come only from the instrument master (2 nearest expiries are cached).
  · Greeks are MODELLED (Black-Scholes from the option's own LTP, r = 6.5%) — labelled as estimates, not exchange data.
  · Premium-chart plan: entry = last CLOSED candle close · SL = structure (lowest low of the last swing, below the entry) ·
    T1/T2/T3 = premium swing highs above entry when they exist, else 1R / 2R / 3R (each target says which).
  · The forming candle is marked and never used for the plan (no repaint / no look-ahead).
"""
import math
import time

import pandas as pd

from .money import SECTOR

TABS = ["gainers", "losers", "volume", "oi", "breakouts", "breakdowns", "sectors"]
CACHE = {}          # key → (ts, value)


def _c(key, ttl, fn):
    hit = CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    v = fn()
    CACHE[key] = (time.time(), v)
    if len(CACHE) > 300:
        for k in sorted(CACHE, key=lambda k: CACHE[k][0])[:100]:
            CACHE.pop(k, None)
    return v


# ───────────────────────── 1. Top movers ─────────────────────────
def _row(sym, q, lv, oi, bv):
    ltp, vw = q.get("ltp") or 0, q.get("vwap")
    hi, lo = q.get("high") or 0, q.get("low") or 0
    pos = (ltp - lo) / (hi - lo) if hi > lo else None
    pdh, pdl = (lv or {}).get("PDH"), (lv or {}).get("PDL")
    pct, vr = q.get("pct") or 0, q.get("vol_ratio") or 0
    mom = ("STRONG UP" if pct >= 1.5 and (pos or 0) >= 0.75 else "UP" if pct > 0.3 else "STRONG DOWN" if pct <= -1.5 and pos is not None and pos <= 0.25
           else "DOWN" if pct < -0.3 else "FLAT")
    setup = ("BREAKOUT" if pdh and ltp > pdh and vr >= 1.5 else "BREAKDOWN" if pdl and ltp < pdl and vr >= 1.5 else
             "NEAR PDH" if pdh and 0 <= (pdh - ltp) / pdh * 100 <= 0.5 else "NEAR PDL" if pdl and 0 <= (ltp - pdl) / pdl * 100 <= 0.5 else "–")
    today = str(pd.Timestamp.now(tz="Asia/Kolkata").date())
    b = [x for x in ((bv or {}).get("spikes") or []) if str(x.get("time", ""))[:10] == today]      # v124: TODAY's big-player spikes only
    return {"symbol": sym, "ltp": ltp, "pct": round(pct, 2), "rvol": vr or None, "volume": q.get("volume"),
            "vwap": vw, "vwap_pos": None if not vw else ("ABOVE" if ltp >= vw else "BELOW"),
            "oi": (oi or {}).get("kind"), "oi_chg_pct": (oi or {}).get("oi_chg_pct"), "sector": SECTOR.get(sym, "Others"),
            "momentum": mom, "setup": setup, "pdh": pdh, "pdl": pdl, "day_pos": None if pos is None else round(pos * 100),
            "big": {"side": b[0]["side"], "mult": b[0]["mult"], "time": b[0]["time"]} if b else None}


def advise(r, mkt=None, strike=None):
    """v124 plain guidance for one mover: CE / PE / avoid, when to enter, SL, strike. Built from the row's own live numbers."""
    pct, vw, ltp, rv = r.get("pct") or 0, r.get("vwap"), r.get("ltp") or 0, r.get("rvol") or 0
    pdh, pdl, dp = r.get("pdh"), r.get("pdl"), r.get("day_pos")
    big = r.get("big") or {}
    up_side = pct > 0
    side = "CE" if up_side else "PE"
    against_big = big and ((up_side and big.get("side") == "SELL") or (not up_side and big.get("side") == "BUY"))
    with_big = big and ((up_side and big.get("side") == "BUY") or (not up_side and big.get("side") == "SELL"))
    vw_ok = vw is None or (ltp >= vw if up_side else ltp <= vw)
    mkt_against = (mkt == "BEAR" and up_side) or (mkt == "BULL" and not up_side)
    st = f"{strike['strike']:g} {side}" if strike else f"ATM {side}"
    if abs(pct) >= 4 or (dp is not None and ((up_side and dp >= 97) or (not up_side and dp <= 3)) and rv < 1.5):
        return {"tag": "LATE", "txt": f"Already moved {pct:+.1f}% — don't chase. Wait for a pullback to VWAP {vw:g}." if vw else f"Already moved {pct:+.1f}% — don't chase."}
    if against_big:
        return {"tag": "AVOID", "txt": f"Big players {'SELLING' if up_side else 'BUYING'} today ({big['mult']}× at {big['time'][11:16]}) — against this move. Skip {side}."}
    if not vw_ok:
        return {"tag": "AVOID", "txt": f"Price is {'below' if up_side else 'above'} VWAP {vw:g} — the move is weak. Skip for now."}
    if abs(pct) < 0.5 or rv < 1.2:
        return {"tag": "WAIT", "txt": f"Small move / normal volume ({rv or '–'}×). Watch only."}
    lvl = pdh if up_side else pdl
    trig = (f"a 5-min close {'above' if up_side else 'below'} {lvl:g} (prev-day {'high' if up_side else 'low'})" if lvl and ((ltp < lvl) if up_side else (ltp > lvl))
            else f"a pullback to VWAP {vw:g} that holds" if vw else "the next 5-min candle in the same direction")
    sl = f"SL if price {'falls below' if up_side else 'rises above'} VWAP {vw:g}" if vw else "SL below the last 5-min candle"
    tag = "CE" if up_side else "PE"
    note = " · market is against it → 1 lot only" if mkt_against else ""
    plus = " · 🐋 big players on the same side" if with_big else ""
    return {"tag": "BUY " + tag, "txt": f"BUY {r['symbol']} {st} on {trig}. {sl}.{plus}{note}", "strike": strike}


def movers(live_q, levels, oi_rows, bv_get=None, n=25, mkt=None, strike_of=None):
    live_q = live_q or {}
    oi = {}
    for r in oi_rows or []:
        oi.setdefault(r["symbol"], r)
    rows = []
    for s, q in live_q.items():
        if not q.get("ltp"):
            continue
        try:
            bv = bv_get(s) if bv_get else None
        except Exception:
            bv = None
        rows.append(_row(s, q, (levels or {}).get(s), oi.get(s), bv))
    srt0 = lambda f, key, rev=True: sorted([r for r in rows if f(r)], key=key, reverse=rev)[:n]

    def srt(f, key, rev=True):
        L = srt0(f, key, rev)
        for r in L:
            if "ai" not in r:
                st = None
                try:
                    st = strike_of(r["symbol"], "CE" if r["pct"] > 0 else "PE", r["ltp"]) if strike_of else None
                except Exception:
                    st = None
                r["ai"] = advise(r, mkt, st)
        return L
    sec = {}
    for r in rows:
        if r["sector"] != "Others":
            sec.setdefault(r["sector"], []).append(r)
    sectors = []
    for k, L in sec.items():
        avg = sum(x["pct"] for x in L) / len(L)
        L2 = sorted(L, key=lambda x: -x["pct"])
        sectors.append({"sector": k, "pct": round(avg, 2), "n": len(L), "up": sum(1 for x in L if x["pct"] > 0),
                        "leader": L2[0]["symbol"], "leader_pct": L2[0]["pct"], "laggard": L2[-1]["symbol"], "laggard_pct": L2[-1]["pct"],
                        "stocks": [x["symbol"] for x in L2]})
    sectors.sort(key=lambda s: -s["pct"])
    return {"gainers": srt(lambda r: r["pct"] > 0, lambda r: r["pct"]),
            "losers": srt(lambda r: r["pct"] < 0, lambda r: r["pct"], False),
            "volume": srt(lambda r: r["rvol"], lambda r: r["rvol"] or 0),
            "oi": srt(lambda r: r["oi"], lambda r: abs(r["oi_chg_pct"] or 0)),
            "breakouts": srt(lambda r: r["setup"] in ("BREAKOUT", "NEAR PDH"), lambda r: (r["setup"] == "BREAKOUT", r["rvol"] or 0)),
            "breakdowns": srt(lambda r: r["setup"] in ("BREAKDOWN", "NEAR PDL"), lambda r: (r["setup"] == "BREAKDOWN", r["rvol"] or 0)),
            "sectors": sectors, "n": len(rows),
            "breadth": {"up": sum(1 for r in rows if r["pct"] > 0), "down": sum(1 for r in rows if r["pct"] < 0)}}


# ───────────────────────── 2. Option chain + strike ranking ─────────────────────────
def _greeks(prem, S, K, exp, typ, now):
    from .optmath import iv, years_to_expiry, R
    T = years_to_expiry(exp, now)
    if not (prem and S and K and T > 0):
        return {}
    try:
        sig = iv(prem, S, K, T, typ)
    except Exception:
        return {}
    if not sig or sig <= 0 or sig > 5:
        return {}
    d1 = (math.log(S / K) + (R + sig * sig / 2) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    pdf = math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi)
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    delta = N(d1) if typ == "CE" else N(d1) - 1
    gamma = pdf / (S * sig * math.sqrt(T))
    vega = S * pdf * math.sqrt(T) / 100
    th = (-(S * pdf * sig) / (2 * math.sqrt(T)) - (R * K * math.exp(-R * T) * (N(d2) if typ == "CE" else -N(-d2)))) / 365
    return {"iv": round(sig * 100, 1), "delta": round(delta, 2), "gamma": round(gamma, 5), "theta": round(th, 2), "vega": round(vega, 2), "model": True}


def expiries(inst, sym):
    from .instruments import INDEX_OPT_EXCH
    rows = (inst.get("opts") or {}).get(sym) or []
    if sym not in INDEX_OPT_EXCH:
        rows = [r for r in rows if r[6] == "NFO"] or rows
    today = str(pd.Timestamp.now(tz="Asia/Kolkata").date())
    return sorted({r[2] for r in rows if r[2] >= today}), rows


def chain(ag, inst, sym, expiry=None, width=6, now=None):
    """Real strikes from the instrument master around the live spot → one quote call → LTP / bid / ask / spread / OI / volume
    + modelled greeks + a liquidity-first ranking."""
    from .instruments import INDEX_SPOT
    now = pd.Timestamp(now or pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None))
    exps, rows = expiries(inst, sym)
    if not exps:
        return {"ok": False, "msg": f"{sym}: no option contracts in the instrument master (not an F&O symbol?)"}
    exp = expiry if expiry in exps else exps[0]
    rows = [r for r in rows if r[2] == exp]
    if sym in INDEX_SPOT:
        ux, ut = INDEX_SPOT[sym]
    else:
        ux, ut = "NSE", (inst.get("eq") or {}).get(sym)
    q0 = ag.quotes({ux: [ut]}) if ut else {}
    spot = float((q0.get(str(ut)) or {}).get("ltp") or 0)
    if not spot:
        return {"ok": False, "msg": f"{sym}: live underlying price not available right now — chain not shown (no made-up numbers)"}
    strikes = sorted({float(r[3]) for r in rows})
    atm = min(strikes, key=lambda k: abs(k - spot))
    i = strikes.index(atm)
    pick = set(strikes[max(0, i - width):i + width + 1])
    use = [r for r in rows if float(r[3]) in pick]
    toks = {}
    for r in use:
        toks.setdefault(r[6], []).append(r[0])
    qs = ag.quotes(toks)
    out = []
    for r in sorted(use, key=lambda r: (r[3], r[4])):
        q = qs.get(str(r[0])) or {}
        ltp = float(q.get("ltp") or 0) or None
        dp = q.get("depth") or {}
        bid = next((float(x.get("price") or 0) for x in dp.get("buy") or [] if float(x.get("price") or 0) > 0), None)
        ask = next((float(x.get("price") or 0) for x in dp.get("sell") or [] if float(x.get("price") or 0) > 0), None)
        spr = round((ask - bid) / ((ask + bid) / 2) * 100, 2) if bid and ask else None
        oi_, ch_ = q.get("opnInterest"), None
        K, typ = float(r[3]), r[4]
        itm = (typ == "CE" and K < spot) or (typ == "PE" and K > spot)
        g = _greeks(ltp, spot, K, exp, typ, now) if ltp else {}
        out.append({"token": r[0], "contract": r[1], "expiry": r[2], "strike": K, "type": typ, "lot": r[5], "exch": r[6],
                    "ltp": ltp, "bid": bid, "ask": ask, "spread_pct": spr, "volume": q.get("tradeVolume"), "oi": oi_,
                    "chg_pct": q.get("percentChange"), "moneyness": "ATM" if K == atm else "ITM" if itm else "OTM", **g})
    for typ in ("CE", "PE"):
        L = [x for x in out if x["type"] == typ and x["ltp"]]
        mv = max([x["volume"] or 0 for x in L] or [1]) or 1
        mo = max([x["oi"] or 0 for x in L] or [1]) or 1
        for x in L:
            sc, why = 0, []
            if x["spread_pct"] is not None:
                p = max(0, 30 - x["spread_pct"] * 15)
                sc += p
                why.append(f"spread {x['spread_pct']}%")
            else:
                why.append("no bid/ask depth")
            sc += 20 * (x["volume"] or 0) / mv + 15 * (x["oi"] or 0) / mo
            d = abs(x.get("delta") or 0)
            if d:
                sc += max(0, 25 - abs(d - 0.5) * 80)
                why.append(f"Δ {d:.2f}")
            risk1 = (x["ltp"] * 0.3) * (x["lot"] or 0)          # cost of a 30% premium SL for one lot
            if risk1 and risk1 <= 2500:
                sc += 10
            elif risk1:
                why.append(f"30% SL = ₹{risk1:,.0f}/lot > ₹2,500")
            x["rank_score"], x["rank_why"] = round(sc), why
        for n_, x in enumerate(sorted(L, key=lambda x: -x["rank_score"]), 1):
            x["rank"] = n_
    return {"ok": True, "symbol": sym, "spot": spot, "atm": atm, "expiry": exp, "expiries": exps, "rows": out,
            "lot": use[0][5] if use else None, "time": now.strftime("%d %b %H:%M:%S"),
            "note": "Greeks are modelled (Black-Scholes from each option's LTP, r 6.5%) — estimates, not exchange data. "
                    "Ranking = spread + volume + OI + delta near 0.5 + 1-lot risk; not by maximum profit."}


# ───────────────────────── 3. Strike premium chart + plan ─────────────────────────
def premium_plan(df, lot=None, closed_upto=None):
    """df = premium OHLCV. Uses CLOSED candles only. → plan dict with the source of every level."""
    if df is None or len(df) < 8:
        return None
    d = df if closed_upto is None else df[df.index <= closed_upto]
    if len(d) < 8:
        return None
    h, l, c = d["high"].astype(float), d["low"].astype(float), d["close"].astype(float)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.tail(14).mean())
    e = float(c.iloc[-1])
    lows = [float(l.iloc[i]) for i in range(len(d) - 12, len(d) - 1) if 0 < i < len(d) - 1 and l.iloc[i] <= l.iloc[i - 1] and l.iloc[i] <= l.iloc[i + 1]]
    sw = [x for x in lows if x < e]
    if sw:
        sl, sl_src = max(sw) - 0.05, "last swing low on the premium chart"
    else:
        sl, sl_src = e - 1.5 * atr, "1.5 × ATR (no swing low below entry)"
    sl = max(round(sl / 0.05) * 0.05, round(e * 0.4 / 0.05) * 0.05)
    if sl >= e:
        return None
    R = e - sl
    highs = sorted({round(float(h.iloc[i]), 2) for i in range(1, len(d) - 1) if h.iloc[i] >= h.iloc[i - 1] and h.iloc[i] >= h.iloc[i + 1] and h.iloc[i] > e + 0.5 * R})
    T, src = [], []
    for k in (1, 2, 3, 4, 5):                # v126: T1–T5
        want = e + k * R
        cand = [x for x in highs if x >= e + (k - 0.5) * R and (not T or x > T[-1] + 0.25 * R)]
        if cand and cand[0] <= want * 1.25:
            T.append(cand[0])
            src.append("premium swing high")
        else:
            T.append(round(round(want / 0.05) * 0.05, 2))
            src.append(f"{k}R")
    risk = round(R * lot) if lot else None
    return {"entry": round(e, 2), "sl": round(sl, 2), "sl_src": sl_src, "targets": T, "t_src": src, "atr": round(atr, 2),
            "rr_t2": round((T[1] - e) / R, 2), "t5": True, "risk_lot": risk, "risk_ok": None if risk is None else risk <= 2500,
            "invalid": f"5-min close below ₹{round(sl, 2)}", "entry_zone": [round(e * 0.99, 2), round(e * 1.02, 2)]}


def opt_candles(ag, exch, token, tf, lot=None, now=None):
    iv = {"1": "ONE_MINUTE", "3": "THREE_MINUTE", "5": "FIVE_MINUTE", "15": "FIFTEEN_MINUTE", "60": "ONE_HOUR"}.get(str(tf), "FIVE_MINUTE")
    bar = {"ONE_MINUTE": 1, "THREE_MINUTE": 3, "FIVE_MINUTE": 5, "FIFTEEN_MINUTE": 15, "ONE_HOUR": 60}[iv]
    now = pd.Timestamp(now or pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None))

    def go():
        df = ag.candles(exch, token, iv, now - pd.Timedelta(days={1: 2, 3: 3, 5: 4, 15: 8, 60: 20}[bar]), now)
        if df is None or df.empty:
            return {"ok": False, "msg": "No premium candles from Angel for this contract (illiquid or outside market hours)."}
        df = df.tail(150)
        cur = now.floor(f"{bar}min")
        closed = cur - pd.Timedelta(minutes=bar)
        k = [[i.strftime("%d %b %H:%M"), round(float(r["open"]), 2), round(float(r["high"]), 2), round(float(r["low"]), 2), round(float(r["close"]), 2),
              int(r["volume"]), bool(i >= cur)] for i, r in df.iterrows()]
        return {"ok": True, "candles": k, "plan": premium_plan(df, lot, closed), "tf": str(tf), "time": now.strftime("%d %b %H:%M:%S"),
                "note": "Plan uses closed candles only — the last candle marked 'forming' is ignored."}
    return _c(f"oc|{token}|{tf}", 20, go)
