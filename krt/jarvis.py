"""🤖 JARVIS — BOSS OF THE BOSS CALLS. The terminal's evidence orchestrator (paper only, execution disabled).

Agents (all deterministic code — every number comes from live data the terminal already fetched, nothing invented):
  Scanner      every open call from every module + index / stock / MCX analysis the terminal already computed
  Price Action structure trend, BOS / CHOCH, S/R, supply-demand, 15-method chart verdict (Chart Room)
  Options/OI   futures OI build-up, option-chain buyers/writers verdict, index PCR / OI bias, spread
  Volume       RVOL, VWAP, footprint order flow
  Risk         SL distance, 1-lot risk, risk-to-reward
  Validator    10 independent checks — can REJECT or DOWNGRADE any setup
  Monitor      WAITING → ENTRY CONFIRMED → ACTIVE → T1..T5 HIT → CLOSED / STOPLOSS HIT / NOT TRIGGERED / INVALIDATED
  Audit        verified results after costs (brokerage, STT, exchange, GST)
Score (100) = Structure 20 · Trend 15 · Volume+VWAP 15 · OI 15 · Liquidity+Volatility 10 · MTF 10 · RR 10 · Regime 5.
A factor with no data scores 0 and is listed under "no data" — never guessed. Weights are initial settings, not calibrated.
Score = setup quality, NOT a win probability. NO TRADE is a valid output. Five targets only when five defensible levels exist.
"""
import pandas as pd

OPEN = ("OPEN", "T1 HIT", "T2 HIT")
IDX = ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY")
W = {"structure": 20, "trend": 15, "volume": 15, "oi": 15, "liquidity": 10, "mtf": 10, "rr": 10, "regime": 5}
NAME = {"structure": "Market structure", "trend": "Trend confirmation", "volume": "Volume + VWAP", "oi": "Open interest",
        "liquidity": "Liquidity + volatility", "mtf": "Multi-timeframe", "rr": "Risk-to-reward", "regime": "Market regime"}
CFG = {"elite": 80, "top": 10, "max_elite": 3, "zone_lo": 0.98, "zone_hi": 1.03, "eod": "15:20", "mcx_eod": "23:20"}
STATE = {"time": None, "top": [], "elite": [], "no_trade": None, "breaker": None, "scanned": 0, "coverage": {}}
LIVE = ("WAITING", "ENTRY CONFIRMED", "ACTIVE", "T1 HIT", "T2 HIT", "T3 HIT", "T4 HIT")


def rating(s):
    return "Elite candidate" if s >= 90 else "Strong candidate" if s >= 80 else "Watchlist" if s >= 70 else "Avoid"


def _agree(rows, keys):
    v = [r["agree"] for r in rows or [] if r["key"] in keys]
    return sum(v) / len(v) if v else None


