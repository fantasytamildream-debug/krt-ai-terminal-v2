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
from .optmath import plan as prem_plan

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
        C.update(session=session, levels={}, avgvol={}, swings={}, nifty_daily=None, feat={})
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
        c = past["close"]
        if len(c) >= 60:
            e20, e50 = c.ewm(span=20).mean(), c.ewm(span=50).mean()
            tr = pd.concat([past["high"] - past["low"], (past["high"] - c.shift()).abs(), (past["low"] - c.shift()).abs()], axis=1).max(axis=1)
            C.setdefault("feat", {})[n] = {"ema20": float(e20.iloc[-1]), "ema50": float(e50.iloc[-1]),
                                           "ema20_5": float(e20.iloc[-6]), "atr": float(tr.tail(14).mean()),
                                           "c20": float(c.iloc[-21]), "hi52": float(past["high"].tail(250).max()),
                                           "lo52": float(past["low"].tail(250).min())}


def ensure_orb(ag, inst, names, session, live, now, prog):
    if live and now < session + pd.Timedelta(hours=9, minutes=20):
        return False
    if C["orb_session"] != session:
        C.update(orb_session=session, orb={}, orb_try={})
    t0 = session + pd.Timedelta(hours=9, minutes=15)
    todo = [n for n in names if C["orb"].get(n) is None and C.setdefault("orb_try", {}).get(n, 0) < 2][:40]
    for i, n in enumerate(todo):
        C["orb_try"][n] = C["orb_try"].get(n, 0) + 1
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


def stars(score):
    return 5 if score >= 85 else 4 if score >= 70 else 3 if score >= 55 else 2 if score >= 40 else 1


def fill_targets(price, sl, side, tg):
    """Structure targets 3-க்கு குறைவு என்றால் 1R/2R/3R கொண்டு நிரப்பு (label உடன்)."""
    tg, kinds = list(tg)[:3], ["level"] * min(3, len(tg))
    risk = abs(price - sl) or price * 0.005
    k = 1
    while len(tg) < 3:
        t = price + k * risk if side == "CE" else price - k * risk
        if t <= 0 or k > 12:
            break
        if all((t > x) if side == "CE" else (t < x) for x in tg):
            tg.append(round(t, 2))
            kinds.append(f"{k}R")
        k += 1
    return tg, kinds


def attach_plan(r, opt, now):
    """r: price, sl, targets, side → opt['plan'] (premium ESTIMATE)."""
    if not opt or "none" in opt:
        return
    tg, kinds = fill_targets(r["price"], r["sl"], r["side"], r.get("targets") or [])
    r["targets"], r["target_kinds"] = tg, kinds
    cfg = load_settings().get("risk", {})
    prem = opt.get("ask") or opt.get("ltp")
    try:
        opt["plan"] = prem_plan(prem, r["price"], opt["strike"], opt["expiry"], opt["type"], r["sl"], tg,
                            now.to_pydatetime(), opt["lot"], cfg.get("charges_slippage", 150),
                            cfg.get("max_risk_per_trade", 2500))
    except Exception:
        opt["plan"] = None


