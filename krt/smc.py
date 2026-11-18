"""📐 SMC / ICT SNIPER ENGINE — deterministic, non-repainting pattern detection + sweep-reversal / BOS-OB setups + chart boxes.

All rules run on CLOSED candles only, bar by bar in time order: a pattern is known only from the bar where it is confirmed
(a swing needs K candles on its right — it is "confirmed" K bars later and never used before that). No future data.

Definitions (configurable in CFG):
  Swing high/low   fractal: high above the K candles on each side (K = 2), confirmed K bars later
  HH / HL / LH / LL each confirmed swing vs the previous one of the same type
  BOS              close beyond the last confirmed swing in the trend direction · CHOCH = close beyond it AGAINST the trend
  MSS              a CHOCH within 12 bars after a liquidity sweep in the opposite direction
  Liquidity pools  confirmed swing highs/lows · equal highs/lows (two swings within 0.06%) · PDH / PDL / PWH / PWL
  BSL / SSL sweep  wick through a pool and the candle (or one of the next 2) closes back inside
  Failed breakout  a CLOSE beyond a pool that is closed back inside within 3 bars (bull / bear trap)
  Displacement     body ≥ 1.5 × ATR(14) and body ≥ 60% of the range
  FVG              3-candle gap (low[i] > high[i-2] bullish) · IFVG = FVG later closed through (flips side) ·
                   Liquidity void = FVG ≥ 1 ATR tall
  Order block      last opposite-colour candle before a displacement that broke structure · Breaker = OB closed through
  ORB              first 15 min high/low, broken on a 5-min close · VWAP reclaim / rejection (stocks only — index spot has no volume)
  Premium/Discount above / below 50% of the current dealing range (last confirmed swing high ↔ swing low)
Setups (a sweep alone is NOT a trade):
  SWEEP REVERSAL   sweep → MSS → retest of the FVG / OB made by the move → rejection close  = ENTRY CONFIRMED
  BOS + OB         BOS with displacement → retest of the order block → rejection close     = ENTRY CONFIRMED
  SL = beyond the sweep extreme / OB + 0.2 ATR buffer · targets = opposing liquidity (swings, PDH/PDL, equal levels), else 1R/2R/3R.
Not built yet (shown honestly): Inducement, Mitigation block.
"""
import numpy as np
import pandas as pd

CFG = {"k": 2, "eq_tol": 0.0006, "sweep_win": 2, "trap_win": 3, "disp_atr": 1.5, "disp_body": 0.6, "mss_win": 12, "retest_win": 12,
       "buffer_atr": 0.2, "void_atr": 1.0, "lookback_sweep": 30, "orb_bars": 3, "fresh_bars": 2}
PATTERNS = ["BSL sweep", "SSL sweep", "BOS", "CHOCH", "MSS", "FVG", "IFVG", "Bullish OB", "Bearish OB", "Breaker", "Equal highs", "Equal lows",
            "ORB break", "VWAP reclaim", "VWAP rejection", "Displacement", "Premium / Discount", "PDH/PDL sweep", "PWH/PWL sweep",
            "Failed breakout", "Liquidity void"]
NOT_BUILT = ["Inducement", "Mitigation block"]


def atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=3).mean().bfill()


def swings(df, k=CFG["k"]):
    """→ list of {i, conf, kind 'H'/'L', price, ts}. conf = index of the bar on which the swing becomes known."""
    H, L = df["high"].values, df["low"].values
    out = []
    for i in range(k, len(df) - k):
        if H[i] > max(H[i - k:i]) and H[i] >= max(H[i + 1:i + k + 1]):
            out.append({"i": i, "conf": i + k, "kind": "H", "price": float(H[i]), "ts": str(df.index[i])[:16]})
        if L[i] < min(L[i - k:i]) and L[i] <= min(L[i + 1:i + k + 1]):
            out.append({"i": i, "conf": i + k, "kind": "L", "price": float(L[i]), "ts": str(df.index[i])[:16]})
    out.sort(key=lambda s: (s["conf"], s["i"]))
    lh = ll = None
    for s in out:
        if s["kind"] == "H":
            s["label"] = "HH" if lh is not None and s["price"] > lh else "LH" if lh is not None else "H"
            lh = s["price"]
        else:
            s["label"] = "HL" if ll is not None and s["price"] > ll else "LL" if ll is not None else "L"
            ll = s["price"]
    return out


def vwap(df):
    v = df["volume"].astype(float)
    if v.sum() <= 0:
        return None
    tp = (df["high"] + df["low"] + df["close"]) / 3
    day = pd.Series(df.index.date, index=df.index)
    return (tp * v).groupby(day).cumsum() / v.groupby(day).cumsum().replace(0, np.nan)


