"""👣 FOOTPRINT ORDER-FLOW STRATEGY — 1M / 3M footprint · RVOL · stacked diagonal imbalance · option filters · entry checklist.

⚠ நேர்மை: உண்மையான footprint-க்கு exchange tick-by-tick trades + aggressor side வேணும் — Angel One API அதை கொடுக்காது.
   இங்கே: ஒவ்வொரு 2 sec quote-ல் புது volume (Δ cumulative volume) → LTP ≥ best ask = BUY · ≤ best bid = SELL · இல்லைன்னா tick rule
   → price level வாரியா buy / sell → 1M / 3M footprint bars. இது *approximation* — tick data-வை விட கரடுமுரடு.

Initial parameters (உங்க numbers) — market / instrument / tick size / volatility-க்கு ஏத்த மாதிரி tuning table காட்டும்:
  footprint TF 1M / 3M · RVOL ≥ 1.5× · stacked imbalance ≥ 3 levels · imbalance ratio ≥ 3:1 · option delta 0.45–0.65 ·
  spread ≤ 1% of mid (tick-size exception: ≤ 2 ticks எப்போதும் OK) · RR ≥ 1:2 · max risk ₹2,500 / lot
"""
import math

import pandas as pd

CFG = {"tfs": [1, 3], "rvol": 1.5, "stack": 3, "ratio": 3.0, "delta_lo": 0.45, "delta_hi": 0.65, "spread_pct": 1.0, "spread_ticks": 2,
       "rr": 2.0, "max_risk": 2500, "start": "09:20", "end": "14:45", "max_day": 5, "n_stocks": 6, "min_lvl_vol": 1}
STATE = {"time": None, "universe": [], "bars": {}, "signals": [], "log": [], "err": None, "tune": None}
FP = {}                     # symbol → {"last": {...}, "tick", "step", "bars": {tf: {start: bar}}, "meta": {...}}


def tick_size(px, kind="EQ"):
    """NSE: options ₹0.05 · equity ₹250-க்கு கீழ் ₹0.01 (2025 revision) · மற்றவை ₹0.05 · index futures ₹0.05."""
    if kind == "OPT":
        return 0.05
    if kind == "EQ" and px and px < 250:
        return 0.01
    return 0.05


def step_for(px, tick):
    """Footprint price level அகலம் = tick-ன் multiple, ≈ price-ன் 0.03% (1 tick-ல் footprint பார்த்தா levels அர்த்தமில்லாம சிதறும்)."""
    raw = max(tick, (px or 0) * 0.0003)
    return round(max(tick, round(raw / tick) * tick), 4)


def spread_ok(bid, ask, tick=0.05):
    """Spread ≤ 1% of mid · அல்லது ≤ 2 ticks (₹3 premium-க்கு ₹0.05 = 1.7% — tick-size exception)."""
    if not bid or not ask or ask < bid:
        return False, None, "depth இல்லை"
    mid = (bid + ask) / 2
    sp = ask - bid
    pct = sp / mid * 100 if mid else 99
    ticks = round(sp / tick)
    if pct <= CFG["spread_pct"]:
        return True, round(pct, 2), f"spread {pct:.2f}% ✓"
    if ticks <= CFG["spread_ticks"]:
        return True, round(pct, 2), f"spread {pct:.2f}% ஆனா {ticks} tick தான் ✓ (tick-size exception)"
    return False, round(pct, 2), f"spread {pct:.2f}% ({ticks} ticks) — அதிகம்"


def _bucket(px, step):
    return round(math.floor(px / step) * step, 4)


