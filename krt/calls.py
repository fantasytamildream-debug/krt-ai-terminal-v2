"""எல்லா calls: Jackpot, Intraday, Swing 5D/10D — original levels freeze, தினமும் track, profit/loss history."""
import threading
import pandas as pd
from .store import STORE
from .telegram import send as tg

CALLS_LOCK = threading.Lock()

OPEN = ("OPEN", "T1 HIT", "T2 HIT", "T3 HIT", "T4 HIT")
INTRA = ("JACKPOT", "INTRADAY", "GAMMA", "ELITE", "POWER-A", "POWER-B", "ALL ROUNDER")
SKIPPED = {"day": None, "n": 0, "items": []}


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


def _new(kind, src, r, opt, now, day, hold=0, session=None):
    p = (opt or {}).get("plan")
    if not p or not opt.get("token"):
        return None
    if p.get("risk_ok") is False:      # 1 lot risk budget-ஐ தாண்டினா SKIP — track செய்ய மாட்டோம் (executable signal மட்டும்)
        if SKIPPED["day"] != day:
            SKIPPED.update(day=day, n=0, items=[])
        k = f"{kind}|{r.get('symbol')}|{opt.get('contract')}"
        if k not in SKIPPED["items"]:
            SKIPPED["items"].append(k)
            SKIPPED["n"] += 1
        return None
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
    c = {"id": cid, "kind": kind, "source": src, "date": day, "time": now.strftime("%H:%M"),
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
        return "BOOK", f"T2 ✅ — பெரும்பகுதி book பண்ணுங்க, மீதியை trail பண்ணுங்க{nxt}"
    if any(h.startswith("T1 ") for h in c["hits"]):
        return "BOOK", f"T1 ✅ — பாதி book பண்ணுங்க, SL-ஐ entry ₹{e}-க்கு மாத்துங்க"
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
        if c and c["kind"] in INTRA and any(x["date"] == c["date"] and x["contract"] == c["contract"]
                                            and x["kind"] in INTRA for x in calls.values()):
            return None  # ஒரே trade இரண்டு முறை count ஆகக்கூடாது
        if c and c["id"] not in calls:
            calls[c["id"]] = c
            changed = True
            return c["id"]

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
    if add and live and mins >= 15 * 60 and not flag.get("swing"):
        for key in ("10", "5"):
            for r in swing.get(key, []):
                add(_new(f"SWING {key}D", "Swing", r, r.get("option"), now, day, int(key), session))
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
    for c in open_:
        toks.setdefault(c["exch"], []).append(c["token"])
        if c.get("ul_token"):
            toks.setdefault("NSE", []).append(c["ul_token"])
    qs = ag.quotes(toks) if (toks and live) else {}
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
                           ("👉 பாதி book பண்ணுங்க, SL → entry" if i == 1 else "👉 பெரும்பகுதி book பண்ணுங்க, மீதியை trail"), f"t{i}|{c['id']}")
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
        by_src.setdefault(c.get("source") or c["kind"], []).append(c)
    for k, rows in by_src.items():
        closed = [c for c in rows if c["status"] not in OPEN and c.get("mfe_pct") is not None]
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
    today = [c for c in allc if c["date"] == day]
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
            "daily": [{"date": d_, **pstat(v)} for d_, v in sorted(daily.items(), reverse=True)[:15]],
            "recent": rows[:30]}
    seg_rank = sorted([{"source": k, **v["periods"]["all"],
                        "avg": round(v["periods"]["all"]["net"] / max(v["periods"]["all"]["calls"], 1))}
                       for k, v in segments.items() if v["periods"]["all"]["closed"] >= 10],
                      key=lambda x: (-(x["win_rate"] or 0) * 0 - x["avg"]))
    return {"skipped_today": SKIPPED["n"] if SKIPPED["day"] == day else 0, "segments": segments, "best_setup": seg_rank[:3], "today": today, "rows": today, "jackpot": [c for c in allc if c["kind"] == "JACKPOT"][:40],
            "jackpot_today": [c for c in today if c["kind"] == "JACKPOT"],
            "swing_open": [c for c in allc if c.get("hold_until") and c["status"] in OPEN],
            "history": allc[:150], "summary": summary, "ranking": ranking, "best_ids": best_ids, "swing_published": flag.get("swing"),
            "store": "GitHub (நிரந்தரம்)" if STORE.remote else "Server disk (restart / deploy-ல் அழியலாம்)",
            "store_error": STORE.error,
            "note": "5-min snapshot LTP அடிப்படையில் — இடையில் தொட்டு திரும்பியதை miss பண்ணலாம். Paper tracking மட்டும்."}



def add_all_rounder(rows, now):
    """🏅 ALL ROUNDER (≥3 modules + TAKE) → paper call, ஒரு stock/side-க்கு ஒரு நாளைக்கு ஒன்று."""
    mins = now.hour * 60 + now.minute
    if not (9 * 60 + 45 <= mins <= 14 * 60 + 30) or now.weekday() >= 5:
        return 0
    n = 0
    with CALLS_LOCK:
        d = STORE.load()
        day = str(now.date())
        flag = d["published"].setdefault(day, {})
        for a in rows:
            if a.get("verdict") != "TAKE":
                continue
            k = f"ar_{a['symbol']}_{a['side']}"
            if flag.get(k):
                continue
            o = a.get("option") or {}
            r = {"symbol": a["symbol"], "price": a.get("price"), "sl": None, "targets": [], "stars": a["stars"],
                 "confidence": f"{a['confidence']}% · {a['count']} modules",
                 "reasons": [f"{m}: {v['note']}" for m, v in a["modules"].items()] + [f"Strike from {a.get('option_from')}"]}
            c = _new("ALL ROUNDER", "All rounder", r, o, now, day)
            if c and c["id"] not in d["calls"]:
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