def analyse(df, levels=None, sym=None):
    """Walk closed bars in time order → events, zones, structure, liquidity pools. df must contain CLOSED candles only."""
    if df is None or len(df) < 25:
        return None
    df = df.copy()
    O, H, L, C = (df[c].astype(float).values for c in ("open", "high", "low", "close"))
    V = df["volume"].astype(float).values
    A = atr(df).values
    n = len(df)
    SW = swings(df)
    vw = vwap(df)
    VW = vw.values if vw is not None else None
    vavg = pd.Series(V).rolling(20, min_periods=5).mean().values
    days = df.index.date
    ev, zones = [], []
    trend, last_break = None, {}
    pools = []                                            # {price, kind 'H'/'L', src, from_i, swept}
    lv = dict(levels or {})
    t_day = days[-1]
    prev = df[days < t_day]
    if len(prev):
        pd_ = prev[prev.index.date == prev.index.date[-1]]
        lv.setdefault("PDH", float(pd_["high"].max()))
        lv.setdefault("PDL", float(pd_["low"].min()))
    today_i = int(np.argmax(days == t_day))
    for k_, src in (("PDH", "PDH"), ("PWH", "PWH")):
        if lv.get(k_):
            pools.append({"price": float(lv[k_]), "kind": "H", "src": src, "from_i": today_i, "swept": False})
    for k_, src in (("PDL", "PDL"), ("PWL", "PWL")):
        if lv.get(k_):
            pools.append({"price": float(lv[k_]), "kind": "L", "src": src, "from_i": today_i, "swept": False})
    fvgs, obs = [], []
    sw_by_conf = {}
    for s in SW:
        sw_by_conf.setdefault(s["conf"], []).append(s)
    known_h, known_l = [], []
    pend_sweep, pend_trap = [], []
    orb = None

    def add(i, name, side, **kw):
        ev.append({"i": i, "ts": str(df.index[i])[:16], "name": name, "side": side, **kw})

    for i in range(n):
        # 1. swings confirmed on this bar become known
        for s in sw_by_conf.get(i, []):
            (known_h if s["kind"] == "H" else known_l).append(s)
            same = known_h if s["kind"] == "H" else known_l
            eq = [x for x in same[:-1][-6:] if abs(x["price"] - s["price"]) / s["price"] <= CFG["eq_tol"]]
            src = "swing"
            if eq:
                src = "equal highs" if s["kind"] == "H" else "equal lows"
                add(i, "Equal highs" if s["kind"] == "H" else "Equal lows", "BEAR" if s["kind"] == "H" else "BULL", level=s["price"])
            pools.append({"price": s["price"], "kind": s["kind"], "src": src, "from_i": i, "swept": False, "label": s.get("label")})
        if i == 0:
            continue
        a = A[i] or (H[i] - L[i]) or 1e-9
        body = abs(C[i] - O[i])
        rng = (H[i] - L[i]) or 1e-9
        disp = bool(body >= CFG["disp_atr"] * a and body / rng >= CFG["disp_body"])
        vr = round(float(V[i] / vavg[i]), 2) if vavg[i] and vavg[i] > 0 else None
        if disp:
            add(i, "Displacement", "BULL" if C[i] > O[i] else "BEAR", level=C[i], vr=vr)
        # 2. BOS / CHOCH on a close beyond the last known swing
        lh = known_h[-1] if known_h else None
        ll = known_l[-1] if known_l else None
        if lh and C[i] > lh["price"] and last_break.get("H") != lh["i"]:
            last_break["H"] = lh["i"]
            nm = "BOS" if trend in (None, "UP") else "CHOCH"
            mss = nm == "CHOCH" and any(e["name"] == "SSL sweep" and i - e["i"] <= CFG["mss_win"] for e in ev[-40:])
            add(i, "MSS" if mss else nm, "BULL", level=lh["price"], disp=disp, from_i=lh["i"])
            trend = "UP"
            if disp or mss or nm == "BOS":
                j = next((j for j in range(i, max(i - 8, 0), -1) if C[j] < O[j]), None)
                if j is not None:
                    obs.append({"side": "BULL", "top": float(max(O[j], C[j])), "bot": float(L[j]), "i": j, "made": i, "touch": 0, "broken": None})
        if ll and C[i] < ll["price"] and last_break.get("L") != ll["i"]:
            last_break["L"] = ll["i"]
            nm = "BOS" if trend in (None, "DOWN") else "CHOCH"
            mss = nm == "CHOCH" and any(e["name"] == "BSL sweep" and i - e["i"] <= CFG["mss_win"] for e in ev[-40:])
            add(i, "MSS" if mss else nm, "BEAR", level=ll["price"], disp=disp, from_i=ll["i"])
            trend = "DOWN"
            if disp or mss or nm == "BOS":
                j = next((j for j in range(i, max(i - 8, 0), -1) if C[j] > O[j]), None)
                if j is not None:
                    obs.append({"side": "BEAR", "top": float(H[j]), "bot": float(min(O[j], C[j])), "i": j, "made": i, "touch": 0, "broken": None})
        # 3. liquidity sweeps / traps
        for p in pools:
            if p["swept"] or p["from_i"] >= i:
                continue
            if p["kind"] == "H" and H[i] > p["price"]:
                if C[i] > p["price"]:
                    pend_trap.append((i, p))
                pend_sweep.append((i, p))
                p["swept"] = True
            elif p["kind"] == "L" and L[i] < p["price"]:
                if C[i] < p["price"]:
                    pend_trap.append((i, p))
                pend_sweep.append((i, p))
                p["swept"] = True
        keep = []
        for (j, p) in pend_sweep:
            back = (C[i] < p["price"]) if p["kind"] == "H" else (C[i] > p["price"])
            if back and all((C[x] <= p["price"]) if p["kind"] == "H" else (C[x] >= p["price"]) for x in range(j, i)):
                ext = float(max(H[j:i + 1])) if p["kind"] == "H" else float(min(L[j:i + 1]))
                nm = "BSL sweep" if p["kind"] == "H" else "SSL sweep"
                add(i, nm, "BEAR" if p["kind"] == "H" else "BULL", level=p["price"], src=p["src"], ext=ext, start=j, vr=vr)
                if p["src"] in ("PDH", "PDL", "PWH", "PWL"):
                    add(i, ("PDH/PDL sweep" if p["src"][:2] == "PD" else "PWH/PWL sweep"), "BEAR" if p["kind"] == "H" else "BULL", level=p["price"], src=p["src"])
            elif i - j < CFG["sweep_win"] and not back:
                keep.append((j, p))
        pend_sweep = keep
        keep = []
        for (j, p) in pend_trap:
            back = (C[i] < p["price"]) if p["kind"] == "H" else (C[i] > p["price"])
            if i > j and back:
                add(i, "Failed breakout", "BEAR" if p["kind"] == "H" else "BULL", level=p["price"], src=p["src"],
                    ext=float(max(H[j:i + 1])) if p["kind"] == "H" else float(min(L[j:i + 1])), start=j, trap="bull trap" if p["kind"] == "H" else "bear trap")
            elif i - j < CFG["trap_win"]:
                keep.append((j, p))
        pend_trap = keep
        # 4. FVG (confirmed when candle i closes)
        if i >= 2:
            if L[i] > H[i - 2]:
                f = {"side": "BULL", "top": float(L[i]), "bot": float(H[i - 2]), "i": i - 1, "made": i, "filled": None, "touch": 0}
                fvgs.append(f)
                add(i, "Liquidity void" if f["top"] - f["bot"] >= CFG["void_atr"] * a else "FVG", "BULL", top=f["top"], bot=f["bot"])
            if H[i] < L[i - 2]:
                f = {"side": "BEAR", "top": float(L[i - 2]), "bot": float(H[i]), "i": i - 1, "made": i, "filled": None, "touch": 0}
                fvgs.append(f)
                add(i, "Liquidity void" if f["top"] - f["bot"] >= CFG["void_atr"] * a else "FVG", "BEAR", top=f["top"], bot=f["bot"])
        for f in fvgs:
            if f["filled"] is not None or f["made"] >= i:
                continue
            if f["side"] == "BULL":
                if L[i] <= f["top"]:
                    f["touch"] += 1
                if C[i] < f["bot"]:
                    f["filled"] = i
                    add(i, "IFVG", "BEAR", top=f["top"], bot=f["bot"])
            else:
                if H[i] >= f["bot"]:
                    f["touch"] += 1
                if C[i] > f["top"]:
                    f["filled"] = i
                    add(i, "IFVG", "BULL", top=f["top"], bot=f["bot"])
        for o in obs:
            if o["broken"] is not None or o["made"] >= i:
                continue
            if (o["side"] == "BULL" and L[i] <= o["top"]) or (o["side"] == "BEAR" and H[i] >= o["bot"]):
                o["touch"] += 1
            if (o["side"] == "BULL" and C[i] < o["bot"]) or (o["side"] == "BEAR" and C[i] > o["top"]):
                o["broken"] = i
                add(i, "Breaker", "BEAR" if o["side"] == "BULL" else "BULL", top=o["top"], bot=o["bot"])
        # 5. ORB + VWAP (today)
        if days[i] == t_day:
            ti = i - today_i
            if ti == CFG["orb_bars"] - 1:
                orb = {"high": float(max(H[today_i:i + 1])), "low": float(min(L[today_i:i + 1])), "broken": None}
            elif orb and orb["broken"] is None and ti >= CFG["orb_bars"]:
                if C[i] > orb["high"]:
                    orb["broken"] = "UP"
                    add(i, "ORB break", "BULL", level=orb["high"])
                elif C[i] < orb["low"]:
                    orb["broken"] = "DOWN"
                    add(i, "ORB break", "BEAR", level=orb["low"])
            if VW is not None and i >= today_i + 3 and not np.isnan(VW[i]):
                below3 = all(C[x] < VW[x] for x in range(i - 3, i))
                above3 = all(C[x] > VW[x] for x in range(i - 3, i))
                if below3 and C[i] > VW[i]:
                    add(i, "VWAP reclaim", "BULL", level=float(VW[i]))
                if above3 and C[i] < VW[i] and H[i] >= VW[i]:
                    add(i, "VWAP rejection", "BEAR", level=float(VW[i]))
    for o in obs:
        add(o["made"], "Bullish OB" if o["side"] == "BULL" else "Bearish OB", o["side"], top=o["top"], bot=o["bot"])
    ev.sort(key=lambda e: e["i"])
    lh = known_h[-1] if known_h else None
    ll = known_l[-1] if known_l else None
    pdz = None
    if lh and ll and lh["price"] > ll["price"]:
        mid = (lh["price"] + ll["price"]) / 2
        pdz = {"hi": lh["price"], "lo": ll["price"], "mid": mid, "where": "PREMIUM" if C[-1] > mid else "DISCOUNT"}
    return {"df": df, "events": ev, "swings": SW, "fvgs": fvgs, "obs": obs, "pools": pools, "trend": trend, "atr": float(A[-1]),
            "orb": orb, "vwap": (float(VW[-1]) if VW is not None and not np.isnan(VW[-1]) else None), "pdz": pdz, "levels": lv, "n": n}


