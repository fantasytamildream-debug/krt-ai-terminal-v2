"""KRT AI TERMINAL V3.0 — SCAN > VALIDATE > RANK > MANAGE RISK > TRACK > IMPROVE.
1) Gamma Blast V3: index option chain-ல் இருந்து gamma exposure (GEX). Gross concentration + scenario signed GEX தனித்தனி.
   Dealer positioning OI-ல் இருந்து தெரியாது — signed GEX ஒரு அனுமான (scenario) மட்டும்.
2) Smart Rank: எல்லா modules signals → ஒரே ranked watchlist, dedupe, காரணம், disqualifier, freshness,
   history (forward paper, இன்றைக்கு முந்தைய closed calls) calibration.
3) Validation: setup வாரியாக win rate, expectancy, profit factor, max drawdown, avg R, false signal rate, regime வாரியாக.
எதுவும் accuracy / profit guarantee இல்லை."""
import math
import pandas as pd
from .optmath import iv, years_to_expiry

VERSION = "V3.0"
GEX_PREV = {"day": None, "first": {}, "last": {}}


def _gamma(S, K, T, sig):
    if S <= 0 or K <= 0 or T <= 0 or sig <= 0:
        return 0.0
    d1 = (math.log(S / K) + 0.5 * sig * sig * T) / (sig * math.sqrt(T))
    return math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) / (S * sig * math.sqrt(T))


