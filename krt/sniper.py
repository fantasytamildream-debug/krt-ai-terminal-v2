"""🎯 POWER OI — KRT INSTITUTIONAL SNIPER V2.0 (paper / alert only).
Regime (NIFTY 15m: EMA slope+separation, ADX/DI, ATR vs baseline, VWAP crosses) → TRENDING / RANGE / HIGH-VOL.
Model A = Trend continuation (15m trend + 5m breakout close + same-slot RVOL + retest 1–6 bars + momentum).
Model B = Confirmed reversal (sweep + CHOCH + displacement + retest + confirmation) — RESEARCH, தனியா track.
State: WATCH → BREAKOUT/SWEEP → RETEST PENDING → ENTRY CONFIRMED → ACTIVE → CLOSED/INVALIDATED.
Gates fail = signal இல்லை. Score = alignment, win probability இல்லை. SMC = price-action proxy மட்டும்."""
import numpy as np
import pandas as pd
from .optmath import greeks_from_price, bs, iv, years_to_expiry, r05

CFG = {"session": (9 * 60 + 30, 14 * 60 + 30), "exit_time": (15, 15), "retest_bars": (1, 6), "max_ext_atr": 0.8,
       "rvol_min": 1.5, "spread_max": 3.0, "delta": (0.45, 0.65), "risk_cap": 2500, "charges": 150, "slippage": 0.01,
       "max_open": 3, "max_consec_sl": 2, "daily_loss": 5000, "time_stop_bars": 6, "candidates": 18, "fvg_atr": 0.2}
ST = {"day": None, "setups": {}, "alerts": set(), "regime": {}, "last": None, "health": {}}
REGIME = {"state": None, "dir": None}


def _ema(x, n):
    return pd.Series(x, dtype=float).ewm(span=n, adjust=False).mean().values


def _rsi(x, n=14):
    s = pd.Series(x, dtype=float).diff()
    up = s.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-s.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    r = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return r.fillna(100.0).values


def _atr(df, n=14):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return pd.Series(np.r_[tr[:1], tr]).rolling(n, min_periods=1).mean().values


def _adx(df, n=14):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    up, dn = np.diff(h, prepend=h[0]), -np.diff(l, prepend=l[0])
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h - l, np.maximum(abs(h - np.r_[c[0], c[:-1]]), abs(l - np.r_[c[0], c[:-1]])))
    sm = lambda x: pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().values
    atr = sm(tr)
    pdi, ndi = 100 * sm(pdm) / np.maximum(atr, 1e-9), 100 * sm(ndm) / np.maximum(atr, 1e-9)
    dx = 100 * abs(pdi - ndi) / np.maximum(pdi + ndi, 1e-9)
    return sm(dx), pdi, ndi


def _done(df, now, mins):
    return df[df.index + pd.Timedelta(minutes=mins) <= now]


def _vwap(df):
    tp = (df["high"] + df["low"] + df["close"]) / 3
    return (tp * df["volume"]).cumsum() / df["volume"].cumsum().replace(0, np.nan)


# ---------------- 1. Regime
def regime(ag, now, session):
    t0 = (pd.Timestamp(session) - pd.tseries.offsets.BDay(4)).normalize() + pd.Timedelta(hours=9, minutes=15)
    df = ag.candles("NSE", "99926000", "FIFTEEN_MINUTE", t0, now)
    if df.empty:
        return {"state": "UNKNOWN", "why": ["NIFTY 15m data இல்லை"]}
    df = _done(df, now, 15)
    if len(df) < 30:
        return {"state": "UNKNOWN", "why": ["போதுமான 15m bars இல்லை"]}
    c = df["close"].values
    atr = _atr(df)
    e9, e21 = _ema(c, 9), _ema(c, 21)
    slope = (e21[-1] - e21[-5]) / max(atr[-1], 1e-9)
    sep = (e9[-1] - e21[-1]) / max(atr[-1], 1e-9)
    adx, pdi, ndi = _adx(df)
    atr_ratio = atr[-1] / max(np.mean(atr[-60:]), 1e-9)
    today = df[df.index.normalize() == pd.Timestamp(session)]
    crosses = 0
    if len(today) >= 2:
        vw = _vwap(today).values
        side = np.sign(today["close"].values - vw)
        crosses = int((np.diff(side) != 0).sum())
    up = pdi[-1] > ndi[-1]
    if atr_ratio >= 1.6:
        state = "HIGH-VOL"
    elif adx[-1] >= 20 and abs(slope) >= 0.15 and abs(sep) >= 0.1 and crosses <= 3 and (slope > 0) == up:
        state = "TRENDING"
    else:
        state = "RANGE"
    out = {"state": state, "dir": ("UP" if up else "DOWN") if state == "TRENDING" else None,
           "adx": round(float(adx[-1]), 1), "slope_atr": round(float(slope), 2), "sep_atr": round(float(sep), 2),
           "atr_ratio": round(float(atr_ratio), 2), "vwap_crosses": crosses,
           "nifty_pct_today": round(float((c[-1] / today["open"].iloc[0] - 1) * 100), 2) if len(today) else 0.0}
    REGIME.update(state=state, dir=out["dir"])
    return out


