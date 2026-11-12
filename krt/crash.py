"""⚠ CRASH / SURGE RADAR — பெரிய sell-off / rally தொடங்கும்போதே early warning (prediction இல்லை).

Signals (DOWN — UP-க்கு mirror):
  • NIFTY 5 நிமிடத்தில் ≤ −0.30% · 15 நிமிடத்தில் ≤ −0.60%   • BANKNIFTY 5 நிமிடத்தில் ≤ −0.45% (banks lead)
  • Breadth: இறக்கம் ≥ 65% அல்லது 15 நிமிடத்தில் +15 points ஏறுது   • NIFTY futures 1M footprint: sell stack ≥ 3 + delta ≤ −40%
  • India VIX ≥ +4% (பயம் கூடுது)
2 signals = ⚠ WATCH · 3+ = 🚨 ALERT → phone push + voice (10 நிமிட cooldown). ஒவ்வொரு alert-க்கும் 15 நிமிடம் கழிச்சு NIFTY
என்ன ஆச்சு என்று save — radar உண்மையில் உதவுதா என்று உங்க data-லேயே தெரியும்.
"""
CFG = {"n5": 0.30, "n15": 0.60, "b5": 0.45, "breadth": 65, "breadth_jump": 15, "vix": 4.0, "cool_min": 10}
H = {}                     # name → [(ts, value)]
STATE = {"level": "NONE", "side": None, "signals": [], "time": None, "history": [], "last_push": None}


def _push(name, ts, v, keep_min=50):
    L = H.setdefault(name, [])
    L.append((ts, v))
    while L and (ts - L[0][0]).total_seconds() > keep_min * 60:
        L.pop(0)


def _chg(name, now, mins, pct=True):
    L = H.get(name) or []
    if len(L) < 2:
        return None
    old = next((v for t, v in reversed(L) if (now - t).total_seconds() >= mins * 60), None)
    if old is None:
        return None
    cur = L[-1][1]
    return (cur / old - 1) * 100 if pct else cur - old


def evaluate(now, risk=None, fp=None):
    n5, n15, b5 = _chg("NIFTY", now, 5), _chg("NIFTY", now, 15), _chg("BANKNIFTY", now, 5)
    dn_share = (risk or {}).get("dn")
    up_share = (risk or {}).get("up")
    bj_dn, bj_up = _chg("breadth_dn", now, 15, False), _chg("breadth_up", now, 15, False)
    vix = _chg("VIX", now, 15)
    out = {}
    for side, sg in (("DOWN", -1), ("UP", 1)):
        S = []
        if n5 is not None and n5 * sg >= CFG["n5"]:
            S.append(f"NIFTY 5 நிமிடத்தில் {n5:+.2f}%")
        if n15 is not None and n15 * sg >= CFG["n15"]:
            S.append(f"NIFTY 15 நிமிடத்தில் {n15:+.2f}%")
        if b5 is not None and b5 * sg >= CFG["b5"]:
            S.append(f"BANKNIFTY 5 நிமிடத்தில் {b5:+.2f}% (banks lead)")
        share, jump = (dn_share, bj_dn) if side == "DOWN" else (up_share, bj_up)
        if share is not None and share >= CFG["breadth"]:
            S.append(f"Breadth: {share}% stocks {'இறக்கம்' if side == 'DOWN' else 'ஏற்றம்'}")
        elif jump is not None and jump >= CFG["breadth_jump"]:
            S.append(f"Breadth 15 நிமிடத்தில் +{jump:.0f} points {'இறக்கம்' if side == 'DOWN' else 'ஏற்றம்'} பக்கம்")
        if fp:
            an = fp.get("an") or {}
            if side == "DOWN" and an.get("sell_stack", 0) >= 3 and an.get("delta_pct", 0) <= -40:
                S.append(f"NIFTY futures footprint: {an['sell_stack']} stacked sell · delta {an['delta_pct']}%")
            if side == "UP" and an.get("buy_stack", 0) >= 3 and an.get("delta_pct", 0) >= 40:
                S.append(f"NIFTY futures footprint: {an['buy_stack']} stacked buy · delta +{an['delta_pct']}%")
        # v104 EARLY (divergence) — price still going the OTHER way but flow / breadth / fear already turning → comes before the momentum signals
        if n15 is not None and n15 * sg <= -0.15:
            if fp and (fp.get("an") or {}).get("delta_pct", 0) * sg >= 40:
                S.append(f"⚡ early: NIFTY still {n15:+.2f}% but futures flow already {'selling' if side == 'DOWN' else 'buying'} (hidden {'distribution' if side == 'DOWN' else 'accumulation'})")
            if jump is not None and 10 <= jump < CFG["breadth_jump"]:      # ≥15 is already counted by the normal breadth signal
                S.append(f"⚡ early: price {'up' if side == 'DOWN' else 'down'} but breadth turning ({jump:+.0f} pts in 15 min)")
            if vix is not None and side == "DOWN" and vix >= 3:
                S.append(f"⚡ early: India VIX +{vix:.1f}% while NIFTY still up — fear rising under the surface")
        if vix is not None and side == "DOWN" and vix >= CFG["vix"]:
            S.append(f"India VIX 15 நிமிடத்தில் +{vix:.1f}% (பயம் கூடுது)")
        if vix is not None and side == "UP" and vix <= -CFG["vix"]:
            S.append(f"India VIX {vix:.1f}% (பயம் குறையுது)")
        out[side] = S
    side = "DOWN" if len(out["DOWN"]) >= len(out["UP"]) else "UP"
    n = len(out[side])
    level = "ALERT" if n >= 3 else "WATCH" if n >= 2 else "NONE"
    return {"level": level, "side": side if level != "NONE" else None, "signals": out[side] if level != "NONE" else [], "n5": n5, "n15": n15, "b5": b5}


