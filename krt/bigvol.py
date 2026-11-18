"""🐋 BIG-PLAYER VOLUME — 15-minute volume spikes that show large participants stepping in, per stock.

Spike  = a 15-min candle whose volume is ≥ 2.5× the 20-candle average AND the largest of the last 20 candles.
Side   = where that candle closed inside its range: top 40% → BUY (buyers absorbed all selling) · bottom 40% → SELL ·
         middle → ABSORB (big volume, price held — someone is soaking up the other side).
Used for: the Big Player Accumulation Radar (score + side check) and its own list "where big players are active today".
Runs in the background for at most ~20 stocks (radar candidates + open-call stocks), one 15-min candle request each, cached 5 min.
Honest: a spike shows big volume, not who traded or their intent.
"""
import time

import pandas as pd

CFG = {"budget_s": 240, "mult": 2.5, "look": 20, "days": 3, "iv": "FIVE_MINUTE", "bar": 5, "ttl": 300, "max_fetch": 12, "keep": 6, "sweep_n": 260, "feed_days": 2, "feed_max": 600, "push_mult": 5.0}
FEED = {}                # "SYM|time" → spike row (whole F&O market + MCX) for the JARVIS 🐋 table
SW = {"cursor": 0, "time": None, "scanned": 0, "universe": 0, "pushed": set()}
CACHE = {}               # symbol → (ts, result)
STATE = {"time": None, "rows": [], "err": None}


def spikes(df, mult=CFG["mult"], look=CFG["look"]):
    """df: 15-min OHLCV (DatetimeIndex). → newest-first list of spikes."""
    if df is None or len(df) < look + 2:
        return []
    v = df["volume"].astype(float)
    out = []
    for i in range(look, len(df)):
        w = v.iloc[i - look:i]
        avg = float(w.mean() or 0)
        if not avg:
            continue
        x = float(v.iloc[i])
        ts = df.index[i]
        if getattr(ts, "hour", None) == 9 and getattr(ts, "minute", None) in (0, 15):
            continue                              # the opening candle is always huge — not a big-player signal
        if x >= mult * avg and x >= float(w.max()):
            h, l, c = float(df["high"].iloc[i]), float(df["low"].iloc[i]), float(df["close"].iloc[i])
            pos = (c - l) / (h - l) if h > l else 0.5
            side = "BUY" if pos >= 0.6 else "SELL" if pos <= 0.4 else "ABSORB"
            out.append({"time": str(df.index[i])[:16], "side": side, "mult": round(x / avg, 1), "price": round(c, 2), "pos": round(pos, 2),
                        "high": round(h, 2), "low": round(l, 2)})
    return out[::-1][:CFG["keep"]]


def verdict(sp, today):
    """Summarise a stock's recent spikes → (bias 'CE' / 'PE' / None, label, today's spikes)."""
    td = [s for s in sp if s["time"][:10] == today]
    recent = sp[:3]
    b = sum(1 for s in recent if s["side"] == "BUY")
    s_ = sum(1 for s in recent if s["side"] == "SELL")
    a = sum(1 for s in recent if s["side"] == "ABSORB")
    if b >= 2 or (b == 1 and a >= 1 and not s_):
        return "CE", f"big buyers: {b} BUY{' + ' + str(a) + ' ABSORB' if a else ''} spikes", td
    if s_ >= 2 or (s_ == 1 and a >= 1 and not b):
        return "PE", f"big sellers: {s_} SELL{' + ' + str(a) + ' ABSORB' if a else ''} spikes", td
    if a >= 2:
        return None, "absorption — big volume, price held (breakout or reversal coming)", td
    return None, ("mixed big volume" if recent else "no big-player spike"), td


def refresh(ag, inst, symbols, now):
    """Background: fetch 15-min candles for symbols not cached in the last 5 min (≤ max_fetch per run)."""
    today = str(pd.Timestamp(now).date())
    n = 0
    for sym in symbols:
        hit = CACHE.get(sym)
        if hit and time.time() - hit[0] < CFG["ttl"]:
            continue
        if n >= CFG["max_fetch"]:
            break
        tok = (inst.get("eq") or {}).get(sym)
        if not tok:
            continue
        try:
            end = pd.Timestamp(now)
            df = ag.candles("NSE", tok, CFG["iv"], end - pd.Timedelta(days=CFG["days"]), end)
            sp = spikes(df)
            bias, label, td = verdict(sp, today)
            CACHE[sym] = (time.time(), {"symbol": sym, "spikes": sp, "bias": bias, "label": label, "today": td})
        except Exception as e:
            STATE["err"] = str(e)[:80]
        n += 1
        time.sleep(0.35)                          # Angel candle-API rate limit
    for k in [k for k in CACHE if k not in symbols and time.time() - CACHE[k][0] > 3600]:
        CACHE.pop(k, None)
    STATE.update(time=pd.Timestamp(now).strftime("%I:%M %p"),
                 rows=sorted([v for _, v in CACHE.values() if v["spikes"]], key=lambda r: (not r["today"], -(r["spikes"][0]["mult"] if r["spikes"] else 0)))[:20])
    return n


