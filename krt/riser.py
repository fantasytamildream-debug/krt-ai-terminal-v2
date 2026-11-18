"""🚀 EARLY RISING DETECTOR — spots an open call whose option premium has started climbing fast, BEFORE it reaches T1.

Every 20 s it samples the live premium of every open call (prices are already tracked — no extra API calls).
RISING  = premium +4% or more in the last 3 minutes · at least 2 of the last 3 steps up · still below T1 · not below entry −3%
STRONG  = +8% or more in 3 minutes (momentum burst)
One alert per call; a fresh alert only if it climbs another +8% after the last one. Push + voice + a 🚀 tag on the call.
Honest: a fast rise can reverse — it says "watch / trail the SL", not "guaranteed target".
"""
CFG = {"win_sec": 180, "rise": 4.0, "strong": 8.0, "again": 8.0, "keep_sec": 900, "build": 2.5}
# v124: also watches HIDDEN module calls (marked "hidden") and shows a BUILDING stage (+2.5% in 3 min) so you see it earlier,
#       plus a clear action line for each row (enter / don't chase / trail).
H = {}                    # call id → [(ts, ltp)]
LAST = {}                 # call id → premium at last alert
STATE = {"time": None, "alerts": [], "live": []}
OPEN = ("OPEN", "T1 HIT", "T2 HIT")


def _old(L, now, sec):
    return next((v for t, v in L if (now - t).total_seconds() <= sec), None)


def scan(calls, now, send=None):
    day = str(now.date())
    live, new = [], []
    seen = set()
    for c in calls:
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
        t1 = (c.get("targets") or [None])[0]
        hit = bool(c.get("hits"))
        state = None
        if chg >= CFG["build"] and sum(steps) >= 2 and ltp >= e * 0.97 and not (t1 and ltp >= t1 and not hit):
            state = "STRONG" if chg >= CFG["strong"] else "RISING" if chg >= CFG["rise"] else "BUILDING"
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
               "hidden": bool(c.get("shadow")), "sl": sl}
        live.append(row)
        if state == "BUILDING" or c.get("shadow"):
            continue                              # building / hidden-module rows are shown, but not pushed as alerts
        last = LAST.get(cid)
        if last is None or ltp >= last * (1 + CFG["again"] / 100):
            LAST[cid] = ltp
            STATE["alerts"].insert(0, row)
            new.append(row)
            if send:
                try:
                    send(f"🚀 {'STRONG MOVE' if state == 'STRONG' else 'RISING'} · {row['symbol']} {row['strike']:g} {row['side']}\n"
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
