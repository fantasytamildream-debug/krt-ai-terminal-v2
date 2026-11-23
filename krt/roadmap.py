"""🗺 LEVEL ROADMAP — "NIFTY is at 25,439. Chance it breaks 25,400 / 25,350 / 25,300 in the next 30 / 60 minutes?"

Method (transparent, no magic):
  1. Live volatility: 1-minute returns of the index over the last 60 minutes (live ticks, sampled every ~10 s).
     Not enough ticks yet (restart / early) → estimated from today's high–low range (expected range ≈ 1.6 σ √minutes).
  2. Probability that price TOUCHES a level within T minutes = first-passage probability of a random walk with drift
         P = Φ((−a − μT)/(σ√T)) + exp(−2μa/σ²) · Φ((−a + μT)/(σ√T))          (a = distance to the level, beyond a small 0.03 % buffer)
  3. Drift μ comes from the 🔮 prediction (UP / DOWN %), SHRUNK by that prediction's real measured direction accuracy —
     a 52 %-accurate prediction moves the numbers only a little; distance + live speed do most of the work.
  4. Levels = round numbers (NIFTY 50 / BANKNIFTY 100 …) tagged with what sits there: day high / low, option-chain OI walls,
     scan support / resistance.  Road map = the chain of next levels: "if 25,400 breaks → 25,350 (x %) → 25,300 (y %)".
  5. Every 15 minutes the NIFTY map is saved; 60 minutes later we check which levels were really touched → calibration table
     ("we said 60–80 % → actually touched z %"). Probabilities, not promises.
"""
import math
from collections import deque

import pandas as pd

STEP = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "SENSEX": 100}
H = {}                       # name → deque[(ts, px)]
DAY = {}                     # name → {"date", "hi", "lo"}
BUF = 0.03                   # % beyond the level that counts as a BREAK
SIG_FLOOR, SIG_CAP = 0.02, 0.25     # % per minute


def push(name, ts, px):
    if not px:
        return
    q = H.setdefault(name, deque(maxlen=1200))
    if not q or (ts - q[-1][0]).total_seconds() >= 10:
        q.append((ts, float(px)))
    while q and (ts - q[0][0]).total_seconds() > 150 * 60:
        q.popleft()
    d, dd = DAY.get(name), str(ts.date())
    if not d or d["date"] != dd:
        DAY[name] = {"date": dd, "hi": float(px), "lo": float(px)}
    else:
        d["hi"], d["lo"] = max(d["hi"], float(px)), min(d["lo"], float(px))


def seed_day(name, ts, hi, lo):
    try:
        hi, lo = float(hi or 0), float(lo or 0)
    except (TypeError, ValueError):
        return
    if not (hi and lo and hi >= lo):
        return
    d, dd = DAY.get(name), str(ts.date())
    if not d or d["date"] != dd:
        DAY[name] = {"date": dd, "hi": hi, "lo": lo}
    else:
        d["hi"], d["lo"] = max(d["hi"], hi), min(d["lo"], lo)


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def touch_prob(a_pct, mu, sig, T):
    """P(random walk with drift mu (%/min, signed TOWARD the level = positive) and vol sig (%/min) moves a_pct within T min)."""
    if a_pct <= 0:
        return 1.0
    if T <= 0 or sig <= 0:
        return 0.0
    s = sig * math.sqrt(T)
    m = -mu                                          # formula is written for a barrier BELOW with drift m
    try:
        p = _phi((-a_pct - m * T) / s) + math.exp(min(50.0, -2 * m * a_pct / sig ** 2)) * _phi((-a_pct + m * T) / s)
    except OverflowError:
        p = 1.0
    return max(0.0, min(1.0, p))


def sigma(name, now, day=None, spot=None):
    """→ (σ %/min, source text)."""
    q = [x for x in H.get(name) or [] if (now - x[0]).total_seconds() <= 60 * 60]
    if len(q) >= 40:
        s = pd.Series([p for _, p in q], index=[t for t, _ in q]).resample("1min").last().dropna()
        r = (s.pct_change().dropna() * 100)
        if len(r) >= 15:
            v = float(r.std())
            return max(SIG_FLOOR, min(SIG_CAP, v)), f"live 1-min moves, last {len(r)} min"
    d = day or DAY.get(name) or {}
    spot = spot or (q[-1][1] if q else None)
    mins = max(15.0, (now - now.normalize() - pd.Timedelta(hours=9, minutes=15)).total_seconds() / 60)
    if d.get("hi") and d.get("lo") and spot:
        rng = (d["hi"] - d["lo"]) / spot * 100
        v = rng / (1.6 * math.sqrt(min(mins, 375)))
        return max(SIG_FLOOR, min(SIG_CAP, v)), "estimated from today's high–low range"
    return 0.035, "default (no live data yet)"