def get(sym):
    hit = CACHE.get(sym)
    return hit[1] if hit else None


def _last_closed(now):
    """Start time of the last fully closed 15-min candle (NSE / MCX candles start at :00/:15/:30/:45)."""
    t = pd.Timestamp(now).floor(f"{CFG['bar']}min")
    return t - pd.Timedelta(minutes=CFG["bar"])


def strike_for(inst, sym, side, px, mcx=False):
    """ATM strike to watch for a big BUY (→ CE) / SELL (→ PE): nearest listed strike, nearest expiry ≥ 1 day away."""
    try:
        if mcx:
            rows = (inst.get("mcx_opt") or {}).get(sym) or []
            today = str(pd.Timestamp.now(tz="Asia/Kolkata").date())
            exps = sorted({r[2] for r in rows if r[2] > today})
            rows = [r for r in rows if exps and r[2] == exps[0]]
        else:
            from .instruments import contracts
            _, rows = contracts(inst, sym, 1)
        rows = [r for r in rows if r[4] == side]
        if not rows or not px:
            return None
        r = min(rows, key=lambda r: abs(float(r[3]) - px))
        return {"strike": float(r[3]), "side": side, "expiry": r[2], "contract": r[1], "lot": r[5] if len(r) > 5 else None}
    except Exception:
        return None


def _feed_add(sym, sp, exch, inst, px_now, send=None, today=None, ref_now=None):
    today = today or str(pd.Timestamp.now(tz="Asia/Kolkata").date())
    for x in sp:
        k = f"{sym}|{x['time']}"
        if k in FEED:
            continue
        side = "CE" if x["side"] == "BUY" else "PE" if x["side"] == "SELL" else None
        end = (pd.Timestamp(x["time"]) + pd.Timedelta(minutes=CFG["bar"])).strftime("%H:%M")
        nowk = pd.Timestamp.now(tz="Asia/Kolkata")
        seen = nowk.strftime("%H:%M:%S")
        # v124: a candle that closed >15 min ago (e.g. re-loaded after a server restart) is history, not a new alert
        try:
            wall = nowk.tz_localize(None)
            # live: the WALL clock (a slow sweep must not hide that an alert is late) · replay / tests: the scan time
            rn = pd.Timestamp(ref_now) if ref_now is not None and abs((wall - pd.Timestamp(ref_now)).total_seconds()) > 6 * 3600 else wall
            backfill = (rn - (pd.Timestamp(x["time"]) + pd.Timedelta(minutes=CFG["bar"]))).total_seconds() > 900
        except Exception:
            backfill = False
        row = {"symbol": sym, "exch": exch, "time": x["time"], "date": x["time"][:10], "side": x["side"], "mult": x["mult"], "price": x["price"],
               "end": end, "seen": seen, "backfill": backfill,
               "now": px_now, "opt": strike_for(inst, sym, side, px_now or x["price"], exch == "MCX") if side else None}
        FEED[k] = row
        if send and not backfill and x["time"][:10] == today and x["mult"] >= CFG["push_mult"] and k not in SW["pushed"] and side and exch != "MCX":
            SW["pushed"].add(k)
            o = row["opt"] or {}
            try:
                send(f"🐋 Big {x['side']} in {sym} · candle {x['time'][11:16]}–{end} · alert {seen[:5]} · {pd.Timestamp(x['time']).strftime('%d %b')}"
                     f" · {x['mult']}× avg vol @ {x['price']:g}"
                     + (f"\nWatch {sym} {o['strike']:g} {o['side']} (exp {o['expiry']})" if o else ""), f"bigvol|{k}", True)
            except Exception:
                pass


