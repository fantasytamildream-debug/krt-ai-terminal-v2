"""🎯 KRT SNIPER — Signal Quality Score (SQS) · Data Integrity · Risk & Position Sizing · MTF · AI explanation.

SQS (0–100) = Price Action 25 · Order Flow 20 · Volume + VWAP 20 · Options 15 · Market Regime 10 · Risk + Liquidity 10
  85–100 = 🟢 PRIORITY (confirmation இருந்தா entry) · 70–84 = 🟡 WATCHLIST · <70 = 🔴 SKIP
⚠ Score 90 = 90% win இல்லை — weights experimental; journal-ல் tier வாரியா உண்மையான win % காட்டும் (calibration).
"""
import math
import time

W = {"pa": 25, "of": 20, "vv": 20, "opt": 15, "reg": 10, "risk": 10}
NAME = {"pa": "Price Action", "of": "Order Flow", "vv": "Volume + VWAP", "opt": "Options", "reg": "Market Regime", "risk": "Risk + Liquidity"}
OPEN = ("OPEN", "T1 HIT", "T2 HIT")


def _ag(rows, keys):
    v = [r["agree"] for r in rows if r["key"] in keys]
    return (sum(v) / len(v) + 1) / 2 if v else 0.5            # −1..1 → 0..1


def score(c, ch=None, guide=None, enter=None, brain=None, mdir=None):
    a = (ch or {}).get("analysis") or {}
    M = a.get("methods") or {}
    R = M.get("rows") or []
    ce = c.get("side") != "PE"
    part = {}
    part["pa"] = _ag(R, ("pa", "smc", "sr", "sd", "mtf")) if R else 0.5
    g = guide or {}
    if g and g.get("side") == c.get("side"):
        part["of"] = {"BUY": 1.0, "RISK": 0.85, "STRIKE": 0.8, "WAIT": 0.55, "NONE": 0.3}.get(g.get("k"), 0.5)
    else:
        part["of"] = _ag(R, ("of", "vsa")) if R else 0.5
    vr = float(c.get("vol_ratio") or 0)
    vol = 1.0 if vr >= 2 else 0.75 if vr >= 1.5 else 0.5 if vr >= 1 else 0.3
    part["vv"] = (vol + (_ag(R, ("vwap", "vp")) if R else 0.5)) / 2
    sp = c.get("strike_pick") or {}
    e = enter or {}
    o = 0.5
    if sp.get("score") or e.get("score"):
        o = float(sp.get("score") or e.get("score")) / 100
    elif c.get("spread_pct") is not None:
        o = 0.8 if c["spread_pct"] <= 1 else 0.6 if c["spread_pct"] <= 2 else 0.3
    cv = ((e.get("chain") or {}).get("verdict")) or ""
    o = min(1.0, o + 0.2) if cv.startswith("✅") else 0.0 if cv.startswith("⛔") else o
    part["opt"] = o
    reg = 0.5
    fams = (brain or {}).get("use") or []
    try:
        from .ailab import family
        reg = 1.0 if family(c) in fams else 0.4
    except Exception:
        pass
    if c.get("exch") != "MCX" and mdir:
        reg = reg * (1.0 if (mdir == "UP") == ce else 0.3)
    part["reg"] = reg
    lot = float(c.get("lot") or 1)
    risk = (float(c.get("entry") or 0) - float(c.get("sl") or 0)) * lot
    part["risk"] = (1.0 if risk <= 2500 else 0.5 if risk <= 4000 else 0.0) * (0.6 if (c.get("spread_pct") or 0) > 2 else 1.0)
    total = round(sum(W[k] * part[k] for k in W))
    tier = "PRIORITY" if total >= 85 else "WATCH" if total >= 70 else "SKIP"
    good = sorted(W, key=lambda k: -part[k] * W[k])[:2]
    bad = [k for k in sorted(W, key=lambda k: part[k]) if part[k] < 0.5][:2]
    lots = int(2500 // risk) if risk > 0 else 0
    tf = (a.get("mtf") or {}).get("tf") or {}
    want = "UP" if ce else "DOWN"
    fp_dir = None
    if g and g.get("k") in ("BUY", "RISK", "STRIKE", "WAIT"):
        fp_dir = "UP" if g.get("side") == "CE" else "DOWN"
    mtf = {"1M": fp_dir, **{k: v for k, v in tf.items()}}
    aligned = sum(1 for v in mtf.values() if v == want)
    why = ([f"✓ {NAME[k]} வலுவா ({round(part[k] * 100)}%)" for k in good] + [f"✗ {NAME[k]} பலவீனம் ({round(part[k] * 100)}%)" for k in bad])
    verdict = {"PRIORITY": "🟢 PRIORITY — confirmation candle வந்தா entry", "WATCH": "🟡 WATCHLIST — இன்னும் 1–2 confirmation வேணும்",
               "SKIP": "🔴 SKIP — score போதல"}[tier]
    return {"score": total, "tier": tier, "parts": {k: round(part[k] * 100) for k in W}, "risk": round(risk), "lots": lots,
            "mtf": mtf, "aligned": aligned, "why": why, "verdict": verdict}


def integrity(now, tick_t=None, deep_t=None, chart_t=None, store=None, angel=None, fp_t=None, market_open=False):
    """🩺 Data Integrity — stale ticks / scan / chart · Angel login fails · storage."""
    issues, ok = [], []

    def age(t):
        if not t:
            return None
        try:
            import pandas as pd
            tt = pd.Timestamp(f"{now.date()} {t}") if len(str(t)) <= 11 else pd.Timestamp(str(t)[:19])
            return (now - tt).total_seconds()
        except Exception:
            return None
    if market_open:
        a = age(tick_t)
        (issues if a is None or a > 30 else ok).append(f"Live ticks {'வரல' if a is None else f'{int(a)} sec முன்'}")
        a = age(deep_t)
        (issues if a is None or a > 1200 else ok).append(f"Deep scan {'இல்லை' if a is None else f'{int(a // 60)} நிமிடம் முன்'}")
        a = age(chart_t)
        (issues if a is None or a > 900 else ok).append(f"Chart room {'இல்லை' if a is None else f'{int(a // 60)} நிமிடம் முன்'}")
        a = age(fp_t)
        (issues if a is None or a > 300 else ok).append(f"Footprint feed {'இல்லை' if a is None else f'{int(a)} sec முன்'}")
    if store is not None and getattr(store, "load_failed", False):
        issues.append(f"Storage: {getattr(store, 'error', '')}")
    else:
        ok.append("Storage OK")
    lf = getattr(angel, "login_fails", 0) if angel else 0
    if lf:
        issues.append(f"Angel login fail {lf} தடவை")
    st = "HEALTHY" if not issues else "WARN" if len(issues) <= 1 else "BAD"
    return {"status": st, "issues": issues, "ok": ok}


def calibrate(calls):
    """Tier வாரியா உண்மையான win % (முடிந்த calls-ல் sqs save ஆனவை) — score நம்பலாமா என்று."""
    out = {}
    for c in calls:
        q = c.get("sqs")
        if not q or c.get("status") in OPEN or c.get("status") == "VOID":
            continue
        t = out.setdefault(q["tier"], {"n": 0, "win": 0, "net": 0})
        t["n"] += 1
        t["win"] += int((c.get("pnl_lot") or 0) > 0)
        t["net"] += c.get("pnl_lot") or 0
    for t in out.values():
        t["win_rate"] = round(t["win"] / t["n"] * 100) if t["n"] else None
    return out
