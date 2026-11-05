"""📰 NEWS RADAR — F&O stocks news (Moneycontrol / ET / Business Standard RSS + Google News: results · orders · brokerage · deals)
→ news score → முன்கூட்டியே FOCUS list (levels-உடன் alert) → விலை news பக்கம் level-ஐ volume-உடன் உடைச்சா மட்டும் CALL.

நேர்மையா: இது keyword scoring (results beat / profit jumps / order win / upgrade …) — LLM இல்லை. News மட்டும் வச்சு call இல்லை:
price + volume confirmation கட்டாயம். X (Twitter) free API இல்லை → சேர்க்கல. Paper / alert மட்டும்.
"""
import re
import threading
import time

import pandas as pd

from .news import _get, match

QUERIES = ["NSE Q2 results net profit", "quarterly results profit jumps revenue NSE", "bags order worth crore", "wins order contract crore NSE",
           "brokerage upgrade target price stock India", "downgrade target cut stock India", "block deal NSE shares", "results miss estimates profit falls"]
# (pattern, weight, event) — regex, பெரிய எழுத்து வேற்றுமை இல்லை
RULES = [
    (r"net profit (jumps|surges|soars|rises|up|grows|doubles)|profit (jumps|surges|soars|doubles)|pat (jumps|rises|up)", 3, "RESULTS"),
    (r"beats? (estimates|expectations|street)|better[- ]than[- ]expected|strong (q[1-4]|quarter|results|numbers)|record (profit|revenue|quarter)", 3, "RESULTS"),
    (r"revenue (jumps|rises|grows|up|surges)|ebitda (jumps|rises|up|grows)|margin (expands|improves)", 2, "RESULTS"),
    (r"net profit (falls|drops|declines|slumps|plunges|down)|profit (falls|drops|slumps|plunges)|net loss|loss widens|swings to loss", -3, "RESULTS"),
    (r"miss(es)? (estimates|expectations)|weak (q[1-4]|quarter|results|numbers)|disappoint", -3, "RESULTS"),
    (r"revenue (falls|drops|declines)|margin (contracts|shrinks|falls)", -2, "RESULTS"),
    (r"bags?|wins? (order|contract)|order (win|worth|inflow)|secures? (order|contract)|l1 bidder|letter of award", 2, "ORDER"),
    (r"upgrade|target (price )?(raised|hiked|increased)|buy rating|outperform|overweight", 2, "BROKER"),
    (r"downgrade|target (price )?(cut|lowered|reduced)|sell rating|underperform|underweight", -2, "BROKER"),
    (r"buyback|bonus issue|stock split|dividend", 1, "CORP"),
    (r"block deal|bulk deal", 0, "DEAL"),
    (r"stake sale|ofs\b|offer for sale|promoter (sells|pledge)", -2, "DEAL"),
    (r"sebi (probe|order|notice|penalty)|raid|fraud|default|penalty|ban\b|show cause|resigns?", -3, "REG"),
    (r"approval|usfda (nod|approval)|gets nod|launch(es)?", 1, "CORP"),
]
# 📊 Index / market news → NIFTY · BANKNIFTY (bias மட்டும், call இல்லை)
MARKET = [
    (r"rbi (cuts?|slashes|lowers) (repo|rates?)|rate cut|fed (cuts?|lowers)|dovish", 3), (r"rbi (hikes?|raises)|rate hike|fed (hikes?|raises)|hawkish", -3),
    (r"fiis? (buy|bought|net buyers|pour)|foreign investors (buy|pour)|dii buying", 2), (r"fiis? (sell|sold|net sellers|dump|pull out)|foreign outflow", -2),
    (r"gdp (grows|rises|beats|jumps)|inflation (eases|cools|falls)|cpi (eases|falls)", 2), (r"gdp (slows|contracts|misses)|inflation (rises|jumps|surges)|cpi (rises|jumps)", -2),
    (r"(sensex|nifty|markets?) (rall|surge|jump|soar|climb|hit record|record high|gain)", 2), (r"(sensex|nifty|markets?) (crash|plunge|tank|slump|fall|tumble|bleed|sink)", -2),
    (r"wall street (rall|gain|surge|jump)|dow (gains|jumps|rallies)|nasdaq (gains|jumps|rallies)|gift nifty (up|higher|signals gains)", 1),
    (r"wall street (fall|slump|tumble|sink)|dow (falls|slumps|tumbles)|nasdaq (falls|slumps|tumbles)|gift nifty (down|lower|signals)", -1),
    (r"crude (falls|slumps|eases|drops)|oil prices? (fall|drop|ease)", 1), (r"crude (surges|jumps|spikes|soars)|oil prices? (surge|jump|spike)", -1),
    (r"war|missile|attack|tariff (hike|threat)|sanctions?", -2), (r"ceasefire|trade deal|peace (deal|talks)", 2),
]
BANK = r"rbi|repo|bank|banking|nbfc|credit growth|npa|psu bank|hdfc bank|icici bank|sbi\b|kotak|axis bank"
CFG = {"min_score": 3, "hours": 20, "max_day": 4, "start": "09:30", "end": "14:30", "vol_x": 1.5, "max_focus": 12, "q_every": 600}
STATE = {"time": None, "focus": [], "err": None, "calls": [], "alerts": [], "log": []}
CACHE = {"q_t": 0, "q_items": []}
LK = threading.Lock()
INDEXES = ("NIFTY", "BANKNIFTY")


