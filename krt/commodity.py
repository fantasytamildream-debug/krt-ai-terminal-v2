"""🛢 KRT COMMODITY TRADE (MCX) — Gold · Silver · Crude Oil · Natural Gas · Copper · Zinc (+ mini contracts).
MCX நேரம் 9:00 – 23:30/23:55 முழுக்க ஓடும் (NSE close ஆனாலும்).
Strategy: V4 engine (🥈 ICT Silver Bullet + CQSMC + Order Flow + VWAP MR) MCX futures 1-min data-வில் + "Silver-grade" filter
(liquidity sweep / structure shift / displacement / FVG retest — 2+ வேணும்). Option = அதே commodity-ன் options on futures (ATM).
நேர்மை: lot multiplier (₹ P/L கணக்கு) MCX contract spec-ல் இருந்து எடுத்தது — உங்க broker contract note-ஓட ஒப்பிட்டு பாருங்க.
Paper / alert மட்டும். Order போகாது.
"""
import datetime as dt
import threading
import time

import pandas as pd

from . import v4 as V

# name: (P/L multiplier — ₹ per 1 point per lot, label)
COMM = {
    "CRUDEOIL": (100, "Crude Oil (100 bbl)"), "CRUDEOILM": (10, "Crude Oil Mini (10 bbl)"),
    "NATURALGAS": (1250, "Natural Gas (1250 mmBtu)"), "NATGASMINI": (250, "Natural Gas Mini (250 mmBtu)"),
    "GOLD": (100, "Gold (1 kg · ₹/10g)"), "GOLDM": (10, "Gold Mini (100 g)"),
    "SILVER": (30, "Silver (30 kg · ₹/kg)"), "SILVERM": (5, "Silver Mini (5 kg)"),
    "COPPER": (2500, "Copper (2500 kg)"), "ZINC": (5000, "Zinc (5000 kg)"),
}
CFG = {"watch": ["CRUDEOIL", "NATURALGAS", "GOLD", "SILVER", "COPPER", "ZINC"],
       "trade_mini": {"CRUDEOIL": "CRUDEOILM", "NATURALGAS": "NATGASMINI", "GOLD": "GOLDM", "SILVER": "SILVERM"},
       "open": "09:00", "last_entry": "23:00", "eod": "23:20", "close": "23:55",
       "silver_windows": [["10:00", "11:00"], ["14:30", "15:30"], ["19:00", "21:00"]],
       "min_score": 70, "lite_score": 60, "max_day": 10 ** 6, "risk_cap": 6000, "max_spread": 10.0}
STATE = {"time": None, "rows": [], "err": None, "beat": None, "jackpot": None, "ai": None}
CACHE = {}
FR = {}          # name → (time, frames)
LK = threading.Lock()


def mcx_open(t):
    hm = t.strftime("%H:%M")
    return t.weekday() < 5 and CFG["open"] <= hm <= CFG["close"]


def _fut(inst, name):
    return (inst.get("mcx_fut") or {}).get(name)


