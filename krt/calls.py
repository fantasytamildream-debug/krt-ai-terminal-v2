"""எல்லா calls: Jackpot, Intraday, Swing 5D/10D — original levels freeze, தினமும் track, profit/loss history."""
import threading
import pandas as pd
from .config import load_settings
from .store import STORE
from .telegram import send as tg

CALLS_LOCK = threading.Lock()

OPEN = ("OPEN", "T1 HIT", "T2 HIT", "T3 HIT", "T4 HIT")
INTRA = ("JACKPOT", "INTRADAY", "GAMMA", "ELITE", "POWER-A", "POWER-B", "ALL ROUNDER")
SKIPPED = {"day": None, "n": 0, "items": [], "log": []}


def calibrate_plan(source, plan):
    """≥20 closed calls உள்ள setup-க்கு: premium targets = வரலாற்றில் 60% / 40% / 20% calls அடைந்த max லாப % அளவு."""
    cal = (STORE.data or {}).get("calib", {}).get(source)
    if not cal or not plan or not plan.get("entry"):
        return plan
    e = plan["entry"]
    plan["model_targets"] = plan["targets"]
    plan["targets"] = [round(round(e * (1 + q / 100) / 0.05) * 0.05, 2) for q in cal["t_pct"]]
    plan["calibrated"] = f"{source}: {cal['n']} closed calls அடிப்படையில்"
    return plan


def _f(x):
    try:
        return float(x)
    except Exception:
        return 0.0


MARKET = {"trend": None}
TREND_SRC = {"Breakout/Breakdown", "5-min ORB", "Elite intraday", "Volume+OI", "All rounder"}
PULLBACK_SRC = {"Breakout/Breakdown", "5-min ORB", "Elite intraday", "Volume+OI"}
QCODE_TXT = {"TIME_OPEN_NOISE": "9:30-க்கு முன் (noise)", "TIME_LUNCH": "11:30–1:15 lunch chop", "AFTER_2PM": "2 PM-க்கு பிறகு",
             "RANGE_DAY": "Range நாள் — breakout off", "COUNTER_TREND": "Market direction எதிர்", "RVOL_LT_2": "Volume 2×-க்கு கீழ்",
             "SPREAD_GT_2": "Spread 2%-க்கு மேல்", "ONE_PER_STOCK": "இந்த stock-க்கு இன்று ஏற்கனவே call", "DAILY_MAX": "இன்று max calls முடிந்தது",
             "SL_STREAK": "தொடர்ந்து 2 SL — இன்று stop", "NIFTY_FLAT": "NIFTY flat (±0.15%) — direction இல்லை",
             "RISK_CAP": "1 lot risk ₹2,500-க்கு மேல்", "T1_UNREALISTIC": "T1-க்கு stock அதிகம் போகணும்", "DAILY_LOSS_STOP": "இன்றைய loss limit தாண்டியது"}


def _qcfg():
    q = load_settings().get("quality") or {}
    return {"enabled": q.get("enabled", True), "min_rvol": q.get("min_rvol", 2.0), "max_calls": q.get("max_calls_per_day", 3),
            "max_spread": q.get("max_spread_pct", 2.0), "pullback": q.get("pullback_entry", True)}


def _regime_side():
    try:
        from .sniper import REGIME
    except Exception:
        REGIME = {}
    if REGIME.get("state") == "TRENDING":
        return {"UP": "CE", "DOWN": "PE"}.get(REGIME.get("dir"))
    if REGIME.get("state") in ("RANGE", "HIGH-VOL"):
        return None
    return {"TRENDING UP": "CE", "TRENDING DOWN": "PE"}.get(MARKET.get("trend"))


def quality_gate(c, calls, now):
    """V3.1 call quality rules. Fail ஆனா call main list-ல் வராது — shadow-ல் (பழைய rule) track ஆகும்."""
    q = _qcfg()
    if not q["enabled"]:
        return []
    codes, mins, intra = [], now.hour * 60 + now.minute, not c.get("hold_until")
    if intra:
        if mins < 9 * 60 + 30:
            codes.append("TIME_OPEN_NOISE")
        elif 11 * 60 + 30 <= mins < 13 * 60 + 15:
            codes.append("TIME_LUNCH")
        elif mins >= 14 * 60:
            codes.append("AFTER_2PM")
    if c["source"] in TREND_SRC:
        side = _regime_side()
        if side is None and c["source"] in ("5-min ORB", "All rounder"):
            np_ = MARKET.get("nifty_pct")     # range / unclear நாளிலும் ORB, All rounder: NIFTY இன்றைய direction போதும்
            side = "CE" if (np_ or 0) >= 0.15 else "PE" if (np_ or 0) <= -0.15 else None
            if side is None:
                codes.append("NIFTY_FLAT")
            elif side != c["side"]:
                codes.append("COUNTER_TREND")
        elif side is None:
            codes.append("RANGE_DAY")
        elif side != c["side"]:
            codes.append("COUNTER_TREND")
        if c.get("vol_ratio") is not None and c["vol_ratio"] < q["min_rvol"]:
            codes.append("RVOL_LT_2")
    if (c.get("spread_pct") or 0) > q["max_spread"]:
        codes.append("SPREAD_GT_2")
    if intra:
        # max calls / one-per-stock / SL streak — Grade A calls (நீங்க எடுப்பவை) மட்டும் எண்ணு
        main = [x for x in calls.values() if x["date"] == c["date"] and not x.get("shadow") and not x.get("hold_until")
                and x.get("grade", "A") == "A"]
        if any(x["symbol"] == c["symbol"] for x in main):
            codes.append("ONE_PER_STOCK")
        if len(main) >= q["max_calls"]:
            codes.append("DAILY_MAX")
        closed = sorted([x for x in main if x["status"] not in OPEN], key=lambda x: x.get("exit_time") or "")
        if len(closed) >= 2 and all(x["status"] == "SL HIT" for x in closed[-2:]):
            codes.append("SL_STREAK")
    return codes


def _reject(day, kind, src, r, opt, code, now=None, extra=""):
    """Rejected signal-க்கு reason code பதிவு (Today tab-ல் தெரியும்)."""
    if SKIPPED["day"] != day:
        SKIPPED.update(day=day, n=0, items=[], log=[])
    k = f"{kind}|{r.get('symbol')}|{(opt or {}).get('contract')}|{code}"
    if k in SKIPPED["items"]:
        return
    SKIPPED["items"].append(k)
    SKIPPED["n"] += 1
    SKIPPED["log"].append({"time": now.strftime("%H:%M") if now is not None else "", "kind": kind, "source": src,
                           "symbol": r.get("symbol"), "contract": (opt or {}).get("contract"), "code": code, "detail": extra})
    del SKIPPED["log"][:-80]


