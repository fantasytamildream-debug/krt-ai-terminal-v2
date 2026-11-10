"""🧠 15 CHART ANALYSIS METHODS — ஒவ்வொன்றும் ஒரே 5-min chart-ஐ பார்த்து ⬆ / ⬇ / ↔ vote (−1 … +1) + காரணம்.

Regime-க்கு ஏத்த weight (AI market-ஐ பார்த்து எந்த methods முக்கியம் என்று தேர்வு) × உங்க rating × கத்துக்கிட்ட accuracy
(ஒவ்வொரு method-ன் பழைய votes சரியா / தப்பா → 15+ results ஆனதும் weight தானா மாறும்).
→ Confluence score 0–100 (call பக்கம்) → ✅ TAKE / ⏳ WAIT / ⛔ AVOID.

நேர்மை: Order Flow / Footprint-க்கு tick-by-tick data இல்லை → OHLCV-ல் இருந்து delta *proxy*. Elliott Wave heuristic மட்டும் (low weight).
"""
import numpy as np
import pandas as pd

METHODS = [  # (key, பெயர், உங்க rating)
    ("pa", "Price Action + Market Structure", 9.5), ("smc", "SMC — Smart Money Concepts", 9.3), ("ict", "ICT Concepts", 9.2),
    ("vp", "Volume Profile + Market Profile", 9.1), ("of", "Order Flow + Footprint (proxy)", 9.0), ("vwap", "VWAP + Anchored VWAP", 9.0),
    ("sd", "Supply & Demand", 8.8), ("mtf", "Multi-Timeframe", 8.8), ("liq", "Liquidity Mapping", 8.7), ("wy", "Wyckoff", 8.5),
    ("vsa", "Volume Spread Analysis", 8.4), ("sr", "Support/Resistance + Retest", 8.3), ("ew", "Elliott Wave (heuristic)", 7.8),
    ("fib", "Fibonacci Retracement", 7.7), ("rs", "Relative Strength + Sector", 8.7)]
NAME = {k: n for k, n, _ in METHODS}
RATING = {k: r for k, _, r in METHODS}
REGIME_W = {
    "TRENDING": {"pa": 1.3, "mtf": 1.3, "vwap": 1.2, "rs": 1.2, "sr": 1.1, "smc": 1.0, "of": 1.0, "fib": 1.0, "ict": 0.9, "sd": 0.9, "vsa": 0.9,
                 "liq": 0.8, "vp": 0.8, "wy": 0.7, "ew": 0.6},
    "SIDEWAYS": {"vp": 1.4, "sd": 1.3, "liq": 1.2, "wy": 1.2, "vwap": 1.1, "ict": 1.1, "sr": 1.0, "vsa": 1.0, "smc": 1.0, "of": 1.0, "fib": 1.0,
                 "pa": 0.8, "mtf": 0.7, "rs": 0.7, "ew": 0.5},
    "VOLATILE": {"liq": 1.4, "ict": 1.3, "smc": 1.3, "of": 1.2, "vsa": 1.2, "sd": 1.0, "vwap": 1.0, "pa": 0.9, "sr": 0.9, "vp": 0.9, "mtf": 0.8,
                 "wy": 0.8, "rs": 0.8, "fib": 0.7, "ew": 0.4}}


def _r(v, t, s=1.0):
    return {"vote": float(max(-1.0, min(1.0, v))), "txt": t, "strength": s}


def _today(df):
    d = df.index[-1].date()
    return df[df.index.date == d]


def m_pa(df, a, ctx):
    st = a.get("structure") or {}
    tr = st.get("trend")
    ev = (st.get("events") or [])[-1:] or []
    v = 1 if tr == "UP" else -1 if tr == "DOWN" else 0
    if ev:
        e = ev[0]
        v = 1 if e["side"] == "UP" else -1
        return _r(v, f"{e['type']} @ {e['price']} · structure {tr}")
    labs = " → ".join(x["label"] for x in (st.get("labels") or [])[-4:])
    return _r(v * 0.7, f"Structure {tr} ({labs})")


