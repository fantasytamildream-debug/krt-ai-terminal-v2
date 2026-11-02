"""👑 MONEY MACHINE — moneycontrol மாதிரி market view (Angel live data-வில் நாமே கணக்கு) + எல்லா signal-ஐயும் சேர்த்து CE / PE ranking + Jackpot.
Sections: Gainers / Losers · Active by Value / Volume · 52-wk High / Low · Only Buyers / Sellers · Price Shockers (3 நாள்) ·
Volume Shockers (5 நாள் avg) · Technical Trends · OI Trends · Sectors · NIFTY option chain.
நேர்மை: moneycontrol-ஐ நேரடியா படிக்கல. 52-week = கிடைச்ச ~250 நாள் daily data (இல்லைன்னா ~6 மாதம்). Sector map = முக்கிய F&O stocks மட்டும்.
"""
import numpy as np

SECTOR = {}
for sec, names in {
    "IT": "TCS INFY HCLTECH WIPRO TECHM LTIM LTM PERSISTENT COFORGE MPHASIS OFSS KPITTECH TATAELXSI CYIENT SONACOMS",
    "Bank": "HDFCBANK ICICIBANK SBIN KOTAKBANK AXISBANK INDUSINDBK BANKBARODA PNB CANBK FEDERALBNK IDFCFIRSTB AUBANK BANDHANBNK BANKINDIA UNIONBANK INDIANB YESBANK RBLBANK",
    "Fin Service": "BAJFINANCE BAJAJFINSV CHOLAFIN SHRIRAMFIN MUTHOOTFIN MANAPPURAM LICHSGFIN PNBHOUSING HDFCLIFE SBILIFE ICICIGI ICICIPRULI LICI SBICARD RECLTD PFC IRFC CAMS CDSL BSE MCX ANGELONE IIFL JIOFIN ABCAPITAL POONAWALLA HDFCAMC NAM-INDIA KFINTECH 360ONE MFSL SAMMAANCAP",
    "Pharma": "SUNPHARMA DRREDDY CIPLA DIVISLAB LUPIN AUROPHARMA ZYDUSLIFE TORNTPHARM ALKEM BIOCON GLENMARK LAURUSLABS IPCALAB MANKIND GRANULES ABBOTINDIA",
    "Healthcare": "APOLLOHOSP MAXHEALTH FORTIS SYNGENE",
    "Auto": "MARUTI TATAMOTORS M&M BAJAJ-AUTO HEROMOTOCO EICHERMOT TVSMOTOR ASHOKLEY BHARATFORG MOTHERSON BOSCHLTD EXIDEIND TIINDIA HYUNDAI TMPV SONACOMS UNOMINDA",
    "Metal": "TATASTEEL JSWSTEEL HINDALCO VEDL SAIL JINDALSTEL NMDC NATIONALUM HINDZINC APLAPOLLO COALINDIA",
    "Energy": "RELIANCE ONGC IOC BPCL HINDPETRO GAIL OIL PETRONET NTPC POWERGRID TATAPOWER ADANIGREEN ADANIENSOL NHPC SJVN JSWENERGY IREDA SUZLON INOXWIND TORNTPOWER CESC",
    "FMCG": "HINDUNILVR ITC NESTLEIND BRITANNIA DABUR MARICO GODREJCP COLPAL TATACONSUM UNITDSPR VBL PATANJALI RADICO",
    "Consumption": "TITAN TRENT DMART ASIANPAINT BERGEPAINT PIDILITIND HAVELLS VOLTAS CROMPTON BLUESTARCO DIXON KALYANKJIL NYKAA ETERNAL SWIGGY JUBLFOOD INDHOTEL PAGEIND AMBER POLYCAB KEI",
    "Infra / Capital goods": "LT ADANIPORTS ADANIENT SIEMENS ABB BHEL BEL HAL CGPOWER CUMMINSIND POWERINDIA GMRAIRPORT IRCTC CONCOR RVNL NBCC KAYNES BDL MAZDOCK SOLARINDS",
    "Cement / Realty": "ULTRACEMCO SHREECEM AMBUJACEM DALBHARAT GRASIM DLF GODREJPROP OBEROIRLTY PRESTIGE LODHA PHOENIXLTD",
    "Telecom / Media": "BHARTIARTL IDEA INDUSTOWERS TATACOMM SUNTV",
    "Chemicals": "SRF PIIND UPL DEEPAKNTR NAVINFLUOR TATACHEM COROMANDEL ATUL",
}.items():
    for n in names.split():
        SECTOR.setdefault(n, sec)


