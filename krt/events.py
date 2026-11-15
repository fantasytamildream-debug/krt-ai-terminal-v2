"""📅 RESULTS DIARY + 🌅 PRE-OPEN WATCHLIST

Results diary — F&O stocks-ன் results தேதி (NSE event calendar → கிடைக்கலைன்னா news headlines → நீங்க manual-ஆ சேர்க்கலாம்):
  • Expected move = ATM CE + PE premium ÷ spot (options market எதிர்பார்க்கும் move — standard method)
  • Context: 20 நாள் trend · 52-week high/low தூரம் · futures OI buildup
  • Results நாள் / அடுத்த நாள்: முதல் 15-min high / low break + volume ≥1.5× → CE / PE + strike (Greeks selector)
  • முடிந்ததும் உண்மையான move save → அடுத்த முறை அந்த stock-ன் results reaction history
Pre-open — 9:08 NSE pre-open (கிடைச்சா) அல்லது 9:15:30 Angel open price: gap 1–4% + OI / news பக்கம் → watchlist + strike,
  9:15–9:20 candle அந்த பக்கம் hold + volume ஆனா மட்டும் entry.
நேர்மை: NSE site cloud server-ஐ block பண்ணலாம் — அப்போ fallback. Guarantee இல்லை, paper மட்டும்.
"""
import datetime as dt
import re
import time

import pandas as pd

MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
STATE = {"results": [], "preopen": {"time": None, "rows": [], "src": None, "err": None}, "err": None, "nse_err": None}
CACHE = {"nse_t": 0, "news_t": 0}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com/"}


def _nse(path):
    import requests
    s = requests.Session()
    s.get("https://www.nseindia.com/", headers=UA, timeout=10)
    r = s.get("https://www.nseindia.com" + path, headers=UA, timeout=15)
    r.raise_for_status()
    return r.json()


def _pdate(v):
    try:
        return pd.Timestamp(str(v).strip()).date()
    except Exception:
        return None


def nse_calendar(fno):
    """NSE event calendar → [{symbol, date}] (F&O only, financial results)."""
    out = []
    for x in _nse("/api/event-calendar") or []:
        sym, purp = str(x.get("symbol") or "").upper(), str(x.get("purpose") or "") + " " + str(x.get("bm_desc") or "")
        d = _pdate(x.get("date"))
        if sym in fno and d and re.search(r"result", purp, re.I):
            out.append({"symbol": sym, "date": str(d), "src": "NSE"})
    return out


def nse_board(fno):
    """NSE board-meeting intimations (results are decided at a board meeting) → [{symbol, date}]."""
    out = []
    js = _nse("/api/corporate-board-meetings?index=equities") or []
    for x in (js.get("data") if isinstance(js, dict) else js) or []:
        sym = str(x.get("bm_symbol") or x.get("symbol") or "").upper()
        purp = str(x.get("bm_purpose") or "") + " " + str(x.get("bm_desc") or "")
        d = _pdate(x.get("bm_date") or x.get("date"))
        if sym in fno and d and re.search(r"result", purp, re.I):
            out.append({"symbol": sym, "date": str(d), "src": "NSE board"})
    return out


def bse_forthcoming(fno):
    """BSE 'forthcoming results' list (backup when NSE blocks cloud servers). BSE scrip id = NSE symbol for most F&O stocks."""
    import requests
    h = {**UA, "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com"}
    r = requests.get("https://api.bseindia.com/BseIndiaAPI/api/Corpforthresults/w", headers=h, timeout=15)
    r.raise_for_status()
    js = r.json()
    rows = js if isinstance(js, list) else (js.get("Table") or js.get("data") or []) if isinstance(js, dict) else []
    out = []
    for x in rows:
        if not isinstance(x, dict):
            continue
        k = {str(a).lower(): v for a, v in x.items()}
        sym = str(k.get("short_name") or k.get("scrip_id") or k.get("symbol") or "").upper().strip()
        d = _pdate(k.get("meeting_date") or k.get("result_date") or k.get("date"))
        if sym in fno and d:
            out.append({"symbol": sym, "date": str(d), "src": "BSE"})
    return out


SOURCES = (("NSE calendar", nse_calendar), ("NSE board meetings", nse_board), ("BSE forthcoming", bse_forthcoming))


DATE_RX = re.compile(r"\b(?:on|dated?)\s+(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|"
                     r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)