def m_smc(df, a, ctx):
    st, lq = a.get("structure") or {}, a.get("liquidity") or {}
    px, atr = a["px"], a["atr"] or 1
    v, why = 0.0, []
    for e in (st.get("events") or [])[-1:]:
        v += 0.6 if e["side"] == "UP" else -0.6
        why.append(e["type"])
    for z in lq.get("zones") or []:                                   # order block ≈ unmitigated zone
        if z["lo"] - 0.3 * atr <= px <= z["hi"] + 0.3 * atr:
            v += 0.5 if z["kind"] == "DEMAND" else -0.5
            why.append(f"{'Bullish' if z['kind'] == 'DEMAND' else 'Bearish'} OB {z['lo']}–{z['hi']}")
    for f in (lq.get("fvg") or [])[-1:]:
        v += 0.3 if f["kind"].startswith("BULL") else -0.3
        why.append(f"{f['kind']} {f['lo']}–{f['hi']}")
    return _r(v, " · ".join(why) or "BOS / OB / FVG signal இல்லை")


def m_ict(df, a, ctx):
    lq, tp = a.get("liquidity") or {}, a.get("trap") or {}
    t = df.index[-1].strftime("%H:%M")
    kz = ("09:15" <= t <= "10:30") or ("13:30" <= t <= "15:00")
    v, why = 0.0, [f"{'⏰ Kill zone' if kz else 'Kill zone வெளியே'} ({t})"]
    sw = (lq.get("sweeps") or [])[-1:]
    if sw:
        v += 0.6 if sw[0]["side"] == "UP" else -0.6
        why.append(sw[0]["txt"])
    if tp and tp.get("status") == "CONFIRMED":
        v += 0.6 if tp["side"] == "CE" else -0.6
        why.append(f"{tp['kind']} confirmed")
    px = a["px"]
    for f in (lq.get("fvg") or [])[-2:]:
        if f["lo"] <= px <= f["hi"]:
            v += 0.3 if f["kind"].startswith("BULL") else -0.3
            why.append(f"price {f['kind']}-க்குள் (retrace)")
    return _r(v * (1.0 if kz else 0.6), " · ".join(why))


def volume_profile(d, bins=24):
    lo, hi = float(d["low"].min()), float(d["high"].max())
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    vol = np.zeros(bins)
    for (_, r) in d.iterrows():
        a_ = min(max(0, int(np.searchsorted(edges, r["low"], "right") - 1)), bins - 1)
        b_ = min(bins - 1, max(a_, int(np.searchsorted(edges, r["high"], "right") - 1)))
        vol[a_:b_ + 1] += float(r["volume"]) / (b_ - a_ + 1)
    poc = int(vol.argmax())
    order, acc, tot, ins = np.argsort(-vol), 0.0, vol.sum() or 1, []
    for i in order:
        acc += vol[i]
        ins.append(i)
        if acc >= 0.7 * tot:
            break
    mid = lambda i: (edges[i] + edges[i + 1]) / 2
    return {"poc": round(mid(poc), 2), "vah": round(edges[max(ins) + 1], 2), "val": round(edges[min(ins)], 2)}


def m_vp(df, a, ctx):
    d = _today(df)
    if len(d) < 6:
        d = df.tail(75)
    vp = volume_profile(d)
    if not vp:
        return _r(0, "data குறைவு")
    px = a["px"]
    ib = d.iloc[:12] if len(d) >= 12 else d                          # Initial balance = முதல் 1 மணி நேரம்
    ibh, ibl = float(ib["high"].max()), float(ib["low"].min())
    v, why = 0.0, [f"POC {vp['poc']} · VA {vp['val']}–{vp['vah']}"]
    if px > vp["vah"]:
        v += 0.7
        why.append("Value area-க்கு மேல் (acceptance ⬆)")
    elif px < vp["val"]:
        v -= 0.7
        why.append("Value area-க்கு கீழ் (acceptance ⬇)")
    else:
        v += 0.3 if px < vp["poc"] else -0.3
        why.append("Value-க்குள் → POC நோக்கி mean reversion")
    if len(d) > 12:
        if px > ibh:
            v += 0.4
            why.append(f"IB high {round(ibh, 2)} மேல் range extension")
        elif px < ibl:
            v -= 0.4
            why.append(f"IB low {round(ibl, 2)} கீழ் range extension")
    a["vp"] = {**vp, "ibh": round(ibh, 2), "ibl": round(ibl, 2)}
    return _r(v, " · ".join(why))