def daily_info(bars, hl52=None):
    """ஒரு நாளுக்கு ஒரு முறை: 52w high/low · 3 நாள் முன் close · 5 நாள் avg vol · SMA20/50 trend + trend change date."""
    if not bars or len(bars.get("c") or []) < 55:
        return None
    c = np.array(bars["c"], float)
    h = np.array(bars["h"], float)
    l_ = np.array(bars["l"], float)
    v = np.array(bars.get("v") or [0] * len(c), float)
    s20 = np.convolve(c, np.ones(20) / 20, "valid")
    s50 = np.convolve(c, np.ones(50) / 50, "valid")
    k = min(len(s20), len(s50))
    a20, a50, cc = s20[-k:], s50[-k:], c[-k:]
    state = np.where((cc > a20) & (a20 > a50), 1, np.where((cc < a20) & (a20 < a50), -1, 0))
    cur = int(state[-1])
    i = len(state) - 1
    while i > 0 and state[i - 1] == cur:
        i -= 1
    since = len(state) - 1 - i
    trend = {1: "Bullish", -1: "Bearish", 0: "Neutral"}[cur]
    if cur == 0:
        trend = "Turning Bullish" if cc[-1] > a20[-1] else "Turning Bearish"
    hi52, lo52 = hl52 if hl52 else (float(h.max()), float(l_.min()))
    return {"hi52": hi52, "lo52": lo52, "c3": float(c[-3]) if len(c) >= 3 else float(c[0]), "v5": float(v[-5:].mean()) if len(v) >= 5 else 0,
            "trend": trend, "trend_date": bars["t"][len(bars["t"]) - 1 - since], "trend_px": float(c[len(c) - 1 - since]),
            "s20": float(a20[-1]), "s50": float(a50[-1]), "hl52_real": bool(hl52)}


