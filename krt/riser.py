"""🚀 EARLY RISING DETECTOR — spots an open call whose option premium has started climbing fast, BEFORE it reaches T1.

Every 20 s it samples the live premium of every open call (prices are already tracked — no extra API calls).
RISING  = premium +4% or more in the last 3 minutes · at least 2 of the last 3 steps up · still below T1 · not below entry −3%
STRONG  = +8% or more in 3 minutes (momentum burst)
One alert per call; a fresh alert only if it climbs another +8% after the last one. Push + voice + a 🚀 tag on the call.
Honest: a fast rise can reverse — it says "watch / trail the SL", not "guaranteed target".
"""
CFG = {"win_sec": 180, "rise": 4.0, "strong": 8.0, "again": 8.0, "keep_sec": 900, "build": 2.5, "burst_sec": 60, "burst": 3.0}
# v155: alerts survive a restart (saved with the calls), a 1-minute BURST (+3 % in 60 s) is caught, and besides open calls it also
#       watches World Top setups + big-player strikes (pseudo-calls with id "W|token", entry = first premium seen today).
# v124: also watches HIDDEN module calls (marked "hidden") and shows a BUILDING stage (+2.5% in 3 min) so you see it earlier,
#       plus a clear action line for each row (enter / don't chase / trail).
H = {}                    # call id → [(ts, ltp)]
LAST = {}                 # call id → premium at last alert
STATE = {"time": None, "alerts": [], "live": [], "day": None}


def restore(saved, day):
    """bring back today's alerts after a restart (saved = store["riser"])."""
    if STATE.get("day") == day or not saved or saved.get("day") != day:
        STATE["day"] = day if STATE.get("day") != day else STATE["day"]
        return
    STATE["alerts"] = list(saved.get("alerts") or [])[:50]
    LAST.update({k: v for k, v in (saved.get("last") or {}).items()})
    STATE["day"] = day


def snapshot():
    return {"day": STATE.get("day"), "alerts": STATE["alerts"][:50], "last": dict(LAST)}
OPEN = ("OPEN", "T1 HIT", "T2 HIT")


def _old(L, now, sec):
    return next((v for t, v in L if (now - t).total_seconds() <= sec), None)


def scan(calls, now, send=None, extra=None):
    day = str(now.date())
    if STATE.get("day") != day:
        STATE.update(day=day, alerts=[], live=[])
        LAST.clear()
    live, new = [], []
    seen = set()
    for c in list(calls) + list(extra or []):
        if c.get("date") != day or c.get("status") not in OPEN or c.get("kind") == "PICK" or "|IMM" in str(c.get("id")):
            continue
        if c.get("shadow") and ("already called today" in str(c.get("shadow_why") or "") or c.get("shadow_code") == "Q_DUP_ANY"):
            continue
        ltp, e = float(c.get("ltp") or 0), float(c.get("entry") or 0)
        if not (ltp and e):
            continue
        cid = c["id"]
        seen.add(cid)
        L = H.setdefault(cid, [])
        if not L or L[-1][1] != ltp or (now - L[-1][0]).total_seconds() >= 20:
            L.append((now, ltp))
        while L and (now - L[0][0]).total_seconds() > CFG["keep_sec"]:
            L.pop(0)
        base = _old(L, now, CFG["win_sec"])
        if not base or len(L) < 3:
            continue
        chg = (ltp / base - 1) * 100
        steps = [L[i][1] > L[i - 1][1] for i in range(max(1, len(L) - 3), len(L))]
        b1 = _old(L, now, CFG["burst_sec"])
        burst = bool(b1 and (ltp / b1 - 1) * 100 >= CFG["burst"] and L[-1][1] > L[-2][1])
        t1 = (c.get("targets") or [None])[0]
        hit = bool(c.get("hits"))
        state = None
        if chg >= CFG["build"] and sum(steps) >= 2 and ltp >= e * 0.97 and not (t1 and ltp >= t1 and not hit):
            state = "STRONG" if chg >= CFG["strong"] else "RISING" if chg >= CFG["rise"] else "BUILDING"
        if burst and state in (None, "BUILDING") and ltp >= e * 0.97 and not (t1 and ltp >= t1 and not hit):
            state = "RISING"                  # v155: +3 % inside one minute = buyers rushing in
        if not state:
            continue
        fe = (ltp / e - 1) * 100
        sl = float(c.get("sl") or 0)
        if hit:
            act = f"T1 done — hold half, SL at entry ₹{e:g}."
        elif fe > 15:
            act = f"Already +{fe:.0f}% from entry — don't chase. In the trade? trail SL to ₹{round(max(e, ltp * 0.9), 2):g}."
        elif fe <= 5:
            act = f"Still near entry (₹{e:g}) — can enter up to ₹{round(e * 1.05, 2):g}, SL ₹{sl:g}."
        else:
            act = f"Up {fe:.0f}% — only enter on a dip to ≈₹{round(e * 1.03, 2):g}; in the trade? move SL to ₹{e:g}."
        row = {"id": cid, "symbol": c["symbol"], "strike": c.get("strike"), "side": c.get("side"), "ltp": ltp, "entry": e, "chg3m": round(chg, 1),
               "from_entry": round((ltp / e - 1) * 100, 1), "t1": t1, "to_t1": round((t1 / ltp - 1) * 100, 1) if t1 else None, "state": state,
               "time": now.strftime("%H:%M:%S"), "source": c.get("source_label") or c.get("source"), "act": act,
               "hidden": bool(c.get("shadow")), "sl": sl, "burst": burst, "watch": str(cid).startswith("W|"),
               "token": c.get("token"), "exch": c.get("exch"), "expiry": c.get("expiry"), "lot": c.get("lot"), "contract": c.get("contract"),
               "lots3m": c.get("lots3m")}
        live.append(row)
        if state == "BUILDING":
            continue                              # building rows are shown, not pushed
        # v136: hidden-module calls ALSO alert now (most module calls are hidden by the quality gate → riser stayed silent)
        last = LAST.get(cid)
        if last is None or ltp >= last * (1 + CFG["again"] / 100):
            LAST[cid] = ltp
            STATE["alerts"].insert(0, row)
            new.append(row)
            if send:
                try:
                    send(f"🚀 {'STRONG MOVE' if state == 'STRONG' else 'RISING'} · {row['symbol']} {row['strike']:g} {row['side']}{' (hidden module call)' if row['hidden'] else ''}\n"
                         f"Premium ₹{ltp:g} · +{row['chg3m']}% in 3 min · {row['from_entry']:+}% from entry ₹{e:g}"
                         + (f" · T1 ₹{t1:g} ({row['to_t1']:+}%)" if t1 else "") + "\n👉 Watch it — in the trade? move SL up. Not in? only enter on a small pullback.",
                         f"rise|{cid}|{round(ltp)}", True)
                except Exception:
                    pass
    for k in [k for k in H if k not in seen]:
        H.pop(k, None)
    del STATE["alerts"][50:]
    STATE.update(time=now.strftime("%I:%M:%S %p"), live=sorted(live, key=lambda r: -r["chg3m"]))
    return new


def report(day):
    return {"time": STATE["time"], "live": STATE["live"], "alerts": [a for a in STATE["alerts"]][:30]}