def ingest(sym, q, now, kind="EQ"):
    """ஒரு quote (ltp, tradeVolume, depth) → footprint-ல் சேர்."""
    ltp = float(q.get("ltp") or 0)
    vol = float(q.get("tradeVolume") or q.get("volume") or 0)
    if not ltp:
        return
    d = q.get("depth") or {}
    bid = float(((d.get("buy") or [{}])[0] or {}).get("price") or 0) or None
    ask = float(((d.get("sell") or [{}])[0] or {}).get("price") or 0) or None
    S = FP.setdefault(sym, {"last": None, "tick": tick_size(ltp, kind), "bars": {tf: {} for tf in CFG["tfs"]}, "kind": kind, "day": str(now.date())})
    if S["day"] != str(now.date()):
        S.update(last=None, bars={tf: {} for tf in CFG["tfs"]}, day=str(now.date()))
    S["step"] = S.get("step") or step_for(ltp, S["tick"])
    prev = S["last"]
    S["last"] = {"ltp": ltp, "vol": vol, "bid": bid, "ask": ask, "side": (prev or {}).get("side", 0)}
    if not prev:
        return
    dv = vol - prev["vol"]
    if dv <= 0:
        return
    if ask and ltp >= ask:
        side = 1
    elif bid and ltp <= bid:
        side = -1
    elif ltp > prev["ltp"]:
        side = 1
    elif ltp < prev["ltp"]:
        side = -1
    else:
        side = prev.get("side") or 0
    S["last"]["side"] = side
    mins = now.hour * 60 + now.minute
    b_ = _bucket(ltp, S["step"])
    for tf in CFG["tfs"]:
        st = mins // tf * tf
        B = S["bars"][tf].setdefault(st, {"t": f"{st // 60:02d}:{st % 60:02d}", "o": ltp, "h": ltp, "l": ltp, "c": ltp, "vol": 0.0, "buy": 0.0, "sell": 0.0, "lv": {}})
        B["h"], B["l"], B["c"] = max(B["h"], ltp), min(B["l"], ltp), ltp
        B["vol"] += dv
        lv = B["lv"].setdefault(b_, [0.0, 0.0])              # [sell (bid) vol, buy (ask) vol]
        if side > 0:
            B["buy"] += dv
            lv[1] += dv
        elif side < 0:
            B["sell"] += dv
            lv[0] += dv
        else:
            B["buy"] += dv / 2
            B["sell"] += dv / 2
            lv[0] += dv / 2
            lv[1] += dv / 2
        for k in sorted(S["bars"][tf])[:-80]:
            S["bars"][tf].pop(k, None)


def analyze_bar(B, ratio=None, min_v=None):
    """Diagonal imbalance (standard footprint): level i-ன் ask (buy) vol ≥ ratio × level i−1-ன் bid (sell) vol → BUY imbalance;
    level i-ன் bid vol ≥ ratio × level i+1-ன் ask vol → SELL imbalance. Stacked = தொடர்ச்சியான levels."""
    ratio, min_v = ratio or CFG["ratio"], min_v if min_v is not None else CFG["min_lvl_vol"]
    ps = sorted(B["lv"])
    sell = [B["lv"][p][0] for p in ps]
    buy = [B["lv"][p][1] for p in ps]
    bi, si = [], []
    for i in range(len(ps)):
        below = sell[i - 1] if i > 0 else 0
        above = buy[i + 1] if i + 1 < len(ps) else 0
        bi.append(buy[i] >= min_v and buy[i] >= ratio * max(below, min_v * 0.5))
        si.append(sell[i] >= min_v and sell[i] >= ratio * max(above, min_v * 0.5))

    def run(flags):
        best = cur = 0
        lo_i = hi_i = None
        for i, f in enumerate(flags):
            cur = cur + 1 if f else 0
            if cur > best:
                best, hi_i, lo_i = cur, i, i - cur + 1
        return best, lo_i, hi_i
    bs, blo, bhi = run(bi)
    ss, slo, shi = run(si)
    delta = B["buy"] - B["sell"]
    tot = B["buy"] + B["sell"] or 1
    poc = ps[max(range(len(ps)), key=lambda i: buy[i] + sell[i])] if ps else None
    rng = (B["h"] - B["l"]) or 1e-9
    return {"buy_stack": bs, "sell_stack": ss, "buy_zone": [ps[blo], ps[bhi]] if bs else None, "sell_zone": [ps[slo], ps[shi]] if ss else None,
            "delta": round(delta), "delta_pct": round(delta / tot * 100, 1), "poc": poc, "close_pos": round((B["c"] - B["l"]) / rng, 2),
            "levels": [{"p": p, "s": round(sell[i]), "b": round(buy[i]), "bi": bi[i], "si": si[i]} for i, p in enumerate(ps)][::-1]}


def rvol(S, tf, start):
    done = [b["vol"] for k, b in sorted(S["bars"][tf].items()) if k < start][-20:]
    if len(done) < 5:
        return None
    base = sum(done) / len(done)
    return round(S["bars"][tf][start]["vol"] / base, 2) if base else None


def _vwap(S):
    bars = list(S["bars"][1].values())
    v = sum(b["vol"] for b in bars)
    return sum((b["h"] + b["l"] + b["c"]) / 3 * b["vol"] for b in bars) / v if v and len(bars) >= 10 else None


