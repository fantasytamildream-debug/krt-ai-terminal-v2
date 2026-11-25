"""🧠 MARKET BEHAVIOUR BRAIN — "the market looks like THIS right now; in the past, when it looked like this, what happened next?"

Memory  : NIFTY + BANKNIFTY 5-minute candles of the last ~6 months (Angel), +1 day every evening → it learns every day.
Snapshot: every closed 5-min candle is described by 11 numbers —
            speed (5 / 15 / 30-min move) · today's % · gap · where price sits in today's range · distance from day high / low ·
            time of day · yesterday's % · BANKNIFTY vs NIFTY (banks leading?).
Outcome : what happened in the NEXT 60 minutes — further fall ≥0.3 %, rise ≥0.3 %, crash ≥0.8 %, rally ≥0.8 %, close-to-close move.
Answer  : the K most similar past moments (never the same day) → how often each outcome happened, shrunk toward the normal rate.
Learning: every evening it re-tests 4 ways of judging "similar" on the last 15 days (walk-forward, no peeking) and keeps the best;
          every 15 min its live answer is saved and checked 60 min later → track record. Probabilities from history, not promises.
"""
import math
import pickle
import threading
import time

import numpy as np
import pandas as pd

OTHER = {"NIFTY": "BANKNIFTY", "BANKNIFTY": "NIFTY", "FINNIFTY": "NIFTY", "SENSEX": "NIFTY"}
TOKS = {"NIFTY": ("NSE", "99926000"), "BANKNIFTY": ("NSE", "99926009"), "FINNIFTY": ("NSE", "99926037"), "SENSEX": ("BSE", "99919000")}
FEATS = ["r5", "r15", "r30", "dayp", "gap", "pos", "offhi", "offlo", "tod", "prevday", "bnf"]
WSETS = {
    "balanced": dict.fromkeys(FEATS, 1.0),
    "speed": {**dict.fromkeys(FEATS, 0.8), "r5": 2.0, "r15": 2.0, "r30": 1.5, "bnf": 1.2},
    "position": {**dict.fromkeys(FEATS, 0.8), "pos": 2.0, "offhi": 2.0, "offlo": 2.0, "dayp": 1.5},
    "time+trend": {**dict.fromkeys(FEATS, 0.8), "tod": 2.0, "dayp": 1.8, "gap": 1.5, "prevday": 1.3},
}
TH = {"move": 0.30, "big": 0.80, "net": 0.20}
M = {"hist": {}, "Z": {}, "tuned": {"wset": "balanced", "k": 60, "skill": None, "tested": None, "date": None}, "built": None, "err": None}
LOCK = threading.Lock()


