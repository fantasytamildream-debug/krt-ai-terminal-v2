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
    src = "rules"
    LM = STATE.get("learned")                      # v93: கடந்த mistakes-ல் இருந்து கத்துக்கிட்ட weights (walk-forward-ல் rules-ஐ விட நல்லா இருந்தா மட்டும்)
    if LM and LM.get("use"):
        x = {s_["name"]: s_["v"] for s_ in sig}
        pu = _sig(LM["b"] + sum(LM["w"].get(k, 0) * x.get(k, 0) for k in LM["w"]))
        pd_ = _sig(LM["bd"] + sum(LM["wd"].get(k, 0) * x.get(k, 0) for k in LM["wd"]))
        if pu >= 0.58 and pu > pd_:
            dirn, prob = "UP", int(pu * 100)
        elif pd_ >= 0.58 and pd_ > pu:
            dirn, prob = "DOWN", int(pd_ * 100)
        else:
            dirn, prob = "RANGE", int(max(1 - pu, 1 - pd_) * 100)
        src = "learned"
    out = {"time": now.strftime("%H:%M"), "spot": spot, "score": score, "dir": dirn, "prob": prob if (dirn != "RANGE" or src == "learned") else None,
           "signals": sig, "horizon": "அடுத்த 30–60 நிமிடம்", "src": src}
    out["text"] = ({"UP": f"⬆ NIFTY மேலே போக வாய்ப்பு {out['prob']}%", "DOWN": f"⬇ NIFTY கீழே வர வாய்ப்பு {out['prob']}%",
                    "RANGE": "↔ தெளிவில்லை / sideways — இப்போ direction சொல்ல data போதல (தப்பா சொல்றதை விட இது நல்லது)"}[dirn])
    out["jackpot"] = jackpot(I, dirn, out["prob"]) if dirn != "RANGE" and out["prob"] >= 62 else None
    return out


def _sig(z):
    import math
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


NAMES = ["Breadth", "Futures OI", "5-min வேகம்", "Heavyweights", "PCR", "Day range", "Gamma flip", "V4 regime"]


def _fit(X, y, it=500, lr=0.3, l2=0.05):
    import numpy as np
    w, b = np.zeros(X.shape[1]), 0.0
    for _ in range(it):
        p = 1 / (1 + np.exp(-(X @ w + b)))
        w -= lr * (X.T @ (p - y) / len(y) + l2 * w)
        b -= lr * (p - y).mean()
    return w, b


def learn(L, min_n=40):
    """✓ / ✗ ஆன predictions (signals save ஆனவை) → UP / DOWN-க்கு தனி logistic weights. கடைசி 30%-ல் rules-ஐ விட accuracy கூடினா மட்டும் use."""
    import numpy as np
    rows = [p for p in L if p.get("sig") and p.get("status") in ("✓", "✗") and p.get("move") is not None]
    if len(rows) < min_n:
        return {"use": False, "n": len(rows), "need": min_n, "why": f"{len(rows)}/{min_n} predictions-ல் signals save ஆகியிருக்கு — {min_n} வந்ததும் கத்துக்கும்"}
    X = np.array([[p["sig"].get(k, 0) for k in NAMES] for p in rows], float)
    up = np.array([1.0 if p["move"] > 0.05 else 0.0 for p in rows])
    dn = np.array([1.0 if p["move"] < -0.05 else 0.0 for p in rows])
    k = int(len(rows) * 0.7)
    wu, bu = _fit(X[:k], up[:k])
    wd, bd = _fit(X[:k], dn[:k])

    def call(x):
        pu, pd_ = _sig(bu + float(x @ wu)), _sig(bd + float(x @ wd))
        return "UP" if pu >= 0.58 and pu > pd_ else "DOWN" if pd_ >= 0.58 and pd_ > pu else "RANGE"

    def ok(d, mv):
        return (mv > 0.05) if d == "UP" else (mv < -0.05) if d == "DOWN" else abs(mv) < 0.15
    test = rows[k:]
    acc_new = sum(ok(call(X[k + i]), p["move"]) for i, p in enumerate(test)) / len(test)
    acc_old = sum(p["status"] == "✓" for p in test) / len(test)
    wu, bu = _fit(X, up)
    wd, bd = _fit(X, dn)
    use = acc_new > acc_old + 0.03
    return {"use": bool(use), "n": len(rows), "acc_new": round(acc_new * 100), "acc_old": round(acc_old * 100),
            "w": {n: round(float(v), 3) for n, v in zip(NAMES, wu)}, "b": float(bu), "wd": {n: round(float(v), 3) for n, v in zip(NAMES, wd)}, "bd": float(bd),
            "why": (f"கத்துக்கிட்ட weights ON — test-ல் {round(acc_new * 100)}% vs பழைய rules {round(acc_old * 100)}%" if use else
                    f"கத்துக்கிட்ட weights test-ல் {round(acc_new * 100)}% vs rules {round(acc_old * 100)}% — போதுமான முன்னேற்றம் இல்லை, rules தொடரும்")}


def jackpot(I, dirn, prob, idxs=("NIFTY", "BANKNIFTY", "SENSEX")):
    """NIFTY (+BANKNIFTY) ATM / 1 ITM strike → ₹ plan."""
    from .calls import rupee_plan
    side = "CE" if dirn == "UP" else "PE"
    out = []
    for idx in idxs:
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
                  "status": "PENDING", "src": pred.get("src"), "sig": {x["name"]: x["v"] for x in pred.get("signals") or []}})
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
    if not STATE.get("learn_t") or (now - STATE["learn_t"]).total_seconds() >= 900:
        try:
            STATE["learned"], STATE["learn_t"] = learn(L), now
        except Exception as e:
            STATE["learned"], STATE["learn_t"] = {"use": False, "why": str(e)[:100]}, now
    done = [p for p in L if p["status"] in ("✓", "✗")]
    today = [p for p in done if p["date"] == str(now.date())]
    hi = [p for p in done if (p.get("prob") or 0) >= 70 and p["dir"] != "RANGE"]
    return {"all": f"{sum(1 for p in done if p['status'] == '✓')}/{len(done)}", "all_pct": round(sum(1 for p in done if p["status"] == "✓") / len(done) * 100) if done else None,
            "today": f"{sum(1 for p in today if p['status'] == '✓')}/{len(today)}",
            "hi_pct": round(sum(1 for p in hi if p["status"] == "✓") / len(hi) * 100) if hi else None, "hi_n": len(hi),
            "dir_pct": (lambda D: round(sum(p["status"] == "✓" for p in D) / len(D) * 100) if D else None)([p for p in done if p["dir"] != "RANGE"]),
            "learned": {k: v for k, v in (STATE.get("learned") or {}).items() if k in ("use", "n", "need", "acc_new", "acc_old", "why", "w")},
            "recent": list(reversed(L[-12:]))}