def checklist(side, an, rv, S, ctx):
    """CE (bullish) / PE (bearish) entry confirmation. mandatory = ★ — இவை எல்லாம் pass + மற்றவை-ல் 2+."""
    ce = side == "CE"
    px = S["last"]["ltp"]
    vw = _vwap(S)
    d = ctx.get("mdir")
    stk = an["buy_stack"] if ce else an["sell_stack"]
    opp = an["sell_stack"] if ce else an["buy_stack"]
    items = [
        ("★ Stacked imbalance ≥ " + str(CFG["stack"]) + f" levels ({'buy' if ce else 'sell'})", stk >= CFG["stack"], f"{stk} levels · ratio ≥ {CFG['ratio']}:1", True),
        (f"★ Relative volume ≥ {CFG['rvol']}×", rv is not None and rv >= CFG["rvol"], f"RVOL {rv if rv is not None else '– (5 bars வேணும்)'}", True),
        ("★ எதிர் பக்க stacked imbalance இல்லை", opp < CFG["stack"], f"{'sell' if ce else 'buy'} stack {opp}", True),
        (f"Bar delta {'+' if ce else '−'} (buyers / sellers control)", (an["delta"] > 0) == ce and an["delta"] != 0, f"delta {an['delta']:+} ({an['delta_pct']:+}%)", False),
        (f"Close bar-ன் {'மேல்' if ce else 'கீழ்'} பாதியில்", (an["close_pos"] >= 0.5) == ce, f"close position {an['close_pos']}", False),
        (f"Price VWAP-க்கு {'மேல்' if ce else 'கீழ்'}", vw is not None and ((px > vw) == ce), f"VWAP {round(vw, 2) if vw else '– (10 bars வேணும்)'}", False),
        ("Market திசை எதிர் இல்லை", not d or (d == "UP") == ce or S.get("kind") == "FUT_MCX", f"NIFTY {d or '↔'}", False),
        (f"நேரம் {CFG['start']}–{CFG['end']}", CFG["start"] <= ctx.get("hm", "00:00") <= CFG["end"], ctx.get("hm", ""), True)]
    mand = all(ok for _, ok, _, m in items if m)
    extra = sum(ok for _, ok, _, m in items if not m)
    return {"items": [{"name": n, "ok": bool(ok), "txt": t, "must": m} for n, ok, t, m in items], "pass": bool(mand and extra >= 2),
            "score": sum(ok for _, ok, _, _ in items), "of": len(items)}


def pick_option(ag, inst, name, side, spot, now, ul_sl, ul_tgts):
    """Delta 0.45–0.65 · spread ≤1% (tick exception) · RR ≥ 1:2 · risk ≤ ₹2,500 / lot — எல்லாம் pass ஆன best strike."""
    from .ailab import best_strike
    from .optmath import plan as _plan
    bs = best_strike(ag, inst, name, side, spot, now, ul_sl, ul_tgts[0], min_days=2, each=3)
    why, alt = [], None
    for o in bs.get("rows") or []:
        if not (CFG["delta_lo"] <= (o.get("delta") or 0) <= CFG["delta_hi"]):
            why.append(f"{o['strike']:g}: delta {o.get('delta')}")
            continue
        ok, pct, stx = spread_ok(o.get("bid"), o.get("ask"), 0.05)
        if not ok:
            why.append(f"{o['strike']:g}: {stx}")
            continue
        pl = _plan(o["ltp"], spot, o["strike"], o["expiry"], side, ul_sl, ul_tgts, now.to_pydatetime(), o["lot"])
        if not pl:
            continue
        risk = (pl["entry"] - pl["sl"]) * o["lot"]
        rr = (pl["targets"][0] - pl["entry"]) / (pl["entry"] - pl["sl"]) if pl["entry"] > pl["sl"] else 0
        if risk > CFG["max_risk"]:
            why.append(f"{o['strike']:g}: risk ₹{risk:,.0f} > ₹{CFG['max_risk']:,}")
            if not alt or risk < alt["risk"]:
                alt = {"strike": o["strike"], "side": side, "risk": round(risk), "entry": pl["entry"], "sl": pl["sl"], "targets": pl["targets"], "delta": o.get("delta")}
            continue
        if rr < CFG["rr"] * 0.9:
            why.append(f"{o['strike']:g}: RR {rr:.2f}")
            continue
        return {**o, "plan": pl, "risk": round(risk), "rr_opt": round(rr, 2), "spread_txt": stx}, why
    PICK_ALT["last"] = alt
    return None, why or ["strike இல்லை"]