def drift(pred, acc_pct):
    """Prediction → drift in σ units per √60 min, shrunk by measured accuracy. Returns (signed z, text)."""
    if not pred or pred.get("dir") not in ("UP", "DOWN") or not pred.get("prob"):
        return 0.0, "no direction bias"
    k = 0.0 if acc_pct is None else max(0.0, min(0.7, (acc_pct - 50) / 20))
    p = 0.5 + (pred["prob"] / 100 - 0.5) * k
    z = -math.sqrt(2) * _inv_erf(1 - 2 * p)          # Φ⁻¹(p)
    z = z if pred["dir"] == "UP" else -z
    return z, f"🔮 {pred['dir']} {pred['prob']}% × accuracy {acc_pct if acc_pct is not None else '–'}% → counted as {round(p * 100)}%"


def _inv_erf(y):
    y = max(-0.999999, min(0.999999, y))
    a = 0.147
    ln = math.log(1 - y * y)
    t = 2 / (math.pi * a) + ln / 2
    return math.copysign(math.sqrt(math.sqrt(t * t - ln / a) - t), y)


def momentum(name, now, sig):
    """30 % of the last 30-min trend (%/min), capped at ±0.15 σ per min — trend days keep some push, but most of it fades."""
    q = [x for x in H.get(name) or [] if (now - x[0]).total_seconds() <= 30 * 60]
    if len(q) < 60 or (q[-1][0] - q[0][0]).total_seconds() < 20 * 60:
        return 0.0, ""
    mins = (q[-1][0] - q[0][0]).total_seconds() / 60
    m = (q[-1][1] / q[0][1] - 1) * 100 / mins * 0.3
    m = max(-0.15 * sig, min(0.15 * sig, m))
    return m, f"last {mins:.0f}-min trend {(q[-1][1] / q[0][1] - 1) * 100:+.2f}% (30 % of it counted)"


def _walls(ix, spot):
    out = {}
    ch = ix.get("chain") or []
    if not ch:
        return out
    pe = sorted([r for r in ch if r.get("strike") and r["strike"] < spot and (r.get("PE") or {}).get("oi")], key=lambda r: -r["PE"]["oi"])[:2]
    ce = sorted([r for r in ch if r.get("strike") and r["strike"] > spot and (r.get("CE") or {}).get("oi")], key=lambda r: -r["CE"]["oi"])[:2]
    for r in pe:
        out.setdefault(float(r["strike"]), []).append(f"PE OI wall {r['PE']['oi'] / 1e5:.1f} L (put writers defend)")
    for r in ce:
        out.setdefault(float(r["strike"]), []).append(f"CE OI wall {r['CE']['oi'] / 1e5:.1f} L (call writers defend)")
    return out