def _new(kind, src, r, opt, now, day, hold=0, session=None):
    p = (opt or {}).get("plan")
    if not p or not opt.get("token"):
        return None
    if hold and p.get("risk") is not None:   # Holding (swing / elite hold / pattern): தனி risk cap (default ₹5,000)
        try:
            from .config import load_settings as _ls
            cap_h = (_ls().get("risk") or {}).get("max_risk_holding", 5000)
        except Exception:
            cap_h = 5000
        p = dict(p, risk_ok=p["risk"] <= cap_h)
    force_ = []
    if p.get("risk_ok") is False:      # V3.2: skip இல்லை — Grade C-ஆ வரும் (risk காட்டும்)
        force_.append("RISK_CAP")
    cid = f"{day}|{kind}|{r['symbol']}|{opt['contract']}"
    if not p.get("calibrated") and (STORE.data or {}).get("calib", {}).get(src) and kind not in ("GAMMA",):
        p = calibrate_plan(src, dict(p))
    if not p.get("money") and r.get("price"):   # safety net — எல்லா calls-க்கும் ₹ targets
        try:
            from .optmath import money_targets
            p = money_targets(dict(p), opt.get("lot"), r["price"], opt.get("strike"), opt.get("expiry"), opt.get("type"),
                              now.to_pydatetime() if hasattr(now, "to_pydatetime") else now, None, not hold)
        except Exception:
            pass
    if p.get("reward_ok") is False:      # V3.2: Grade C
        force_.append("T1_UNREALISTIC")
    try:
        from .sniper import REGIME as _RG
        reg_ = (_RG.get("state") or "") + (" " + _RG["dir"] if _RG.get("dir") else "")
    except Exception:
        reg_ = ""
    c = {"force_codes": force_, "ver": "V3.2", "regime": reg_ or None, "spread_pct": opt.get("spread_pct"), "vol_ratio": r.get("vol_ratio"),
         "trail_after_t1": True, "trail_after_t2": True,       # T1 → SL entry, T2 → SL T1, T3 → exit
         "time_stop": None if hold else str(now + pd.Timedelta(minutes=30)), "id": cid, "kind": kind, "source": src, "date": day, "time": now.strftime("%H:%M"),
         "symbol": r["symbol"], "side": opt["type"], "contract": opt["contract"], "token": opt["token"],
         "exch": opt["exch"], "strike": opt["strike"], "expiry": opt["expiry"], "lot": opt["lot"],
         "ul_price": r.get("price"), "ul_sl": r.get("sl"), "ul_targets": r.get("targets"),
         "entry": p["entry"], "sl": p["sl"], "targets": p["targets"], "risk": p["risk"], "risk_ok": p["risk_ok"],
         "score": r.get("score"), "stars": r.get("stars"), "confidence": r.get("confidence") or f"{r.get('stars', 0)}★",
         "reasons": r.get("reasons") or ([f"{'+'.join(r['levels'])} break"] if r.get("levels") else []),
         "ltp": p["entry"], "status": "OPEN", "hits": [], "exit": None, "exit_time": None, "pnl_lot": 0,
         "calibrated": bool(p.get("calibrated"))}
    if hold:
        c["hold_days"] = hold
        c["hold_until"] = str(pd.bdate_range(session, periods=hold + 1)[-1].date())
    return c


IMPORTANT_KINDS = ("ELITE", "ELITE HOLD", "JACKPOT", "GAMMA", "GU-INTRADAY", "GU-HOLDING", "SWING 5D", "SWING 10D")


def guide(c, now):
    """ஒவ்வொரு call-க்கும் இப்போ என்ன செய்யலாம் — rule-based வழிகாட்டல் (advice இல்லை)."""
    st, ltp, e = c["status"], c.get("ltp") or 0, c["entry"] or 0
    mins = now.hour * 60 + now.minute
    intra = c["kind"] in INTRA or c.get("intraday")
    tg_ = c.get("targets") or []
    if st not in OPEN:
        return "CLOSED", f"முடிந்தது — {st}"
    if intra and mins >= 15 * 60:
        return "EXIT", "3:20-க்கு முன் exit பண்ணுங்க (intraday)"
    if c.get("hold_until") and str(now.date()) >= c["hold_until"]:
        return "EXIT", "இன்று holding கடைசி நாள் — exit"
    if any(h.startswith("T2 ") for h in c["hits"]):
        nxt = f" · அடுத்த target ₹{tg_[2]}" if len(tg_) > 2 else ""
        return "BOOK", f"T2 ✅ — SL-ஐ T1 ₹{tg_[0]}-க்கு மாத்துங்க (லாபம் lock){nxt}"
    if any(h.startswith("T1 ") for h in c["hits"]):
        return "BOOK", f"T1 ✅ — SL-ஐ entry ₹{e}-க்கு மாத்துங்க (இனி நஷ்டம் இல்லை)"
    if intra and mins >= 14 * 60 + 45:
        return "LATE", "நேரம் முடிந்தது — புது entry வேண்டாம்"
    if e and ltp > e * 1.04:
        return "LATE", f"Entry-ஐ விட {((ltp / e - 1) * 100):.0f}% மேலே — chase வேண்டாம், pullback-க்கு காத்திருங்க"
    if e and ltp < e * 0.9:
        return "WEAK", f"Entry-க்கு கீழே — SL ₹{c['sl']} கவனிங்க, புது entry வேண்டாம்"
    return "ENTRY", f"Entry zone-க்குள் (₹{e}) — rules படி எடுக்கலாம், SL ₹{c['sl']}"


def _close(c, status, price, when):
    c.update(status=status, exit=price, exit_time=when)
    c["pnl_lot"] = round((price - c["entry"]) * c["lot"])


def update_calls(ag, session, now, live, best, orb, voi, idx, swing, add=True, patterns=(), gamma=(), gu=(),
                 elite=(), elite_hold=(), footprint=(), power=()):
    with CALLS_LOCK:
        return _update_calls(ag, session, now, live, best, orb, voi, idx, swing, add, patterns, gamma, gu, elite,
                             elite_hold, footprint, power)