PICK_ALT = {"last": None}


def universe(inst, now):
    """NIFTY + BANKNIFTY futures (index options-க்கு) + live volume அதிகமான 6 F&O stocks — 5 நிமிடத்துக்கு ஒருமுறை மாறும்."""
    from . import fullscan as FS
    U = []
    for ix in ("NIFTY", "BANKNIFTY"):
        f = (inst.get("fut") or {}).get(ix)
        if f:
            U.append({"symbol": ix, "token": f[0], "exch": f[3] if len(f) > 3 else "NFO", "kind": "FUT", "opt_name": ix})
    lq = FS.C.get("live_q") or {}
    eq = inst.get("eq") or {}
    top = sorted([s for s, q in lq.items() if s in eq and (q.get("vol_ratio") or 0) >= 1.2],
                 key=lambda s: -((lq[s].get("vol_ratio") or 0) * (1 + abs(lq[s].get("pct") or 0))))[:CFG["n_stocks"]]
    U += [{"symbol": s, "token": eq[s], "exch": "NSE", "kind": "EQ", "opt_name": s} for s in top]
    return U


def tokens():
    by = {}
    for u in STATE["universe"]:
        by.setdefault(u["exch"], []).append(u["token"])
    return by


def feed(qs, now):
    """tick_loop-ல் இருந்து (2 sec) — universe tokens-ன் quotes → ingest."""
    for u in STATE["universe"]:
        q = qs.get(u["token"])
        if q:
            ingest(u["symbol"], q, now, u["kind"])