def _targets(an, side, entry, risk):
    """Opposing liquidity beyond entry (unswept pools), nearest first; fill missing with R multiples."""
    want = "L" if side == "PE" else "H"
    lv = sorted({round(p["price"], 2): p["src"] for p in an["pools"] if p["kind"] == want and not p["swept"]
                 and ((p["price"] < entry - 0.5 * risk) if side == "PE" else (p["price"] > entry + 0.5 * risk))}.items(),
                key=lambda x: x[0], reverse=(side == "PE"))
    T, src = [], []
    for k in (1, 2, 3):
        w = entry - k * risk if side == "PE" else entry + k * risk
        cand = [(p, s) for p, s in lv if (p <= entry - (k - 0.4) * risk if side == "PE" else p >= entry + (k - 0.4) * risk)
                and (not T or (p < T[-1] if side == "PE" else p > T[-1]))]
        if cand:
            T.append(cand[0][0])
            src.append(cand[0][1] + " liquidity")
        else:
            T.append(round(w, 2))
            src.append(f"{k}R")
    return T, src


def setups(an, sym, now=None):
    """Sweep-reversal + BOS/OB setups with state. Uses only the analysed closed bars."""
    if not an:
        return []
    df, ev = an["df"], an["events"]
    n = an["n"]
    H, L, C, O = (df[c].astype(float).values for c in ("high", "low", "close", "open"))
    A = an["atr"]
    out = []
    # SWEEP REVERSAL
    day0 = df.index[-1].date()
    tday = lambda i: df.index[i].date() == day0          # v124: only TODAY's setups (yesterday's 15:10 setup is not a trade today)
    for s in [e for e in ev if e["name"] in ("BSL sweep", "SSL sweep") and n - 1 - e["i"] <= CFG["lookback_sweep"] and tday(e["i"])]:
        bear = s["name"] == "BSL sweep"
        side = "PE" if bear else "CE"
        mss = next((e for e in ev if e["i"] > s["i"] and e["i"] - s["i"] <= CFG["mss_win"] and e["name"] in ("MSS", "CHOCH", "BOS")
                    and e["side"] == ("BEAR" if bear else "BULL")), None)
        st = {"kind": "Sweep reversal", "side": side, "symbol": sym, "sweep": s, "mss": mss, "events": [s] + ([mss] if mss else [])}
        sl = round(s["ext"] + CFG["buffer_atr"] * A, 2) if bear else round(s["ext"] - CFG["buffer_atr"] * A, 2)
        st["sl"] = sl
        inval = next((i for i in range(s["i"] + 1, n) if (C[i] > s["ext"] if bear else C[i] < s["ext"])), None)
        if not mss:
            st["state"] = "INVALIDATED" if inval is not None else ("PATTERN DETECTED" if n - 1 - s["i"] <= CFG["mss_win"] else "EXPIRED")
            st["why"] = "sweep seen — waiting for MSS / CHOCH (a sweep alone is not a trade)" if st["state"] == "PATTERN DETECTED" else \
                "closed beyond the sweep extreme" if st["state"] == "INVALIDATED" else "no MSS within 12 bars"
            out.append(st)
            continue
        z = next((f for f in an["fvgs"] if f["side"] == ("BEAR" if bear else "BULL") and s["i"] - 1 <= f["made"] <= mss["i"]), None)
        zk = "FVG"
        if not z:
            z = next((o for o in an["obs"] if o["side"] == ("BEAR" if bear else "BULL") and o["made"] == mss["i"]), None)
            zk = "order block"
        if not z:
            mid = (s["ext"] + C[mss["i"]]) / 2
            z = {"top": max(mid, C[mss["i"]]), "bot": min(mid, C[mss["i"]])}
            zk = "50% of the MSS leg"
        st["zone"], st["zone_kind"] = {"top": round(z["top"], 2), "bot": round(z["bot"], 2)}, zk
        _confirm(st, an, mss["i"], bear, inval)
        out.append(st)
    # BOS + ORDER BLOCK continuation
    for o in [o for o in an["obs"] if n - 1 - o["made"] <= CFG["lookback_sweep"] and tday(o["made"])]:
        b = next((e for e in ev if e["i"] == o["made"] and e["name"] == "BOS"), None)
        if not b:
            continue
        bear = o["side"] == "BEAR"
        st = {"kind": "BOS + order block", "side": "PE" if bear else "CE", "symbol": sym, "bos": b, "events": [b],
              "zone": {"top": round(o["top"], 2), "bot": round(o["bot"], 2)}, "zone_kind": "order block",
              "sl": round(o["top"] + CFG["buffer_atr"] * A, 2) if bear else round(o["bot"] - CFG["buffer_atr"] * A, 2)}
        inval = next((i for i in range(o["made"] + 1, n) if (C[i] > o["top"] if bear else C[i] < o["bot"])), None)
        if o["touch"] > 2:
            st.update(state="INVALIDATED", why=f"order block tested {o['touch']}× — stale")
        else:
            _confirm(st, an, o["made"], bear, inval)
        out.append(st)
    for st in out:
        if st.get("entry") and st.get("sl"):
            r = abs(st["entry"] - st["sl"])
            st["targets"], st["t_src"] = _targets(an, st["side"], st["entry"], r)
            st["rr"] = round(abs(st["targets"][1] - st["entry"]) / r, 2) if r else None
        last = max([e["i"] for e in st["events"] if e])
        st["id"] = f"{sym}|{st['kind']}|{st['side']}|{str(df.index[st['events'][0]['i']])[:16]}"
        st["ts"] = str(df.index[last])[:16]
        st["fresh"] = st.get("conf_i") is not None and n - 1 - st["conf_i"] <= CFG["fresh_bars"]
    order = {"ENTRY CONFIRMED": 0, "WAITING FOR CONFIRMATION": 1, "PATTERN DETECTED": 2, "TARGET HIT": 3, "STOPLOSS HIT": 4, "EXPIRED": 5, "INVALIDATED": 6}
    out.sort(key=lambda s: (order.get(s["state"], 9), -(s.get("conf_i") or s["events"][0]["i"])))
    seen, res = set(), []
    for s in out:
        if s["id"] in seen:
            continue
        seen.add(s["id"])
        res.append(s)
    return res