def score(c, a, ctx):
    """→ (parts {factor: points|None}, reasons, missing). a = Chart Room analysis for the symbol (may be {})."""
    ce = c.get("side") != "PE"
    want = "UP" if ce else "DOWN"
    R = (a.get("methods") or {}).get("rows") or []
    P, why, miss = {}, [], []
    if a:
        st = a.get("structure") or {}
        s = 8 if st.get("trend") == want else 0
        if any(e.get("side") == want for e in st.get("events") or []):
            s += 6
            why.append(next(e["type"] for e in st["events"] if e.get("side") == want) + " in call direction")
        ag = _agree(R, ("pa", "smc", "sd", "sr"))
        if ag is not None:
            s += round(max(0.0, ag) * 6)
        P["structure"] = min(20, s)
        tf = (a.get("mtf") or {}).get("tf") or {}
        t = sum(3 for k in ("5m", "15m", "1H") if tf.get(k) == want)
        ag = _agree(R, ("vwap", "mtf"))
        t += round(max(0.0, ag or 0) * 6)
        P["trend"] = min(15, t)
    else:
        P["structure"] = P["trend"] = None
        miss += ["structure", "trend"]
    vr = c.get("vol_ratio")
    if vr is not None or R:
        v = (9 if float(vr) >= 2 else 7 if float(vr) >= 1.5 else 4 if float(vr) >= 1 else 1) if vr is not None else 0
        ag = _agree(R, ("vwap", "vp", "of"))
        v += 6 if (ag or 0) > 0.2 else 3 if ag is not None and ag > -0.2 else 0
        P["volume"] = min(15, v)
        if vr is not None and float(vr) >= 1.5:
            why.append(f"volume {float(vr):.1f}× normal")
    else:
        P["volume"] = None
        miss.append("volume")
    o, have = 0, False
    oi = (ctx.get("money_oi") or {}).get(c["symbol"])
    if oi:
        have = True
        good, bad = (("Long Built Up", "Short Covering"), ("Short Built Up", "Long Unwinding")) if ce else (("Short Built Up", "Long Unwinding"), ("Long Built Up", "Short Covering"))
        o += 10 if oi in good else 0 if oi in bad else 5
        if oi in good:
            why.append(f"futures OI: {oi}")
    ix = (ctx.get("idx") or {}).get(c["symbol"])
    if ix and ix.get("bias"):
        have = True
        b = ix["bias"]
        o += 10 if (("BULL" in b) == ce and "NEUTRAL" not in b) else 5 if "NEUTRAL" in b else 0
        if ix.get("pcr"):
            why.append(f"PCR {ix['pcr']} · {b}")
    cv = str((((ctx.get("enter") or {}).get(c["symbol"]) or {}).get("chain") or {}).get("verdict") or "")
    if cv:
        have = True
        o += 5 if cv.startswith("✅") else -5 if cv.startswith("⛔") else 0
    P["oi"] = max(0, min(15, o)) if have else None
    if not have:
        miss.append("oi")
    sp = c.get("spread_pct")
    e, sl = float(c.get("entry") or 0), float(c.get("sl") or 0)
    risk = (e - sl) * float(c.get("lot") or 1)
    lq = (5 if sp <= 1 else 3 if sp <= 2 else 1 if sp <= 3 else 0) if sp is not None else 0
    lq += 5 if risk <= 2500 else 3 if risk <= 4000 else 0
    P["liquidity"] = lq
    if sp is None:
        miss.append("spread")
    q = (ctx.get("sniper") or {}).get(c["id"]) or {}
    P["mtf"] = round(q["aligned"] / 4 * 10) if q.get("aligned") is not None and a else None
    if P["mtf"] is None:
        miss.append("mtf")
    t1 = (c.get("targets") or [None])[0]
    rr = (t1 - e) / (e - sl) if t1 and e > sl else 0
    P["rr"] = 10 if rr >= 2 else 7 if rr >= 1.5 else 4 if rr >= 1 else 0
    md = ctx.get("mdir")
    P["regime"] = 3 if c.get("exch") == "MCX" else (5 if md == want else 0 if md else 2)
    return P, why, miss


def plan5(c, a, ctx):
    """Up to 5 targets from REAL levels beyond price (S/R, pattern target, prev day/week/month, module targets) → option premium
    via delta (≈0.5 unless known). Fewer levels → fewer targets."""
    ce = c.get("side") != "PE"
    ul = ((ctx.get("live_q") or {}).get(c["symbol"]) or {}).get("ltp") or a.get("px") or c.get("ul_price")
    e = float(c.get("entry") or 0)
    lv = []
    if ul:
        ul = float(ul)
        for x in (a.get("sr_up") if ce else a.get("sr_dn")) or []:
            lv.append((x["price"], "S/R"))
        for k in (("up_target", "pattern target"), ("up_level", "breakout level")) if ce else (("dn_target", "pattern target"), ("dn_level", "breakdown level")):
            if a.get(k[0]):
                lv.append((a[k[0]], k[1]))
        for k, v in ((ctx.get("levels") or {}).get(c["symbol"]) or {}).items():
            if v and k in (("PDH", "PWH", "PMH") if ce else ("PDL", "PWL", "PML")):
                lv.append((v, k))
        for t in c.get("ul_targets") or []:
            lv.append((t, "module target"))
        lv = sorted({round(float(p), 2): n for p, n in lv if p and ((p > ul * 1.0015) if ce else (p < ul * 0.9985))}.items(), key=lambda x: x[0], reverse=not ce)
        clean = []
        for p, n in lv:
            if not clean or abs(p - clean[-1][0]) / ul > 0.0015:
                clean.append((p, n))
        lv = clean[:5]
    delta = abs(float(c.get("delta") or 0.5))
    T = []
    for p, n in lv:
        prem = round(e + delta * abs(p - ul), 2)
        if prem > e * 1.03 and (not T or prem > T[-1]["prem"]):
            T.append({"prem": prem, "ul": p, "why": n})
    src = "structure"
    if not T:
        T = [{"prem": float(t), "ul": None, "why": "module target"} for t in c.get("targets") or [] if t and float(t) > e]
        src = "module"
    inv = c.get("ul_sl") or (a.get("dn_level") if ce else a.get("up_level"))
    return {"targets": T[:5], "ul": ul, "invalid": inv, "delta": delta, "src": src,
            "zone": [round(e * CFG["zone_lo"], 2), round(e * CFG["zone_hi"], 2)], "sl": float(c.get("sl") or 0), "entry": e}


