"""🔮 MARKET PREDICTION — அடுத்த 30–60 நிமிடம் NIFTY மேல / கீழ / range? + 👑 Index Jackpot setup (NIFTY / BANKNIFTY strike + plan).
Leading signals (ஒவ்வொன்றும் −1…+1 × weight): Breadth 20 · Futures OI build-up 15 · 5-min வேகம் 15 · Heavyweights 15 · PCR 10 ·
Day-range இடம் 10 · Gamma flip 10 · V4 regime 5.  Probability = 50 + |score|×0.4 (max 85%).
ஒவ்வொரு 15 நிமிடமும் prediction save → 45 நிமிடம் கழிச்சு சரியா தப்பா check → accuracy %. Rule-based estimate — guarantee இல்லை.
"""
import pandas as pd

HEAVY = {"RELIANCE": 9, "HDFCBANK": 13, "ICICIBANK": 9, "INFY": 5, "TCS": 3, "BHARTIARTL": 4, "LT": 4, "ITC": 3, "SBIN": 3, "AXISBANK": 3}
STATE = {"last": None}


def _clip(x, a=1.0):
    return max(-a, min(a, x))


def compute(res, live_q, now):
    I = {x.get("index"): x for x in res.get("index") or []}
    nf = I.get("NIFTY") or {}
    spot = nf.get("spot")
    if not spot:
        return None
    sig = []

    def add(name, val, w, txt):
        sig.append({"name": name, "v": round(_clip(val), 2), "w": w, "pts": round(_clip(val) * w, 1), "txt": txt})

    q = [v.get("pct") or 0 for v in live_q.values()]
    up, dn = sum(1 for x in q if x > 0.2), sum(1 for x in q if x < -0.2)
    if up + dn:
        add("Breadth", (up - dn) / (up + dn), 20, f"↑{up} / ↓{dn} stocks")
    bk = {"Long Built Up": 1, "Short Covering": 1, "Short Built Up": -1, "Long Unwinding": -1}
    oi = [(bk[k], len(v)) for k, v in (res.get("oi_buildup") or {}).items() if k in bk]
    tot = sum(n for _, n in oi)
    if tot:
        add("Futures OI", sum(s * n for s, n in oi) / tot, 15, f"bull {sum(n for s, n in oi if s > 0)} · bear {sum(n for s, n in oi if s < 0)}")
    try:
        from .ai import STATE as AST
        vel = ((AST.get("risk") or {}).get("vel")) or 0
    except Exception:
        vel = 0
    add("5-min வேகம்", vel / 0.3, 15, f"NIFTY 5-min {vel:+.2f}%")
    hv = [(live_q.get(n) or {}).get("pct") for n in HEAVY]
    hw = [(p, HEAVY[n]) for n, p in zip(HEAVY, hv) if p is not None]
    if hw:
        avg = sum(p * w for p, w in hw) / sum(w for _, w in hw)
        add("Heavyweights", avg / 1.0, 15, f"Reliance/HDFC/ICICI… avg {avg:+.2f}%")
    pcr = nf.get("pcr")
    if pcr:
        add("PCR", (pcr - 1.0) / 0.25, 10, f"PCR {pcr}")
    hi, lo = nf.get("day_high") or spot, nf.get("day_low") or spot
    if hi > lo:
        pos = (spot - lo) / (hi - lo)
        add("Day range", (pos - 0.5) * 2, 10, f"Day range-ல் {int(pos * 100)}%")
    gx = next((g for g in res.get("gex") or [] if g.get("index") == "NIFTY"), None)
    if gx and gx.get("flip"):
        add("Gamma flip", (spot - gx["flip"]) / max(1, spot * 0.003), 10, f"Flip {gx['flip']} — spot {'மேல்' if spot > gx['flip'] else 'கீழ்'}")
    try:
        from .v4 import STATE as V4S
        ix = V4S.get("indices") or {}
        reg = ((ix.get("NIFTY") or {}).get("regime") if isinstance(ix, dict)
               else next((x.get("regime") for x in ix if x.get("index") == "NIFTY"), "")) or ""
    except Exception:
        reg = ""
    if reg:
        add("V4 regime", 1 if "UP" in reg else -1 if "DOWN" in reg else 0, 5, reg)
    wsum = sum(s["w"] for s in sig) or 1
    score = round(sum(s["pts"] for s in sig) * 100 / wsum, 1)
    prob = int(min(85, 50 + abs(score) * 0.4))
    dirn = "UP" if score > 12 else "DOWN" if score < -12 else "RANGE"
    out = {"time": now.strftime("%H:%M"), "spot": spot, "score": score, "dir": dirn, "prob": prob if dirn != "RANGE" else int(50 + (12 - abs(score)) * 1.5),
           "signals": sig, "horizon": "அடுத்த 30–60 நிமிடம்"}
    out["text"] = ({"UP": f"⬆ NIFTY மேலே போக வாய்ப்பு {out['prob']}%", "DOWN": f"⬇ NIFTY கீழே வர வாய்ப்பு {out['prob']}%",
                    "RANGE": "↔ Range / sideways வாய்ப்பு அதிகம் — பெரிய move எதிர்பார்க்கல"}[dirn])
    out["jackpot"] = jackpot(I, dirn, out["prob"]) if dirn != "RANGE" and out["prob"] >= 62 else None
    return out


