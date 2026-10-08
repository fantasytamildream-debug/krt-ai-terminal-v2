"""💥 Gamma Blast — expiry நாளில் மட்டும் (zero-to-hero முயற்சி). மிக அதிக RISK.
Rules (index): expiry இன்று + 1:00 PM பிறகு + spot day high/low அருகில் + (OI wall உடைப்பு அல்லது ATM writers unwinding).
Strike: ATM அல்லது 1 OTM மட்டும் (far-OTM lottery இல்லை), premium range-க்குள். SL = premium 50%. Targets 2× / 3× / 5×.
பெரும்பாலான expiry options zero ஆகும் — இழக்கக் கூடிய பணம் மட்டும், 1 lot."""
import datetime as dt
from .optmath import r05

IDX_PREM = (5, 90)      # index option premium range
STK_PREM = (2, 40)


def _plan(o, lot, cap=2500, charges=100):
    e = r05(o.get("ask") or o.get("ltp") or 0)
    if not e:
        return None
    sl = r05(e * 0.5)
    risk = round((e - sl) * lot + charges)
    return {"entry": e, "entry_zone": [r05(e * 0.97), r05(e * 1.03)], "sl": sl,
            "targets": [r05(e * 2), r05(e * 3), r05(e * 5)], "risk": risk, "risk_ok": risk <= cap,
            "iv": None, "estimated": False}


def _status(side, spot, hi, lo, flags, mins):
    rng = max(hi - lo, spot * 0.002)
    pos = (spot - lo) / rng
    near = pos >= 0.85 if side == "CE" else pos <= 0.15
    oi_ok = flags.get(f"{side}_oi")
    if mins < 12 * 60 + 30:
        return "WAIT", pos
    if mins >= 15 * 60 + 15:
        return "CLOSED", pos
    if mins >= 13 * 60 and near and oi_ok:
        return "TRIGGERED", pos
    if near or oi_ok:
        return "WATCH", pos
    return "WAIT", pos


def index_gamma(idx_rows, now, cap=2500):
    today, mins = now.date().isoformat(), now.hour * 60 + now.minute
    out, cal = [], []
    for x in idx_rows:
        if x.get("error"):
            continue
        cal.append({"name": x["index"], "expiry": x["expiry"], "today": x["expiry"] == today})
        if x["expiry"] != today:
            continue
        chain = {r["strike"]: r for r in x.get("chain") or []}
        strikes = sorted(chain)
        if not strikes:
            continue
        atm = x["atm"]
        i = strikes.index(atm)
        spot, hi, lo = x["spot"], x.get("day_high") or x["spot"], x.get("day_low") or x["spot"]
        a = chain[atm]
        flags = {"CE_oi": spot > x["resistance"] or a.get("CE", {}).get("chg", 0) < 0,
                 "PE_oi": spot < x["support"] or a.get("PE", {}).get("chg", 0) < 0}
        for side in ("CE", "PE"):
            otm = strikes[i + 1] if side == "CE" and i + 1 < len(strikes) else (strikes[i - 1] if side == "PE" and i > 0 else None)
            pick = None
            for k in (atm, otm):
                o = (chain.get(k) or {}).get(side)
                if o and IDX_PREM[0] <= (o.get("ltp") or 0) <= IDX_PREM[1]:
                    pick = (k, o)
                    break
            st, pos = _status(side, spot, hi, lo, flags, mins)
            reasons = [f"Expiry இன்று ({x['expiry']})",
                       f"Day range-ல் இடம் {pos*100:.0f}% ({'high' if side=='CE' else 'low'} அருகில் வேண்டும்)",
                       ("Resistance " if side == "CE" else "Support ") + f"{x['resistance'] if side=='CE' else x['support']:g} " +
                       ("உடைந்தது" if (spot > x['resistance'] if side == 'CE' else spot < x['support']) else "இன்னும் உடையவில்லை"),
                       f"ATM {side} OI மாற்றம் {a.get(side, {}).get('chg', 0):+,}"]
            item = {"name": x["index"], "side": side, "spot": spot, "day_high": hi, "day_low": lo,
                    "status": st, "flags": flags, "expiry": x["expiry"], "reasons": reasons,
                    "trigger": hi if side == "CE" else lo}
            if pick:
                k, o = pick
                opt = {"token": o.get("token"), "exch": o.get("exch"), "contract": o.get("contract"), "strike": k,
                       "type": side, "expiry": x["expiry"], "lot": o.get("lot"), "bid": o.get("bid"),
                       "ask": o.get("ask"), "ltp": o.get("ltp"), "moneyness": "ATM" if k == atm else "1 OTM"}
                opt["plan"] = _plan(opt, opt["lot"] or 0, cap)
                item["option"] = opt
            else:
                item["option"] = {"none": f"Premium {IDX_PREM[0]}–{IDX_PREM[1]} range-ல் ATM / 1 OTM இல்லை"}
            out.append(item)
    return out, cal


