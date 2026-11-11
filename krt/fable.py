"""🧠 FABLE PICKS — Claude Fable 5.2 reads every analysis in the terminal and picks only the best 0-3 setups, like an experienced trader.

Needs ANTHROPIC_API_KEY in Render → Environment. Optional: FABLE_MODEL (default claude-fable-5-2), FABLE_EFFORT (low/medium/high, default medium),
FABLE_MAX_RUNS (default 12 auto runs a day), FABLE_ASK_MAX (default 30 questions a day), FABLE_AUTO_PAPER (1 = put Fable picks in Paper Trade).
API notes (platform.claude.com docs): no temperature/top_p/top_k on Fable 5.2 · adaptive thinking always on · depth via output_config.effort ·
thinking counts toward max_tokens · read only `text` blocks. Pricing (Fable 5.2): $8 / M input, $40 / M output, cache read $0.20 / M.
Honest: Fable is a strong reasoner, not a crystal ball. Its picks are tracked with real results below — judge it on those.
"""
import hashlib
import json
import os
import re
import time
import urllib.request

API = __import__("os").environ.get("FABLE_API_URL", "https://api.anthropic.com/v1/messages")
OPEN = ("OPEN", "T1 HIT", "T2 HIT")
PRICE = {"claude-fable-5-2": (8.0, 40.0, 0.20, 10.0)}          # input, output, cache read, cache write (write ≈ 1.25× input — estimate)


def cfg():
    return {"model": os.environ.get("FABLE_MODEL", "claude-fable-5-2"), "effort": os.environ.get("FABLE_EFFORT", "medium"),
            "max_runs": int(os.environ.get("FABLE_MAX_RUNS", "12")), "ask_max": int(os.environ.get("FABLE_ASK_MAX", "30")),
            "auto_paper": os.environ.get("FABLE_AUTO_PAPER", "1") == "1", "every_min": 15, "min_gap": 8, "start": "09:45", "end": "14:30",
            "max_tokens": 16000, "key": bool(os.environ.get("ANTHROPIC_API_KEY"))}


STATE = {"day": None, "runs": 0, "asks": 0, "last_t": 0, "last_hash": None, "last": None, "err": None, "busy": False,
         "usage": {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "usd": 0.0}, "chat": []}

SYSTEM = """You are FABLE, the head trader and risk manager inside the KRT Terminal, an NSE / MCX options scanner used by a retail trader in India.
Your job: from the candidate setups you are given, choose only the best of the best — at most 3 — that an experienced intraday options trader would actually take right now. Choosing NOTHING is a correct answer when nothing is clean. Quality over quantity, always.

You are an expert in: price action and market structure (HH/HL, BOS, CHOCH), smart money concepts (order blocks, fair value gaps, liquidity sweeps, inducement), ICT (kill zones, silver bullet, displacement), liquidity mapping (equal highs/lows, stop pools), VWAP and anchored VWAP, volume profile (POC, value area), order flow / footprint (delta, stacked imbalance, absorption), volume spread analysis, Wyckoff (spring, upthrust, SOS/SOW), supply and demand, support/resistance and retests, multi-timeframe alignment, Fibonacci, relative strength vs NIFTY and sector, every candlestick pattern (engulfing, hammer, shooting star, doji, morning/evening star, three soldiers/crows, inside bar, pin bar, marubozu, tweezer, harami), option buying mechanics (delta, gamma, theta decay, IV, spread, liquidity, expiry risk), open interest reading (long build-up, short covering, writing walls, PCR), and market regime (trending, sideways, volatile).

Hard rules (never break):
1. Only pick ids that appear in the candidates list. Never invent symbols, strikes or prices.
2. Option BUY plans only: sl < entry < t1 < t2 < t3, all in option premium rupees.
3. Reject: premium already more than 5% above entry (late — chasing); premium near SL; direction against NIFTY (except MCX); a module with negative expectancy and fewer than 15 trades unless the setup itself is exceptional; setups with no volume confirmation.
4. Need at least 2 independent confirmations (e.g. chart structure + volume, footprint + level break, proven module + chart TAKE).
5. Prefer modules whose REAL results (module_stats) are good: win rate, expectancy, profit factor. Trust real numbers over theory.
6. Risk: 1 lot risk above Rs 2,500 must be flagged in risk_note.
7. Learn from past_fable results: avoid repeating the kind of pick that hit SL.
8. Confidence is YOUR judgment 0-100 of setup quality — not a promised win probability. Never promise profit.
9. GOLD grade only for the single cleanest setup with 3+ confirmations, proven module and clean entry. Most days there is no GOLD.

Reply with ONLY one JSON object, no markdown, in simple English:
{"market_view": "1-2 sentences", "picks": [{"id": "...", "grade": "GOLD|A|B", "confidence": 0-100, "entry_zone": [low, high], "sl": n, "t1": n, "t2": n, "t3": n,
  "why": ["short reason", "..."], "risk_note": "...", "invalidate_if": "..."}], "avoid": [{"id": "...", "reason": "..."}], "no_trade_reason": null or "...", "lesson": "one line"}"""


