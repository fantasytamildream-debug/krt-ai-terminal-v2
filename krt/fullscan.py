"""Full F&O market scan (rule-based — AI prediction இல்லை).
- PDH/PWH/PMH breakout, PDL/PWL/PML breakdown (எல்லா F&O stocks)
- முதல் 5-min candle (ORB) break
- Volume ratio (approx), Futures OI buildup
- Stock option strike (ATM / 1 ITM, liquidity check)
- NIFTY / BANKNIFTY / FINNIFTY / SENSEX option OI: PCR, support/resistance, strikes
"""
import re, time
import pandas as pd
from .config import ROOT, load_settings
from .instruments import load as load_inst, contracts, INDEX_SPOT, INDEX_OPT_EXCH
from .levels import completed_levels, swing_levels
from .market import classify

C = {"session": None, "levels": {}, "avgvol": {}, "swings": {}, "orb": {}, "orb_session": None,
     "nifty_daily": None, "oi_base": {}, "oi_day": None}
UP, DN = ("PDH", "PWH", "PMH"), ("PDL", "PWL", "PML")


def _f(x, d=0.0):
    try:
        return float(x)
    except Exception:
        return d


def _now():
    return pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).floor("min")


def _depth(q):
    d = q.get("depth") or {}
    b = (d.get("buy") or [{}])[0] or {}
    s = (d.get("sell") or [{}])[0] or {}
    return _f(b.get("price")), _f(s.get("price"))


