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

AI = {"min_p": 0.66, "min_samples": 30, "max_day": 10 ** 6, "cold_score": 85, "pink_score": 70, "pink_min_p": 0.50}
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
    dirn = market_dir(npct, vel, up, dn, res.get("predict"))
    lvl, txt = "OK", "Market சாதாரணம்"
    if npct <= -1.0 or (npct <= -0.6 and dn >= 60) or vel <= -0.5:
        lvl, txt, dirn = "CRASH", f"Market crash possible — NIFTY {npct:+.2f}% · 5 நிமிடத்தில் {vel:+.2f}% · {dn:.0f}% stocks -1%-க்கு கீழ். CE வேண்டாம், size குறைங்க.", "DOWN"
    elif abs(vel) >= 0.3 or (neg and abs(npct) >= 0.5) or max(dn, up) >= 55:
        # V9: பழைய code-ல் vel -0.02 மாதிரி சின்ன எண் கூட "கீழே" ஆக்கிடுச்சு (prediction "மேலே" சொல்லும்போதே) → இப்போ ஒரே திசை
        side = {"UP": "மேலே", "DOWN": "கீழே"}.get(dirn, "இரு பக்கமும் — திசை தெளிவில்லை")
        lvl, txt = "BIG", f"Big move possible ({side}) — NIFTY {npct:+.2f}% · 5 நிமிட வேகம் {vel:+.2f}% · breadth ↑{up:.0f}% ↓{dn:.0f}%{' · negative gamma zone' if neg else ''}."
    STATE["risk"] = {"level": lvl, "text": txt, "nifty": npct, "vel": vel, "up": round(up), "dn": round(dn), "dir": dirn, "time": now.strftime("%H:%M")}
    return STATE["risk"]


def market_dir(npct, vel, up, dn, pred=None):
    """ஒரே market திசை (UP / DOWN / None) — prediction, breadth, NIFTY %, 5-min வேகம் எல்லாம் சேர்த்து வாக்கு.
    சின்ன noise (vel ±0.1-க்கு கீழ், breadth வித்தியாசம் <8%, NIFTY ±0.3-க்கு கீழ்) வாக்கு போடாது."""
    s = 0
    if abs(vel) >= 0.1:
        s += 1 if vel > 0 else -1
    if abs(up - dn) >= 8:
        s += 1 if up > dn else -1
    if abs(npct) >= 0.3:
        s += 1 if npct > 0 else -1
    pd_ = (pred or {}).get("dir")
    if pd_ in ("UP", "DOWN"):
        s += 2 if pd_ == "UP" else -2
    return "UP" if s >= 2 else "DOWN" if s <= -2 else None


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


RETIRED = {"Elite intraday": "Elite நீக்கப்பட்டது", "Elite holding": "Elite நீக்கப்பட்டது", "Swing": "பழைய Swing — V8 rules-ல் புதுசா",
           "POWER OI": "POWER OI நீக்கப்பட்டது", "POWER OI (range mode)": "POWER OI நீக்கப்பட்டது", "Chart pattern": "Chart pattern auto-pause"}
UPGRADES = {"Goki Mannan Jackpot": "V8: 9/9 + score 70 + 15m vol 2× + NIFTY + late இல்லை", "Top Movers": "V6: 🟢 85+ · 9:45 பிறகு · velocity",
            "Swing 5D": "V8: score 80 · vol 1.8× · close top 25%", "Swing 10D": "V8: score 80 · vol 1.8× · close top 25%",
            "V4 🥇 CQSMC PRO": "Silver-grade 2/4 filter", "V4 🥈 Order Flow + Profile": "Silver-grade 2/4 filter", "V4 🥉 Gamma Squeeze": "Silver-grade 2/4 filter",
            "Volume+OI": "V2 + learned filter (volume 2-4x block)", "OI Footprint": "learned filters", "Breakout CE": "V2 rules", "2K Profit Machine": "dup fix (V7)"}


