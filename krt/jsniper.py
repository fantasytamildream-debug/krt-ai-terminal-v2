"""🎯 JARVIS SNIPER (V3.0 Institutional Sniper upgrade) — fewer, cleaner setups with a clear accept / reject reason.

Built on top of the JARVIS scan (same live calls, same Chart Room analysis) — re-weighted to the Sniper model:
  Market trend + sector alignment 15 · Liquidity sweep + market structure 20 · Volume + OI 20 · VWAP + multi-timeframe 15 ·
  Options liquidity + spread 10 · Entry quality + reward/risk 15 · News + event risk 5  = 100
  90–100 Elite candidate (confirmation still required) · 80–89 Strong watchlist · 70–79 Wait · <70 Reject
States: PRE-ALERT → SETUP FORMING → READY → CONFIRMED · INVALIDATED · EXPIRED.  Early alerts are NOT buy calls.
False-breakout filter: wick back inside the broken level · fading from the day extreme · weak volume · wrong side of VWAP ·
over-extended move · premium already ran. 2+ trap flags → rejected.
Risk: 1 lot planned loss + estimated costs must be ≤ ₹2,500, else rejected. A factor without data scores 0 and is listed as missing.
Score = setup-quality ranking, NOT a win probability. Weights are initial settings, to be validated out-of-sample.
"""
W = {"trend_sector": 15, "structure": 20, "vol_oi": 20, "vwap_mtf": 15, "opt_liq": 10, "entry_rr": 15, "event": 5}
NAME = {"trend_sector": "Trend + sector", "structure": "Liquidity sweep + structure", "vol_oi": "Volume + OI", "vwap_mtf": "VWAP + multi-timeframe",
        "opt_liq": "Option liquidity + spread", "entry_rr": "Entry quality + R:R", "event": "News / event risk"}
MAX_RISK = 2500


def band(s):
    return "ELITE" if s >= 90 else "STRONG WATCH" if s >= 80 else "WAIT" if s >= 70 else "REJECT"


def traps(r, q, lv):
    """False-breakout / trap checks from live quote + previous-day levels."""
    out = []
    ce = r.get("side") != "PE"
    ltp, hi, lo, vw = q.get("ltp"), q.get("high"), q.get("low"), q.get("vwap")
    pdh, pdl = (lv or {}).get("PDH"), (lv or {}).get("PDL")
    if ltp and hi and lo and hi > lo:
        pos = (ltp - lo) / (hi - lo)
        if ce and pdh and hi > pdh > ltp:
            out.append(f"failed breakout — went above PDH {pdh:g}, now back below")
        if not ce and pdl and lo < pdl < ltp:
            out.append(f"failed breakdown — went below PDL {pdl:g}, now back above")
        if ce and pos < 0.4:
            out.append(f"fading — price at {pos * 100:.0f}% of the day range")
        if not ce and pos > 0.6:
            out.append(f"bouncing — price at {pos * 100:.0f}% of the day range")
    vr = q.get("vol_ratio")
    if vr is not None and vr < 1.2:
        out.append(f"weak volume {vr}×")
    if vw and ltp and ((ce and ltp < vw) or (not ce and ltp > vw)):
        out.append(f"wrong side of VWAP {vw:g}")
    pct = q.get("pct")
    if pct is not None and ((ce and pct >= 4) or (not ce and pct <= -4)):
        out.append(f"over-extended {pct:+.1f}% — exhaustion risk")
    e, l_ = r.get("entry") or 0, r.get("ltp") or 0
    if e and l_ and l_ > e * 1.05:
        out.append(f"premium already ran {((l_ / e) - 1) * 100:.0f}% above entry")
    return out


def score(r, q, lv, sec_pct, event):
    P, miss = {}, []
    p = r.get("parts") or {}
    ce = r.get("side") != "PE"

    def g(k):
        v = p.get(k)
        if v is None:
            miss.append(k)
        return v
    t = g("trend")
    sp = None
    if sec_pct is not None:
        sp = 5 if (sec_pct >= 0.3 if ce else sec_pct <= -0.3) else 2 if abs(sec_pct) < 0.3 else 0
    P["trend_sector"] = None if t is None and sp is None else round((t or 0) * 10 / 15 + (sp or 0))
    P["structure"] = g("structure")
    v, o = g("volume"), g("oi")
    P["vol_oi"] = None if v is None and o is None else round(((v or 0) + (o or 0)) * 20 / 30)
    m = g("mtf")
    vw, ltp = q.get("vwap"), q.get("ltp")
    vp = None if not (vw and ltp) else (5 if (ltp >= vw) == ce else 0)
    P["vwap_mtf"] = None if m is None and vp is None else round((m or 0) + (vp or 0))
    P["opt_liq"] = g("liquidity")
    rr = g("rr")
    pl = r.get("plan") or {}
    zl, zh = (pl.get("zone") or [None, None])[:2]
    inz = 5 if zl and r.get("ltp") and zl <= r["ltp"] <= zh else 0
    P["entry_rr"] = None if rr is None else round(rr + inz)
    P["event"] = 0 if event else 5
    P = {k: (None if v_ is None else max(0, min(W[k], v_))) for k, v_ in P.items()}
    return P, [NAME.get(k, k) for k in ("trend_sector", "structure", "vol_oi", "vwap_mtf", "opt_liq", "entry_rr") if P.get(k) is None]


