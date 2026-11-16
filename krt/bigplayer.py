"""🏦 BIG PLAYER ACCUMULATION RADAR — which F&O stocks big players look to be building positions in, and the CE / PE to watch.

Combines what the terminal already measures (no extra API calls):
  · Institutional OI flow  — fresh Long Built Up (price ↑ + OI ↑ → CE) / Short Built Up (price ↓ + OI ↑ → PE), OI change %, OI still rising
  · Volume                 — time-of-day relative volume
  · Pre-Breakout Radar     — tight range (volatility squeeze) close to a 20-day high / low = quiet accumulation before a move
  · Live market            — NIFTY direction + breadth must not be against the side
Stage: ACCUMULATING (OI building, price still quiet near the level) · BREAKING OUT (level breaking with volume) · LATE (already ran >3%).
Strike / plan: from the AI Lab ENTER list or an open call when one exists, else ATM.
Honest: OI + volume show that large positions are being built — they cannot prove WHO traded, and a breakout can fail.
"""
OPEN = ("OPEN", "T1 HIT", "T2 HIT")


def radar(oi_rows, prebreak_rows, enter_rows, calls, breadth=None, nifty_pct=None):
    pb = {r["symbol"]: r for r in prebreak_rows or []}
    en = {r["symbol"]: r for r in enter_rows or []}
    oc = {}
    for c in calls or []:
        if c.get("status") in OPEN and not c.get("shadow") and c.get("kind") != "PICK":
            oc.setdefault(c["symbol"], c)
    up, dn = breadth or (None, None)
    out = []
    for r in oi_rows or []:
        side = r.get("side")
        if r.get("kind") not in ("Long Built Up", "Short Built Up") or side not in ("CE", "PE"):
            continue                              # only FRESH positions (OI rising) — covering / unwinding is not accumulation
        sym = r["symbol"]
        sc, why = 30, [f"{r['kind']} (OI {r.get('oi_chg_pct') if r.get('oi_chg_pct') is not None else '?'}%)"]
        ocp = abs(r.get("oi_chg_pct") or 0)
        if ocp >= 5:
            sc += 15
            why.append("big OI addition")
        elif ocp >= 2:
            sc += 8
        if (r.get("accel") or 0) >= 0.5:
            sc += 10
            why.append("OI still rising now")
        elif r.get("accel") is not None and r["accel"] <= -0.5:
            sc -= 10
            why.append("OI starting to fall")
        vr = r.get("vr")
        if vr is not None:
            if vr >= 2.5:
                sc += 20
                why.append(f"volume {vr}×")
            elif vr >= 1.5:
                sc += 12
                why.append(f"volume {vr}×")
            elif vr < 1.0:
                sc -= 10
        pct = r.get("pct")
        late = pct is not None and abs(pct) > 3
        if pct is not None and 0.2 <= abs(pct) <= 2:
            sc += 10
            why.append(f"price only {pct:+.2f}% — still quiet")
        if late:
            sc -= 15
        bv = None
        try:
            from .bigvol import get as _bvget
            bv = _bvget(sym)
        except Exception:
            bv = None
        if bv and bv.get("spikes"):
            sp0 = bv["spikes"][0]
            if bv.get("bias") == side:
                sc += 20
                why.append(f"🐋 {bv['label']} (last {sp0['side']} {sp0['mult']}× at {sp0['time'][11:]})")
            elif bv.get("bias") and bv["bias"] != side:
                sc -= 20
                why.append(f"🐋 big-player volume on the OTHER side ({bv['label']})")
            elif "absorption" in (bv.get("label") or ""):
                sc += 8
                why.append("🐋 absorption spikes — big volume, price held")
        p = pb.get(sym)
        brk = False
        if p and p.get("side") == side:
            if p.get("status") == "BREAKING":
                sc += 20
                brk = True
                why.append(f"breaking {p.get('level')} now")
            elif p.get("status") in ("NEAR", "WATCH"):
                sc += 15
                why.append(f"squeezed near {p.get('level')} (pre-breakout)")
        against = False
        if nifty_pct is not None and ((side == "CE" and nifty_pct <= -0.4) or (side == "PE" and nifty_pct >= 0.4)):
            against = True
        if up and dn and ((side == "CE" and up < dn * 0.9) or (side == "PE" and dn < up * 0.9)):
            against = True
        if against:
            sc -= 15
            why.append("market against this side")
        sc = max(0, min(100, sc))
        stage = "LATE" if late else "BREAKING OUT" if brk else "ACCUMULATING"
        e, c = en.get(sym), oc.get(sym)
        plan = None
        if e and e.get("side") == side and e.get("strike"):
            plan = {k: e.get(k) for k in ("strike", "expiry", "entry", "sl", "targets", "lot", "token", "exch", "contract", "ltp")}
            plan["from"] = "AI Lab ENTER"
        elif c and c.get("side") == side:
            plan = {k: c.get(k) for k in ("strike", "expiry", "entry", "sl", "targets", "lot", "token", "exch", "contract", "ltp")}
            plan["from"] = c.get("source")
            plan["id"] = c["id"]
        lvl = (p or {}).get("level")
        if stage == "LATE":
            act = f"⏳ Already moved {pct:+.1f}% — don't chase; wait for a pullback near VWAP / the breakout level."
        elif against:
            act = f"🔴 Big players are building {side} positions, but the market is against it — watch only."
        elif sc >= 75:
            act = (f"🔥 Strong accumulation — {side} {('strike ' + format(plan['strike'], 'g')) if plan else 'ATM / 1 strike ITM'}"
                   + (f" on a 5-min close {'above' if side == 'CE' else 'below'} {lvl} with volume ≥1.5×" if lvl else " on the next volume push")
                   + (f" · SL ₹{plan['sl']}" if plan and plan.get("sl") else "") + ". High conviction — still keep the ₹2,500/lot risk rule.")
        elif sc >= 60:
            act = f"🟡 Building — keep on watch; take {side} only when it breaks{(' ' + str(lvl)) if lvl else ''} with volume."
        else:
            act = "⚪ Early / weak — not enough evidence yet."
        out.append({"symbol": sym, "side": side, "score": sc, "stage": stage, "why": why, "action": act, "plan": plan, "level": lvl,
                    "bigvol": (bv or {}).get("spikes", [])[:3],
                    "pct": pct, "vr": vr, "oi_chg_pct": r.get("oi_chg_pct"), "flow": r.get("flow"), "against": against})
    out.sort(key=lambda x: (x["stage"] == "LATE", x["against"], -x["score"]))
    return out[:15]