def gex_index(x, now, candles=None):
    """x = index_oi() row (chain-உடன்). OI = Angel units (shares) → contract multiplier ஏற்கனவே உள்ளே.
    GEX(₹ per 1% move) = Γ × OI × S² × 0.01."""
    S, chain = x.get("spot"), x.get("chain") or []
    if not S or not chain or not x.get("expiry"):
        return {"index": x.get("index"), "status": "UNVERIFIED", "why": "Option chain / spot இல்லை"}
    T = max(years_to_expiry(x["expiry"], now.to_pydatetime() if hasattr(now, "to_pydatetime") else now), 1 / (365 * 24))
    legs, missing, total = [], 0, 0
    for r in chain:
        K = r["strike"]
        for typ in ("CE", "PE"):
            o = r.get(typ)
            if not o:
                continue
            total += 1
            px = (o["bid"] + o["ask"]) / 2 if o.get("bid") and o.get("ask") else o.get("ltp")
            sig = None
            if px and px > 0.05:
                try:
                    sig = iv(px, S, K, T, typ)
                except Exception:
                    sig = None
            if not sig or sig < 0.02 or sig > 3:
                missing += 1
                continue
            legs.append((K, typ, o.get("oi") or 0, sig))
    if total == 0 or len(legs) < 8:
        return {"index": x["index"], "status": "UNVERIFIED", "why": "IV கணக்கிட போதுமான contracts இல்லை"}

    def at(spot):
        per = {}
        for K, typ, oi, sig in legs:
            g = _gamma(spot, K, T, sig) * oi * spot * spot * 0.01
            d = per.setdefault(K, {"CE": 0.0, "PE": 0.0})
            d[typ] += g
        return per
    per = at(S)
    gross = sum(v["CE"] + v["PE"] for v in per.values())
    signed = sum(v["CE"] - v["PE"] for v in per.values())          # scenario: calls +, puts −
    call_wall = max(per, key=lambda k: per[k]["CE"])
    put_wall = max(per, key=lambda k: per[k]["PE"])
    clusters = sorted(per, key=lambda k: -(per[k]["CE"] + per[k]["PE"]))[:3]
    # estimated gamma flip: spot grid-ல் signed GEX sign மாறும் இடம்
    flip, prev_s, prev_v = None, None, None
    for i in range(-30, 31):
        sp = S * (1 + i * 0.001)
        v = sum(a["CE"] - a["PE"] for a in at(sp).values())
        if prev_v is not None and (v > 0) != (prev_v > 0):
            cand = (prev_s + sp) / 2
            if flip is None or abs(cand - S) < abs(flip - S):
                flip = cand
        prev_s, prev_v = sp, v
    out = {"index": x["index"], "spot": S, "expiry": x["expiry"], "status": "ESTIMATED" if missing / max(total, 1) <= 0.3 else "UNVERIFIED",
           "missing_iv_pct": round(missing / max(total, 1) * 100), "gross_cr": round(gross / 1e7, 2), "signed_cr": round(signed / 1e7, 2),
           "call_wall": call_wall, "put_wall": put_wall, "clusters": clusters, "flip": round(flip, 2) if flip else None,
           "zone": ("POSITIVE (scenario) — pinning / mean-revert வாய்ப்பு" if (flip and S > flip) or (not flip and signed > 0)
                    else "NEGATIVE (scenario) — move நீளும் வாய்ப்பு"),
           "per_strike": [{"strike": k, "ce_cr": round(per[k]["CE"] / 1e7, 2), "pe_cr": round(per[k]["PE"] / 1e7, 2)} for k in sorted(per)]}
    # snapshot மாற்றம்
    day = str(pd.Timestamp(now).date())
    if GEX_PREV["day"] != day:
        GEX_PREV.update(day=day, first={}, last={})
    f0 = GEX_PREV["first"].setdefault(x["index"], {"call_wall": call_wall, "put_wall": put_wall, "gross": gross, "t": pd.Timestamp(now).strftime("%H:%M")})
    l0 = GEX_PREV["last"].get(x["index"])
    out["change"] = {"since": f0["t"], "gross_chg_pct": round((gross / f0["gross"] - 1) * 100, 1) if f0["gross"] else None,
                     "call_wall_from": f0["call_wall"], "put_wall_from": f0["put_wall"],
                     "moved": (l0 and (l0["call_wall"] != call_wall or l0["put_wall"] != put_wall))}
    GEX_PREV["last"][x["index"]] = {"call_wall": call_wall, "put_wall": put_wall}
    # direction confirmation — completed 5-min candles (repaint இல்லை)
    sig_ = []
    if candles is not None and not candles.empty:
        df = candles[candles.index + pd.Timedelta(minutes=5) <= pd.Timestamp(now)]
        df = df[df.index.normalize() == pd.Timestamp(now).normalize()]
        if len(df) >= 4:
            c, h, l = df["close"].values, df["high"].values, df["low"].values
            twap = float(df["close"].mean())
            mom_up, mom_dn = c[-1] > max(c[-4:-1]), c[-1] < min(c[-4:-1])
            out["confirm"] = {"last_5m": round(float(c[-1]), 2), "bar": str(df.index[-1])[11:16], "twap": round(twap, 2),
                              "above_twap": bool(c[-1] > twap), "mom": "UP" if mom_up else "DOWN" if mom_dn else "FLAT"}
            if c[-1] > call_wall:
                sig_.append({"type": "GAMMA BREAKOUT", "side": "CE", "why": f"5-min close {c[-1]:.0f} > call wall {call_wall:g}"})
            if c[-1] < put_wall:
                sig_.append({"type": "GAMMA BREAKDOWN", "side": "PE", "why": f"5-min close {c[-1]:.0f} < put wall {put_wall:g}"})
            if h[-1] >= call_wall > c[-1]:
                sig_.append({"type": "CALL WALL REJECTION", "side": "PE", "why": f"High {h[-1]:.0f} call wall தொட்டு கீழே close"})
            if l[-1] <= put_wall < c[-1]:
                sig_.append({"type": "PUT WALL REJECTION", "side": "CE", "why": f"Low {l[-1]:.0f} put wall தொட்டு மேலே close"})
            neg = flip and S < flip
            if 0 < (call_wall - S) / S <= 0.004 and mom_up and c[-1] > twap:
                sig_.append({"type": "GAMMA SQUEEZE WATCH", "side": "CE", "why": f"Call wall {call_wall:g} அருகில் + momentum UP" + (" + negative gamma zone" if neg else "")})
            if 0 < (S - put_wall) / S <= 0.004 and mom_dn and c[-1] < twap:
                sig_.append({"type": "GAMMA SQUEEZE WATCH", "side": "PE", "why": f"Put wall {put_wall:g} அருகில் + momentum DOWN" + (" + negative gamma zone" if neg else "")})
    else:
        out["confirm"] = None
    out["signals"] = sig_ if out["status"] == "ESTIMATED" else []
    out["note"] = "VWAP: index-க்கு volume இல்லை → TWAP proxy. Signed GEX = scenario அனுமானம் (dealer நிலை தெரியாது)."
    return out