def build(name, spot, now, ix=None, pred=None, acc_pct=None, n_down=4, n_up=3):
    if not spot:
        return None
    ix = ix or {}
    step = STEP.get(name, 50)
    d = DAY.get(name) or {}
    sig, sig_src = sigma(name, now, d, spot)
    z, drift_txt = drift(pred if name in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX") else None, acc_pct)
    close = now.normalize() + pd.Timedelta(hours=15, minutes=30)
    left = max(0.0, (close - now).total_seconds() / 60)
    mom, mom_txt = momentum(name, now, sig)
    mu_up = z * sig / math.sqrt(60) + mom            # %/min toward UP
    if mom_txt:
        drift_txt += " · " + mom_txt
    tags = _walls(ix, spot)
    for k, v in (("support", "scan support"), ("resistance", "scan resistance")):
        if ix.get(k):
            tags.setdefault(float(ix[k]), []).append(v)

    def lvl(L, up):
        a = abs(L / spot - 1) * 100 + BUF
        mu = mu_up if up else -mu_up
        T30, T60 = min(30, left), min(60, left)
        t = list(tags.get(float(L), []))
        if d.get("lo") and not up and abs(L - d["lo"]) <= step / 2:
            t.append(f"today's low {d['lo']:,.0f}")
        if d.get("hi") and up and abs(L - d["hi"]) <= step / 2:
            t.append(f"today's high {d['hi']:,.0f}")
        return {"level": L, "dir": "UP" if up else "DOWN", "dist": round(L - spot, 2), "dist_pct": round((L / spot - 1) * 100, 2),
                "p30": round(touch_prob(a, mu, sig, T30) * 100), "p60": round(touch_prob(a, mu, sig, T60) * 100), "tags": t}

    base_dn = math.floor(spot / step) * step
    if spot - base_dn < step * 0.05:
        base_dn -= step
    base_up = math.ceil(spot / step) * step
    if base_up - spot < step * 0.05:
        base_up += step
    down = [lvl(base_dn - i * step, False) for i in range(n_down)]
    up = [lvl(base_up + i * step, True) for i in range(n_up)]
    for side in (down, up):                          # road map: chance of the NEXT level once this one has broken (≈ half the time left)
        for i, r in enumerate(side):
            if i + 1 < len(side):
                nx = side[i + 1]["level"]
                a = abs(nx / r["level"] - 1) * 100 + BUF
                r["then"] = {"level": nx, "p": round(touch_prob(a, (mu_up if r["dir"] == "UP" else -mu_up), sig, min(30, left)) * 100)}
    key = next((r for r in down if r["p60"] < 80), down[-1]), next((r for r in up if r["p60"] < 80), up[-1])
    lines = []
    for side, word in ((down, "breaks"), (up, "crosses")):
        r0 = side[0]
        chain = " → ".join(f"{r['level']:,.0f} ({r['p60']}%)" for r in side)
        lines.append(f"{'⬇' if side is down else '⬆'} {chain}")
        if r0.get("then"):
            lines.append(f"IF {r0['level']:,.0f} {word} → next stop {r0['then']['level']:,.0f} (chance {r0['then']['p']}% after the break)")
    vd = verdict(down, up, mu_up, sig, name)
    sd60 = sig * math.sqrt(min(60, left) or 1)
    return {"name": name, "spot": round(spot, 2), "time": now.strftime("%H:%M:%S"), "down": down, "up": up, "lines": lines,
            "sigma": round(sig, 4), "sigma_src": sig_src, "drift": drift_txt, "range60": [round(spot * (1 - sd60 / 100), 0), round(spot * (1 + sd60 / 100), 0)],
            "day": d or None, "mins_left": round(left), "verdict": vd, "key_down": key[0]["level"], "key_up": key[1]["level"]}


def _f(x):
    return f"{x:,.0f}"


def verdict(down, up, mu_up, sig, name="NIFTY"):
    """ONE clear answer: which way, how far it will likely go, what would cancel it."""
    zz = mu_up * math.sqrt(60) / sig if sig else 0          # bias in σ-units over an hour
    if abs(zz) < 0.15:
        lo = next((r for r in down if r["p60"] < 50), down[-1])
        hi = next((r for r in up if r["p60"] < 50), up[-1])
        return {"dir": "RANGE", "head": f"↔ {name} likely stays between {_f(lo['level'])} and {_f(hi['level'])} for the next hour",
                "target": None, "next": None,
                "cancel": f"No clear side. Trade only a clean break: below {_f(lo['level'])} → PE · above {_f(hi['level'])} → CE.", "conf": None}
    dn = zz < 0
    side, other = (down, up) if dn else (up, down)
    sure = [r for r in side if r["p60"] >= 60]
    tgt = sure[-1] if sure else side[0]
    i = side.index(tgt)
    nxt = side[i + 1] if i + 1 < len(side) else None
    stop = next((r for r in other if r["p60"] < 50), other[-1])
    w = "falls" if dn else "rises"
    head = (f"{'⬇' if dn else '⬆'} {name} likely {w} to {_f(tgt['level'])} in the next hour ({tgt['p60']}% chance)" if sure else
            f"{'⬇' if dn else '⬆'} {name} leaning {'down' if dn else 'up'} — may test {_f(tgt['level'])} ({tgt['p60']}% chance)")
    return {"dir": "DOWN" if dn else "UP", "head": head, "target": tgt["level"], "conf": tgt["p60"],
            "next": (f"Only if {_f(tgt['level'])} {'breaks' if dn else 'is crossed'} → next {_f(nxt['level'])} ({nxt['p60']}% — not sure)" if nxt else None),
            "cancel": f"View wrong if {name} goes {'above' if dn else 'below'} {_f(stop['level'])} — then stop {'PE' if dn else 'CE'} trades."}


def track(rm, store, now, lock=None):
    """Save the NIFTY map every 15 min; 60 min later mark which levels were touched (from the live ticks we kept) → calibration."""
    if not rm or rm.get("name") != "NIFTY":
        return None
    import contextlib
    with (lock or contextlib.nullcontext()):
        d = store.load()
        L = d.setdefault("roadmap_log", [])
        slot = now.floor("15min").strftime("%Y-%m-%d %H:%M")
        if rm.get("mins_left", 0) >= 60 and (not L or L[-1]["slot"] != slot):
            L.append({"slot": slot, "date": str(now.date()), "spot": rm["spot"], "status": "PENDING",
                      "lv": [[r["level"], r["dir"], r["p60"]] for r in rm["down"] + rm["up"]]})
            del L[:-600]
            store.dirty = True
        q = H.get("NIFTY") or []
        for p in L:
            if p["status"] != "PENDING":
                continue
            t0 = pd.Timestamp(p["slot"])
            if p["date"] != str(now.date()):
                p["status"] = "EXPIRED"
                store.dirty = True
                continue
            if (now - t0).total_seconds() >= 60 * 60:
                win = [px for t, px in q if t0 <= t <= t0 + pd.Timedelta(minutes=60)]
                if len(win) < 60:                  # not enough ticks (restart in between) → can't judge honestly
                    p["status"] = "NO DATA"
                else:
                    lo, hi = min(win), max(win)
                    p["hit"] = [int((lo <= l * (1 - BUF / 100)) if dr == "DOWN" else (hi >= l * (1 + BUF / 100))) for l, dr, _ in p["lv"]]
                    p["status"] = "DONE"
                store.dirty = True
        done = [p for p in L if p["status"] == "DONE"]
    bins = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]
    cal = []
    for a, b in bins:
        xs = [h for p in done for (l, dr, pr), h in zip(p["lv"], p.get("hit") or []) if a <= pr < b]
        cal.append({"band": f"{a}–{min(b, 100)}%", "n": len(xs), "hit_pct": round(sum(xs) / len(xs) * 100) if xs else None})
    return {"maps": len(done), "cal": cal}