def m_of(df, a, ctx):
    d = df.tail(12)
    rng = (d["high"] - d["low"]).replace(0, np.nan)
    delta = (d["volume"] * ((d["close"] - d["open"]) / rng)).fillna(0)
    cum = float(delta.sum())
    tv = float(d["volume"].sum()) or 1
    imb = cum / tv
    last = df.iloc[-1]
    body = abs(last["close"] - last["open"])
    absorb = last["volume"] > 1.8 * df["volume"].tail(21).iloc[:-1].mean() and body < 0.3 * (last["high"] - last["low"] + 1e-9)
    why = [f"12-bar delta proxy {imb * 100:+.0f}% ({'buyers' if imb > 0 else 'sellers'} அதிகம்)"]
    if absorb:
        why.append("⚠ absorption candle (அதிக volume, சின்ன body)")
    return _r(imb * 2.5 * (0.5 if absorb else 1), " · ".join(why) + " — tick data இல்லை, proxy")


def m_vwap(df, a, ctx):
    d = _today(df)
    if len(d) < 3:
        return _r(0, "இன்றைய data குறைவு")
    tp = (d["high"] + d["low"] + d["close"]) / 3
    vw = float((tp * d["volume"]).cumsum().iloc[-1] / max(1, d["volume"].cumsum().iloc[-1]))
    lo_i, hi_i = d["low"].values.argmin(), d["high"].values.argmax()
    seg_l, seg_h = d.iloc[lo_i:], d.iloc[hi_i:]
    av_l = float(((seg_l["high"] + seg_l["low"] + seg_l["close"]) / 3 * seg_l["volume"]).sum() / max(1, seg_l["volume"].sum()))
    av_h = float(((seg_h["high"] + seg_h["low"] + seg_h["close"]) / 3 * seg_h["volume"]).sum() / max(1, seg_h["volume"].sum()))
    px = a["px"]
    v = (0.5 if px > vw else -0.5) + (0.3 if px > av_l else -0.3) + (0.2 if px > av_h else -0.2)
    a["avwap"] = {"vwap": round(vw, 2), "from_low": round(av_l, 2), "from_high": round(av_h, 2)}
    return _r(v, f"VWAP {round(vw, 2)} · AVWAP (day low-ல் இருந்து) {round(av_l, 2)} · (day high-ல் இருந்து) {round(av_h, 2)} — price {'மேல்' if px > vw else 'கீழ்'}")


def m_sd(df, a, ctx):
    px, atr = a["px"], a["atr"] or 1
    zs = (a.get("liquidity") or {}).get("zones") or []
    for z in zs:
        if z["lo"] - 0.2 * atr <= px <= z["hi"] + 0.2 * atr:
            return _r(1 if z["kind"] == "DEMAND" else -1, f"Price {z['kind'].lower()} zone {z['lo']}–{z['hi']}-ல் (fresh)")
    dem = [z for z in zs if z["kind"] == "DEMAND" and z["hi"] < px]
    sup = [z for z in zs if z["kind"] == "SUPPLY" and z["lo"] > px]
    t = (f"கீழே demand {dem[-1]['lo']}–{dem[-1]['hi']}" if dem else "") + (" · " if dem and sup else "") + (f"மேலே supply {sup[0]['lo']}–{sup[0]['hi']}" if sup else "")
    return _r(0, t or "Fresh zone அருகில் இல்லை")


