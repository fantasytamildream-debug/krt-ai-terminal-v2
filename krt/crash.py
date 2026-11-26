"""⚠ CRASH / SURGE RADAR — பெரிய sell-off / rally தொடங்கும்போதே early warning (prediction இல்லை).

Signals (DOWN — UP-க்கு mirror):
  • NIFTY 5 நிமிடத்தில் ≤ −0.30% · 15 நிமிடத்தில் ≤ −0.60%   • BANKNIFTY 5 நிமிடத்தில் ≤ −0.45% (banks lead)
  • Breadth: இறக்கம் ≥ 65% அல்லது 15 நிமிடத்தில் +15 points ஏறுது   • NIFTY futures 1M footprint: sell stack ≥ 3 + delta ≤ −40%
  • India VIX ≥ +4% (பயம் கூடுது)
2 signals = ⚠ WATCH · 3+ = 🚨 ALERT → phone push + voice (10 நிமிட cooldown). ஒவ்வொரு alert-க்கும் 15 நிமிடம் கழிச்சு NIFTY
என்ன ஆச்சு என்று save — radar உண்மையில் உதவுதா என்று உங்க data-லேயே தெரியும்.
"""
CFG = {"n5": 0.30, "n15": 0.60, "b5": 0.45, "breadth": 65, "breadth_jump": 15, "vix": 4.0, "cool_min": 10,
       # v131 SLOW-BLEED signals — a steady grind down (e.g. 23 Nov: −480 pts over hours, no single fast 5-min candle) was invisible before
       "n30": 0.50, "from_hi": 0.80, "near_lo": 0.30, "breadth_strong": 75}
DAY = {"date": None, "hi": None, "lo": None}
H = {}                     # name → [(ts, value)]
STATE = {"level": "NONE", "side": None, "signals": [], "time": None, "history": [], "last_push": None}


def _push(name, ts, v, keep_min=70):
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