def _confirm(st, an, start, bear, inval):
    """After MSS/BOS at `start`: wait for a retest of the zone + a rejection close (closed candles only)."""
    df = an["df"]
    H, L, C, O = (df[c].astype(float).values for c in ("high", "low", "close", "open"))
    n = an["n"]
    z = st["zone"]
    for i in range(start + 1, min(n, start + 1 + CFG["retest_win"])):
        if inval is not None and i >= inval:
            st.update(state="INVALIDATED", why="closed beyond the invalidation level before entry")
            return
        touched = (H[i] >= z["bot"]) if bear else (L[i] <= z["top"])
        rejected = (C[i] < z["top"] and C[i] < O[i]) if bear else (C[i] > z["bot"] and C[i] > O[i])
        if touched and rejected:
            e = round(C[i], 2)
            if (bear and st["sl"] <= e) or (not bear and st["sl"] >= e):
                st.update(state="INVALIDATED", why="no room between entry and SL")
                return
            st.update(state="ENTRY CONFIRMED", entry=e, conf_i=i, conf_ts=str(df.index[i])[:16],
                      why=f"retest of the {st['zone_kind']} + {'bearish' if bear else 'bullish'} rejection close at {str(df.index[i])[11:16]}")
            _track(st, an, i, bear)
            return
    if n - 1 - start < CFG["retest_win"]:
        st.update(state="WAITING FOR CONFIRMATION", why=f"structure broke — wait for price to retest the {st['zone_kind']} "
                                                         f"{z['bot']:g}–{z['top']:g} and reject it on a 5-min close")
    else:
        st.update(state="EXPIRED", why="no retest within 12 bars — don't chase")


