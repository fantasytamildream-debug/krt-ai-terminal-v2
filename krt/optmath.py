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