def sweep(ag, inst, now, priority=(), send=None, mcx_only=False):
    """🐋 Whole-market sweep: every F&O stock's 15-min candles, re-fetched only after a NEW 15-min candle closes
    (≈200 requests per 15 min, ≤40 per run) + all MCX commodities from the commodity candle cache (no API)."""
    now = pd.Timestamp(now)
    lc = _last_closed(now)
    n = 0
    if not mcx_only:
        uni = list(dict.fromkeys(list(priority) + list(inst.get("fno") or [])))
        SW["universe"] = len(uni)
        try:
            from .fullscan import C as _C
            lq = _C.get("live_q") or {}
        except Exception:
            lq = {}
        # v125: most ACTIVE stocks first (live relative volume) — that is where big players show up — and a 4-min time budget
        #       so a slow / throttled API never makes the next candle wait.
        act = sorted(uni, key=lambda x: -((lq.get(x) or {}).get("vol_ratio") or 0))
        order = list(priority) + act
        t_start = time.time()
        for sym in dict.fromkeys(order):
            if n >= CFG["sweep_n"] or time.time() - t_start > CFG.get("budget_s", 240):
                break
            hit = CACHE.get(sym)
            if hit and hit[1].get("last_bar") and pd.Timestamp(hit[1]["last_bar"]) >= lc:
                continue
            tok = (inst.get("eq") or {}).get(sym)
            if not tok:
                continue
            try:
                try:
                    df = ag.candles("NSE", tok, CFG["iv"], now - pd.Timedelta(days=CFG["days"]), now)
                except Exception:
                    time.sleep(1.0)                   # rate-limit hiccup → one retry so no stock is missed
                    df = ag.candles("NSE", tok, CFG["iv"], now - pd.Timedelta(days=CFG["days"]), now)
                df = df[df.index <= lc] if df is not None and len(df) else df          # only CLOSED candles
                sp = spikes(df)
                bias, label, td = verdict(sp, str(now.date()))
                CACHE[sym] = (time.time(), {"symbol": sym, "spikes": sp, "bias": bias, "label": label, "today": td,
                                            "last_bar": str(df.index[-1]) if df is not None and len(df) else None})
                _feed_add(sym, sp, "NSE", inst, (lq.get(sym) or {}).get("ltp"), send, str(now.date()), now)
            except Exception as e:
                STATE["err"] = str(e)[:80]
            n += 1
            if sym in uni:
                SW["cursor"] = (uni.index(sym) + 1) % max(len(uni), 1)
            time.sleep(0.34)                          # Angel candle-API limit ≈3/s → whole market in ~80 s
    try:
        from .commodity import FR as _MFR
        for name, v in list(_MFR.items()):
            m15 = (v[1] or {}).get("5M") if v else None
            if m15 is None or len(m15) < 25:
                continue
            m15 = m15[m15.index <= lc]
            sp = spikes(m15)
            bias, label, td = verdict(sp, str(now.date()))
            CACHE["MCX:" + name] = (time.time(), {"symbol": name, "spikes": sp, "bias": bias, "label": label, "today": td})
            _feed_add(name, sp, "MCX", inst, float(m15["close"].iloc[-1]) if len(m15) else None, send, str(now.date()), now)
    except Exception as e:
        STATE["err"] = str(e)[:80]
    keep = sorted({k.split("|")[1][:10] for k in FEED}, reverse=True)[:CFG["feed_days"]]
    for k in [k for k, r in FEED.items() if r["date"] not in keep]:
        FEED.pop(k, None)
    if len(FEED) > CFG["feed_max"]:
        for k in sorted(FEED, key=lambda k: FEED[k]["time"])[:len(FEED) - CFG["feed_max"]]:
            FEED.pop(k, None)
    SW.update(time=now.strftime("%d %b %I:%M %p"), scanned=sum(1 for k in CACHE if not k.startswith("MCX:")))
    STATE.update(time=now.strftime("%I:%M %p"),
                 rows=sorted([v for k, (_, v) in CACHE.items() if v["spikes"] and not k.startswith("MCX:")],
                             key=lambda r: (not r["today"], -(r["spikes"][0]["mult"] if r["spikes"] else 0)))[:20])
    return n


def feed_report():
    rows = sorted(FEED.values(), key=lambda r: (r["time"], r["mult"]), reverse=True)
    today = rows[0]["date"] if rows else None
    T = [r for r in rows if r["date"] == today]
    er = sorted(EARLY.values(), key=lambda r: r["full"], reverse=True)[:60]
    return {"time": SW["time"], "scanned": SW["scanned"], "universe": SW["universe"], "rows": rows[:300], "early": er, "early_time": ES["time"],
            "summary": {"buy": sum(1 for r in T if r["side"] == "BUY"), "sell": sum(1 for r in T if r["side"] == "SELL"),
                        "absorb": sum(1 for r in T if r["side"] == "ABSORB"), "date": today}}


