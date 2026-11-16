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

CFG = {"mult": 2.5, "look": 20, "days": 6, "ttl": 300, "max_fetch": 12, "keep": 6}
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
        if x >= mult * avg and x >= float(w.max()):
            h, l, c = float(df["high"].iloc[i]), float(df["low"].iloc[i]), float(df["close"].iloc[i])
            pos = (c - l) / (h - l) if h > l else 0.5
            side = "BUY" if pos >= 0.6 else "SELL" if pos <= 0.4 else "ABSORB"
            out.append({"time": str(df.index[i])[:16], "side": side, "mult": round(x / avg, 1), "price": round(c, 2), "pos": round(pos, 2)})
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
            df = ag.candles("NSE", tok, "FIFTEEN_MINUTE", end - pd.Timedelta(days=CFG["days"]), end)
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
