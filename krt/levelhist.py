"""📜 LEVEL HISTORY — 2 years of daily candles: which price zones really held, how often, and what happened after they broke.

Method (deterministic, daily CLOSED candles only):
  1. Swing highs / lows (fractal: 3 candles each side) → clustered into zones (within 0.5 × ATR(20)).
  2. Each time price came INTO a zone from one side = a TEST:
        HELD   price closed back away within 3 days, without a daily close beyond the zone
        BROKE  a daily close beyond the zone (by ≥ 0.25 ATR)
     After a BREAK: move over the next 5 days (in the break direction) and whether it FOLLOWED THROUGH (≥ 1 ATR further)
     or FAILED (closed back inside the zone within 3 days).
  3. Strength: STRONG = ≥3 tests and held ≥65% · WEAK = held ≤40% · else MEDIUM.
Output: the zones near today's price with their record + plain IF/THEN lines. History describes the past, it does not predict.
"""
import numpy as np
import pandas as pd


def _atr(d, n=20):
    h, l, c = d["high"], d["low"], d["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=5).mean()


def zones(d, k=3):
    a = float(_atr(d).iloc[-1] or 0) or float((d["high"] - d["low"]).mean())
    H, L = d["high"].values, d["low"].values
    pts = []
    for i in range(k, len(d) - k):
        if H[i] >= H[i - k:i + k + 1].max():
            pts.append(float(H[i]))
        if L[i] <= L[i - k:i + k + 1].min():
            pts.append(float(L[i]))
    pts.sort()
    Z = []
    for p in pts:
        if Z and p - Z[-1]["hi"] <= 0.5 * a:
            Z[-1]["hi"] = max(Z[-1]["hi"], p)
            Z[-1]["n"] += 1
        else:
            Z.append({"lo": p, "hi": p, "n": 1})
    for z in Z:
        pad = 0.15 * a
        z["lo"], z["hi"] = z["lo"] - pad, z["hi"] + pad
        z["mid"] = (z["lo"] + z["hi"]) / 2
    return Z, a


def record(d, z, a):
    """Walk the daily candles: every test of zone z → HELD / BROKE (+ what happened after)."""
    C, H, L, T = d["close"].values, d["high"].values, d["low"].values, d.index
    tests = []
    i, n = 1, len(d)
    while i < n:
        prev = C[i - 1]
        from_below = prev < z["lo"] and H[i] >= z["lo"]
        from_above = prev > z["hi"] and L[i] <= z["hi"]
        if not (from_below or from_above):
            i += 1
            continue
        up = from_below                                   # approaching resistance from below (else support from above)
        out, j_end = "HELD", min(n - 1, i + 3)
        for j in range(i, j_end + 1):
            if (up and C[j] > z["hi"] + 0.25 * a) or (not up and C[j] < z["lo"] - 0.25 * a):
                out = "BROKE"
                j_end = j
                break
        t = {"date": str(T[i].date()), "side": "resistance" if up else "support", "result": out}
        if out == "BROKE":
            k5 = min(n - 1, j_end + 5)
            mv = (C[k5] / C[j_end] - 1) * 100 if up else (C[j_end] / C[k5] - 1) * 100
            failed = any((C[x] < z["hi"]) if up else (C[x] > z["lo"]) for x in range(j_end + 1, min(n, j_end + 4)))
            far = (max(H[j_end:k5 + 1]) - C[j_end] if up else C[j_end] - min(L[j_end:k5 + 1])) >= a
            t.update(move5=round(float(mv), 2), follow=bool(far and not failed), failed=bool(failed))
        tests.append(t)
        i = j_end + 2
    return tests


def analyse(d, px=None, near_pct=8.0, top=6):
    if d is None or len(d) < 120:
        return None
    d = d.dropna()
    Z, a = zones(d)
    px = float(px or d["close"].iloc[-1])
    out = []
    for z in Z:
        if abs(z["mid"] - px) / px * 100 > near_pct:
            continue
        T = record(d, z, a)
        if not T:
            continue
        held = sum(1 for t in T if t["result"] == "HELD")
        br = [t for t in T if t["result"] == "BROKE"]
        hr = held / len(T)
        strength = "STRONG" if len(T) >= 3 and hr >= 0.65 else "WEAK" if hr <= 0.40 else "MEDIUM"
        role = "RESISTANCE" if z["lo"] > px else "SUPPORT" if z["hi"] < px else "PRICE IS INSIDE"
        fol = sum(1 for t in br if t.get("follow"))
        avg5 = round(float(np.mean([t["move5"] for t in br])), 2) if br else None
        out.append({"lo": round(z["lo"], 2), "hi": round(z["hi"], 2), "mid": round(z["mid"], 2), "role": role, "tests": len(T), "held": held,
                    "held_pct": round(hr * 100), "broke": len(br), "follow": fol, "failed": sum(1 for t in br if t.get("failed")), "avg5": avg5,
                    "strength": strength, "last": T[-1]["date"], "dist_pct": round((z["mid"] - px) / px * 100, 2), "log": T[-6:]})
    out.sort(key=lambda r: abs(r["dist_pct"]))
    out = out[:top]
    lines = []
    res = next((r for r in out if r["role"] == "RESISTANCE"), None)
    sup = next((r for r in out if r["role"] == "SUPPORT"), None)
    for r, up in ((res, True), (sup, False)):
        if not r:
            continue
        lv = r["hi"] if up else r["lo"]
        s = (f"{'Resistance' if up else 'Support'} {r['lo']:g}–{r['hi']:g} ({r['dist_pct']:+.1f}%): tested {r['tests']}× in 2 years, held {r['held']}× "
             f"({r['held_pct']}%) → {r['strength']}.")
        if r["broke"]:
            s += (f" When it broke ({r['broke']}×), price moved {r['avg5']:+.1f}% on average in the next 5 days; follow-through {r['follow']}/{r['broke']}, "
                  f"failed {r['failed']}/{r['broke']}.")
        s += (f" IF a daily close {'above' if up else 'below'} {lv:g} → {'upside' if up else 'downside'} opens (history: "
              f"{'reliable' if r['broke'] and r['follow'] / r['broke'] >= 0.6 else 'often fails — wait for a retest' if r['broke'] else 'never broken yet — first break is a big event'}).")
        lines.append(s)
    return {"px": round(px, 2), "atr": round(a, 2), "days": len(d), "from": str(d.index[0].date()), "to": str(d.index[-1].date()), "zones": out, "lines": lines}
