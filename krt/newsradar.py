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

QUERIES = ["Sensex Nifty today why market", "stock market today Sensex Nifty rally", "Sensex Nifty fall today reason", "GIFT Nifty pre-market today",
           "NSE Q2 results net profit", "quarterly results profit jumps revenue NSE", "bags order worth crore", "wins order contract crore NSE",
           "brokerage upgrade target price stock India", "downgrade target cut stock India", "block deal NSE shares", "results miss estimates profit falls"]
# (pattern, weight, event) — regex, பெரிய எழுத்து வேற்றுமை இல்லை
RULES = [
    (r"net profit (jumps|surges|soars|rises|up|grows|doubles)|profit (jumps|surges|soars|doubles)|pat (jumps|rises|up)", 3, "RESULTS"),
    (r"beats? (estimates|expectations|street)|better[- ]than[- ]expected|strong (q[1-4]|quarter|results|numbers)|record (profit|revenue|quarter)", 3, "RESULTS"),
    (r"revenue (jumps|rises|grows|up|surges)|ebitda (jumps|rises|up|grows)|margin (expands|improves)", 2, "RESULTS"),
    (r"net profit (falls|drops|declines|slumps|plunges|down)|profit (falls|drops|slumps|plunges)|net loss|loss widens|swings to loss", -3, "RESULTS"),
    (r"miss(es)? (estimates|expectations)|weak (q[1-4]|quarter|results|numbers)|disappoint", -3, "RESULTS"),
    (r"revenue (falls|drops|declines)|margin (contracts|shrinks|falls)", -2, "RESULTS"),
    (r"bags?\b|bagged|wins? (order|contract)|order (win|worth|inflow)|secures? (order|contract)|l1 bidder|letter of award", 2, "ORDER"),
    (r"upgrade|target (price )?(raised|hiked|increased)|buy rating|outperform|overweight", 2, "BROKER"),
    (r"downgrade|target (price )?(cut|lowered|reduced)|sell rating|underperform|underweight", -2, "BROKER"),
    (r"buyback|bonus issue|stock split|dividend", 1, "CORP"),
    (r"block deal|bulk deal", 0, "DEAL"),
    (r"stake sale|ofs\b|offer for sale|promoter (sells|pledge)", -2, "DEAL"),
    (r"sebi (probe|order|notice|penalty)|raids?\b|fraud|default|penalty|ban\b|banned|show cause|resigns?\b", -3, "REG"),
    (r"approval|usfda (nod|approval)|gets nod|launch(es)?", 1, "CORP"),
]
# 📊 Index / market news → NIFTY · BANKNIFTY (bias மட்டும், call இல்லை)
MARKET = [
    (r"rbi (cuts?|slashes|lowers) (repo|rates?)|rate cut|fed (cuts?|lowers)|dovish", 3), (r"rbi (hikes?|raises)|rate hike|fed (hikes?|raises)|hawkish", -3),
    (r"fiis? (buy|bought|net buyers|pour)|foreign investors (buy|pour)|dii buying", 2), (r"fiis? (sell|sold|net sellers|dump|pull out)|foreign outflow", -2),
    (r"gdp (grows|rises|beats|jumps)|inflation (eases|cools|falls)|cpi (eases|falls)", 2), (r"gdp (slows|contracts|misses)|inflation (rises|jumps|surges)|cpi (rises|jumps)", -2),
    (r"(sensex|nifty|markets?|d-street|dalal street|indices) (rall|surge|jump|soar|zoom|skyrocket|rocket|spurt|climb|hit record|record high|gain|scale|extend gains)", 2),
    (r"(sensex|nifty|markets?|d-street|dalal street|indices) (crash|plunge|tank|slump|fall|tumble|bleed|sink|nosedive|crack|slide|extend losses)", -2),
    (r"(sensex|nifty)[^.]{0,40}\b(up|jumps?|surges?|gains?|rises?|zooms?|soars?|rall(y|ies)|climbs?) (over |nearly |about |more than )?[\d,]{3,6} ?(pts|points)", 3),
    (r"(sensex|nifty)[^.]{0,40}\b(down|falls?|drops?|slumps?|tanks?|crash(es)?|plunges?|tumbles?|sheds?|loses?) (over |nearly |about |more than )?[\d,]{3,6} ?(pts|points)", -3),
    (r"bulls? (charge|run|rampage|take charge)|biggest (single[- ]day )?(gain|rally|jump)|best day in", 2), (r"bears? (grip|tighten|rampage|maul)|biggest (single[- ]day )?(fall|loss|crash)|worst day in|bloodbath", -2),
    (r"wall street (rall|gain|surge|jump)|dow (gains|jumps|rallies)|nasdaq (gains|jumps|rallies)", 1),
    (r"wall street (fall|slump|tumble|sink)|dow (falls|slumps|tumbles)|nasdaq (falls|slumps|tumbles)", -1),
    # GIFT Nifty = pre-market-ல் அடுத்த நாள் open-க்கு நேரடி clue → வலுவான weight
    (r"gift nifty (jumps|rises|surges|soars|up|higher|gains|trades higher|indicates (a )?(positive|gap[- ]up|higher|strong))|gap[- ]up (open|opening|start)|positive (opening|start) (for|on) (dalal|d-street|sensex|nifty)", 3),
    (r"gift nifty (falls|drops|slips|down|lower|trades lower|indicates (a )?(negative|gap[- ]down|lower|weak))|gap[- ]down (open|opening|start)|negative (opening|start) (for|on) (dalal|d-street|sensex|nifty)", -3),
    (r"crude (falls|slumps|eases|drops)|oil prices? (fall|drop|ease)", 1), (r"crude (surges|jumps|spikes|soars)|oil prices? (surge|jump|spike)", -1),
    (r"war\b|wars\b|missiles?\b|attacks?\b|tariff (hike|threat)|sanctions\b|sanctioned", -2), (r"ceasefire|trade deal|peace (deal|talks)", 2),
]
BANK = r"rbi|repo|bank|banking|nbfc|credit growth|npa|psu bank|hdfc bank|icici bank|sbi\b|kotak|axis bank"
CFG = {"min_score": 3, "hours": 20, "max_day": 4, "start": "09:30", "end": "14:30", "vol_x": 1.5, "max_focus": 12, "q_every": 600}
STATE = {"time": None, "focus": [], "err": None, "calls": [], "alerts": [], "log": []}
CACHE = {"q_t": 0, "q_items": []}
LK = threading.Lock()
INDEXES = ("NIFTY", "BANKNIFTY")