def m_mtf(df, a, ctx):
    m = a.get("mtf") or {}
    tf = m.get("tf") or {}
    up, dn = sum(v == "UP" for v in tf.values()), sum(v == "DOWN" for v in tf.values())
    return _r((up - dn) / 4 + (0.25 if m.get("aligned") == "UP" else -0.25 if m.get("aligned") == "DOWN" else 0),
              " · ".join(f"{k} {'⬆' if v == 'UP' else '⬇' if v == 'DOWN' else '↔'}" for k, v in tf.items()))


def m_liq(df, a, ctx):
    lq = a.get("liquidity") or {}
    px = a["px"]
    eq = lq.get("eq") or []
    above = sorted([e["price"] for e in eq if e["kind"] == "EQH" and e["price"] > px])
    below = sorted([e["price"] for e in eq if e["kind"] == "EQL" and e["price"] < px])
    sw = (lq.get("sweeps") or [])[-1:]
    v = (0.8 if sw[0]["side"] == "UP" else -0.8) if sw else 0
    t = (f"மேலே buy-side liquidity {above[0]}" if above else "மேலே EQH pool இல்லை") + " · " + (f"கீழே sell-side {below[-1]}" if below else "கீழே EQL pool இல்லை")
    if sw:
        t = sw[0]["txt"] + " · " + t
    elif above and not below:
        v = 0.3
    elif below and not above:
        v = -0.3
    return _r(v, t)


def m_wy(df, a, ctx):
    d = df.tail(40)
    if len(d) < 30:
        return _r(0, "data குறைவு")
    rng_h, rng_l = float(d["high"].iloc[:-5].max()), float(d["low"].iloc[:-5].min())
    atr = a["atr"] or 1
    if rng_h - rng_l > 6 * atr:
        return _r(0, "Trading range இல்லை (trend phase)")
    last5 = d.tail(5)
    vbase = float(d["volume"].iloc[:-5].mean()) or 1
    spring = (last5["low"] < rng_l).any() and float(last5["close"].iloc[-1]) > rng_l
    upth = (last5["high"] > rng_h).any() and float(last5["close"].iloc[-1]) < rng_h
    sos = float(last5["close"].iloc[-1]) > rng_h and float(last5["volume"].max()) > 1.5 * vbase
    sow = float(last5["close"].iloc[-1]) < rng_l and float(last5["volume"].max()) > 1.5 * vbase
    prior = a.get("trend_before")
    if spring:
        return _r(0.9, f"Spring — range low {round(rng_l, 2)} கீழ் போய் உள்ளே close (accumulation{' after ⬇' if prior == 'DOWN' else ''})")
    if sos:
        return _r(0.8, f"Sign of Strength — range high {round(rng_h, 2)} மேல் volume-உடன்")
    if upth:
        return _r(-0.9, f"Upthrust — range high {round(rng_h, 2)} மேல் போய் உள்ளே close (distribution)")
    if sow:
        return _r(-0.8, f"Sign of Weakness — range low {round(rng_l, 2)} கீழ் volume-உடன்")
    return _r(0.2 if prior == "DOWN" else -0.2, f"Range {round(rng_l, 2)}–{round(rng_h, 2)} — {'accumulation?' if prior == 'DOWN' else 'distribution?'} confirm இல்லை")


def m_vsa(df, a, ctx):
    d = df.tail(21)
    vb = float(d["volume"].iloc[:-1].mean()) or 1
    sp = (d["high"] - d["low"])
    sb = float(sp.iloc[:-1].mean()) or 1e-9
    r = d.iloc[-1]
    s, vol = float(r["high"] - r["low"]), float(r["volume"])
    cp = (r["close"] - r["low"]) / (s + 1e-9)
    up = r["close"] > r["open"]
    if up and s > 1.3 * sb and vol > 1.5 * vb and cp > 0.7:
        return _r(0.9, "Wide-spread up bar + அதிக volume + high close = demand")
    if not up and s > 1.3 * sb and vol > 1.5 * vb and cp > 0.6:
        return _r(0.7, "Stopping volume — down bar ஆனா high-ல் close (buyers absorb)")
    if not up and s > 1.3 * sb and vol > 1.5 * vb and cp < 0.3:
        return _r(-0.9, "Wide-spread down bar + அதிக volume + low close = supply")
    if up and s < 0.7 * sb and vol < 0.7 * vb:
        return _r(-0.5, "No demand — narrow up bar, குறைந்த volume")
    if not up and s < 0.7 * sb and vol < 0.7 * vb:
        return _r(0.5, "No supply — narrow down bar, குறைந்த volume")
    return _r(0, f"Neutral bar (spread {s / sb:.1f}× · volume {vol / vb:.1f}×)")