# ---------------- 3. Structure helpers (swing confirmation delay = K bars)
K = 3


def swings(df):
    h, l = df["high"].values, df["low"].values
    sh = [i for i in range(K, len(h) - K) if h[i] == h[i - K:i + K + 1].max()]
    sl = [i for i in range(K, len(l) - K) if l[i] == l[i - K:i + K + 1].min()]
    return sh, sl     # index i confirmed only at bar i+K


def fvg_zones(df, atr):
    out = []
    h, l = df["high"].values, df["low"].values
    for i in range(2, len(df)):
        if l[i] > h[i - 2] and (l[i] - h[i - 2]) >= CFG["fvg_atr"] * atr:
            out.append(("BULL", i, h[i - 2], l[i]))
        if h[i] < l[i - 2] and (l[i - 2] - h[i]) >= CFG["fvg_atr"] * atr:
            out.append(("BEAR", i, h[i], l[i - 2]))
    return out


def same_slot_rvol(df5, session):
    """கடைசி completed 5m bar volume ÷ அதே நேர slot-ன் முந்தைய sessions சராசரி."""
    today = df5[df5.index.normalize() == pd.Timestamp(session)]
    if today.empty:
        return 0.0
    t = today.index[-1].time()
    prev = df5[(df5.index.normalize() < pd.Timestamp(session)) & (df5.index.time == t)]["volume"]
    base = prev.tail(4).mean() if len(prev) else 0
    return round(float(today["volume"].iloc[-1] / base), 2) if base else 0.0


# ---------------- 4. Models
def model_a(df, side, atr, levels):
    """Trend continuation: breakout close beyond confirmed swing / PDH-PDL, then retest within 1–6 bars holding level."""
    n = len(df)
    sh, sl = swings(df)
    ce = side == "CE"
    lv_list = [(df["high"].values[i], f"5m swing high {df.index[i]:%H:%M}") for i in sh if i + K < n - 1] if ce else \
              [(df["low"].values[i], f"5m swing low {df.index[i]:%H:%M}") for i in sl if i + K < n - 1]
    if ce and levels.get("PDH"):
        lv_list.append((levels["PDH"], "PDH"))
    if not ce and levels.get("PDL"):
        lv_list.append((levels["PDL"], "PDL"))
    c, h, l, o, v = (df[k].values for k in ("close", "high", "low", "open", "volume"))
    best = None
    for L, name in lv_list:
        for b in range(max(1, n - 12), n):       # கடைசி 12 bars-க்குள் breakout
            crossed = (c[b] > L and c[b - 1] <= L) if ce else (c[b] < L and c[b - 1] >= L)
            if not crossed:
                continue
            body = abs(c[b] - o[b]) / max(h[b] - l[b], 1e-9)
            st = {"model": "A", "level": round(float(L), 2), "level_name": name, "breakout_bar": str(df.index[b])[11:16],
                  "breakout_body": round(float(body), 2), "state": "BREAKOUT"}
            after = range(b + 1, min(n, b + 1 + CFG["retest_bars"][1]))
            for j in after:
                if (c[j] < L - 0.05 * atr) if ce else (c[j] > L + 0.05 * atr):
                    st["state"] = "INVALIDATED"
                    st["why"] = "Level-க்கு உள்ளே மீண்டும் close"
                    break
                touched = (l[j] <= L + 0.15 * atr) if ce else (h[j] >= L - 0.15 * atr)
                if touched and ((c[j] > L) if ce else (c[j] < L)):
                    st.update(state="RETEST HELD", retest_bar=str(df.index[j])[11:16], retest_after=j - b,
                              retest_idx=j)
                    # confirmation: அடுத்த bar retest bar-ஐ தாண்டி close
                    if j + 1 < n and ((c[j + 1] > h[j]) if ce else (c[j + 1] < l[j])):
                        st.update(state="ENTRY CONFIRMED", entry_bar=str(df.index[j + 1])[11:16], entry_idx=j + 1)
                    break
            else:
                if n - 1 - b > CFG["retest_bars"][1]:
                    st["state"] = "EXPIRED"
                    st["why"] = "6 bars-க்குள் retest இல்லை"
                else:
                    st["state"] = "RETEST PENDING"
            if best is None or ["INVALIDATED", "EXPIRED", "BREAKOUT", "RETEST PENDING", "RETEST HELD", "ENTRY CONFIRMED"].index(st["state"]) > \
                    ["INVALIDATED", "EXPIRED", "BREAKOUT", "RETEST PENDING", "RETEST HELD", "ENTRY CONFIRMED"].index(best["state"]):
                best = st
    return best


