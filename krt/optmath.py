"""Option premium ESTIMATE — Black-Scholes (IV-ஐ இப்போதைய premium-ல் இருந்து கணக்கிட்டு,
underlying SL / target விலையில் reprice). Fixed multiplier இல்லை. இது ESTIMATE மட்டும்."""
import math
import datetime as dt

R = 0.065


def _N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, sig, typ):
    if S <= 0 or K <= 0:
        return max(0.0, S - K) if typ == "CE" else max(0.0, K - S)
    if T <= 0 or sig <= 0:
        return max(0.0, S - K) if typ == "CE" else max(0.0, K - S)
    d1 = (math.log(S / K) + (R + sig * sig / 2) * T) / (sig * math.sqrt(T))
    d2 = d1 - sig * math.sqrt(T)
    if typ == "CE":
        return S * _N(d1) - K * math.exp(-R * T) * _N(d2)
    return K * math.exp(-R * T) * _N(-d2) - S * _N(-d1)


def iv(price, S, K, T, typ):
    lo, hi = 0.01, 4.0
    if price <= bs(S, K, T, lo, typ):
        return lo
    for _ in range(80):
        mid = (lo + hi) / 2
        if bs(S, K, T, mid, typ) > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def years_to_expiry(expiry_iso: str, now: dt.datetime) -> float:
    exp = dt.datetime.fromisoformat(expiry_iso) + dt.timedelta(hours=15, minutes=30)
    return max((exp - now).total_seconds(), 3600) / (365 * 86400)


def r05(x):
    return round(round(x / 0.05) * 0.05, 2)


def plan(prem, S, K, expiry, typ, ul_sl, ul_targets, now, lot, charges=150, cap=2500, hold_days=0, sl_days=None):
    """→ premium entry zone, SL, T1-T3, risk. ul_targets: underlying targets (3)."""
    if not prem or prem <= 0 or not S:
        return None
    T = years_to_expiry(expiry, now)
    sig = iv(prem, S, K, T, typ)
    # intraday: ~2 மணி நேரம்; swing: hold_days கழித்து (theta கணக்கில்)
    T2 = max(T - (2 / 24 + hold_days) / 365, 1 / (365 * 24))
    # SL பொதுவாக சீக்கிரம் வரும் → SL premium-க்கு குறைந்த நாள் theta (swing-ல் 2 நாள்)
    sd = hold_days if sl_days is None else sl_days
    Tsl = max(T - (2 / 24 + sd) / 365, 1 / (365 * 24))
    sl = r05(max(0.05, bs(ul_sl, K, Tsl, sig, typ)))
    tg = [r05(bs(t, K, T2, sig, typ)) for t in ul_targets]
    entry = r05(prem)
    if sl >= entry:
        sl = r05(entry * 0.8)
    sl = max(sl, r05(entry * 0.4))  # premium SL அதிகபட்சம் 60% நஷ்டம்
    risk = round((entry - sl) * lot + charges)
    return {"entry": entry, "entry_zone": [r05(entry * 0.99), r05(entry * 1.01)], "sl": sl,
            "targets": tg, "iv": round(sig * 100, 1), "risk": risk,
            "risk_ok": risk <= cap, "estimated": True}


def delta(S, K, T, sig, typ):
    if T <= 0 or sig <= 0 or S <= 0 or K <= 0:
        return 1.0 if (typ == "CE" and S > K) or (typ == "PE" and S < K) else 0.0
    d1 = (math.log(S / K) + (R + sig * sig / 2) * T) / (sig * math.sqrt(T))
    return _N(d1) if typ == "CE" else _N(d1) - 1


def greeks_from_price(prem, S, K, expiry_iso, typ, now):
    """IV, delta, 1-நாள் theta (premium-ல் %)."""
    T = years_to_expiry(expiry_iso, now)
    sig = iv(prem, S, K, T, typ)
    d = delta(S, K, T, sig, typ)
    t1 = max(T - 1 / 365, 1 / (365 * 24))
    theta_pct = (prem - bs(S, K, t1, sig, typ)) / prem * 100 if prem else 0
    return {"iv": round(sig * 100, 1), "delta": round(abs(d), 2), "theta_pct": round(theta_pct, 1)}


def solve_spot(target_prem, K, T, sig, typ, spot):
    """Premium target-ஐ அடைய underlying எவ்வளவு போகணும் (Black-Scholes inverse, bisection)."""
    lo, hi = (spot * 0.5, spot * 1.5)
    f = lambda S: bs(S, K, T, sig, typ) - target_prem
    if typ == "CE":
        if f(hi) < 0:
            return None
        a, b = spot, hi
    else:
        if f(lo) < 0:
            return None
        a, b = lo, spot
    for _ in range(60):
        m = (a + b) / 2
        fm = f(m)
        if typ == "CE":
            a, b = (m, b) if fm < 0 else (a, m)
        else:
            a, b = (a, m) if fm < 0 else (m, b)
    return (a + b) / 2


MONEY = {"mins": (1200, 3000, 6000)}   # per lot ₹ — config/settings.yaml-ல் மாற்றலாம்


def money_targets(plan, lot, spot, strike, expiry, typ, now, atr=None, intraday=True, mins=None):
    """Targets குறைந்தது T1 ₹1,200 / T2 ₹3,000 / T3 ₹6,000 per lot. ஒவ்வொரு target-க்கும் stock எவ்வளவு போகணும்,
    அது realistic-ஆ (intraday ≤0.8 ATR / holding ≤2 ATR) என்று check. Realistic இல்லைன்னா reward_ok = False."""
    if not plan or not plan.get("entry") or not lot or not spot or plan.get("money"):
        return plan
    mins = mins or MONEY["mins"]
    e = plan["entry"]
    old = list(plan.get("targets") or [])
    while len(old) < 3:
        old.append(old[-1] if old else e)
    import math as _m
    need = [round(_m.ceil(round((e + m / lot) / 0.05, 6)) * 0.05, 2) for m in mins]
    tg = [round(max(o, n), 2) for o, n in zip(old[:3], need)]
    for i in range(1, 3):
        if tg[i] <= tg[i - 1]:
            tg[i] = r05(tg[i - 1] + max(0.05, e * 0.05))
    try:
        T = years_to_expiry(expiry, now)
        sig = iv(e, spot, strike, T, typ)
        T2 = max(T - (3 / 24 if intraday else 3) / 365, 1 / (365 * 24))
        ul = [solve_spot(t, strike, T2, sig, typ, spot) for t in tg]
    except Exception:
        ul = [None, None, None]
    lim_atr = 0.8 if intraday else 2.0
    lim_pct = 1.5 if intraday else 5.0
    feas = []
    for S in ul:
        if S is None:
            feas.append(False)
        elif atr:
            feas.append(abs(S - spot) <= lim_atr * atr)
        else:
            feas.append(abs(S - spot) / spot * 100 <= lim_pct)
    plan.update(money=True, model_targets2=old[:3], targets=tg,
                target_rupees=[round((t - e) * lot) for t in tg],
                ul_needed=[round(S, 2) if S else None for S in ul],
                ul_move_atr=[round(abs(S - spot) / atr, 2) if (S and atr) else None for S in ul],
                ul_move_pct=[round(abs(S - spot) / spot * 100, 2) if S else None for S in ul],
                feasible=feas, reward_ok=bool(feas and feas[0]),
                rr_t2=round(((tg[1] - e) * lot) / max(plan.get("risk") or 1, 1), 2))
    return plan
