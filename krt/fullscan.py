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
        C.update(session=session, levels={}, avgvol={}, swings={}, nifty_daily=None, feat={}, bars={}, first_seen={})
    if C["nifty_daily"] is None:
        df = ag.candles("NSE", INDEX_SPOT["NIFTY"][1], "ONE_DAY", session - pd.Timedelta(days=200), session)
        if not df.empty:
            df.index = df.index.normalize()
        C["nifty_daily"] = df
    todo = [n for n in names if n not in C["levels"] or n not in C.setdefault("bars", {})]
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
        tail = past.tail(130)
        C.setdefault("bars", {})[n] = {"t": [str(x.date()) for x in tail.index], "o": tail["open"].round(2).tolist(),
                                       "h": tail["high"].round(2).tolist(),
                                       "l": tail["low"].round(2).tolist(), "c": tail["close"].round(2).tolist(),
                                       "v": tail["volume"].tolist()}
        c = past["close"]
        if len(c) >= 60:
            e20, e50 = c.ewm(span=20).mean(), c.ewm(span=50).mean()
            tr = pd.concat([past["high"] - past["low"], (past["high"] - c.shift()).abs(), (past["low"] - c.shift()).abs()], axis=1).max(axis=1)
            e200 = c.ewm(span=200).mean()
            C.setdefault("feat", {})[n] = {"ema20": float(e20.iloc[-1]), "ema50": float(e50.iloc[-1]),
                                           "ema200": float(e200.iloc[-1]), "n_days": int(len(c)),
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


def seen(kind, r, now):
    fs = C.setdefault("first_seen", {})
    k = f"{kind}|{r['symbol']}|{r.get('side')}|{r.get('pattern', '')}"
    if k not in fs:
        fs[k] = now.strftime("%Y-%m-%d %H:%M")
    r["signal_time"] = fs[k]


def stars(score):
    return 5 if score >= 85 else 4 if score >= 70 else 3 if score >= 55 else 2 if score >= 40 else 1


def fill_targets(price, sl, side, tg, atr=None):
    """Realistic targets: structure levels — ஆனால் intraday-ல் ஒரு நாள் ATR-க்கு மேல் போகாது.
    குறைந்தால் ATR பங்குகள் (0.35 / 0.6 / 0.85 ATR); ATR தெரியலைன்னா 1R/1.5R/2R."""
    sgn = 1 if side == "CE" else -1
    risk = abs(price - sl) or price * 0.005
    cap = atr * 1.0 if atr else None
    lv = [t for t in tg if (t - price) * sgn > 0 and (cap is None or abs(t - price) <= cap)]
    lv = sorted(lv, key=lambda t: abs(t - price))[:3]
    kinds = ["level"] * len(lv)
    steps = [(0.35, "0.35 ATR"), (0.6, "0.6 ATR"), (0.85, "0.85 ATR")] if atr else [(1, "1R"), (1.5, "1.5R"), (2, "2R")]
    for m, lab in steps:
        if len(lv) >= 3:
            break
        t = price + sgn * m * (atr if atr else risk)
        if t > 0 and all(abs(t - x) > price * 0.001 and (t - x) * sgn > 0 for x in lv):
            lv.append(round(t, 2))
            kinds.append(lab)
    order = sorted(range(len(lv)), key=lambda i: abs(lv[i] - price))
    lv, kinds = [lv[i] for i in order], [kinds[i] for i in order]
    return lv, kinds


def apply_money(opt, spot, now, atr=None, intraday=True):
    """எல்லா plan-க்கும்: T1 ≥ ₹1,200 · T2 ≥ ₹3,000 · T3 ≥ ₹6,000 per lot + stock எவ்வளவு போகணும் என்ற realistic check."""
    from .optmath import money_targets, MONEY
    if not opt or "none" in opt or not opt.get("plan"):
        return
    try:
        m = load_settings().get("money_targets")
        if m and len(m) == 3:
            MONEY["mins"] = tuple(m)
        money_targets(opt["plan"], opt.get("lot"), spot, opt.get("strike"), opt.get("expiry"), opt.get("type"),
                      now.to_pydatetime() if hasattr(now, "to_pydatetime") else now, atr, intraday)
    except Exception:
        pass


def attach_plan(r, opt, now, source=None):
    """r: price, sl, targets, side → opt['plan'] (premium ESTIMATE) + history-calibrated targets."""
    if not opt or "none" in opt:
        return
    atr = ((C.get("feat") or {}).get(r.get("symbol")) or {}).get("atr")
    tg, kinds = fill_targets(r["price"], r["sl"], r["side"], r.get("targets") or [], atr)
    r["targets"], r["target_kinds"] = tg, kinds
    risk_ul = abs(r["price"] - r["sl"]) or 1e-9
    r["rr"] = round(abs(tg[0] - r["price"]) / risk_ul, 2) if tg else 0
    r["low_rr"] = r["rr"] < 1.0   # T1 ≥ 1R இல்லைன்னா தரம் குறைவு
    cfg = load_settings().get("risk", {})
    prem = opt.get("ask") or opt.get("ltp")
    try:
        opt["plan"] = prem_plan(prem, r["price"], opt["strike"], opt["expiry"], opt["type"], r["sl"], tg,
                            now.to_pydatetime(), opt["lot"], cfg.get("charges_slippage", 150),
                            cfg.get("max_risk_per_trade", 2500))
    except Exception:
        opt["plan"] = None
    if source and opt.get("plan"):
        from .calls import calibrate_plan
        calibrate_plan(source, opt["plan"])
    apply_money(opt, r["price"], now, atr, intraday=not r.get("hold"))
    p_ = opt.get("plan") or {}
    if p_ and p_.get("risk_ok") is False and r.get("option_alts") and not r.get("_alt"):
        r["_alt"] = True          # ATM / ITM risk cap-ஐ தாண்டினா cheaper strike (1 OTM) — SL-ஐ tight பண்ணாம
        for alt in r["option_alts"]:
            if alt["contract"] == opt.get("contract"):
                continue
            attach_plan(r, alt, now, source)
            ap = alt.get("plan") or {}
            if ap.get("risk_ok") and ap.get("reward_ok", True):
                alt["alt_reason"] = f"{opt.get('moneyness')} {opt.get('strike'):g} risk ₹{p_.get('risk')} > cap → {alt['moneyness']} {alt['strike']:g} (risk ₹{ap.get('risk')})"
                r["option"] = alt
                break
        r.pop("_alt", None)


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
        otm = strikes[i + 1] if r["side"] == "CE" and i + 1 < len(strikes) else (strikes[i - 1] if r["side"] == "PE" and i > 0 else None)
        chosen = [c for c in cs if c[3] in (atm, itm, otm)]
        plan.append((r, chosen, atm))
        for c in chosen:
            toks.setdefault(c[6], []).append(c[0])
    qs = ag.quotes(toks) if toks else {}
    miss = {ex: [t for t in ts if t not in qs] for ex, ts in toks.items()}
    if any(miss.values()):
        time.sleep(1.2)                       # Angel rate-limit → ஒருமுறை மறுபடி
        try:
            qs.update(ag.quotes({ex: ts for ex, ts in miss.items() if ts}) or {})
        except Exception:
            pass
    for r, chosen, atm in plan:
        best, alts, ref = None, [], None
        if chosen and not any(qs.get(c[0]) for c in chosen):
            r["option"] = {"none": "Option quote வரல (API) — அடுத்த tick-ல் மறுபடி", "retry": True}
            continue
        smax = 6.0 if r.get("hold") else 5.0     # V5.3: stock options intraday 5% வரை (limit order), holding 6%
        for c in chosen:
            q = qs.get(c[0])
            if not q:
                continue
            bid, ask = _depth(q)
            mid = (bid + ask) / 2 if bid and ask else 0
            spread = (ask - bid) / mid * 100 if mid else 999
            mny = "ATM" if c[3] == atm else ("ITM" if ((c[3] < atm) == (r["side"] == "CE")) else "1 OTM")
            cand = {"token": c[0], "exch": c[6], "contract": c[1], "strike": c[3], "expiry": c[2], "type": c[4], "lot": c[5],
                    "moneyness": mny, "bid": bid, "ask": ask,
                    "ltp": _f(q.get("ltp")), "spread_pct": round(spread, 2), "oi": int(_f(q.get("opnInterest"))),
                    "volume": int(_f(q.get("tradeVolume"))), "lot_cost": round(ask * c[5])}
            if bid > 0 and (ref is None or ref.get("no_depth") or spread < ref["spread_pct"]):
                ref = cand
            elif not bid and cand["ltp"] > 0 and (ref is None or (ref.get("no_depth") and cand["oi"] > ref["oi"])):
                ref = dict(cand, no_depth=True, ask=cand["ltp"], bid=cand["ltp"])   # bid/ask இல்லை — LTP reference
            if spread <= smax and bid > 0:
                alts.append(cand)
                if mny != "1 OTM" and (best is None or cand["oi"] > best["oi"]):
                    best = cand
        if best and best["spread_pct"] > 3:
            best["wide_spread"] = True
            best["alt_reason"] = f"Spread {best['spread_pct']}% — limit order மட்டும் (market order வேண்டாம்)"
        if not best and ref:
            r["option_ref"] = dict(ref, wide_spread=True, alt_reason=("Bid/ask depth வரல — LTP reference (limit order)" if ref.get("no_depth")
                                   else f"Spread {ref['spread_pct']}% — liquidity குறைவு, reference மட்டும் (limit order)"))
        r["option"] = best or {"none": "STOCK SETUP VALID — NO SUITABLE OPTION (spread / liquidity குறைவு)" +
                               (f" · Reference: {ref['strike']:g} {ref['type']} ({ref['moneyness']}) expiry {ref['expiry']} · LTP {ref['ltp']} · spread {ref['spread_pct']}%" if ref else "")}
        r["option_alts"] = sorted([a for a in alts if not best or a["contract"] != best["contract"]], key=lambda a: a["ask"])


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
                "lot": c[5], "contract": c[1], "token": c[0], "exch": INDEX_OPT_EXCH[idx]}
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
            attach_plan(pr, opt, _now(), "Index OI")
            plans[sd] = {"ul_sl": pr["sl"], "ul_targets": pr["targets"], "kinds": pr.get("target_kinds"), "option": opt}
        out.append({"index": idx, "spot": spot, "pct": pct, "expiry": exp,
                    "day_high": _f((q or {}).get("high")) or spot, "day_low": _f((q or {}).get("low")) or spot,
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

    _before = len(C.get("bars") or {})
    ensure_daily(ag, inst, names, session, prog)
    if len(C.get("bars") or {}) > _before:   # புதிதாக எடுத்தது → GitHub-ல் save (restart-க்கு பின் மீண்டும் எடுக்க வேண்டாம்)
        try:
            from .store import BARS
            BARS.load()
            BARS.data = export_bars()
            BARS.dirty = True
            BARS.save(force=True)
        except Exception as e:
            errors.append(f"Bars save: {e}")
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
                         "high": _f(q.get("high")), "low": _f(q.get("low")), "open": op,
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
        seen("lvl", r, now)
        aligned = (trend == "TRENDING UP" and r["side"] == "CE") or (trend == "TRENDING DOWN" and r["side"] == "PE")
        r["strong"] = r["status"] == "CONFIRMED" and r["stars"] == 5 and r["vol_ratio"] >= 2 and aligned
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
    for r in orb_up + orb_dn:
        seen("orb", r, now)
        r["strong"] = r["status"] == "CONFIRMED" and r["stars"] >= 5

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

    for side in ("CE", "PE"):
        for r in voi[side]:
            seen("voi", r, now)

    # ---- Chart patterns (daily) ----
    prog("Chart patterns")
    from .patterns import detect as detect_patterns
    ulook = {u["symbol"]: u for u in universe}
    pats = []
    for n_, u in ulook.items():
        b, f_ = C.get("bars", {}).get(n_), (C.get("feat") or {}).get(n_)
        if not b or not f_:
            continue
        try:
            for p_ in detect_patterns(n_, b, u["ltp"], f_["atr"]):
                p_.update(price=u["ltp"], pct=u["pct"], vol_ratio=u["vol_ratio"], sl=p_["invalidation"])
                aligned = (trend == "TRENDING UP" and p_["side"] == "CE") or (trend == "TRENDING DOWN" and p_["side"] == "PE")
                p_["score"] = int(min(100, p_["score"] + (10 if aligned else 0) + (10 if u["vol_ratio"] >= 1.5 and p_["status"] in ("TRIGGERED", "CONFIRMED") else 0)))
                p_["stars"] = stars(p_["score"])
                p_["strong"] = p_["status"] in ("TRIGGERED", "CONFIRMED") and p_["stars"] >= 4 and u["vol_ratio"] >= 1.5
                seen("pat", p_, now)
                pats.append(p_)
        except Exception:
            continue
    order = {"CONFIRMED": 0, "TRIGGERED": 1, "NEAR BREAKOUT": 2, "FORMING": 3, "FAILED": 4}
    pats.sort(key=lambda p_: (order[p_["status"]], -p_["score"]))
    pats = pats[:40]
    pat_pick = [p_ for p_ in pats if p_["status"] in ("CONFIRMED", "TRIGGERED", "NEAR BREAKOUT")][:10]
    for p_ in pat_pick:
        p_["min_days"] = 10

    # ---- 👑 ELITE (user's 2 Chartink scanners) ----
    prog("Elite scan")
    elite = {"intraday": [], "holding": [], "jackpot": [], "almost": [], "checked": 0}
    elite_hold = []
    try:
        from .elite import scan as elite_scan
        nd_ = C.get("nifty_daily")
        nret = 0.0
        if nd_ is not None and not nd_.empty:
            pc_ = nd_[nd_.index < session]["close"]
            n_spot = _f((qs.get(INDEX_SPOT["NIFTY"][1]) or {}).get("ltp"))
            if len(pc_) > 21 and n_spot:
                nret = n_spot / float(pc_.iloc[-21]) - 1
        elite = elite_scan(ag, inst, C, universe, trend, bu_tag, nret, now, session, live)
        elite["time"] = now.strftime("%H:%M")
        for r in elite["intraday"]:
            seen("elite", r, now)
        for r in elite["holding"]:
            hr = dict(r)
            atr_ = r.get("atr") or r["price"] * 0.02
            sg = 1 if r["side"] == "CE" else -1
            hr.update(sl=r["hold_sl"], targets=[round(r["price"] + sg * m * atr_, 2) for m in (1.5, 3, 4.5)],
                      min_days=20, hold=10)
            seen("eliteh", hr, now)
            elite_hold.append(hr)
        elite["holding"] = elite_hold
    except Exception as e:
        errors.append(f"Elite: {e}")

    picks = top_ce + top_pe + orb_up[:5] + orb_dn[:5] + voi["CE"] + voi["PE"] + pat_pick + elite["intraday"][:8] + elite_hold[:6]
    pick_options(ag, inst, picks)
    for r in picks:
        if any(r is x for x in elite_hold):
            o_ = r.get("option")
            if o_ and "none" not in o_:
                cfg_ = load_settings().get("risk", {})
                try:
                    o_["plan"] = prem_plan(o_.get("ask") or o_.get("ltp"), r["price"], o_["strike"], o_["expiry"], o_["type"],
                                           r["sl"], r["targets"], now.to_pydatetime(), o_["lot"],
                                           cfg_.get("charges_slippage", 150), cfg_.get("max_risk_holding", 5000),
                                           hold_days=7, sl_days=2)
                    from .calls import calibrate_plan
                    calibrate_plan("Elite holding", o_["plan"])
                    apply_money(o_, r["price"], now, r.get("atr"), intraday=False)
                except Exception:
                    o_["plan"] = None
            continue
        if any(r is x for x in elite["intraday"]):
            attach_plan(r, r.get("option"), now, "Elite intraday")
            continue
        if r in pat_pick:
            o_ = r.get("option")
            if o_ and "none" not in o_:
                cfg_ = load_settings().get("risk", {})
                try:
                    o_["plan"] = prem_plan(o_.get("ask") or o_.get("ltp"), r["price"], o_["strike"], o_["expiry"], o_["type"],
                                           r["invalidation"], r["targets"], now.to_pydatetime(), o_["lot"],
                                           cfg_.get("charges_slippage", 150), cfg_.get("max_risk_holding", 5000),
                                           hold_days=3, sl_days=1)
                    from .calls import calibrate_plan
                    calibrate_plan("Chart pattern", o_["plan"])
                    apply_money(o_, r["price"], now, ((C.get("feat") or {}).get(r["symbol"]) or {}).get("atr"), intraday=False)
                except Exception:
                    o_["plan"] = None
            continue
        src_ = ("5-min ORB" if r in orb_up or r in orb_dn else "Volume+OI" if r in voi["CE"] or r in voi["PE"]
                else "Breakout/Breakdown")
        attach_plan(r, r.get("option"), now, src_)
        if r.get("low_rr"):
            r["stars"] = max(1, r.get("stars", 1) - 1)
            r["strong"] = False

    prog("Index option OI")
    gex = []
    try:
        idx = index_oi(ag, inst, qs)
        try:     # ⚡ Gamma Blast V3 — index GEX (estimated, completed 5-min candles confirm)
            from .v3 import gex_index
            for x_ in idx:
                if x_.get("chain"):
                    ex_, tk_ = INDEX_SPOT[x_["index"]]
                    cdl = ag.candles(ex_, tk_, "FIVE_MINUTE", pd.Timestamp(session) + pd.Timedelta(hours=9, minutes=15), now)
                    gex.append(gex_index(x_, now, cdl))
        except Exception as e:
            errors.append(f"Gamma V3: {e}")
    except Exception as e:
        idx = []
        errors.append(f"Index OI: {e}")
    footprint = build_footprint(idx, universe, bu_tag, now)
    prog("Gamma blast")
    from .gamma import index_gamma, stock_gamma
    try:
        cap_ = load_settings().get("risk", {}).get("max_risk_per_trade", 2500)
        g_idx, g_cal = index_gamma(idx, now, cap_)
        g_stk = stock_gamma(ag, inst, universe, now, contracts, cap_) if live else []
        gamma = {"index": g_idx, "stocks": g_stk, "calendar": g_cal}
    except Exception as e:
        gamma = {"index": [], "stocks": [], "calendar": []}
        errors.append(f"Gamma: {e}")
    hv = sorted(universe, key=lambda u: -u["vol_ratio"])[:20]
    for u in hv:
        u["oi_tag"] = bu_tag.get(u["symbol"], "")
    if has_orb:
        got = sum(1 for n in names if C["orb"].get(n))
        if got < len(names) * 0.8:
            errors.append(f"5-min ORB data {got}/{len(names)} stocks மட்டும் கிடைத்தது — அடுத்த scan-ல் மீதி எடுக்கும்")
    best = [r for r in ce + pe if r["status"] == "CONFIRMED" and "none" not in (r.get("option") or {"none": 1})
            and not r.get("low_rr")]
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
        from .calls import MARKET as _MK
        _MK["trend"] = trend
        _MK["nifty_pct"] = next((x.get("pct") for x in (idx or []) if x.get("index") == "NIFTY"), None)
        track = update_calls(ag, session, now, live, best, orb_up[:3] + orb_dn[:3], voi["CE"] + voi["PE"], idx, swing,
                             patterns=[p_ for p_ in pat_pick if p_["status"] in ("CONFIRMED", "TRIGGERED") and p_["vol_ratio"] >= 1.5],
                             gamma=[g for g in gamma["index"] + gamma["stocks"] if g["status"] == "TRIGGERED"],
                             elite=[r for r in elite["intraday"] if elite_ok(r, now, trend)],
                             elite_hold=[r for r in elite_hold if r["confidence"] >= 80],
                             footprint=footprint.get("index") or [],
                             gex=[dict(g_, plans=next((x.get("plans") for x in idx if x.get("index") == g_.get("index")), None)) for g_ in gex])
    except Exception as e:
        track = {"today": [], "history": [], "jackpot": [], "summary": {}, "swing_published": None}
        errors.append(f"Tracking: {e}")

    for key_ in ("10", "5"):
        for r in swing.get(key_, []):
            seen("swing", r, now)
    _res = {"kind": "full", "time": str(now), "volume_oi_picks": voi, "patterns": pats, "gamma": gamma, "elite": elite, "footprint": footprint, "tracking": track, "swing": swing, "session": str(session.date()), "live": live,
            "trend": trend, "summary": summary, "best": best[:6], "ce": ce[:25], "pe": pe[:25],
            "orb_up": orb_up, "orb_dn": orb_dn, "orb_ready": has_orb, "high_volume": hv,
            "oi_buildup": bu, "index": idx, "gex": gex, "universe_count": len(universe),
            "errors": errors, "seconds": round(time.time() - t_start)}
    _res["gu_snap"] = (C.get("_gu_snap") or {})
    try:
        _res["orb2"] = run_v2_rows(orb_up[:5] + orb_dn[:5], "ORB", "5-min ORB", now, live, _res, need=lambda r: r.get("status") == "CONFIRMED")
        _res["voi2"] = run_v2_rows(voi["CE"] + voi["PE"], "VOI", "Volume+OI", now, live, _res)
    except Exception as e:
        _res.setdefault("errors", []).append(f"ORB/VOI V2: {e}")
    try:
        _res["bo2"] = run_breakouts(ag, inst, _res, universe, now, live)
    except Exception as e:
        _res.setdefault("errors", []).append(f"Breakout V2: {e}")
    try:
        compute_all_rounder(_res)
    except Exception as e:
        _res.setdefault("errors", []).append(f"All rounder: {e}")
    return _res




def build_footprint(idx, universe, bu_tag, now):
    """OI footprint (proxy) — option writers (sellers) எங்கே OI சேர்க்கிறார்கள், futures buildup + அதிக volume.
    இது உண்மையான institution order data இல்லை; public OI / volume-ல் இருந்து ஊகம் மட்டும்."""
    out = {"index": [], "stocks": []}
    for x in idx:
        ch = x.get("chain") or []
        if not ch:
            continue
        ce_add = sorted(ch, key=lambda r: -(r.get("CE", {}).get("chg", 0)))[:3]
        pe_add = sorted(ch, key=lambda r: -(r.get("PE", {}).get("chg", 0)))[:3]
        ce_cut = sorted(ch, key=lambda r: r.get("CE", {}).get("chg", 0))[:2]
        pe_cut = sorted(ch, key=lambda r: r.get("PE", {}).get("chg", 0))[:2]
        ce_sum = sum(max(0, r.get("CE", {}).get("chg", 0)) for r in ch)
        pe_sum = sum(max(0, r.get("PE", {}).get("chg", 0)) for r in ch)
        if pe_sum > ce_sum * 1.3:
            bias, why = "CE", "Put writers (sellers) அதிகம் OI சேர்க்கிறார்கள் → கீழே support வலுவாகிறது"
        elif ce_sum > pe_sum * 1.3:
            bias, why = "PE", "Call writers (sellers) அதிகம் OI சேர்க்கிறார்கள் → மேலே resistance வலுவாகிறது"
        else:
            bias, why = None, "இரண்டு பக்கமும் சமம் — range / wait"
        pl = (x.get("plans") or {}).get(bias) if bias else None
        out["index"].append({
            "index": x["index"], "spot": x.get("spot"), "bias": bias, "why": why,
            "ce_writing": [{"strike": r["strike"], "chg": r["CE"]["chg"]} for r in ce_add if r.get("CE", {}).get("chg", 0) > 0],
            "pe_writing": [{"strike": r["strike"], "chg": r["PE"]["chg"]} for r in pe_add if r.get("PE", {}).get("chg", 0) > 0],
            "ce_unwind": [{"strike": r["strike"], "chg": r["CE"]["chg"]} for r in ce_cut if r.get("CE", {}).get("chg", 0) < 0],
            "pe_unwind": [{"strike": r["strike"], "chg": r["PE"]["chg"]} for r in pe_cut if r.get("PE", {}).get("chg", 0) < 0],
            "ce_added": int(ce_sum), "pe_added": int(pe_sum), "plan": pl})
    for u in universe:
        k = bu_tag.get(u["symbol"], "")
        if u["vol_ratio"] >= 3 and k and abs(u["pct"]) >= 1.5:
            side = "CE" if k in ("Long Built Up", "Short Covering") else "PE"
            r = {"symbol": u["symbol"], "side": side, "ltp": u["ltp"], "pct": u["pct"], "vol_ratio": u["vol_ratio"],
                 "oi_tag": k, "note": f"Volume {u['vol_ratio']}× + {k}"}
            seen("fp", r, now)
            out["stocks"].append(r)
    out["stocks"].sort(key=lambda r: -r["vol_ratio"])
    out["stocks"] = out["stocks"][:15]
    return out


def export_cache():
    """Daily levels / features / ORB — session-க்கு ஒருமுறை கணக்கிட்டது (restart-க்கு பின் மீண்டும் எடுக்க வேண்டாம்)."""
    if C["session"] is None:
        return None
    nd = C.get("nifty_daily")
    return {"session": str(C["session"].date()), "levels": C["levels"], "avgvol": C["avgvol"],
            "swings": C["swings"], "feat": C.get("feat", {}),
            "orb_session": str(C["orb_session"].date()) if C.get("orb_session") is not None else None,
            "orb": C.get("orb", {}), "oi_day": C.get("oi_day"), "oi_base": C.get("oi_base", {}),
            "first_seen": C.get("first_seen", {}),
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
    C.update(oi_day=d.get("oi_day"), oi_base=d.get("oi_base", {}), first_seen=d.get("first_seen", {}))
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
    for key in ("best", "ce", "pe", "orb_up", "orb_dn", "patterns"):
        opt_rows += [r for r in res.get(key) or [] if (r.get("option") or {}).get("token")]
    for side in ("CE", "PE"):
        opt_rows += [r for r in (res.get("volume_oi_picks") or {}).get(side, []) if (r.get("option") or {}).get("token")]
    for k in ("5", "10"):
        opt_rows += [r for r in (res.get("swing") or {}).get(k, []) if (r.get("option") or {}).get("token")]
    for r in opt_rows:
        o = r["option"]
        toks.setdefault(o["exch"], []).append(o["token"])
    g = res.get("gamma") or {}
    g_items = (g.get("index") or []) + (g.get("stocks") or [])
    for it in g_items:
        o = it.get("option") or {}
        if o.get("token"):
            toks.setdefault(o["exch"], []).append(o["token"])
    for a_ in res.get("all_rounder") or []:
        o_ = a_.get("option") or {}
        if o_.get("token") and o_.get("exch"):
            toks.setdefault(o_["exch"], []).append(o_["token"])
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
                         "vol_ratio": round(vol / (avg * share), 2) if avg else 0.0,
                         "high": _f(q.get("high")), "low": _f(q.get("low")), "open": _f(q.get("open"))}
    try:
        res["movers"] = run_movers(ag, inst, live_q, res, now, live)
        res["movers"]["gainers"] = [{"symbol": k_, **v_} for k_, v_ in res["movers"]["gainers"]]
        res["movers"]["losers"] = [{"symbol": k_, **v_} for k_, v_ in res["movers"]["losers"]]
    except Exception as e:
        res.setdefault("errors", []).append(f"Movers: {e}")
    try:
        res["strong"] = run_strong(ag, inst, live_q, res, now, live)
    except Exception as e:
        res.setdefault("errors", []).append(f"Strong: {e}")
    try:
        res["ai"] = run_ai(live_q, res, now, live)
    except Exception as e:
        res.setdefault("errors", []).append(f"AI: {e}")
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
    for p_ in res.get("patterns") or []:
        q = live_q.get(p_["symbol"])
        if not q or p_["status"] in ("CONFIRMED", "FAILED"):
            continue
        ltp = q["ltp"]
        ce = p_["side"] == "CE"
        p_["price"], p_["pct"], p_["vol_ratio"] = ltp, q["pct"], q["vol_ratio"]
        p_["dist_pct"] = round(((p_["level"] - ltp) if ce else (ltp - p_["level"])) / ltp * 100, 2)
        if (ltp < p_["invalidation"]) if ce else (ltp > p_["invalidation"]):
            p_["status"] = "FAILED"
        elif p_["dist_pct"] < 0:
            if p_["status"] != "TRIGGERED":
                p_["triggered_at"] = str(now)[11:16]
            p_["status"] = "TRIGGERED"
        elif p_["dist_pct"] <= 2:
            p_["status"] = "NEAR BREAKOUT"
    for x in res.get("index") or []:
        q = qs.get(INDEX_SPOT.get(x.get("index"), (None, None))[1])
        if q:
            x["spot"], x["pct"] = _f(q.get("ltp")), _f(q.get("percentChange"))
    try:
        res["momentum"] = momentum_watch(live_q, now, res.get("trend"), live)
    except Exception as e:
        res["momentum_err"] = str(e)
    for a_ in res.get("all_rounder") or []:    # 🏅 All rounder: live stock + option LTP, T1 tick, volume light
        try:
            q_ = live_q.get(a_["symbol"])
            if q_:
                a_["price"], a_["vol_ratio"] = q_["ltp"], q_["vol_ratio"]
            o_ = a_.get("option") or {}
            oq_ = qs.get(o_.get("token")) if o_.get("token") else None
            if oq_:
                o_["ltp"] = _f(oq_.get("ltp"))
            ar_live(a_, now)
        except Exception:
            pass
    if res.get("all_rounder"):
        smart_refresh(res)
    if g_items:
        from .gamma import retick
        spot_q = {}
        for name_, (ex_, tok_) in INDEX_SPOT.items():
            q = qs.get(tok_)
            if q:
                spot_q[name_] = {"ltp": _f(q.get("ltp")), "high": _f(q.get("high")), "low": _f(q.get("low"))}
        for n_, v_ in live_q.items():
            spot_q.setdefault(n_, {"ltp": v_["ltp"]})
        retick(g_items, spot_q, qs, now)
    try:
        from .calls import update_calls
        tr = update_calls(ag, session, now, live, [], [], [], [], {"10": [], "5": []}, add=False,
                          gamma=[x for x in g_items if x["status"] == "TRIGGERED"])
        res["tracking"] = tr
    except Exception:
        pass
    res["tick_time"] = str(now if not live else pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).floor("s"))
    return res


def elite_ok(r, now, trend):
    """Elite upgrade: 9:45 பிறகு · confidence ≥80 · EMA20-ல் இருந்து ≤1.5 ATR · market regime ஒத்துப்போகணும்."""
    from .sniper import REGIME
    mins = now.hour * 60 + now.minute
    if mins < 9 * 60 + 45 or r.get("confidence", 0) < 75 or (r.get("ext_atr") or 0) > 1.8 or not r.get("in_window", True):
        return False
    want = r["side"]
    st_ = REGIME.get("state")
    if st_ == "TRENDING":       # market direction-உடன் மட்டும் (V6: 75+)
        return {"UP": "CE", "DOWN": "PE"}.get(REGIME.get("dir")) == want
    if st_ == "HIGH-VOL":
        return r.get("confidence", 0) >= 90
    # V4: RANGE நாளில் — daily trend ஒத்துப்போனா 80+, அல்லது NIFTY இன்றைய direction எதிர் இல்லைன்னா 80+, இல்லைன்னா 85+
    daily_ok = (trend == "TRENDING UP" and want == "CE") or (trend == "TRENDING DOWN" and want == "PE")
    try:
        from .calls import MARKET as _MK
        np_ = _MK.get("nifty_pct") or 0
    except Exception:
        np_ = 0
    day_ok = (want == "CE" and np_ > -0.15) or (want == "PE" and np_ < 0.15)
    c_ = r.get("confidence", 0)
    return ((daily_ok or day_ok) and c_ >= 75) or c_ >= 85


def run_power(ag, res):
    """🎯 POWER OI cycle (5 நிமிடத்துக்கு ஒருமுறை)."""
    from .sniper import run as sniper_run
    from .calls import update_calls
    if not res or not C.get("levels"):
        return res
    inst = load_inst(ROOT / "data" / "cache")
    names = [n for n in inst["fno"] if n in inst["eq"]]
    toks = {"NSE": [inst["eq"][n] for n in names]}
    for ex, tok in INDEX_SPOT.values():
        toks.setdefault(ex, []).append(tok)
    qs = ag.quotes(toks)
    now = _now()
    session, live, mins = _session(qs.get(INDEX_SPOT["NIFTY"][1]), now)
    share = _vol_share(mins)
    universe = []
    for n in names:
        q = qs.get(inst["eq"][n])
        if not q:
            continue
        avg = C["avgvol"].get(n) or 0
        vol = _f(q.get("tradeVolume"))
        universe.append({"symbol": n, "ltp": _f(q.get("ltp")), "pct": _f(q.get("percentChange")),
                         "vol_ratio": round(vol / (avg * share), 2) if avg else 0.0})
    today_calls = ((res.get("tracking") or {}).get("today")) or []
    pw = sniper_run(ag, inst, C, universe, now, session, contracts, today_calls)
    res["power"] = pw
    res["gu_snap"] = C.get("_gu_snap") or res.get("gu_snap")
    try:
        compute_all_rounder(res)
    except Exception:
        pass
    try:
        res["tracking"] = update_calls(ag, session, now, live, [], [], [], [], {"10": [], "5": []}, add=False,
                                       power=pw["signals"])
    except Exception:
        pass
    return res


MOVERS = {"min_pct": 2.0, "min_vr": 1.5, "max_calls": 25, "min_score": 85, "max_spread": 5}   # V6: 🟢 green மட்டும் call


def run_v2_rows(rows, kind, src, now, live, res, max_day=4, need=None):
    """⚡ 5-min ORB / Volume+OI V2 — quality-gate block இல்லாம நேரடி call: volume ≥1.5× · late இல்லை · NIFTY பெரிய எதிர் இல்லை ·
    option + ₹ plan (SL ≤ ₹2,500) · ★ rating · 9:20–2:30 · module-க்கு நாளைக்கு max 4."""
    from .calls import rupee_plan, add_simple
    mins = now.hour * 60 + now.minute
    npct = next((x.get("pct") for x in res.get("index") or [] if x.get("index") == "NIFTY"), 0) or 0
    out = []
    for r in rows:
        o = r.get("option") or {}
        p = o.get("plan") or {}
        if not (o.get("token") and p.get("entry") and o.get("lot")):
            continue
        if need and not need(r):
            continue
        if (r.get("vol_ratio") or 0) < 1.5 or (r.get("ext") or 0) > 1.2:
            continue
        if (r["side"] == "CE" and npct <= -0.5) or (r["side"] == "PE" and npct >= 0.5):
            continue
        sl_, tg_, rk_, rc_ = rupee_plan(p["entry"], p.get("sl"), o["lot"], False)
        if "SL_TIGHT" in rc_ or (o.get("spread_pct") or 0) > 8:
            continue
        sc = int(r.get("score") or 60)
        r2 = dict(r, stars=5 if sc >= 85 else 4 if sc >= 75 else 3 if sc >= 65 else 2,
                  rp={"entry": p["entry"], "sl": sl_, "targets": tg_, "risk": rk_, "t_rs": [round((t - p["entry"]) * o["lot"]) for t in tg_]})
        out.append(r2)
    out.sort(key=lambda r: -(r.get("score") or 0))
    if live and 9 * 60 + 20 <= mins <= 14 * 60 + 30:
        try:
            add_simple(kind, src, [r for r in out if (r.get("score") or 0) >= 60], now, max_day)
        except Exception as e:
            res.setdefault("errors", []).append(f"{src} V2: {e}")
    return out[:8]


def run_breakouts(ag, inst, res, universe, now, live):
    """📈📉 BREAKOUT CE / BREAKDOWN PE V2 — PDH/PWH/PMH மேல் (CE) / PDL/PWL/PML கீழ் (PE) fresh break · volume ≥1.5× ·
    level-ல் இருந்து ≤1% · day range சரியான பக்கம் · NIFTY பெரிய எதிர் move இல்லை → strike + ₹ plan + ★ rating → call."""
    from .calls import rupee_plan, add_breakouts
    mins = now.hour * 60 + now.minute
    U = {u["symbol"]: u for u in universe}
    bu_tag = {}
    for kind, rows in (res.get("oi_buildup") or {}).items():
        for x in rows:
            bu_tag[x["symbol"]] = kind
    npct = next((x.get("pct") for x in res.get("index") or [] if x.get("index") == "NIFTY"), 0) or 0
    out = {"CE": [], "PE": []}
    for side, key in (("CE", "ce"), ("PE", "pe")):
        for r0 in res.get(key) or []:
            u = U.get(r0["symbol"]) or {}
            vr, ext = r0.get("vol_ratio") or 0, r0.get("ext") or 9
            hi, lo, ltp = u.get("high") or 0, u.get("low") or 0, r0.get("price") or 0
            if r0.get("gap_only") or vr < 1.5 or ext > 1.0 or not (hi > lo > 0):
                continue
            pos = (ltp - lo) / (hi - lo)
            if (side == "CE" and pos < 0.6) or (side == "PE" and pos > 0.4):
                continue
            if (side == "CE" and npct <= -0.4) or (side == "PE" and npct >= 0.4):
                continue
            k = bu_tag.get(r0["symbol"], "")
            oi_ok = (side == "CE" and k in ("Long Built Up", "Short Covering")) or (side == "PE" and k in ("Short Built Up", "Long Unwinding"))
            lvl = r0.get("ref_key", "")
            sc = 30 + min(25, vr * 8) + (15 if lvl[1:2] == "M" else 10 if lvl[1:2] == "W" else 5) + (10 if ext <= 0.5 else 5)
            sc += 10 if oi_ok else 0
            sc += 5 if (pos >= 0.8 if side == "CE" else pos <= 0.2) else 0
            sc += 5 if (side == "CE" and npct > 0.1) or (side == "PE" and npct < -0.1) else 0
            sc = int(min(100, sc))
            r = {"symbol": r0["symbol"], "side": side, "price": ltp, "pct": r0.get("pct"), "vol_ratio": vr, "levels": r0.get("levels"),
                 "ref_level": r0.get("ref_level"), "sl": r0.get("sl"), "targets": list(r0.get("targets") or []), "score": sc,
                 "stars": 5 if sc >= 85 else 4 if sc >= 75 else 3 if sc >= 65 else 2, "min_days": 1,
                 "why": [f"{'+'.join(r0.get('levels') or [])} {'break' if side == 'CE' else 'breakdown'} · {ext}% தூரம்", f"Volume {vr}×",
                         f"Day range-ல் {int(pos * 100)}%", f"OI: {k or 'தெரியல'}"]}
            out[side].append(r)
        out[side].sort(key=lambda r: -r["score"])
        out[side] = out[side][:4]
    rows = out["CE"] + out["PE"]
    if rows:
        pick_options(ag, inst, rows)
    for r in rows:
        if "none" in (r.get("option") or {}) and r.get("option_ref"):
            r["option"] = r["option_ref"]
        attach_plan(r, r.get("option"), now, "Breakout/Breakdown")
        o = r.get("option") or {}
        p = o.get("plan") or {}
        if p.get("entry") and o.get("lot"):
            sl_, tg_, rk_, rc_ = rupee_plan(p["entry"], p.get("sl"), o["lot"], False)
            r["rp"] = {"entry": p["entry"], "sl": sl_, "targets": tg_, "risk": rk_, "t_rs": [round((t - p["entry"]) * o["lot"]) for t in tg_], "codes": rc_}
    if live and 9 * 60 + 30 <= mins <= 14 * 60:
        try:
            add_breakouts([r for r in rows if r["score"] >= 65 and r.get("rp") and not r["rp"]["codes"]
                           and ((r.get("option") or {}).get("spread_pct") or 99) <= 5], now)
        except Exception as e:
            res.setdefault("errors", []).append(f"Breakout calls: {e}")
    return {"time": now.strftime("%H:%M"), "CE": out["CE"], "PE": out["PE"]}


STRONG = {"start": 9 * 60 + 30, "end": 14 * 60 + 30, "max_dist": 1.2, "vol_x": 2.0, "day_vr": 1.5, "fresh_bars": 3,
          "max_check": 8, "max_day": 6}


def run_strong(ag, inst, live_q, res, now, live):
    """🟠 STRONG BREAK — ஒரே completed 5-min candle-ல்: 1st 5-min candle (ORB) break + PDH/PDL break + (PWH/PWL bonus) +
    volume ≥2× + fresh break (கடைசி 3 bars-க்குள்) + வலுவான candle + NIFTY எதிர் இல்லை → orange alert + call."""
    from .calls import rupee_plan, add_simple
    mins = now.hour * 60 + now.minute
    if mins < 9 * 60 + 21:
        return {"time": now.strftime("%H:%M"), "rows": [], "note": "முதல் 5-min candle (9:15–9:20) முடியட்டும்"}
    npct = next((x.get("pct") for x in res.get("index") or [] if x.get("index") == "NIFTY"), 0) or 0
    bu_tag = {}
    for kind, rows in (res.get("oi_buildup") or {}).items():
        for x in rows:
            bu_tag[x["symbol"]] = kind
    cands = []
    for n, q in live_q.items():
        lv = (C.get("levels") or {}).get(n) or {}
        ltp, vr = q.get("ltp") or 0, q.get("vol_ratio") or 0
        if not ltp or vr < STRONG["day_vr"] or ltp <= 50:
            continue
        for side, key in (("CE", "PDH"), ("PE", "PDL")):
            lvl = lv.get(key)
            if not lvl:
                continue
            beyond = ltp > lvl if side == "CE" else ltp < lvl
            dist = abs(ltp - lvl) / lvl * 100
            if beyond and dist <= STRONG["max_dist"]:
                cands.append((vr, n, side, lv))
    cands.sort(key=lambda x: -x[0])
    cache = C.setdefault("strong_cache", {})
    slot = now.floor("5min") if hasattr(now, "floor") else now
    t0 = pd.Timestamp(now.date()) + pd.Timedelta(hours=9, minutes=15)
    out = []
    for vr, n, side, lv in cands[:STRONG["max_check"]]:
        ck = f"{slot}|{n}|{side}"
        if ck in cache:
            if cache[ck]:
                out.append(cache[ck])
            continue
        r = None
        try:
            tok = inst["eq"].get(n)
            df = ag.candles("NSE", tok, "FIVE_MINUTE", t0, now)
            df = df[df.index + pd.Timedelta(minutes=5) <= now] if df is not None and not df.empty else df
        except Exception:
            df = None
        if df is not None and len(df) >= 2:
            ce = side == "CE"
            o1h, o1l = float(df["high"].iloc[0]), float(df["low"].iloc[0])
            last = df.iloc[-1]
            cl = df["close"].values
            pd_, pw = lv.get("PDH" if ce else "PDL"), lv.get("PWH" if ce else "PWL")
            vols = df["volume"].values
            base = vols[1:-1].mean() if len(vols) > 2 else vols[0]
            rng = float(last["high"] - last["low"]) or 1e-9
            body = abs(float(last["close"] - last["open"])) / rng
            near = (float(last["close"] - last["low"]) / rng) if ce else (float(last["high"] - last["close"]) / rng)
            fresh = any(((cl[i - 1] <= pd_) if ce else (cl[i - 1] >= pd_)) for i in range(max(1, len(cl) - STRONG["fresh_bars"]), len(cl))) \
                if len(cl) > 1 else True
            chk = {"1st 5-min candle break": bool(cl[-1] > o1h if ce else cl[-1] < o1l),
                   f"{'PDH' if ce else 'PDL'} break (5m close)": bool(cl[-1] > pd_ if ce else cl[-1] < pd_),
                   f"{'PWH' if ce else 'PWL'} break": bool(pw and (cl[-1] > pw if ce else cl[-1] < pw)),
                   f"Volume ≥{STRONG['vol_x']:g}× (5m)": bool(base and vols[-1] >= STRONG["vol_x"] * base),
                   "Fresh break (late இல்லை)": bool(fresh),
                   "வலுவான candle": bool(body >= 0.5 and near >= 0.7 and ((last["close"] > last["open"]) == ce)),
                   "NIFTY எதிர் இல்லை": not ((ce and npct <= -0.3) or (not ce and npct >= 0.3))}
            k = bu_tag.get(n, "")
            oi_ok = (ce and k in ("Long Built Up", "Short Covering")) or (not ce and k in ("Short Built Up", "Long Unwinding"))
            w = [25, 25, 15, 20, 10, 5, 0]
            sc = sum(wi for wi, v in zip(w, chk.values()) if v) + (5 if oi_ok else 0) + min(10, int(vr * 2))
            must = ["1st 5-min candle break", f"{'PDH' if ce else 'PDL'} break (5m close)", f"Volume ≥{STRONG['vol_x']:g}× (5m)",
                    "Fresh break (late இல்லை)", "வலுவான candle", "NIFTY எதிர் இல்லை"]
            strong = all(chk[m] for m in must)
            q = live_q[n]
            r = {"symbol": n, "side": side, "price": q.get("ltp"), "pct": q.get("pct"), "vol_ratio": vr, "score": int(min(100, sc)),
                 "checks": chk, "strong": strong, "oi": k, "bar": (df.index[-1] + pd.Timedelta(minutes=5)).strftime("%H:%M"), "level": pd_, "pwl": pw,
                 "sl": round(min(o1l, float(last["low"])) if ce else max(o1h, float(last["high"])), 2), "targets": [],
                 "min_days": 1, "found": now.strftime("%H:%M"),
                 "reasons": [f"🟠 {'1st 5m high' if ce else '1st 5m low'} + {'PDH' if ce else 'PDL'} break" + (" + PW break" if chk[f"{'PWH' if ce else 'PWL'} break"] else ""),
                             f"5m volume {vols[-1] / base:.1f}× · day {vr}×" if base else f"day volume {vr}×", f"OI: {k or 'தெரியல'}"]}
        cache[ck] = r
        if r:
            out.append(r)
    for k_ in [k_ for k_ in cache if not k_.startswith(str(slot))]:
        cache.pop(k_, None)
    out.sort(key=lambda r: (-int(r["strong"]), -r["score"]))
    S = [r for r in out if r["strong"]][:6]
    LOG = C.setdefault("strong_log", {})
    for r in S:
        LOG.setdefault(f"{now.date()}|{r['symbol']}|{r['side']}", {"date": str(now.date()), "time": r["bar"], "symbol": r["symbol"], "side": r["side"],
                                                                   "price": r["price"], "score": r["score"]})
    for k_ in [k_ for k_ in LOG if not k_.startswith(str(now.date()))]:
        LOG.pop(k_, None)
    if S:
        pick_options(ag, inst, S)
        for r in S:
            attach_plan(r, r.get("option"), now, "Strong Break")
            o = r.get("option") or {}
            p = o.get("plan") or {}
            if p.get("entry") and o.get("lot"):
                sl_, tg_, rk_, rc_ = rupee_plan(p["entry"], p.get("sl"), o["lot"], False)
                r["rp"] = {"entry": p["entry"], "sl": sl_, "targets": tg_, "risk": rk_, "t_rs": [round((t - p["entry"]) * o["lot"]) for t in tg_]}
        if live and STRONG["start"] <= mins <= STRONG["end"]:
            try:
                add_simple("STRONG", "🟠 Strong Break", [r for r in S if r.get("rp") and (r.get("option") or {}).get("spread_pct", 99) <= 5],
                           now, STRONG["max_day"])
            except Exception as e:
                res.setdefault("errors", []).append(f"Strong calls: {e}")
    return {"time": now.strftime("%H:%M:%S"), "rows": out[:10], "cfg": STRONG, "log": sorted(LOG.values(), key=lambda x: x["time"], reverse=True)}


def run_ai(live_q, res, now, live):
    """🤖 AI Picks + 🚨 market risk — fast tick-ல் (≈30 sec)."""
    from .ai import AI, STATE as AST, feats, predict, train, market_risk
    from .calls import add_aipick
    from .store import STORE
    risk = market_risk(live_q, res, now)
    if not AST.get("_t") or (now - AST["_t"]).total_seconds() > 300:
        try:
            _all = list((STORE.load().get("calls") or {}).values())
            train(_all)
            from .ai import optimize
            optimize(_all)
        except Exception:
            pass
        AST["_t"] = now
    M = AST.get("model") or {}
    npct = risk["nifty"]
    pool = []
    for r in (res.get("movers") or {}).get("rows") or []:
        pool.append(("Top Movers", r))
    for r in (res.get("goki") or {}).get("top") or []:
        pool.append(("Goki Mannan Jackpot", r))
    for sd in ("CE", "PE"):
        for r in (res.get("bo2") or {}).get(sd) or []:
            pool.append(("Breakout CE" if sd == "CE" else "Breakdown PE", r))
    for r in (res.get("strong") or {}).get("rows") or []:
        if r.get("strong"):
            pool.append(("🟠 Strong Break", r))
    for key, src in (("orb2", "5-min ORB"), ("voi2", "Volume+OI")):
        for r in res.get(key) or []:
            pool.append((src, r))
    cands, seen = [], set()
    for src, r in pool:
        o, rp = r.get("option") or {}, r.get("rp")
        if not (o.get("token") and rp) or o.get("no_depth") or (o.get("spread_pct") or 99) > 5:
            continue
        k = f"{r['symbol']}|{r['side']}"
        if k in seen:
            continue
        seen.add(k)
        f = feats(src, r["side"], now.strftime("%H:%M"), score=r.get("score"), vol=r.get("vol_ratio"), vel=r.get("vel"),
                  pos=r.get("pos"), oi=r.get("oi"), nifty_pct=npct, symbol=r["symbol"])
        p, why = predict(f)
        cold = p is None
        ok = (p is not None and p >= AI["min_p"]) or (cold and (r.get("score") or 0) >= AI["cold_score"] and f.get("trend") != "against")
        if risk["level"] == "CRASH" and r["side"] == "CE":
            ok, why = False, why + ["🚨 crash risk — CE வேண்டாம்"]
        o2 = dict(o, plan=dict(o.get("plan") or {}, entry=rp["entry"], sl=rp["sl"], targets=rp["targets"], money=True))
        cands.append({"symbol": r["symbol"], "side": r["side"], "src": src, "score": r.get("score"), "p": p, "why": why, "ok": ok,
                      "feat": f, "option": o2, "rp": rp, "price": r.get("price"), "sl": r.get("sl"), "vol": r.get("vol_ratio")})
    cands.sort(key=lambda c: (-(c["p"] or 0), -(c["score"] or 0)))
    mins = now.hour * 60 + now.minute
    if live and 9 * 60 + 45 <= mins <= 14 * 60 + 30:
        try:
            add_aipick([c for c in cands if c["ok"]], now, AI["max_day"])
        except Exception as e:
            res.setdefault("errors", []).append(f"AI picks: {e}")
    return {"risk": risk, "cands": cands[:6], "model": {k: v for k, v in M.items() if k != "stats"}, "opt": AST.get("opt"),
            "top_feats": sorted([(k, v, s_[0], round((s_[1] + 1) / (s_[0] + 2) * 100)) for k, d_ in (M.get("stats") or {}).items()
                                 for v, s_ in d_.items() if s_[0] >= 8], key=lambda x: -x[3])[:6],
            "worst_feats": sorted([(k, v, s_[0], round((s_[1] + 1) / (s_[0] + 2) * 100)) for k, d_ in (M.get("stats") or {}).items()
                                   for v, s_ in d_.items() if s_[0] >= 8], key=lambda x: x[3])[:6],
            "cfg": AI}


def run_movers(ag, inst, live_q, res, now, live):
    """🚀 TOP MOVERS (F&O) — moneycontrol gainers / losers மாதிரி: |%| ≥ 2 · volume ≥ 1.5× · day high / low அருகில் (continuation)
    → stock option strike + ₹ plan → score ≥65 ஆனா call (9:45–2:00, நாளைக்கு max 4)."""
    from .calls import rupee_plan, add_movers
    mins = now.hour * 60 + now.minute
    bu_tag = {}
    for kind, rows in (res.get("oi_buildup") or {}).items():
        for x in rows:
            bu_tag[x["symbol"]] = kind
    npct = next((x.get("pct") for x in res.get("index") or [] if x.get("index") == "NIFTY"), 0) or 0
    cands = []
    H = C.setdefault("mov_hist", {})
    tnow = now.timestamp() if hasattr(now, "timestamp") else 0
    for n, q in live_q.items():
        h_ = H.setdefault(n, [])
        h_.append((tnow, q.get("pct") or 0))
        del h_[:-30]
    for n, q in live_q.items():
        pct, vr, hi, lo, ltp = q.get("pct") or 0, q.get("vol_ratio") or 0, q.get("high") or 0, q.get("low") or 0, q.get("ltp") or 0
        h_ = H.get(n) or []
        old = [p_ for t_, p_ in h_ if tnow - t_ >= 240]          # ~5 நிமிடத்துக்கு முன் %
        vel = round(pct - old[-1], 2) if old else 0.0             # 🏃 velocity: கடைசி ~5 நிமிட move
        early = abs(pct) >= 1.2 and abs(vel) >= 0.5 and (vel > 0) == (pct > 0) and vr >= 1.5
        if (abs(pct) < MOVERS["min_pct"] and not early) or vr < MOVERS["min_vr"] or not (hi > lo > 0) or ltp <= 50:
            continue
        side = "CE" if pct > 0 else "PE"
        pos = (ltp - lo) / (hi - lo)
        if (side == "CE" and pos < 0.7) or (side == "PE" and pos > 0.3):
            continue                     # day high / low-ல் இருந்து விலகிடுச்சு — fade ஆகுது
        f = (C.get("feat") or {}).get(n) or {}
        lv = (C.get("levels") or {}).get(n) or {}
        atr = f.get("atr") or ltp * 0.02
        k = bu_tag.get(n, "")
        oi_ok = (side == "CE" and k in ("Long Built Up", "Short Covering")) or (side == "PE" and k in ("Short Built Up", "Long Unwinding"))
        broke = [x for x in (("PDH", "PWH") if side == "CE" else ("PDL", "PWL")) if lv.get(x) and ((ltp > lv[x]) if side == "CE" else (ltp < lv[x]))]
        ext = abs(ltp - (q.get("open") or ltp)) / atr if atr else 0
        sc = min(30, abs(pct) * 7) + min(25, vr * 8) + (15 if (pos >= 0.85 if side == "CE" else pos <= 0.15) else 8)
        sc += 15 if oi_ok else 0
        sc += 10 if broke else 0
        sc += 5 if ext <= 2.5 else -10
        sc += 5 if (side == "CE" and npct > -0.2) or (side == "PE" and npct < 0.2) else -5
        if old and vel:
            sc += min(15, abs(vel) * 15) if (vel > 0) == (side == "CE") else -10     # இப்போ வேகமா நகருதா (history இருந்தா மட்டும்)
        why = [f"{pct:+.2f}% · volume {vr}×", f"🏃 5-min {vel:+.2f}%", f"Day range-ல் {int(pos * 100)}% இடம்", f"OI: {k or 'தெரியல'}"] + ([f"{'+'.join(broke)} break"] if broke else [])
        fs = C.setdefault("mov_first", {})
        fk = f"{now.date()}|{n}|{side}"
        fs.setdefault(fk, now.strftime("%H:%M"))
        cands.append({"symbol": n, "side": side, "price": ltp, "pct": pct, "vol_ratio": vr, "pos": round(pos, 2), "oi": k, "vel": vel,
                      "first": fs[fk], "min_days": 1,       # stock: NSE monthly · expiry நாள் அன்னைக்கு அடுத்த மாதம்
                      "stage": "🟠 EARLY — இப்போ நகருது" if abs(pct) < MOVERS["min_pct"] else "🚀 MOVING",
                      "score": int(max(0, min(100, sc))), "why": why, "atr": round(atr, 2),
                      "sl": round(ltp - atr if side == "CE" else ltp + atr, 2), "targets": []})
    cands.sort(key=lambda r: -r["score"])
    top = cands[:8]
    cache = C.setdefault("mov_opt", {})
    day = str(now.date())
    need = [r for r in top if not (cache.get(f"{day}|v6|{r['symbol']}|{r['side']}") or {}).get("token")][:4]
    if need:
        pick_options(ag, inst, need)
        for r in need:
            o_ = r.get("option") if "none" not in (r.get("option") or {}) else (r.get("option_ref") or r.get("option"))
            if (o_ or {}).get("token"):
                cache[f"{day}|v6|{r['symbol']}|{r['side']}"] = o_      # கிடைச்சா மட்டும் cache — fail ஆனா அடுத்த tick மறுபடி
            else:
                r["option"] = o_
    otoks = {}
    for r in top:
        o = cache.get(f"{day}|v6|{r['symbol']}|{r['side']}")
        if o and "none" not in o:
            otoks.setdefault(o["exch"], []).append(o["token"])
    oq = ag.quotes(otoks) if (live and otoks) else {}
    for r in top:
        o = cache.get(f"{day}|v6|{r['symbol']}|{r['side']}")
        if not o or "none" in o:
            if not (r.get("option") or {}).get("none"):
                r["option"] = {"none": "Option தேடுது… (அடுத்த tick)"}
            continue
        o = dict(o)
        qq = oq.get(o["token"])
        if qq and qq.get("ltp"):
            o["ltp"] = float(qq["ltp"])
            o["ask"] = o["ltp"]
        r["option"] = o
        attach_plan(r, o, now, "Top Movers")
        p = o.get("plan") or {}
        if p.get("entry"):
            sl_, tg_, rk_, rc_ = rupee_plan(p["entry"], p.get("sl"), o["lot"], False)
            r["rp"] = {"entry": p["entry"], "sl": sl_, "targets": tg_, "risk": rk_, "t_rs": [round((t - p["entry"]) * o["lot"]) for t in tg_], "codes": rc_}
    if live and 9 * 60 + 16 <= mins <= 15 * 60 + 15:
        try:
            add_movers([r for r in top if r["score"] >= MOVERS["min_score"] and r.get("rp") and "SL_TIGHT" not in r["rp"]["codes"]
                        and not r["option"].get("no_depth") and (r["option"].get("spread_pct") or 99) <= MOVERS["max_spread"]
                        and (not r.get("vel") or (r["vel"] > 0) == (r["side"] == "CE"))], now)
        except Exception as e:
            res.setdefault("errors", []).append(f"Movers calls: {e}")
    LOG = C.setdefault("mov_log", {})
    for k_ in [k_ for k_, v_ in LOG.items() if ((v_.get("option") or {}).get("exch") == "BFO")]:
        LOG.pop(k_, None)
    for r in top:
        if (r.get("option") or {}).get("strike"):
            LOG[f"{day}|{r['symbol']}|{r['side']}"] = {k_: r.get(k_) for k_ in ("symbol", "side", "score", "stage", "first", "pct", "vol_ratio", "option", "rp", "why")}
    for k_ in [k_ for k_ in LOG if not k_.startswith(day)]:
        LOG.pop(k_, None)
    return {"time": now.strftime("%H:%M:%S"), "rows": top,
            "log": sorted(LOG.values(), key=lambda r: r.get("first") or "", reverse=True)[:60],
            "gainers": sorted([x for x in live_q.items() if (x[1].get("pct") or 0) > 0], key=lambda x: -x[1]["pct"])[:8],
            "losers": sorted([x for x in live_q.items() if (x[1].get("pct") or 0) < 0], key=lambda x: x[1]["pct"])[:8]}


def run_goki(ag, inst, universe, bu_tag, nret, now, session, live, el, res):
    """👑 GOKI MANNAN JACKPOT RADAR — FINAL SCANER MASTER (CE) + DOW EARANGUM (PE) → analysis score → top 3 + calls."""
    from .goki import scan as goki_scan, STATE as GST
    from .calls import rupee_plan, add_goki
    npct = next((x.get("pct") for x in res.get("index") or [] if x.get("index") == "NIFTY"), 0) or 0
    rows = goki_scan(ag, inst, C, universe, bu_tag, npct, nret, now, session, live,
                     (el.get("intraday") or []) + (el.get("almost") or []))
    try:
        from .goki import scan_daily
        rows += scan_daily(C, universe, bu_tag, npct, nret, now)     # CHAT HPY · GROK BEST ONE · MONSTER HOLDING
    except Exception as e:
        res.setdefault("errors", []).append(f"Goki daily: {e}")
    rows.sort(key=lambda r: (-int(r["full"]), -r["score"]))
    top = rows[:8]
    mins = now.hour * 60 + now.minute
    for r in top:
        r["min_days"] = 10 if r.get("hold") else 1      # holding scanners → போதுமான நாள் உள்ள expiry
    pick_options(ag, inst, top)
    for r in top:
        if "none" in (r.get("option") or {}) and r.get("option_ref"):
            r["option"] = r["option_ref"]          # strike எப்போதும் காட்டு (wide spread warning-ஓட)
        attach_plan(r, r.get("option"), now, "Goki Mannan")
        o = r.get("option") or {}
        p = o.get("plan") or {}
        r["action"], r["why_not"] = "WATCH", []
        if p.get("entry") and o.get("lot"):
            sl_, tg_, rk_, rc_ = rupee_plan(p["entry"], p.get("sl"), o["lot"], bool(r.get("hold")))
            r["rp"] = {"entry": p["entry"], "sl": sl_, "targets": tg_, "risk": rk_, "t_rs": [round((t - p["entry"]) * o["lot"]) for t in tg_]}
            r["orange"] = bool(r["full"] and r["score"] >= 70 and not rc_)       # 🟠 எடுக்கலாம்
            if "SL_TIGHT" in rc_:
                r["why_not"].append("SL_TIGHT")
        else:
            r["why_not"].append((o.get("none") or "Option இல்லை")[:90])
        if o.get("wide_spread") and not o.get("no_depth") and (o.get("spread_pct") or 0) > 10:
            r["why_not"].append(f"Spread {o.get('spread_pct')}% — limit order, paper மட்டும்")
        if not r["full"] and r["score"] < 65:
            r["why_not"].append(f"Scanner 8/9 + score {r['score']} < 65")
        if r["score"] < 55:
            r["why_not"].append(f"Score {r['score']} < 55")
        if r.get("hold"):
            if not (14 * 60 <= mins <= 15 * 60 + 20):
                r["why_not"].append("Daily / weekly scanner — 2:00–3:20 (candle close அருகில்) தான் entry")
        elif not (9 * 60 + 30 <= mins <= 14 * 60 + 30):
            r["why_not"].append("நேரம் 9:30–2:30 இல்லை")
        if not r["why_not"] and r.get("rp"):
            r["action"] = "ENTRY"
    top.sort(key=lambda r: (-int(r.get("action") == "ENTRY"), -int(bool(r.get("orange"))), -r["score"]))
    radar = {"time": now.strftime("%H:%M"), "date": str(now.date()), "top": top[:3], "rows": rows[:25],
             "scanners": sorted({r["scanner"] for r in rows}),
             "ce": sum(1 for r in rows if r["side"] == "CE" and r["full"]), "pe": sum(1 for r in rows if r["side"] == "PE" and r["full"])}
    if live:
        try:
            add_goki([r for r in top[:5] if r["action"] == "ENTRY"], now)
        except Exception as e:
            res.setdefault("errors", []).append(f"Goki calls: {e}")
    GST["radar"] = radar
    return radar


def run_elite_fast(ag, res):
    """⚡ 15-min candle முடிந்த உடனே Elite மட்டும் (deep scan-க்கு காத்திருக்காமல்) — quotes + 15m candles மட்டும்."""
    from .elite import scan as elite_scan
    from .calls import update_calls
    if not res or not C.get("bars"):
        return res
    inst = load_inst(ROOT / "data" / "cache")
    names = [n for n in inst["fno"] if n in inst["eq"]]
    toks = {"NSE": [inst["eq"][n] for n in names]}
    for ex, tok in INDEX_SPOT.values():
        toks.setdefault(ex, []).append(tok)
    qs = ag.quotes(toks)
    now = _now()
    session, live, mins = _session(qs.get(INDEX_SPOT["NIFTY"][1]), now)
    share = _vol_share(mins)
    universe = []
    for n in names:
        q = qs.get(inst["eq"][n])
        if not q:
            continue
        avg = C["avgvol"].get(n) or 0
        vol = _f(q.get("tradeVolume"))
        universe.append({"symbol": n, "ltp": _f(q.get("ltp")), "pct": _f(q.get("percentChange")),
                         "vol_ratio": round(vol / (avg * share), 2) if avg else 0.0, "volume": int(vol),
                         "open": _f(q.get("open")), "high": _f(q.get("high")), "low": _f(q.get("low"))})
    bu_tag = {}
    for kind, rows in (res.get("oi_buildup") or {}).items():
        for x in rows:
            bu_tag[x["symbol"]] = kind
    nret = 0.0
    nd_ = C.get("nifty_daily")
    n_spot = _f((qs.get(INDEX_SPOT["NIFTY"][1]) or {}).get("ltp"))
    if nd_ is not None and not nd_.empty and n_spot:
        pc_ = nd_[nd_.index < session]["close"]
        if len(pc_) > 21:
            nret = n_spot / float(pc_.iloc[-21]) - 1
    el = elite_scan(ag, inst, C, universe, res.get("trend"), bu_tag, nret, now, session, live)
    hold = []
    for r in el["intraday"]:
        seen("elite", r, now)
    for r in el["holding"]:
        hr = dict(r)
        atr_ = r.get("atr") or r["price"] * 0.02
        sg = 1 if r["side"] == "CE" else -1
        hr.update(sl=r["hold_sl"], targets=[round(r["price"] + sg * m * atr_, 2) for m in (1.5, 3, 4.5)], min_days=20, hold=10)
        seen("eliteh", hr, now)
        hold.append(hr)
    pick_options(ag, inst, el["intraday"][:8] + hold[:6])
    cfg_ = load_settings().get("risk", {})
    for r in el["intraday"][:8]:
        attach_plan(r, r.get("option"), now, "Elite intraday")
    for r in hold[:6]:
        o_ = r.get("option")
        if o_ and "none" not in o_:
            try:
                o_["plan"] = prem_plan(o_.get("ask") or o_.get("ltp"), r["price"], o_["strike"], o_["expiry"], o_["type"],
                                       r["sl"], r["targets"], now.to_pydatetime(), o_["lot"],
                                       cfg_.get("charges_slippage", 150), cfg_.get("max_risk_holding", 5000),
                                       hold_days=7, sl_days=2)
                from .calls import calibrate_plan
                calibrate_plan("Elite holding", o_["plan"])
                apply_money(o_, r["price"], now, r.get("atr"), intraday=False)
            except Exception:
                o_["plan"] = None
    el["holding"] = hold
    el["jackpot"] = [r for r in el["intraday"] + hold if r.get("jackpot")]
    el["time"] = now.strftime("%H:%M")
    res["elite"] = el
    try:
        res["goki"] = run_goki(ag, inst, universe, bu_tag, nret, now, session, live, el, res)
    except Exception as e:
        res.setdefault("errors", []).append(f"Goki: {e}")
    try:
        compute_all_rounder(res)
    except Exception:
        pass
    try:
        res["tracking"] = update_calls(ag, session, now, live, [], [], [], [], {"10": [], "5": []}, add=False,
                                       elite=[], elite_hold=[])      # V5.5: Elite calls OFF (user request) — scan Goki-க்கு மட்டும்
    except Exception:
        pass
    return res


def export_bars():
    if C["session"] is None or not C.get("bars"):
        return None
    return {"session": str(C["session"].date()), "bars": C["bars"], "levels": C["levels"], "avgvol": C["avgvol"],
            "swings": C["swings"], "feat": C.get("feat", {})}


def import_bars(d):
    """bars.json → C (அதே session என்றால் மட்டும்)."""
    if not d or not d.get("bars"):
        return False
    s = pd.Timestamp(d["session"])
    if C["session"] is not None and C["session"] != s:
        return False
    C.update(session=s, bars=d["bars"], levels=d.get("levels") or C.get("levels") or {},
             avgvol=d.get("avgvol") or C.get("avgvol") or {}, swings=d.get("swings") or C.get("swings") or {},
             feat=d.get("feat") or C.get("feat") or {})
    return True


# ---------------- 🏅 ALL ROUNDER: பல module-களில் ஒரே stock + side வந்தால் ----------------
AR_W = {"POWER OI": 25, "Elite": 20, "Gamma unwind": 20, "Breakout/Breakdown": 15, "Volume+OI": 15, "Swing": 15,
        "5-min ORB": 10, "Chart pattern": 10, "OI Footprint": 10, "Best setup": 10, "Index OI": 10}
AR_PRI = ["POWER OI", "Elite", "Gamma unwind", "Best setup", "Breakout/Breakdown", "5-min ORB", "Volume+OI", "Swing",
          "Chart pattern", "Index OI", "OI Footprint"]


AR_MAX = {"day": None, "m": {}}


def ar_live(a, now=None):
    """All-rounder row-க்கு live: option LTP, T1/T2/T3 tick (sticky — தொட்டா tick இருக்கும்), SL touch, volume light."""
    now = now or _now()
    o = a.get("option") or {}
    p = o.get("plan") or {}
    day = str(pd.Timestamp(now).date())
    if AR_MAX["day"] != day:
        AR_MAX.update(day=day, m={})
    ltp = o.get("ltp")
    if not ltp and o.get("bid") and o.get("ask"):
        ltp = round((o["bid"] + o["ask"]) / 2, 2)
    e, sl, tg = p.get("entry"), p.get("sl"), (p.get("targets") or [])[:3]
    vr = a.get("vol_ratio")
    hhmm = pd.Timestamp(now).strftime("%H:%M")
    live = {"ltp": ltp, "vol": vr, "t_hits": [False] * 3, "t_times": [None] * 3, "sl_hit": False, "since": hhmm}
    key = o.get("contract")
    if ltp and key:
        m = AR_MAX["m"].setdefault(key, {"max": ltp, "min": ltp, "t": [None] * 3, "since": hhmm})
        m["max"], m["min"] = max(m["max"], ltp), min(m["min"], ltp)
        for i, t in enumerate(tg):
            if m["t"][i] is None and m["max"] >= t:
                m["t"][i] = hhmm
        live.update(t_hits=[x is not None for x in m["t"]], t_times=m["t"], since=m["since"],
                    sl_hit=bool(sl and m["min"] <= sl))
    prog = round((ltp - e) / (tg[0] - e) * 100) if (ltp and e and tg and tg[0] > e) else None
    live["t1_prog"] = prog
    live["t1_state"] = "HIT" if live["t_hits"][0] else "NEAR" if (prog is not None and prog >= 60) else "WAIT"
    why = []
    if not p:
        light = "red"
        why.append("Option plan இல்லை")
    else:
        ok_risk, ok_rw = bool(p.get("risk_ok")), p.get("reward_ok", True)
        if live["sl_hit"]:
            why.append("SL touch ஆச்சு")
        if not ok_risk:
            why.append("Risk > ₹2,500")
        if not ok_rw:
            why.append("T1 unrealistic")
        if vr is None:
            why.append("Volume data இல்லை (index)")
        else:
            why.append(f"Volume {vr}× " + ("✓" if vr >= 1.5 else "குறைவு"))
        bad = live["sl_hit"] or not ok_risk or not ok_rw or (vr is not None and vr < 1.0)
        light = "red" if bad else ("green" if (vr is not None and vr >= 1.5) else "yellow")
    live["light"], live["why"] = light, why
    live["hot"] = light == "green" and live["t1_state"] in ("HIT", "NEAR")
    # 🟣 ENTRY NOW: green + LTP இன்னும் entry zone-க்குள் + option premium மேலே நகருது + volume ≥2× (rule-based timing)
    live["entry_now"] = False
    if key and ltp and e and AR_MAX["m"].get(key) is not None:
        h_ = AR_MAX["m"][key].setdefault("hist", [])
        if not h_ or h_[-1] != ltp:
            h_.append(ltp)
            del h_[:-6]
        rising = len(h_) >= 3 and h_[-1] > h_[-3]
        in_zone = e * 0.97 <= ltp <= e * 1.03
        live["entry_now"] = bool(light == "green" and in_zone and rising and (vr or 0) >= 2 and not live["t_hits"][0])
        if live["entry_now"] and not AR_MAX["m"][key].get("purple_sent"):
            AR_MAX["m"][key]["purple_sent"] = hhmm
            try:
                from .telegram import send as _tg
                _tg(f"🟣 ENTRY NOW · All Rounder\n{a['symbol']} {o.get('strike')} {a['side']} @ ₹{ltp} (entry ₹{e})\n"
                    f"SL ₹{sl} · T1 ₹{tg[0] if tg else '-'} · Volume {vr}× · premium மேலே நகருது\n(Rule-based timing — paper/alert only)",
                    f"purple|{key}|{day}")
            except Exception:
                pass
    a["live"] = live
    return a


MOM = {"day": None, "hist": {}, "sent": set()}


def momentum_watch(live_q, now, trend, live=True):
    """⚡ Momentum Watch — range market-லும் news / volume-ல் வேகமா நகரும் stocks.
    CE watch (green) = மேலே, PE watch (red) = கீழே. 🟣 ENTRY NOW = day high/low உடைப்பு + 2-min வேகம் + volume ≥2× (rule-based)."""
    day = str(pd.Timestamp(now).date())
    if MOM["day"] != day:
        MOM.update(day=day, hist={}, sent=set())
    try:
        from .news import CACHE as NC
        news = NC.get("items") or []
    except Exception:
        news = []
    cutoff = pd.Timestamp(now).timestamp() - 6 * 3600
    ts_now = pd.Timestamp(now).timestamp()
    out = {"CE": [], "PE": []}
    for n, q in live_q.items():
        ltp, pct, vr = q.get("ltp"), q.get("pct") or 0, q.get("vol_ratio") or 0
        if not ltp:
            continue
        h = MOM["hist"].setdefault(n, [])
        h.append((ts_now, ltp))
        del h[:-12]
        if abs(pct) < 1.0 or vr < 1.8:
            continue
        side = "CE" if pct > 0 else "PE"
        hi, lo = q.get("high") or ltp, q.get("low") or ltp
        near = (ltp >= hi * 0.997) if side == "CE" else (ltp <= lo * 1.003)
        past = [p for t, p in h if ts_now - t >= 100]           # ~2 நிமிடம் முன்
        vel = round((ltp / past[-1] - 1) * 100, 2) if past else 0.0
        nw = next((x for x in news if n in (x.get("symbols") or []) and (x.get("ts") or 0) >= cutoff), None)
        news_ok = bool(nw and ((nw["tag"] == "POSITIVE") if side == "CE" else (nw["tag"] == "NEGATIVE")))
        sc = min(vr / 4, 1) * 35 + min(abs(pct) / 3, 1) * 25 + (20 if near else 0) + (10 if news_ok else 0) + \
            (10 if (vel >= 0.2 if side == "CE" else vel <= -0.2) else 0)
        late = abs(pct) > 4.5
        entry_now = bool(near and vr >= 2 and (vel >= 0.25 if side == "CE" else vel <= -0.25) and not late)
        row = {"symbol": n, "side": side, "ltp": ltp, "pct": pct, "vol_ratio": vr, "near": near, "vel_2m": vel,
               "score": int(sc), "late": late, "entry_now": entry_now, "high": hi, "low": lo,
               "news": ({"title": nw["title"], "tag": nw["tag"], "time": nw.get("time"), "link": nw.get("link")} if nw else None)}
        out[side].append(row)
        if entry_now and live and (n, side) not in MOM["sent"]:
            MOM["sent"].add((n, side))
            row["alert_time"] = pd.Timestamp(now).strftime("%H:%M")
            try:
                from .telegram import send as _tg
                _tg(f"🟣 ENTRY NOW (momentum) · {n} {side}\nLTP {ltp} ({pct:+.2f}%) · Volume {vr}× · 2-min {vel:+.2f}%\n"
                    f"{'Day high' if side == 'CE' else 'Day low'} உடைக்குது" + (f"\n📰 {nw['title'][:90]}" if nw else "") +
                    "\n(Watch list — strike-ஐ chart-ல் பார்த்து முடிவு. Rule-based, guarantee இல்லை)", f"mom|{n}|{side}|{day}")
            except Exception:
                pass
    for k in out:
        out[k].sort(key=lambda r: (-r["entry_now"], -r["score"]))
        out[k] = out[k][:8]
    out["time"] = pd.Timestamp(now).strftime("%H:%M")
    out["trend"] = trend
    return out


AR_TRIGGER = {"POWER OI", "Breakout/Breakdown", "Best setup", "5-min ORB", "Elite", "Gamma unwind", "Index OI", "OI Footprint"}
AR_EDGE_SRC = {"Elite": "Elite intraday", "Best setup": "Breakout/Breakdown", "Swing": "Swing"}


def ar_pro(a, res):
    """🏅 ALL ROUNDER PRO (V4): நஷ்ட setup modules எண்ணிக்கையில் இல்லை · ≥3 நல்ல modules · ஒரு trigger module ✓ ·
    TAKE · volume ≥1.5× · NIFTY direction எதிர் இல்லை · light red இல்லை. இது pass ஆனா மட்டும் call."""
    try:
        from .store import STORE
        edge = (STORE.data or {}).get("edge") or {}
    except Exception:
        edge = {}
    good = {m: v for m, v in a["modules"].items() if edge.get(AR_EDGE_SRC.get(m, m)) != "NEGATIVE"}
    bad = [m for m in a["modules"] if m not in good]
    trig = any(m in AR_TRIGGER and v["strength"] >= 1.0 for m, v in good.items())
    np_ = next((x.get("pct") for x in (res.get("index") or []) if x.get("index") == "NIFTY"), None) or 0
    flat = abs(np_) < 0.15
    dir_ok = flat or (a["side"] == "CE") == (np_ > 0)
    is_idx = a["symbol"] in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX")
    vr = a.get("vol_ratio")
    vol_ok = is_idx or (vr is not None and vr >= 1.5)
    need = 4 if flat else 3
    light = (a.get("live") or {}).get("light")
    chk = {f"நல்ல modules ≥{need} ({len(good)})": len(good) >= need, "Trigger module ✓": trig, "TAKE": a.get("verdict") == "TAKE",
           "Volume ≥1.5×": vol_ok, "NIFTY direction எதிர் இல்லை": dir_ok, "Light red இல்லை": light != "red"}
    a["pro_chk"] = chk
    a["pro_ok"] = all(chk.values())
    a["pro_drop"] = bad
    if a["pro_ok"]:
        a["tag"] = "🏅 ALL ROUNDER PRO"


MACHINE = {"t1_rs": 2000, "t2_rs": 4000, "t3_rs": 6000, "max_risk": 2500, "max_move_pct": 30, "day_target": 10000,
           "day_stop": -4500, "max_calls": 5, "min_score": 58, "show_score": 40}


def _r05(x):
    return round(round(x / 0.05) * 0.05, 2)


def machine_day(now=None):
    """இன்றைய 2K machine calls P/L → target / loss stop."""
    from .store import STORE
    day = str((now or _now()).date())
    cs = [c for c in ((STORE.data or {}).get("calls") or {}).values() if c.get("kind") == "MACHINE" and c["date"] == day]
    closed = sum(c.get("pnl_lot") or 0 for c in cs if c["status"] not in ("OPEN", "T1 HIT", "T2 HIT", "T3 HIT"))
    total = sum(c.get("pnl_lot") or 0 for c in cs)
    stop = ("🎯 இன்றைய ₹10,000 target வந்தாச்சு — இன்று போதும்" if closed >= MACHINE["day_target"] else
            "🛑 இன்றைய loss ₹4,500 தாண்டியது — இன்று புது call இல்லை" if total <= MACHINE["day_stop"] else
            f"இன்று max {MACHINE['max_calls']} calls முடிந்தது" if len(cs) >= MACHINE["max_calls"] else None)
    return {"calls": len(cs), "closed_net": closed, "net": total, "stop": stop, "symbols": {f"{c['symbol']}|{c['side']}" for c in cs}}


def _machine_pool(rows):
    """Machine candidates: All rounder rows + இன்றைய open Grade A/B calls (எல்லா modules-ல் இருந்தும்)."""
    from .store import STORE
    from .calls import OPEN as _OPEN
    pool = []
    for a in rows:
        o = a.get("option") or {}
        if (o.get("plan") or {}).get("entry") and o.get("token"):
            pool.append(dict(src="AR", a=a, o=o, lv=a.get("live") or {}))
    now = _now()
    day = str(now.date())
    edge = (STORE.data or {}).get("edge") or {}
    for c in ((STORE.data or {}).get("calls") or {}).values():
        if (c["date"] != day or c["status"] not in _OPEN or c.get("shadow") or c.get("hold_until") or c["kind"] == "MACHINE"
                or c.get("grade") not in ("A", "B") or c["hits"]):
            continue
        srcs = c.get("sources") or [c.get("source")]
        if all(edge.get(s_) == "NEGATIVE" for s_ in srcs):
            continue
        a = {"symbol": c["symbol"], "side": c["side"], "modules": {s_: {"strength": 1.0} for s_ in srcs}, "count": len(srcs),
             "verdict": "TAKE" if c.get("grade") == "A" else "WATCH", "vol_ratio": c.get("vol_ratio"),
             "pro_ok": c.get("grade") == "A" and len(srcs) >= 2,
             "pro_chk": {"NIFTY direction எதிர் இல்லை": "COUNTER_TREND" not in (c.get("qcodes") or [])}}
        o = {"token": c["token"], "exch": c["exch"], "contract": c["contract"], "strike": c["strike"], "type": c["side"],
             "expiry": c["expiry"], "lot": c["lot"], "plan": {"entry": c["entry"], "sl": c["sl"]}}
        pool.append(dict(src="CALL", a=a, o=o, lv={"ltp": c.get("ltp"), "since": c["time"], "t_hits": [False] * 3, "sl_hit": False}))
    return pool


def machine_pick(rows, res):
    """💰 2K PROFIT MACHINE (V6) — All rounder + இன்றைய Grade A/B calls-ல் இருந்து top 5.
    ₹ rules: SL ≤ ₹2,500 (cap) · T1 ₹2,000 (கஷ்டம்னா ₹1,500) · T2 ₹4,000 · T3 ₹6,000. Rule-based score (AI model இல்லை)."""
    from .store import STORE
    from .calls import rupee_plan
    edge = (STORE.data or {}).get("edge") or {}
    now = _now()
    mins = now.hour * 60 + now.minute
    day = machine_day(now)
    best = {}
    for P in _machine_pool(rows):
        a, o, lv = P["a"], P["o"], P["lv"]
        p = o["plan"]
        lot, e = o.get("lot") or 0, p.get("entry")
        if not (e and lot):
            continue
        ltp = lv.get("ltp") or e
        if e * 0.97 <= ltp <= e * 1.03:
            e = _r05(ltp)          # இப்போ entry எடுத்தா வாங்கும் விலை
        sl, tg_, risk, rc = rupee_plan(e, p.get("sl"), lot, False)
        if not tg_:
            continue
        move_pct = (tg_[0] / e - 1) * 100
        sc, why, bad, soft = 0, [], [], []
        if a.get("pro_ok"):
            sc += 30; why.append("PRO ✓" if P["src"] == "AR" else "Grade A + 2+ modules")
        elif a.get("count", 0) >= 3:
            sc += 22; why.append(f"{a['count']} modules")
        elif a.get("count", 0) == 2:
            sc += 14; why.append("2 modules")
        else:
            sc += 8
        if a.get("verdict") == "TAKE":
            sc += 10
        if P["src"] == "CALL" and a.get("verdict") == "TAKE":
            sc += 15; why.append("Grade A call")
        vr = a.get("vol_ratio")
        if vr is None:
            sc += 10
        elif vr >= 3:
            sc += 20; why.append(f"Volume {vr}×")
        elif vr >= 2:
            sc += 15; why.append(f"Volume {vr}×")
        elif vr >= 1.5:
            sc += 8
        elif vr < 1.0:
            bad.append(f"Volume {vr}× மிகக் குறைவு")
        else:
            soft.append(f"Volume {vr}×")
        if lv.get("entry_now"):
            sc += 10; why.append("🟣 ENTRY NOW")
        pos = [m for m in a["modules"] if edge.get(AR_EDGE_SRC.get(m, m)) == "POSITIVE"]
        neg = [m for m in a["modules"] if edge.get(AR_EDGE_SRC.get(m, m)) == "NEGATIVE"]
        sc += min(24, 12 * len(pos))
        if pos:
            why.append("லாப setup: " + ", ".join(pos))
        if neg and not pos:
            soft.append("நஷ்ட setup: " + ", ".join(neg))
        sc += 10 if move_pct <= 12 else 6 if move_pct <= 20 else 2 if move_pct <= 28 else 0
        if "T1_UNREALISTIC" in rc:
            bad.append(f"T1-க்கு premium {move_pct:.0f}% ஏறணும் — கஷ்டம்")
        if "SL_TIGHT" in rc:
            bad.append("Lot பெரிசு — ₹2,500 SL மிக நெருக்கம்")
        if not (a.get("pro_chk") or {}).get("NIFTY direction எதிர் இல்லை", True):
            soft.append("NIFTY direction எதிர்")
        sc = max(0, min(100, sc - 8 * len(soft) - 20 * len(bad)))
        t1_hit = (lv.get("t_hits") or [False])[0] or ltp >= tg_[0]
        if bad:
            act, txt = "SKIP", "❌ வேண்டாம் — " + bad[0]
        elif lv.get("sl_hit"):
            act, txt = "SKIP", "❌ SL touch ஆச்சு — skip"
        elif t1_hit:
            act, txt = "SKIP", "T1 ஏற்கனவே போச்சு — late, chase வேண்டாம்"
        elif ltp > e * 1.03:
            act, txt = "WAIT", f"⏳ WAIT — ₹{e} அருகில் (≤ ₹{_r05(e * 1.03)}) வந்தா entry"
        elif sc >= MACHINE["min_score"] and 9 * 60 + 30 <= mins <= 14 * 60:
            act, txt = "ENTRY", f"✅ ENTRY எடு — இப்போ எடுத்தா T1-ல் ≈ ₹{round((tg_[0] - ltp) * lot):,}"
        elif not (9 * 60 + 30 <= mins <= 14 * 60):
            act, txt = "WAIT", "⏳ Machine நேரம் 9:30–2:00 மட்டும்"
        else:
            act, txt = "WAIT", f"⏳ WATCH — score {sc} ({MACHINE['min_score']} வேணும்)"
        if day["stop"] and act == "ENTRY":
            act, txt = "STOP", day["stop"]
        r = {"symbol": a["symbol"], "side": a["side"], "strike": o.get("strike"), "expiry": o.get("expiry"), "lot": lot,
             "contract": o.get("contract"), "token": o.get("token"), "exch": o.get("exch") or "NFO", "entry": e, "ltp": ltp,
             "sl": sl, "risk": risk, "targets": tg_, "t_rs": [round((t - e) * lot) for t in tg_],
             "move_pct": round(move_pct, 1), "score": sc, "action": act, "text": txt, "why": why, "bad": bad + soft,
             "modules": list(a["modules"].keys()), "first_seen": (lv.get("since") or now.strftime("%H:%M")), "vol_ratio": vr,
             "from": "All rounder" if P["src"] == "AR" else "Today call"}
        if P["src"] == "AR":
            a["mc"] = {"action": act, "text": txt, "score": sc, "t1": tg_[0]}
        k = f"{a['symbol']}|{a['side']}"
        if k not in best or r["score"] > best[k]["score"]:
            best[k] = r
    out = sorted(best.values(), key=lambda r: ({"ENTRY": 0, "WAIT": 1, "STOP": 1, "SKIP": 2}[r["action"]], -r["score"]))
    top = out[:5]
    try:
        from .calls import add_machine
        if res.get("live"):
            add_machine([r for r in top if r["action"] == "ENTRY"], now)
            day = machine_day(now)
    except Exception as e:
        res.setdefault("errors", []).append(f"2K machine: {e}")
    return {"rows": top, "day": {k: v for k, v in day.items() if k != "symbols"}, "cfg": MACHINE, "time": now.strftime("%H:%M")}


def compute_all_rounder(res):
    agg = {}

    def add(sym, side, mod, row=None, opt=None, strength=1.0, note=""):
        if not sym or side not in ("CE", "PE"):
            return
        a = agg.setdefault(f"{sym}|{side}", {"symbol": sym, "side": side, "modules": {}, "options": {}, "price": None})
        if mod not in a["modules"] or a["modules"][mod]["strength"] < strength:
            a["modules"][mod] = {"strength": strength, "note": note}
        if row and row.get("price") is not None:
            a["price"] = a["price"] or row.get("price")
        vr_ = (row or {}).get("vol_ratio")
        if vr_ is not None and (mod != "POWER OI" or a.get("vol_ratio") is None):
            a["vol_ratio"] = vr_
        o = opt or (row or {}).get("option")
        if o and "none" not in o and o.get("plan") and mod not in a["options"]:
            a["options"][mod] = o
    for r in (res.get("power") or {}).get("rows") or []:
        if r["grade"] in ("A+", "STRONG", "WATCH") and r["state"] in ("ENTRY CONFIRMED", "RETEST HELD", "RETEST PENDING"):
            add(r["symbol"], r["side"], "POWER OI", {"price": r["ltp"], "vol_ratio": r.get("rvol")}, r.get("option"),
                1.0 if r["state"] == "ENTRY CONFIRMED" else 0.6, f"{r['grade']} {r['score']} · {r['state']}")
    el = res.get("elite") or {}
    for r in (el.get("intraday") or []) + (el.get("holding") or []):
        add(r["symbol"], r["side"], "Elite", r, None, 1.0 if r.get("confidence", 0) >= 80 else 0.6, f"{r.get('confidence')}% conf")
    for r in res.get("best") or []:
        add(r["symbol"], r["side"], "Best setup", r, None, 1.0, f"score {r.get('score')}")
    for r in (res.get("ce") or []) + (res.get("pe") or []):
        if r.get("status") in ("CONFIRMED", "WATCH"):
            add(r["symbol"], r["side"], "Breakout/Breakdown", r, None, 1.0 if r["status"] == "CONFIRMED" else 0.5,
                f"{'+'.join(r.get('levels') or [])} {r['status']}")
    for r in (res.get("orb_up") or []) + (res.get("orb_dn") or []):
        if r.get("status") in ("CONFIRMED", "WATCH"):
            add(r["symbol"], r["side"], "5-min ORB", r, None, 1.0 if r["status"] == "CONFIRMED" else 0.5, r["status"])
    for side in ("CE", "PE"):
        for r in (res.get("volume_oi_picks") or {}).get(side, []):
            add(r["symbol"], side, "Volume+OI", r, None, 1.0, r.get("oi_tag", ""))
    for k in ("5", "10"):
        for r in (res.get("swing") or {}).get(k, []):
            add(r["symbol"], r["side"], "Swing", r, None, 1.0 if r.get("confidence") == "HIGH" else 0.7, f"{k}D hold")
    for p in res.get("patterns") or []:
        if p["status"] in ("CONFIRMED", "TRIGGERED", "NEAR BREAKOUT"):
            add(p["symbol"], p["side"], "Chart pattern", p, None, 1.0 if p["status"] != "NEAR BREAKOUT" else 0.5,
                f"{p['pattern']} {p['status']}")
    for s in (res.get("footprint") or {}).get("stocks") or []:
        add(s["symbol"], s["side"], "OI Footprint", {"price": s.get("ltp"), "vol_ratio": s.get("vol_ratio")}, None, 1.0, s.get("oi_tag", ""))
    for x in (res.get("footprint") or {}).get("index") or []:
        if x.get("bias") and x.get("plan"):
            add(x["index"], x["bias"], "OI Footprint", {"price": x.get("spot")}, x["plan"].get("option"), 1.0, "writers bias")
    for x in res.get("index") or []:
        pl = (x.get("plans") or {}).get(x.get("suggest"))
        if pl:
            add(x["index"], x["suggest"], "Index OI", {"price": x.get("spot")}, pl.get("option"),
                1.0 if x.get("confidence") == "OI bias" else 0.5, x.get("bias", ""))
    for s in (res.get("gu_snap") or {}).get("signals") or []:
        if s.get("tier") in ("PRO ENTRY", "STRONG WATCHLIST"):
            opt = {"token": s["token"], "exch": s["exch"], "contract": s["contract"], "strike": s["strike"], "type": s["side"],
                   "expiry": s["expiry"], "lot": s["lot"], "moneyness": s.get("pick", ""), "ask": s["entry"],
                   "plan": {"entry": s["entry"], "entry_zone": s.get("entry_zone"), "sl": s["sl"], "targets": s["targets"],
                            "risk": s["risk"], "risk_ok": s["risk"] <= 2500}}
            add(s["symbol"], s["side"], "Gamma unwind", None, opt, 1.0 if s["tier"] == "PRO ENTRY" else 0.6, s["tier"])
    out = []
    for a in agg.values():
        n = len(a["modules"])
        if n < 2:
            continue
        conf = sum(AR_W.get(m, 10) * v["strength"] for m, v in a["modules"].items())
        a["confidence"] = int(min(99, round(conf)))
        a["count"] = n
        a["tag"] = "🏅 ALL ROUNDER" if n >= 3 else "✌ DOUBLE CONFIRM"
        best = None
        for m in AR_PRI:
            o = a["options"].get(m)
            if o and (o.get("plan") or {}).get("risk_ok"):
                best = (m, o)
                break
        if not best:
            for m in AR_PRI:
                if a["options"].get(m):
                    best = (m, a["options"][m])
                    break
        a["option"], a["option_from"] = (best[1], best[0]) if best else (None, None)
        a["stars"] = 5 if a["confidence"] >= 70 else 4 if a["confidence"] >= 50 else 3
        p = (a["option"] or {}).get("plan") or {}
        a["verdict"] = ("TAKE" if n >= 3 and a["confidence"] >= 50 and p.get("risk_ok") and p.get("reward_ok", True) else
                        "WATCH" if n >= 2 and p else "UNDERLYING ONLY")
        a.pop("options")
        ar_live(a)
        ar_pro(a, res)
        out.append(a)
    out.sort(key=lambda a: (-a["count"], -a["confidence"]))
    res["all_rounder"] = out[:25]
    try:
        res["machine"] = machine_pick(out, res)
    except Exception as e:
        res["machine"] = {"rows": [], "error": str(e)}
    smart_refresh(res)
    try:
        from .calls import add_all_rounder
        if res.get("live"):
            add_all_rounder(out, _now())
    except Exception:
        pass
    return out



def smart_refresh(res):
    """🧠 Smart Rank (V3) — எல்லா modules signals ஒரே ranked list."""
    try:
        from .v3 import smart_rank
        from .sniper import REGIME
        segs = ((res.get("tracking") or {}).get("segments")) or {}
        rs = {"UP": "CE", "DOWN": "PE"}.get(REGIME.get("dir")) if REGIME.get("state") == "TRENDING" else \
            {"TRENDING UP": "CE", "TRENDING DOWN": "PE"}.get(res.get("trend"))
        res["smart"] = smart_rank(res, segs, str(_now().date()), rs)
    except Exception as e:
        res["smart_err"] = str(e)
    return res