def features(df, bnf=None):
    """df: 5-min OHLC (DatetimeIndex, one or many days). → DataFrame of FEATS + outcomes (NaN where the future is unknown)."""
    df = df.sort_index()
    df = df[(df.index.time >= pd.Timestamp("09:15").time()) & (df.index.time <= pd.Timestamp("15:25").time())]
    if df.empty:
        return pd.DataFrame()
    day = pd.Series(df.index.date, index=df.index)
    c, h, lo, o = df["close"], df["high"], df["low"], df["open"]
    dclose = c.groupby(day).last()
    prevc = dclose.shift(1)
    prevprev = dclose.shift(2)
    dopen = o.groupby(day).first()
    pc = day.map(prevc)
    out = pd.DataFrame(index=df.index)
    g = c.groupby(day)
    first_open = day.map(dopen)
    for n, k in (("r5", 1), ("r15", 3), ("r30", 6)):
        back = g.shift(k)
        out[n] = (c / back.fillna(first_open) - 1) * 100
    out["dayp"] = (c / pc - 1) * 100
    out["gap"] = (first_open / pc - 1) * 100
    hi = h.groupby(day).cummax()
    lw = lo.groupby(day).cummin()
    rng = (hi - lw).replace(0, np.nan)
    out["pos"] = ((c - lw) / rng).fillna(0.5)
    out["offhi"] = (c / hi - 1) * 100
    out["offlo"] = (c / lw - 1) * 100
    mins = (df.index.hour * 60 + df.index.minute + 5) - (9 * 60 + 15)
    out["tod"] = mins / 375.0
    out["prevday"] = day.map((prevc / prevprev - 1) * 100)
    if bnf is not None and len(bnf):
        b = bnf.sort_index()["close"].reindex(df.index).ffill()
        bday = pd.Series(b.index.date, index=b.index)
        out["bnf"] = (b / b.groupby(bday).shift(3).fillna(b.groupby(bday).transform("first")) - 1) * 100 - out["r15"]
    else:
        out["bnf"] = 0.0
    # outcomes over the next 12 bars of the SAME day
    fut_lo = pd.concat([lo.groupby(day).shift(-i) for i in range(1, 13)], axis=1).min(axis=1, skipna=True)
    fut_hi = pd.concat([h.groupby(day).shift(-i) for i in range(1, 13)], axis=1).max(axis=1, skipna=True)
    ahead = pd.concat([c.groupby(day).shift(-i).notna() for i in range(1, 13)], axis=1).sum(axis=1)
    c12 = pd.concat([c.groupby(day).shift(-i) for i in range(1, 13)], axis=1).ffill(axis=1).iloc[:, -1]
    ok = ahead >= 6
    out["maxdn"] = ((fut_lo / c - 1) * 100).where(ok)
    out["maxup"] = ((fut_hi / c - 1) * 100).where(ok)
    out["ret60"] = ((c12 / c - 1) * 100).where(ok)
    out["date"] = [str(x) for x in day.values]
    out["close"] = c
    return out.dropna(subset=["dayp"])


def _events(H):
    return {"fall": (H["maxdn"] <= -TH["move"]).values, "rise": (H["maxup"] >= TH["move"]).values,
            "crash": (H["maxdn"] <= -TH["big"]).values, "rally": (H["maxup"] >= TH["big"]).values,
            "dn": (H["ret60"] <= -TH["net"]).values, "up": (H["ret60"] >= TH["net"]).values}


def _z(H):
    mu = H[FEATS].mean()
    sd = H[FEATS].std().replace(0, 1).fillna(1)
    return mu, sd


def neighbours(H, Z, q, wset="balanced", k=60, before=None):
    """H: history with outcomes, Z: its standardised feature matrix, q: one feature row. → index of the k nearest (other days only)."""
    w = np.array([WSETS[wset][f] for f in FEATS])
    zq = ((q[FEATS].astype(float) - H.attrs["mu"]) / H.attrs["sd"]).values.astype("float32")
    mask = np.ones(len(H), bool) if before is None else (H["date"].values < before)
    d = np.sqrt((((Z - zq) ** 2) * w).sum(axis=1))
    d[~mask] = np.inf
    k = min(k, int(mask.sum()))
    if k <= 0:
        return np.array([], int)
    return np.argpartition(d, k - 1)[:k]


def answer(H, Z, q, wset="balanced", k=60, before=None, shrink=20):
    idx = neighbours(H, Z, q, wset, k, before)
    E = H.attrs["ev"]
    base = H.attrs["base"]
    out = {"n": int(len(idx))}
    for e in E:
        hits = int(E[e][idx].sum()) if len(idx) else 0
        out[e] = round((hits + shrink * base[e]) / (len(idx) + shrink) * 100)
    out["med60"] = round(float(np.median(H["ret60"].values[idx])), 2) if len(idx) else None
    out["base"] = {e: round(base[e] * 100) for e in base}
    return out


def prepare(H):
    H = H.dropna(subset=["maxdn", "maxup", "ret60"]).copy()
    mu, sd = _z(H)
    H.attrs["mu"], H.attrs["sd"] = mu, sd
    ev = _events(H)
    H.attrs["ev"] = ev
    H.attrs["base"] = {e: float(v.mean()) for e, v in ev.items()}
    Z = ((H[FEATS] - mu) / sd).values
    return H, Z