def build(live_q, C, res, now):
    """→ sections + CE/PE ranked list."""
    D = C.setdefault("mm_daily", {})
    day = str(now.date())
    if D.get("_day") != day:
        D.clear()
        D["_day"] = day
    rows = []
    bu = {}
    for kind, L in (res.get("oi_buildup") or {}).items():
        for x in L:
            bu[x["symbol"]] = kind
    for n, q in live_q.items():
        if n not in D:
            D[n] = daily_info((C.get("bars") or {}).get(n), (C.get("hl52") or {}).get(n))
        d = D.get(n) or {}
        ltp, pct = q.get("ltp") or 0, q.get("pct") or 0
        if not ltp:
            continue
        vol = q.get("volume") or 0
        r = {"symbol": n, "ltp": ltp, "pct": round(pct, 2), "vol_ratio": q.get("vol_ratio") or 0, "volume": vol, "value_cr": round(ltp * vol / 1e7, 1),
             "high": q.get("high"), "low": q.get("low"), "sector": SECTOR.get(n, "Others"), "oi": bu.get(n, ""),
             "trend": d.get("trend"), "trend_date": d.get("trend_date"), "trend_perf": round((ltp / d["trend_px"] - 1) * 100, 2) if d.get("trend_px") else None,
             "shock3": round((ltp / d["c3"] - 1) * 100, 2) if d.get("c3") else 0, "volx5": round(vol / d["v5"], 2) if d.get("v5") else 0,
             "hi52": d.get("hi52"), "lo52": d.get("lo52"), "hl52_real": d.get("hl52_real")}
        r["new_hi52"] = bool(d.get("hi52") and q.get("high") and q["high"] >= d["hi52"])
        r["new_lo52"] = bool(d.get("lo52") and q.get("low") and q["low"] <= d["lo52"])
        r["only_buy"] = bool(q.get("high") and ltp >= q["high"] * 0.999 and pct > 1)
        r["only_sell"] = bool(q.get("low") and ltp <= q["low"] * 1.001 and pct < -1)
        rows.append(r)
    # sectors
    sec = {}
    for r in rows:
        sec.setdefault(r["sector"], []).append(r["pct"])
    sectors = sorted([{"sector": k, "pct": round(sum(v) / len(v), 2), "n": len(v), "up": sum(1 for x in v if x > 0)} for k, v in sec.items() if k != "Others"],
                     key=lambda s: -s["pct"])
    sp = {s["sector"]: s["pct"] for s in sectors}
    # OI trends summary
    bull_k, bear_k = ("Long Built Up", "Short Covering"), ("Short Built Up", "Long Unwinding")
    nb = sum(1 for r in rows if r["oi"] in bull_k)
    ns = sum(1 for r in rows if r["oi"] in bear_k)
    oi_tr = {"bull_pct": round(nb / (nb + ns) * 100, 1) if nb + ns else None, "bear_pct": round(ns / (nb + ns) * 100, 1) if nb + ns else None,
             "lists": {k: [r["symbol"] for r in rows if r["oi"] == k][:12] for k in bull_k + bear_k}}
    npct = next((x.get("pct") for x in res.get("index") or [] if x.get("index") == "NIFTY"), 0) or 0
    # score CE / PE
    for r in rows:
        for side in ("CE", "PE"):
            ce = side == "CE"
            pts, why = 0, []

            def add(ok, p, t):
                nonlocal pts
                if ok:
                    pts += p
                    why.append(t)
            lv = (C.get("levels") or {}).get(r["symbol"]) or {}
            q = live_q.get(r["symbol"]) or {}
            rng = (q.get("high") or 0) - (q.get("low") or 0)
            pos = ((r["ltp"] - q["low"]) / rng) if rng > 0 else 0.5
            add((r["pct"] >= 1.5) if ce else (r["pct"] <= -1.5), 10, f"{'Gainer' if ce else 'Loser'} {r['pct']:+.2f}%")
            add(r["vol_ratio"] >= 2 or r["volx5"] >= 2, 15, f"Volume shocker {max(r['vol_ratio'], r['volx5']):.1f}×")
            add(r["only_buy"] if ce else r["only_sell"], 10, "Only buyers (day high-ல்)" if ce else "Only sellers (day low-ல்)")
            add(r["new_hi52"] if ce else r["new_lo52"], 10, "52-week high" if ce else "52-week low")
            add((r["oi"] in bull_k) if ce else (r["oi"] in bear_k), 15, f"OI: {r['oi']}")
            add((r["trend"] in ("Bullish", "Turning Bullish")) if ce else (r["trend"] in ("Bearish", "Turning Bearish")), 10, f"Trend: {r['trend']}")
            add(bool(lv.get("PDH" if ce else "PDL")) and ((r["ltp"] > lv["PDH"]) if ce else (r["ltp"] < lv["PDL"])), 10, "PDH break" if ce else "PDL break")
            add((pos >= 0.8) if ce else (pos <= 0.2), 5, f"Day range-ல் {int(pos * 100)}%")
            add((r["shock3"] >= 4) if ce else (r["shock3"] <= -4), 5, f"3 நாள் {r['shock3']:+.1f}%")
            s_ = sp.get(r["sector"])
            add(s_ is not None and ((s_ >= 0.5) if ce else (s_ <= -0.5)), 5, f"Sector {r['sector']} {s_:+.2f}%" if s_ is not None else "")
            add((npct > -0.2) if ce else (npct < 0.2), 5, "NIFTY எதிர் இல்லை")
            r[f"sc_{side}"], r[f"why_{side}"] = pts, why
            r[f"conf_{side}"] = "HIGH" if pts >= 80 else "MEDIUM" if pts >= 65 else "LOW"
    ce_list = sorted([r for r in rows if r["sc_CE"] >= 45], key=lambda r: -r["sc_CE"])[:12]
    pe_list = sorted([r for r in rows if r["sc_PE"] >= 45], key=lambda r: -r["sc_PE"])[:12]
    top = lambda key, rev=True, n=10, f=None: sorted([r for r in rows if (f(r) if f else True)], key=lambda r: r[key], reverse=rev)[:n]
    nifty = next((x for x in res.get("index") or [] if x.get("index") == "NIFTY"), {}) or {}
    ch = sorted(nifty.get("chain") or [], key=lambda x: abs(x["strike"] - (nifty.get("spot") or 0)))[:9]
    chain = sorted([{"strike": x["strike"], "ce": {k: (x.get("CE") or {}).get(k) for k in ("ltp", "oi", "vol")},
                     "pe": {k: (x.get("PE") or {}).get(k) for k in ("ltp", "oi", "vol")}} for x in ch], key=lambda x: x["strike"])
    return {"time": now.strftime("%H:%M:%S"), "ce": ce_list, "pe": pe_list,
            "gainers": top("pct"), "losers": top("pct", False), "value": top("value_cr"), "volume": top("volume"),
            "hi52": top("pct", f=lambda r: r["new_hi52"]), "lo52": top("pct", False, f=lambda r: r["new_lo52"]),
            "only_buy": top("pct", f=lambda r: r["only_buy"]), "only_sell": top("pct", False, f=lambda r: r["only_sell"]),
            "price_shock": top("shock3", n=8), "vol_shock": top("volx5", n=10),
            "tech": {t: sorted([r for r in rows if r["trend"] == t], key=lambda r: -(r["trend_perf"] or 0) if "Bull" in t else (r["trend_perf"] or 0))[:8]
                     for t in ("Bullish", "Turning Bullish", "Bearish", "Turning Bearish")},
            "oi": oi_tr, "sectors": sectors, "chain": {"spot": nifty.get("spot"), "expiry": nifty.get("expiry"), "pcr": nifty.get("pcr"),
                                                      "support": nifty.get("support"), "resistance": nifty.get("resistance"), "rows": chain},
            "breadth": {"up": sum(1 for r in rows if r["pct"] > 0), "down": sum(1 for r in rows if r["pct"] < 0)}}