def optimize(calls, min_n=8):
    """ஒவ்வொரு module-க்கும்: எந்த feature-bucket (நேரம் / score / volume / trend / velocity / range / OI) நஷ்டம்
    (charges சேர்த்து expectancy < 0, win% module-ஐ விட 8% கம்மி, ≥12 calls) → அதை block. Module மொத்தமா நஷ்டம் (≥25 calls) → pause."""
    PREC = {}                                       # module → pink tag ஆன முடிந்த calls P/L (நேர வரிசை)
    for c_ in sorted((x for x in (calls or []) if x.get("pink") and x.get("status") not in ("OPEN", "T1 HIT", "T2 HIT", "T3 HIT", "T4 HIT")),
                     key=lambda x: str(x.get("exit_time") or x.get("date"))):
        PREC.setdefault((c_.get("ai_from") if c_.get("kind") == "AIPICK" else None) or c_.get("source") or c_.get("kind"), []).append(c_.get("pnl_lot") or 0)
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
        mods[m]["losing"] = len(L) >= 15 and (len(kn) < 8 or sum(kn) / len(kn) < 0)      # V8 rule kept as a LABEL only
        mods[m]["paused"] = False                                                            # v107: nothing auto-paused (user choice)
        mods[m]["retired"] = RETIRED.get(m)
        mods[m]["upgrade"] = UPGRADES.get(m)
        mods[m]["pink"] = pink_tier(mods[m], PREC.get(m))
    STATE["opt"] = {"mods": mods, "blocks": blocks, "pink_cfg": PINK}
    STATE["pink_rec"] = {k: v[-PINK["prob_look"]:] for k, v in PREC.items()}
    return STATE["opt"]


# 🩷 PINK ALERT — நல்லா வேலை செய்யும் strategy-ன் call (stock / index / commodity எதுவானாலும்)
# win ≥75% = light pink · ≥80% = dark pink. ஆனா: charges சேர்த்து லாபம் (avg > 0) கட்டாயம், ≥5 முடிந்த calls.
# 20 calls-க்கு குறைவு = "sample small" — light pink மட்டும் (4/5 win luck-ஆவும் இருக்கலாம்).
# 🩷 PINK v2 (v86) — v78-ல் 5 calls-ல் 4 win = pink ஆச்சு → 05-11 அன்று 3/3 SL. இப்போ statistics-ஆ நேர்மை:
#   • min 10 முடிந்த calls (dark = 20+) · charges சேர்த்து லாபம் கட்டாயம்
#   • Wilson lower bound (95%) — "sample size-ஐ வச்சு குறைஞ்சபட்சம் எவ்வளவு win %" ≥55% (dark ≥62%)
#   • Pink probation: module-ன் கடைசி 6 pink calls-ல் 4+ நஷ்டம் → pink நிறுத்தம்
#   • Call-level: market திசைக்கு எதிர் / trend நாளில் mean-reversion counter-trend → pink இல்லை
PINK = {"light": 75, "dark": 80, "min_n": 10, "proven_n": 20, "lb_light": 0.55, "lb_dark": 0.62, "prob_look": 6, "prob_loss": 4}
MR_WORDS = ("mean reversion", "vwap2sd", "reversal", "fade")


def wilson(w, n, z=1.96):
    if not n:
        return 0.0
    p = w / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (c - r) / d


def pink_tier(md, recent=None):
    """Module stats (+ அதன் கடைசி pink calls result) → None / {"tier", "win", "n", "lb", "small"}."""
    if not md or md.get("paused") or md.get("retired"):
        return None
    af = md.get("after_filters") or {}
    use_af = (af.get("n") or 0) >= PINK["min_n"] and af.get("win") is not None
    n, win, exp = (af["n"], af["win"], af.get("exp")) if use_af else (md.get("n") or 0, md.get("win") or 0, md.get("exp"))
    if n < PINK["min_n"] or exp is None or exp <= 0 or win < PINK["light"]:
        return None
    lb = wilson(round(win / 100 * n), n)
    if lb < PINK["lb_light"]:
        return None
    rec = [x for x in (recent or [])][-PINK["prob_look"]:]
    if len(rec) >= PINK["prob_look"] and sum(1 for x in rec if x <= 0) >= PINK["prob_loss"]:
        return None                                  # 🩷 probation — pink calls உண்மையில் தோக்குது
    small = n < PINK["proven_n"]
    tier = "dark" if (win >= PINK["dark"] and not small and lb >= PINK["lb_dark"]) else "light"
    return {"tier": tier, "win": win, "n": n, "exp": exp, "small": small, "lb": round(lb * 100)}


def pink_gate(c, mod_name=""):
    """Call-level: market திசை எதிர் / பெரிய trend நாளில் counter-trend mean-reversion → pink block காரணம் (இல்லைன்னா None)."""
    r = STATE.get("risk") or {}
    d, npct = r.get("dir"), r.get("nifty") or 0
    ce = c.get("side") == "CE"
    if c.get("exch") != "MCX":
        if d and (d == "UP") != ce:
            return f"Market {'⬆' if d == 'UP' else '⬇'} எதிர் பக்கம்"
        if abs(npct) >= 1.0 and (npct > 0) != ce and any(w in str(mod_name).lower() for w in MR_WORDS):
            return f"NIFTY {npct:+.1f}% trend நாள் — mean-reversion counter-trend"
    return None


def pink_of(c):
    """Call-க்கு அதன் module-ன் pink tier."""
    m = (c.get("ai_from") if c.get("kind") == "AIPICK" else None) or c.get("source") or c.get("kind")
    if c.get("kind") == "PICK":
        return None
    return ((((STATE.get("opt") or {}).get("mods") or {}).get(m)) or {}).get("pink")


