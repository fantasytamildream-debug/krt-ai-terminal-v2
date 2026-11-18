"""🧭 KRT MARKET GUIDE — one easy box: what is happening · what can happen next · strong / weak sectors · take / avoid ·
big players buying aggressively (strike + target) · best intraday setups right now.

Also the V3.0 Market Regime Detector (7 classes + UNKNOWN) and the Command Center top strip.
Every line is built from data the terminal already has. Nothing is a prediction: "next" lines are IF/THEN scenarios on real levels.
Confidence shown = how many evidence items agree (e.g. 5/6) — NOT a win probability.
"""
import pandas as pd

LABELS = ["STRONG BULLISH", "BULLISH", "SIDEWAYS", "BEARISH", "STRONG BEARISH", "HIGH VOLATILITY", "NO TRADE", "UNKNOWN"]


def regime(nifty=None, breadth=None, sectors=None, oi=None, crash=None, stale=False, now=None):
    """→ {label, evidence[], conflicts[], agree 'x/y', time}. Missing data → UNKNOWN, never a guessed direction."""
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)
    ev, votes = [], []
    np_ = (nifty or {}).get("pct")
    if stale:
        return {"label": "NO TRADE", "evidence": ["market data is stale — no live signals"], "conflicts": [], "agree": None, "time": now.strftime("%d %b %H:%M")}
    if np_ is None and not breadth:
        return {"label": "UNKNOWN", "evidence": ["no live NIFTY / breadth data yet"], "conflicts": [], "agree": None, "time": now.strftime("%d %b %H:%M")}
    cr = crash or {}
    if np_ is not None:
        v = 1 if np_ >= 0.25 else -1 if np_ <= -0.25 else 0
        votes.append(v)
        ev.append((v, f"NIFTY {np_:+.2f}%"))
    up, dn = (breadth or {}).get("up"), (breadth or {}).get("down")
    if up is not None and dn is not None and up + dn:
        ad = up / max(dn, 1)
        v = 1 if ad >= 1.3 else -1 if ad <= 0.77 else 0
        votes.append(v)
        ev.append((v, f"breadth {up} up / {dn} down"))
    if sectors:
        pos = sum(1 for s in sectors if s["pct"] > 0)
        v = 1 if pos >= len(sectors) * 0.65 else -1 if pos <= len(sectors) * 0.35 else 0
        votes.append(v)
        ev.append((v, f"{pos}/{len(sectors)} sectors green"))
    bp = (oi or {}).get("bull_pct")
    if bp is not None:
        v = 1 if bp >= 60 else -1 if bp <= 40 else 0
        votes.append(v)
        ev.append((v, f"F&O OI: {bp:.0f}% bullish build-up"))
    sp = (nifty or {}).get("spot")
    s_, r_ = (nifty or {}).get("support"), (nifty or {}).get("resistance")
    if sp and s_ and r_:
        v = 1 if sp > r_ else -1 if sp < s_ else 0
        votes.append(v)
        ev.append((v, f"NIFTY {sp:,.0f} vs option-chain support {s_:,.0f} / resistance {r_:,.0f}"))
    n = len(votes)
    s = sum(votes)
    bull, bear = sum(1 for v in votes if v > 0), sum(1 for v in votes if v < 0)
    if cr.get("level") == "ALERT" or (bull >= 2 and bear >= 2):
        lab = "HIGH VOLATILITY"
    elif n < 2:
        lab = "UNKNOWN"
    elif s >= max(3, n - 1) and (np_ or 0) >= 0.6:
        lab = "STRONG BULLISH"
    elif s >= 2:
        lab = "BULLISH"
    elif s <= -max(3, n - 1) and (np_ or 0) <= -0.6:
        lab = "STRONG BEARISH"
    elif s <= -2:
        lab = "BEARISH"
    else:
        lab = "SIDEWAYS"
    want = 1 if "BULL" in lab else -1 if "BEAR" in lab else 0
    evid = [t for v, t in ev if want == 0 or v == want]
    conf = [t for v, t in ev if want != 0 and v == -want]
    if cr.get("level") == "ALERT":
        evid.insert(0, f"crash radar ALERT ({cr.get('side')})")
    agree = f"{sum(1 for v in votes if v == want)}/{n}" if want else f"{sum(1 for v in votes if v == 0)}/{n} neutral"
    return {"label": lab, "evidence": evid, "conflicts": conf, "agree": agree, "time": now.strftime("%d %b %H:%M")}