def _price(model, u):
    p = PRICE.get(model)
    if not p:
        return 0.0
    return (u.get("input_tokens", 0) * p[0] + u.get("output_tokens", 0) * p[1] + u.get("cache_read_input_tokens", 0) * p[2]
            + u.get("cache_creation_input_tokens", 0) * p[3]) / 1e6


def call_api(user_text, system=SYSTEM, max_tokens=None, _post=None):
    """One Messages API request. Returns (text, usage). _post lets tests inject a fake transport."""
    C = cfg()
    body = {"model": C["model"], "max_tokens": max_tokens or C["max_tokens"], "output_config": {"effort": C["effort"]},
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user_text}]}
    if _post:
        res = _post(body)
    else:
        req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST",
                                     headers={"content-type": "application/json", "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
                                              "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=240) as r:
            res = json.loads(r.read().decode())
    if res.get("type") == "error":
        raise RuntimeError((res.get("error") or {}).get("message") or "API error")
    text = "".join(b.get("text", "") for b in res.get("content") or [] if b.get("type") == "text")
    u = res.get("usage") or {}
    U = STATE["usage"]
    U["in"] += u.get("input_tokens", 0)
    U["out"] += u.get("output_tokens", 0)
    U["cache_read"] += u.get("cache_read_input_tokens", 0)
    U["cache_write"] += u.get("cache_creation_input_tokens", 0)
    U["usd"] = round(U["usd"] + _price(C["model"], u), 4)
    return text, u


def parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("no JSON in reply")
    return json.loads(m.group(0))


def validate(out, cands):
    """Keep only picks on real candidate ids with a sane BUY plan; max 3."""
    ok, ids = [], {c["id"]: c for c in cands}
    for p in out.get("picks") or []:
        if len(ok) >= 3:
            break
        c = ids.get(p.get("id"))
        if not c or any(x["id"] == p.get("id") for x in ok):
            continue
        if not c:
            continue
        try:
            sl, t1, t2, t3 = (float(p[k]) for k in ("sl", "t1", "t2", "t3"))
            ez = [float(x) for x in (p.get("entry_zone") or [c["entry"], c["entry"]])][:2]
        except Exception:
            continue
        e = sum(ez) / len(ez)
        if not (0 < sl < e < t1 < t2 < t3):
            continue
        ok.append({**p, "entry_zone": [round(min(ez), 2), round(max(ez), 2)], "sl": round(sl, 2), "t1": round(t1, 2), "t2": round(t2, 2), "t3": round(t3, 2),
                   "confidence": int(max(0, min(100, float(p.get("confidence") or 0)))), "grade": p.get("grade") if p.get("grade") in ("GOLD", "A", "B") else "B"})
    golds = [p for p in ok if p["grade"] == "GOLD"]
    for p in golds[1:]:
        p["grade"] = "A"
    out["picks"] = ok
    return out


def candidates(D, day, ctx):
    """Top 15 open calls with every analysis attached (built by server from best picks / sniper / chart room / lab / footprint)."""
    rows = []
    for c in (D.get("calls") or {}).values():
        if c.get("date") != day or c.get("status") not in OPEN or c.get("shadow") or c.get("kind") == "PICK":
            continue
        x = (ctx.get("extra") or {}).get(c["id"]) or {}
        e, ltp = float(c.get("entry") or 0), float(c.get("ltp") or 0)
        rows.append({"id": c["id"], "time": c.get("time"), "symbol": c["symbol"], "strike": c.get("strike"), "side": c.get("side"), "exch": c.get("exch"),
                     "module": c.get("source"), "entry": c.get("entry"), "sl": c.get("sl"), "targets": c.get("targets"), "ltp": c.get("ltp"),
                     "premium_move_pct": round((ltp / e - 1) * 100, 1) if e and ltp else None, "lot": c.get("lot"),
                     "risk_per_lot": round((e - float(c.get("sl") or 0)) * float(c.get("lot") or 1)), "vol_ratio": c.get("vol_ratio"),
                     "hits": c.get("hits"), **x})
    rows.sort(key=lambda r: -(r.get("score") or 0))
    return rows[:15]


def build_prompt(now, cands, ctx, past):
    return json.dumps({"now": now.strftime("%Y-%m-%d %H:%M IST"), "market": ctx.get("market"), "module_stats": ctx.get("module_stats"),
                       "candidates": cands, "past_fable": past}, default=str, separators=(",", ":"))


def past_results(D, n=20):
    J = (D or {}).get("fable_picks") or {}
    L = sorted(J.values(), key=lambda p: (p["date"], p["time"]), reverse=True)[:n]
    return [{"symbol": p["symbol"], "side": p["side"], "grade": p.get("grade"), "module": p.get("module"), "result": p.get("result"), "pnl": p.get("pnl")} for p in L]


def should_run(now, cands, force=False):
    C = cfg()
    day = str(now.date())
    if STATE["day"] != day:
        STATE.update(day=day, runs=0, asks=0, last_hash=None)
    if STATE["busy"] or not C["key"]:
        return False
    if force:
        return STATE["runs"] < C["max_runs"] + 5
    hm = now.strftime("%H:%M")
    if not (C["start"] <= hm <= C["end"]) or now.weekday() >= 5 or STATE["runs"] >= C["max_runs"] or not cands:
        return False
    h = hashlib.md5(json.dumps([(c["id"], c.get("status"), round((c.get("premium_move_pct") or 0) / 3)) for c in cands]).encode()).hexdigest()
    gap = time.time() - STATE["last_t"]
    if gap < C["min_gap"] * 60:
        return False
    if h == STATE["last_hash"] and gap < C["every_min"] * 60:
        return False
    STATE["last_hash"] = h
    return True


def prepare(D, now, ctx):
    """Under the store lock: snapshot candidates + prompt (no API call here)."""
    cands = candidates(D, str(now.date()), ctx)
    return cands, build_prompt(now, cands, ctx, past_results(D))


def ask_model(prompt, _post=None):
    """Outside the lock: the slow API call. Returns parsed JSON or raises."""
    STATE["busy"] = True
    try:
        text, _ = call_api(prompt, _post=_post)
        return parse(text)
    finally:
        STATE["busy"] = False
        STATE["last_t"] = time.time()
        STATE["runs"] += 1


def apply(D, now, out, cands):
    """Under the lock: validate + save new picks with the time picked."""
    day = str(now.date())
    out = validate(out, cands)
    out.update(time=now.strftime("%I:%M %p"), n_cands=len(cands))
    STATE.update(last=out, err=None)
    J = D.setdefault("fable_picks", {})
    byid = {c["id"]: c for c in cands}
    new = []
    for p in out["picks"]:
        if p["id"] in J:
            J[p["id"]].update(last_seen=now.strftime("%H:%M"), confidence=p["confidence"])
            continue
        c = byid[p["id"]]
        rec = {"id": p["id"], "date": day, "time": now.strftime("%H:%M"), "symbol": c["symbol"], "strike": c.get("strike"), "side": c.get("side"), "module": c.get("module"),
               "grade": p["grade"], "confidence": p["confidence"], "entry_zone": p["entry_zone"], "sl": p["sl"], "t1": p["t1"], "t2": p["t2"], "t3": p["t3"],
               "why": (p.get("why") or [])[:5], "risk_note": p.get("risk_note"), "invalidate_if": p.get("invalidate_if"), "lot": c.get("lot"),
               "status": "OPEN", "hits": [], "result": None, "pnl": 0, "ltp": c.get("ltp")}
        J[p["id"]] = rec
        new.append(rec)
    return new


def run(D, now, ctx, _post=None):
    """prepare → ask_model → apply in one go (tests / single-thread use)."""
    cands, prompt = prepare(D, now, ctx)
    try:
        out = ask_model(prompt, _post=_post)
    except Exception as e:
        STATE["err"] = str(e)[:200]
        return []
    return apply(D, now, out, cands)


def track(D, now):
    """Fable's OWN plan (its SL / T1-T3, not the module's) tracked on the call's live premium. EOD exit 15:20 (MCX 23:00)."""
    J = (D or {}).get("fable_picks") or {}
    calls = (D or {}).get("calls") or {}
    hm = now.strftime("%H:%M")
    for p in J.values():
        if p["status"] != "OPEN":
            continue
        c = calls.get(p["id"]) or {}
        ltp = float(c.get("ltp") or 0)
        if not ltp:
            continue
        p["ltp"] = ltp
        e = sum(p["entry_zone"]) / 2
        lot = float(p.get("lot") or 1)
        for i, k in enumerate(("t1", "t2", "t3"), 1):
            if ltp >= p[k] and not any(h.startswith(f"T{i}") for h in p["hits"]):
                p["hits"].append(f"T{i} {hm}")
        p["pnl"] = round((ltp - e) * lot)
        if ltp <= p["sl"]:
            p.update(status="SL HIT", result="SL", pnl=round((p["sl"] - e) * lot), exit_time=hm)
        elif any(h.startswith("T3") for h in p["hits"]):
            p.update(status="T3 DONE", result="T3", pnl=round((p["t3"] - e) * lot), exit_time=hm)
        elif p["date"] != str(now.date()) or hm >= ("23:00" if c.get("exch") == "MCX" else "15:20"):
            p.update(status="EOD EXIT", result=("T" + str(len(p["hits"])) if p["hits"] else ("PROFIT" if ltp > e else "LOSS")), exit_time=hm)


def ask(D, now, question, ctx, _post=None):
    C = cfg()
    if not C["key"]:
        return "Add ANTHROPIC_API_KEY in Render → Environment to talk to Fable."
    if STATE["asks"] >= C["ask_max"]:
        return f"Daily question limit reached ({C['ask_max']}). Change FABLE_ASK_MAX to allow more."
    STATE["asks"] += 1
    cands = candidates(D, str(now.date()), ctx)
    sys2 = SYSTEM.split("Reply with ONLY one JSON object")[0] + ("Now answer the trader's question in plain simple English (max 180 words). Be direct and honest; "
                                                                "if the answer is 'do not trade', say so. Use only the data given. No JSON.")
    try:
        text, _ = call_api(build_prompt(now, cands, ctx, past_results(D)) + "\n\nQUESTION: " + str(question)[:600], system=sys2, max_tokens=8000, _post=_post)
    except Exception as e:
        return f"Fable error: {str(e)[:160]}"
    STATE["chat"].insert(0, {"time": now.strftime("%I:%M %p"), "q": str(question)[:600], "a": text.strip()})
    del STATE["chat"][20:]
    return text.strip()


def report(D, day):
    J = (D or {}).get("fable_picks") or {}
    L = sorted(J.values(), key=lambda p: (p["date"], p["time"]), reverse=True)[:120]
    done = [p for p in L if p["status"] != "OPEN"]

    def st(X):
        return {"n": len(X), "win": round(sum(p["pnl"] > 0 for p in X) / len(X) * 100) if X else None, "net": round(sum(p["pnl"] for p in X))}
    C = cfg()
    return {"cfg": {k: C[k] for k in ("model", "effort", "max_runs", "ask_max", "auto_paper", "key", "start", "end")}, "runs": STATE["runs"], "asks": STATE["asks"],
            "busy": STATE["busy"], "err": STATE["err"], "last": STATE["last"], "usage": STATE["usage"], "chat": STATE["chat"][:6],
            "today": [p for p in L if p["date"] == day], "history": L, "stats": {"all": st(done), "gold": st([p for p in done if p.get("grade") == "GOLD"])}}