def tick(items, now, risk=None, fp=None, send=None):
    """tick_loop (2 sec) — இந்த function-ல் API call இல்லை, ஏற்கனவே வந்த prices மட்டும்."""
    for k in ("NIFTY", "BANKNIFTY"):
        if (items.get(k) or {}).get("ltp"):
            _push(k, now, float(items[k]["ltp"]))
    if (items.get("INDIA VIX") or {}).get("ltp"):
        _push("VIX", now, float(items["INDIA VIX"]["ltp"]))
    if risk:
        if risk.get("dn") is not None:
            _push("breadth_dn", now, float(risk["dn"]))
        if risk.get("up") is not None:
            _push("breadth_up", now, float(risk["up"]))
    ev = evaluate(now, risk, fp)
    prev_lv, prev_side = STATE["level"], STATE["side"]
    STATE.update(level=ev["level"], side=ev["side"], signals=ev["signals"], time=now.strftime("%I:%M:%S %p"), n5=ev["n5"], n15=ev["n15"])
    rank = {"NONE": 0, "WATCH": 1, "ALERT": 2}
    cool = STATE["last_push"] is None or (now - STATE["last_push"]).total_seconds() >= CFG["cool_min"] * 60
    if ev["level"] != "NONE" and (rank[ev["level"]] > rank[prev_lv] or ev["side"] != prev_side) and cool:
        STATE["last_push"] = now
        px = (H.get("NIFTY") or [(None, None)])[-1][1]
        STATE["history"].insert(0, {"date": str(now.date()), "time": now.strftime("%H:%M"), "level": ev["level"], "side": ev["side"],
                                    "signals": ev["signals"], "nifty": px, "after15": None, "_ts": now})
        del STATE["history"][40:]
        head = ("🚨 CRASH ALERT" if ev["side"] == "DOWN" else "🚀 SURGE ALERT") if ev["level"] == "ALERT" else \
               ("⚠ பெரிய SELL வர வாய்ப்பு" if ev["side"] == "DOWN" else "⚠ பெரிய BUY வர வாய்ப்பு")
        msg = head + "\n" + " · ".join(ev["signals"]) + ("\n👉 CE positions SL tight பண்ணுங்க / புது CE வேண்டாம்" if ev["side"] == "DOWN" else
                                                         "\n👉 PE positions SL tight பண்ணுங்க / புது PE வேண்டாம்")
        if send:
            try:
                send(msg, f"crash|{now.strftime('%H%M')}", True)
            except Exception:
                pass
    for h in STATE["history"]:                       # 15 நிமிடம் கழிச்சு outcome
        if h["after15"] is None and h.get("_ts") is not None and (now - h["_ts"]).total_seconds() >= 900 and h.get("nifty"):
            cur = (H.get("NIFTY") or [(None, None)])[-1][1]
            if cur:
                mv = (cur / h["nifty"] - 1) * 100
                h["after15"] = round(mv, 2)
                h["right"] = (mv < -0.15) if h["side"] == "DOWN" else (mv > 0.15)
    return STATE


def report():
    H_ = [{k: v for k, v in h.items() if k != "_ts"} for h in STATE["history"]]
    done = [h for h in H_ if h.get("after15") is not None]
    return {**{k: STATE.get(k) for k in ("level", "side", "signals", "time", "n5", "n15")}, "history": H_,
            "hit": (round(sum(bool(h.get("right")) for h in done) / len(done) * 100) if done else None), "n": len(done)}