def score(title):
    t = title.lower()
    s, ev, hit = 0, None, []
    for pat, w, e in RULES:
        if re.search(pat, t):
            s += w
            hit.append(e)
            if ev is None or abs(w) >= 3:
                ev = e
    return s, ev or (hit[0] if hit else None)


def mscore(title):
    t = title.lower()
    return sum(w for pat, w in MARKET if re.search(pat, t))


def collect(news_items, fno):
    """news.py items + results/orders queries → [{symbol, title, source, ts, time, score, event}] கடைசி CFG['hours']."""
    now = time.time()
    if now - CACHE["q_t"] >= CFG["q_every"]:
        items = []
        for q in QUERIES:
            try:
                items += _get("https://news.google.com/rss/search?q=" + re.sub(r"\s+", "+", q) + "+when:1d&hl=en-IN&gl=IN&ceid=IN:en", "Google News")[:25]
            except Exception:
                pass
            time.sleep(0.3)
        CACHE.update(q_t=now, q_items=items)
    out, seen = [], set()
    cut = now - CFG["hours"] * 3600
    for x in list(news_items or []) + [{"title": i["title"], "link": i["link"], "source": i["source"],
                                        "ts": i["dt"].timestamp() if i.get("dt") else 0,
                                        "time": i["dt"].strftime("%d-%m %I:%M %p") if i.get("dt") else "",
                                        "symbols": match(i["title"], fno)} for i in CACHE["q_items"]]:
        k = (x.get("title") or "")[:90]
        if not k or k in seen or (x.get("ts") or 0) < cut:
            continue
        seen.add(k)
        sc, ev = score(k)
        syms = list((x.get("symbols") or [])[:2])
        ms = mscore(k)
        if ms:                                          # market-wide news → index bias
            syms += ["BANKNIFTY"] if re.search(BANK, k.lower()) else []
            syms += ["NIFTY"]
            if not sc:
                sc, ev = ms, "MARKET"
        if not sc:
            continue
        for sym in syms[:3]:
            out.append({"symbol": sym, "title": x["title"], "source": x.get("source"), "link": x.get("link"), "ts": x.get("ts") or 0,
                        "time": x.get("time"), "score": ms if sym in INDEXES and ms else sc, "event": "MARKET" if sym in INDEXES else ev})
    out.sort(key=lambda x: -x["ts"])
    return out


def build_focus(items, levels, live_q, mdir=None):
    """Symbol-க்கு news score கூட்டு → |score| ≥ min → CE / PE focus + trigger levels (PDH / PDL / day range)."""
    agg = {}
    for x in items:
        a = agg.setdefault(x["symbol"], {"symbol": x["symbol"], "score": 0, "news": [], "events": set()})
        a["score"] += x["score"]
        a["events"].add(x["event"])
        if len(a["news"]) < 4:
            a["news"].append(x)
    out = []
    for s, a in agg.items():
        if abs(a["score"]) < CFG["min_score"]:
            continue
        if s in INDEXES:                                 # index = bias மட்டும் (news-ஐ வச்சு index call இல்லை)
            side = "CE" if a["score"] > 0 else "PE"
            out.append({"symbol": s, "side": side, "score": a["score"], "events": ["MARKET"], "news": a["news"], "index": True, "status": "BIAS",
                        "why": f"Market news {'positive' if side == 'CE' else 'negative'} → {s} setups-ல் {side} பக்கம் மட்டும் பாருங்க (index call news-ஐ வச்சு இல்லை)"})
            continue
        side = "CE" if a["score"] > 0 else "PE"
        lv, q = (levels or {}).get(s) or {}, (live_q or {}).get(s) or {}
        ltp, vr = q.get("ltp"), q.get("vol_ratio") or 0
        pdh, pdl = lv.get("PDH"), lv.get("PDL")
        dh, dl = q.get("high"), q.get("low")
        # Trigger = PDH (CE) / PDL (PE). (Day high-ஐ trigger-ஆ வச்சா LTP அதை தாண்டவே முடியாது → confirm ஆகாது.)
        trig = pdh if side == "CE" else pdl
        sl = (pdl or dl) if side == "CE" else (pdh or dh)
        brk = bool(ltp and trig and ((ltp > trig) if side == "CE" else (ltp < trig)))
        late = bool(brk and abs(ltp - trig) / trig * 100 > 2.0)
        against = bool(mdir and (mdir == "UP") != (side == "CE"))
        st = "AGAINST" if against else "LATE" if late else ("CONFIRMED" if brk and vr >= CFG["vol_x"] else "WATCH")
        out.append({"symbol": s, "side": side, "score": a["score"], "events": sorted(e for e in a["events"] if e), "news": a["news"],
                    "ltp": ltp, "pct": q.get("pct"), "vr": round(vr, 2) if vr else None, "pdh": pdh, "pdl": pdl, "trigger": round(trig, 2) if trig else None,
                    "ul_sl": round(sl, 2) if sl else None, "status": st,
                    "why": (f"Market திசை {'⬆' if mdir == 'UP' else '⬇'} எதிர்" if against else
                            f"Level {trig:.2f}-ஐ விட 2%+ ஓடிடுச்சு — late, chase வேண்டாம் (pullback-க்கு காத்திருங்க)" if late else
                            f"{'மேல்' if side == 'CE' else 'கீழ்'} {trig:.2f} உடைஞ்சாச்சு · volume {vr:.1f}×" if brk else
                            f"{'மேல்' if side == 'CE' else 'கீழ்'} {trig:.2f} உடைஞ்சா entry (volume ≥{CFG['vol_x']}×)" if trig else "levels இன்னும் வரல")})
    out.sort(key=lambda r: (not r.get("index"), r["status"] != "CONFIRMED", -abs(r["score"])))
    return out[:CFG["max_focus"]]


