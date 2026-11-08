"""🎯 DSK — Daily Select Kit: ஒரு நாளைக்கு 1–3 high-quality opportunities மட்டும்.  EARLY WATCH → CONFIRMED ENTRY → EXIT

  Layers (எல்லாம் ஏற்கனவே உள்ள engines-ன் output மேல்):
   🏦 Institutional Activity Radar — futures OI buildup + volume ≥2× + call பக்கம் ஒத்துப்போகுதா
   🧠 Market Regime + Sector Strength — regime-க்கு பொருந்திய strategy family (Battle Lab) + sector % பக்கம்
   📈 Order Flow + Futures OI — OI buildup அர்த்தம் (Long Built Up / Short Covering …) + market திசை
   🤖 Boosted-stumps + Logistic ensemble (XGBoost / LightGBM மாதிரி gradient boosting — numpy-ல், library இல்லாம)
   🎯 Meta-labeling false-signal filter — முடிந்த calls-ல் train, WALK-FORWARD-ல் net லாபம் கூடினா மட்டும் பயன்படுத்தும்
   💰 Option premium — call-ன் strike (v87 strike selector score இருந்தா அதுவும்)
   🛑 Adaptive risk + No-Trade engine — தினசரி நஷ்டம் / 2 SL / volatile / நேரம் → புது entry இல்லை

  நேர்மை: 90% accuracy promise இல்லை. Walk-forward-ல் model உதவலைன்னா "model OFF — rules மட்டும்" என்று சொல்லும். Paper மட்டும்.
"""
import math
import time

import numpy as np
import pandas as pd

OPEN = ("OPEN", "T1 HIT", "T2 HIT", "T3 HIT", "T4 HIT")
CFG = {"max_day": 3, "min_score": 75, "unclear_score": 85, "day_loss": -5000, "max_sl": 2, "end": "14:30", "mcx_end": "22:30",
       "retrain_sec": 1800, "min_train": 60}
STATE = {"time": None, "picks": [], "watch": [], "notrade": [], "model": None, "risk": None, "log": []}
MODEL = {"t": 0, "m": None, "wf": None}


# ───────────────────────── features ─────────────────────────
def _fam(c):
    from .ailab import family
    return family(c)


def _cond(c):
    from .ailab import condition
    return condition(c)


FAMS = ["ICT / Liquidity", "VWAP / Mean-Rev", "ORB / Opening", "Trend / Momentum", "OI / Gamma", "News", "Mannan", "Chart pattern", "Other"]
CONDS = ["TRENDING", "SIDEWAYS", "VOLATILE", "UNKNOWN"]
INDEXES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY")
NAMES = ["CE", "time", "vol", "score", "grade", "pink", "spread", "index", "mcx"] + [f"fam:{f}" for f in FAMS] + [f"cond:{c}" for c in CONDS]


def feats(c):
    t = str(c.get("time") or "12:00")
    try:
        mins = int(t[:2]) * 60 + int(t[3:5])
    except Exception:
        mins = 720
    g = {"A": 1.0, "B": 0.5}.get(str(c.get("grade") or ""), 0.0)
    f, cd = _fam(c), _cond(c)
    sc = c.get("score")
    if sc is None:
        sc = float(c.get("stars") or 3) * 20
    return [1.0 if c.get("side") == "CE" else 0.0, (mins - 555) / 375, min(float(c.get("vol_ratio") or 0), 8) / 8,
            min(float(sc or 0), 100) / 100, g, 1.0 if c.get("pink") else 0.0,
            min(float(c.get("spread_pct") or 2), 5) / 5, 1.0 if c.get("symbol") in INDEXES else 0.0, 1.0 if c.get("exch") == "MCX" else 0.0] + \
           [1.0 if f == x else 0.0 for x in FAMS] + [1.0 if cd == x else 0.0 for x in CONDS]


def _net(c):
    try:
        from .ai import charges
        return (c.get("pnl_lot") or 0) - charges(c)
    except Exception:
        return c.get("pnl_lot") or 0