def validate(c, a, pl, ctx, now):
    """10 independent checks. Any FAIL → REJECT. 4+ WARN → DOWNGRADE."""
    ce = c.get("side") != "PE"
    want = "UP" if ce else "DOWN"
    md = ctx.get("mdir")
    ltp, e, sl = float(c.get("ltp") or 0), pl["entry"], pl["sl"]
    tf15 = ((a.get("mtf") or {}).get("tf") or {}).get("15m")
    vr, oi = c.get("vol_ratio"), (ctx.get("money_oi") or {}).get(c["symbol"])
    sp = c.get("spread_pct")
    T = pl["targets"]
    t1 = T[0]["prem"] if T else None
    rr = (t1 - e) / (e - sl) if t1 and e > sl else 0
    exp = c.get("expiry")
    dte = (pd.Timestamp(exp).date() - now.date()).days if exp else None
    vd = (a.get("advice") or {}).get("verdict")
    stt = (a.get("structure") or {}).get("trend")
    ck = [
        ("Market direction", "PASS" if c.get("exch") == "MCX" or md == want else "FAIL" if md else "WARN", f"NIFTY direction {md or 'unclear'}"),
        ("15-minute candle", "PASS" if tf15 == want else "FAIL" if tf15 in ("UP", "DOWN") else "WARN", f"15m trend {tf15 or 'no chart data'}"),
        ("Entry still valid", "FAIL" if ltp and (ltp > e * 1.05 or (sl and ltp <= sl)) else "PASS" if ltp and ltp >= e * 0.97 else "WARN",
         f"LTP ₹{ltp:g} vs entry ₹{e:g}" if ltp else "no LTP"),
        ("Contract liquidity", "PASS" if sp is not None and sp <= 3 else "FAIL" if sp is not None and sp > 6 else "WARN",
         f"spread {sp}%" if sp is not None else "spread not reported for this contract"),
        ("Volume + OI confirm", "PASS" if (vr is not None and float(vr) >= 1.5) or (oi in (("Long Built Up", "Short Covering") if ce else ("Short Built Up", "Long Unwinding")))
         else "WARN", f"volume {vr or '–'}× · OI {oi or '–'}"),
        ("Stoploss justified", "FAIL" if sl >= e else "PASS" if 0.08 <= (e - sl) / e <= 0.45 else "WARN", f"SL {(e - sl) / e * 100:.0f}% below entry" if e else "–"),
        ("Targets realistic", "PASS" if t1 and 1.05 <= t1 / e <= 1.6 else "WARN" if t1 else "FAIL", f"T1 {(t1 / e - 1) * 100:+.0f}%" if t1 else "no target"),
        ("Risk-to-reward", "PASS" if rr >= 1.5 else "WARN" if rr >= 1 else "FAIL", f"1:{rr:.2f}"),
        ("Expiry", "FAIL" if dte is not None and dte < 0 else "WARN" if dte == 0 else "PASS" if dte is not None else "WARN",
         "expiry day — fast theta decay" if dte == 0 else f"{dte} days to expiry" if dte is not None else "expiry unknown"),
        ("Structure unchanged", "FAIL" if vd == "AVOID" or (stt in ("UP", "DOWN") and stt != want) else "PASS" if vd == "TAKE" else "WARN",
         f"chart {vd or 'no verdict'} · structure {stt or '–'}"),
    ]
    fails = [n for n, s_, _ in ck if s_ == "FAIL"]
    warns = [n for n, s_, _ in ck if s_ == "WARN"]
    dec = "REJECT" if fails else "DOWNGRADE" if len(warns) >= 4 else "APPROVE"
    return {"checks": [{"name": n, "status": s_, "detail": d} for n, s_, d in ck], "decision": dec, "fails": fails, "warns": warns, "rr": round(rr, 2)}


