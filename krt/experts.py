"""🎓 EXPERT-STYLE PICKS — four screens built from publicly described trading METHODS, run on the terminal's own live data.

These are NOT calls from the people named. Each screen applies a well-known approach mechanically:
  1. Price Action + OI + Market Direction   (the approach Gaurav Reddy is known for teaching)
       trade only WITH NIFTY · price breaking the previous-day high/low and holding VWAP · fresh OI build-up on the same side
  2. Quality stock selection + setup ranking (the approach associated with Asit Baran Pati)
       strongest / weakest sectors first · relative strength vs NIFTY · clean trend · liquid · not extended → ranked list
  3. VCP + volume breakout + relative strength (Mark Minervini's published method, long-only)
       volatility contraction (ATR5/ATR20, Bollinger width, NR7, volume drying up) near the 20-day high · RS rating ≥70 ·
       buy only on a breakout with ≥1.5× volume
  4. Experienced-trader consensus — every engine in the terminal votes (JARVIS, AI Lab, SMC, big players, Top Movers guide,
       ⭐ star-strategy calls, the three screens above). More independent agreement = higher rank.
Every pick: side, strike (instrument master), live premium, entry trigger, stop, target, and the evidence. A plan, not a guarantee.
"""
import pandas as pd


def _rs_table(bars):
    """RS rating 1–99: percentile of each stock's ~3-month return among all F&O stocks (Minervini-style relative strength)."""
    from .ailab import _bars_df
    ret = {}
    for s, b in (bars or {}).items():
        d = _bars_df(b)
        if d is None or len(d) < 30:
            continue
        c = d["close"].astype(float)
        n = min(63, len(c) - 1)
        if c.iloc[-1 - n]:
            ret[s] = float(c.iloc[-1] / c.iloc[-1 - n] - 1)
    if not ret:
        return {}, {}
    srt = sorted(ret.values())
    rs = {s: max(1, min(99, round(sum(1 for x in srt if x <= v) / len(srt) * 99))) for s, v in ret.items()}
    sma = {}
    for s, b in (bars or {}).items():
        d = _bars_df(b)
        if d is not None and len(d) >= 50:
            c = d["close"].astype(float)
            sma[s] = {"c": float(c.iloc[-1]), "s20": float(c.tail(20).mean()), "s50": float(c.tail(50).mean())}
    return rs, sma


def _pick(sym, side, score, why, entry, sl, target, method):
    return {"symbol": sym, "side": side, "score": int(max(0, min(100, score))), "why": why, "entry": entry, "sl": sl, "target": target, "method": method}


def price_action_oi(lq, levels, oi, nifty_pct, top=3):
    out = []
    mdir = "CE" if (nifty_pct or 0) >= 0.25 else "PE" if (nifty_pct or 0) <= -0.25 else None
    for s, q in lq.items():
        ltp, vw, pct = q.get("ltp"), q.get("vwap"), q.get("pct") or 0
        hi, lo, rv = q.get("high"), q.get("low"), q.get("vol_ratio") or 0
        lv = levels.get(s) or {}
        pdh, pdl = lv.get("PDH"), lv.get("PDL")
        if not (ltp and hi and lo and hi > lo):
            continue
        for side in ("CE", "PE"):
            if mdir and side != mdir:
                continue                                   # trade only WITH the market
            ce = side == "CE"
            if (ce and pct < 0.5) or (not ce and pct > -0.5):
                continue
            sc, why = 0, []
            lvl = pdh if ce else pdl
            if lvl and ((ce and ltp > lvl) or (not ce and ltp < lvl)):
                sc += 30
                why.append(f"price {'above PDH' if ce else 'below PDL'} {lvl:g}")
            if vw and ((ce and ltp > vw) or (not ce and ltp < vw)):
                sc += 15
                why.append(f"holding {'above' if ce else 'below'} VWAP {vw:g}")
            pos = (ltp - lo) / (hi - lo)
            if (ce and pos >= 0.75) or (not ce and pos <= 0.25):
                sc += 10
                why.append("closing near the day's " + ("high" if ce else "low"))
            k = oi.get(s)
            if k == ("Long Built Up" if ce else "Short Built Up"):
                sc += 30
                why.append(f"OI: {k} (fresh positions)")
            elif k == ("Short Covering" if ce else "Long Unwinding"):
                sc += 12
                why.append(f"OI: {k}")
            if mdir == side:
                sc += 15
                why.append(f"NIFTY {nifty_pct:+.2f}% — same direction")
            if rv >= 1.5:
                sc += 10
                why.append(f"volume {rv}×")
            if sc < 70:
                continue
            sl = vw if vw else (lo if ce else hi)
            rng = hi - lo
            out.append(_pick(s, side, sc, why, f"on a pullback that holds {'above' if ce else 'below'} {lvl or vw:g}" if (lvl or vw) else "next 5-min candle in the same direction",
                             round(sl, 2), round(ltp + rng if ce else ltp - rng, 2), "PA+OI+Direction"))
    out.sort(key=lambda p: -p["score"])
    return out[:top]