def tune(H, Z, days=15, step=2):
    """Walk-forward test of every way of judging 'similar' on the last `days` days (each day predicted only from earlier days).
    Score = log-loss on the 4 key events vs. just using the normal rate. Keeps the best — this is how the brain improves daily."""
    dates = sorted(set(H["date"]))
    test = dates[-days:] if len(dates) > days + 20 else []
    if not test:
        return M["tuned"]
    rows = [i for i in range(0, len(H), step) if H["date"].iat[i] in set(test)]
    keys = ("fall", "rise", "dn", "up")
    E, base = H.attrs["ev"], H.attrs["base"]

    def ll(p, y):
        p = min(0.98, max(0.02, p))
        return -(y * math.log(p) + (1 - y) * math.log(1 - p))
    res = {}
    for ws in WSETS:
        for k in (40, 80):
            s = 0.0
            for i in rows:
                a = answer(H, Z, H.iloc[i], ws, k, before=H["date"].iat[i])
                s += sum(ll(a[e] / 100, E[e][i]) for e in keys)
            res[(ws, k)] = s / max(1, len(rows))
    b = sum(ll(base[e], E[e][i]) for i in rows for e in keys) / max(1, len(rows))
    (ws, k), best = min(res.items(), key=lambda kv: kv[1])
    return {"wset": ws, "k": k, "skill": round((1 - best / b) * 100, 1) if b else None, "tested": len(rows), "days": len(test),
            "scores": {f"{a}/{kk}": round(v, 4) for (a, kk), v in res.items()}}


def build(store_dir, ag, now, log=print):
    """Load / refresh ~6 months of 5-min candles (cached on disk) → features → tune. Heavy: run in a background thread."""
    from pathlib import Path
    p = Path(store_dir) / "behav.pkl"
    raw = {}
    try:
        raw = pickle.loads(p.read_bytes()) if p.exists() else {}
    except Exception:
        raw = {}
    toks = {"NIFTY": ("NSE", "99926000"), "BANKNIFTY": ("NSE", "99926009"), "FINNIFTY": ("NSE", "99926037"), "SENSEX": ("BSE", "99919000")}
    end = now.normalize() - pd.Timedelta(minutes=1) if now.hour * 60 + now.minute < 15 * 60 + 35 else now
    for n, (ex, t) in toks.items():
        df = raw.get(n)
        start = (df.index.max() + pd.Timedelta(minutes=5)) if df is not None and len(df) else end - pd.Timedelta(days=180)
        start = max(start, end - pd.Timedelta(days=180))
        parts = [df] if df is not None else []
        # v136: NEWEST first, 30-day pieces, retry when Angel rate-limits (it returns an empty table) — v135 kept only the OLDEST
        # 40 days (May–July) and compared today with a July close → "day +7.20 %, gap +6.89 %"
        e = end
        while e > start:
            s = max(start, e - pd.Timedelta(days=30))
            x = None
            for attempt in range(3):
                try:
                    x = ag.candles(ex, t, "FIVE_MINUTE", s, e)
                except Exception as ex:
                    log(f"behaviour candles {n}: {ex}")
                    x = None
                if x is not None and len(x):
                    break
                time.sleep(2.5 * (attempt + 1))
            if x is not None and len(x):
                parts.append(x[["open", "high", "low", "close"]])
            e = s - pd.Timedelta(minutes=1)
        if parts:
            d = pd.concat(parts)
            d = d[~d.index.duplicated(keep="last")].sort_index()
            raw[n] = d[d.index >= end - pd.Timedelta(days=185)]
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(pickle.dumps(raw))
    except Exception:
        pass
    if "NIFTY" not in raw:
        M["err"] = "no candle history yet (Angel)"
        return False
    last = raw["NIFTY"].index.max()
    prev_wd = (end.normalize() - pd.offsets.BDay(1)) if end.hour * 60 + end.minute < 15 * 60 + 35 else end.normalize()
    M["fresh"] = bool(last.normalize() >= prev_wd - pd.Timedelta(days=3))        # holidays allowed
    M["last_day"] = str(last.date())
    hist = {}
    for n in toks:
        if n in raw:
            hist[n] = prepare(features(raw[n], raw.get(OTHER[n])))
    tuned = tune(*hist["NIFTY"])
    for n, (H, Z) in hist.items():                       # v140: keep RAM small — float32 matrix, no spare columns, raw = last 6 days only
        H2 = H.drop(columns=[c for c in ("close",) if c in H.columns])
        H2.attrs.update(H.attrs)
        hist[n] = (H2, Z.astype("float32"))
    raw = {n: d[d.index >= d.index.max().normalize() - pd.Timedelta(days=9)] for n, d in raw.items()}
    with LOCK:
        M["hist"] = hist
        M["raw"] = raw
        M["tuned"] = {**tuned, "date": str(now.date())}
        M["built"] = now.strftime("%d %b %H:%M")
        M["err"] = None
    return True