def m_sr(df, a, ctx):
    d = df.tail(14)
    atr = a["atr"] or 1
    c = d["close"].values
    for lv in (a.get("sr_up") or []) + (a.get("sr_dn") or []):
        p = lv["price"]
        if (c[:-4] < p).any() and (c[-4:] > p).all() and d["low"].tail(4).min() <= p + 0.35 * atr:
            return _r(1, f"{p} resistance உடைஞ்சு retest ஆகி hold ✅ (role reversal → support)")
        if (c[:-4] > p).any() and (c[-4:] < p).all() and d["high"].tail(4).max() >= p - 0.35 * atr:
            return _r(-1, f"{p} support உடைஞ்சு retest ஆகி reject ✅ (→ resistance)")
    up, dn = a.get("up_level"), a.get("dn_level")
    return _r(0, f"Retest இல்லை · மேலே {up} · கீழே {dn}")


def m_ew(df, a, ctx):
    labs = [x["label"] for x in ((a.get("structure") or {}).get("labels") or [])][-5:]
    s = " ".join(labs)
    if labs[-3:] in (["HL", "HH", "HL"], ["HH", "HL", "HH"]) and labs.count("HH") >= 2:
        return _r(0.5, f"Possible impulse ⬆ (wave 3/5?) — {s} · heuristic, confirm வேணும்", 0.5)
    if labs[-3:] in (["LH", "LL", "LH"], ["LL", "LH", "LL"]) and labs.count("LL") >= 2:
        return _r(-0.5, f"Possible impulse ⬇ (wave 3/5?) — {s} · heuristic", 0.5)
    return _r(0, f"Wave count தெளிவில்லை ({s or '–'})", 0.3)


def m_fib(df, a, ctx):
    f = a.get("fib") or {}
    lv = f.get("levels") or {}
    if not lv:
        return _r(0, "Fib leg இல்லை")
    px = a["px"]
    g1, g2 = lv.get("0.5") or lv.get(0.5), lv.get("0.618") or lv.get(0.618)
    if g1 is None or g2 is None:
        return _r(0, "Fib levels இல்லை")
    lo, hi = min(g1, g2), max(g1, g2)
    last = df.iloc[-1]
    bull = last["close"] > last["open"]
    if f.get("leg") == "UP" and lo * 0.999 <= px <= hi * 1.001:
        return _r(0.9 if bull else 0.4, f"UP leg golden zone {round(lo, 2)}–{round(hi, 2)}-ல் {'bounce candle ✅' if bull else '(bounce காத்திருக்கு)'}")
    if f.get("leg") == "DOWN" and lo * 0.999 <= px <= hi * 1.001:
        return _r(-0.9 if not bull else -0.4, f"DOWN leg golden zone {round(lo, 2)}–{round(hi, 2)}-ல் {'reject candle ✅' if not bull else ''}")
    return _r(0.2 if f.get("leg") == "UP" else -0.2, f"{f.get('leg')} leg · golden zone {round(lo, 2)}–{round(hi, 2)} இல்லை")