def model_b(df, side, atr):
    """Reversal: sweep of confirmed swing → CHOCH close beyond last opposing swing with displacement → retest → confirm."""
    n = len(df)
    sh, sl = swings(df)
    ce = side == "CE"
    c, h, l = df["close"].values, df["high"].values, df["low"].values
    sw = [i for i in (sl if ce else sh) if i + K < n - 1][-3:]
    for i in reversed(sw):
        lvl = l[i] if ce else h[i]
        for s_ in range(i + K + 1, n):
            swept = (l[s_] < lvl and c[s_] > lvl) if ce else (h[s_] > lvl and c[s_] < lvl)
            if not swept:
                continue
            opp = [k for k in (sh if ce else sl) if k + K <= s_]
            if not opp:
                return None
            ch_lvl = h[opp[-1]] if ce else l[opp[-1]]
            for d in range(s_ + 1, min(n, s_ + 13)):
                if (c[d] > ch_lvl) if ce else (c[d] < ch_lvl):
                    disp = (h[d] - l[d]) / max(atr, 1e-9)
                    st = {"model": "B", "level": round(float(ch_lvl), 2), "level_name": "CHOCH level",
                          "sweep_bar": str(df.index[s_])[11:16], "sweep_level": round(float(lvl), 2),
                          "choch_bar": str(df.index[d])[11:16], "displacement_atr": round(float(disp), 2),
                          "state": "SWEEP+CHOCH" if disp >= 1.2 else "WEAK DISPLACEMENT"}
                    if disp < 1.2:
                        return st
                    mid = (h[d] + l[d]) / 2
                    for j in range(d + 1, min(n, d + 7)):
                        if (c[j] < lvl) if ce else (c[j] > lvl):
                            st.update(state="INVALIDATED", why="Sweep level மீண்டும் உடைந்தது")
                            return st
                        if (l[j] <= mid) if ce else (h[j] >= mid):
                            st.update(state="RETEST HELD", retest_idx=j, retest_bar=str(df.index[j])[11:16])
                            if j + 1 < n and ((c[j + 1] > h[j]) if ce else (c[j + 1] < l[j])):
                                st.update(state="ENTRY CONFIRMED", entry_idx=j + 1, entry_bar=str(df.index[j + 1])[11:16])
                            return st
                    st["state"] = "RETEST PENDING" if n - 1 - d <= 6 else "EXPIRED"
                    return st
            return None
    return None


