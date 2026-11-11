"""📐 CREDIT SPREADS / IRON CONDOR (paper) — option *selling*, defined risk.

எப்போ (10:00–11:30, index-க்கு நாளைக்கு ஒன்று):
  • Iron Condor — Index OI bias NEUTRAL / RANGE + NIFTY |move| < 0.5%: CE wall (அதிக CE OI) விக்கு + 2 strike மேல் வாங்கு ·
    PE wall விக்கு + 2 strike கீழ் வாங்கு. Short strikes spot-ல் இருந்து ≥0.4% தூரம்.
  • Bull Put spread — BULLISH TILT: support PE wall விக்கு + 2 strike கீழ் வாங்கு
  • Bear Call spread — BEARISH TILT: resistance CE wall விக்கு + 2 strike மேல் வாங்கு
Exit: லாபம் ≥ 50% of credit · நஷ்டம் ≥ 1× credit · spot short strike-ஐ தாண்டினா · 3:15.
⚠ Selling-க்கு margin அதிகம் (NIFTY IC ≈ ₹1 லட்சம்+) · gap risk · paper மட்டும்.
"""
CFG = {"start": "10:00", "end": "11:30", "exit": "15:15", "wing": 2, "tp": 0.5, "sl": 1.0, "min_dist": 0.4}
STATE = {"time": None, "log": []}
OPEN = ("OPEN",)


def _leg(row, typ):
    x = (row or {}).get(typ) or {}
    return x if x.get("token") else None


def build(x, nifty_pct):
    """Index OI row (chain-உடன்) → spread plan அல்லது None."""
    rows = x.get("chain") or []
    if len(rows) < 8 or not x.get("spot"):
        return None
    spot, ks = x["spot"], [r["strike"] for r in rows]
    by = {r["strike"]: r for r in rows}
    bias = x.get("bias") or ""
    ce_wall = max([r for r in rows if r["strike"] >= spot * (1 + CFG["min_dist"] / 100)], key=lambda r: r.get("CE", {}).get("oi", 0), default=None)
    pe_wall = max([r for r in rows if r["strike"] <= spot * (1 - CFG["min_dist"] / 100)], key=lambda r: r.get("PE", {}).get("oi", 0), default=None)

    def wing(k, d):
        i = ks.index(k)
        j = i + d
        return ks[j] if 0 <= j < len(ks) else None
    legs, kind = [], None
    if "NEUTRAL" in bias and abs(nifty_pct or 0) < 0.5 and ce_wall and pe_wall:
        kind = "IRON CONDOR"
        cw, pw = wing(ce_wall["strike"], CFG["wing"]), wing(pe_wall["strike"], -CFG["wing"])
        if not (cw and pw):
            return None
        legs = [("SELL", ce_wall["strike"], "CE"), ("BUY", cw, "CE"), ("SELL", pe_wall["strike"], "PE"), ("BUY", pw, "PE")]
    elif "BULLISH" in bias and pe_wall:
        kind = "BULL PUT SPREAD"
        pw = wing(pe_wall["strike"], -CFG["wing"])
        if not pw:
            return None
        legs = [("SELL", pe_wall["strike"], "PE"), ("BUY", pw, "PE")]
    elif "BEARISH" in bias and ce_wall:
        kind = "BEAR CALL SPREAD"
        cw = wing(ce_wall["strike"], CFG["wing"])
        if not cw:
            return None
        legs = [("SELL", ce_wall["strike"], "CE"), ("BUY", cw, "CE")]
    if not legs:
        return None
    L, credit = [], 0.0
    for act, k, t in legs:
        o = _leg(by.get(k), t)
        if not o or not o.get("ltp"):
            return None
        px = (o.get("bid") or o["ltp"]) if act == "SELL" else (o.get("ask") or o["ltp"])     # sell = bid · buy = ask (realistic fill)
        credit += px if act == "SELL" else -px
        L.append({"act": act, "strike": k, "type": t, "token": o["token"], "exch": o["exch"], "contract": o["contract"], "entry": round(float(px), 2), "lot": o["lot"]})
    if credit <= 0:
        return None
    lot = L[0]["lot"]
    width = max(abs(L[0]["strike"] - L[1]["strike"]), abs(L[2]["strike"] - L[3]["strike"]) if len(L) == 4 else 0)
    shorts = [l for l in L if l["act"] == "SELL"]
    be = {"up": round(max([l["strike"] for l in shorts if l["type"] == "CE"], default=0) + credit, 2) if any(l["type"] == "CE" for l in shorts) else None,
          "dn": round(min([l["strike"] for l in shorts if l["type"] == "PE"], default=0) - credit, 2) if any(l["type"] == "PE" for l in shorts) else None}
    return {"index": x["index"], "kind": kind, "spot0": spot, "legs": L, "credit": round(credit, 2), "width": width, "lot": lot,
            "max_profit": round(credit * lot), "max_loss": round((width - credit) * lot), "be": be,
            "why": f"{bias} · PCR {x.get('pcr')} · CE wall {ce_wall['strike'] if ce_wall else '–'} · PE wall {pe_wall['strike'] if pe_wall else '–'}"}