def frames(ag, name, fut, now):
    """MCX future 1-min: 5 நாள் history (நாளுக்கு ஒருமுறை) + இன்று incremental → V4 frames."""
    tok = fut[0]
    day = str(now.date())
    ch = CACHE.get(name)
    if not ch or ch["day"] != day or ch["hist"] is None or ch["hist"].empty:
        h = ag.candles("MCX", tok, "ONE_MINUTE", now - pd.Timedelta(days=6), now.normalize())
        if h is None or h.empty:
            time.sleep(1.5)                                    # Angel rate-limit → ஒருமுறை மறுபடி
            h = ag.candles("MCX", tok, "FIVE_MINUTE", now - pd.Timedelta(days=6), now.normalize())
        ch = CACHE[name] = {"day": day, "hist": h if h is not None else pd.DataFrame()}
    td = ag.candles("MCX", tok, "ONE_MINUTE", now.normalize() + pd.Timedelta(hours=9), now)
    if td is None or td.empty:
        time.sleep(1.5)
        td = ag.candles("MCX", tok, "ONE_MINUTE", now.normalize() + pd.Timedelta(hours=9), now)
    parts = [x for x in (ch["hist"], td) if x is not None and not x.empty]
    if not parts:
        return None
    m1 = pd.concat(parts)
    m1 = m1[~m1.index.duplicated(keep="last")].sort_index()
    m1 = m1[m1.index + pd.Timedelta(minutes=1) <= now]
    if m1.empty or m1.index[-1].date() != now.date():
        return None
    fr = {"1M": m1, "3M": V._resample(m1, "3min"), "5M": V._resample(m1, "5min"), "15M": V._resample(m1, "15min"),
          "1H": V._resample(m1, "60min")}
    if len(fr["5M"]) < 40:
        return None
    fr["5M"]["fvol"] = fr["5M"]["volume"]
    fr["has_vol"] = float(fr["5M"]["volume"].sum()) > 0
    fr["data_time"] = (m1.index[-1] + pd.Timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
    return fr


def s_mcx_momentum(fr, cx):
    """🔥 MCX Momentum Breakout: 15-min EMA20 vs EMA50 trend + VWAP side + கடைசி 1 மணி high/low-ஐ 5-min close-ல் உடைப்பு + volume ≥1.5×."""
    m5, m15 = fr["5M"], fr["15M"]
    if len(m5) < 30 or len(m15) < 55:
        return None
    e20, e50 = V.ema(m15["close"], 20).iloc[-1], V.ema(m15["close"], 50).iloc[-1]
    c = float(m5["close"].iloc[-1])
    hi12, lo12 = float(m5["high"].iloc[-13:-1].max()), float(m5["low"].iloc[-13:-1].min())
    v = m5["volume"]
    vx = float(v.iloc[-1] / v.iloc[-21:-1].mean()) if v.iloc[-21:-1].mean() else 0
    up = e20 > e50 and c > cx["vwap"]
    dn = e20 < e50 and c < cx["vwap"]
    side = "CE" if up else "PE" if dn else None
    if not side:
        return {"side": None, "stage": None}
    brk = c > hi12 if side == "CE" else c < lo12
    chk = {"15m EMA20/50 trend": True, "VWAP side": True, "1-hour high/low break (5m close)": brk, f"Volume {vx:.1f}× (≥1.5)": vx >= 1.5}
    n = sum(chk.values())
    stage = "CONFIRMED" if n == 4 else "READY" if n == 3 else "FORMING"
    return {"side": side, "stage": stage, "chk": chk, "spot_sl": round(lo12 if side == "CE" else hi12, 2),
            "buckets": {"trend": True, "volume": vx >= 1.5, "bos": brk, "liquidity": False}, "notes": [f"1h range {lo12}–{hi12}"]}


def silver_grade(cx, side):
    try:
        sw = V.sweep(cx["m3"], cx["levels"], look=20)
        st = cx["st3"]
        dp = V.displacement(cx["m3"], float(V.atr(cx["m3"]).iloc[-1] or 0))
        fv = [f for f in V.fvgs(cx["m3"], 20) if f["side"] == side]
        last = cx["m3"].iloc[-1]
    except Exception:
        return {}
    ce = side == "CE"
    return {"Liquidity sweep": bool(sw and sw["side"] == side),
            "Structure shift": bool((st.get("choch_up") or st.get("bos_up")) if ce else (st.get("choch_dn") or st.get("bos_dn"))),
            "Displacement": bool(dp and dp["side"] == side),
            "FVG retest": bool(fv and ((last["low"] <= fv[-1]["hi"] and last["close"] > fv[-1]["hi"]) if ce
                                       else (last["high"] >= fv[-1]["lo"] and last["close"] < fv[-1]["lo"])))}


def pick_option(ag, inst, name, side, fut_px, now):
    """அதே commodity options (மினி இருந்தா மினி) — ATM ±1 · spread ≤5% · ≥2 நாள் expiry."""
    tname = CFG["trade_mini"].get(name, name)
    for nm in (tname, name):
        rows = (inst.get("mcx_opt") or {}).get(nm) or []
        rows = [r for r in rows if r[4] == side and (dt.date.fromisoformat(r[2]) - now.date()).days >= 2]
        if not rows:
            continue
        exp = min(r[2] for r in rows)
        rows = [r for r in rows if r[2] == exp]
        ks = sorted({r[3] for r in rows})
        if ks and fut_px and (ks[len(ks) // 2] / fut_px > 20):        # strike ×100 சேமிப்பு fix
            rows = [[r[0], r[1], r[2], r[3] / 100, r[4], r[5], r[6]] for r in rows]
            ks = sorted({r[3] for r in rows})
        if not ks:
            continue
        atm = min(ks, key=lambda k: abs(k - fut_px))
        i = ks.index(atm)
        near = [k for k in ks[max(0, i - 1): i + 2]]
        cand = [r for r in rows if r[3] in near]
        qs = ag.quotes({"MCX": [r[0] for r in cand]}) or {}
        best = None
        for r in cand:
            q = qs.get(r[0]) or {}
            d = q.get("depth") or {}
            bid = float(((d.get("buy") or [{}])[0] or {}).get("price") or 0)
            ask = float(((d.get("sell") or [{}])[0] or {}).get("price") or 0)
            ltp = float(q.get("ltp") or 0)
            if not ltp:
                continue
            sp = round((ask - bid) / ask * 100, 2) if ask and bid else 99
            c = {"token": r[0], "contract": r[1], "expiry": r[2], "strike": r[3], "type": side, "exch": "MCX", "commodity": nm,
                 "mult": COMM.get(nm, (r[5] or 1,))[0], "ltp": ltp, "ask": ask or ltp, "bid": bid, "spread_pct": sp,
                 "oi": float(q.get("opnInterest") or 0), "moneyness": "ATM" if r[3] == atm else ("ITM" if (r[3] < atm) == (side == "CE") else "OTM")}
            if best is None or (c["spread_pct"], abs(r[3] - atm)) < (best["spread_pct"], abs(best["strike"] - atm)):
                best = c
        if best:
            return best
    return None


def plan(opt, fut_px, spot_sl):
    e = opt["ask"]
    srisk = abs(fut_px - spot_sl) if spot_sl else fut_px * 0.004
    r = min(max(0.5 * srisk, e * 0.08), e * 0.40)            # delta ≈0.5 · 8%–40% premium
    sl = round(e - r, 2)
    return {"entry": round(e, 2), "sl": sl, "targets": [round(e + k * r, 2) for k in (1, 2, 3)],
            "risk_rs": round(r * opt["mult"]), "t_rs": [round(k * r * opt["mult"]) for k in (1, 2, 3)]}


def scan(ag, inst, now):
    S = dict(V.settings(), silver_windows=CFG["silver_windows"])
    out = []
    for i_, name in enumerate(CFG["watch"]):
        if i_:
            time.sleep(1.2)                                         # Angel rate-limit: commodities இடையே இடைவெளி
        try:
            out.append(_scan_one(ag, inst, name, now, S))
        except Exception as e:
            out.append({"name": name, "label": COMM[name][1], "status": "ERROR", "error": str(e)[:100]})
    return out


def _scan_one(ag, inst, name, now, S):
    out = []
    if True:
        fut = _fut(inst, name)
        if not fut:
            return {"name": name, "label": COMM[name][1], "status": "NO CONTRACT"}
        try:
            fr = frames(ag, name, fut, now)
        except Exception as e:
            return {"name": name, "label": COMM[name][1], "status": "DATA ERROR", "error": str(e)[:80]}
        if not fr:
            return {"name": name, "label": COMM[name][1], "status": "NO DATA", "error": "இன்றைய candles இல்லை / Angel data வரல — அடுத்த scan-ல் மறுபடி"}
        FR[name] = (now, fr)               # 👑 Mannan Commodity இதையே பயன்படுத்தும்
        cx = V.context(fr, None, None)
        reg = V.regime(cx)
        res = {}
        for k_, fn in (("CQSMC", lambda: V.s_cqsmc(cx)), ("ORDERFLOW", lambda: V.s_orderflow(cx)), ("SILVER", lambda: V.s_silver(cx, now, S)),
                       ("VWAPMR", lambda: V.s_vwapmr(cx, reg)), ("MCXMOM", lambda: s_mcx_momentum(fr, cx))):
            try:
                res[k_] = fn()
            except Exception:
                res[k_] = None
        cands = []
        for k, r in res.items():
            if not r or not r.get("side") or not r.get("stage"):
                continue
            r = dict(r)
            sg = silver_grade(cx, r["side"])
            r.setdefault("chk", {}).update({f"Silver-grade: {a}": b for a, b in sg.items()})
            if k not in ("SILVER", "MCXMOM") and r["stage"] == "CONFIRMED" and (sum(sg.values()) < 2 or (reg == "SIDEWAYS" and k != "VWAPMR")):
                r["stage"] = "READY"
                r.setdefault("notes", []).insert(0, f"🥈 Silver-grade {sum(sg.values())}/4 (2 வேணும்)")
            r["strategy"], r["name"] = k, V.SNAME.get(k, "🔥 MCX Momentum Breakout")
            r["preferred"] = k in V.PREFERRED.get(reg, []) or k in ("SILVER", "MCXMOM")
            r["support"] = [k2 for k2, r2 in res.items() if k2 != k and r2 and r2.get("side") == r["side"] and r2.get("stage")]
            try:
                r["score"] = V.score(r, False, S)
            except Exception:
                r["score"] = 50
            if k == "MCXMOM":
                r["score"] = min(100, 45 + 12 * sum((r.get("chk") or {}).values()) + 5 * len(r["support"]))
            cands.append(r)
        rank = {"CONFIRMED": 3, "READY": 2, "FORMING": 1}
        cands.sort(key=lambda r: (rank.get(r["stage"], 0), r["preferred"], r["score"]), reverse=True)
        best = cands[0] if cands else None
        row = {"name": name, "label": COMM[name][1], "status": "OK", "px": round(cx["px"], 2), "vwap": round(cx["vwap"], 2),
               "atr": round(cx["atr"], 2), "pdh": cx.get("pdh"), "pdl": cx.get("pdl"), "regime": reg, "htf": cx.get("htf"),
               "data_time": fr["data_time"], "cands": [{k: c.get(k) for k in ("strategy", "name", "side", "stage", "score", "notes")} for c in cands[:4]],
               "best": None}
        if best:
            b = {k: best.get(k) for k in ("strategy", "name", "side", "stage", "score", "chk", "notes", "spot_sl", "support", "preferred")}
            if best["stage"] in ("READY", "CONFIRMED"):
                o = pick_option(ag, inst, name, best["side"], cx["px"], now)
                if o:
                    b["option"] = o
                    b["plan"] = plan(o, cx["px"], best.get("spot_sl"))
                    b["why_not"] = []
                    sgn = sum(1 for kk, vv in (b.get("chk") or {}).items() if kk.startswith("Silver-grade") and vv)
                    b["lite"] = best["stage"] == "READY" and b["score"] >= CFG["lite_score"] and (sgn >= 2 or best["strategy"] == "MCXMOM")
                    if best["stage"] != "CONFIRMED" and not b["lite"]:
                        b["why_not"].append("Stage READY — CONFIRMED (அல்லது READY + Silver-grade 2) ஆகணும்")
                    if b["score"] < (CFG["lite_score"] if b["lite"] else CFG["min_score"]):
                        b["why_not"].append(f"Score {b['score']} < {CFG['lite_score'] if b['lite'] else CFG['min_score']}")
                    if o["spread_pct"] > CFG["max_spread"]:
                        b["why_not"].append(f"Spread {o['spread_pct']}%")
                    if b["plan"]["risk_rs"] > CFG["risk_cap"]:                   # v107: warning only — big MCX lots blocked every call
                        b["risk_warn"] = f"⚠ risk ₹{b['plan']['risk_rs']:,}/lot (> ₹{CFG['risk_cap']:,}) — use the mini contract or smaller size"
                    b["ok"] = not b["why_not"]
            row["best"] = b
        return row


def ai_choice(rows):
    """🤖 AI choice: CONFIRMED + preferred + support அதிகம் + risk குறைவு + score → ஒன்று. Jackpot = score ≥85 + ok."""
    try:
        from .ai import feats, predict
    except Exception:
        feats = predict = None
    best = None
    for r in rows:
        b = r.get("best") or {}
        if not b.get("option") or not b.get("plan"):
            continue
        p = None
        if predict:
            p, _ = predict(feats("🛢 Commodity", b["side"], dt.datetime.now().strftime("%H:%M"), score=b["score"], symbol=r["name"]))
        k = (int(bool(b.get("ok"))), int(b["stage"] == "CONFIRMED"), int(bool(b.get("preferred"))), len(b.get("support") or []),
             p or 0, b["score"], -b["plan"]["risk_rs"])
        if best is None or k > best[0]:
            best = (k, r, p)
    if not best:
        return None, None
    r, p = best[1], best[2]
    ch = {"name": r["name"], "label": r["label"], "side": r["best"]["side"], "strategy": r["best"]["name"], "score": r["best"]["score"],
          "option": r["best"]["option"], "plan": r["best"]["plan"], "ok": r["best"].get("ok"), "p": p,
          "why": [f"{r['best']['stage']} · {r['regime']}", f"Support: {', '.join(r['best'].get('support') or []) or '–'}"]}
    jp = ch if (ch["ok"] and ch["score"] >= 85) else None
    return ch, jp


def to_calls(rows, now):
    """CONFIRMED + ok → paper call (kind MCX). commodity-க்கு 2 மணி நேரத்துக்கு ஒன்று · நாளைக்கு max 8."""
    from .calls import CALLS_LOCK, STORE, _new, tg
    hm = now.strftime("%H:%M")
    if hm > CFG["last_entry"] or hm < "09:15":
        return 0
    n = 0
    day = str(now.date())
    with CALLS_LOCK:
        d = STORE.load()
        mine = [x for x in d["calls"].values() if x["date"] == day and x["kind"] == "MCX"]
        for r in rows:
            b = r.get("best") or {}
            if not (b.get("ok") and (b.get("stage") == "CONFIRMED" or b.get("lite"))):
                continue
            if len(mine) >= CFG["max_day"]:
                break
            if any(x["symbol"] == r["name"] and (now - pd.Timestamp(x["signal_time"])).total_seconds() < 7200 for x in mine):
                continue
            o, p = b["option"], b["plan"]
            opt = {"token": o["token"], "exch": "MCX", "contract": o["contract"], "strike": o["strike"], "type": b["side"],
                   "expiry": o["expiry"], "lot": o["mult"],
                   "plan": {"entry": p["entry"], "sl": p["sl"], "targets": p["targets"], "risk": p["risk_rs"], "risk_ok": True,
                            "money": True, "reward_ok": True, "v4": True}}
            rr = {"symbol": r["name"], "price": r["px"], "sl": b.get("spot_sl"), "targets": [], "stars": 5, "score": b["score"],
                  "confidence": f"{b['name']} · score {b['score']}", "reasons": [f"🛢 {r['label']}", f"{b['name']} {b['stage']} · {r['regime']}"]
                  + [f"✓ {k}" for k, v in (b.get("chk") or {}).items() if v][:6]}
            c = _new("MCX", f"🛢 {b['name']}", rr, opt, now, day)
            if not c or c["id"] in d["calls"]:
                continue
            c["shadow"] = False                                           # v107: never hidden
            if b.get("risk_warn"):
                c.setdefault("risk_warn", []).append(b["risk_warn"])
            c.update(grade="A" if (b["score"] >= 85 and b.get("stage") == "CONFIRMED") else "B", qcodes=[], qtext=[], mcx={"commodity": o.get("commodity"), "fut_px": r["px"]},
                     source_label=f"🛢 Commodity · {b['name']}")
            d["calls"][c["id"]] = c
            mine.append(c)
            n += 1
            tg(f"🛢 COMMODITY CALL · {o.get('commodity')} {o['strike']:g} {b['side']} (exp {o['expiry']})\n{b['name']} · score {b['score']}\n"
               f"Entry ₹{p['entry']} · SL ₹{p['sl']} · T1/T2/T3 {' / '.join(str(t) for t in p['targets'])}\nRisk ≈ ₹{p['risk_rs']:,}/lot (paper)", f"mcx|{c['id']}")
        if n:
            STORE.dirty = True
            STORE.save(force=True)
    return n


def track(ag, now):
    """Open MCX calls: LTP · SL · T1 (lock) · T2 · T3 · 23:20 EOD exit — NSE close ஆனாலும் இங்கே ஓடும்."""
    from .calls import CALLS_LOCK, STORE, _close, lock_price, OPEN
    with CALLS_LOCK:
        d = STORE.load()
        day = str(now.date())
        hm0 = now.strftime("%H:%M")
        for c in d["calls"].values():
            # பழைய bug: MCX paper / call 3:20 PM-க்கே EOD EXIT ஆச்சு → இன்று 11:20 PM முன்னால இருந்தா மறுபடி OPEN
            if (c.get("exch") == "MCX" and c["date"] == day and c["status"] == "EOD EXIT" and " 15:2" in str(c.get("exit_time"))
                    and hm0 < CFG["eod"]):
                c["status"] = f"T{len(c['hits'])} HIT" if c.get("hits") else "OPEN"
                for k_ in ("exit", "exit_time"):
                    c.pop(k_, None)
                c.setdefault("revisions", []).append({"t": hm0, "sl": c["sl"], "why": "MCX: 3:20 EOD தவறு — 11:20 PM வரை reopen"})
        op = [c for c in d["calls"].values() if (c["kind"] == "MCX" or c.get("exch") == "MCX") and c["status"] in OPEN]
        if not op:
            return 0
        qs = ag.quotes({"MCX": [c["token"] for c in op]}) or {}
        hm = now.strftime("%H:%M")
        for c in op:
            q = qs.get(c["token"]) or {}
            ltp = float(q.get("ltp") or 0)
            if not ltp:
                continue
            c["ltp"] = ltp
            c["pnl_lot"] = round((ltp - c["entry"]) * c["lot"])
            if ltp <= c["sl"]:
                _close(c, "SL HIT" if not c["hits"] else "TRAIL SL", c["sl"] if c["hits"] else ltp, str(now))
                continue
            for i, t in enumerate(c["targets"]):
                if i >= len(c["hits"]) and ltp >= t:
                    c["hits"].append(f"T{i + 1} {now.strftime('%d-%m %H:%M')}")
                    c["status"] = f"T{i + 1} HIT"
                    c["sl"] = lock_price(c["entry"], c["targets"][0], c["lot"]) if i == 0 else c["targets"][i - 1]
                    if i == len(c["targets"]) - 1:
                        _close(c, "T3 DONE", ltp, str(now))
                        break
            if c["status"] in OPEN and hm >= CFG["eod"]:
                _close(c, "EOD EXIT", ltp, str(now))
        STORE.dirty = True
    return len(op)


def run_once(ag, inst, now):
    with LK:
        STATE["beat"] = now.strftime("%H:%M:%S")
        errs = []
        rows = scan(ag, inst, now)
        try:
            ch, jp = ai_choice(rows)
        except Exception as e:
            ch, jp = None, None
            errs.append(f"AI: {e}")
        STATE.update(time=now.strftime("%H:%M:%S"), date=str(now.date()), rows=rows, ai=ch, jackpot=jp, cfg=CFG, open=mcx_open(now))
        for nm_, fn in (("calls", lambda: to_calls(rows, now)), ("track", lambda: track(ag, now))):
            try:
                fn()
            except Exception as e:
                errs.append(f"{nm_}: {e}")
        STATE["err"] = " · ".join(errs) or None
        try:
            from .calls import STORE
            STATE["calls"] = sorted([dict(c) for c in STORE.load()["calls"].values() if c["kind"] == "MCX" or c.get("exch") == "MCX"],
                                    key=lambda c: c.get("signal_time") or "", reverse=True)[:60]
        except Exception:
            pass
        return STATE
