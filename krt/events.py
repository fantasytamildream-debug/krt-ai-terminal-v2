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


def nse_calendar(fno):
    """NSE event calendar → [{symbol, date}] (F&O மட்டும், financial results)."""
    out = []
    for x in _nse("/api/event-calendar") or []:
        sym, purp = str(x.get("symbol") or "").upper(), str(x.get("purpose") or "") + " " + str(x.get("bm_desc") or "")
        if sym in fno and re.search(r"result", purp, re.I):
            try:
                d = pd.Timestamp(x.get("date")).date()
            except Exception:
                continue
            out.append({"symbol": sym, "date": str(d), "src": "NSE"})
    return out


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
    """NSE (6 மணி நேரத்துக்கு ஒருமுறை) + news (ஒவ்வொரு run) → STORE results_cal-ல் merge (manual entries எப்போதும் இருக்கும்)."""
    from .calls import CALLS_LOCK
    found = []
    if time.time() - CACHE["nse_t"] > 6 * 3600:
        CACHE["nse_t"] = time.time()
        try:
            found += nse_calendar(fno)
            STATE["nse_err"] = None
        except Exception as e:
            STATE["nse_err"] = f"NSE calendar கிடைக்கல ({str(e)[:60]}) — news + manual மட்டும்"
    found += news_dates(news_items, today)
    with CALLS_LOCK:
        D = store.load()
        C = D.setdefault("results_cal", {})
        for x in found:
            k = f"{x['symbol']}|{x['date']}"
            if k not in C:
                C[k] = {**x, "added": str(today)}
                store.dirty = True
        for k in [k for k, v in C.items() if v["date"] < str(today - dt.timedelta(days=10))]:
            C.pop(k, None)
            store.dirty = True
    return C


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
    return {"lean": lean, "side": side, "score": sc, "why": why, "warn": warn, "watch": watch, "normal": norm, "ratio": big,
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
        if days > 7 or days < -3:
            continue
        s = x["symbol"]
        b = bars.get(s) or {}
        cl = b.get("c") or []
        q = lq.get(s) or {}
        spot = q.get("ltp") or (cl[-1] if cl else None)
        r20 = round((cl[-1] / cl[-21] - 1) * 100, 2) if len(cl) > 21 else None
        hi52 = max((b.get("h") or [0])[-250:]) if b.get("h") else None
        row = {**x, "days": days, "spot": spot, "r20": r20, "oi": oi.get(s), "near_high": bool(hi52 and spot and (hi52 - spot) / hi52 <= 0.03)}
        ik = f"{s}|{today}"
        if live and ag and spot and 0 <= days <= 3 and ik not in IM:
            try:
                IM[ik] = implied_move(ag, inst, s, spot, now)
            except Exception:
                IM[ik] = None
        row["implied"] = IM.get(ik)
        if days > 1:
            row["plan"] = "Results-க்கு முன் — பெரிய position வேண்டாம். Expected move-ஐ விட stock ஏற்கனவே ஓடியிருந்தா 'buy rumour sell news' ஆகலாம்."
        elif days == 1:
            row["plan"] = "நாளை results — இன்று overnight naked option வேண்டாம் (gap + IV crush). Results வந்த பிறகு direction confirm ஆனா மட்டும்."
        elif days in (0, -1):
            hm = now.strftime("%H:%M")
            rk = f"{s}|{today}"
            if live and "09:30" <= hm <= "15:15" and rk not in R15 and q.get("high") and q.get("low"):
                R15[rk] = {"h": q["high"], "l": q["low"], "t": hm}
            r = R15.get(rk)
            if r and spot:
                vr = q.get("vol_ratio") or 0
                if spot > r["h"] and vr >= 1.5:
                    row["setup"] = {"side": "CE", "txt": f"✅ Results reaction ⬆ — முதல் 15-min high {r['h']} மேல் + volume {vr}× → CE"}
                elif spot < r["l"] and vr >= 1.5:
                    row["setup"] = {"side": "PE", "txt": f"✅ Results reaction ⬇ — முதல் 15-min low {r['l']} கீழ் + volume {vr}× → PE"}
                else:
                    row["setup"] = {"side": None, "txt": f"⏳ {r['h']} மேல் (CE) / {r['l']} கீழ் (PE) 5-min close + volume ≥1.5× வரும் வரை காத்திருங்க"}
            row["plan"] = "Results நாள் — முதல் 15 நிமிடம் (9:15–9:30) பாருங்க, அதன் high / low உடைஞ்ச பக்கம் மட்டும் (volume-உடன்)."
            if days == -1 and len(cl) >= 2:
                row["reaction"] = round((cl[-1] / cl[-2] - 1) * 100, 2)
        else:
            if len(cl) >= 2:
                row["reaction"] = round((cl[-1] / cl[-2] - 1) * 100, 2)
            row["plan"] = "Results முடிஞ்சது."
        RH = store.load().setdefault("results_hist", {})
        if row.get("reaction") is not None and days < 0:              # remember every reaction → next quarter's analysis uses it
            L = RH.setdefault(s, [])
            if not any(p["date"] == x["date"] for p in L):
                L.append({"date": x["date"], "reaction": row["reaction"], "r20": r20})
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
