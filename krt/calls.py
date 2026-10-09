"""எல்லா calls: Jackpot, Intraday, Swing 5D/10D — original levels freeze, தினமும் track, profit/loss history."""
import threading
import pandas as pd
from .store import STORE
from .telegram import send as tg

CALLS_LOCK = threading.Lock()

OPEN = ("OPEN", "T1 HIT", "T2 HIT", "T3 HIT", "T4 HIT")
INTRA = ("JACKPOT", "INTRADAY", "GAMMA")


def _f(x):
    try:
        return float(x)
    except Exception:
        return 0.0


def _new(kind, src, r, opt, now, day, hold=0, session=None):
    p = (opt or {}).get("plan")
    if not p or not opt.get("token"):
        return None
    cid = f"{day}|{kind}|{r['symbol']}|{opt['contract']}"
    c = {"id": cid, "kind": kind, "source": src, "date": day, "time": now.strftime("%H:%M"),
         "symbol": r["symbol"], "side": opt["type"], "contract": opt["contract"], "token": opt["token"],
         "exch": opt["exch"], "strike": opt["strike"], "expiry": opt["expiry"], "lot": opt["lot"],
         "ul_price": r.get("price"), "ul_sl": r.get("sl"), "ul_targets": r.get("targets"),
         "entry": p["entry"], "sl": p["sl"], "targets": p["targets"], "risk": p["risk"], "risk_ok": p["risk_ok"],
         "score": r.get("score"), "stars": r.get("stars"), "confidence": r.get("confidence") or f"{r.get('stars', 0)}★",
         "reasons": r.get("reasons") or ([f"{'+'.join(r['levels'])} break"] if r.get("levels") else []),
         "ltp": p["entry"], "status": "OPEN", "hits": [], "exit": None, "exit_time": None, "pnl_lot": 0}
    if hold:
        c["hold_days"] = hold
        c["hold_until"] = str(pd.bdate_range(session, periods=hold + 1)[-1].date())
    return c


def _close(c, status, price, when):
    c.update(status=status, exit=price, exit_time=when)
    c["pnl_lot"] = round((price - c["entry"]) * c["lot"])


def update_calls(ag, session, now, live, best, orb, voi, idx, swing, add=True, patterns=(), gamma=(), gu=()):
    with CALLS_LOCK:
        return _update_calls(ag, session, now, live, best, orb, voi, idx, swing, add, patterns, gamma, gu)


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


def _update_calls(ag, session, now, live, best, orb, voi, idx, swing, add, patterns, gamma, gu):
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
    if add and live and mins < 15 * 60 + 15:
        # Jackpot: ஒரு நாளுக்கு ஒரு CE + ஒரு PE — 4★+, CONFIRMED, liquid option, risk limit உள்ளே
        for side in ("CE", "PE"):
            if flag.get(f"jackpot_{side}"):
                continue
            c = [r for r in best if r["side"] == side and r.get("stars", 0) >= 4
                 and ((r.get("option") or {}).get("plan") or {}).get("risk_ok")]
            if c:
                cid = add(_new("JACKPOT", "Best setup", c[0], c[0]["option"], now, day))
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
                    if gu_:
                        tg(f"GAMMA-UNWIND T{i} HIT ✅ {c['symbol']} {c['strike']} {c['side']} @ {ltp}" + (" · SL → entry" if i == 1 else ""))
                    changed = True
            if c["status"] == f"T{len(c['targets'])} HIT":
                _close(c, f"T{len(c['targets'])} DONE", ltp, str(now))
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
    summary = {k: stats([c for c in allc if c["kind"] == k]) for k in ("JACKPOT", "INTRADAY", "SWING 5D", "SWING 10D", "PATTERN 5D", "GAMMA", "GU-INTRADAY", "GU-HOLDING")}
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
    ranking.sort(key=lambda x: (-(x["win_rate"] or 0), -x["net"]))
    # இன்றைய best calls (live P/L)
    today_rank = sorted([c for c in allc if c["date"] == day], key=lambda c: -c["pnl_lot"])
    best_ids = [c["id"] for c in today_rank[:3] if c["pnl_lot"] > 0]
    today = [c for c in allc if c["date"] == day]
    return {"today": today, "rows": today, "jackpot": [c for c in allc if c["kind"] == "JACKPOT"][:40],
            "jackpot_today": [c for c in today if c["kind"] == "JACKPOT"],
            "swing_open": [c for c in allc if c.get("hold_until") and c["status"] in OPEN],
            "history": allc[:300], "summary": summary, "ranking": ranking, "best_ids": best_ids, "swing_published": flag.get("swing"),
            "store": "GitHub (நிரந்தரம்)" if STORE.remote else "Server disk (restart / deploy-ல் அழியலாம்)",
            "store_error": STORE.error,
            "note": "5-min snapshot LTP அடிப்படையில் — இடையில் தொட்டு திரும்பியதை miss பண்ணலாம். Paper tracking மட்டும்."}