# ---------------- Smart Rank
MOD2SRC = {"POWER OI": ["POWER OI"], "Elite": ["Elite intraday", "Elite holding"], "Breakout/Breakdown": ["Breakout/Breakdown"],
           "5-min ORB": ["5-min ORB"], "Volume+OI": ["Volume+OI"], "Chart pattern": ["Chart pattern"], "Swing": ["Swing"],
           "Gamma unwind": ["Gamma unwind V3"], "OI Footprint": ["OI Footprint"], "Index OI": ["Index OI"], "Best setup": ["Breakout/Breakdown"]}


def _hist(segments, mod, today):
    """இன்றைக்கு முந்தைய closed calls மட்டும் (out-of-sample for today's signals)."""
    rows = []
    for s in MOD2SRC.get(mod, [mod]):
        rows += [c for c in ((segments.get(s) or {}).get("all_rows") or []) if c["date"] < today]
    closed = [c for c in rows if c.get("closed")]
    if len(closed) < 20:
        return None, f"DATA {len(closed)}/20"
    avg = sum(c["pnl"] for c in closed) / len(closed)
    return max(-1.0, min(1.0, avg / 1500)), f"avg ₹{avg:,.0f}/call · {len(closed)} closed"


def early_alert(tier, p, L, vr):
    """🟠 ஏறுறதுக்கு முன் (rule-based): disqualify இல்லை · option LTP இன்னும் entry-க்கு ±2%-க்குள் · T1 / SL தொடல ·
    volume ≥2× அல்லது 🟣 entry-now அல்லது 🟢 light. → None / காரணம்."""
    if tier == "REJECTED" or not p or not p.get("entry"):
        return None
    ltp = L.get("ltp")
    if not ltp or L.get("sl_hit") or any(L.get("t_hits") or []):
        return None
    e = p["entry"]
    if not (e * 0.98 <= ltp <= e * 1.02):
        return None
    why = []
    if (vr or 0) >= 2:
        why.append(f"volume {vr}×")
    if L.get("entry_now"):
        why.append("🟣 entry-now")
    if L.get("light") == "green":
        why.append("🟢 light")
    return " + ".join(why) if why else None