def jackpot(I, dirn, prob):
    """NIFTY (+BANKNIFTY) ATM / 1 ITM strike → ₹ plan."""
    from .calls import rupee_plan
    side = "CE" if dirn == "UP" else "PE"
    out = []
    for idx in ("NIFTY", "BANKNIFTY", "SENSEX"):
        x = I.get(idx) or {}
        spot, ch = x.get("spot"), x.get("chain") or []
        if not spot or not ch:
            continue
        ks = sorted(r["strike"] for r in ch if r.get(side))
        if not ks:
            continue
        itm = [k for k in ks if (k <= spot if side == "CE" else k >= spot)]
        k = (itm[-1] if side == "CE" else itm[0]) if itm else min(ks, key=lambda k: abs(k - spot))
        o = next(r[side] for r in ch if r["strike"] == k)
        e = o.get("ask") or o.get("ltp")
        if not e or not o.get("token"):
            continue
        sl_, tg_, rk_, rc_ = rupee_plan(e, e * 0.7, o["lot"], False)
        out.append({"index": idx, "side": side, "strike": k, "expiry": x.get("expiry"), "lot": o["lot"], "token": o["token"], "exch": o["exch"],
                    "contract": o["contract"], "ltp": o.get("ltp"), "entry": round(e, 2), "sl": round(sl_, 2), "targets": [round(t, 2) for t in tg_], "risk": rk_,
                    "t_rs": [round((t - e) * o["lot"]) for t in tg_], "prob": prob})
    return out


def track(pred, store, now):
    """15 நிமிடத்துக்கு ஒரு prediction save · 45 நிமிடம் கழிச்சு சரியா check."""
    if not pred:
        return None
    d = store.load()
    L = d.setdefault("mkt_preds", [])
    slot = now.floor("15min").strftime("%Y-%m-%d %H:%M")
    if not L or L[-1]["slot"] != slot:
        L.append({"slot": slot, "date": str(now.date()), "time": now.strftime("%H:%M"), "spot": pred["spot"], "dir": pred["dir"], "prob": pred["prob"],
                  "status": "PENDING"})
        del L[:-400]
        store.dirty = True
    for p in L:
        if p["status"] != "PENDING":
            continue
        age = (now - pd.Timestamp(p["slot"])).total_seconds() / 60
        if p["date"] != str(now.date()):
            p["status"] = "EXPIRED"
            continue
        if age >= 45:
            mv = (pred["spot"] / p["spot"] - 1) * 100
            ok = (mv > 0.05) if p["dir"] == "UP" else (mv < -0.05) if p["dir"] == "DOWN" else abs(mv) < 0.15
            p.update(status="✓" if ok else "✗", move=round(mv, 2), end=now.strftime("%H:%M"))
            store.dirty = True
    done = [p for p in L if p["status"] in ("✓", "✗")]
    today = [p for p in done if p["date"] == str(now.date())]
    hi = [p for p in done if p["prob"] >= 70 and p["dir"] != "RANGE"]
    return {"all": f"{sum(1 for p in done if p['status'] == '✓')}/{len(done)}", "all_pct": round(sum(1 for p in done if p["status"] == "✓") / len(done) * 100) if done else None,
            "today": f"{sum(1 for p in today if p['status'] == '✓')}/{len(today)}",
            "hi_pct": round(sum(1 for p in hi if p["status"] == "✓") / len(hi) * 100) if hi else None, "hi_n": len(hi),
            "recent": list(reversed(L[-12:]))}