def scan(ag, inst, now, calls, mdir=None):
    """60 sec-க்கு ஒருமுறை: ஒவ்வொரு symbol-ன் கடைசி *முடிந்த* 1M / 3M bar → checklist → pass ஆனா option filters → FOOTPRINT call."""
    from .calls import CALLS_LOCK, STORE, _new
    day, hm = str(now.date()), now.strftime("%H:%M")
    if not STATE.get("u_t") or (now - STATE["u_t"]).total_seconds() >= 300:
        STATE["universe"], STATE["u_t"] = universe(inst, now), now
    mins = now.hour * 60 + now.minute
    view, new_sig = {}, []
    for u in STATE["universe"]:
        S = FP.get(u["symbol"])
        if not S or not S.get("last"):
            continue
        for tf in CFG["tfs"]:
            done = [k for k in S["bars"][tf] if k + tf <= mins]
            if not done:
                continue
            k = max(done)
            B = S["bars"][tf][k]
            an = analyze_bar(B)
            rv = rvol(S, tf, k)
            view.setdefault(u["symbol"], {})[tf] = {"bar": {x: B[x] for x in ("t", "o", "h", "l", "c", "vol", "buy", "sell")}, "an": an, "rvol": rv,
                                                     "ck": {sd: checklist(sd, an, rv, S, {"mdir": mdir, "hm": hm}) for sd in ("CE", "PE")}}
            for side in ("CE", "PE"):
                ck = checklist(side, an, rv, S, {"mdir": mdir, "hm": hm})
                stk = an["buy_stack"] if side == "CE" else an["sell_stack"]
                if stk < CFG["stack"]:
                    continue
                key = f"{day}|{u['symbol']}|{tf}|{B['t']}|{side}"
                if any(x["key"] == key for x in STATE["signals"]):
                    continue
                sig = {"key": key, "date": day, "time": hm, "bar": B["t"], "tf": tf, "symbol": u["symbol"], "side": side, "px": S["last"]["ltp"],
                       "stack": stk, "rvol": rv, "delta_pct": an["delta_pct"], "check": ck, "pass": ck["pass"], "result": None, "call": None}
                new_sig.append((sig, u, an, S))
    STATE["bars"] = view
    with CALLS_LOCK:
        D = STORE.load()
        J = D.setdefault("fp_signals", [])
        mine = [c for c in (D.get("calls") or {}).values() if c.get("date") == day and c.get("kind") == "FOOTPRINT"]
        for sig, u, an, S in new_sig:
            if sig["pass"] and ag and len(mine) < CFG["max_day"] and not any(c["symbol"] == u["symbol"] for c in mine):
                ce = sig["side"] == "CE"
                zone = an["buy_zone"] if ce else an["sell_zone"]
                spot = S["last"]["ltp"]
                ul_sl = (zone[0] - S["step"]) if ce else (zone[1] + 2 * S["step"])
                r = abs(spot - ul_sl)
                tg = [spot + m * r for m in (2, 3, 4)] if ce else [spot - m * r for m in (2, 3, 4)]
                try:
                    o, why = pick_option(ag, inst, u["opt_name"], sig["side"], spot, now, ul_sl, tg)
                except Exception as e:
                    o, why = None, [str(e)[:80]]
                if not o and PICK_ALT.get("last"):
                    sig["alt"] = PICK_ALT["last"]
                    PICK_ALT["last"] = None
                if o:
                    pl = o["plan"]
                    rr_ = {"symbol": u["symbol"], "side": sig["side"], "price": spot, "sl": round(ul_sl, 2), "targets": [round(x, 2) for x in tg], "score": 70 + 5 * sig["check"]["score"],
                           "stars": 5, "vol_ratio": sig["rvol"], "reasons": [f"👣 {sig['tf']}M footprint: {sig['stack']} stacked {'buy' if ce else 'sell'} imbalance (≥{CFG['ratio']}:1) · RVOL {sig['rvol']}",
                                                                                 f"Option {o['strike']:g} {sig['side']} · δ {o.get('delta')} · {o['spread_txt']} · RR {o['rr_opt']} · risk ₹{o['risk']:,}"]}
                    opt = {"token": o["token"], "exch": o["exch"], "contract": o["contract"], "strike": o["strike"], "type": sig["side"], "expiry": o["expiry"], "lot": o["lot"],
                           "spread_pct": o.get("spread_pct"), "plan": dict(pl, money=False)}
                    c = _new("FOOTPRINT", "👣 Footprint", rr_, opt, now, day)
                    if c and c["id"] not in D["calls"] and not c.get("shadow"):
                        c.update(source_label="👣 Footprint", intraday=True, fp={k: sig[k] for k in ("tf", "bar", "stack", "rvol", "delta_pct")}, checklist=sig["check"]["items"])
                        D["calls"][c["id"]] = c
                        STORE.dirty = True
                        mine.append(c)
                        sig["call"] = {"id": c["id"], "strike": o["strike"], "entry": c.get("entry"), "sl": c.get("sl"), "targets": c.get("targets")}
                else:
                    sig["why_no"] = why[:4]
            STATE["signals"].insert(0, sig)
            J.append({k: sig[k] for k in ("key", "date", "time", "tf", "symbol", "side", "px", "stack", "rvol", "delta_pct", "pass")} | {"result": None})
            STORE.dirty = True
        for s in J:                                  # 15 நிமிடம் கழிச்சு underlying அந்த பக்கம் போச்சா → tuning-க்கு
            if s.get("result") is not None or s["date"] != day:
                continue
            t0 = pd.Timestamp(f"{s['date']} {s['time']}")
            if (now - t0).total_seconds() < 900:
                continue
            S = FP.get(s["symbol"])
            if not S or not S.get("last"):
                continue
            mv = (S["last"]["ltp"] / s["px"] - 1) * 100 * (1 if s["side"] == "CE" else -1)
            s["result"] = round(mv, 3)
        del J[:-2000]
    del STATE["signals"][60:]
    STATE["tune"] = tune(D.get("fp_signals") or [])
    STATE["time"] = now.strftime("%I:%M:%S %p")
    return STATE


def tune(J, win_mv=0.15):
    """Parameter tuning: ஒவ்வொரு signal-க்கும் 15 நிமிடத்தில் underlying ≥0.15% அந்த பக்கம் போனா WIN — எந்த threshold combination best?"""
    R = [s for s in J if s.get("result") is not None]
    if len(R) < 20:
        return {"n": len(R), "need": 20, "rows": [], "why": f"{len(R)}/20 signals-க்கு result வந்திருக்கு — 20 ஆனதும் tuning காட்டும்"}
    rows = []
    for st in (2, 3, 4):
        for rv in (1.2, 1.5, 2.0):
            X = [s for s in R if s["stack"] >= st and (s.get("rvol") or 0) >= rv]
            if len(X) >= 8:
                w = sum(s["result"] >= win_mv for s in X)
                rows.append({"stack": st, "rvol": rv, "n": len(X), "win": round(w / len(X) * 100), "avg_mv": round(sum(s["result"] for s in X) / len(X), 3)})
    rows.sort(key=lambda r: (-r["win"], -r["n"]))
    cur = next((r for r in rows if r["stack"] == CFG["stack"] and r["rvol"] == CFG["rvol"]), None)
    return {"n": len(R), "rows": rows[:9], "best": rows[0] if rows else None, "current": cur}