def smart_rank(res, segments, today, regime_side=None):
    ar = res.get("all_rounder") or []
    lv = {(r["symbol"], r["side"]): r for r in (res.get("ce") or []) + (res.get("pe") or [])}
    out = []
    for a in ar:
        L = a.get("live") or {}
        o = a.get("option") or {}
        p = o.get("plan") or {}
        mods = list((a.get("modules") or {}).keys())
        comps, hs = [], []
        for m in mods:
            h, txt = _hist(segments, m, today)
            comps.append({"module": m, "note": (a["modules"][m] or {}).get("note", "") if isinstance(a["modules"][m], dict) else "", "hist": txt})
            if h is not None:
                hs.append(h)
        hist = sum(hs) / len(hs) if hs else 0.0
        dq, warn = [], []
        if not p:
            dq.append("NO_OPTION — underlying setup மட்டும்")
        else:
            if p.get("risk_ok") is False:
                dq.append("RISK_CAP — 1 lot risk ₹2,500-க்கு மேல்")
            if p.get("reward_ok") is False:
                dq.append("T1_UNREALISTIC")
            if (o.get("spread_pct") or 0) > 3:
                dq.append(f"WIDE_SPREAD {o.get('spread_pct')}%")
        vr = a.get("vol_ratio")
        if vr is not None and vr < 1.2:
            dq.append(f"LOW_VOLUME {vr}×")
        if L.get("sl_hit"):
            dq.append("SL_TOUCHED")
        if regime_side and regime_side != a["side"]:
            warn.append("COUNTER_TREND (market direction எதிர்)")
        br = lv.get((a["symbol"], a["side"]))
        if br and a.get("price"):
            levels = [x.get("level") for x in (br.get("levels") or []) if isinstance(x, dict) and x.get("level")]
            lvl = br.get("level") or (levels[0] if levels else None)
            if lvl and ((a["side"] == "CE" and a["price"] < lvl) or (a["side"] == "PE" and a["price"] > lvl)):
                dq.append(f"FAILED_BREAKOUT — price level {lvl}-க்கு உள்ளே திரும்பியது")
        if L.get("t1_state") == "HIT":
            warn.append("T1 ஏற்கனவே hit — late entry")
        fresh = 100 if L.get("ltp") else 40
        vol_s = min((vr or 0) / 3, 1) * 100
        rank = 0.4 * a.get("confidence", 0) + 0.3 * (hist + 1) / 2 * 100 + 0.2 * vol_s + 0.1 * fresh - 15 * len(warn)
        if dq:
            rank -= 40
        tier = "A" if rank >= 70 and not dq else "B" if rank >= 55 and not dq else "WATCH" if not dq else "REJECTED"
        out.append({"symbol": a["symbol"], "side": a["side"], "strike": o.get("strike"), "expiry": o.get("expiry"),
                    "rank": round(rank, 1), "tier": tier, "confidence": a.get("confidence"), "hist": round(hist, 2),
                    "components": comps, "disq": dq, "warn": warn, "ltp": L.get("ltp"), "entry": p.get("entry"), "sl": p.get("sl"),
                    "targets": p.get("targets"), "risk": p.get("risk"), "light": L.get("light"), "entry_now": L.get("entry_now"),
                    "vol_ratio": vr, "t_hits": L.get("t_hits"), "fresh": "LIVE" if L.get("ltp") else "STALE",
                    "contract": o.get("contract"), "token": o.get("token"), "exch": o.get("exch") or "NFO", "lot": o.get("lot"),
                    "early": early_alert(tier, p, L, vr), "src_modules": mods})
    for g in res.get("gex") or []:
        for sg in g.get("signals") or []:
            out.append({"symbol": g["index"], "side": sg["side"], "strike": None, "expiry": g.get("expiry"), "rank": 50.0,
                        "tier": "WATCH", "confidence": None, "hist": 0, "components": [{"module": "Gamma V3", "note": sg["type"], "hist": sg["why"]}],
                        "disq": [], "warn": ["Index gamma signal — strike Index OI tab-ல் பாருங்க"], "ltp": g.get("spot"),
                        "entry": None, "sl": None, "targets": None, "risk": None, "light": None, "entry_now": False,
                        "vol_ratio": None, "t_hits": None, "fresh": "LIVE"})
    out.sort(key=lambda r: (0 if r.get("early") and r["tier"] in ("A", "B") else 1, -r["rank"]))
    return out


# ---------------- Validation (forward paper test)
def validation(by_src):
    rows = []
    for src, cs in by_src.items():
        closed = sorted([c for c in cs if c.get("status") not in ("OPEN", "T1 HIT", "T2 HIT") and not c.get("shadow")],
                        key=lambda c: (c["date"], c["time"]))
        if not closed:
            continue
        pnl = [c.get("pnl_lot") or 0 for c in closed]
        wins, losses = [x for x in pnl if x > 0], [x for x in pnl if x < 0]
        eq, peak, mdd = 0, 0, 0
        for x in pnl:
            eq += x
            peak = max(peak, eq)
            mdd = min(mdd, eq - peak)
        rs = [(c.get("pnl_lot") or 0) / c["risk"] for c in closed if c.get("risk")]
        false_ = sum(1 for c in closed if c["status"] in ("SL HIT", "INVALIDATED") and not any(h.startswith("T1 ") for h in c.get("hits") or []))
        reg = {}
        for c in closed:
            k = c.get("regime") or "–"
            r_ = reg.setdefault(k, [0, 0])
            r_[0] += 1
            r_[1] += (c.get("pnl_lot") or 0) > 0
        rows.append({"source": src, "n": len(closed), "win": round(len(wins) / len(closed) * 100),
                     "expectancy": round(sum(pnl) / len(closed)), "pf": round(sum(wins) / abs(sum(losses)), 2) if losses else None,
                     "mdd": round(mdd), "avg_r": round(sum(rs) / len(rs), 2) if rs else None,
                     "false_rate": round(false_ / len(closed) * 100), "avg_win": round(sum(wins) / len(wins)) if wins else 0,
                     "avg_loss": round(sum(losses) / len(losses)) if losses else 0,
                     "by_regime": {k: f"{v[1]}/{v[0]} win" for k, v in reg.items()},
                     "verdict": ("POSITIVE" if sum(pnl) > 0 else "NEGATIVE") if len(closed) >= 20 else f"DATA {len(closed)}/20"})
    rows.sort(key=lambda r: -r["expectancy"])
    return rows
