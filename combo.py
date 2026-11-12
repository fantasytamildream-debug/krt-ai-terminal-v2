"""🔥 COMBO — Liquidity Sweep + CHOCH + Volume + Candlestick + AI (15-method confluence)

CE (bullish): கடைசி 8 bars-ல் sell-side liquidity sweep (EQL sweep அல்லது swing low trap) → இப்போ CHOCH ⬆ (structure மாற்றம்)
   → sweep / CHOCH bars-ல் volume ≥ 1.5× (20 bar avg) → கடைசி 2 bars-ல் bullish candle (engulfing / hammer / morning star)
   → 15 methods confluence ≥ 60 → call. PE = mirror.
ஒவ்வொரு condition-ம் தனியா பலவீனம் — எல்லாம் ஒன்னா வரும்போது தான் call (அதனால் எண்ணிக்கை குறைவு, quality அதிகம்).
"""
import pandas as pd

CFG = {"sweep_bars": 8, "vol_x": 1.5, "min_conf": 60, "max_day": 4, "start": "09:30", "end": "14:30", "n_stocks": 10}
STATE = {"time": None, "rows": [], "log": [], "err": None}


def evaluate(df, side, mdir=None):
    """→ {"pass", "checks":[...], "a"} — df = 5-min OHLCV (volume உள்ளது: stock / futures)."""
    from .chartroom import analyse, candle_engine
    from .methods import run_all
    a = analyse(df)
    n = len(df)
    ce = side == "CE"
    want = "UP" if ce else "DOWN"
    lq = a.get("liquidity") or {}
    sw = [s for s in lq.get("sweeps") or [] if s["side"] == want and s["i"] >= n - CFG["sweep_bars"]]
    tp = a.get("trap") or {}
    trap_ok = tp and tp.get("side") == side and tp.get("i", -99) >= n - CFG["sweep_bars"]
    sweep_ok = bool(sw or trap_ok)
    sweep_i = (sw[-1]["i"] if sw else tp.get("i")) if sweep_ok else None
    ev = (a.get("structure") or {}).get("events") or []
    choch = any(e["type"].startswith("CHOCH") and e["side"] == want for e in ev)
    bos = any(e["type"].startswith("BOS") and e["side"] == want for e in ev)
    v = df["volume"].values
    base = float(v[-23:-3].mean()) if n > 25 else float(v.mean())
    seg = v[(sweep_i if sweep_i is not None else n - 3):]
    vx = float(seg.max() / base) if base and len(seg) else 0.0
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    cd = [x for x in candle_engine(o, h, l, c, a["atr"]) + candle_engine(o[:-1], h[:-1], l[:-1], c[:-1], a["atr"]) if x["side"] == want]
    M = run_all(df, a, side)
    a["methods"] = M
    checks = [("⚡ Liquidity sweep (கடைசி 8 bars)", sweep_ok, (sw[-1]["txt"] if sw else tp.get("txt", "")) if sweep_ok else "sweep இல்லை"),
              (f"🔄 CHOCH {'⬆' if ce else '⬇'} (structure மாற்றம்)", choch, "CHOCH ✓" if choch else ("BOS மட்டும் (continuation)" if bos else "structure மாற்றம் இல்லை")),
              (f"📊 Volume ≥ {CFG['vol_x']}×", vx >= CFG["vol_x"], f"{vx:.2f}× (sweep / CHOCH bars)"),
              ("🕯 Candle confirmation", bool(cd), ", ".join(x["name"] for x in cd) or "confirmation candle இல்லை"),
              (f"🤖 AI confluence ≥ {CFG['min_conf']}", M["score"] >= CFG["min_conf"], f"{M['score']}/100 · {len(M['pro'])} methods பக்கம்"),
              ("🧭 Market திசை எதிர் இல்லை", not mdir or (mdir == "UP") == ce, f"NIFTY {mdir or '↔'}")]
    return {"pass": all(x[1] for x in checks), "checks": [{"name": x[0], "ok": bool(x[1]), "txt": x[2]} for x in checks],
            "score": sum(bool(x[1]) for x in checks), "a": a, "vx": round(vx, 2), "conf": M["score"]}


def universe(inst):
    from . import fullscan as FS
    U = []
    for ix in ("NIFTY", "BANKNIFTY"):
        f = (inst.get("fut") or {}).get(ix)
        if f:
            U.append({"symbol": ix, "exch": f[3] if len(f) > 3 else "NFO", "token": f[0], "index": True})
    lq, eq = FS.C.get("live_q") or {}, inst.get("eq") or {}
    top = sorted([s for s, q in lq.items() if s in eq and (q.get("vol_ratio") or 0) >= 1.3],
                 key=lambda s: -((lq[s].get("vol_ratio") or 0) * (1 + abs(lq[s].get("pct") or 0))))[:CFG["n_stocks"]]
    return U + [{"symbol": s, "exch": "NSE", "token": eq[s], "index": False} for s in top]