def run(ag, inst, news_items, now, send=None):
    """news_loop-ல் (60 sec) கூப்பிடும். Focus → alert (ஒருமுறை) · CONFIRMED → NEWS call (9:30–2:30, நாளைக்கு max 4)."""
    from . import fullscan as FS
    from .calls import CALLS_LOCK, STORE, _new
    with LK:
        try:
            fno = (FS.C.get("fno") or []) or list((FS.C.get("levels") or {}).keys())
            items = collect(news_items, fno)
            try:
                from .ai import STATE as AST
                mdir = (AST.get("risk") or {}).get("dir")
            except Exception:
                mdir = None
            focus = build_focus(items, FS.C.get("levels") or {}, FS.C.get("live_q") or {}, mdir)
            day, hm = str(now.date()), now.strftime("%H:%M")
            al = STATE.setdefault("alerted", {})
            for k in [k for k in al if not k.startswith(day)]:
                al.pop(k, None)
            for f in focus:
                key = f"{day}|{f['symbol']}|{f['side']}|{f['status'] == 'CONFIRMED'}"
                if key in al:
                    continue
                al[key] = hm
                msg = (f"📰 NEWS FOCUS · {f['symbol']} {f['side']} (score {f['score']:+d} · {', '.join(f['events'])})\n{f['news'][0]['title'][:140]}\n"
                       f"👉 {f['why']}" + (f" · SL (stock) {f['ul_sl']}" if f.get("ul_sl") else ""))
                STATE["alerts"].insert(0, {"time": hm, "date": day, "symbol": f["symbol"], "side": f["side"], "text": msg})
                if send:
                    try:
                        send(msg, f"news|{key}")
                    except Exception:
                        pass
            del STATE["alerts"][40:]
            # CONFIRMED → call
            if ag and CFG["start"] <= hm <= CFG["end"]:
                with CALLS_LOCK:
                    mine = [c for c in (STORE.load().get("calls") or {}).values() if c.get("date") == day and c.get("kind") == "NEWS"]
                for f in [f for f in focus if f["status"] == "CONFIRMED"]:
                    if len(mine) >= CFG["max_day"] or any(c["symbol"] == f["symbol"] for c in mine):
                        continue
                    rr = {"symbol": f["symbol"], "side": f["side"], "price": f["ltp"], "sl": f["ul_sl"], "min_days": 3,
                          "targets": [], "score": min(100, 60 + 8 * abs(f["score"])), "stars": 4, "vol_ratio": f["vr"],
                          "reasons": [f"📰 {f['news'][0]['title'][:120]}", f"News score {f['score']:+d} · {', '.join(f['events'])} · {f['why']}"]}
                    FS.pick_options(ag, inst, [rr])
                    o = rr.get("option") or {}
                    if not o.get("token"):
                        STATE["log"].insert(0, {"time": hm, "symbol": f["symbol"], "result": "⛔ option இல்லை"})
                        continue
                    FS.attach_plan(rr, o, now, "📰 News Radar")
                    o = rr.get("option") or o
                    with CALLS_LOCK:
                        d = STORE.load()
                        c = _new("NEWS", "📰 News Radar", rr, o, now, day)
                        if c and c["id"] not in d["calls"] and not c.get("shadow"):
                            c.update(source_label="📰 News Radar", intraday=True, news={"score": f["score"], "events": f["events"], "title": f["news"][0]["title"]})
                            d["calls"][c["id"]] = c
                            STORE.dirty = True
                            mine.append(c)
                            STATE["log"].insert(0, {"time": hm, "symbol": f["symbol"], "result": "✅ CALL"})
                        else:
                            STATE["log"].insert(0, {"time": hm, "symbol": f["symbol"], "result": "⛔ quality gate / duplicate"})
                del STATE["log"][30:]
            STATE.update(time=now.strftime("%I:%M:%S %p"), focus=focus, err=None, items=len(items),
                         recent=[{k: x.get(k) for k in ("symbol", "title", "source", "link", "time", "score", "event")} for x in items[:50]])
        except Exception as e:
            STATE["err"] = str(e)[:200]
    return STATE