def risk_flags(c, ctx, now):
    out = []
    if c.get("expiry") == str(now.date()):
        out.append("expiry day — premiums decay fast after 1 PM")
    for r in ctx.get("results") or []:
        if r.get("symbol") == c["symbol"] and 0 <= (r.get("days") or 9) <= 2:
            out.append(f"results on {r.get('date')} — gap / IV-crush risk")
    cr = ctx.get("crash") or {}
    if cr.get("level") in ("WATCH", "ALERT") and (cr.get("side") == "DOWN") == (c.get("side") != "PE"):
        out.append(f"crash radar {cr['level']} against this side")
    vix = ((ctx.get("ticks") or {}).get("INDIA VIX") or {}).get("pct")
    if vix is not None and vix >= 5:
        out.append(f"India VIX +{vix}% — volatile")
    return out


def advice(c, pl, val):
    ltp, (lo, hi) = float(c.get("ltp") or 0), pl["zone"]
    T = pl["targets"]
    now_ = ("Enter now — premium is inside the entry zone." if lo <= ltp <= hi else
            f"Wait — premium ₹{ltp:g} is above the zone; enter only on a pullback to ₹{lo:g}–₹{hi:g}." if ltp > hi else
            f"Wait — premium ₹{ltp:g} is below the zone; enter only if it climbs back above ₹{lo:g} with a green 5-min candle.")
    return [now_,
            "Confirmation: a 5-minute candle closing in the call direction" + (f" beyond {pl['ul']:g} on the underlying" if pl.get("ul") else "") + ".",
            f"Avoid entry if the 15-min candle closes against the trade, the spread widens above 3%, or price is already past T1.",
            f"Stoploss ₹{pl['sl']:g}" + (f" (underlying invalidation {pl['invalid']:g})" if pl.get("invalid") else "") + " — exit at once, never average a losing option.",
            (f"Book ~50% at T1 ₹{T[0]['prem']:g}, move SL to entry." if T else "No technical target — manage with the stoploss only."),
            (f"After T2 ₹{T[1]['prem']:g}, trail SL to T1." if len(T) > 1 else ""),
            "Exit early if the market reverses (crash radar against you or NIFTY breaks its 15-min low/high)."]


def scan(ctx, now):
    """Scanner + scoring + validation → Top 10 + up to 3 elite. ctx built by server (see server.jarvis_ctx)."""
    day = str(now.date())
    rows = []
    cov = {k: 0 for k in W}
    calls = [c for c in ctx.get("calls") or [] if c.get("date") == day and c.get("status") in OPEN and not c.get("shadow") and c.get("kind") != "PICK"]
    seen = set()
    for c in sorted(calls, key=lambda c: str(c.get("time") or ""), reverse=True):
        key = (c["symbol"], c.get("side"), c.get("strike"))
        if key in seen:
            continue
        seen.add(key)
        a = (ctx.get("charts") or {}).get(c["symbol"]) or {}
        P, why, miss = score(c, a, ctx)
        for k, v in P.items():
            cov[k] += v is not None
        raw = sum(v or 0 for v in P.values())
        pl = plan5(c, a, ctx)
        val = validate(c, a, pl, ctx, now)
        sc = max(0, raw - 3 * len(val["warns"]))
        bad = sorted([k for k, v in P.items() if v is not None and v < W[k] * 0.4], key=lambda k: P[k] / W[k])
        rows.append({"id": c["id"], "symbol": c["symbol"], "strike": c.get("strike"), "side": c.get("side"), "expiry": c.get("expiry"), "exch": c.get("exch"),
                     "contract": c.get("contract"), "ltp": c.get("ltp"), "entry": c.get("entry"), "sl": c.get("sl"), "lot": c.get("lot"), "token": c.get("token"),
                     "time": c.get("time"), "module": c.get("source_label") or c.get("source"), "raw": raw, "score": sc, "rating": rating(sc),
                     "parts": P, "missing": miss, "why": why[:5], "against": [NAME[k] for k in bad[:3]], "plan": pl, "val": val,
                     "risk": "LOW" if (pl["entry"] - pl["sl"]) * float(c.get("lot") or 1) <= 2500 else "MEDIUM" if (pl["entry"] - pl["sl"]) * float(c.get("lot") or 1) <= 4000 else "HIGH",
                     "flags": risk_flags(c, ctx, now), "advice": [x for x in advice(c, pl, val) if x],
                     "status": "Confirmed" if val["decision"] == "APPROVE" else "Pending" if val["decision"] == "DOWNGRADE" else "Rejected",
                     "draw": {"zones": ((a.get("liquidity") or {}).get("zones") or [])[:4], "eq": ((a.get("liquidity") or {}).get("eq") or [])[:4],
                              "events": ((a.get("structure") or {}).get("events") or [])[:3], "sr": (a.get("sr_up") or []) + (a.get("sr_dn") or [])}})
    rows.sort(key=lambda r: (r["val"]["decision"] != "REJECT", r["score"]), reverse=True)
    top = rows[:CFG["top"]]
    integ, cr = (ctx.get("integrity") or {}).get("status"), ctx.get("crash") or {}
    breaker = ("data feed unhealthy — " + "; ".join((ctx.get("integrity") or {}).get("issues") or [])) if integ == "BAD" else \
              (f"crash radar ALERT ({cr.get('side')})" if cr.get("level") == "ALERT" else None)
    against = lambda r: cr.get("level") == "ALERT" and (cr.get("side") == "DOWN") == (r["side"] != "PE")     # crash ALERT blocks only its side
    elite = [] if integ == "BAD" else [r for r in top if r["val"]["decision"] == "APPROVE" and r["score"] >= CFG["elite"]
                                       and r["plan"]["targets"] and not against(r)][:CFG["max_elite"]]
    STATE.update(time=now.strftime("%I:%M:%S %p"), top=top, elite=elite, breaker=breaker, scanned=len(rows),
                 coverage={k: f"{v}/{len(rows)}" for k, v in cov.items()},
                 no_trade=None if elite else "NO TRADE — WAITING FOR HIGH-QUALITY CONFIRMATION")
    return STATE