def _gu_call(sig, now, day):
    """V3 PRO: INTRADAY (hard SL, 15:20 exit) / HOLDING (hard SL, T1→SL entry, T2→SL T1, max 5 days / expiry-1)."""
    e, sl = sig["entry"], sig["sl"]
    eng = sig.get("engine", "INTRADAY")
    opt = {"token": sig["token"], "exch": sig["exch"], "contract": sig["contract"], "strike": sig["strike"],
           "type": sig["side"], "expiry": sig["expiry"], "lot": sig["lot"],
           "plan": {"entry": e, "sl": sl, "targets": sig["targets"], "risk": sig["risk"], "risk_ok": sig["risk"] <= 2500}}
    r = {"symbol": sig["symbol"], "price": sig.get("ul_close"), "sl": sig["edge"], "targets": [], "stars": 5,
         "confidence": f"{sig['score']}/100 {sig['tier']}",
         "reasons": [f"{sig['setup']} · {sig['trigger']} @ {sig['time']}", f"Zone {sig['zone'][0]}–{sig['zone'][1]}",
                     f"OI drop {(sig.get('oi') or {}).get('drop', '–')}% · RV {sig.get('rv')}×", f"ID {sig['id']}"]}
    c = _new("GU-" + eng, "Gamma unwind V3", r, opt, now, day)
    if not c:
        return None
    c.update(trail_after_t1=True, trail_after_t2=(eng == "HOLDING"), zone=sig["zone"], ul_token=sig.get("ul_token"),
             intraday=(eng == "INTRADAY"), signal_id=sig["id"], engine=eng)
    if eng == "HOLDING":
        hu = pd.bdate_range(now.normalize(), periods=6)[-1].date()
        exp_minus1 = (pd.Timestamp(sig["expiry"]) - pd.tseries.offsets.BDay(1)).date()
        c["hold_until"] = str(min(hu, exp_minus1))
    tg(f"🚀 GU {eng} ENTRY tracked: {c['symbol']} {c['strike']:g} {c['side']} @ {e} · SL {sl} · " +
       " · ".join(f"T{i+1} {t}" for i, t in enumerate(c["targets"])), f"trk|{c['id']}")
    return c