def news_dates(items, today):
    """"X Q2 results on Nov 12" / "board meeting on 12 November to consider results" மாதிரி headlines → தேதி."""
    out = []
    for x in items or []:
        t = x.get("title") or ""
        if not re.search(r"result|earnings|board meeting|q[1-4]\b", t, re.I):
            continue
        m = DATE_RX.search(t)
        if not m:
            continue
        dd, mm = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        try:
            d = dt.date(today.year, MON[mm.lower()[:3]], int(dd))
        except Exception:
            continue
        if d < today - dt.timedelta(days=2):
            d = dt.date(today.year + 1, d.month, d.day)
        for s in (x.get("symbols") or [])[:1]:
            out.append({"symbol": s, "date": str(d), "src": "news", "title": t[:140]})
    return out


def implied_move(ag, inst, sym, spot, now):
    from .instruments import contracts
    exp, rows = contracts(inst, sym, 1)
    if not rows or not spot:
        return None
    k = min({float(r[3]) for r in rows}, key=lambda x: abs(x - spot))
    ce = next((r for r in rows if float(r[3]) == k and r[4] == "CE"), None)
    pe = next((r for r in rows if float(r[3]) == k and r[4] == "PE"), None)
    if not ce or not pe:
        return None
    ex = ce[6] if len(ce) > 6 else "NFO"
    q = ag.quotes({ex: [ce[0], pe[0]]}) or {}
    c, p = float((q.get(ce[0]) or {}).get("ltp") or 0), float((q.get(pe[0]) or {}).get("ltp") or 0)
    if not (c and p):
        return None
    return {"strike": k, "expiry": exp, "straddle": round(c + p, 2), "pct": round((c + p) / spot * 100, 2)}


def refresh_calendar(store, fno, news_items, today):
    """NSE + NSE board meetings + BSE (each every 2 h when it works, retry in 30 min when it fails) + news headlines (every run)
    → merged into STORE results_cal (manual entries always stay). Runs every day, weekends too, so Monday's list is ready."""
    from .calls import CALLS_LOCK
    found = []
    src = STATE.setdefault("src", {})
    for name, fn in SOURCES:
        nxt = CACHE.get("next|" + name, 0)
        if time.time() < nxt:
            continue
        try:
            got = fn(fno)
            src[name] = {"ok": True, "n": len(got), "time": time.strftime("%H:%M")}
            CACHE["next|" + name] = time.time() + 2 * 3600
            found += got
        except Exception as e:
            src[name] = {"ok": False, "err": str(e)[:70], "time": time.strftime("%H:%M")}
            CACHE["next|" + name] = time.time() + 1800
    nd = news_dates(news_items, today)
    src["News headlines"] = {"ok": True, "n": len(nd), "time": time.strftime("%H:%M")}
    found += nd
    bad = [k for k, v in src.items() if not v.get("ok")]
    STATE["nse_err"] = (f"{', '.join(bad)} not reachable from the server right now — using the other sources + news + manual" if bad else None)
    with CALLS_LOCK:
        D = store.load()
        C = D.setdefault("results_cal", {})
        for x in found:
            k = f"{x['symbol']}|{x['date']}"
            if k not in C:
                C[k] = {**x, "added": str(today)}
                store.dirty = True
            elif x["src"] != "news" and C[k].get("src") == "news":
                C[k]["src"] = x["src"]                    # confirmed by an exchange
                store.dirty = True
        for k in [k for k, v in C.items() if v["date"] < str(today - dt.timedelta(days=10))]:
            C.pop(k, None)
            store.dirty = True
    return C