def pick_options(ag, inst, rows):
    """ATM / 1 ITM — spread ≤ 3%, OI அதிகம். Cheap far-OTM தேர்வு இல்லை."""
    plan, toks = [], {}
    for r in rows:
        exp, cs = contracts(inst, r["symbol"], r.get("min_days", 3))
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
            cand = {"token": c[0], "exch": c[6], "contract": c[1], "strike": c[3], "expiry": c[2], "type": c[4], "lot": c[5],
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
        pct = _f((q or {}).get("percentChange"))
        if bias == "BULLISH TILT":
            side, conf = "CE", "OI bias"
        elif bias == "BEARISH TILT":
            side, conf = "PE", "OI bias"
        else:
            side, conf = ("CE" if pct >= 0 else "PE"), "LOW — range market, day change அடிப்படையில்"
        plans = {}
        for sd in ("CE", "PE"):
            o = atm_row.get(sd)
            if not o:
                continue
            if sd == "CE":
                walls = sorted(r["strike"] for r in sorted(rows, key=lambda r: -r.get("CE", {}).get("oi", 0))[:6] if r["strike"] > spot)
                sl_ul = max(sup, spot * 0.996) if sup < spot else spot * 0.996
            else:
                walls = sorted((r["strike"] for r in sorted(rows, key=lambda r: -r.get("PE", {}).get("oi", 0))[:6] if r["strike"] < spot), reverse=True)
                sl_ul = min(res, spot * 1.004) if res > spot else spot * 1.004
            pr = {"side": sd, "price": spot, "sl": round(sl_ul, 2), "targets": walls[:3]}
            opt = {"token": next((c[0] for c in sel if c[3] == atm and c[4] == sd), None),
                   "exch": INDEX_OPT_EXCH[idx], "contract": o["contract"], "strike": atm, "expiry": exp,
                   "type": sd, "lot": o["lot"], "bid": o["bid"], "ask": o["ask"], "ltp": o["ltp"], "moneyness": "ATM"}
            attach_plan(pr, opt, _now())
            plans[sd] = {"ul_sl": pr["sl"], "ul_targets": pr["targets"], "kinds": pr.get("target_kinds"), "option": opt}
        out.append({"index": idx, "spot": spot, "pct": pct, "expiry": exp,
                    "atm": atm, "pcr": pcr, "support": sup, "resistance": res, "bias": bias,
                    "suggest": side, "confidence": conf, "plans": plans,
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
                         "high": _f(q.get("high")), "low": _f(q.get("low")),
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
    slot = str(now.floor("5min"))
    cc = C.setdefault("confirm_cache", {})
    if cc.get("slot") != slot:
        cc.clear()
        cc["slot"] = slot
    for i, r in enumerate(cands[:20]):
        if i % 5 == 0:
            prog(f"5-min confirmation {i}/{min(20, len(cands))}")
        key = f"{r['symbol']}|{r['side']}|{r['ref_level']}"
        if key in cc:
            r.update(cc[key])
            continue
        _confirm(ag, inst, r, session, live, now)
        cc[key] = {k: r.get(k) for k in ("confirmed", "break_time", "sl") if k in r}
    for r in cands:
        r["targets"] = _targets(r["symbol"], r["side"], r["price"])
        r["status"] = _status(r)
        r["score"] = _score(r, trend)
    rank = {"CONFIRMED": 0, "WATCH": 1, "LTP ONLY": 2, "EXTENDED": 3}
    cands.sort(key=lambda r: (rank.get(r["status"], 9), -r["score"]))
    ce = [r for r in cands if r["side"] == "CE"]
    pe = [r for r in cands if r["side"] == "PE"]

    prog("Option strikes")
    for r in cands:
        r["stars"] = stars(r["score"])
    top_ce, top_pe = ce[:8], pe[:8]

    # 5-min ORB rows + targets (range multiples)
    def orb_rows(side):
        rows = []
        for u in universe:
            o = u["orb"]
            if not o or not (u["orb_up"] if side == "CE" else u["orb_dn"]):
                continue
            hi, lo = o[0], o[1]
            rng = max(hi - lo, u["ltp"] * 0.002)
            if side == "CE":
                ent, sl, tg = hi, lo, [hi + rng, hi + 2 * rng, hi + 3 * rng]
            else:
                ent, sl, tg = lo, hi, [lo - rng, lo - 2 * rng, lo - 3 * rng]
            ext = abs(u["ltp"] - ent) / ent * 100
            sc = min(100, int(min(u["vol_ratio"] / 3, 1) * 50 + (25 if ext <= 1 else 5) +
                              (25 if (trend == "TRENDING UP") == (side == "CE") and trend != "RANGE-BOUND" else 10)))
            rows.append({"symbol": u["symbol"], "side": side, "price": u["ltp"], "pct": u["pct"],
                         "vol_ratio": u["vol_ratio"], "orb_high": hi, "orb_low": lo, "entry": round(ent, 2),
                         "sl": round(sl, 2), "targets": [round(x, 2) for x in tg], "target_kinds": ["1×range", "2×range", "3×range"],
                         "ext": round(ext, 2), "status": "EXTENDED" if ext > 1.2 else ("CONFIRMED" if u["vol_ratio"] >= 1.5 else "WATCH"),
                         "score": sc, "stars": stars(sc)})
        rows.sort(key=lambda r: (r["status"] != "CONFIRMED", -r["score"]))
        return rows[:20]
    orb_up, orb_dn = orb_rows("CE"), orb_rows("PE")

    # Volume + OI picks: buildup + volume + direction ஒத்துப்போனால்
    bu_tag = {}
    try:
        prog("Futures OI buildup")
        bu = oi_buildups(ag)
    except Exception as e:
        bu = {}
        errors.append(f"OI buildup: {e}")
    for kind, rows_ in bu.items():
        for x in rows_:
            bu_tag[x["symbol"]] = kind
    voi = {"CE": [], "PE": []}
    for u in sorted(universe, key=lambda u: -u["vol_ratio"]):
        k = bu_tag.get(u["symbol"], "")
        side = "CE" if k in ("Long Built Up", "Short Covering") and u["pct"] > 0 else \
               "PE" if k in ("Short Built Up", "Long Unwinding") and u["pct"] < 0 else None
        if not side or len(voi[side]) >= 3 or u["vol_ratio"] < 1.5:
            continue
        sl = u["low"] if side == "CE" else u["high"]
        if not sl or abs(u["ltp"] - sl) / u["ltp"] > 0.03:
            sl = u["ltp"] * (0.985 if side == "CE" else 1.015)
        sc = min(100, int(min(u["vol_ratio"] / 3, 1) * 40 + 30 + (20 if k in ("Long Built Up", "Short Built Up") else 10) +
                          (10 if (trend == "TRENDING UP") == (side == "CE") else 0)))
        voi[side].append({"symbol": u["symbol"], "side": side, "price": u["ltp"], "pct": u["pct"],
                          "vol_ratio": u["vol_ratio"], "oi_tag": k, "sl": round(sl, 2),
                          "targets": _targets(u["symbol"], side, u["ltp"]), "score": sc, "stars": stars(sc),
                          "status": "CONFIRMED"})

    picks = top_ce + top_pe + orb_up[:5] + orb_dn[:5] + voi["CE"] + voi["PE"]
    pick_options(ag, inst, picks)
    for r in picks:
        attach_plan(r, r.get("option"), now)

    prog("Index option OI")
    try:
        idx = index_oi(ag, inst, qs)
    except Exception as e:
        idx = []
        errors.append(f"Index OI: {e}")
    hv = sorted(universe, key=lambda u: -u["vol_ratio"])[:20]
    for u in hv:
        u["oi_tag"] = bu_tag.get(u["symbol"], "")
    if has_orb:
        got = sum(1 for n in names if C["orb"].get(n))
        if got < len(names) * 0.8:
            errors.append(f"5-min ORB data {got}/{len(names)} stocks மட்டும் கிடைத்தது — அடுத்த scan-ல் மீதி எடுக்கும்")
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

    prog("Swing picks")
    from .swing import swing_picks
    try:
        swing = swing_picks(ag, inst, universe, C, idx, trend, now, session)
    except Exception as e:
        swing = {"5": [], "10": []}
        errors.append(f"Swing: {e}")
    prog("Calls tracking")
    from .calls import update_calls
    try:
        track = update_calls(ag, session, now, live, best, orb_up[:3] + orb_dn[:3], voi["CE"] + voi["PE"], idx, swing)
    except Exception as e:
        track = {"today": [], "history": [], "jackpot": [], "summary": {}, "swing_published": None}
        errors.append(f"Tracking: {e}")

    return {"kind": "full", "time": str(now), "volume_oi_picks": voi, "tracking": track, "swing": swing, "session": str(session.date()), "live": live,
            "trend": trend, "summary": summary, "best": best[:6], "ce": ce[:25], "pe": pe[:25],
            "orb_up": orb_up, "orb_dn": orb_dn, "orb_ready": has_orb, "high_volume": hv,
            "oi_buildup": bu, "index": idx, "universe_count": len(universe),
            "errors": errors, "seconds": round(time.time() - t_start)}




def export_cache():
    """Daily levels / features / ORB — session-க்கு ஒருமுறை கணக்கிட்டது (restart-க்கு பின் மீண்டும் எடுக்க வேண்டாம்)."""
    if C["session"] is None:
        return None
    nd = C.get("nifty_daily")
    return {"session": str(C["session"].date()), "levels": C["levels"], "avgvol": C["avgvol"],
            "swings": C["swings"], "feat": C.get("feat", {}),
            "orb_session": str(C["orb_session"].date()) if C.get("orb_session") is not None else None,
            "orb": C.get("orb", {}),
            "nifty": None if nd is None or nd.empty else {"t": [str(x.date()) for x in nd.index], "c": nd["close"].tolist(),
                                                           "h": nd["high"].tolist(), "l": nd["low"].tolist()}}


def import_cache(d):
    if not d or not d.get("session"):
        return False
    s = pd.Timestamp(d["session"])
    nd = None
    if d.get("nifty"):
        n = d["nifty"]
        nd = pd.DataFrame({"open": n["c"], "high": n["h"], "low": n["l"], "close": n["c"], "volume": 0.0},
                          index=pd.to_datetime(n["t"]))
    C.update(session=s, levels=d.get("levels", {}), avgvol=d.get("avgvol", {}), swings=d.get("swings", {}),
             feat=d.get("feat", {}), nifty_daily=nd)
    if d.get("orb_session"):
        C.update(orb_session=pd.Timestamp(d["orb_session"]), orb={k: tuple(v) if v else None for k, v in d.get("orb", {}).items()},
                 orb_try={})
    return True


def fast_tick(ag, res):
    """Deep scan-க்கு இடையில் ~30 sec-க்கு ஒருமுறை: LTP, % change, vol ratio, option LTP, calls T1/SL update.
    Candle / OI chain எதுவும் இல்லை — light & fast."""
    if not res:
        return res
    inst = load_inst(ROOT / "data" / "cache")
    names = [n for n in inst["fno"] if n in inst["eq"]]
    toks = {"NSE": [inst["eq"][n] for n in names]}
    for ex, tok in INDEX_SPOT.values():
        toks.setdefault(ex, []).append(tok)
    opt_rows = []
    for key in ("best", "ce", "pe", "orb_up", "orb_dn"):
        opt_rows += [r for r in res.get(key) or [] if (r.get("option") or {}).get("token")]
    for side in ("CE", "PE"):
        opt_rows += [r for r in (res.get("volume_oi_picks") or {}).get(side, []) if (r.get("option") or {}).get("token")]
    for k in ("5", "10"):
        opt_rows += [r for r in (res.get("swing") or {}).get(k, []) if (r.get("option") or {}).get("token")]
    for r in opt_rows:
        o = r["option"]
        toks.setdefault(o["exch"], []).append(o["token"])
    toks = {k: list(dict.fromkeys(v)) for k, v in toks.items()}
    qs = ag.quotes(toks)
    now = _now()
    session = pd.Timestamp(res["session"])
    _, live, mins = _session(qs.get(INDEX_SPOT["NIFTY"][1]), now)
    share = _vol_share(mins)
    live_q = {}
    for n in names:
        q = qs.get(inst["eq"][n])
        if q:
            avg = C["avgvol"].get(n) or 0
            vol = _f(q.get("tradeVolume"))
            live_q[n] = {"ltp": _f(q.get("ltp")), "pct": _f(q.get("percentChange")), "volume": int(vol),
                         "vol_ratio": round(vol / (avg * share), 2) if avg else 0.0}
    seen = set()
    for key in ("best", "ce", "pe", "orb_up", "orb_dn", "high_volume"):
        for r in res.get(key) or []:
            if id(r) in seen:
                continue
            seen.add(id(r))
            q = live_q.get(r["symbol"])
            if not q:
                continue
            if "price" in r:
                r["price"] = q["ltp"]
            if "ltp" in r:
                r["ltp"] = q["ltp"]
            r["pct"], r["vol_ratio"] = q["pct"], q["vol_ratio"]
            if "volume" in r:
                r["volume"] = q["volume"]
            if r.get("ref_level"):
                r["ext"] = round(abs(q["ltp"] - r["ref_level"]) / r["ref_level"] * 100, 2)
                beyond = q["ltp"] > r["ref_level"] if r.get("side") == "CE" else q["ltp"] < r["ref_level"]
                if not beyond:
                    r["status"] = "WATCH"
                    r["live_note"] = "Price level-க்கு உள்ளே திரும்பி வந்துவிட்டது"
                elif r.get("status") == "CONFIRMED" and r["ext"] > 1.0:
                    r["status"] = "EXTENDED"
    for r in opt_rows:
        o = r["option"]
        q = qs.get(o["token"])
        if q:
            o["ltp"] = _f(q.get("ltp"))
            b, a = _depth(q)
            if b and a:
                o["bid"], o["ask"] = b, a
    for x in res.get("index") or []:
        q = qs.get(INDEX_SPOT.get(x.get("index"), (None, None))[1])
        if q:
            x["spot"], x["pct"] = _f(q.get("ltp")), _f(q.get("percentChange"))
    try:
        from .calls import update_calls
        tr = update_calls(ag, session, now, live, [], [], [], [], {"10": [], "5": []}, add=False)
        res["tracking"] = tr
    except Exception:
        pass
    res["tick_time"] = str(now if not live else pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).floor("s"))
    return res