def dataset(calls):
    done = sorted([c for c in calls if not c.get("shadow") and c.get("status") not in OPEN and c.get("pnl_lot") is not None
                   and c.get("kind") not in ("PICK", "DSK")], key=lambda c: str(c.get("exit_time") or f"{c.get('date')} {c.get('time')}"))
    X = np.array([feats(c) for c in done], float) if done else np.zeros((0, len(NAMES)))
    net = np.array([_net(c) for c in done], float)
    return done, X, (net > 0).astype(float), net


# ───────────────────────── model: boosted stumps + logistic ─────────────────────────
def _sig(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


class Stumps:
    """Gradient boosting (logistic loss) — depth-1 trees. XGBoost-ன் அடிப்படை யோசனை, சின்ன அளவில்."""

    def fit(self, X, y, rounds=60, lr=0.25):
        p0 = min(max(y.mean(), 1e-3), 1 - 1e-3)
        self.base, self.trees = math.log(p0 / (1 - p0)), []
        F = np.full(len(y), self.base)
        for _ in range(rounds):
            p = _sig(F)
            g, h = y - p, np.maximum(p * (1 - p), 1e-6)
            best = None
            for j in range(X.shape[1]):
                col = X[:, j]
                for thr in np.unique(np.quantile(col, [0.2, 0.4, 0.5, 0.6, 0.8])):
                    L = col <= thr
                    if L.all() or not L.any():
                        continue
                    gl, gr, hl, hr = g[L].sum(), g[~L].sum(), h[L].sum(), h[~L].sum()
                    gain = gl * gl / (hl + 1) + gr * gr / (hr + 1)
                    if best is None or gain > best[0]:
                        best = (gain, j, thr, gl / (hl + 1), gr / (hr + 1))
            if best is None:
                break
            _, j, thr, vl, vr = best
            self.trees.append((j, thr, lr * vl, lr * vr))
            F += np.where(X[:, j] <= thr, lr * vl, lr * vr)
        return self

    def predict(self, X):
        F = np.full(len(X), self.base)
        for j, thr, vl, vr in self.trees:
            F += np.where(X[:, j] <= thr, vl, vr)
        return _sig(F)

    def importance(self):
        imp = {}
        for j, thr, vl, vr in self.trees:
            imp[NAMES[j]] = imp.get(NAMES[j], 0) + abs(vl - vr)
        return sorted(imp.items(), key=lambda x: -x[1])[:8]


class Logit:
    def fit(self, X, y, it=400, lr=0.3, l2=0.01):
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Z = (X - self.mu) / self.sd
        self.w, self.b = np.zeros(Z.shape[1]), 0.0
        for _ in range(it):
            p = _sig(Z @ self.w + self.b)
            self.w -= lr * (Z.T @ (p - y) / len(y) + l2 * self.w)
            self.b -= lr * (p - y).mean()
        return self

    def predict(self, X):
        return _sig(((X - self.mu) / self.sd) @ self.w + self.b)


class Ensemble:
    def fit(self, X, y):
        self.s, self.l = Stumps().fit(X, y), Logit().fit(X, y)
        return self

    def predict(self, X):
        return 0.6 * self.s.predict(X) + 0.4 * self.l.predict(X)


def _auc(y, p):
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return None
    r = pd.Series(np.r_[pos, neg]).rank().values
    return round((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)), 3)