def quality_rank(lq, sectors, sector_of, oi, nifty_pct, rs, sma, top=3):
    out = []
    mdir = "CE" if (nifty_pct or 0) >= 0 else "PE"
    secs = sorted(sectors.items(), key=lambda kv: -kv[1])
    strong = {k for k, _ in secs[:3]}
    weak = {k for k, _ in secs[-3:]}
    for s, q in lq.items():
        ltp, vw, pct, rv = q.get("ltp"), q.get("vwap"), q.get("pct") or 0, q.get("vol_ratio") or 0
        sec = sector_of.get(s)
        if not ltp or not sec or abs(pct) > 4:
            continue
        side = mdir
        ce = side == "CE"
        if (ce and sec not in strong) or (not ce and sec not in weak):
            continue
        sc, why = 0, [f"sector {sec} {'strong' if ce else 'weak'} ({sectors.get(sec, 0):+.2f}%)"]
        sc += 25
        rel = pct - (nifty_pct or 0)
        if (ce and rel >= 1) or (not ce and rel <= -1):
            sc += 25
            why.append(f"{'stronger' if ce else 'weaker'} than NIFTY by {abs(rel):.1f}%")
        elif (ce and rel <= 0) or (not ce and rel >= 0):
            continue
        m = sma.get(s) or {}
        if m and ((ce and m["c"] > m["s20"] > m["s50"]) or (not ce and m["c"] < m["s20"] < m["s50"])):
            sc += 20
            why.append("clean daily trend (price / 20-day / 50-day in order)")
        if vw and ((ce and ltp > vw) or (not ce and ltp < vw)):
            sc += 10
            why.append("on the right side of VWAP")
        if rv >= 1.5:
            sc += 10
            why.append(f"volume {rv}×")
        k = oi.get(s)
        if k == ("Long Built Up" if ce else "Short Built Up"):
            sc += 10
            why.append(f"OI {k}")
        r_ = rs.get(s)
        if r_ is not None:
            why.append(f"RS rating {r_}")
        if sc < 65:
            continue
        hi, lo = q.get("high") or ltp, q.get("low") or ltp
        out.append(_pick(s, side, sc, why, f"5-min close {'above' if ce else 'below'} today's {'high' if ce else 'low'} {hi if ce else lo:g}",
                         round(vw or (lo if ce else hi), 2), round(ltp + (hi - lo) * 1.5 if ce else ltp - (hi - lo) * 1.5, 2), "Quality+Ranking"))
    out.sort(key=lambda p: -p["score"])
    return out[:top]


def vcp_breakout(prebreak, rs, sma, lq, top=3):
    out = []
    for p in prebreak or []:
        if p.get("side") != "CE" or p.get("status") not in ("BREAKING", "NEAR", "WATCH"):
            continue                                    # Minervini method = long-only
        s = p["symbol"]
        r_ = rs.get(s)
        if r_ is not None and r_ < 70:
            continue
        sc = p.get("score", 50) * 0.5 + (r_ or 50) * 0.3
        why = [f"volatility contraction: ATR5/ATR20 {p.get('comp')} · BB width {p.get('bw_pct')} pct · volume dry {p.get('vol_dry')}×" + (" · NR7" if p.get("nr7") else ""),
               f"near the 20-day high {p.get('level')} ({p.get('dist')}% away)"]
        if r_ is not None:
            why.append(f"RS rating {r_} (top {100 - r_}% of F&O)")
        m = sma.get(s) or {}
        if m and m["c"] > m["s50"]:
            sc += 5
            why.append("above the 50-day average")
        vr = (lq.get(s) or {}).get("vol_ratio") or p.get("vr") or 0
        if p.get("status") == "BREAKING":
            sc += 15
            why.append(f"BREAKING OUT now with volume {vr}×")
            ent = f"breakout confirmed — buy near {p.get('level')}, not more than 2% above it"
        else:
            ent = f"BUY only on a 5-min close above {p.get('level')} with volume ≥1.5× (pivot breakout)"
        out.append(_pick(s, "CE", sc, why, ent, p.get("ul_sl"), p.get("ul_target"), "VCP+Breakout+RS"))
    out.sort(key=lambda p: -p["score"])
    return out[:top]


def consensus(sources, mdir=None, top=5):
    """sources: list of (name, weight, [(symbol, side)]). → symbols with the most independent agreement."""
    votes = {}
    for name, w, items in sources:
        for sym, side in set(items):
            v = votes.setdefault((sym, side), {"score": 0, "who": []})
            v["score"] += w
            v["who"].append(name)
    out = []
    for (sym, side), v in votes.items():
        if len(v["who"]) < 2:
            continue
        sc = v["score"] * 12 + (10 if mdir == side else -10 if mdir and mdir != side else 0)
        out.append(_pick(sym, side, sc, [f"{len(v['who'])} engines agree: " + ", ".join(v["who"])]
                         + ([f"market direction {'agrees' if mdir == side else 'is AGAINST — 1 lot only'}"] if mdir else []), None, None, None, "Consensus"))
    out.sort(key=lambda p: -p["score"])
    return out[:top]