def _hit(pat, t):
    """முழு வார்த்தை தொடக்கம் மட்டும் — "soft-WAR-e" / "multi-BAG-g" / "af-RAID" மாதிரி தவறான match இல்லை."""
    return re.search(r"\b(?:" + pat + r")", t)


def score(title):
    t = title.lower()
    s, ev, hit = 0, None, []
    for pat, w, e in RULES:
        if _hit(pat, t):
            s += w
            hit.append(e)
            if ev is None or abs(w) >= 3:
                ev = e
    return s, ev or (hit[0] if hit else None)


def mscore(title):
    t = title.lower()
    return sum(w for pat, w in MARKET if _hit(pat, t))


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
            syms += ["BANKNIFTY"] if _hit(BANK, k.lower()) else []
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


def build_focus(items, levels, live_q, mdir=None, idx_pct=None):
    """Symbol-க்கு news score கூட்டு → |score| ≥ min → CE / PE focus + trigger levels (PDH / PDL / day range)."""
    agg = {}
    for x in items:
        a = agg.setdefault(x["symbol"], {"symbol": x["symbol"], "score": 0, "news": [], "events": set()})
        a["score"] += x["score"]
        a["events"].add(x["event"])
        a.setdefault("all", []).append(x)
        if len(a["news"]) < 4:
            a["news"].append(x)
    out = []
    for s, a in agg.items():
        if abs(a["score"]) < CFG["min_score"]:
            continue
        if s in INDEXES:                                 # index = bias மட்டும் (news-ஐ வச்சு index call இல்லை)
            side = "CE" if a["score"] > 0 else "PE"
            heads = {x["title"][:60] for x in a["all"]}
            pc = (idx_pct or {}).get(s)
            agree = pc is not None and (pc > 0) == (side == "CE")
            if pc is not None and abs(pc) >= 0.4 and not agree:
                st, why = "CONFLICT", f"News {'positive' if side == 'CE' else 'negative'}, ஆனா {s} live {pc:+.2f}% — price-ஐ நம்புங்க, news bias-ஐ விடுங்க"
            elif agree and abs(pc) >= 0.3 and (len(heads) >= 2 or abs(pc) >= 1.0):
                st, why = "CONFIRMED", f"News + price ஒத்துப்போகுது — {s} live {pc:+.2f}% → {side} setups (strike கீழே)"
            elif len(heads) < 2:
                st, why = "WEAK", "ஒரே ஒரு headline தான் — bias-க்கு போதாது (2+ தனி news வேணும்)"
            else:
                st, why = "BIAS", f"Market news {'positive' if side == 'CE' else 'negative'} ({len(heads)} headlines) → {s} setups-ல் {side} பக்கம் மட்டும் பாருங்க (index call news-ஐ வச்சு இல்லை)"
            out.append({"symbol": s, "side": side, "score": a["score"], "events": ["MARKET"], "news": sorted(a["all"], key=lambda x: -abs(x["score"]))[:6],
                        "index": True, "status": st, "why": why, "heads": len(heads)})
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


