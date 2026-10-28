"""🤖 KRT AI PICKS — உங்க history-ல் இருந்து கத்துக்கும் picker + 🚨 market risk detector.

எப்படி வேலை செய்யும் (நேர்மையா):
  • ஒவ்வொரு call-க்கும் features: module, நேரம், side vs NIFTY, score, volume, velocity, day-range இடம், OI build-up.
  • முடிந்த calls (இன்று + history) — எந்த feature இருந்தப்போ win / SL ஆனது-ன்னு count → naive-Bayes மாதிரி log-odds.
  • புது candidate-க்கு "win வாய்ப்பு %" கணக்கு. ≥ 70% (data போதுமானா) ஆனா மட்டும் AI pick.
  • இது LLM / magic இல்லை — உங்க சொந்த data-வில் இருந்து statistics. Data அதிகமாக ஆக மேம்படும்.
  • 80%+ win rate guarantee யாராலும் தர முடியாது; AI picks-ன் உண்மையான win rate website-ல் காட்டப்படும்.
"""
import math

import pandas as pd

AI = {"min_p": 0.70, "min_samples": 30, "max_day": 5, "cold_score": 88}
STATE = {"model": None, "risk": None, "nifty_hist": []}
IDX = ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY")


def _tb(t):
    try:
        h, m = int(str(t)[:2]), int(str(t)[3:5])
    except Exception:
        return "?"
    x = h * 60 + m
    return "09:15-09:45" if x < 585 else "09:45-11:00" if x < 660 else "11:00-13:00" if x < 780 else "13:00-15:30"


def feats(src, side, time, score=None, vol=None, vel=None, pos=None, oi=None, nifty_pct=None, symbol=""):
    f = {"module": src or "?", "time": _tb(time), "type": "index" if symbol in IDX else "stock"}
    if nifty_pct is not None:
        f["trend"] = "flat" if abs(nifty_pct) < 0.2 else ("with" if (nifty_pct > 0) == (side == "CE") else "against")
    if score is not None:
        f["score"] = "85+" if score >= 85 else "70-84" if score >= 70 else "<70"
    if vol is not None:
        f["volume"] = "4x+" if vol >= 4 else "2-4x" if vol >= 2 else "<2x"
    if vel is not None and vel != 0:
        f["velocity"] = "aligned" if (vel > 0) == (side == "CE") else "against"
    if pos is not None:
        f["range"] = "extreme" if (pos >= 0.85 if side == "CE" else pos <= 0.15) else "mid"
    if oi:
        ok = (side == "CE" and oi in ("Long Built Up", "Short Covering")) or (side == "PE" and oi in ("Short Built Up", "Long Unwinding"))
        f["oi"] = "aligned" if ok else "against"
    return f


def feat_of_call(c):
    """பழைய calls-க்கு (feat save ஆகாதவை) கிடைக்கிற fields-ல் இருந்து features."""
    if c.get("feat"):
        return c["feat"]
    sc = None
    try:
        sc = float(str(c.get("confidence", "")).split("score")[-1].strip().split()[0])
    except Exception:
        pass
    return feats(c.get("source") or c.get("kind"), c.get("side"), c.get("time"), score=sc, vol=c.get("vol_ratio"), symbol=c.get("symbol", ""))


def train(calls):
    """முடிந்த calls → feature-value win stats."""
    OPEN = ("OPEN", "T1 HIT", "T2 HIT", "T3 HIT", "T4 HIT")
    rows = [c for c in calls if c.get("status") not in OPEN and c.get("status") not in ("VOID", "CANCELLED") and c.get("entry")]
    n = len(rows)
    w = sum(1 for c in rows if (c.get("pnl_lot") or 0) > 0)
    base = (w + 1) / (n + 2)
    stats = {}
    for c in rows:
        win = (c.get("pnl_lot") or 0) > 0
        for k, v in feat_of_call(c).items():
            s = stats.setdefault(k, {}).setdefault(v, [0, 0])
            s[0] += 1
            s[1] += int(win)
    pick_rows = [c for c in rows if c.get("kind") == "PICK"]
    ai_rows = [c for c in rows if c.get("kind") == "AIPICK"]
    STATE["model"] = {"n": n, "wins": w, "base": round(base, 3), "stats": stats,
                      "your_picks": {"n": len(pick_rows), "wr": round(sum(1 for c in pick_rows if c["pnl_lot"] > 0) / len(pick_rows) * 100) if pick_rows else None},
                      "ai_picks": {"n": len(ai_rows), "wr": round(sum(1 for c in ai_rows if c["pnl_lot"] > 0) / len(ai_rows) * 100) if ai_rows else None,
                                   "net": sum(c["pnl_lot"] for c in ai_rows)}}
    return STATE["model"]