def walk_forward(X, y, net, min_train=None):
    """Chronological: [0:k] train → அடுத்த chunk predict → முன்னேறு. எதிர்காலம் தெரியாம test (leak இல்லை)."""
    n = len(y)
    k0 = max(min_train or CFG["min_train"], int(n * 0.4))
    if n < k0 + 20:
        return {"ok": False, "why": f"முடிந்த calls {n} — walk-forward-க்கு குறைஞ்சது {k0 + 20} வேணும்"}
    step = max(15, n // 10)
    P, idx = [], []
    k = k0
    while k < n:
        m = Ensemble().fit(X[:k], y[:k])
        e = min(n, k + step)
        P += list(m.predict(X[k:e]))
        idx += list(range(k, e))
        k = e
    P, Y, N = np.array(P), y[idx], net[idx]
    base = {"n": len(Y), "win": round(Y.mean() * 100, 1), "avg": round(N.mean()), "net": round(N.sum())}
    rows = []
    for thr in (0.45, 0.5, 0.55, 0.6, 0.65, 0.7):
        s = P >= thr
        if s.sum() >= max(10, int(0.08 * len(Y))):
            rows.append({"thr": thr, "n": int(s.sum()), "win": round(Y[s].mean() * 100, 1), "avg": round(N[s].mean()), "net": round(N[s].sum())})
    best = max(rows, key=lambda r: r["avg"]) if rows else None
    useful = bool(best and best["avg"] > 0 and best["avg"] > base["avg"] + 100)
    return {"ok": True, "base": base, "rows": rows, "best": best, "useful": useful, "auc": _auc(Y, P), "folds": math.ceil((n - k0) / step),
            "why": (f"Walk-forward-ல் p ≥ {best['thr']} filter: avg ₹{best['avg']:+,}/call vs எல்லாம் ₹{base['avg']:+,} → model ON" if useful else
                    "Walk-forward-ல் model net லாபத்தை கூட்டல → model OFF (rules மட்டும்) — data கூடக்கூட தானா மறுபடி test ஆகும்")}


def model(calls, now_ts=None):
    if MODEL["m"] is not None and time.time() - MODEL["t"] < CFG["retrain_sec"]:
        return MODEL
    done, X, y, net = dataset(calls)
    wf = walk_forward(X, y, net)
    m = Ensemble().fit(X, y) if len(y) >= CFG["min_train"] else None
    MODEL.update(t=time.time(), m=m, wf=wf, n=len(y), imp=m.s.importance() if m else [])
    return MODEL


# ───────────────────────── live: candidates → score → no-trade → picks ─────────────────────────
def _sector_map(money):
    sym2sec, sec_pct = {}, {}
    for L in ((money or {}).get("ce") or [], (money or {}).get("pe") or []):
        for r in L:
            if r.get("symbol") and r.get("sector"):
                sym2sec[r["symbol"]] = r["sector"]
    for x in (money or {}).get("sectors") or []:
        nm = x.get("sector") or x.get("name")
        if nm is not None and x.get("pct") is not None:
            sec_pct[nm] = x["pct"]
    return sym2sec, sec_pct


def notrade(calls, now, risk, regime):
    """🛑 இன்று புது DSK entry வேண்டாம் என்பதற்கான காரணங்கள்."""
    day, hm = str(now.date()), now.strftime("%H:%M")
    today = [c for c in calls if c.get("date") == day and not c.get("shadow") and c.get("kind") != "PICK"]
    closed = [c for c in today if c.get("status") not in OPEN]
    net = sum(_net(c) for c in closed)
    dsk = [c for c in today if c.get("kind") == "DSK"]
    dsl = [c for c in dsk if c.get("status") == "SL HIT"]
    out = []
    if net <= CFG["day_loss"]:
        out.append(f"இன்றைய paper நஷ்டம் ₹{net:,.0f} ≤ ₹{CFG['day_loss']:,} — நிறுத்துங்க (revenge trade வேண்டாம்)")
    if len(dsl) >= CFG["max_sl"]:
        out.append(f"DSK-ல் இன்று {len(dsl)} SL — நாள் முடிஞ்சது")
    if regime == "VOLATILE" and abs((risk or {}).get("vel") or 0) >= 0.3:
        out.append("Market VOLATILE + வேகமான swing — புது entry ஆபத்து")
    return out, round(net), dsk


def _rank(c, ctx):
    """0–100 DSK score + ஒவ்வொரு layer-ன் பங்கு (explain)."""
    parts = []
    ce = c.get("side") == "CE"
    m, wf = ctx["model"], ctx["wf"] or {}
    p = None
    if m is not None:
        p = float(m.predict(np.array([feats(c)]))[0])
    if p is not None and wf.get("useful"):
        v = int(max(0, min(35, (p - 0.4) / 0.3 * 35)))
        parts.append(("🤖 ML ensemble", v, f"win வாய்ப்பு {p * 100:.0f}% (walk-forward ON)"))
    else:
        g = {"A": 22, "B": 14}.get(str(c.get("grade") or ""), 6)
        parts.append(("📋 Rule quality", g, f"Grade {c.get('grade') or '?'}" + (f" · model {p * 100:.0f}% (OFF)" if p is not None else "")))
    tag = ctx["oi"].get(c.get("symbol"), "")
    inst = (ce and tag in ("Long Built Up", "Short Covering")) or (not ce and tag in ("Short Built Up", "Long Unwinding"))
    vr = float(c.get("vol_ratio") or 0)
    v = (10 if inst else 0) + (8 if vr >= 3 else 5 if vr >= 2 else 0)
    parts.append(("🏦 Institutional", v, f"OI {tag or '–'} · volume {vr:.1f}×"))
    fam = _fam(c)
    fit = fam in (ctx["brain"].get("use") or [])
    parts.append(("🧠 Regime fit", 15 if fit else 0, f"{ctx['brain'].get('regime', '?')} → {fam}" + (" ✓" if fit else " (பொருந்தல)")))
    sec = ctx["sym2sec"].get(c.get("symbol"))
    sp = ctx["sec_pct"].get(sec) if sec else None
    sv = 10 if sp is not None and ((sp > 0.3) == ce) and abs(sp) > 0.3 else 0
    parts.append(("📊 Sector", sv, f"{sec or '–'} {sp:+.2f}%" if sp is not None else "sector data இல்லை"))
    d = ctx["dir"]
    dv = 10 if d and (d == "UP") == ce else 0 if not d else -15
    parts.append(("🧭 Market திசை", dv, {"UP": "⬆", "DOWN": "⬇"}.get(d, "↔") + (" ✓" if dv > 0 else " எதிர்" if dv < 0 else "")))
    pk = 10 if c.get("pink") else 0
    parts.append(("🩷 Proven", pk, "pink" if pk else "–"))
    sp_ = c.get("strike_pick") or {}
    ov = 5 if (c.get("spread_pct") or 9) <= 2 else 0
    parts.append(("💰 Premium", ov, f"spread {c.get('spread_pct')}%" + (f" · delta {sp_.get('delta')}" if sp_ else "")))
    return max(0, min(100, sum(x[1] for x in parts))), p, parts


def run(calls, full, now, risk=None, brain=None, live=True):
    """60 sec-க்கு ஒருமுறை. இன்றைய open calls → rank → CONFIRMED (stage ENTRY + score) → DSK call (max 3) · மற்றவை EARLY WATCH."""
    from .ailab import STATE as LAB
    M = model(calls)
    idx = {x.get("index"): x for x in (full or {}).get("index") or []}
    d = (risk or {}).get("dir")
    oi = {}
    for kind, xs in ((full or {}).get("oi_buildup") or {}).items():
        for x in xs:
            oi[x["symbol"]] = kind
    sym2sec, sec_pct = _sector_map((full or {}).get("money"))
    brain = brain or {}
    ctx = {"model": M["m"], "wf": M["wf"], "oi": oi, "brain": brain, "sym2sec": sym2sec, "sec_pct": sec_pct, "dir": d}
    day, hm = str(now.date()), now.strftime("%H:%M")
    nt, day_net, dsk_today = notrade(calls, now, risk, brain.get("regime"))
    unclear = not d
    need = CFG["unclear_score"] if unclear else CFG["min_score"]
    cands = [c for c in calls if c.get("date") == day and c.get("status") in ("OPEN",) and not c.get("shadow")
             and c.get("kind") not in ("DSK", "PICK") and not c.get("hold_until") and not c.get("hits") and c.get("exch") != "MCX"]
    rows = []
    for c in cands:
        sc, p, parts = _rank(c, ctx)
        act = c.get("action")
        st = "CONFIRMED" if act == "ENTRY" and sc >= need else "LATE" if act == "LATE" else "EARLY WATCH"
        rows.append({"id": c["id"], "symbol": c["symbol"], "side": c["side"], "strike": c.get("strike"), "expiry": c.get("expiry"), "source": c.get("source_label") or c.get("source"),
                     "entry": c.get("entry"), "sl": c.get("sl"), "targets": c.get("targets"), "ltp": c.get("ltp"), "lot": c.get("lot"), "time": c.get("time"),
                     "score": sc, "p": round(p, 3) if p is not None else None, "parts": parts, "stage": st, "token": c.get("token"), "exch": c.get("exch")})
    for r in (LAB.get("prebreak") or {}).get("rows") or []:
        if r["status"] in ("NEAR", "BREAKING") and r["score"] >= 70 and not any(x["symbol"] == r["symbol"] for x in rows):
            rows.append({"symbol": r["symbol"], "side": r["side"], "source": "🔭 Pre-Breakout", "score": r["score"], "stage": "EARLY WATCH",
                         "parts": [("🔭 Pre-breakout", r["score"], " · ".join(r["why"][:3]))], "level": r["level"], "ltp": r["ltp"], "time": hm})
    rows.sort(key=lambda r: (r["stage"] != "CONFIRMED", -r["score"]))
    made = []
    late_day = hm >= CFG["end"]
    if live and not nt and not late_day:
        from .calls import CALLS_LOCK, STORE
        with CALLS_LOCK:
            D = STORE.load()
            mine = [c for c in D["calls"].values() if c.get("date") == day and c.get("kind") == "DSK"]
            for r in [r for r in rows if r["stage"] == "CONFIRMED"]:
                if len(mine) >= CFG["max_day"] or any(x["symbol"] == r["symbol"] for x in mine):
                    continue
                base = D["calls"].get(r["id"])
                if not base or not base.get("ltp"):
                    continue
                e = float(base["ltp"])
                if e > float(base["entry"]) * 1.05 or e <= float(base["sl"]):
                    continue
                c2 = {k: v for k, v in base.items() if not k.startswith("_") and k not in ("pink_sent", "pink_block", "hits", "exit", "exit_time", "guide", "action")}
                c2.update(id=f"{day}|DSK|{base['symbol']}|{base.get('contract')}", kind="DSK", source="🎯 DSK", source_label="🎯 DSK",
                          time=now.strftime("%H:%M"), signal_time=str(now)[:19], entry=round(e, 2), status="OPEN", hits=[], pnl_lot=0, intraday=True,
                          dsk={"score": r["score"], "p": r["p"], "from": base["id"], "from_src": base.get("source"), "parts": r["parts"]})
                D["calls"][c2["id"]] = c2
                STORE.dirty = True
                mine.append(c2)
                made.append(c2["id"])
                STATE["log"].insert(0, {"time": hm, "symbol": r["symbol"], "result": f"✅ DSK CALL (score {r['score']})"})
    del STATE["log"][30:]
    closed = [c for c in dsk_today if c.get("status") not in OPEN]
    lossrun = 0
    for c in sorted(closed, key=lambda c: str(c.get("exit_time")), reverse=True):
        if _net(c) > 0:
            break
        lossrun += 1
    lots = 0 if (nt or lossrun >= 2) else 1
    STATE.update(time=now.strftime("%I:%M:%S %p"), picks=[r for r in rows if r["stage"] == "CONFIRMED"][:3], watch=[r for r in rows if r["stage"] != "CONFIRMED"][:8],
                 notrade=nt + ([f"{CFG['end']} பிறகு புது entry இல்லை"] if late_day else []), need=need, unclear=unclear, made=made,
                 risk={"lots": lots, "day_net": day_net, "lossrun": lossrun, "txt": "0 lot — இன்று paper-ல் மட்டும் பாருங்க" if lots == 0 else "1 lot · SL ≤ ₹2,500/lot"},
                 model={"wf": M["wf"], "n": M.get("n"), "imp": M.get("imp")})
    return STATE


def journal(calls):
    from .ailab import _st
    ds = [c for c in calls if c.get("kind") == "DSK" and not c.get("shadow")]
    ds.sort(key=lambda c: (c.get("date"), c.get("time")), reverse=True)
    closed = [c for c in ds if c.get("status") not in OPEN]
    return {"rows": ds[:100], "stats": _st(closed)}