def pink_scan(store, lock, now, send):
    """இன்றைய புது calls-ல் pink module-ன் call இருந்தா → tag + Telegram/WhatsApp alert (ஒரு call-க்கு ஒருமுறை)."""
    day = str(now.date())
    out = []
    with lock:
        d = store.load()
        for c in (d.get("calls") or {}).values():
            if c.get("date") != day or c.get("shadow") or c.get("pink_sent") or c.get("status") not in ("OPEN", "T1 HIT"):
                continue
            pk = pink_of(c)
            if not pk:
                continue
            why_b = pink_gate(c, c.get("source") or c.get("kind"))
            if why_b:
                c["pink_block"], c["pink_sent"] = why_b, now.strftime("%H:%M")      # ஒருமுறை முடிவு — இந்த call pink இல்லை
                store.dirty = True
                continue
            c["pink"], c["pink_sent"] = pk, now.strftime("%H:%M")
            store.dirty = True
            out.append(c)
    for c in out:
        pk = c["pink"]
        try:
            send(f"{'🩷🩷 DARK PINK' if pk['tier'] == 'dark' else '🩷 PINK'} ALERT · {c.get('source') or c.get('kind')} (win {pk['win']}% · {pk['n']} calls"
                 f"{' · ⚠ sample small' if pk['small'] else ''})\nBUY {c['symbol']} {c.get('strike')} {c.get('side')} · Entry ₹{c.get('entry')} · SL ₹{c.get('sl')}"
                 f" · T1 ₹{(c.get('targets') or [None])[0]} (paper)", f"pink|{c['id']}")
        except Exception:
            pass
    return out


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


def pink_tick(now):
    """NSE fast tick / MCX loop இரண்டிலும் கூப்பிடலாம் — optimizer 5 நிமிடத்துக்கு ஒருமுறை fresh + pink scan."""
    from .calls import CALLS_LOCK, STORE
    from .telegram import send
    if not STATE.get("opt") or not STATE.get("_pt") or (now - STATE["_pt"]).total_seconds() > 300:
        try:
            optimize(list((STORE.load().get("calls") or {}).values()))
        except Exception:
            pass
        STATE["_pt"] = now
    out = pink_scan(STORE, CALLS_LOCK, now, send)
    try:
        from .notify import both, notify_tick
        notify_tick(now)                               # 📲 எல்லா புது calls → phone push (stock / index / MCX)
        exit_alerts(STORE, CALLS_LOCK, now, both)      # 🎯 T1/T2/T3 · SL · exit → Telegram + phone push
    except Exception:
        pass
    return out


EXIT_MSG = {"SL HIT": "🔴 SL HIT — exit", "TRAIL SL": "🟡 TRAIL SL — profit-உடன் exit", "T3 DONE": "🏆 T3 DONE — full target, exit",
            "EOD EXIT": "⏹ EOD auto exit"}


def exit_alerts(store, lock, now, send):
    """🔔 Browser மூடியிருந்தாலும்: இன்றைய calls-ல் T1/T2/T3 hit · SL / exit ஆனதும் Telegram / WhatsApp (ஒவ்வொன்றுக்கும் ஒருமுறை)."""
    day = str(now.date())
    msgs = []
    with lock:
        d = store.load()
        for c in (d.get("calls") or {}).values():
            if c.get("date") != day or c.get("shadow"):
                continue
            h = len(c.get("hits") or [])
            if "_al" not in c:                 # முதல் தடவை பார்க்கும் call → இப்போதைய நிலை (பழைய hits-க்கு spam இல்லை)
                c["_al"] = {"h": h, "x": c.get("status") if c.get("status") in EXIT_MSG else None}
                store.dirty = True
                continue
            al = c["_al"]
            nm = f"{c['symbol']} {c.get('strike')} {c.get('side')}"
            pl = c.get("pnl_lot") or 0
            if h > al["h"]:
                for k in range(al["h"] + 1, h + 1):
                    msgs.append((f"🎯 T{k} HIT · {nm} · ₹{pl:+,.0f}/lot\n" + ("👉 SL-ஐ entry-க்கு மாத்துங்க (இனி நஷ்டம் இல்லை)" if k == 1 else f"👉 SL-ஐ T{k - 1}-க்கு trail பண்ணுங்க"),
                                 f"tgt|{c['id']}|{k}"))
                al["h"] = h
                store.dirty = True
            st = c.get("status")
            if st in EXIT_MSG and al.get("x") != st:
                al["x"] = st
                store.dirty = True
                msgs.append((f"{EXIT_MSG[st]} · {nm} · {c.get('source_label') or c.get('source')}\nExit ₹{c.get('exit')} · P/L ₹{pl:+,.0f}/lot (paper)", f"exit|{c['id']}"))
    for t, k in msgs[:10]:
        try:
            send(t, k)
        except Exception:
            pass
    return len(msgs)



