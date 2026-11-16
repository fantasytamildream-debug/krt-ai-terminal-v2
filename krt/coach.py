"""🧭 AI COACH — one clear line for every pick / watch call: ENTER · JACKPOT · WAIT · HOLD · BOOK · EXIT · AVOID.

Rules (from your own results + the live market), no guessing:
  AVOID   live market check fails (breadth / NIFTY against, stock PE on a non-down day, volume <1.5×)
  WAIT    premium already >5% above entry (chasing) — wait for a pullback to the entry price
  JACKPOT entry still valid + volume ≥2.5× + buyers adding OI on the same side + premium rising now + proven module
          → "high conviction — up to 2× normal size, but never more than the ₹2,500/lot risk rule"
  ENTER   entry still valid, nothing against it
  HOLD / BOOK / EXIT for open trades: T1 hit → book half, SL to entry · gave back ≥40% of the gain from the high → exit ·
          premium fell to within 25% of the SL distance → exit early is allowed
Honest: confidence ≠ certainty — size by the SL, not by the label.
"""


def advise(c, mkt_why=None, oi_side=None, rising=None, proven=False):
    e, sl, ltp = c.get("entry") or 0, c.get("sl") or 0, c.get("ltp") or c.get("entry") or 0
    T = c.get("targets") or []
    hits = c.get("hits") or []
    hi = max(c.get("max_ltp") or 0, ltp)
    st = c.get("status")
    if st in ("T1 HIT", "T2 HIT") or hits:
        if T and len(T) > 1 and ltp >= T[1]:
            return {"tag": "BOOK", "txt": f"💰 T2 reached — book most of it; trail the rest with SL at T1 ₹{T[0]}."}
        return {"tag": "HOLD", "txt": f"✅ T1 done — keep half, SL at entry ₹{e} (risk-free now); next target ₹{T[1] if len(T) > 1 else T[0]}."}
    if st != "OPEN" or not e:
        return None
    if hi > e * 1.05 and ltp <= e + (hi - e) * 0.6 and ltp > e:
        return {"tag": "EXIT", "txt": f"🚪 Momentum fading — it gave back {round((hi - ltp) / (hi - e) * 100)}% of the gain from ₹{hi}. Book / exit near ₹{ltp}."}
    if sl and ltp <= sl + (e - sl) * 0.25:
        return {"tag": "EXIT", "txt": f"⚠ Close to SL ₹{sl} — exiting early at ₹{ltp} is allowed; don't average down."}
    if mkt_why:
        return {"tag": "AVOID", "txt": f"🔴 Avoid now — {mkt_why}."}
    if ltp > e * 1.05:
        return {"tag": "WAIT", "txt": f"⏳ Ran {round((ltp / e - 1) * 100)}% above entry — wait for a pullback to ≈₹{e}; don't chase."}
    vr = c.get("vol_ratio") or 0
    jack = vr >= 2.5 and oi_side == c.get("side") and (rising or {}).get("state") in ("RISING", "STRONG") and proven
    if jack:
        return {"tag": "JACKPOT", "txt": f"🔥 JACKPOT SETUP — volume {vr}×, buyers adding OI, premium rising now, proven module. High conviction: up to 2× "
                                         f"normal size, still within the ₹2,500/lot risk rule. Entry ₹{e} · SL ₹{sl}."}
    plus = [x for x in (f"volume {vr}×" if vr >= 2 else None, "buyers adding OI" if oi_side == c.get("side") else None,
                        "premium rising" if rising else None, "proven module" if proven else None) if x]
    return {"tag": "ENTER", "txt": f"✅ Entry OK at ₹{e} · SL ₹{sl}" + (f" · {', '.join(plus)}" if plus else "") + "."}