def predict(f):
    """→ (p_win, காரணங்கள்). Feature-value-க்கு ≥5 samples இருந்தா மட்டும் கணக்கில்."""
    M = STATE.get("model")
    if not M or M["n"] < AI["min_samples"]:
        return None, []
    base = M["base"]
    lo = math.log(base / (1 - base))
    why = []
    for k, v in f.items():
        s = (M["stats"].get(k) or {}).get(v)
        if not s or s[0] < 5:
            continue
        p = (s[1] + 1) / (s[0] + 2)
        d = math.log(p / (1 - p)) - math.log(base / (1 - base))
        d = max(-1.2, min(1.2, d * min(1.0, s[0] / 20)))          # கம்மி sample-க்கு கம்மி weight
        lo += d
        why.append((d, f"{k}={v}: {round(p * 100)}% ({s[0]})"))
    p = 1 / (1 + math.exp(-lo))
    why.sort(key=lambda x: -abs(x[0]))
    return round(p, 3), [("▲ " if d > 0 else "▼ ") + t for d, t in why[:4]]


def market_risk(live_q, res, now):
    """🚨 Crash / big move possible — NIFTY % · 5-நிமிட வேகம் · breadth (F&O stocks) · V4 regime / GEX."""
    npct = next((x.get("pct") for x in res.get("index") or [] if x.get("index") == "NIFTY"), 0) or 0
    H = STATE["nifty_hist"]
    t = now.timestamp() if hasattr(now, "timestamp") else 0
    H.append((t, npct))
    del H[:-60]
    old = [p for tt, p in H if t - tt >= 280]
    vel = round(npct - old[-1], 2) if old else 0.0
    q = [v.get("pct") or 0 for v in live_q.values()]
    n = len(q) or 1
    dn = sum(1 for x in q if x <= -1) / n * 100
    up = sum(1 for x in q if x >= 1) / n * 100
    gex = next((g for g in res.get("gex") or [] if g.get("index") == "NIFTY"), {}) or {}
    neg = "NEGATIVE" in str(gex.get("zone", ""))
    lvl, txt = "OK", "Market சாதாரணம்"
    if npct <= -1.0 or (npct <= -0.6 and dn >= 60) or vel <= -0.5:
        lvl, txt = "CRASH", f"Market crash possible — NIFTY {npct:+.2f}% · 5 நிமிடத்தில் {vel:+.2f}% · {dn:.0f}% stocks -1%-க்கு கீழ். CE வேண்டாம், size குறைங்க."
    elif abs(vel) >= 0.3 or (neg and abs(npct) >= 0.5) or max(dn, up) >= 55:
        side = "கீழே" if (vel < 0 or dn > up) else "மேலே"
        lvl, txt = "BIG", f"Big move possible ({side}) — NIFTY {npct:+.2f}% · 5 நிமிட வேகம் {vel:+.2f}% · breadth ↑{up:.0f}% ↓{dn:.0f}%{' · negative gamma zone' if neg else ''}."
    STATE["risk"] = {"level": lvl, "text": txt, "nifty": npct, "vel": vel, "up": round(up), "dn": round(dn), "time": now.strftime("%H:%M")}
    return STATE["risk"]


# ───────────── 💸 charges + 🧠 module optimizer ─────────────
def charges(c):
    """1 lot round-trip charges (₹): brokerage ₹20×2 · STT 0.15% sell · exchange 0.0355% · SEBI · stamp 0.003% buy · GST 18%."""
    try:
        lot = float(c.get("lot") or 0)
        buy = float(c.get("entry") or 0) * lot
        sell = float(c.get("exit") if c.get("exit") is not None else c.get("ltp") or 0) * lot
    except Exception:
        return 0
    brk = 40.0
    exch = (buy + sell) * 0.000355299
    sebi = (buy + sell) * 1e-6
    gst = 0.18 * (brk + exch + sebi)
    return round(brk + sell * 0.0015 + exch + sebi + buy * 0.00003 + gst)