def pink_history(calls):
    """🩷 pink tag ஆன எல்லா calls (pink_scan tag பண்ணது) → date-wise result + மொத்த win ratio. நிரந்தரம் (STORE-ல்)."""
    pk = [c for c in calls if c.get("pink") and not c.get("shadow")]
    pk.sort(key=lambda c: (c.get("date") or "", c.get("time") or ""), reverse=True)
    OPEN = ("OPEN", "T1 HIT", "T2 HIT", "T3 HIT", "T4 HIT")
    days = {}
    for c in pk:
        d = days.setdefault(c["date"], {"date": c["date"], "calls": 0, "closed": 0, "win": 0, "net": 0, "dark": 0})
        d["calls"] += 1
        d["dark"] += int((c.get("pink") or {}).get("tier") == "dark")
        d["net"] += c.get("pnl_lot") or 0
        if c.get("status") not in OPEN:
            d["closed"] += 1
            d["win"] += int((c.get("pnl_lot") or 0) > 0)
    for d in days.values():
        d["win_rate"] = round(d["win"] / d["closed"] * 100) if d["closed"] else None
    closed = [c for c in pk if c.get("status") not in OPEN]
    w = sum((c.get("pnl_lot") or 0) > 0 for c in closed)
    return {"rows": pk[:300], "days": sorted(days.values(), key=lambda d: d["date"], reverse=True),
            "total": {"calls": len(pk), "closed": len(closed), "win": w, "win_rate": round(w / len(closed) * 100) if closed else None,
                      "net": round(sum(c.get("pnl_lot") or 0 for c in pk))}}


def trade_journal(calls):
    """📒 VERIFIED TRADE JOURNAL — முடிந்த calls மட்டும் (paper, 1 lot), charges சேர்த்து:
    win rate · profit factor (மொத்த லாபம் ÷ மொத்த நஷ்டம்) · max drawdown (cumulative net peak → trough) · expectancy · streaks."""
    OPEN = ("OPEN", "T1 HIT", "T2 HIT", "T3 HIT", "T4 HIT", "VOID")
    done = [c for c in calls if not c.get("shadow") and c.get("status") not in OPEN and c.get("kind") != "PICK" and c.get("pnl_lot") is not None]
    done.sort(key=lambda c: str(c.get("exit_time") or f"{c.get('date')} {c.get('time')}"))

    def stats(xs):
        if not xs:
            return {"n": 0}
        net = [(c.get("pnl_lot") or 0) - charges(c) for c in xs]
        wins, losses = [x for x in net if x > 0], [x for x in net if x <= 0]
        eq, peak, mdd = 0.0, 0.0, 0.0
        for x in net:
            eq += x
            peak = max(peak, eq)
            mdd = max(mdd, peak - eq)
        streak = best_w = best_l = 0
        for x in net:
            streak = (streak + 1 if streak >= 0 else 1) if x > 0 else (streak - 1 if streak <= 0 else -1)
            best_w, best_l = max(best_w, streak), min(best_l, streak)
        gl = abs(sum(losses))
        return {"n": len(xs), "win": len(wins), "win_rate": round(len(wins) / len(xs) * 100, 1), "net": round(sum(net)),
                "gross": round(sum(c.get("pnl_lot") or 0 for c in xs)), "pf": round(sum(wins) / gl, 2) if gl else None,
                "mdd": round(mdd), "avg_win": round(sum(wins) / len(wins)) if wins else 0, "avg_loss": round(sum(losses) / len(losses)) if losses else 0,
                "exp": round(sum(net) / len(xs)), "best": round(max(net)), "worst": round(min(net)), "max_win_streak": best_w, "max_loss_streak": -best_l}
    import datetime as _dt
    today = _dt.date.today()
    last7 = str(today - _dt.timedelta(days=7))
    by = {}
    for c in done:
        by.setdefault(c.get("source_label") or c.get("source") or c.get("kind"), []).append(c)
    mods = sorted(({"module": k, **stats(v)} for k, v in by.items() if len(v) >= 3), key=lambda r: -(r.get("net") or 0))
    curve, eq = [], 0.0
    for c in done[-200:]:
        eq += (c.get("pnl_lot") or 0) - charges(c)
        curve.append(round(eq))
    return {"all": stats(done), "d7": stats([c for c in done if str(c.get("date")) >= last7]),
            "today": stats([c for c in done if str(c.get("date")) == str(today)]),
            "chart": stats([c for c in done if c.get("kind") == "CHART"]), "modules": mods[:25], "curve": curve}