def _net(rec):
    try:
        from .ai import charges
        return round((rec.get("pnl") or 0) - charges({"lot": rec["lot"], "entry": rec["entry_px"] or rec["orig"]["entry"], "exit": rec.get("exit_px") or rec.get("ltp")}))
    except Exception:
        return rec.get("pnl") or 0


def publish(D, now, send=None):
    """New elite → permanent record with signal ID (original plan immutable; later changes saved as versions)."""
    day = str(now.date())
    J = D.setdefault("jarvis", {"calls": {}, "seq": {}})
    new = []
    for r in STATE["elite"]:
        if any(x["call_id"] == r["id"] or (x["date"] == day and x["contract"] == r["contract"]) for x in J["calls"].values()):
            continue
        J["seq"][day] = J["seq"].get(day, 0) + 1
        sid = f"JV-{day.replace('-', '')}-{J['seq'][day]:03d}"
        pl = r["plan"]
        rec = {"sid": sid, "call_id": r["id"], "date": day, "time": now.strftime("%H:%M:%S"), "symbol": r["symbol"], "strike": r["strike"], "side": r["side"],
               "expiry": r["expiry"], "contract": r["contract"], "exch": r["exch"], "lot": r["lot"], "module": r["module"], "regime": (D.get("_regime") or ""),
               "orig": {"entry": pl["entry"], "zone": pl["zone"], "sl": pl["sl"], "targets": [t["prem"] for t in pl["targets"]], "ul_targets": [t["ul"] for t in pl["targets"]],
                        "invalid": pl["invalid"], "score": r["score"], "rr": r["val"]["rr"], "why": r["why"]},
               "status": "WAITING", "sl": pl["sl"], "entry_px": None, "entry_time": None, "hits": [], "exit_px": None, "exit_time": None,
               "pnl": 0, "ltp": r["ltp"], "versions": [], "type": "Intraday", "source": "paper (simulated on live option prices)"}
        J["calls"][sid] = rec
        new.append(rec)
        if send:
            try:
                T = rec["orig"]["targets"]
                send(f"🤖 JARVIS · BOSS OF THE BOSS CALL {sid}\n{r['symbol']} {r['strike']:g} {r['side']} (exp {r['expiry']})\nEntry ₹{pl['zone'][0]}–₹{pl['zone'][1]} · SL ₹{pl['sl']}\n"
                     + " · ".join(f"T{i + 1} ₹{t}" for i, t in enumerate(T)) + f"\nScore {r['score']}/100 · RR 1:{r['val']['rr']}", f"jv|{sid}", True)
            except Exception:
                pass
    return new