def _track(st, an, i0, bear):
    df = an["df"]
    H, L = df["high"].astype(float).values, df["low"].astype(float).values
    r = abs(st["entry"] - st["sl"])
    T, _ = _targets(an, st["side"], st["entry"], r)
    for i in range(i0 + 1, an["n"]):
        if (H[i] >= st["sl"]) if bear else (L[i] <= st["sl"]):
            st.update(state="STOPLOSS HIT", exit_ts=str(df.index[i])[:16], result_r=-1.0)
            return
        if (L[i] <= T[0]) if bear else (H[i] >= T[0]):
            st.update(state="TARGET HIT", exit_ts=str(df.index[i])[:16], result_r=round(abs(T[0] - st["entry"]) / r, 2))
            return


def mtf(df5):
    """1H / 15m / 5m bias from resampled CLOSED bars (a resampled bar is only used once all its 5-min parts closed)."""
    out = {}
    for lab, rule in (("5m", None), ("15m", "15min"), ("1H", "60min")):
        d = df5 if rule is None else df5.resample(rule, origin="start_day", offset="15min").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        if rule is not None and len(d):
            last_end = d.index[-1] + pd.Timedelta(rule)
            if df5.index[-1] + pd.Timedelta(minutes=5) < last_end:
                d = d.iloc[:-1]                           # incomplete higher-TF bar dropped
        an = analyse(d) if len(d) >= 30 else None
        out[lab] = (an or {}).get("trend") or "RANGE"
    return out


def score(st, an, m, q=None, oi=None, sec_pct=None, event=False):
    """Sniper weights (15/20/20/15/10/15/5). None = no data (scored 0, listed)."""
    bull = st["side"] == "CE"
    want = "UP" if bull else "DOWN"
    P, miss = {}, []
    tf = sum(7 for k in ("15m", "1H") if m.get(k) == want)
    P["trend_sector"] = min(15, tf + (1 if sec_pct is not None and (sec_pct > 0) == bull else 0))
    s = st.get("sweep")
    liq = 0
    if s:
        liq += 10 if s.get("src") in ("PDH", "PDL", "PWH", "PWL", "equal highs", "equal lows") else 6
    if st.get("mss"):
        liq += 6 + (2 if st["mss"].get("disp") else 0)
    if st.get("bos"):
        liq += 8 + (4 if st["bos"].get("disp") else 0)
    if st.get("zone_kind") == "FVG":
        liq += 2
    P["structure"] = min(20, liq)
    vr = (s or {}).get("vr") or (st.get("mss") or st.get("bos") or {}).get("vr")
    if vr is None and oi is None:
        P["vol_oi"] = None
        miss.append("Volume + OI")
    else:
        P["vol_oi"] = (10 if vr and vr >= 1.5 else 5 if vr and vr >= 1 else 0) + (10 if oi == ("Long Built Up" if bull else "Short Built Up") else
                                                                                   5 if oi == ("Short Covering" if bull else "Long Unwinding") else 0)
    vw = an.get("vwap")
    c = float(an["df"]["close"].iloc[-1])
    P["vwap_mtf"] = (7 if vw and (c >= vw) == bull else 0) + (8 if m.get("15m") == want else 0)
    if vw is None:
        miss.append("VWAP (index spot has no volume)")
    P["opt_liq"] = None
    rr = st.get("rr") or 0
    ext = 5 if st.get("entry") and abs(c - st["entry"]) <= abs(st["entry"] - st["sl"]) * 0.5 else 0
    P["entry_rr"] = (10 if rr >= 2 else 6 if rr >= 1.5 else 2 if rr >= 1 else 0) + ext
    P["event"] = 0 if event else 5
    return P, miss