def run(ag, inst, now, mdir=None):
    """Chart loop-ல் (5 நிமிடம்) — universe ஒவ்வொன்றுக்கும் 1 candle call. pass → option + plan → COMBO call (நாளைக்கு max 4)."""
    from . import fullscan as FS
    from . import v4 as V
    from .calls import CALLS_LOCK, STORE, _new
    day, hm = str(now.date()), now.strftime("%H:%M")
    rows = []
    for u in universe(inst):
        try:
            df = ag.candles(u["exch"], u["token"], "FIVE_MINUTE", now - pd.Timedelta(days=4), now)
        except Exception:
            continue
        if df is None or len(df) < 40 or float(df["volume"].tail(20).sum()) <= 0:
            continue
        for side in ("CE", "PE"):
            try:
                ev = evaluate(df, side, None if u["index"] else mdir)
            except Exception as e:
                STATE["err"] = str(e)[:120]
                continue
            if ev["score"] >= 4:
                rows.append({"symbol": u["symbol"], "side": side, "time": hm, "score": ev["score"], "conf": ev["conf"], "vx": ev["vx"], "pass": ev["pass"],
                             "checks": ev["checks"], "px": round(float(df["close"].iloc[-1]), 2), "index": u["index"], "_a": ev["a"]})
    rows.sort(key=lambda r: (not r["pass"], -r["score"], -r["conf"]))
    made = []
    if CFG["start"] <= hm <= CFG["end"] and ag:
        with CALLS_LOCK:
            D = STORE.load()
            mine = [c for c in D["calls"].values() if c.get("date") == day and c.get("kind") == "COMBO"]
        for r in [r for r in rows if r["pass"]]:
            if len(mine) >= CFG["max_day"] or any(c["symbol"] == r["symbol"] for c in mine):
                continue
            a = r["_a"]
            ce = r["side"] == "CE"
            ul_sl = (a.get("dn_level") if ce else a.get("up_level")) or (r["px"] * (0.994 if ce else 1.006))
            risk = abs(r["px"] - ul_sl) or r["px"] * 0.004
            tg = [round(r["px"] + (m * risk if ce else -m * risk), 2) for m in (1.5, 2.5, 3.5)]
            rr = {"symbol": r["symbol"], "side": r["side"], "price": r["px"], "sl": round(ul_sl, 2), "targets": tg, "score": 60 + 6 * r["score"], "stars": 5,
                  "vol_ratio": r["vx"], "reasons": ["🔥 " + " · ".join(f"{x['name'].split(' ', 1)[1]}: {x['txt']}" for x in r["checks"][:4]), f"AI confluence {r['conf']}/100"]}
            try:
                if r["index"]:
                    o, _ = V.pick_strike(ag, inst, r["symbol"], r["side"], r["px"], now)
                    if not o:
                        continue
                    pl, _ = V.option_plan(o, r["px"], ul_sl, V.settings())
                    if not pl:
                        continue
                    o = {**o, "plan": pl}
                else:
                    FS.pick_options(ag, inst, [rr])
                    o = rr.get("option") or {}
                    if not o.get("token"):
                        continue
                    FS.attach_plan(rr, o, now, "🔥 Combo")
                    o = rr.get("option") or o
            except Exception as e:
                STATE["log"].insert(0, {"time": hm, "symbol": r["symbol"], "result": f"⛔ option: {str(e)[:60]}"})
                continue
            with CALLS_LOCK:
                D = STORE.load()
                c = _new("COMBO", "🔥 Sweep+CHOCH+Candle", rr, o, now, day)
                if c and c["id"] not in D["calls"] and not c.get("shadow"):
                    c.update(source_label="🔥 Sweep+CHOCH+Candle", intraday=True, checklist=r["checks"])
                    D["calls"][c["id"]] = c
                    STORE.dirty = True
                    mine.append(c)
                    made.append(c["id"])
                    STATE["log"].insert(0, {"time": hm, "symbol": r["symbol"], "result": "✅ CALL"})
                else:
                    STATE["log"].insert(0, {"time": hm, "symbol": r["symbol"], "result": "⛔ quality gate / duplicate"})
    del STATE["log"][30:]
    STATE.update(time=now.strftime("%I:%M %p"), rows=[{k: v for k, v in r.items() if k != "_a"} for r in rows[:20]])
    return made