def _describe(q, name):
    t = []
    r15, r30, dayp = q["r15"], q["r30"], q["dayp"]
    if abs(r15) >= 0.25:
        t.append(f"fast {'fall' if r15 < 0 else 'rise'} ({r15:+.2f}% in 15 min)")
    elif abs(r30) >= 0.3:
        t.append(f"steady {'fall' if r30 < 0 else 'rise'} ({r30:+.2f}% in 30 min)")
    else:
        t.append("quiet last 30 min")
    t.append(f"day {dayp:+.2f}%")
    if q["pos"] <= 0.15:
        t.append("near the day LOW")
    elif q["pos"] >= 0.85:
        t.append("near the day HIGH")
    if abs(q["gap"]) >= 0.4:
        t.append(f"gap {'down' if q['gap'] < 0 else 'up'} {q['gap']:+.2f}%")
    m = q["tod"] * 375
    t.append("morning" if m < 90 else "midday" if m < 255 else "last 2 hours")
    if name == "NIFTY" and abs(q.get("bnf", 0)) >= 0.25:
        t.append(f"banks {'weaker' if q['bnf'] < 0 else 'stronger'} than NIFTY")
    return " · ".join(t)


def live(name, today_df, other_df=None, now=None, prev_close=None):
    """Today's 5-min candles → answer for the last CLOSED candle. prev_close (from the live index %) overrides history."""
    with LOCK:
        hist = M["hist"].get(name)
        raw = (M.get("raw") or {}).get(name)
        tuned = dict(M["tuned"])
    if hist is None or today_df is None or not len(today_df):
        return None
    H, Z = hist
    now = now or pd.Timestamp.now()
    td = today_df[today_df.index + pd.Timedelta(minutes=5) <= now]          # closed candles only
    if td.empty:
        return None
    pre = raw[raw.index.date < td.index[0].date()].tail(150) if raw is not None else None
    full = pd.concat([pre, td[["open", "high", "low", "close"]]]) if pre is not None else td
    oth = other_df
    if oth is not None and raw is not None:
        oraw = (M.get("raw") or {}).get(OTHER.get(name, "NIFTY"))
        if oraw is not None:
            oth = pd.concat([oraw[oraw.index.date < td.index[0].date()].tail(150), other_df[["open", "high", "low", "close"]]])
    F = features(full, oth)
    if F.empty:
        return None
    q = F.iloc[-1].copy()
    if prev_close:
        stale = pre is None or not len(pre) or (td.index[0].normalize() - pre.index.max().normalize()).days > 4
        q["dayp"] = (float(q["close"]) / prev_close - 1) * 100
        q["gap"] = (float(td["open"].iloc[0]) / prev_close - 1) * 100
        if stale:
            q["prevday"] = 0.0
    a = answer(H, Z, q, tuned["wset"], tuned["k"], before=str(td.index[0].date()))
    dn, up = a["dn"], a["up"]
    edge = dn - up
    if a["crash"] >= 2 * max(1, a["base"]["crash"]) and a["crash"] >= 15:
        v, c = "CRASH RISK", "#dc2626"
    elif a["rally"] >= 2 * max(1, a["base"]["rally"]) and a["rally"] >= 15:
        v, c = "RALLY CHANCE", "#16a34a"
    elif edge >= 12:
        v, c = "DOWN", "#ef4444"
    elif edge <= -12:
        v, c = "UP", "#22c55e"
    else:
        v, c = "MIXED", "#eab308"
    head = {"CRASH RISK": f"⚠ {name}: big fall risk — in similar past moments it fell another 0.8 %+ in {a['crash']}% of cases (normal {a['base']['crash']}%)",
            "RALLY CHANCE": f"🚀 {name}: big rise chance — in similar past moments it rose 0.8 %+ in {a['rally']}% of cases (normal {a['base']['rally']}%)",
            "DOWN": f"⬇ {name} more likely lower in the next hour — {dn}% fell vs {up}% rose in similar past moments",
            "UP": f"⬆ {name} more likely higher in the next hour — {up}% rose vs {dn}% fell in similar past moments",
            "MIXED": f"↔ {name}: no edge — similar past moments split {dn}% down / {up}% up. Don't force a trade."}[v]
    side = "PE" if v in ("DOWN", "CRASH RISK") else "CE" if v in ("UP", "RALLY CHANCE") else None
    feat = {k: round(float(q[k]), 3) for k in ("r5", "r15", "r30", "dayp", "pos", "gap") if k in q.index}
    return {"name": name, "bar": td.index[-1].strftime("%H:%M"), "verdict": v, "color": c, "head": head, "side": side, "feat": feat,
            "pattern": _describe(q, name), "p": a, "spot": round(float(q["close"]), 2), "wset": tuned["wset"], "k": tuned["k"]}