def net_of(c):
    return (c.get("pnl_lot") or 0) - charges(c)


def optimize(calls, min_n=12):
    """ஒவ்வொரு module-க்கும்: எந்த feature-bucket (நேரம் / score / volume / trend / velocity / range / OI) நஷ்டம்
    (charges சேர்த்து expectancy < 0, win% module-ஐ விட 8% கம்மி, ≥12 calls) → அதை block. Module மொத்தமா நஷ்டம் (≥25 calls) → pause."""
    OPEN = ("OPEN", "T1 HIT", "T2 HIT", "T3 HIT", "T4 HIT")
    rows = [c for c in calls if c.get("status") not in OPEN and c.get("status") not in ("VOID", "CANCELLED") and c.get("entry")
            and c.get("kind") not in ("PICK", "AIPICK")]
    by = {}
    for c in rows:
        by.setdefault(c.get("source") or c.get("kind"), []).append(c)
    mods, blocks = {}, []
    for m, L in by.items():
        n = len(L)
        nets = [net_of(c) for c in L]
        wr = sum(1 for x in nets if x > 0) / n
        exp = sum(nets) / n
        mods[m] = {"n": n, "win": round(wr * 100), "exp": round(exp), "net": round(sum(nets)), "gross": sum(c.get("pnl_lot") or 0 for c in L),
                   "paused": False}
        buckets = {}
        for c, x in zip(L, nets):
            for k, v in feat_of_call(c).items():
                if k in ("module", "type"):
                    continue
                buckets.setdefault((k, v), []).append(x)
        for (k, v), xs in buckets.items():
            if len(xs) < min_n:
                continue
            bw = sum(1 for x in xs if x > 0) / len(xs)
            be = sum(xs) / len(xs)
            if be < 0 and bw <= wr - 0.08:
                blocks.append({"module": m, "k": k, "v": v, "n": len(xs), "win": round(bw * 100), "exp": round(be)})
    blocks.sort(key=lambda b: b["exp"])
    # learned filters போட்ட பிறகும் மீதி calls நஷ்டம்னா தான் module pause (நல்ல நேரம் / condition-ஐ காப்பாத்தும்)
    for m, L in by.items():
        bl = [b for b in blocks if b["module"] == m]
        keep = [c for c in L if not any(feat_of_call(c).get(b["k"]) == b["v"] for b in bl)]
        kn = [net_of(c) for c in keep[-60:]]                 # சமீபத்திய 60 — recover ஆனா தானா resume
        mods[m]["after_filters"] = {"n": len(keep), "exp": round(sum(kn) / len(kn)) if kn else None,
                                    "win": round(sum(1 for x in kn if x > 0) / len(kn) * 100) if kn else None}
        mods[m]["paused"] = len(L) >= 25 and (len(kn) < 10 or sum(kn) / len(kn) < 0)
    STATE["opt"] = {"mods": mods, "blocks": blocks}
    return STATE["opt"]


def blocked(c):
    """Call-க்கு learned block / module pause பொருந்துதா → (code, காரணம்) அல்லது None."""
    O = STATE.get("opt") or {}
    m = c.get("source") or c.get("kind")
    md = (O.get("mods") or {}).get(m)
    if md and md["paused"]:
        return ("Q_MODULE_PAUSED", f"{m}: {md['n']} calls-ல் charges சேர்த்து சராசரி ₹{md['exp']} — auto pause (shadow paper-ல் track — லாபம் திரும்பினா resume)")
    f = c.get("feat") or {}
    for b in O.get("blocks") or []:
        if b["module"] == m and f.get(b["k"]) == b["v"]:
            return ("Q_LEARNED", f"{m}: {b['k']}={b['v']} — {b['n']} calls-ல் win {b['win']}%, சராசரி ₹{b['exp']} (learned filter)")
    return None