# ───────────────────────── ⚡ v120 EARLY detector (every minute, live quotes — no candle API) ─────────────────────────
ECFG = {"mult": 4.0, "win": 2, "hist": 20, "min_hist": 5, "move": 0.15, "cool": 15, "keep": 300}
EH = {}          # symbol → [(ts, cum_volume, ltp), …]  last ~20 minutes
EARLY = {}       # "SYM|HH:MM" → row
ES = {"time": None, "n": 0, "err": None}


def early(ag, inst, now, send=None, quotes=None):
    """Every minute: one quote call per 50 F&O stocks → per-minute volume from the cumulative day volume.
    Last 2 minutes' volume ≥ 5× the stock's normal 2-minute volume AND price moved ≥0.15% → ⚡ EARLY big BUY / SELL —
    before the 5-min candle even closes. Confirmed later (or not) by the 5-min candle sweep."""
    now = pd.Timestamp(now)
    uni = list(inst.get("fno") or [])
    eq = inst.get("eq") or {}
    toks = {"NSE": [eq[s] for s in uni if eq.get(s)]}
    try:
        qs = quotes if quotes is not None else ag.quotes(toks)
    except Exception as e:
        ES["err"] = str(e)[:80]
        return 0
    try:
        from .fullscan import C as _C
        avgd = _C.get("avgvol") or {}
    except Exception:
        avgd = {}
    today = str(now.date())
    hm = now.strftime("%H:%M")
    n = 0
    for sym in uni:
        q = qs.get(str(eq.get(sym)))
        if not q:
            continue
        try:
            vol, ltp = float(q.get("tradeVolume") or 0), float(q.get("ltp") or 0)
        except Exception:
            continue
        h = EH.setdefault(sym, [])
        if h and str(h[-1][0].date()) != today:
            h.clear()
        if h and vol < h[-1][1]:
            h.clear()                                  # volume reset (new session / bad tick)
        h.append((now, vol, ltp))
        del h[:-ECFG["hist"]]
        w = ECFG["win"]
        if len(h) < ECFG["min_hist"] + w:
            continue
        recent = h[-1][1] - h[-1 - w][1]               # volume in the last 2 minutes
        past = [h[i][1] - h[i - w][1] for i in range(w, len(h) - w)]
        base = sorted(past)[len(past) // 2] if past else 0          # median 2-minute volume today
        dayb = (avgd.get(sym) or 0) / 375 * w * 0.6                # floor from the 20-day average (quiet mornings)
        base = max(base, dayb, 1)
        mult = recent / base
        p0 = h[-1 - w][2]
        mv = (ltp / p0 - 1) * 100 if p0 else 0
        if mult < ECFG["mult"] or abs(mv) < ECFG["move"]:
            continue
        side = "BUY" if mv > 0 else "SELL"
        last = [r for k, r in EARLY.items() if r["symbol"] == sym and r["side"] == side and r["date"] == today]
        if last and (now - pd.Timestamp(max(r["full"] for r in last))) < pd.Timedelta(minutes=ECFG["cool"]):
            continue
        o = strike_for(inst, sym, "CE" if side == "BUY" else "PE", ltp)
        k = f"{sym}|{hm}"
        row = {"symbol": sym, "exch": "NSE", "date": today, "time": hm, "full": str(now), "side": side, "mult": round(mult, 1),
               "move": round(mv, 2), "price": ltp, "opt": o, "early": True}
        EARLY[k] = row
        n += 1
        if send:
            try:
                send(f"⚡ EARLY big {side} building in {sym} · {now.strftime('%d %b')} {hm} · last 2 min volume {mult:.1f}× normal · price {mv:+.2f}% @ {ltp:g}"
                     + (f"\nWatch {sym} {o['strike']:g} {o['side']} (exp {o['expiry']}) — wait for the 5-min candle to confirm" if o else ""),
                     f"early|{k}", True)
            except Exception:
                pass
    for k in [k for k, r in EARLY.items() if r["date"] != today]:
        EARLY.pop(k, None)
    if len(EARLY) > ECFG["keep"]:
        for k in sorted(EARLY, key=lambda k: EARLY[k]["full"])[:len(EARLY) - ECFG["keep"]]:
            EARLY.pop(k, None)
    ES.update(time=now.strftime("%d %b %H:%M:%S"), n=len(uni), err=None)
    return n