def _update_calls(ag, session, now, live, best, orb, voi, idx, swing, add, patterns, gamma, gu, elite=(), elite_hold=(),
                  footprint=(), power=()):
    d = STORE.load()
    calls, pub = d["calls"], d["published"]
    day = str(session.date())
    flag = pub.setdefault(day, {})
    changed = False

    def add(c):
        nonlocal changed
        if not c:
            return None
        intra_ = not c.get("hold_until")
        for x in calls.values():   # ஒரே contract ஒரே நாள் வேறு setup-லும் வந்தா → புது call இல்லை, source சேர்த்து ஒரே call
            if x["date"] == c["date"] and x["contract"] == c["contract"] and (not x.get("hold_until")) == intra_:
                srcs = x.setdefault("sources", [x.get("source") or x["kind"]])
                if c["source"] not in srcs:
                    srcs.append(c["source"])
                    x["source_label"] = " + ".join(srcs)
                    changed = True
                return None
        risk_cfg = load_settings().get("risk") or {}
        if not c.get("hold_until"):
            day_net = sum(x.get("pnl_lot") or 0 for x in calls.values() if x["date"] == c["date"] and not x.get("shadow")
                          and x.get("grade", "A") == "A" and x["status"] not in OPEN)   # Grade A closed calls மட்டும்
            if day_net <= -abs(risk_cfg.get("daily_loss_limit", 5000)):
                c.setdefault("force_codes", []).append("DAILY_LOSS_STOP")
            if risk_cfg.get("breakeven_after_t1", True):
                c.setdefault("trail_after_t1", True)     # T1 பிறகு SL → entry (break-even)
        codes = (c.get("force_codes") or []) + quality_gate(c, calls, now)   # V3.2: block இல்லை — grade மட்டும்
        hard_ = {"TIME_OPEN_NOISE", "AFTER_2PM", "COUNTER_TREND", "RANGE_DAY", "SL_STREAK", "DAILY_MAX",
                 "RISK_CAP", "T1_UNREALISTIC", "DAILY_LOSS_STOP"}
        c["grade"] = "A" if not codes else ("C" if any(x in hard_ for x in codes) else "B")
        c["qcodes"] = codes
        c["qtext"] = [QCODE_TXT.get(x, x) for x in codes]
        if (c["grade"] == "A" and c["source"] in PULLBACK_SRC and not c.get("hold_until") and _qcfg()["pullback"] and c.get("ul_price")
                and d.get("edge", {}).get(c["source"]) != "NEGATIVE"):
            try:
                from .instruments import _MEM
                ul_tok = ((_MEM.get("data") or {}).get("eq") or {}).get(c["symbol"])
                from .fullscan import C as _FC
                atr_ = ((_FC.get("feat") or {}).get(c["symbol"]) or {}).get("atr")
            except Exception:
                ul_tok, atr_ = None, None
            if ul_tok:
                imm = dict(c, id=c["id"] + "|IMM", shadow=True, variant="IMMEDIATE", hits=[])   # பழைய rule: உடனே entry
                calls[imm["id"]] = imm
                d.setdefault("pending", {})[c["id"]] = {"call": c, "created": str(now), "sig_ul": c["ul_price"], "ul_sl": c.get("ul_sl"),
                                                        "atr": atr_ or c["ul_price"] * 0.01, "ul_token": ul_tok,
                                                        "hi": c["ul_price"], "lo": c["ul_price"], "pulled": False}
                changed = True
                return None
        if d.get("edge", {}).get(c["source"]) == "NEGATIVE" and (load_settings().get("auto_pause_negative", False)):
            c["shadow"] = True       # 20+ closed calls-ல் சராசரி நஷ்டம் → ⏸ PAUSED: paper-ல் மட்டும் track, main list-ல் இல்லை
            _reject(c["date"], c["kind"], c["source"], c, {"contract": c["contract"]}, "PAUSED_NEGATIVE_EDGE", now)
        if c["id"] not in calls:
            calls[c["id"]] = c
            changed = True
            return None if c.get("shadow") else c["id"]

    if not load_settings().get("auto_pause_negative", False):     # V3.2: hide ஆன calls மீண்டும் main list-க்கு
        for x in calls.values():
            if x.get("shadow") and x.get("variant") != "IMMEDIATE":
                codes_ = x.get("qcodes") or []
                hard_ = {"TIME_OPEN_NOISE", "AFTER_2PM", "COUNTER_TREND", "RANGE_DAY", "SL_STREAK", "DAILY_MAX"}
                x.update(shadow=False, variant=None, grade=("A" if not codes_ else "C" if any(k in hard_ for k in codes_) else "B"),
                         qtext=[QCODE_TXT.get(k, k) for k in codes_])
                changed = True
    # பழைய duplicate calls-ஐ ஒன்றாக்கு (ஒரே நாள் · ஒரே contract · intraday/holding ஒன்று)
    seen_ = {}
    for cid_ in sorted(calls, key=lambda k: (calls[k]["date"], calls[k]["time"])):
        x = calls[cid_]
        k_ = (x["date"], x["contract"], bool(x.get("hold_until")), bool(x.get("shadow")), x.get("variant"))
        if k_ in seen_:
            keep = calls[seen_[k_]]
            srcs = keep.setdefault("sources", [keep.get("source") or keep["kind"]])
            if (x.get("source") or x["kind"]) not in srcs:
                srcs.append(x.get("source") or x["kind"])
            keep["source_label"] = " + ".join(srcs)
            del calls[cid_]
            changed = True
        else:
            seen_[k_] = cid_

    mins = now.hour * 60 + now.minute
    if live and mins < 15 * 60 + 15:
        for r in list(elite) + list(elite_hold):
            hold = r in elite_hold
            rr = dict(r)
            rr["reasons"] = (["👑 ELITE JACKPOT — இரண்டு scanner"] if r.get("jackpot") else []) + (r.get("why") or [])
            rr["confidence"] = f"{r['confidence']}%"
            c = _new("ELITE HOLD" if hold else "ELITE", "Elite holding" if hold else "Elite intraday", rr, r.get("option"),
                     now, day, 10 if hold else 0, session)
            if c and hold:
                exp2 = (pd.Timestamp(c["expiry"]) - pd.tseries.offsets.BDay(2)).date()
                c["hold_until"] = min(c["hold_until"], str(exp2))
            cid = add(c)
            if cid and r.get("jackpot"):
                o = r.get("option") or {}
                p = o.get("plan") or {}
                tg("🟢👑 ELITE JACKPOT\n" + f"{r['symbol']} {o.get('strike', ''):g} {r['side']} — {'HOLDING' if hold else 'INTRADAY'}" +
                   (" (mirror PE)" if r.get("mirror") else "") +
                   f"\nEntry ₹{p.get('entry')} · SL ₹{p.get('sl')}\n" +
                   " · ".join(f"T{i+1} ₹{t}" for i, t in enumerate(p.get("targets") or [])) +
                   f"\nConfidence {r['confidence']}% · Expiry {o.get('expiry')}\n" + "\n".join("• " + w for w in r.get("why", [])[:5]) +
                   "\n(Paper/alert only — not advice)", f"elite|{cid}")
    if add and live and mins < 15 * 60 + 15:
        # Jackpot: ஒரு நாளுக்கு ஒரு CE + ஒரு PE — 4★+, CONFIRMED, liquid option, risk limit உள்ளே
        for side in ("CE", "PE"):
            if flag.get(f"jackpot_{side}"):
                continue
            c = [r for r in best if r["side"] == side and r.get("stars", 0) >= 4 and not r.get("low_rr")
                 and ((r.get("option") or {}).get("plan") or {}).get("risk_ok")
                 and d.get("edge", {}).get("Breakout/Breakdown") != "NEGATIVE"]
            if c:
                cid = add(_new("JACKPOT", "Breakout/Breakdown", c[0], c[0]["option"], now, day))
                if cid:
                    flag[f"jackpot_{side}"] = cid
        for r in best:
            add(_new("INTRADAY", "Breakout/Breakdown", r, r.get("option"), now, day))
        for r in orb:
            if r.get("status") == "CONFIRMED":
                add(_new("INTRADAY", "5-min ORB", r, r.get("option"), now, day))
        for r in voi:
            add(_new("INTRADAY", "Volume+OI", r, r.get("option"), now, day))
        for x in idx:
            pl = (x.get("plans") or {}).get(x.get("suggest"))
            if pl and x.get("confidence") == "OI bias":
                add(_new("INTRADAY", "Index OI", {"symbol": x["index"], "price": x["spot"], "sl": pl["ul_sl"],
                                                  "targets": pl["ul_targets"]}, pl["option"], now, day))
    if live and 9 * 60 + 30 <= mins <= 14 * 60 + 30:
        for r in power:   # 🎯 POWER OI: gates எல்லாம் pass ஆன ENTRY CONFIRMED மட்டும்
            o = r.get("option")
            if not o or not o.get("plan"):
                continue
            kind = "POWER-B" if r.get("model") == "B" else "POWER-A"
            rr = {"symbol": r["symbol"], "price": r["ltp"], "sl": r["ul_inval"], "targets": [], "stars": 5,
                  "confidence": f"{r['grade']} {r['score']}",
                  "reasons": [f"Model {r['model']} · {r.get('level_name')} {r['level']}", f"Retest {r.get('retest_bar', '–')} · entry bar {r.get('entry_bar', '–')}",
                              f"RVOL {r['rvol']}× · RS {r['rs_vs_nifty']:+.2f}%"]}
            c = _new(kind, "POWER OI" if kind == "POWER-A" else "POWER OI (reversal research)", rr, o, now, day)
            if c:
                c.update(ul_token=r.get("ul_token"), ul_inval=r["ul_inval"], exit_at=2, trail_after_t1=True,
                         time_stop=str(now + pd.Timedelta(minutes=5 * 6)))
                if add(c):
                    tg(f"🎯 POWER OI {r['grade']} ENTRY · Model {r['model']}\n{r['symbol']} {o['strike']:g} {r['side']} ({o['moneyness']}, Δ {o.get('delta')})\n"
                       f"Entry ₹{o['plan']['entry']} · SL ₹{o['plan']['sl']} · T1 ₹{o['plan']['targets'][0]} · T2 ₹{o['plan']['targets'][1]} · T3 ₹{o['plan']['targets'][2]}\n"
                       f"Stock invalidation {r['ul_inval']} · Risk ₹{o['plan']['risk']} · Score {r['score']}\n(Paper/alert only)", f"pw|{c['id']}")
        for x in footprint:   # OI footprint: writers bias உள்ள index — ஒரு index-க்கு ஒரு நாளைக்கு ஒரு call
            pl = x.get("plan")
            fk = f"fp_{x['index']}"
            if not x.get("bias") or not pl or flag.get(fk):
                continue
            r = {"symbol": x["index"], "price": x.get("spot"), "sl": pl.get("ul_sl"), "targets": pl.get("ul_targets"),
                 "stars": 4, "confidence": "OI writers bias", "reasons": [x.get("why", "")]}
            cid = add(_new("INTRADAY", "OI Footprint", r, pl.get("option"), now, day))
            if cid:
                flag[fk] = cid
    if live and mins < 15 * 60 + 15:
        for sig in gu:
            add(_gu_call(sig, now, day))
        for gm in gamma:  # Gamma: trigger ஆனவுடன் (30-sec tick-லும்) call சேரும், ஒரு index/side-க்கு ஒன்று
            gk = f"gamma_{gm['name']}_{gm['side']}"
            if flag.get(gk) or not (gm.get("option") or {}).get("plan"):
                continue
            r = {"symbol": gm["name"], "price": gm["spot"], "sl": gm["day_low"] if gm["side"] == "CE" else gm["day_high"],
                 "targets": [], "stars": 5, "confidence": "HIGH RISK", "reasons": gm.get("reasons")}
            cid = add(_new("GAMMA", "Gamma blast", r, gm["option"], now, day))
            if cid:
                flag[gk] = cid
    if add and live and mins < 15 * 60 + 15:
        for p in patterns:
            r = dict(p)
            r["reasons"] = [f"{p['pattern']} ({p['timeframe']}) {p['status']}", p["confirm_rule"], p.get("note", "")]
            r["confidence"] = f"{p.get('stars', 0)}★"
            add(_new("PATTERN 5D", "Chart pattern", r, p.get("option"), now, day, 5, session))
    # Swing: 3:00 PM-க்கு பிறகு ஒரு முறை publish (அன்றைய close அருகில் confirm)
    if add and live and 14 * 60 + 30 <= mins <= 15 * 60 + 25 and not flag.get("swing"):
        n_ = 0
        for key in ("10", "5"):
            for r in swing.get(key, []):
                n_ += bool(add(_new(f"SWING {key}D", "Swing", r, r.get("option"), now, day, int(key), session)))
        if n_ or mins >= 15 * 60 + 20:     # ஒண்ணும் சேரலைன்னா 3:20 வரை மீண்டும் முயற்சி
            flag["swing"] = now.strftime("%H:%M")
            changed = True

    # ---- update open calls ----
    open_ = [c for c in calls.values() if c["status"] in OPEN]
    for c in open_:
        if (c["kind"] in INTRA or c.get("intraday")) and c["date"] < day:
            _close(c, "EOD EXIT", c["ltp"], c["date"] + " 15:20")
            changed = True
    open_ = [c for c in calls.values() if c["status"] in OPEN]
    toks = {}
    pend = d.setdefault("pending", {})
    for k_, pd_ in list(pend.items()):
        if pd_["call"]["date"] != day:
            del pend[k_]
            changed = True
            continue
        toks.setdefault("NSE", []).append(pd_["ul_token"])
        toks.setdefault(pd_["call"]["exch"], []).append(pd_["call"]["token"])
    for c in open_:
        toks.setdefault(c["exch"], []).append(c["token"])
        if c.get("ul_token"):
            toks.setdefault("NSE", []).append(c["ul_token"])
    qs = ag.quotes(toks) if (toks and live) else {}
    # 📥 Pullback entry: breakout-க்கு பிறகு 0.25 ATR pullback → signal price-ஐ மீண்டும் தாண்டினா தான் entry
    for k_, pd_ in list(pend.items()):
        c = pd_["call"]
        uq, oq = qs.get(pd_["ul_token"]), qs.get(c["token"])
        u, o = (_f(uq.get("ltp")) if uq else 0), (_f(oq.get("ltp")) if oq else 0)
        if not u:
            continue
        ce = c["side"] == "CE"
        pd_["hi"], pd_["lo"] = max(pd_["hi"], u), min(pd_["lo"], u)
        if (ce and u <= pd_["hi"] - 0.25 * pd_["atr"]) or (not ce and u >= pd_["lo"] + 0.25 * pd_["atr"]):
            pd_["pulled"] = True
        if pd_["pulled"]:          # pullback-ன் கடைசி low (CE) / high (PE)
            pd_["pl"] = min(pd_.get("pl", u), u) if ce else max(pd_.get("pl", u), u)
        inval = pd_.get("ul_sl") and ((u < pd_["ul_sl"]) if ce else (u > pd_["ul_sl"]))
        expired = now - pd.Timestamp(pd_["created"]) > pd.Timedelta(minutes=45) or mins >= 14 * 60
        if inval or expired:
            _reject(day, c["kind"], c["source"], c, {"contract": c["contract"]}, "PULLBACK_FAILED" if inval else "NO_PULLBACK", now,
                    "stock SL உடைந்தது" if inval else "45 நிமிடத்தில் pullback entry வரல")
            del pend[k_]
            changed = True
            continue
        resumed = pd_["pulled"] and ((u > pd_["sig_ul"] and u >= pd_["pl"] + 0.1 * pd_["atr"]) if ce
                                     else (u < pd_["sig_ul"] and u <= pd_["pl"] - 0.1 * pd_["atr"]))
        if resumed and o:
            ratio = o / c["entry"] if c["entry"] else 1
            from .optmath import MONEY
            mins_ = MONEY.get("mins", (1200, 3000, 6000))
            c["entry"], c["sl"] = round(o, 2), round(c["sl"] * ratio, 2)
            c["targets"] = [round(max(t * ratio, o + m / c["lot"]), 2) for t, m in zip(c["targets"], mins_)]
            c["risk"] = round((o - c["sl"]) * c["lot"] + 150)
            del pend[k_]
            changed = True
            if c["risk"] > ((load_settings().get("risk") or {}).get("max_risk_per_trade", 2500)):
                _reject(day, c["kind"], c["source"], c, {"contract": c["contract"]}, "RISK_CAP", now, f"pullback entry risk ₹{c['risk']}")
                continue
            c.update(id=c["id"] + "|PB", time=now.strftime("%H:%M"), entry_type="PULLBACK", ltp=o, max_ltp=o, min_ltp=o,
                     time_stop=str(now + pd.Timedelta(minutes=30)))
            calls[c["id"]] = c
            tg(f"📥 PULLBACK ENTRY · {c['source']}\n{c['symbol']} {c['strike']:g} {c['side']} @ ₹{o}\nSL ₹{c['sl']} · " +
               " · ".join(f"T{i+1} ₹{t}" for i, t in enumerate(c["targets"])) + "\nT1 → SL entry · T2 → SL T1 · 30 min time stop\n(Paper/alert only)",
               f"pb|{c['id']}")
    open_ = [c for c in calls.values() if c["status"] in OPEN]
    for c in open_:
        q = qs.get(c["token"])
        ltp = _f(q.get("ltp")) if q else 0
        if ltp:
            c["ltp"] = ltp
            c["updated"] = now.strftime("%d-%m %H:%M")
            c["max_ltp"] = max(c.get("max_ltp") or c["entry"], ltp)
            c["min_ltp"] = min(c.get("min_ltp") or c["entry"], ltp)
            c["mfe_pct"] = round((c["max_ltp"] - c["entry"]) / c["entry"] * 100, 1) if c["entry"] else 0
            c["mae_pct"] = round((c["min_ltp"] - c["entry"]) / c["entry"] * 100, 1) if c["entry"] else 0
            gu_ = c["kind"].startswith("GU") or c["kind"] == "GAMMA-UNWIND"
            if ltp <= c["sl"] and not (c.get("no_sl_before_t1") and not c["hits"]):
                c["hits"].append(f"SL {now:%d-%m %H:%M}")
                _close(c, "SL HIT" if not c["hits"][:-1] else "TRAIL SL", ltp, str(now))
                if gu_:
                    tg(f"GAMMA-UNWIND exit: {c['symbol']} {c['strike']} {c['side']} @ {ltp} ({c['status']}) P/L/lot ₹{c['pnl_lot']}")
                changed = True
                continue
            for i, tgt in enumerate(c["targets"], 1):
                if ltp >= tgt and not any(h.startswith(f"T{i} ") for h in c["hits"]):
                    c["hits"].append(f"T{i} {now:%d-%m %H:%M}")
                    c["status"] = f"T{i} HIT"
                    if i == 1 and c.get("trail_after_t1"):
                        c["sl"] = c["entry"]  # T1 பின் SL → entry
                        if gu_:
                            tg(f"🔁 Trailing stop update: {c['symbol']} {c['strike']:g} {c['side']} SL → {c['sl']}")
                    if i == 2 and c.get("trail_after_t2"):
                        c["sl"] = c["targets"][0]
                        if gu_:
                            tg(f"🔁 Trailing stop update: {c['symbol']} {c['strike']:g} {c['side']} SL → {c['sl']} (T1)")
                    if c["kind"] in IMPORTANT_KINDS and not gu_:
                        tg(f"✅ T{i} HIT · {c['kind']} · {c['symbol']} {c['strike']:g} {c['side']} @ ₹{ltp} (entry ₹{c['entry']})\n" +
                           (f"👉 SL → entry ₹{c['entry']}" if i == 1 else f"👉 SL → T1 ₹{c['targets'][0]}" if i == 2 else "👉 T3 — full exit"), f"t{i}|{c['id']}")
                    if gu_:
                        tg(f"GAMMA-UNWIND T{i} HIT ✅ {c['symbol']} {c['strike']} {c['side']} @ {ltp}" + (" · SL → entry" if i == 1 else ""))
                    changed = True
            if c["status"] == f"T{len(c['targets'])} HIT":
                _close(c, f"T{len(c['targets'])} DONE", ltp, str(now))
                continue
            if c.get("exit_at") and any(h.startswith(f"T{c['exit_at']} ") for h in c["hits"]):
                _close(c, f"T{c['exit_at']} EXIT", ltp, str(now))
                changed = True
                continue
            if (c.get("time_stop") and not c.get("hold_until") and not c["kind"].startswith("POWER")
                    and str(now) >= c["time_stop"] and not c["hits"] and ltp < c["entry"] * 1.10):
                _close(c, "TIME STOP", ltp, str(now))      # 30 நிமிடத்தில் +10% வரல → exit
                changed = True
                continue
            if c["kind"].startswith("POWER"):
                uq = qs.get(c.get("ul_token")) if c.get("ul_token") else None
                u = _f(uq.get("ltp")) if uq else 0
                if u and ((u < c["ul_inval"]) if c["side"] == "CE" else (u > c["ul_inval"])):
                    _close(c, "INVALIDATED", ltp, str(now))
                    tg(f"❌ POWER OI invalidated: {c['symbol']} {c['strike']:g} {c['side']} @ ₹{ltp} · P/L/lot ₹{c['pnl_lot']}")
                    changed = True
                    continue
                if c.get("time_stop") and str(now) >= c["time_stop"] and not c["hits"] and ltp < c["entry"] * 1.05:
                    _close(c, "TIME STOP", ltp, str(now))
                    changed = True
                    continue
                if mins >= 15 * 60 + 15:
                    _close(c, "EOD EXIT", ltp, str(now))
                    changed = True
                    continue
            if c["kind"].startswith("GU-") and c.get("zone") and c.get("ul_token"):
                uq = qs.get(c["ul_token"])
                u = _f(uq.get("ltp")) if uq else 0
                inv = u and ((u < c["zone"][0]) if c["side"] == "CE" else (u > c["zone"][1]))
                if inv and (c.get("intraday") or mins >= 15 * 60 + 25):
                    _close(c, "INVALIDATED", ltp, str(now))
                    tg(f"❌ Signal invalidated (stock back in zone): {c['symbol']} {c['strike']:g} {c['side']} @ {ltp} · P/L/lot ₹{c['pnl_lot']}")
                    changed = True
                    continue
            if c["kind"] == "GAMMA-UNWIND" and c.get("zone") and not c["hits"] and mins >= 15 * 60 + 25:
                uq = qs.get(c.get("ul_token")) if c.get("ul_token") else None
                u = _f(uq.get("ltp")) if uq else 0
                if u:
                    beyond = u > c["zone"][1] if c["side"] == "CE" else u < c["zone"][0]
                    if beyond:
                        c["zone_broken"] = day
                    elif c.get("zone_broken") and c["zone_broken"] < day:
                        _close(c, "ZONE FAIL EXIT", ltp, str(now))
                        tg(f"GAMMA-UNWIND zone fail exit: {c['symbol']} {c['strike']} {c['side']} @ {ltp}")
                        changed = True
                        continue
        c["pnl_lot"] = round((c["ltp"] - c["entry"]) * c["lot"])
        if live and (c["kind"] in INTRA or c.get("intraday")) and mins >= 15 * 60 + 20 and c["status"] in OPEN:
            _close(c, "EOD EXIT", c["ltp"], str(now))
            if c["kind"].startswith("GU"):
                tg(f"🕒 15:20 exit: {c['symbol']} {c['strike']:g} {c['side']} @ {c['ltp']} · P/L/lot ₹{c['pnl_lot']}")
            changed = True
        if c.get("hold_until") and c["status"] in OPEN and (
                day > c["hold_until"] or (day == c["hold_until"] and mins >= 15 * 60 + 20)):
            _close(c, "TIME EXIT", c["ltp"], str(now))
            if c["kind"].startswith("GU"):
                tg(f"⏱ Time/expiry exit: {c['symbol']} {c['strike']:g} {c['side']} @ {c['ltp']} · P/L/lot ₹{c['pnl_lot']}")
            changed = True

    if changed:
        STORE.dirty = True
    STORE.save(force=changed and live)

    allc = sorted(calls.values(), key=lambda c: (c["date"], c["time"]), reverse=True)

    def stats(rows):
        closed = [c for c in rows if c["status"] not in OPEN]
        wins = [c for c in closed if c["pnl_lot"] > 0]
        return {"calls": len(rows), "closed": len(closed), "wins": len(wins),
                "win_rate": round(len(wins) / len(closed) * 100) if closed else None,
                "t1": sum(any(h.startswith("T1") for h in c["hits"]) for c in rows),
                "net": sum(c["pnl_lot"] for c in rows)}
    summary = {k: stats([c for c in allc if c["kind"] == k]) for k in ("ALL ROUNDER", "POWER-A", "POWER-B", "ELITE", "ELITE HOLD", "JACKPOT", "INTRADAY", "SWING 5D", "SWING 10D", "PATTERN 5D", "GAMMA", "GU-INTRADAY", "GU-HOLDING")}
    summary["ALL"] = stats(allc)
    # Setup type ranking — எந்த setup உண்மையில் வேலை செய்கிறது
    groups = {}
    for c in allc:
        key = "JACKPOT" if c["kind"] == "JACKPOT" else c.get("source") or c["kind"]
        groups.setdefault(key, []).append(c)
    ranking = []
    for k, rows in groups.items():
        st = stats(rows)
        st["source"] = k
        st["avg"] = round(st["net"] / len(rows)) if rows else 0
        st["t1_rate"] = round(st["t1"] / len(rows) * 100) if rows else 0
        ranking.append(st)
    import numpy as _np
    for k, rows in groups.items():
        st_ = next(x for x in ranking if x["source"] == k)
        n_ = len(rows) or 1
        for i in (1, 2, 3):
            st_[f"t{i}_rate"] = round(sum(any(h.startswith(f"T{i} ") for h in c["hits"]) for c in rows) / n_ * 100)
        st_["sl_rate"] = round(sum(c["status"] == "SL HIT" for c in rows) / n_ * 100)
        closed = [c for c in rows if c["status"] not in OPEN and c.get("mfe_pct") is not None]
        if closed:
            st_["mfe_med"] = round(float(_np.median([c["mfe_pct"] for c in closed])), 1)
            st_["expectancy"] = round(sum(c["pnl_lot"] for c in closed) / len(closed))
        st_["closed_mfe"] = len(closed)
    # Calibration: source வாரியாக (Jackpot calls-ம் அதன் source-க்குள் சேரும்)
    calib, edge = {}, {}
    by_src = {}
    for c in allc:
        for src_x in (c.get("sources") or [c.get("source") or c["kind"]]):
            by_src.setdefault(src_x, []).append(c)
    for k, rows in by_src.items():
        # A/B shadow (FILTERED / IMMEDIATE) calls setup-ன் edge-ஐ பாதிக்கக்கூடாது
        closed = [c for c in rows if c["status"] not in OPEN and c.get("mfe_pct") is not None and not c.get("variant")]
        if len(closed) >= 20:
            m = _np.array([c["mfe_pct"] for c in closed])
            q = [max(5.0, round(float(_np.quantile(m, x)), 1)) for x in (0.4, 0.6, 0.8)]
            exp_ = sum(c["pnl_lot"] for c in closed) / len(closed)
            calib[k] = {"n": len(closed), "t_pct": q}
            edge[k] = "POSITIVE" if exp_ > 0 else "NEGATIVE"
        else:
            edge[k] = f"DATA {len(closed)}/20"
    for st_ in ranking:
        src_ = st_["source"] if st_["source"] != "JACKPOT" else "Breakout/Breakdown"
        st_["edge"] = edge.get(src_, "DATA 0/20")
        st_["calib"] = (calib.get(src_) or {}).get("t_pct")
    d["calib"] = calib
    d["edge"] = edge
    ranking.sort(key=lambda x: (-(x["win_rate"] or 0), -x["net"]))
    # இன்றைய best calls (live P/L)
    today_rank = sorted([c for c in allc if c["date"] == day], key=lambda c: -c["pnl_lot"])
    best_ids = [c["id"] for c in today_rank[:3] if c["pnl_lot"] > 0]
    today_all = [c for c in allc if c["date"] == day]
    today = [c for c in today_all if not c.get("shadow")]
    paused_today = [c for c in today_all if c.get("shadow")]
    for c in allc[:400]:
        c["action"], c["guide"] = guide(c, now)
    # Segment வாரியாக: இன்று / நேற்று / இந்த வாரம் / இந்த மாதம் / மொத்தம் + நாள் வாரியாக + சமீபத்திய calls
    dts = sorted({c["date"] for c in allc}, reverse=True)
    yday = next((d_ for d_ in dts if d_ < day), None)
    wk = str((pd.Timestamp(day) - pd.Timedelta(days=pd.Timestamp(day).weekday())).date())
    mo = day[:8] + "01"

    def pstat(rows):
        cl = [c for c in rows if c["status"] not in OPEN]
        return {"calls": len(rows), "wins": sum(c["pnl_lot"] > 0 for c in cl), "closed": len(cl),
                "net": sum(c["pnl_lot"] for c in rows),
                "win_rate": round(sum(c["pnl_lot"] > 0 for c in cl) / len(cl) * 100) if cl else None}
    segments = {}
    for src, rows in by_src.items():
        daily = {}
        for c in rows:
            daily.setdefault(c["date"], []).append(c)
        segments[src] = {
            "periods": {"today": pstat([c for c in rows if c["date"] == day]),
                        "yday": pstat([c for c in rows if c["date"] == yday]) if yday else pstat([]),
                        "week": pstat([c for c in rows if c["date"] >= wk]),
                        "month": pstat([c for c in rows if c["date"] >= mo]), "all": pstat(rows)},
            "all_rows": [{"date": c["date"], "closed": c["status"] not in OPEN, "pnl": c.get("pnl_lot") or 0} for c in rows if not c.get("shadow")],
            "daily": [{"date": d_, **pstat(v)} for d_, v in sorted(daily.items(), reverse=True)[:15]],
            "recent": rows[:30]}
    seg_rank = sorted([{"source": k, **v["periods"]["all"],
                        "avg": round(v["periods"]["all"]["net"] / max(v["periods"]["all"]["calls"], 1))}
                       for k, v in segments.items() if v["periods"]["all"]["closed"] >= 10],
                      key=lambda x: (-(x["win_rate"] or 0) * 0 - x["avg"]))
    try:
        from .v3 import validation as _val
        valid = _val(by_src)
    except Exception:
        valid = []
    def ab_stat(rows):
        cl = [c for c in rows if c["status"] not in OPEN]
        return {"calls": len(rows), "closed": len(cl), "win": round(sum(c["pnl_lot"] > 0 for c in cl) / len(cl) * 100) if cl else None,
                "net": sum(c["pnl_lot"] for c in rows), "avg": round(sum(c["pnl_lot"] for c in cl) / len(cl)) if cl else None}
    v31 = [c for c in allc if c.get("ver") == "V3.1" or c.get("variant")]
    ab = {"Grade A — எல்லா rules ✓": ab_stat([c for c in allc if c.get("grade") == "A" and not c.get("shadow")]),
          "Grade B — சின்ன குறை": ab_stat([c for c in allc if c.get("grade") == "B" and not c.get("shadow")]),
          "Grade C — முக்கிய rule fail": ab_stat([c for c in allc if c.get("grade") == "C" and not c.get("shadow")]),
          "Grade A pullback-க்கு பதில் உடனே entry (shadow)": ab_stat([c for c in v31 if c.get("variant") == "IMMEDIATE"])}
    pend_list = [{"symbol": v["call"]["symbol"], "side": v["call"]["side"], "contract": v["call"]["contract"], "source": v["call"]["source"],
                  "since": str(v["created"])[11:16], "pulled": v["pulled"], "sig_ul": v["sig_ul"]} for v in (d.get("pending") or {}).values()]
    return {"ab": ab, "pending": pend_list, "validation": valid, "rejected_today": list(reversed(SKIPPED["log"])) if SKIPPED["day"] == day else [],
            "paused_today": paused_today, "paused_sources": sorted(k for k, v in (d.get("edge") or {}).items() if v == "NEGATIVE"),
            "skipped_today": SKIPPED["n"] if SKIPPED["day"] == day else 0, "segments": segments, "best_setup": seg_rank[:3], "today": today, "rows": today, "jackpot": [c for c in allc if c["kind"] == "JACKPOT"][:40],
            "jackpot_today": [c for c in today if c["kind"] == "JACKPOT"],
            "swing_open": [c for c in allc if c.get("hold_until") and c["status"] in OPEN],
            "history": allc[:150], "summary": summary, "ranking": ranking, "best_ids": best_ids, "swing_published": flag.get("swing"),
            "store": "GitHub (நிரந்தரம்)" if STORE.remote else "Server disk (restart / deploy-ல் அழியலாம்)",
            "store_error": STORE.error,
            "note": "5-min snapshot LTP அடிப்படையில் — இடையில் தொட்டு திரும்பியதை miss பண்ணலாம். Paper tracking மட்டும்."}