def value(sp, qs):
    """இப்போ spread-ஐ மூட ஆகும் cost (sell legs-ஐ ask-ல் வாங்கணும், buy legs-ஐ bid-ல் விக்கணும்)."""
    cost = 0.0
    for l in sp["legs"]:
        q = qs.get(l["token"]) or {}
        d = q.get("depth") or {}
        bid = float(((d.get("buy") or [{}])[0] or {}).get("price") or 0) or float(q.get("ltp") or 0)
        ask = float(((d.get("sell") or [{}])[0] or {}).get("price") or 0) or float(q.get("ltp") or 0)
        if not (bid or ask):
            return None
        cost += ask if l["act"] == "SELL" else -bid
    return round(cost, 2)


def run(ag, now, idx_rows, nifty_pct):
    from .calls import CALLS_LOCK, STORE
    day, hm = str(now.date()), now.strftime("%H:%M")
    with CALLS_LOCK:
        D = STORE.load()
        S = D.setdefault("spreads", [])
        today = [s for s in S if s["date"] == day]
        if CFG["start"] <= hm <= CFG["end"]:
            for x in idx_rows or []:
                if x.get("index") not in ("NIFTY", "BANKNIFTY") or any(s["index"] == x["index"] for s in today):
                    continue
                sp = build(x, nifty_pct)
                if sp:
                    sp.update(id=f"{day}|SPR|{x['index']}", date=day, time=hm, status="OPEN", pnl=0, cost=sp["credit"])
                    S.append(sp)
                    today.append(sp)
                    STORE.dirty = True
                    STATE["log"].insert(0, {"time": hm, "index": x["index"], "result": f"✅ {sp['kind']} · credit ₹{sp['credit']}"})
        live = [s for s in S if s["status"] in OPEN]
        if live and ag:
            toks = {}
            for s in live:
                for l in s["legs"]:
                    toks.setdefault(l["exch"], []).append(l["token"])
            try:
                qs = ag.quotes(toks) or {}
            except Exception:
                qs = {}
            spot = {x["index"]: x.get("spot") for x in idx_rows or []}
            for s in live:
                cost = value(s, qs)
                if cost is None:
                    continue
                s["cost"] = cost
                s["pnl"] = round((s["credit"] - cost) * s["lot"])
                sp_ = spot.get(s["index"])
                hit = None
                if s["pnl"] >= CFG["tp"] * s["credit"] * s["lot"]:
                    hit = "TARGET (50% credit)"
                elif -s["pnl"] >= CFG["sl"] * s["credit"] * s["lot"]:
                    hit = "SL (1× credit)"
                elif sp_ and any((l["type"] == "CE" and sp_ > l["strike"]) or (l["type"] == "PE" and sp_ < l["strike"]) for l in s["legs"] if l["act"] == "SELL"):
                    hit = "SHORT STRIKE BREACH"
                elif hm >= CFG["exit"] or s["date"] != day:
                    hit = "TIME EXIT 3:15"
                if hit:
                    s.update(status=hit, exit_time=f"{day} {hm}")
                STORE.dirty = True
        del S[:-300]
    STATE["time"] = now.strftime("%I:%M %p")
    return S


def report(D):
    S = sorted((D or {}).get("spreads") or [], key=lambda s: (s["date"], s["time"]), reverse=True)
    closed = [s for s in S if s["status"] not in OPEN]
    w = sum(s["pnl"] > 0 for s in closed)
    return {"rows": S[:60], "stats": {"n": len(closed), "win": round(w / len(closed) * 100) if closed else None, "net": sum(s["pnl"] for s in closed)},
            "time": STATE["time"], "log": STATE["log"][:10], "cfg": CFG}