def track(D, now, send=None):
    """Verify every live JARVIS call against the underlying call's live option price."""
    J = (D.get("jarvis") or {}).get("calls") or {}
    calls = D.get("calls") or {}
    hm = now.strftime("%H:%M")
    ev = []
    for rec in J.values():
        if rec["status"] not in LIVE:
            continue
        c = calls.get(rec["call_id"]) or {}
        ltp = float(c.get("ltp") or 0)
        if not ltp:
            continue
        rec["ltp"] = ltp
        o = rec["orig"]
        lo, hi = o["zone"]
        eod = hm >= (CFG["mcx_eod"] if rec.get("exch") == "MCX" else CFG["eod"]) or rec["date"] != str(now.date())
        if rec["status"] == "WAITING":
            if ltp <= rec["sl"] or (c.get("status") not in OPEN and c.get("status")):
                rec.update(status="INVALIDATED", exit_time=hm)
                ev.append((rec, "invalidated before entry"))
            elif lo <= ltp <= hi:
                rec.update(status="ENTRY CONFIRMED", entry_px=ltp, entry_time=hm)
                ev.append((rec, f"entry confirmed ₹{ltp:g}"))
            elif eod:
                rec.update(status="NOT TRIGGERED", exit_time=hm)
            continue
        if rec["status"] == "ENTRY CONFIRMED":
            rec["status"] = "ACTIVE"
        e = rec["entry_px"]
        for i, t in enumerate(o["targets"], 1):
            if ltp >= t and not any(h.startswith(f"T{i} ") for h in rec["hits"]):
                rec["hits"].append(f"T{i} {hm}")
                rec["status"] = f"T{i} HIT"
                ev.append((rec, f"T{i} ₹{t:g} hit"))
                if i == 1 and rec["sl"] < e:
                    rec["versions"].append({"time": hm, "change": f"SL {rec['sl']:g} → {e:g} (entry) after T1"})
                    rec["sl"] = e
                elif i == 2 and rec["sl"] < o["targets"][0]:
                    rec["versions"].append({"time": hm, "change": f"SL {rec['sl']:g} → {o['targets'][0]:g} (T1) after T2"})
                    rec["sl"] = o["targets"][0]
        rec["pnl"] = round((ltp - e) * float(rec["lot"] or 1))
        if ltp <= rec["sl"]:
            rec.update(status="STOPLOSS HIT" if not rec["hits"] else "CLOSED", exit_px=rec["sl"], exit_time=hm, pnl=round((rec["sl"] - e) * float(rec["lot"] or 1)))
            ev.append((rec, f"stoploss ₹{rec['sl']:g}" if not rec["hits"] else f"trailing SL ₹{rec['sl']:g} — closed in profit"))
        elif len(rec["hits"]) == len(o["targets"]) and o["targets"]:
            rec.update(status="CLOSED", exit_px=ltp, exit_time=hm)
            ev.append((rec, "all targets done"))
        elif eod:
            rec.update(status="CLOSED", exit_px=ltp, exit_time=hm)
            ev.append((rec, f"end of day exit ₹{ltp:g}"))
        if rec.get("exit_px") is not None:
            rec["net"] = _net(rec)
    if send:
        for rec, what in ev:
            try:
                send(f"🤖 JARVIS {rec['sid']} · {rec['symbol']} {rec['strike']:g} {rec['side']}: {what}", f"jvt|{rec['sid']}|{what[:12]}", True)
            except Exception:
                pass
    return ev