def option_plan(st, o, lot, prem, delta=0.5, cost=60, spread=None):
    """Underlying plan → option premium plan via delta (MODEL estimate, labelled). Risk cap ₹2,500 incl. costs."""
    if not (prem and lot and st.get("entry")):
        return None, "missing option quote"
    d = abs(delta or 0.5)
    dist = abs(st["entry"] - st["sl"])
    sl_p = round(max(prem - d * dist, prem * 0.4), 2)
    T = [round(prem + d * abs(t - st["entry"]), 2) for t in st.get("targets") or []]
    slip = prem * max(0.002, (spread or 0) / 200)
    risk = round((prem - sl_p + 2 * slip) * lot + cost)
    why = None
    if spread is not None and spread > 5:
        why = f"spread {spread}% too wide"
    elif risk > 2500:
        why = f"1-lot risk ₹{risk:,} incl. costs > ₹2,500"
    return {"entry": round(prem, 2), "zone": [round(prem * 0.99, 2), round(prem * 1.02, 2)], "sl": sl_p, "targets": T, "risk": risk, "lot": lot,
            "delta": d, "model": f"premium ≈ LTP ± Δ{d:.2f} × underlying move (estimate)"}, why


def chart_payload(an, sts, bars=90):
    """Compact chart data for the UI: candles + boxes (sweep / SL / target / FVG / OB) + labels, trimmed to the last `bars` candles."""
    df = an["df"].tail(bars)
    off = an["n"] - len(df)
    K = [[str(i)[5:16], round(float(r["open"]), 2), round(float(r["high"]), 2), round(float(r["low"]), 2), round(float(r["close"]), 2), int(r["volume"])]
         for i, r in df.iterrows()]
    lab = []
    for s in an["swings"]:
        if s["i"] >= off and s["conf"] < an["n"]:
            lab.append({"i": s["i"] - off, "y": s["price"], "t": s["label"], "k": s["kind"]})
    evs = []
    for e in an["events"]:
        if e["i"] >= off and e["name"] in ("BOS", "CHOCH", "MSS", "BSL sweep", "SSL sweep"):
            evs.append({"i": e["i"] - off, "name": e["name"], "side": e["side"], "y": e.get("level"), "from": (e.get("from_i") or e.get("start") or e["i"]) - off})
    zones = []
    for f in an["fvgs"]:
        if f["made"] >= off:
            zones.append({"k": "FVG", "side": f["side"], "x0": f["i"] - off, "x1": (f["filled"] - off) if f["filled"] else len(K) - 1, "top": f["top"], "bot": f["bot"], "dead": f["filled"] is not None})
    for o in an["obs"]:
        if o["made"] >= off:
            zones.append({"k": "OB", "side": o["side"], "x0": max(0, o["i"] - off), "x1": (o["broken"] - off) if o["broken"] else len(K) - 1, "top": o["top"], "bot": o["bot"], "dead": o["broken"] is not None})
    pos = []
    for s in sts:
        if s.get("entry") and s.get("targets") and s.get("conf_i") is not None and s["conf_i"] >= off:
            sw = s.get("sweep")
            pos.append({"id": s["id"], "side": s["side"], "x0": s["conf_i"] - off, "entry": s["entry"], "sl": s["sl"], "tp": s["targets"][1], "t1": s["targets"][0],
                        "state": s["state"], "sweep": {"x0": sw["start"] - off, "x1": sw["i"] - off, "top": max(sw["ext"], sw["level"]), "bot": min(sw["ext"], sw["level"])}
                        if sw and sw.get("start") is not None and sw["start"] >= off else None})
    lv = {k: v for k, v in an["levels"].items() if k in ("PDH", "PDL", "PWH", "PWL") and v}
    return {"candles": K, "labels": lab[-14:], "events": evs[-6:], "zones": [z for z in zones if not z["dead"] and z["k"] == "FVG"][-3:] + [z for z in zones if not z["dead"] and z["k"] == "OB"][-2:]
                 + [z for z in zones if z["dead"]][-1:],
            "pos": pos[-2:], "levels": lv, "vwap": an.get("vwap"), "orb": an.get("orb")}


# ───────────────────────── live runner + immutable record ─────────────────────────
STATE = {"time": None, "rows": [], "setups": [], "charts": {}, "rejected": [], "overview": [], "err": None, "scanned": 0}
SRC, KIND = "📐 SMC/ICT Sniper", "SMC"