CAUSE = re.compile(r"\b(?:on|amid|after|as|led by|driven by|tracking|following)\s+([^,;|\-–]{6,70})", re.I)


def market_box(items, idx):
    """📈 Price-led: NIFTY / BANKNIFTY பெரிய move (±0.8%) இருந்தா — அதுக்கு காரணமான market headlines (score இல்லைன்னாலும்)."""
    npct = (idx.get("NIFTY") or {}).get("pct")
    bpct = (idx.get("BANKNIFTY") or {}).get("pct")
    mk = [x for x in items if x["symbol"] in INDEXES or re.search(r"\b(sensex|nifty|dalal|d-street|market|stocks)\b", x["title"].lower())]
    seen, heads = set(), []
    for x in sorted(mk, key=lambda x: -x["ts"]):
        k = x["title"][:70]
        if k in seen:
            continue
        seen.add(k)
        heads.append(x)
    causes = []
    for x in heads[:12]:
        for m in CAUSE.finditer(x["title"]):
            c = m.group(1).strip().rstrip(".")
            if 6 <= len(c) <= 70 and c.lower() not in [z.lower() for z in causes]:
                causes.append(c)
    mv = None if npct is None else ("RALLY" if npct >= 0.8 else "SELLOFF" if npct <= -0.8 else None)
    return {"nifty": npct, "banknifty": bpct, "move": mv, "heads": heads[:8], "causes": causes[:5]}