def evaluate(now, risk=None, fp=None, fp2=None, day_pct=None):
    n5, n15, b5 = _chg("NIFTY", now, 5), _chg("NIFTY", now, 15), _chg("BANKNIFTY", now, 5)
    b15 = _chg("BANKNIFTY", now, 15)
    dn_share = (risk or {}).get("dn")
    up_share = (risk or {}).get("up")
    bj_dn, bj_up = _chg("breadth_dn", now, 15, False), _chg("breadth_up", now, 15, False)
    vix = _chg("VIX", now, 15)
    n30 = _chg("NIFTY", now, 30)
    L = H.get("NIFTY") or []
    cur = L[-1][1] if L else None
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
        if share is not None and share >= CFG["breadth_strong"]:
            S.append(f"Very broad {'selling' if side == 'DOWN' else 'buying'}: {share}% of stocks {'down' if side == 'DOWN' else 'up'}")
        if n30 is not None and n30 * sg >= CFG["n30"] and not (n15 is not None and n15 * sg >= CFG["n15"]):
            S.append(f"🐢 NIFTY 30 நிமிடத்தில் {n30:+.2f}% (steady {'fall' if side == 'DOWN' else 'rise'})")
        if cur and DAY["hi"] and DAY["lo"] and DAY["date"] == str(now.date()):
            if side == "DOWN":
                off = (cur / DAY["hi"] - 1) * 100
                if off <= -CFG["from_hi"] and (cur / DAY["lo"] - 1) * 100 <= CFG["near_lo"]:
                    S.append(f"🐢 NIFTY day high {DAY['hi']:,.0f}-லிருந்து {off:+.2f}% — still near the day low (no bounce)")
            else:
                off = (cur / DAY["lo"] - 1) * 100
                if off >= CFG["from_hi"] and (1 - cur / DAY["hi"]) * 100 <= CFG["near_lo"]:
                    S.append(f"🐢 NIFTY day low {DAY['lo']:,.0f}-லிருந்து +{off:.2f}% — still near the day high")
        # v139 — 25 Nov: a GREEN day sold 1.1 % from its high (profit booking) never reached 2 signals: breadth stayed positive and
        # no single 5/15-min candle was big. These three see it: the turn itself, banks falling for 15 min, BANKNIFTY futures selling.
        if cur and DAY["hi"] and DAY["lo"] and DAY["date"] == str(now.date()) and day_pct is not None and n15 is not None:
            _pc = cur / (1 + day_pct / 100)                    # previous close
            hi_pct, lo_pct = (DAY["hi"] / _pc - 1) * 100, (DAY["lo"] / _pc - 1) * 100
            if side == "DOWN" and hi_pct >= TCFG["day_min"] and (cur / DAY["hi"] - 1) * 100 <= -TCFG["off"] and n15 <= -TCFG["n15"]:
                S.append(f"📉 Profit booking: green day (NIFTY {day_pct:+.2f}%) sold {(cur / DAY['hi'] - 1) * 100:+.2f}% from the high {DAY['hi']:,.0f}")
            if side == "UP" and lo_pct <= -TCFG["day_min"] and (cur / DAY["lo"] - 1) * 100 >= TCFG["off"] and n15 >= TCFG["n15"]:
                S.append(f"📈 Short covering: red day (NIFTY {day_pct:+.2f}%) up {(cur / DAY['lo'] - 1) * 100:+.2f}% from the low {DAY['lo']:,.0f}")
        if b15 is not None and b15 * sg >= 0.6 and not (b5 is not None and b5 * sg >= CFG["b5"]):
            S.append(f"BANKNIFTY 15 நிமிடத்தில் {b15:+.2f}% (banks {'falling' if side == 'DOWN' else 'rising'})")
        if fp2:
            a2 = fp2.get("an") or {}
            if side == "DOWN" and a2.get("sell_stack", 0) >= 3 and a2.get("delta_pct", 0) <= -40:
                S.append(f"BANKNIFTY futures: {a2['sell_stack']} stacked sell · delta {a2['delta_pct']}% (big sellers)")
            if side == "UP" and a2.get("buy_stack", 0) >= 3 and a2.get("delta_pct", 0) >= 40:
                S.append(f"BANKNIFTY futures: {a2['buy_stack']} stacked buy · delta +{a2['delta_pct']}% (big buyers)")
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


def seed_day(now, hi, lo):
    """Day high / low from the deep scan (Angel OHLC) — so a restart at 11:00 still knows the 09:20 high."""
    try:
        hi, lo, dd = float(hi or 0), float(lo or 0), str(now.date())
    except (TypeError, ValueError):
        return
    if not (hi and lo and hi >= lo):
        return
    if DAY["date"] != dd:
        DAY.update(date=dd, hi=hi, lo=lo)
    else:
        DAY["hi"], DAY["lo"] = max(DAY["hi"] or hi, hi), min(DAY["lo"] or lo, lo)


# v143: 26 Nov — NIFTY went from red to +0.44 % (~100 pts off the low) and NOTHING alerted: the old rule needed the day to STILL be
# ≤ −0.4 % and a 0.6 % bounce. Now: the day's LOW was red (≤ −0.15 %), bounce ≥ 0.35 % and still rising → SHORT COVERING / TURNED UP.
TCFG = {"day_min": 0.15, "off": 0.35, "strong": 0.8, "reset": 0.2, "n15": 0.10}
TURN = {"side": None, "since": None, "off": None, "day": None, "text": None, "strong": False, "date": None}