# ---------------- 8. Option contract engine
def pick_contract(ag, inst, sym, side, spot, now, contracts_fn, lot_only=False):
    exp, cs = contracts_fn(inst, sym, 2)
    cs = [c for c in cs if c[4] == side]
    if not cs:
        return None, "Contract இல்லை"
    strikes = sorted({c[3] for c in cs})
    atm = min(strikes, key=lambda k: abs(k - spot))
    i = strikes.index(atm)
    itm = strikes[i - 1] if side == "CE" and i > 0 else strikes[i + 1] if side == "PE" and i + 1 < len(strikes) else None
    cand = [c for c in cs if c[3] in (atm, itm)]
    qs = ag.quotes({cand[0][6]: [c[0] for c in cand]}) if cand else {}
    best, why = None, "Liquid contract இல்லை"
    for c in cand:
        q = qs.get(c[0]) or {}
        d = q.get("depth") or {}
        buy, sell = d.get("buy") or [], d.get("sell") or []
        bid = float((buy[0] or {}).get("price") or 0) if buy else 0
        ask = float((sell[0] or {}).get("price") or 0) if sell else 0
        ask_qty = sum(float((x or {}).get("quantity") or 0) for x in sell)
        if not bid or not ask:
            continue
        spread = (ask - bid) / ((ask + bid) / 2) * 100
        try:
            g = greeks_from_price((bid + ask) / 2, spot, c[3], c[2], side, now.to_pydatetime())
        except Exception:
            g = {"delta": 0, "iv": None, "theta_pct": None}
        x = {"token": c[0], "exch": c[6], "contract": c[1], "strike": c[3], "expiry": c[2], "type": side, "lot": c[5],
             "bid": bid, "ask": ask, "spread_pct": round(spread, 2), "ask_depth": int(ask_qty),
             "oi": int(float(q.get("opnInterest") or 0)), "volume": int(float(q.get("tradeVolume") or 0)),
             "delta": g.get("delta"), "iv": g.get("iv"), "theta_pct": g.get("theta_pct"),
             "moneyness": "ATM" if c[3] == atm else "1 ITM", "fresh": q.get("exchFeedTime")}
        x["gates"] = {"Spread ≤3%": spread <= CFG["spread_max"], "Depth ≥ 1 lot": ask_qty >= c[5],
                      "Delta 0.45–0.65": CFG["delta"][0] <= (g.get("delta") or 0) <= CFG["delta"][1],
                      "Traded today": x["volume"] > 0}
        ok = all(x["gates"].values())
        rank = (ok, -spread, ask_qty, -abs((g.get("delta") or 0) - 0.55))
        if best is None or rank > best[0]:
            best = (rank, x)
    if not best:
        return None, why
    return best[1], None