def add_all_rounder(rows, now):
    """🏅 ALL ROUNDER (≥3 modules + TAKE) → paper call, ஒரு stock/side-க்கு ஒரு நாளைக்கு ஒன்று."""
    mins = now.hour * 60 + now.minute
    if not (9 * 60 + 30 <= mins <= 15 * 60) or now.weekday() >= 5:
        return 0
    n = 0
    with CALLS_LOCK:
        d = STORE.load()
        day = str(now.date())
        flag = d["published"].setdefault(day, {})
        for a in rows:
            if not ((a.get("option") or {}).get("plan")) or a.get("count", 0) < 2:
                continue        # V3.2: option plan உள்ள எல்லா All rounder rows-ம் call (TAKE = Grade A, மற்றவை B/C)
            k = f"ar_{a['symbol']}_{a['side']}"
            if flag.get(k):
                continue
            o = a.get("option") or {}
            r = {"symbol": a["symbol"], "price": a.get("price"), "sl": None, "targets": [], "stars": a["stars"],
                 "confidence": f"{a['confidence']}% · {a['count']} modules",
                 "reasons": [f"{m}: {v['note']}" for m, v in a["modules"].items()] + [f"Strike from {a.get('option_from')}"]}
            r["vol_ratio"] = a.get("vol_ratio")
            c = _new("ALL ROUNDER", "All rounder", r, o, now, day)
            if c and c["id"] not in d["calls"]:
                codes = (c.get("force_codes") or []) + quality_gate(c, d["calls"], now)
                hard_ = {"TIME_OPEN_NOISE", "AFTER_2PM", "COUNTER_TREND", "RANGE_DAY", "SL_STREAK", "DAILY_MAX",
                         "RISK_CAP", "T1_UNREALISTIC", "DAILY_LOSS_STOP"}
                c.update(grade="A" if not codes else ("C" if any(x in hard_ for x in codes) else "B"), qcodes=codes,
                         qtext=[QCODE_TXT.get(x, x) for x in codes])
                if a.get("verdict") != "TAKE" and c["grade"] == "A":
                    c["grade"] = "B"
                    c["qtext"].append("All rounder WATCH (TAKE இல்லை)")
                d["calls"][c["id"]] = c
                flag[k] = c["id"]
                STORE.dirty = True
                n += 1
                tg(f"🏅 ALL ROUNDER · {a['count']} modules\n{a['symbol']} {o.get('strike', ''):g} {a['side']}\n"
                   f"Entry ₹{c['entry']} · SL ₹{c['sl']} · " + " · ".join(f"T{i+1} ₹{t}" for i, t in enumerate(c["targets"])) +
                   f"\nConfidence {a['confidence']}% · " + ", ".join(a["modules"].keys()) + "\n(Paper/alert only)", f"ar|{c['id']}")
        if n:
            STORE.save(force=True)
    return n