def _session(q_nifty, now):
    t = (q_nifty or {}).get("exchFeedTime") or (q_nifty or {}).get("exchTradeTime")
    ts = pd.to_datetime(t, dayfirst=True, errors="coerce") if t else pd.NaT
    session = ts.normalize() if not pd.isna(ts) else now.normalize()
    open_ = session + pd.Timedelta(hours=9, minutes=15)
    live = session.date() == now.date() and open_ <= now <= session + pd.Timedelta(hours=15, minutes=30)
    mins = max(1, min(375, int((now - open_).total_seconds() // 60))) if live else 375
    return session, live, mins


def _vol_share(mins):
    """Intraday cumulative volume share (approx U-shape)."""
    return max(0.06, (mins / 375) ** 0.75)


def ensure_daily(ag, inst, names, session, prog):
    if C["session"] != session:
        C.update(session=session, levels={}, avgvol={}, swings={}, nifty_daily=None)
    if C["nifty_daily"] is None:
        df = ag.candles("NSE", INDEX_SPOT["NIFTY"][1], "ONE_DAY", session - pd.Timedelta(days=200), session)
        if not df.empty:
            df.index = df.index.normalize()
        C["nifty_daily"] = df
    todo = [n for n in names if n not in C["levels"]]
    start, end = session - pd.Timedelta(days=420), session + pd.Timedelta(hours=9)
    for i, n in enumerate(todo):
        if i % 10 == 0:
            prog(f"Daily levels {i}/{len(todo)}")
        tok = inst["eq"].get(n)
        df = ag.candles("NSE", tok, "ONE_DAY", start, end) if tok else pd.DataFrame()
        if df.empty:
            C["levels"][n] = None
            continue
        df.index = df.index.normalize()
        C["levels"][n] = completed_levels(df, session)
        past = df[df.index < session]
        C["avgvol"][n] = float(past["volume"].tail(20).mean()) if len(past) else 0.0
        C["swings"][n] = swing_levels(df, session)


def ensure_orb(ag, inst, names, session, live, now, prog):
    if live and now < session + pd.Timedelta(hours=9, minutes=20):
        return False
    if C["orb_session"] != session:
        C.update(orb_session=session, orb={})
    t0 = session + pd.Timedelta(hours=9, minutes=15)
    todo = [n for n in names if n not in C["orb"]]
    for i, n in enumerate(todo):
        if i % 10 == 0:
            prog(f"First 5-min candle {i}/{len(todo)}")
        tok = inst["eq"].get(n)
        df = ag.candles("NSE", tok, "FIVE_MINUTE", t0, t0 + pd.Timedelta(minutes=5)) if tok else pd.DataFrame()
        df = df[df.index == t0] if not df.empty else df
        C["orb"][n] = None if df.empty else (float(df["high"].iloc[0]), float(df["low"].iloc[0]), float(df["volume"].iloc[0]))
    return True


def _targets(n, side, price):
    pool = set(C["swings"].get(n) or []) | set((C["levels"].get(n) or {}).values())
    if side == "CE":
        return [round(x, 2) for x in sorted(p for p in pool if p > price * 1.002)][:3]
    return [round(x, 2) for x in sorted((p for p in pool if p < price * 0.998), reverse=True)][:3]


def _confirm(ag, inst, row, session, live, now):
    tok = inst["eq"].get(row["symbol"])
    t0 = session + pd.Timedelta(hours=9, minutes=15)
    end = now if live else session + pd.Timedelta(hours=15, minutes=30)
    df = ag.candles("NSE", tok, "FIVE_MINUTE", t0, end)
    if df.empty:
        return
    df = df[df.index + pd.Timedelta(minutes=5) <= end]  # completed candles மட்டும்
    if df.empty:
        return
    lvl, ce = row["ref_level"], row["side"] == "CE"
    crossed = (df["close"] > lvl) if ce else (df["close"] < lvl)
    row["confirmed"] = bool(crossed.iloc[-1])
    if crossed.any():
        first = crossed.idxmax()
        row["break_time"] = str(first)
        bc = df.loc[first]
        row["sl"] = round(min(bc["low"], lvl * 0.997), 2) if ce else round(max(bc["high"], lvl * 1.003), 2)


def _status(r):
    if r.get("gap_only"):
        return "WATCH"  # gap → retest / ORB confirmation தேவை
    if r.get("confirmed") is None:
        return "LTP ONLY"
    if not r["confirmed"]:
        return "WATCH"
    if r["ext"] > 1.0:
        return "EXTENDED"
    if r["vol_ratio"] < 1.5:
        return "WATCH"
    return "CONFIRMED"


def _score(r, trend):
    s = {"CONFIRMED": 30, "WATCH": 15, "EXTENDED": 8, "LTP ONLY": 10}.get(r["status"], 0)
    s += min(r["vol_ratio"] / 3, 1) * 25
    s += min(len(r["levels"]) - 1, 2) * 7.5 + (5 if r.get("orb") else 0)
    if (trend == "TRENDING UP" and r["side"] == "CE") or (trend == "TRENDING DOWN" and r["side"] == "PE"):
        s += 15
    elif trend == "RANGE-BOUND":
        s += 5
    s += {0: 0, 1: 5}.get(len(r["targets"]), 10)
    return int(min(100, round(s)))


def pick_options(ag, inst, rows):
    """ATM / 1 ITM — spread ≤ 3%, OI அதிகம். Cheap far-OTM தேர்வு இல்லை."""
    plan, toks = [], {}
    for r in rows:
        exp, cs = contracts(inst, r["symbol"], 3)
        cs = [c for c in cs if c[4] == r["side"]]
        if not cs:
            r["option"] = {"none": "F&O option contract கிடைக்கவில்லை"}
            continue
        strikes = sorted({c[3] for c in cs})
        atm = min(strikes, key=lambda s: abs(s - r["price"]))
        i = strikes.index(atm)
        itm = strikes[i - 1] if r["side"] == "CE" and i > 0 else (strikes[i + 1] if r["side"] == "PE" and i + 1 < len(strikes) else None)
        chosen = [c for c in cs if c[3] in (atm, itm)]
        plan.append((r, chosen, atm))
        for c in chosen:
            toks.setdefault(c[6], []).append(c[0])
    qs = ag.quotes(toks) if toks else {}
    for r, chosen, atm in plan:
        best = None
        for c in chosen:
            q = qs.get(c[0])
            if not q:
                continue
            bid, ask = _depth(q)
            mid = (bid + ask) / 2 if bid and ask else 0
            spread = (ask - bid) / mid * 100 if mid else 999
            cand = {"contract": c[1], "strike": c[3], "expiry": c[2], "type": c[4], "lot": c[5],
                    "moneyness": "ATM" if c[3] == atm else "ITM", "bid": bid, "ask": ask,
                    "ltp": _f(q.get("ltp")), "spread_pct": round(spread, 2), "oi": int(_f(q.get("opnInterest"))),
                    "volume": int(_f(q.get("tradeVolume"))), "lot_cost": round(ask * c[5])}
            if spread <= 3 and bid > 0 and (best is None or cand["oi"] > best["oi"]):
                best = cand
        r["option"] = best or {"none": "STOCK SETUP VALID — NO SUITABLE OPTION (spread / liquidity குறைவு)"}


def index_oi(ag, inst, spot_q):
    out = []
    today = pd.Timestamp.now(tz="Asia/Kolkata").date().isoformat()
    if C["oi_day"] != today:
        C.update(oi_day=today, oi_base={})
    for idx, (ex, tok) in INDEX_SPOT.items():
        q = spot_q.get(tok)
        spot = _f((q or {}).get("ltp"))
        exp, cs = contracts(inst, idx, 0)
        if not spot or not cs:
            out.append({"index": idx, "error": "Data கிடைக்கவில்லை"})
            continue
        strikes = sorted({c[3] for c in cs})
        atm = min(strikes, key=lambda s: abs(s - spot))
        i = strikes.index(atm)
        win = set(strikes[max(0, i - 10): i + 11])
        sel = [c for c in cs if c[3] in win]
        qs = ag.quotes({INDEX_OPT_EXCH[idx]: [c[0] for c in sel]})
        chain = {}
        for c in sel:
            qq = qs.get(c[0]) or {}
            oi = _f(qq.get("opnInterest"))
            base = C["oi_base"].setdefault(c[0], oi)
            bid, ask = _depth(qq)
            chain.setdefault(c[3], {"strike": c[3]})[c[4]] = {
                "oi": int(oi), "chg": int(oi - base), "ltp": _f(qq.get("ltp")), "bid": bid, "ask": ask,
                "lot": c[5], "contract": c[1]}
        rows = [chain[k] for k in sorted(chain)]
        ce_oi = sum(r.get("CE", {}).get("oi", 0) for r in rows)
        pe_oi = sum(r.get("PE", {}).get("oi", 0) for r in rows)
        pcr = round(pe_oi / ce_oi, 2) if ce_oi else None
        res = max(rows, key=lambda r: r.get("CE", {}).get("oi", 0))["strike"]
        sup = max(rows, key=lambda r: r.get("PE", {}).get("oi", 0))["strike"]
        if pcr is None:
            bias = "UNCLEAR"
        elif pcr >= 1.2 and spot > sup:
            bias = "BULLISH TILT"
        elif pcr <= 0.8 and spot < res:
            bias = "BEARISH TILT"
        else:
            bias = "NEUTRAL / RANGE"
        atm_row = chain.get(atm, {})
        out.append({"index": idx, "spot": spot, "pct": _f((q or {}).get("percentChange")), "expiry": exp,
                    "atm": atm, "pcr": pcr, "support": sup, "resistance": res, "bias": bias,
                    "atm_ce": atm_row.get("CE"), "atm_pe": atm_row.get("PE"), "chain": rows})
    return out


SYM_RE = re.compile(r"^(.+?)\d{2}[A-Z]{3}\d{2}FUT$")


def oi_buildups(ag):
    out = {}
    for kind in ("Long Built Up", "Short Built Up", "Short Covering", "Long Unwinding"):
        rows = []
        for d in ag.oi_buildup(kind)[:12]:
            ts = d.get("tradingSymbol", "")
            m = SYM_RE.match(ts)
            rows.append({"symbol": m.group(1) if m else ts, "ltp": _f(d.get("ltp")),
                         "pct": _f(d.get("percentChange")), "oi": int(_f(d.get("opnInterest"))),
                         "oi_chg": _f(d.get("netChangeOpnInterest"))})
        out[kind] = rows
    return out


def run_full(ag, prog=lambda m: None) -> dict:
    t_start = time.time()
    cfg = load_settings()
    now = _now()
    errors = []
    prog("Instrument list")
    inst = load_inst(ROOT / "data" / "cache")
    names = [n for n in inst["fno"] if n in inst["eq"]]

    prog("Live quotes")
    spot_toks = {}
    for ex, tok in INDEX_SPOT.values():
        spot_toks.setdefault(ex, []).append(tok)
    tok2name = {inst["eq"][n]: n for n in names}
    spot_toks.setdefault("NSE", []).extend(tok2name)
    qs = ag.quotes(spot_toks)
    session, live, mins = _session(qs.get(INDEX_SPOT["NIFTY"][1]), now)

    ensure_daily(ag, inst, names, session, prog)
    has_orb = ensure_orb(ag, inst, names, session, live, now, prog)
    nd = C["nifty_daily"]
    trend = classify(nd, session) if nd is not None and not nd.empty else "UNCLEAR — WAIT"

    share = _vol_share(mins)
    universe, cands = [], []
    adv = dec = 0
    for tok, n in tok2name.items():
        q = qs.get(tok)
        lv = C["levels"].get(n)
        if not q or not lv:
            continue
        ltp, op, pct = _f(q.get("ltp")), _f(q.get("open")), _f(q.get("percentChange"))
        vol, avg = _f(q.get("tradeVolume")), C["avgvol"].get(n) or 0
        vr = round(vol / (avg * share), 2) if avg else 0.0
        adv += pct > 0
        dec += pct < 0
        orb = C["orb"].get(n) if has_orb else None
        orb_up = bool(orb and ltp > orb[0])
        orb_dn = bool(orb and ltp < orb[1])
        universe.append({"symbol": n, "ltp": ltp, "pct": pct, "vol_ratio": vr, "volume": int(vol),
                         "orb_up": orb_up, "orb_dn": orb_dn, "orb": orb})
        for side, keys, beyond, gapf in (("CE", UP, lambda l: ltp > l, lambda l: op > l),
                                         ("PE", DN, lambda l: ltp < l, lambda l: op < l)):
            hit = [k for k in keys if lv.get(k) and beyond(lv[k])]
            if not hit:
                continue
            fresh = [k for k in hit if not gapf(lv[k])]
            ref_key = (max if side == "CE" else min)(hit, key=lambda k: lv[k])
            ref = lv[ref_key]
            ext = abs(ltp - ref) / ref * 100
            cands.append({"symbol": n, "side": side, "levels": hit, "fresh": fresh, "gap_only": not fresh,
                          "ref_key": ref_key, "ref_level": round(ref, 2), "price": ltp, "pct": pct,
                          "vol_ratio": vr, "ext": round(ext, 2),
                          "orb": orb_up if side == "CE" else orb_dn,
                          "sl": round(ref * (0.997 if side == "CE" else 1.003), 2), "confirmed": None})

    # Stage 2: top candidates-க்கு 5-min candle close confirmation
    cands.sort(key=lambda r: -r["vol_ratio"])
    for i, r in enumerate(cands[:30]):
        if i % 5 == 0:
            prog(f"5-min confirmation {i}/{min(30, len(cands))}")
        _confirm(ag, inst, r, session, live, now)
    for r in cands:
        r["targets"] = _targets(r["symbol"], r["side"], r["price"])
        r["status"] = _status(r)
        r["score"] = _score(r, trend)
    rank = {"CONFIRMED": 0, "WATCH": 1, "LTP ONLY": 2, "EXTENDED": 3}
    cands.sort(key=lambda r: (rank.get(r["status"], 9), -r["score"]))
    ce = [r for r in cands if r["side"] == "CE"]
    pe = [r for r in cands if r["side"] == "PE"]

    prog("Option strikes")
    pick_options(ag, inst, ce[:6] + pe[:6])

    orb_up = sorted([u for u in universe if u["orb_up"]], key=lambda u: -u["vol_ratio"])[:20]
    orb_dn = sorted([u for u in universe if u["orb_dn"]], key=lambda u: -u["vol_ratio"])[:20]

    prog("Index option OI")
    try:
        idx = index_oi(ag, inst, qs)
    except Exception as e:
        idx, _ = [], errors.append(f"Index OI: {e}")
    prog("Futures OI buildup")
    try:
        bu = oi_buildups(ag)
    except Exception as e:
        bu, _ = {}, errors.append(f"OI buildup: {e}")
    tag = {}
    for kind, rows in bu.items():
        for x in rows:
            tag[x["symbol"]] = kind
    hv = sorted(universe, key=lambda u: -u["vol_ratio"])[:20]
    for u in hv:
        u["oi_tag"] = tag.get(u["symbol"], "")

    best = [r for r in ce + pe if r["status"] == "CONFIRMED" and "none" not in (r.get("option") or {"none": 1})]
    best.sort(key=lambda r: -r["score"])
    nifty = next((x for x in idx if x.get("index") == "NIFTY"), {})
    summary = [
        f"NIFTY daily trend: {trend}" + (f", இன்று {nifty.get('pct', 0):+.2f}%" if nifty.get("spot") else ""),
        f"F&O breadth: {adv} ஏற்றம் / {dec} இறக்கம்",
        f"Breakout {len(ce)} stocks, breakdown {len(pe)} stocks (CONFIRMED: {sum(r['status']=='CONFIRMED' for r in ce)} CE / {sum(r['status']=='CONFIRMED' for r in pe)} PE)",
    ]
    if nifty.get("pcr") is not None:
        summary.append(f"NIFTY PCR {nifty['pcr']} — support {nifty['support']:g}, resistance {nifty['resistance']:g} ({nifty['bias']})")
    if not best:
        summary.append("இப்போ rules எல்லாம் pass ஆன setup இல்லை → WAIT.")

    return {"kind": "full", "time": str(now), "session": str(session.date()), "live": live,
            "trend": trend, "summary": summary, "best": best[:6], "ce": ce[:25], "pe": pe[:25],
            "orb_up": orb_up, "orb_dn": orb_dn, "orb_ready": has_orb, "high_volume": hv,
            "oi_buildup": bu, "index": idx, "universe_count": len(universe),
            "errors": errors, "seconds": round(time.time() - t_start)}