def _tgt(sp):
    """Big-player spike candle → underlying target estimate: price ± 2 × spike-candle range; SL beyond the candle."""
    rng = (sp.get("high") or 0) - (sp.get("low") or 0)
    px = sp.get("price") or 0
    if not (rng > 0 and px):
        return None, None
    if sp["side"] == "BUY":
        return round(px + 2 * rng, 2), round(sp["low"], 2)
    return round(px - 2 * rng, 2), round(sp["high"], 2)


def build(rg, brain, money, nifty, jv_top, feed, early, calls, adv, events, coach_of=None, now=None):
    """All inputs are already-computed terminal state. → guide dict for the UI."""
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)
    day = str(now.date())
    lab = rg.get("label")
    mood = {"STRONG BULLISH": "Buyers in full control — trend day up.", "BULLISH": "Buyers have the edge.",
            "SIDEWAYS": "No clear side — range day, breakouts fail often.", "BEARISH": "Sellers have the edge.",
            "STRONG BEARISH": "Sellers in full control — trend day down.", "HIGH VOLATILITY": "Index and stocks disagree / big swings — trade small.",
            "NO TRADE": "Data not live — no trades.", "UNKNOWN": "Not enough live data yet."}.get(lab, "")
    now_txt = f"{mood} " + " · ".join(rg.get("evidence") or [])
    nxt = []
    sp, s_, r_ = (nifty or {}).get("spot"), (nifty or {}).get("support"), (nifty or {}).get("resistance")
    if sp and s_ and r_:
        nxt.append(f"IF NIFTY holds above {r_:,.0f} (call-writers' wall) → upside can extend; CE on dips.")
        nxt.append(f"IF NIFTY breaks below {s_:,.0f} (put-writers' floor) → downside opens; PE on pullbacks.")
        nxt.append(f"Between {s_:,.0f} and {r_:,.0f} → range: book quickly at T1, avoid chasing breakouts.")
    pcr = (nifty or {}).get("pcr")
    if pcr:
        nxt.append(f"PCR {pcr} — " + ("put writers active (supportive)" if pcr >= 1.2 else "call writers active (capping)" if pcr <= 0.8 else "balanced"))
    if (brain or {}).get("advice"):
        nxt.append("🧠 " + brain["advice"])
    secs = (money or {}).get("sectors") or []
    strong = [s for s in secs if s["pct"] > 0][:3]
    weak = [s for s in sorted(secs, key=lambda s: s["pct"]) if s["pct"] < 0][:3]
    take, avoid = [], []
    for r in jv_top or []:
        v = r.get("verdict")
        p = r.get("plan") or {}
        item = {"symbol": r["symbol"], "strike": r.get("strike"), "side": r.get("side"), "entry": p.get("entry") or r.get("entry"), "sl": p.get("sl") or r.get("sl"),
                "targets": [t.get("prem") if isinstance(t, dict) else t for t in (p.get("targets") or [])][:3], "score": r.get("score"),
                "module": r.get("module"), "why": r.get("verdict_why"), "id": r.get("id"), "ltp": r.get("ltp")}
        (take if v == "TAKE" else avoid if v == "DON'T TAKE" else []).append(item)
    for m in (brain or {}).get("avoid") or []:
        avoid.append({"module": m["module"], "why": f"{m['module']} loses in this market ({m['win']}% win, {'−' if m['exp'] < 0 else '+'}₹{abs(m['exp']):,}/call)", "symbol": None})
    big = []
    for r in sorted([x for x in (feed or []) if x.get("date") == day and x.get("side") in ("BUY", "SELL") and x.get("exch") != "MCX"],
                    key=lambda x: (-(x.get("mult") or 0)))[:8]:
        t, sl = _tgt(r)
        big.append({"symbol": r["symbol"], "side": r["side"], "mult": r["mult"], "price": r["price"], "time": r["time"][11:16],
                    "seen": (r.get("seen") or "")[:5], "opt": r.get("opt"), "target": t, "sl": sl, "now": r.get("now"), "early": False})
    for r in sorted([x for x in (early or []) if x.get("date") == day], key=lambda x: x["full"], reverse=True)[:5]:
        big.insert(0, {"symbol": r["symbol"], "side": r["side"], "mult": r["mult"], "price": r["price"], "time": r["time"], "seen": r["time"],
                       "opt": r.get("opt"), "target": None, "sl": None, "early": True})
    best = []
    seen = set()
    for x in take:
        best.append(dict(x, tag="JARVIS TAKE"))
        seen.add((x["symbol"], x["side"]))
    for c in calls or []:
        if c.get("date") != day or c.get("status") != "OPEN" or c.get("shadow") or c.get("kind") == "PICK" or (c["symbol"], c.get("side")) in seen:
            continue
        g = coach_of(c) if coach_of else None
        if g and g.get("tag") not in ("ENTER", "JACKPOT"):
            continue
        best.append({"symbol": c["symbol"], "strike": c.get("strike"), "side": c.get("side"), "entry": c.get("entry"), "sl": c.get("sl"),
                     "targets": (c.get("targets") or [])[:3], "module": c.get("source"), "id": c.get("id"), "ltp": c.get("ltp"),
                     "tag": (g or {}).get("tag") or "OPEN", "why": (g or {}).get("txt"), "score": None})
        seen.add((c["symbol"], c.get("side")))
    for c in adv or []:
        if c.get("status") == "OPEN" and (c["symbol"], c.get("side")) not in seen:
            best.append({"symbol": c["symbol"], "strike": c.get("strike"), "side": c.get("side"), "entry": c.get("entry"), "sl": c.get("sl"),
                         "targets": (c.get("targets") or [])[:3], "module": "🐋 Big Player Advance", "id": c.get("id"), "ltp": c.get("ltp"), "tag": "BIG PLAYER", "score": None})
    ev = []
    for r in events or []:
        if r.get("date") in (day, str((now + pd.Timedelta(days=1)).date())):
            ev.append({"symbol": r["symbol"], "date": r["date"], "lean": (r.get("ai") or {}).get("lean")})
    return {"time": now.strftime("%d %b %H:%M"), "regime": rg, "now": now_txt, "next": nxt, "strong": strong, "weak": weak,
            "take": take[:6], "avoid": avoid[:6], "big": big[:10], "best": best[:10], "events": ev[:8],
            "rules": ["Take only TAKE / ENTER setups with entry still within 3% of the plan.", "Risk ≤ ₹2,500 per trade · SL decided before entry · never average a loser.",
                      "After T1: book half, SL to entry. After 2 SL in a row: stop for 30 min.", "No new trades after 2:30 PM (stocks) — exits only."]}


def strip(rg, feed_sum, risk, scan):
    """Top bar: Market regime | Institutional flow | Money Control | Risk status | Scan status."""
    b, s = (feed_sum or {}).get("buy") or 0, (feed_sum or {}).get("sell") or 0
    flow = "BUYERS" if b > s * 1.3 else "SELLERS" if s > b * 1.3 else "MIXED"
    return {"regime": rg.get("label"), "agree": rg.get("agree"), "flow": flow, "flow_txt": f"🐋 {b} big BUY · {s} big SELL today",
            "risk": risk, "scan": scan}
