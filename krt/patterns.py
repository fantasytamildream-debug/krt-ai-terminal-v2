"""Daily chart pattern detection — pivots அடிப்படையில் (rule-based).
FORMING → NEAR BREAKOUT (2% அருகில்) → TRIGGERED (live LTP தாண்டியது) → CONFIRMED (daily close தாண்டியது).
Pattern = guaranteed direction இல்லை. Future candle பயன்படுத்தப்படவில்லை (pivot-க்கு 3 bar பின் தான் உறுதி)."""
import numpy as np

W = 3


def _piv(h, l):
    n = len(h)
    ph = [i for i in range(W, n - W) if h[i] == max(h[i - W:i + W + 1])]
    pl = [i for i in range(W, n - W) if l[i] == min(l[i - W:i + W + 1])]
    return _dd(ph), _dd(pl)


def _dd(idx):
    """அருகருகே உள்ள (சம மதிப்பு) pivots-ஐ ஒன்றாக்கு."""
    out = []
    for i in idx:
        if out and i - out[-1] <= W:
            out[-1] = i
        else:
            out.append(i)
    return out


def _line(idx, vals, at):
    k, b = np.polyfit(idx, vals, 1)
    return k, k * at + b


def detect(sym, bars, ltp, atr):
    h, l, c, v = (np.array(bars[k], dtype=float) for k in ("h", "l", "c", "v"))
    t = bars["t"]
    n = len(c)
    if n < 40 or not ltp:
        return []
    ph, pl = _piv(h, l)
    ph = [i for i in ph if i >= n - 60]
    pl = [i for i in pl if i >= n - 60]
    out = []
    vol_dry = bool(v[-5:].mean() < v[-25:-5].mean() * 0.85) if n > 25 else False

    def add(name, bias, level, inval, piv, height, note=""):
        level, inval = float(level), float(inval)
        if level <= 0:
            return
        ce = bias == "CE"
        dist = (level - ltp) / ltp * 100 if ce else (ltp - level) / ltp * 100
        closed_beyond = c[-1] > level if ce else c[-1] < level
        recent = (c[-6] <= level) if ce else (c[-6] >= level)
        failed = ltp < inval if ce else ltp > inval
        if failed:
            status = "FAILED"
        elif closed_beyond and recent:
            status = "CONFIRMED"
        elif closed_beyond:
            return  # பழைய breakout — fresh இல்லை
        elif dist < 0:
            status = "TRIGGERED"
        elif dist <= 2:
            status = "NEAR BREAKOUT"
        elif dist <= 6:
            status = "FORMING"
        else:
            return
        height = abs(height) or atr
        sgn = 1 if ce else -1
        tg = [round(level + sgn * height * m, 2) for m in (0.5, 1.0, 1.5)]
        sc = {"CONFIRMED": 35, "TRIGGERED": 30, "NEAR BREAKOUT": 28, "FORMING": 12, "FAILED": 0}[status]
        sc += 20 if vol_dry else 8
        sc += max(0, 25 - abs(dist) * 6)
        sc += {"Inverse Head & Shoulders": 20, "Head & Shoulders": 20, "Double Bottom": 16, "Double Top": 16,
               "Ascending Triangle": 18, "Descending Triangle": 18, "Bull Flag": 18, "Bear Flag": 18}.get(name, 12)
        out.append({"symbol": sym, "pattern": name, "timeframe": "Daily", "bias": f"{bias} WATCH", "side": bias,
                    "status": status, "level": round(level, 2), "invalidation": round(inval, 2),
                    "dist_pct": round(dist, 2), "targets": tg, "height": round(height, 2),
                    "pivots": [{"date": t[i], "price": round(float(p), 2)} for i, p in piv],
                    "vol_dry": vol_dry, "note": note, "score": int(min(100, sc)),
                    "confirm_rule": ("Daily close " + ("மேலே " if ce else "கீழே ") + f"{level:.2f}")})

    hs, ls = ph[-3:], pl[-3:]
    if len(hs) >= 2 and len(ls) >= 2:
        R = h[hs]
        if R.max() - R.min() <= 0.015 * R.mean() and all(l[ls[k]] < l[ls[k + 1]] for k in range(len(ls) - 1)):
            add("Ascending Triangle", "CE", R.max(), l[ls[-1]], [(i, h[i]) for i in hs] + [(i, l[i]) for i in ls],
                R.max() - l[ls[0]], "Flat resistance + higher lows")
        S = l[ls]
        if S.max() - S.min() <= 0.015 * S.mean() and all(h[hs[k]] > h[hs[k + 1]] for k in range(len(hs) - 1)):
            add("Descending Triangle", "PE", S.min(), h[hs[-1]], [(i, h[i]) for i in hs] + [(i, l[i]) for i in ls],
                h[hs[0]] - S.min(), "Flat support + lower highs")
    if len(ls) >= 2:
        a, b = ls[-2], ls[-1]
        if b - a >= 5 and abs(l[a] - l[b]) <= 0.02 * l[a]:
            neck = h[a:b + 1].max()
            if neck >= min(l[a], l[b]) * 1.04:
                add("Double Bottom", "CE", neck, min(l[a], l[b]), [(a, l[a]), (b, l[b])], neck - min(l[a], l[b]))
    if len(hs) >= 2:
        a, b = hs[-2], hs[-1]
        if b - a >= 5 and abs(h[a] - h[b]) <= 0.02 * h[a]:
            neck = l[a:b + 1].min()
            if neck <= max(h[a], h[b]) * 0.96:
                add("Double Top", "PE", neck, max(h[a], h[b]), [(a, h[a]), (b, h[b])], max(h[a], h[b]) - neck)
    if len(hs) >= 3:
        s1, hd, s2 = hs[-3:]
        if h[hd] > max(h[s1], h[s2]) * 1.03 and abs(h[s1] - h[s2]) <= 0.04 * h[s1]:
            t1, t2 = l[s1:hd + 1].min(), l[hd:s2 + 1].min()
            neck = (t1 + t2) / 2
            add("Head & Shoulders", "PE", neck, h[s2], [(s1, h[s1]), (hd, h[hd]), (s2, h[s2])], h[hd] - neck)
    if len(ls) >= 3:
        s1, hd, s2 = ls[-3:]
        if l[hd] < min(l[s1], l[s2]) * 0.97 and abs(l[s1] - l[s2]) <= 0.04 * l[s1]:
            t1, t2 = h[s1:hd + 1].max(), h[hd:s2 + 1].max()
            neck = (t1 + t2) / 2
            add("Inverse Head & Shoulders", "CE", neck, l[s2], [(s1, l[s1]), (hd, l[hd]), (s2, l[s2])], neck - l[hd])
    # Flags: கடைசி 15 bar-க்குள் pole, பின் 3–10 bar flag
    for end in range(n - 13, n - 3):
        st = max(0, end - 8)
        up = (c[end] - l[st:end].min()) / l[st:end].min()
        dn = (h[st:end].max() - c[end]) / h[st:end].max()
        fh, fl = h[end + 1:].max(), l[end + 1:].min()
        if up >= 0.08 and h[end:].argmax() == 0 and (h[end] - fl) <= 0.5 * (h[end] - l[st:end].min()):
            add("Bull Flag", "CE", fh, fl, [(end, h[end])], h[end] - l[st:end].min(), "Strong pole + tight pullback")
            break
        if dn >= 0.08 and l[end:].argmin() == 0 and (fh - l[end]) <= 0.5 * (h[st:end].max() - l[end]):
            add("Bear Flag", "PE", fl, fh, [(end, l[end])], h[st:end].max() - l[end], "Strong fall + weak bounce")
            break
    # Wedges
    if len(hs) >= 3 and len(ls) >= 3:
        kh, uh = _line(hs, h[hs], n - 1)
        kl, ul = _line(ls, l[ls], n - 1)
        if kh > 0 and kl > 0 and kl > kh * 1.2:
            add("Rising Wedge", "PE", ul, uh, [(i, h[i]) for i in hs] + [(i, l[i]) for i in ls], uh - ul)
        if kh < 0 and kl < 0 and kh < kl * 1.2:
            add("Falling Wedge", "CE", uh, ul, [(i, h[i]) for i in hs] + [(i, l[i]) for i in ls], uh - ul)
    # Tight range / rectangle (கடைசி 10 நாள்)
    top, bot = h[-10:].max(), l[-10:].min()
    if (top - bot) / c[-1] <= 0.05:
        add("Rectangle / Tight Range", "CE", top, bot, [], top - bot, "Range breakout watch")
        add("Rectangle / Tight Range", "PE", bot, top, [], top - bot, "Range breakdown watch")
    best = {}
    for p in out:  # ஒரு stock-க்கு ஒரு side-ல் சிறந்த pattern மட்டும்
        k = p["side"]
        if k not in best or p["score"] > best[k]["score"]:
            best[k] = p
    return list(best.values())