# ---------------- main
def run(ag, inst, C, universe, now, session, contracts_fn, calls_today):
    day = str(pd.Timestamp(session).date())
    if ST["day"] != day:
        ST.update(day=day, setups={}, alerts=set())
    mins = now.hour * 60 + now.minute
    rg = regime(ag, now, session)
    ST["regime"] = rg
    # capital protection
    pw = [c for c in calls_today if c["kind"].startswith("POWER")]
    consec = 0
    for c in sorted([c for c in pw if c["status"] not in ("OPEN",)], key=lambda c: c.get("exit_time") or "", reverse=True):
        if c["status"] == "SL HIT":
            consec += 1
        else:
            break
    open_n = sum(c["status"] in ("OPEN", "T1 HIT", "T2 HIT") for c in pw)
    day_pnl = sum(c["pnl_lot"] for c in pw)
    protect = {"Consecutive SL < 2": consec < CFG["max_consec_sl"], f"Open trades < {CFG['max_open']}": open_n < CFG["max_open"],
               f"Daily loss < ₹{CFG['daily_loss']}": day_pnl > -CFG["daily_loss"],
               "Session 9:30–14:30": CFG["session"][0] <= mins <= CFG["session"][1]}
    # stage 1 — direction follows regime for Model A; Model B both sides (research)
    want_side = {"UP": "CE", "DOWN": "PE"}.get(rg.get("dir"))
    stage = []
    for u in universe:
        if abs(u["pct"]) < 0.6 or u["vol_ratio"] < 1.2 or not inst["eq"].get(u["symbol"]):
            continue
        stage.append(u)
    stage.sort(key=lambda u: -u["vol_ratio"] * abs(u["pct"]))
    stage = stage[:CFG["candidates"]]
    t0 = (pd.Timestamp(session) - pd.tseries.offsets.BDay(4)).normalize() + pd.Timedelta(hours=9, minutes=15)
    rows, signals = [], []
    for u in stage:
        df5 = ag.candles("NSE", inst["eq"][u["symbol"]], "FIVE_MINUTE", t0, now)
        if df5.empty:
            continue
        df5 = _done(df5, now, 5)
        today = df5[df5.index.normalize() == pd.Timestamp(session)]
        if len(today) < 8:
            continue
        atr5 = float(_atr(today)[-1])
        rvol = same_slot_rvol(df5, session)
        c15 = today["close"].resample("15min").last().dropna()
        e15 = _ema(c15.values, min(20, max(3, len(c15))))
        trend15 = "UP" if len(e15) >= 3 and e15[-1] > e15[-3] else "DOWN" if len(e15) >= 3 and e15[-1] < e15[-3] else "FLAT"
        vw = float(_vwap(today).iloc[-1])
        rsi5 = float(_rsi(today["close"].values)[-1])
        last = float(today["close"].iloc[-1])
        stock_pct = (last / today["open"].iloc[0] - 1) * 100
        rs = stock_pct - (rg.get("nifty_pct_today") or 0)
        lv = (C.get("levels") or {}).get(u["symbol"]) or {}
        for side in ("CE", "PE"):
            ce = side == "CE"
            for model in ("A", "B"):
                if model == "A" and side != want_side:
                    continue
                st = model_a(today, side, atr5, lv) if model == "A" else model_b(today, side, atr5)
                if not st:
                    continue
                key = f"{u['symbol']}|{side}|{model}|{st['level']}"
                prev = ST["setups"].get(key, {})
                st["first_seen"] = prev.get("first_seen") or now.strftime("%H:%M")
                L = st["level"]
                ext = abs(last - L) / max(atr5, 1e-9)
                # structure quality: FVG / order block at retest
                fv = fvg_zones(today, atr5)
                fvg_hit = any(z[0] == ("BULL" if ce else "BEAR") for z in fv[-4:])
                ob_ok = False
                if st.get("retest_idx"):
                    j = st["retest_idx"]
                    opp = today.iloc[max(0, j - 8):j]
                    obs = opp[(opp["close"] < opp["open"])] if ce else opp[(opp["close"] > opp["open"])]
                    if len(obs):
                        ob = obs.iloc[-1]
                        ob_ok = (today["low"].iloc[j] <= ob["high"]) if ce else (today["high"].iloc[j] >= ob["low"])
                # SCORE (100)
                regime_fit = 20 if (model == "A" and rg["state"] == "TRENDING") else (10 if model == "B" and rg["state"] != "HIGH-VOL" else 0)
                structure = 8 + (6 if fvg_hit else 0) + (6 if ob_ok else 0)
                rt = st.get("retest_after") or 0
                br = (6 if st.get("breakout_body", 0.6) >= 0.5 else 2) + (8 if 1 <= rt <= 3 else 5 if rt else 0) + (6 if ext <= 0.5 else 3 if ext <= CFG["max_ext_atr"] else 0)
                rv = 15 * min(rvol / 3, 1)
                strength = 15 if (rs > 0.5 if ce else rs < -0.5) else 8 if (rs > 0 if ce else rs < 0) else 0
                mom = (5 if (last > vw if ce else last < vw) else 0) + (5 if (55 <= rsi5 <= 75 if ce else 25 <= rsi5 <= 45) else 0)
                score = int(round(regime_fit + structure + br + rv + strength + mom))
                grade = "A+" if score >= 90 else "STRONG" if score >= 80 else "WATCH" if score >= 70 else "REJECT"
                row = {"symbol": u["symbol"], "ul_token": inst["eq"][u["symbol"]], "side": side, "model": model, **st, "atr5": round(atr5, 2), "rvol": rvol,
                       "rs_vs_nifty": round(rs, 2), "trend15": trend15, "vwap": round(vw, 2), "rsi5": round(rsi5, 1),
                       "ltp": last, "ext_atr": round(ext, 2), "fvg": fvg_hit, "order_block": ob_ok, "score": score,
                       "grade": grade, "parts": {"Trend/Regime": regime_fit, "Structure": structure, "Breakout/Retest": br,
                                                 "Rel volume": round(rv), "Stock strength": strength, "Momentum/VWAP": mom},
                       "sector": "N/A (sector data இல்லை)"}
                ST["setups"][key] = {"first_seen": st["first_seen"], "state": st["state"]}
                rows.append(row)
                if st["state"] != "ENTRY CONFIRMED" or grade == "REJECT" or key in ST["alerts"]:
                    continue
                # ---- gates + option
                gates = dict(protect)
                gates["Extension ≤0.8 ATR"] = ext <= CFG["max_ext_atr"]
                gates[f"Same-slot RVOL ≥{CFG['rvol_min']}"] = rvol >= CFG["rvol_min"]
                gates["Regime allows"] = (model == "A" and rg["state"] == "TRENDING") or model == "B"
                inval = (L - 0.1 * atr5) if ce else (L + 0.1 * atr5)
                risk_ul = abs(last - inval)
                opp_lv = [x for x in ([lv.get("PDH"), lv.get("PWH")] if ce else [lv.get("PDL"), lv.get("PWL")]) if x]
                room = min([abs(x - last) for x in opp_lv if (x > last if ce else x < last)] or [9e9])
                gates["Room ≥1R to opposing level"] = room >= risk_ul
                opt, why = pick_contract(ag, inst, u["symbol"], side, last, now, contracts_fn)
                row["option"] = opt
                if not opt:
                    row["underlying_only"] = f"UNDERLYING SETUP ONLY — {why}"
                    gates["Verified option contract"] = False
                else:
                    gates.update({f"Option: {k}": v for k, v in opt["gates"].items()})
                    gates["Fresh option quote"] = bool(opt.get("fresh"))
                    entry = r05(opt["ask"] * (1 + CFG["slippage"]))
                    try:
                        T = years_to_expiry(opt["expiry"], now.to_pydatetime())
                        sig = iv((opt["bid"] + opt["ask"]) / 2, last, opt["strike"], T, side)
                        stop = r05(max(0.05, bs(inval, opt["strike"], max(T - 1 / 365 / 6, 1e-4), sig, side)))
                    except Exception:
                        stop = r05(entry * 0.7)
                    risk = round((entry - stop) * opt["lot"] + CFG["charges"])
                    opt["plan"] = {"entry": entry, "entry_zone": [opt["ask"], entry], "sl": stop,
                                   "targets": [r05(entry * 1.2), r05(entry * 1.3), r05(entry * 1.4)],
                                   "risk": risk, "risk_ok": risk <= CFG["risk_cap"], "iv": opt.get("iv")}
                    from .fullscan import apply_money
                    apply_money(opt, last, now, None, intraday=True)
                    gates["Planned risk ≤ ₹2,500"] = risk <= CFG["risk_cap"]
                    gates["T1 (₹1,200+) realistic"] = bool(opt["plan"].get("reward_ok"))
                row["gates"] = gates
                row["executable"] = all(gates.values()) and grade in ("A+", "STRONG") and model == "A"
                row["research"] = model == "B"
                row["ul_inval"] = round(inval, 2)
                if row["executable"] or (model == "B" and opt and all(v for k, v in gates.items() if k != "Regime allows")):
                    ST["alerts"].add(key)
                    signals.append(row)
    order = ["ENTRY CONFIRMED", "RETEST HELD", "RETEST PENDING", "SWEEP+CHOCH", "BREAKOUT", "WEAK DISPLACEMENT", "EXPIRED", "INVALIDATED"]
    rows.sort(key=lambda r: (order.index(r["state"]) if r["state"] in order else 9, -r["score"]))
    ST["last"] = now.strftime("%H:%M")
    return {"regime": rg, "protect": protect, "rows": rows[:40], "signals": signals, "last": ST["last"],
            "want_side": want_side, "checked": len(stage), "cfg": CFG}