def setups(ag, inst, focus, idx, now, max_new=3):
    """📰 News setups — CE / PE + strike: stock (WATCH / CONFIRMED) + index (CONFIRMED / BIAS). நாளுக்கு ஒருமுறை strike pick (cache), LTP ஒவ்வொரு run."""
    from . import fullscan as FS
    from . import v4 as V
    day = str(now.date())
    OC = CACHE.setdefault("opt", {})
    for k in [k for k in OC if not k.startswith(day)]:
        OC.pop(k, None)
    want = [f for f in focus if (f.get("index") and f["status"] in ("CONFIRMED", "BIAS")) or (not f.get("index") and f["status"] in ("WATCH", "CONFIRMED"))][:8]
    new = 0
    for f in want:
        k = f"{day}|{f['symbol']}|{f['side']}"
        if k in OC or not ag or new >= max_new:
            continue
        new += 1
        try:
            if f.get("index"):
                spot = (idx.get(f["symbol"]) or {}).get("spot")
                if not spot:
                    continue
                o, _ = V.pick_strike(ag, inst, f["symbol"], f["side"], spot, now)
                if not o:
                    OC[k] = None
                    continue
                pl, _ = V.option_plan(o, spot, spot * (0.996 if f["side"] == "CE" else 1.004), V.settings())
                OC[k] = {"strike": o["strike"], "expiry": o["expiry"], "lot": o["lot"], "token": o["token"], "exch": o["exch"], "contract": o.get("contract"),
                         "entry": (pl or {}).get("entry") or o.get("ltp"), "sl": (pl or {}).get("sl"), "targets": (pl or {}).get("targets") or [],
                         "first": now.strftime("%H:%M"), "first_ul": spot}
            else:
                rr = {"symbol": f["symbol"], "side": f["side"], "price": f.get("ltp"), "sl": f.get("ul_sl"), "min_days": 3, "targets": []}
                FS.pick_options(ag, inst, [rr])
                o = rr.get("option") or {}
                if not o.get("token"):
                    OC[k] = None
                    continue
                FS.attach_plan(rr, o, now, "📰 News Radar")
                o = rr.get("option") or o
                pl = o.get("plan") or {}
                OC[k] = {"strike": o["strike"], "expiry": o.get("expiry"), "lot": o.get("lot"), "token": o["token"], "exch": o.get("exch", "NFO"),
                         "contract": o.get("contract"), "entry": pl.get("entry") or o.get("ltp"), "sl": pl.get("sl"), "targets": pl.get("targets") or [],
                         "first": now.strftime("%H:%M"), "first_ul": f.get("ltp")}
        except Exception:
            OC[k] = None
    toks = {}
    for f in want:
        o = OC.get(f"{day}|{f['symbol']}|{f['side']}")
        if o:
            toks.setdefault(o["exch"], []).append(o["token"])
    qs = {}
    if ag and toks:
        try:
            qs = ag.quotes(toks) or {}
        except Exception:
            qs = {}
    out = []
    for f in want:
        o = OC.get(f"{day}|{f['symbol']}|{f['side']}")
        if not o:
            continue
        ltp = float((qs.get(o["token"]) or {}).get("ltp") or 0) or None
        e = float(o["entry"] or 0)
        mv = ((ltp - e) / e * 100) if (ltp and e) else None
        live = ("✅ Entry OK" if mv is not None and mv <= 5 else "⚠ சற்று late — limit order" if mv is not None and mv <= 12 else
                "⏭ LATE — chase வேண்டாம்" if mv is not None else "LTP வரல")
        if o.get("sl") and ltp and ltp <= float(o["sl"]):
            live = "⛔ SL கீழ் — invalid"
        out.append({"symbol": f["symbol"], "side": f["side"], "index": bool(f.get("index")), "status": f["status"], "score": f["score"],
                    "news": (f.get("news") or [{}])[0].get("title"), "why": f.get("why"), **o, "ltp": ltp, "move": round(mv, 1) if mv is not None else None, "live": live})
    out.sort(key=lambda x: (x["status"] != "CONFIRMED", not x["index"], -abs(x["score"])))
    return out


def run(ag, inst, news_items, now, send=None, full=None):
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
            idx = {x.get("index"): x for x in ((full or {}).get("index") or [])}
            ip = {k: v.get("pct") for k, v in idx.items() if k in INDEXES and v.get("pct") is not None}
            if "NIFTY" not in ip:
                try:
                    if (AST.get("risk") or {}).get("nifty") is not None:
                        ip["NIFTY"] = AST["risk"]["nifty"]
                except Exception:
                    pass
            focus = build_focus(items, FS.C.get("levels") or {}, FS.C.get("live_q") or {}, mdir, ip or None)
            STATE["market"] = market_box(items, idx)
            try:
                STATE["setups"] = setups(ag, inst, focus, idx, now) if ag else STATE.get("setups") or []
            except Exception as e:
                STATE["setups_err"] = str(e)[:150]
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