def costs(entry, sl, lot):
    try:
        from .ai import charges
        return charges({"lot": lot, "entry": entry, "exit": sl})
    except Exception:
        return 60


def build(jv_top, live_q, levels, sectors, results, avoid_mods, early, v4_setups, regime_label=None, data_age=None):
    secp = {s["sector"]: s["pct"] for s in sectors or []}
    from .money import SECTOR
    evs = {r["symbol"]: r for r in results or [] if 0 <= (r.get("days") if r.get("days") is not None else 9) <= 2}
    bad = {m["module"]: m for m in avoid_mods or []}
    cards = []
    for r in jv_top or []:
        q = (live_q or {}).get(r["symbol"]) or {}
        lv = (levels or {}).get(r["symbol"])
        sec = SECTOR.get(r["symbol"])
        P, miss = score(r, q, lv, secp.get(sec), evs.get(r["symbol"]))
        sc = sum(v or 0 for v in P.values())
        tr = traps(r, q, lv)
        pl = r.get("plan") or {}
        e, sl, lot = float(pl.get("entry") or r.get("entry") or 0), float(pl.get("sl") or r.get("sl") or 0), float(r.get("lot") or 0)
        T = [t.get("prem") if isinstance(t, dict) else t for t in pl.get("targets") or []][:3]
        risk = round((e - sl) * lot + costs(e, sl, lot)) if e > sl and lot else None
        rr = round((T[1 if len(T) > 1 else 0] - e) / (e - sl), 2) if T and e > sl else None
        rej = []
        if len(tr) >= 2:
            rej.append("trap risk: " + "; ".join(tr[:2]))
        if risk is not None and risk > MAX_RISK:
            rej.append(f"1-lot risk ₹{risk:,} incl. costs > ₹{MAX_RISK:,}")
        if (r.get("val") or {}).get("decision") == "REJECT":
            rej.append("validator: " + ", ".join((r.get("val") or {}).get("fails") or []))
        if r.get("module") in bad:
            m = bad[r["module"]]
            rej.append(f"{r['module']} is disabled in this market ({m['win']}% win, {'−' if m['exp'] < 0 else '+'}₹{abs(m['exp']):,}/call in {regime_label or 'this regime'})")
        if evs.get(r["symbol"]):
            tr.append(f"results {evs[r['symbol']].get('date')} — event risk")
        if data_age is not None and data_age > 180:
            rej.append(f"data stale ({int(data_age)} s old)")
        b = band(sc)
        ltp = r.get("ltp") or 0
        if rej or b == "REJECT":
            state = "EXPIRED" if T and ltp and ltp >= T[0] else "INVALIDATED"
        elif b in ("ELITE", "STRONG WATCH") and r.get("verdict") == "TAKE" and (pl.get("zone") or [0, 0])[0] <= ltp <= (pl.get("zone") or [0, 0])[1]:
            state = "CONFIRMED"
        elif b in ("ELITE", "STRONG WATCH"):
            state = "READY"
        else:
            state = "SETUP FORMING"
        acc = (["5-min close in the trade direction still required"] if state in ("READY", "CONFIRMED") else [])
        good = [NAME[k] for k, v in P.items() if v is not None and v >= W[k] * 0.7]
        cards.append({"id": r.get("id"), "symbol": r["symbol"], "side": r.get("side"), "strike": r.get("strike"), "expiry": r.get("expiry"), "module": r.get("module"),
                      "score": sc, "band": b, "state": state, "parts": P, "missing": miss, "traps": tr, "reject": rej, "accept": good, "need": acc,
                      "entry": e, "sl": sl, "targets": T, "rr": rr, "lot": lot or None, "risk": risk, "ltp": ltp,
                      "regime": regime_label, "sector": sec, "sector_pct": secp.get(sec), "oi": (r.get("raw_call") or {}).get("oi"),
                      "vwap": q.get("vwap"), "vwap_side": None if not (q.get("vwap") and q.get("ltp")) else ("above" if q["ltp"] >= q["vwap"] else "below"),
                      "rvol": q.get("vol_ratio"), "structure": (r.get("why") or [None])[0], "verdict": r.get("verdict"), "fresh": data_age})
    order = {"CONFIRMED": 0, "READY": 1, "SETUP FORMING": 2, "INVALIDATED": 3, "EXPIRED": 4}
    cards.sort(key=lambda c: (order[c["state"]], -c["score"]))
    pre = [{"kind": "⚡ early volume", "symbol": x["symbol"], "side": "CE" if x["side"] == "BUY" else "PE", "time": x["time"],
            "why": f"last 2 min volume {x['mult']}× normal, price {x['move']:+.2f}%"} for x in sorted(early or [], key=lambda x: x["full"], reverse=True)[:6]]
    for s in v4_setups or []:
        if s.get("stage") == "FORMING":
            pre.append({"kind": "V4 forming", "symbol": s.get("index"), "side": s.get("side"), "time": None, "why": f"{s.get('name')} · score {s.get('score')}"})
    return {"cards": cards, "pre": pre[:10], "weights": W, "names": NAME,
            "summary": {k: sum(1 for c in cards if c["state"] == k) for k in order}}