def run(frames, now, ctx, ag=None, inst=None, store=None, lock=None, add_calls=None):
    """frames: {symbol: 5-min closed DataFrame}. ctx: levels, live_q, oi, sectors, sector_of, results, market_open, stale.
    → STATE (pattern heatmap rows, setups with option plan, chart payloads, rejection log) + new confirmed setups recorded once."""
    now = pd.Timestamp(now)
    rows, allst, charts, rej, ov = [], [], {}, [], []
    for sym, df in frames.items():
        try:
            an = analyse(df, (ctx.get("levels") or {}).get(sym), sym)
            if not an:
                continue
            m = mtf(df)
            sts = setups(an, sym, now)
            q = (ctx.get("live_q") or {}).get(sym) or {}
            for e in an["events"][-40:]:
                rows.append({"symbol": sym, "pattern": e["name"], "side": e["side"], "tf": "5m", "ts": e["ts"], "level": e.get("level") or e.get("top"),
                             "trend": an["trend"], "fresh": an["n"] - 1 - e["i"] <= 2})
            ov.append({"symbol": sym, "ltp": q.get("ltp") or float(df["close"].iloc[-1]), "mtf": m, "trend": an["trend"],
                       "align": "ALIGNED" if m["15m"] == m["1H"] == m["5m"] else "CONFLICT" if {"UP", "DOWN"} <= set(m.values()) else "MIXED",
                       "pdz": (an.get("pdz") or {}).get("where"), "vwap": an.get("vwap"), "last_bar": str(df.index[-1])[:16],
                       "pools": sorted([{"price": round(p["price"], 2), "src": p["src"], "kind": p["kind"]} for p in an["pools"] if not p["swept"]],
                                       key=lambda p: abs(p["price"] - float(df["close"].iloc[-1])))[:6]})
            for st in sts:
                sec = (ctx.get("sector_of") or {}).get(sym)
                P, miss = score(st, an, m, q, (ctx.get("oi") or {}).get(sym), (ctx.get("sectors") or {}).get(sec),
                                any(r.get("symbol") == sym and 0 <= (r.get("days") if r.get("days") is not None else 9) <= 1 for r in ctx.get("results") or []))
                st.update(parts=P, missing=miss, score=sum(v or 0 for v in P.values()), mtf=m,
                          counter=(st["side"] == "CE" and m.get("1H") == "DOWN") or (st["side"] == "PE" and m.get("1H") == "UP"))
                veto = []
                if ctx.get("stale"):
                    veto.append("data stale")
                if not ctx.get("market_open"):
                    veto.append("market closed — no live entry")
                if st["state"] == "ENTRY CONFIRMED" and not st.get("fresh"):
                    veto.append("confirmed earlier — entry is old, don't chase")
                st["veto"] = veto
                allst.append(st)
            charts[sym] = chart_payload(an, sts)
        except Exception as e:
            STATE["err"] = f"{sym}: {str(e)[:80]}"
    # v124: strike to watch for every live setup (no quote needed) — so a WAIT card already says which CE / PE to buy if it confirms
    if inst is not None:
        try:
            from .bigvol import strike_for
            for s in allst:
                if s["state"] in ("PATTERN DETECTED", "WAITING FOR CONFIRMATION", "ENTRY CONFIRMED"):
                    z = s.get("zone") or {}
                    ref = s.get("entry") or ((z["top"] + z["bot"]) / 2 if z else None) or float(frames[s["symbol"]]["close"].iloc[-1])
                    o = strike_for(inst, s["symbol"], s["side"], ref)
                    if o:
                        s["strike_watch"] = o
        except Exception as e:
            STATE["err"] = f"strike: {str(e)[:80]}"
    # option plan for live confirmed setups (stocks + indices) — one quote call
    live = [s for s in allst if s["state"] == "ENTRY CONFIRMED" and not s["veto"]]
    if live and ag is not None and inst is not None:
        try:
            from .bigvol import strike_for
            picks = {}
            for s in live:
                o = strike_for(inst, s["symbol"], s["side"], s["entry"])
                if o:
                    picks[s["id"]] = o
            toks = {}
            for o in picks.values():
                ex = "BFO" if str(o.get("contract", "")).startswith(("SENSEX", "BANKEX")) else "NFO"
                o["exch"] = ex
            rowsx = {o["contract"]: o for o in picks.values()}
            tokmap = {}
            for sym in {s["symbol"] for s in live}:
                for r in (inst.get("opts") or {}).get(sym) or []:
                    if r[1] in rowsx:
                        tokmap[r[1]] = (r[0], r[6])
            for c_, (t_, ex) in tokmap.items():
                toks.setdefault(ex, []).append(t_)
            qs = ag.quotes(toks) if toks else {}
            for s in live:
                o = picks.get(s["id"])
                if not o or o["contract"] not in tokmap:
                    s["veto"].append("no listed option strike found")
                    continue
                t_, ex = tokmap[o["contract"]]
                qq = qs.get(str(t_)) or {}
                ltp = float(qq.get("ltp") or 0)
                dp = qq.get("depth") or {}
                bid = next((float(x.get("price") or 0) for x in dp.get("buy") or [] if float(x.get("price") or 0) > 0), None)
                ask = next((float(x.get("price") or 0) for x in dp.get("sell") or [] if float(x.get("price") or 0) > 0), None)
                spr = round((ask - bid) / ((ask + bid) / 2) * 100, 2) if bid and ask else None
                plan, why = option_plan(s, o, o.get("lot"), ltp, 0.5, 60, spr)
                s["option"] = dict(o, token=t_, exch=ex, ltp=ltp or None, spread=spr)
                s["opt_plan"] = plan
                s["parts"]["opt_liq"] = None if spr is None else (10 if spr <= 1.5 else 6 if spr <= 3 else 2 if spr <= 5 else 0)
                s["score"] = sum(v or 0 for v in s["parts"].values())
                if why:
                    s["veto"].append(why)
                if not ltp:
                    s["veto"].append("missing option quote")
        except Exception as e:
            STATE["err"] = f"option plan: {str(e)[:80]}"
    for s in allst:
        s["band"] = "ELITE" if s["score"] >= 90 else "STRONG WATCH" if s["score"] >= 80 else "WAIT" if s["score"] >= 70 else "REJECT"
        s["decision"] = ("TAKE" if s["state"] == "ENTRY CONFIRMED" and not s["veto"] and s["score"] >= 70 else
                         "WAIT" if s["state"] in ("WAITING FOR CONFIRMATION", "PATTERN DETECTED") else "DON'T TAKE")
        s["explain"] = explain(s)
        if s["decision"] == "DON'T TAKE" and s["state"] in ("ENTRY CONFIRMED", "INVALIDATED", "EXPIRED"):
            rej.append({"symbol": s["symbol"], "kind": s["kind"], "side": s["side"], "ts": s["ts"], "state": s["state"],
                        "why": "; ".join(s["veto"]) or s.get("why") or (f"score {s['score']} < 70" if s["score"] < 70 else "")})
    # immutable record (first time a setup is ENTRY CONFIRMED) + outcome fields only
    if store is not None and lock is not None:
        try:
            with lock:
                d = store.load()
                R = d.setdefault("smc", {})
                for s in allst:
                    if s["state"] in ("ENTRY CONFIRMED", "TARGET HIT", "STOPLOSS HIT") and s.get("entry"):
                        if s["id"] not in R:
                            R[s["id"]] = {"id": s["id"], "symbol": s["symbol"], "kind": s["kind"], "side": s["side"], "tf": "5m",
                                          "pattern": (s.get("sweep") or s.get("bos") or {}).get("name"), "conf_ts": s.get("conf_ts"),
                                          "entry": s["entry"], "sl": s["sl"], "targets": s.get("targets"), "score": s["score"],
                                          "regime": ctx.get("regime"), "recorded": str(now)[:16], "model": "smc-v1", "outcome": None}
                            store.dirty = True
                        rec = R[s["id"]]
                        if rec["outcome"] is None and s["state"] in ("TARGET HIT", "STOPLOSS HIT"):
                            rec.update(outcome=s["state"], result_r=s.get("result_r"), exit_ts=s.get("exit_ts"))
                            store.dirty = True
                if len(R) > 3000:
                    for k in sorted(R, key=lambda k: R[k]["recorded"])[:len(R) - 3000]:
                        R.pop(k, None)
        except Exception as e:
            STATE["err"] = f"record: {str(e)[:80]}"
    # live paper calls for fresh TAKE setups on stocks (indices are shown, V4 handles index calls)
    if add_calls:
        good = [s for s in allst if s["decision"] == "TAKE" and s.get("fresh") and s["symbol"] not in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY")]
        if good:
            try:
                add_calls(good)
            except Exception as e:
                STATE["err"] = f"calls: {str(e)[:80]}"
    order = {"TAKE": 0, "WAIT": 1, "DON'T TAKE": 2}
    allst.sort(key=lambda s: (order[s["decision"]], -s["score"]))
    slim = [{k: v for k, v in s.items() if k not in ("events",)} for s in allst]
    for s in slim:
        for k in ("sweep", "mss", "bos"):
            if s.get(k):
                s[k] = {kk: s[k].get(kk) for kk in ("name", "ts", "level", "src", "ext", "disp")}
    STATE.update(time=now.strftime("%d %b %H:%M"), rows=sorted(rows, key=lambda r: r["ts"], reverse=True)[:300], setups=slim[:60], charts=charts,
                 rejected=rej[:60], overview=ov, scanned=len(frames), err=STATE.get("err") if STATE.get("err") else None)
    return STATE


def explain(s):
    bull = s["side"] == "CE"
    sw, ms, bo = s.get("sweep"), s.get("mss"), s.get("bos")
    L = []
    if sw:
        L.append(("What formed", f"{sw['name']} — price took the {sw.get('src')} liquidity at {sw.get('level'):g} (wick to {sw.get('ext'):g}) and closed back "
                                 f"{'below' if not bull else 'above'} it at {sw['ts'][11:]}."))
    if bo:
        L.append(("What formed", f"BOS {'up' if bull else 'down'} at {bo['ts'][11:]} — close beyond the last swing {bo.get('level'):g}"
                                 + (" with a displacement candle" if bo.get("disp") else "") + "."))
    if ms:
        L.append(("Why " + ("bullish" if bull else "bearish"), f"{ms['name']} at {ms['ts'][11:]}: close beyond swing {ms.get('level'):g} after the sweep — structure flipped."))
    z = s.get("zone")
    if z:
        L.append(("What confirms entry", f"retest of the {s.get('zone_kind')} {z['bot']:g}–{z['top']:g} and a {'green' if bull else 'red'} rejection close (5-min)."))
    L.append(("Invalidation", f"a 5-min close {'below' if bull else 'above'} {s.get('sl'):g} (beyond the sweep / zone + ATR buffer)."))
    if s.get("targets"):
        L.append(("Targets", " / ".join(f"{t:g} ({src})" for t, src in zip(s["targets"], s.get("t_src") or [])) + f" · R:R at T2 1:{s.get('rr')}"))
    o, p = s.get("option"), s.get("opt_plan")
    if o and p:
        L.append(("Why this strike", f"{o['strike']:g} {s['side']} — nearest listed strike to entry, exp {o['expiry']}, spread {o.get('spread') if o.get('spread') is not None else '–'}%. "
                                     f"Premium plan is a model estimate: {p['model']}."))
    if s.get("counter"):
        L.append(("Risk", "countertrend vs the 1H trend — smaller size, quick T1"))
    if s.get("missing"):
        L.append(("Missing data", ", ".join(s["missing"])))
    L.append(("Decision", f"{s['decision']} — " + ("; ".join(s["veto"]) if s.get("veto") else s.get("why") or "")))
    return L


def performance(store):
    try:
        R = list((store.load().get("smc") or {}).values())
    except Exception:
        return []
    by = {}
    for r in R:
        by.setdefault(f"{r['kind']} · {r['side']}", []).append(r)
    out = []
    for k, L in by.items():
        done = [r for r in L if r.get("outcome")]
        w = [r for r in done if (r.get("result_r") or 0) > 0]
        rs = [r.get("result_r") or 0 for r in done]
        gp, gl = sum(x for x in rs if x > 0), -sum(x for x in rs if x < 0)
        streak = mx = 0
        for r in sorted(done, key=lambda r: r["conf_ts"] or ""):
            streak = streak + 1 if (r.get("result_r") or 0) < 0 else 0
            mx = max(mx, streak)
        out.append({"setup": k, "signals": len(L), "closed": len(done), "wins": len(w), "win": round(len(w) / len(done) * 100) if done else None,
                    "avg_r": round(sum(rs) / len(rs), 2) if rs else None, "pf": round(gp / gl, 2) if gl else None, "streak": mx})
    return sorted(out, key=lambda r: -r["signals"])