def report():
    from .calls import STORE
    D = STORE.load()
    day = max([s["date"] for s in STATE["signals"]] or [""])
    calls = sorted([c for c in (D.get("calls") or {}).values() if c.get("kind") == "FOOTPRINT" and not c.get("shadow")],
                   key=lambda c: (c.get("date"), c.get("time")), reverse=True)[:100]
    closed = [c for c in calls if c.get("status") not in ("OPEN", "T1 HIT", "T2 HIT", "T3 HIT")]
    w = sum((c.get("pnl_lot") or 0) > 0 for c in closed)
    return {"time": STATE["time"], "cfg": CFG, "universe": [u["symbol"] for u in STATE["universe"]], "bars": STATE["bars"], "signals": STATE["signals"][:40],
            "guide": guide(STATE["bars"], STATE["signals"]),
            "calls": calls, "stats": {"n": len(closed), "win": round(w / len(closed) * 100) if closed else None, "net": sum(c.get("pnl_lot") or 0 for c in closed)},
            "tune": STATE.get("tune"), "err": STATE.get("err")}



def guide(view, signals):
    """🎯 AI guide — ஒவ்வொரு symbol-க்கும் ஒரு தெளிவான முடிவு: ✅ BUY CE / PE (strike) · ⚠ setup சரி ஆனா strike filter · ⏳ WAIT (எது missing) · ⛔ setup இல்லை."""
    out = []
    for sym, tfs in (view or {}).items():
        best = None
        for tf, x in tfs.items():
            for sd, ck in (x.get("ck") or {}).items():
                if not best or (ck["pass"], ck["score"]) > (best[2]["pass"], best[2]["score"]):
                    best = (tf, sd, ck, x)
        if not best:
            continue
        tf, sd, ck, x = best
        an = x["an"]
        ce = sd == "CE"
        miss = [i["name"].replace("★ ", "") for i in ck["items"] if not i["ok"]]
        sig = next((g for g in signals or [] if g["symbol"] == sym and g["side"] == sd and g.get("pass")), None)
        flow = (f"{'Buyers' if ce else 'Sellers'} {an['buy_stack'] if ce else an['sell_stack']} levels-ல் தொடர்ந்து அழுத்துறாங்க (stacked imbalance) · "
                f"delta {an['delta_pct']:+}% · RVOL {x['rvol'] if x['rvol'] is not None else '–'}×")
        if ck["pass"] and sig and sig.get("call"):
            k, head = "BUY", f"✅ BUY {sym} {sig['call']['strike']:g} {sd} — call கொடுத்தாச்சு"
            plan = f"Entry ₹{sig['call']['entry']} · SL ₹{sig['call']['sl']} · T " + " / ".join(str(t) for t in sig['call'].get('targets') or [])
        elif ck["pass"] and sig and sig.get("alt"):
            a = sig["alt"]
            k, head = "RISK", f"⚠ {sd} setup சரி — ஆனா {a['strike']:g} {sd} 1 lot risk ₹{a['risk']:,} (உங்க limit ₹{CFG['max_risk']:,})"
            plan = f"எடுக்கணும்னா: Entry ₹{a['entry']} · SL ₹{a['sl']} · T1 ₹{(a['targets'] or [None])[0]} — பெரிய lot, risk அதிகம். Skip பண்றது நல்லது."
        elif ck["pass"]:
            k, head = "STRIKE", f"⚠ {sd} setup சரி — ஆனா filter-க்கு சரியான strike இல்லை"
            plan = " · ".join((sig or {}).get("why_no") or ["delta / spread / RR filter"])
        elif ck["score"] >= ck["of"] - 2:
            k, head = "WAIT", f"⏳ {sd} பக்கம் உருவாகுது — இன்னும் வேணும்: " + ", ".join(miss[:3])
            plan = "இவை வந்ததும் இங்கே ✅ ஆகும் (voice + notification)."
        else:
            k, head = "NONE", "⛔ இப்போ setup இல்லை"
            plan = "Stacked imbalance / volume போதல — காத்திருங்க."
        out.append({"symbol": sym, "side": sd, "tf": tf, "k": k, "head": head, "plan": plan, "flow": flow, "score": ck["score"], "of": ck["of"], "bar": x["bar"]["t"]})
    order = {"BUY": 0, "RISK": 1, "STRIKE": 2, "WAIT": 3, "NONE": 4}
    out.sort(key=lambda g: (order[g["k"]], -g["score"]))
    return out