def stock_gamma(ag, inst, universe, now, contracts, cap=2500):
    """Stock monthly expiry நாளில்: volume ≥2× + day high/low அருகில் உள்ள stocks."""
    today, mins = now.date().isoformat(), now.hour * 60 + now.minute
    picks = []
    for u in sorted(universe, key=lambda u: -u["vol_ratio"]):
        if len(picks) >= 6:
            break
        exp, cs = contracts(inst, u["symbol"], 0)
        if exp != today or u["vol_ratio"] < 2 or not u.get("high"):
            continue
        rng = max(u["high"] - u["low"], u["ltp"] * 0.003)
        pos = (u["ltp"] - u["low"]) / rng
        side = "CE" if pos >= 0.85 and u["pct"] > 0 else "PE" if pos <= 0.15 and u["pct"] < 0 else None
        if not side:
            continue
        strikes = sorted({c[3] for c in cs if c[4] == side})
        if not strikes:
            continue
        atm = min(strikes, key=lambda s: abs(s - u["ltp"]))
        j = strikes.index(atm)
        otm = strikes[j + 1] if side == "CE" and j + 1 < len(strikes) else strikes[j - 1] if side == "PE" and j > 0 else None
        picks.append((u, side, pos, [c for c in cs if c[4] == side and c[3] in (atm, otm)], atm))
    toks = {}
    for _, _, _, cc, _ in picks:
        for c in cc:
            toks.setdefault(c[6], []).append(c[0])
    qs = ag.quotes(toks) if toks else {}
    out = []
    for u, side, pos, cc, atm in picks:
        best = None
        for c in sorted(cc, key=lambda c: c[3] != atm):
            q = qs.get(c[0]) or {}
            ltp = float(q.get("ltp") or 0)
            if STK_PREM[0] <= ltp <= STK_PREM[1]:
                d = q.get("depth") or {}
                b = float(((d.get("buy") or [{}])[0] or {}).get("price") or 0)
                a = float(((d.get("sell") or [{}])[0] or {}).get("price") or 0)
                best = {"token": c[0], "exch": c[6], "contract": c[1], "strike": c[3], "type": side, "expiry": c[2],
                        "lot": c[5], "bid": b, "ask": a or ltp, "ltp": ltp, "moneyness": "ATM" if c[3] == atm else "1 OTM"}
                break
        st = "TRIGGERED" if mins >= 13 * 60 and mins < 15 * 60 + 15 else "WATCH"
        item = {"name": u["symbol"], "side": side, "spot": u["ltp"], "day_high": u["high"], "day_low": u["low"],
                "status": st, "expiry": today, "vol_ratio": u["vol_ratio"],
                "reasons": [f"Monthly expiry இன்று", f"Volume {u['vol_ratio']}×", f"Day range-ல் இடம் {pos*100:.0f}%"],
                "trigger": u["high"] if side == "CE" else u["low"]}
        if best:
            best["plan"] = _plan(best, best["lot"], cap)
            item["option"] = best
        else:
            item["option"] = {"none": "Premium range-ல் liquid ATM / 1 OTM இல்லை"}
        out.append(item)
    return out


def retick(items, spot_q, opt_q, now):
    """30-sec tick: spot / option LTP / status update."""
    mins = now.hour * 60 + now.minute
    for it in items:
        q = spot_q.get(it["name"])
        if q:
            it["spot"] = q["ltp"]
            it["day_high"] = max(it["day_high"], q.get("high") or q["ltp"])
            it["day_low"] = min(it["day_low"], q.get("low") or q["ltp"])
        if it.get("flags") is not None:
            prev = it["status"]
            it["status"], _ = _status(it["side"], it["spot"], it["day_high"], it["day_low"], it["flags"], mins)
            if it["status"] == "TRIGGERED" and prev != "TRIGGERED":
                it["triggered_at"] = now.strftime("%H:%M")
        o = it.get("option") or {}
        oq = opt_q.get(o.get("token"))
        if oq:
            o["ltp"] = float(oq.get("ltp") or 0)
    return items