def track(ans, store, now, today_df, lock=None):
    """Save the NIFTY answer every 15 min; 60 min later check it against what really happened → track record."""
    import contextlib
    with (lock or contextlib.nullcontext()):
        d = store.load()
        L = d.setdefault("behav_log", [])
        slot = now.floor("15min").strftime("%Y-%m-%d %H:%M")
        if ans and ans.get("name") == "NIFTY" and now.hour * 60 + now.minute <= 14 * 60 + 25 and (not L or L[-1]["slot"] != slot):
            L.append({"slot": slot, "date": str(now.date()), "spot": ans["spot"], "v": ans["verdict"], "dn": ans["p"]["dn"], "up": ans["p"]["up"],
                      "fall": ans["p"]["fall"], "rise": ans["p"]["rise"], "status": "PENDING"})
            del L[:-800]
            store.dirty = True
        for p in L:
            if p["status"] != "PENDING":
                continue
            if p["date"] != str(now.date()):
                p["status"] = "EXPIRED"
                store.dirty = True
                continue
            t0 = pd.Timestamp(p["slot"])
            if (now - t0).total_seconds() < 62 * 60 or today_df is None:
                continue
            w = today_df[(today_df.index >= t0) & (today_df.index < t0 + pd.Timedelta(minutes=60))]
            if len(w) < 10:
                continue
            r = (float(w["close"].iloc[-1]) / p["spot"] - 1) * 100
            p.update(ret=round(r, 2), status="DONE", ok=(None if p["v"] == "MIXED" else
                                                         bool((r <= -TH["net"]) if p["v"] in ("DOWN", "CRASH RISK") else (r >= TH["net"]))),
                     wrong=(None if p["v"] == "MIXED" else bool((r >= TH["net"]) if p["v"] in ("DOWN", "CRASH RISK") else (r <= -TH["net"]))))
            store.dirty = True
        done = [p for p in L if p["status"] == "DONE" and p.get("ok") is not None]
    return {"n": len(done), "right": sum(1 for p in done if p["ok"]), "wrong": sum(1 for p in done if p.get("wrong")),
            "today": [p for p in L if p["date"] == str(now.date())][-30:]}