def m_rs(df, a, ctx):
    nf = ctx.get("nifty_ret")
    if ctx.get("is_index") or nf is None:
        return _r(0, "Index / NIFTY data இல்லை — RS பொருந்தாது", 0.3)
    c = df["close"].tail(25)
    sret = float(c.iloc[-1] / c.iloc[0] - 1) * 100 if len(c) > 5 else 0
    rs = sret - nf
    v = 1 if rs > 0.5 else -1 if rs < -0.5 else rs
    sec = ctx.get("sector_pct")
    t = f"Stock {sret:+.2f}% vs NIFTY {nf:+.2f}% (2 மணி நேரம்) → RS {rs:+.2f}%"
    if sec is not None:
        v += 0.4 if sec > 0.3 else -0.4 if sec < -0.3 else 0
        t += f" · sector {sec:+.2f}%"
    return _r(v, t)


FN = {"pa": m_pa, "smc": m_smc, "ict": m_ict, "vp": m_vp, "of": m_of, "vwap": m_vwap, "sd": m_sd, "mtf": m_mtf, "liq": m_liq, "wy": m_wy,
      "vsa": m_vsa, "sr": m_sr, "ew": m_ew, "fib": m_fib, "rs": m_rs}


def method_stats(preds):
    """Chart predictions break ஆனதும்: ஒவ்வொரு method-ன் vote அந்த break பக்கமா? → method accuracy (கத்துக்கும் weight)."""
    st = {k: {"n": 0, "ok": 0} for k in FN}
    for p in preds or []:
        br = p.get("broke")
        if br not in ("UP", "DOWN"):
            continue
        for k, v in (p.get("votes") or {}).items():
            if k in st and abs(v) >= 0.25:
                st[k]["n"] += 1
                st[k]["ok"] += int((v > 0) == (br == "UP"))
    for k, x in st.items():
        x["acc"] = round(x["ok"] / x["n"] * 100) if x["n"] else None
        x["mult"] = round(0.5 + x["ok"] / x["n"], 2) if x["n"] >= 15 else 1.0
    return st


def run_all(df, a, side, ctx=None, stats=None):
    ctx, stats = ctx or {}, stats or {}
    reg = ((a.get("regime") or {}).get("kind") or "MIXED").replace("TRENDING UP", "TRENDING").replace("TRENDING DOWN", "TRENDING")
    RW = REGIME_W.get(reg) or {k: 1.0 for k in FN}
    rows, num, den = [], 0.0, 0.0
    want = 1 if side == "CE" else -1
    for k, nm, rt in METHODS:
        try:
            r = FN[k](df, a, ctx)
        except Exception as e:
            r = _r(0, f"பிழை: {str(e)[:40]}", 0)
        w = round(RW.get(k, 1.0) * (rt / 9.0) * (stats.get(k) or {}).get("mult", 1.0) * r.get("strength", 1.0), 2)
        agree = r["vote"] * want
        num += w * agree
        den += w
        rows.append({"key": k, "name": nm, "rating": rt, "vote": round(r["vote"], 2), "weight": w, "agree": round(agree, 2), "txt": r["txt"],
                     "acc": (stats.get(k) or {}).get("acc"), "n": (stats.get(k) or {}).get("n", 0)})
    conf = int(round(50 + 50 * (num / den))) if den else 50
    pro = sorted([x for x in rows if x["agree"] > 0.2], key=lambda x: -x["weight"] * x["agree"])
    con = sorted([x for x in rows if x["agree"] < -0.2], key=lambda x: x["weight"] * x["agree"])
    strong_con = [x for x in con if x["agree"] <= -0.7 and x["weight"] >= 1.0]
    verdict = "TAKE" if conf >= 65 and len(pro) >= 6 and not strong_con else "AVOID" if conf < 40 or len(strong_con) >= 3 else "WAIT"
    top = sorted(rows, key=lambda x: -x["weight"])[:5]
    return {"regime": reg, "score": conf, "verdict": verdict, "rows": rows, "pro": [x["name"] for x in pro[:5]], "con": [x["name"] for x in con[:4]],
            "focus": [x["name"] for x in top], "votes": {x["key"]: x["vote"] for x in rows},
            "txt": (f"{len(pro)}/15 methods {side} பக்கம் · {len(con)} எதிர் · regime {reg} → இன்று முக்கியம்: {', '.join(x['name'].split(' —')[0].split(' (')[0] for x in top[:3])}")}