def performance(D, now, period="all"):
    J = list(((D.get("jarvis") or {}).get("calls") or {}).values())
    if period != "all":
        days = {"day": 0, "week": 6, "month": 30}.get(period, 10 ** 6)
        J = [r for r in J if (now.date() - pd.Timestamp(r["date"]).date()).days <= days]
    trig = [r for r in J if r.get("entry_px") is not None]
    done = [r for r in trig if r["status"] in ("CLOSED", "STOPLOSS HIT")]
    nets = [r.get("net", r.get("pnl") or 0) for r in done]
    wins, losses = [x for x in nets if x > 0], [x for x in nets if x <= 0]
    eq = peak = dd = 0.0
    for x in nets:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)

    def grp(f):
        g = {}
        for r in done:
            k = f(r)
            x = g.setdefault(k, {"n": 0, "w": 0, "net": 0})
            x["n"] += 1
            x["w"] += int(r.get("net", r.get("pnl") or 0) > 0)
            x["net"] += r.get("net", r.get("pnl") or 0)
        return {k: {**v, "win": round(v["w"] / v["n"] * 100)} for k, v in g.items()}
    return {"total": len(J), "triggered": len(trig), "closed": len(done), "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / len(done) * 100) if done else None, "avg_win": round(sum(wins) / len(wins)) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses)) if losses else 0, "pf": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) else None,
            "expectancy": round(sum(nets) / len(nets)) if nets else 0, "max_dd": round(dd), "net": round(sum(nets)),
            "gross": round(sum(r.get("pnl") or 0 for r in done)), "avg_rr": round(sum(r["orig"].get("rr") or 0 for r in J) / len(J), 2) if J else None,
            "not_triggered": sum(1 for r in J if r["status"] == "NOT TRIGGERED"), "invalidated": sum(1 for r in J if r["status"] == "INVALIDATED"),
            "by_side": grp(lambda r: r["side"]), "by_type": grp(lambda r: "Index" if r["symbol"] in IDX else "MCX" if r.get("exch") == "MCX" else "Stock"),
            "by_regime": grp(lambda r: r.get("regime") or "–"), "period": period}


def report(D, now):
    J = sorted(((D.get("jarvis") or {}).get("calls") or {}).values(), key=lambda r: (r["date"], r["time"]), reverse=True)
    return {**{k: STATE.get(k) for k in ("time", "top", "elite", "no_trade", "breaker", "scanned", "coverage")},
            "live": [r for r in J if r["status"] in LIVE], "history": J[:150], "perf": {p: performance(D, now, p) for p in ("day", "week", "month", "all")},
            "weights": W, "names": NAME, "execution": "DISABLED — paper only"}


def answer(q, now):
    """Ask JARVIS — answers only from the current scan (no guessing)."""
    q = str(q or "").lower()
    rows = STATE.get("top") or []
    r = next((x for x in rows if str(x["symbol"]).lower() in q), None) or (STATE.get("elite") or rows or [None])[0]
    if not r:
        return "No open setups scanned yet — JARVIS needs live calls from the modules (market hours)."
    pl, v, P = r["plan"], r["val"], r["parts"]
    nm = f"{r['symbol']} {r['strike']:g} {r['side']}"
    if any(w in q for w in ("invalid", "stop", " sl")):
        return f"{nm}: stoploss ₹{pl['sl']:g}" + (f"; the setup is invalid if the underlying breaks {pl['invalid']:g}." if pl.get("invalid") else ".")
    if any(w in q for w in ("capital", "risk", "money", "lose")):
        rk = (pl["entry"] - pl["sl"]) * float(r["lot"] or 1)
        return f"{nm}: 1 lot = {r['lot']} qty · entry ₹{pl['entry']:g} · SL ₹{pl['sl']:g} → about ₹{rk:,.0f} at risk per lot (plus ~₹60–80 costs)."
    if "entry" in q or "valid" in q or "wait" in q:
        e = next(c for c in v["checks"] if c["name"] == "Entry still valid")
        return f"{nm}: {e['status']} — {e['detail']}. {r['advice'][0]}"
    if " oi" in f" {q}" or "open interest" in q:
        oi_w = "; ".join(w for w in r["why"] if "OI" in w or "PCR" in w)
        return f"{nm}: OI score {P['oi'] if P['oi'] is not None else 'no data'}/15. " + (oi_w or "No OI change reported for this symbol.")
    if "ce" in q and "pe" in q:
        return f"{nm}: JARVIS rates the {r['side']} side because " + ("; ".join(r["why"]) or "the module signal and score favour it") + f". Factors against: {', '.join(r['against']) or 'none major'}."
    return (f"{nm} — score {r['score']}/100 ({r['rating']}) · validator {v['decision']}.\nWhy: " + ("; ".join(r["why"]) or "module signal") +
            f".\nWeak: {', '.join(r['against']) or 'none'} · no data: {', '.join(r['missing']) or 'none'}.\nNext: {r['advice'][0]}")