def turn_check(items, now, send=None):
    """📉 v138 PROFIT-BOOKING / SHORT-COVERING detector — the move the speed radar misses:
    an UP day (NIFTY ≥ +0.4 %) that has fallen ≥ 0.6 % from its high and is still falling (15-min) → book / trail CE profits,
    no fresh CE, PE allowed even though the day is green. Mirror for a DOWN day bouncing ≥ 0.6 % off its low.
    Stays on until price gets back within 0.3 % of the high / low."""
    q = items.get("NIFTY") or {}
    cur, pct = q.get("ltp"), q.get("pct")
    if not cur or pct is None or not DAY.get("hi") or DAY.get("date") != str(now.date()):
        return TURN
    cur, pct = float(cur), float(pct)
    off_hi, off_lo = (cur / DAY["hi"] - 1) * 100, (cur / DAY["lo"] - 1) * 100
    n15 = _chg("NIFTY", now, 15)
    side = TURN["side"] if TURN.get("date") == str(now.date()) else None
    if side == "DOWN" and off_hi > -TCFG["reset"]:
        side = None
    if side == "UP" and off_lo < TCFG["reset"]:
        side = None
    new = None
    if side is None:
        pc = cur / (1 + pct / 100)
        hi_pct, lo_pct = (DAY["hi"] / pc - 1) * 100, (DAY["lo"] / pc - 1) * 100
        if hi_pct >= TCFG["day_min"] and off_hi <= -TCFG["off"] and n15 is not None and n15 <= -TCFG["n15"]:
            new = "DOWN"
        elif lo_pct <= -TCFG["day_min"] and off_lo >= TCFG["off"] and n15 is not None and n15 >= TCFG["n15"]:
            new = "UP"
    if new:
        side = new
        TURN.update(since=now.strftime("%H:%M"))
    if not side:
        TURN.update(side=None, text=None, strong=False, off=None, date=str(now.date()))
        return TURN
    off = off_hi if side == "DOWN" else off_lo
    strong = abs(off) >= TCFG["strong"]
    text = (f"📉 PROFIT BOOKING from the day high {DAY['hi']:,.0f} — NIFTY {off:+.2f}% off the high (day now {pct:+.2f}%). "
            f"Book / trail CE profits · no fresh CE · PE allowed." if side == "DOWN" else
            f"📈 SHORT COVERING from the day low {DAY['lo']:,.0f} — NIFTY {off:+.2f}% off the low (day now {pct:+.2f}%). "
            f"Book / trail PE profits · no fresh PE · CE allowed.")
    TURN.update(side=side, off=round(off, 2), day=round(pct, 2), text=text, strong=strong, date=str(now.date()))
    if new and send:
        try:
            send(text, f"turn|{now.strftime('%H%M')}", True)
        except Exception:
            pass
    return TURN


def tick(items, now, risk=None, fp=None, send=None, fp2=None):
    """tick_loop (2 sec) — இந்த function-ல் API call இல்லை, ஏற்கனவே வந்த prices மட்டும்."""
    for k in ("NIFTY", "BANKNIFTY"):
        if (items.get(k) or {}).get("ltp"):
            _push(k, now, float(items[k]["ltp"]))
    nx = (items.get("NIFTY") or {}).get("ltp")
    if nx:
        nx, dd = float(nx), str(now.date())
        if DAY["date"] != dd:
            DAY.update(date=dd, hi=nx, lo=nx)
        DAY["hi"], DAY["lo"] = max(DAY["hi"], nx), min(DAY["lo"], nx)
    if (items.get("INDIA VIX") or {}).get("ltp"):
        _push("VIX", now, float(items["INDIA VIX"]["ltp"]))
    if risk:
        if risk.get("dn") is not None:
            _push("breadth_dn", now, float(risk["dn"]))
        if risk.get("up") is not None:
            _push("breadth_up", now, float(risk["up"]))
    _dp = (items.get("NIFTY") or {}).get("pct")
    ev = evaluate(now, risk, fp, fp2, float(_dp) if _dp is not None else None)
    # v139: a warning stays on screen at least 15 min (it used to vanish as soon as one signal flickered off)
    if ev["level"] == "NONE" and STATE.get("level") != "NONE" and STATE.get("last_push") and (now - STATE["last_push"]).total_seconds() < 900 \
            and str(STATE["last_push"].date()) == str(now.date()):
        ev = {**ev, "level": "WATCH", "side": STATE["side"], "signals": [s for s in STATE["signals"] if "(earlier)" not in s] + ["(earlier) signals cooling — still careful"]}
    try:
        turn_check(items, now, send)
    except Exception:
        pass
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