def fno_names(bars, inst):
    """F&O stock list — from scan bars, else from the instrument master (so the calendar works right after a restart / on weekends)."""
    names = set((bars or {}).keys())
    if not names:
        names = {k for k in ((inst or {}).get("opts") or {}) if k not in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX", "NIFTYNXT50")}
    return names


def add_manual(store, sym, date):
    from .calls import CALLS_LOCK
    d = str(pd.Timestamp(date).date())
    with CALLS_LOCK:
        D = store.load()
        D.setdefault("results_cal", {})[f"{sym}|{d}"] = {"symbol": sym, "date": d, "src": "manual", "added": str(dt.date.today())}
        store.dirty = True
    return d


def outlook(row, cl, past):
    """🤖 Pre-results analysis (rule-based, honest — no one can know the numbers): trend into results · near 52w high ·
    OI build-up · options-implied move vs the stock's normal daily move · how this stock reacted to its past results
    → LEAN UP / LEAN DOWN / NEUTRAL + what to watch on results day (CE above the first 15-min high, PE below the low)."""
    sc, why = 0, []
    r20 = row.get("r20")
    r5 = round((cl[-1] / cl[-6] - 1) * 100, 2) if len(cl) > 6 else None
    if r20 is not None:
        if r20 >= 5:
            sc += 1
            why.append(f"strong run-up into results (+{r20}% in 20 days)")
        elif r20 <= -5:
            sc -= 1
            why.append(f"weak into results ({r20}% in 20 days)")
    if r5 is not None and abs(r5) >= 2:
        sc += 1 if r5 > 0 else -1
        why.append(f"last 5 days {r5:+}%")
    if row.get("near_high"):
        sc += 1
        why.append("near 52-week high — buyers in control")
    oi = str(row.get("oi") or "")
    if oi in ("Long Built Up", "Short Covering"):
        sc += 1
        why.append(f"futures OI: {oi}")
    elif oi in ("Short Built Up", "Long Unwinding"):
        sc -= 1
        why.append(f"futures OI: {oi}")
    rets = [abs(cl[i] / cl[i - 1] - 1) * 100 for i in range(max(1, len(cl) - 20), len(cl))] if len(cl) > 2 else []
    norm = round(sum(rets) / len(rets), 2) if rets else None
    im = (row.get("implied") or {}).get("pct")
    big = None
    if im and norm:
        big = round(im / norm, 1)
        why.append(f"options expect ±{im}% (≈{big}× a normal day ±{norm}%)" + (" — a big move is priced in" if big >= 3 else ""))
    reacts = [p["reaction"] for p in past if p.get("reaction") is not None][-6:]
    if reacts:
        up = sum(1 for x in reacts if x > 0)
        avg = round(sum(abs(x) for x in reacts) / len(reacts), 2)
        why.append(f"past results: {up}/{len(reacts)} up days · average move ±{avg}%")
        if len(reacts) >= 3:
            sc += 1 if up / len(reacts) >= 0.67 else -1 if up / len(reacts) <= 0.33 else 0
    sec = row.get("sector")
    if sec and sec.get("score") is not None:
        if sec["score"] >= 60:
            sc += 1
            why.append(f"sector {sec['name']} strong today (mood {sec['score']})")
        elif sec["score"] <= 40:
            sc -= 1
            why.append(f"sector {sec['name']} weak today (mood {sec['score']})")
    drift = [p.get("drift") for p in past if p.get("drift") is not None][-4:]
    if len(drift) >= 2:
        why.append(f"after past results the stock moved {', '.join(f'{x:+}%' for x in drift)} over the next 3 days")
    warn = None
    if r20 is not None and im and r20 >= 2 * im:
        warn = "⚠ already ran more than 2× the expected move — 'buy the rumour, sell the news' risk (a good result can still fall)"
    elif r20 is not None and im and r20 <= -2 * im:
        warn = "⚠ already fell more than 2× the expected move — a decent result can bounce sharply (short covering)"
    lean = "LEAN UP" if sc >= 2 else "LEAN DOWN" if sc <= -2 else "NEUTRAL"
    side = "CE" if lean == "LEAN UP" else "PE" if lean == "LEAN DOWN" else None
    watch = ("Results day: wait 9:15–9:30. 5-min close ABOVE the first 15-min high with volume ≥1.5× → CE (ATM / 1 ITM). "
             "Close BELOW the 15-min low with volume → PE. Target ≈ the options-implied move"
             + (f" (±{im}%)" if im else "") + ". Do not buy options the day BEFORE results — IV crush can cut premium 20–40% even if you are right.")
    expect = ("POSITIVE reaction more likely" if lean == "LEAN UP" else "NEGATIVE reaction more likely" if lean == "LEAN DOWN"
              else "MIXED — could go either way")
    if side:
        adv = (f"Advance view: {side}. Safest: buy {side} only AFTER results, when the 5-min candle closes "
               f"{'above the first 15-min high' if side == 'CE' else 'below the first 15-min low'} with volume. "
               f"If you take it before results: 1 lot only, next-month ATM / 1-ITM strike, and accept that IV crush can cut 20–40% even if the view is right.")
    else:
        adv = "Advance view: no side — signals are mixed. Do not take a position before results; trade only the results-day 15-min break."
    return {"lean": lean, "side": side, "score": sc, "expect": expect, "advance": adv, "why": why, "warn": warn, "watch": watch, "normal": norm, "ratio": big,
            "past": reacts, "conf": "low" if abs(sc) <= 1 else "medium" if abs(sc) <= 3 else "higher"}


def diary(store, ag, inst, now, full=None, live=True):
    """Results diary rows — 7 நாள் வரை upcoming + 3 நாள் முன் முடிந்தவை (reaction-உடன்)."""
    from . import fullscan as FS
    today = now.date()
    C = (store.load().get("results_cal")) or {}
    lq = FS.C.get("live_q") or {}
    bars = FS.C.get("bars") or {}
    oi = {}
    for kind, xs in ((full or {}).get("oi_buildup") or {}).items():
        for x in xs:
            oi[x["symbol"]] = kind
    IM = STATE.setdefault("im", {})
    R15 = STATE.setdefault("r15", {})
    out = []
    for k, x in sorted(C.items(), key=lambda kv: kv[1]["date"]):
        d = pd.Timestamp(x["date"]).date()
        days = (d - today).days
        if days > 30 or days < -3:
            continue
        s = x["symbol"]
        b = bars.get(s) or {}
        cl = b.get("c") or []
        q = lq.get(s) or {}
        spot = q.get("ltp") or (cl[-1] if cl else None)
        r20 = round((cl[-1] / cl[-21] - 1) * 100, 2) if len(cl) > 21 else None
        hi52 = max((b.get("h") or [0])[-250:]) if b.get("h") else None
        row = {**x, "days": days, "spot": spot, "r20": r20, "oi": oi.get(s), "near_high": bool(hi52 and spot and (hi52 - spot) / hi52 <= 0.03)}
        try:
            from .money import SECTOR as _SEC
            from .mood import STATE as _MS
            sn = _SEC.get(s)
            sr = next((z for z in _MS.get("sectors") or [] if z.get("sector") == sn), None) if sn else None
            row["sector"] = {"name": sn, "score": (sr or {}).get("score")} if sn else None
        except Exception:
            row["sector"] = None
        ik = f"{s}|{today}"
        if live and ag and spot and 0 <= days <= 3 and ik not in IM:
            try:
                IM[ik] = implied_move(ag, inst, s, spot, now)
            except Exception:
                IM[ik] = None
        row["implied"] = IM.get(ik)
        if days > 1:
            row["plan"] = "Before results — no big position. If the stock already ran more than the expected move, 'buy the rumour, sell the news' can happen."
        elif days == 1:
            row["plan"] = "Results tomorrow — no overnight naked option today (gap + IV crush). Trade only after results confirm the direction."
        elif days in (0, -1):
            hm = now.strftime("%H:%M")
            rk = f"{s}|{today}"
            if live and "09:30" <= hm <= "15:15" and rk not in R15 and q.get("high") and q.get("low"):
                R15[rk] = {"h": q["high"], "l": q["low"], "t": hm}
            r = R15.get(rk)
            if r and spot:
                vr = q.get("vol_ratio") or 0
                if spot > r["h"] and vr >= 1.5:
                    row["setup"] = {"side": "CE", "txt": f"✅ Results reaction UP — above the first 15-min high {r['h']} with volume {vr}× → CE"}
                elif spot < r["l"] and vr >= 1.5:
                    row["setup"] = {"side": "PE", "txt": f"✅ Results reaction DOWN — below the first 15-min low {r['l']} with volume {vr}× → PE"}
                else:
                    row["setup"] = {"side": None, "txt": f"⏳ Wait for a 5-min close above {r['h']} (CE) or below {r['l']} (PE) with volume ≥1.5×"}
            row["plan"] = "Results day — watch the first 15 minutes (9:15–9:30); trade only the side whose high / low breaks, with volume."
            if days == -1 and len(cl) >= 2:
                row["reaction"] = round((cl[-1] / cl[-2] - 1) * 100, 2)
        else:
            if len(cl) >= 2:
                row["reaction"] = round((cl[-1] / cl[-2] - 1) * 100, 2)
            row["plan"] = "Results done."
        if days <= -3 and len(cl) >= 4:
            row["drift"] = round((cl[-1] / cl[-4] - 1) * 100, 2)
        RH = store.load().setdefault("results_hist", {})
        if row.get("reaction") is not None and days < 0:              # remember every reaction → next quarter's analysis uses it
            L = RH.setdefault(s, [])
            if not any(p["date"] == x["date"] for p in L):
                L.append({"date": x["date"], "reaction": row["reaction"], "r20": r20})
                store.dirty = True
            if row.get("drift") is not None:
                for p_ in L:
                    if p_["date"] == x["date"] and p_.get("drift") is None:
                        p_["drift"] = row["drift"]
                        store.dirty = True
        if days >= 0:
            row["ai"] = outlook(row, cl, [p for p in RH.get(s, []) if p["date"] != x["date"]])
        out.append(row)
    STATE["results"] = out
    return out


def preopen_nse(fno):
    j = _nse("/api/market-data-pre-open?key=FO")
    out = []
    for x in (j or {}).get("data") or []:
        m = x.get("metadata") or {}
        s = str(m.get("symbol") or "").upper()
        if s in fno and m.get("pChange") is not None:
            out.append({"symbol": s, "gap": float(m["pChange"]), "iep": m.get("iep") or m.get("lastPrice"), "pvol": (x.get("detail") or {}).get("preOpenMarket", {}).get("totalTradedVolume")})
    return out


def preopen_angel(live_q, bars):
    out = []
    for s, q in (live_q or {}).items():
        b = (bars or {}).get(s) or {}
        cl = b.get("c") or []
        o = q.get("open")
        if o and cl:
            out.append({"symbol": s, "gap": round((o / cl[-1] - 1) * 100, 2), "iep": o, "pvol": q.get("volume")})
    return out


def preopen(now, full=None, news=None):
    """9:08–9:14 NSE pre-open · 9:15:30–9:25 Angel open fallback → gap 1–4% + OI / news பக்கம் → watchlist (CE / PE)."""
    from . import fullscan as FS
    P = STATE["preopen"]
    hm = now.strftime("%H:%M")
    if P.get("date") == str(now.date()) and P.get("src") == "NSE" and hm < "09:15":
        return P
    rows, src = [], None
    fno = set((FS.C.get("bars") or {}).keys())
    if "09:08" <= hm < "09:15":
        try:
            rows, src = preopen_nse(fno), "NSE"
            P["err"] = None
        except Exception as e:
            P["err"] = f"NSE pre-open கிடைக்கல ({str(e)[:60]}) — 9:15:30-க்கு Angel open price-ல் இருந்து வரும்"
    elif "09:15" <= hm <= "09:25":
        rows, src = preopen_angel(FS.C.get("live_q") or {}, FS.C.get("bars") or {}), "Angel open"
    if not rows:
        return P
    oi = {}
    for kind, xs in ((full or {}).get("oi_buildup") or {}).items():
        for x in xs:
            oi[x["symbol"]] = kind
    pos_news = {}
    for n in news or []:
        for s in n.get("symbols") or []:
            pos_news[s] = pos_news.get(s, 0) + (1 if n.get("tag") == "POS" else -1 if n.get("tag") == "NEG" else 0)
    sel = []
    for r in rows:
        g = r["gap"]
        if not (1.0 <= abs(g) <= 4.0):
            continue
        side = "CE" if g > 0 else "PE"
        sc = 50 + min(20, abs(g) * 6)
        k = oi.get(r["symbol"], "")
        if (side == "CE" and k in ("Long Built Up", "Short Covering")) or (side == "PE" and k in ("Short Built Up", "Long Unwinding")):
            sc += 15
        nv = pos_news.get(r["symbol"], 0)
        sc += 10 if (nv > 0 and side == "CE") or (nv < 0 and side == "PE") else -10 if nv else 0
        sel.append({**r, "side": side, "score": int(min(100, sc)), "oi": k, "news": nv,
                    "plan": f"9:15–9:20 candle {'open-க்கு மேல் hold' if side == 'CE' else 'open-க்கு கீழ் hold'} + volume ≥1.5× ஆனா மட்டும் {side} · gap {g:+.2f}% (4%-க்கு மேல் = chase வேண்டாம்)"})
    sel.sort(key=lambda r: -r["score"])
    P.update(time=now.strftime("%I:%M %p"), date=str(now.date()), src=src, rows=sel[:12])
    return P
