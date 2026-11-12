"""KRT Terminal — local website. KRT.bat double-click செய்தால் இது ஓடும்.
உங்கள் PC-ல் மட்டும் (127.0.0.1) — வெளியே யாருக்கும் தெரியாது."""
import base64, json, os, re, threading, time, traceback, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import pandas as pd

from krt.config import ROOT
from krt.runner import run_scan, now_ist, market_open, angel_configured
from krt.chartink import CLAUSE_FILE, saved_clauses
from krt.config import load_settings

HOSTED = bool(os.getenv("RENDER") or os.getenv("HOSTED"))
PORT = int(os.getenv("PORT", "8765"))
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
STATE = {"scanning": False, "result": None, "error": None, "last_run": None, "slot": None,
         "full": None, "full_error": None, "full_running": False, "full_last": None, "progress": "", "fslot": None}
ANGEL = None
LOCK = threading.Lock()
API_LOCK = threading.Lock()  # Chartink scan + full scan ஒரே நேரத்தில் Angel API-ஐ அடிக்கக்கூடாது (rate limit)


def _nan_safe(o):
    if isinstance(o, float) and (o != o or o in (float("inf"), float("-inf"))):
        return None
    if isinstance(o, dict):
        return {k: _nan_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_nan_safe(v) for v in o]
    return o


def _json(o):
    """NaN / Infinity browser JSON-ஐ உடைக்கும் → None (இதனால் 'Server-ஐ அடைய முடியவில்லை' வந்தது)."""
    try:
        return json.dumps(o, default=str, ensure_ascii=False, allow_nan=False)
    except ValueError:
        return json.dumps(_nan_safe(o), default=str, ensure_ascii=False)


def do_scan(at=None):
    with LOCK:
        if STATE["scanning"]:
            return False
        STATE["scanning"] = True
    try:
        if not angel_configured():
            raise RuntimeError("Angel One connect ஆகவில்லை — demo data காட்டப்படாது")
        with API_LOCK:
            res = run_scan("angel", at or None)
        STATE.update(result=res, error=None)
    except Exception as e:
        traceback.print_exc()
        STATE["error"] = str(e)
    finally:
        STATE["last_run"] = str(now_ist())
        STATE["scanning"] = False
    return True


def do_full():
    global ANGEL
    with LOCK:
        if STATE["full_running"]:
            return False
        STATE["full_running"] = True
    try:
        if not angel_configured():
            raise RuntimeError("Angel One connect ஆகவில்லை — Render Environment-ல் ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_MPIN, ANGEL_TOTP_SECRET வேண்டும்")
        for _ in range(60):                     # 👑 Goki 15-min scan ஓடிக்கிட்டிருந்தா அது முடியட்டும் (max 2 நிமிடம்)
            if not GOKI_RUN.get("running"):
                break
            STATE["progress"] = "👑 Goki scan முடியட்டும் — deep scan காத்திருக்கு…"
            time.sleep(2)
        from krt.angel_api import Angel
        from krt.fullscan import run_full
        ANGEL = ANGEL or Angel()
        with API_LOCK:
            res = run_full(ANGEL, lambda m: STATE.update(progress=m))
        old = STATE.get("full") or {}
        if old.get("goki") and not res.get("goki"):
            res["goki"] = old["goki"]            # 👑 Goki radar — 15-min loop, deep scan அழிக்கக்கூடாது
        if old.get("power") and not res.get("power"):
            res["power"] = old["power"]          # POWER OI தனி loop — deep scan அழிக்கக்கூடாது
            try:
                from krt.fullscan import compute_all_rounder
                compute_all_rounder(res)
            except Exception:
                pass
        STATE.update(full=res, full_error=None)
        try:
            from krt.store import SNAP
            from krt.fullscan import export_cache
            snap = dict(res)
            snap["tracking"] = {k: v for k, v in (res.get("tracking") or {}).items() if k != "history"}
            SNAP.load()
            SNAP.data = {"result": snap, "cache": export_cache(), "saved": str(now_ist())}
            SNAP.dirty = True
            SNAP.save()
        except Exception:
            traceback.print_exc()
    except Exception as e:
        traceback.print_exc()
        STATE["full_error"] = str(e)
    finally:
        STATE.update(full_last=str(now_ist()), full_running=False, progress="")
    return True


V4E = {"err": None, "t": None}


def _snap_put(c):
    """Call-ஐ STATE['full']['tracking'] snapshot-ல் உடனே சேர்/update (today + history)."""
    if not c:
        return
    tr = (STATE.get("full") or {}).get("tracking")
    if not isinstance(tr, dict):
        return
    for key in ("today", "history"):
        lst = tr.setdefault(key, [])
        for i, x in enumerate(lst):
            if x.get("id") == c["id"]:
                lst[i] = dict(c)
                break
        else:
            lst.insert(0, dict(c))


def v4_loop():
    """🔥 KRT AI V4: market நேரத்தில் ஒவ்வொரு நிமிடமும் (completed 1-min candle) 4 index × 5 strategies. Browser close ஆனாலும் server-ல் ஓடும்."""
    global ANGEL
    done = None
    while True:
        time.sleep(5)
        try:
            # ⚠ now_ist() நிமிடத்துக்கு floor பண்ணும் (seconds = 0) — அதனால் இங்கே real clock
            real = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)
            V4E["beat"] = real.strftime("%H:%M:%S")
            t = real.floor("1min")
            slot = t
            if done == slot or real.second < 5 or not angel_configured():
                continue
            if real.minute % 2:            # Angel rate-limit: V4 2 நிமிடத்துக்கு ஒருமுறை
                continue
            mo = market_open(t)
            if not mo and not (V4E["t"] is None or t.minute % 15 == 0):
                continue
            done = slot
            v4_run_once(t, mo)
        except Exception as e:
            V4E["err"] = str(e)
            traceback.print_exc()


V4_LK = threading.Lock()
MCXE = {"err": None, "beat": None}


def chart_once(t):
    global ANGEL
    from krt import chartroom as CR
    from krt.angel_api import Angel
    from krt.instruments import load as load_inst
    from krt.store import STORE as _ST
    ANGEL = ANGEL or Angel()
    full = STATE.get("full") or {}
    extra = []
    for src, rows in (("👑 Money Machine", (full.get("money") or {}).get("picks") or []), ("🟠 Strong Break", [r for r in (full.get("strong") or {}).get("rows") or [] if r.get("strong")]),
                      ("🚀 Top Movers", (full.get("movers") or {}).get("rows") or [])):
        for r in rows:
            o, p = r.get("option") or {}, r.get("rp") or {}
            if o.get("strike") and p.get("entry"):
                extra.append({"id": None, "symbol": r["symbol"], "strike": o["strike"], "side": r["side"], "entry": p["entry"], "sl": p["sl"],
                              "targets": p["targets"], "ltp": o.get("ltp"), "status": "SETUP", "source": src, "time": t.strftime("%H:%M"),
                              "expiry": o.get("expiry"), "lot": o.get("lot"), "token": o.get("token"), "exch": o.get("exch"), "contract": o.get("contract")})
    indices = []
    try:
        from krt.predict import jackpot as _jp
        I_ = {x.get("index"): x for x in full.get("index") or []}
        for idx in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"):
            if idx not in I_:
                continue
            opts = {}
            for sd, dn in (("CE", "UP"), ("PE", "DOWN")):
                j = (_jp(I_, dn, 0, (idx,)) or [None])[0]
                if j:
                    opts[sd] = j
            indices.append({"id": None, "symbol": idx, "is_index": True, "status": "SETUP", "source": "📈 Index chart", "time": t.strftime("%H:%M"),
                            "side": "CE", "strike": None, "entry": None, "sl": None, "targets": [], "chain_opts": opts})
    except Exception:
        pass
    CR.run_once(ANGEL, load_inst(ROOT / "data" / "cache"), _ST, t, extra, indices)


def chart_loop():
    """📈 Chart Room: 5 நிமிடத்துக்கு ஒருமுறை (completed 5-min candle + 1 min) — NSE நேரம் + MCX நேரம்."""
    done = None
    while True:
        time.sleep(10)
        try:
            from krt import commodity as CM
            real = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)
            t = real.floor("1min")
            if not angel_configured() or t.minute % 5 != 1 or done == t or real.second < 15:
                continue
            nse = t.weekday() < 5 and "09:20" <= t.strftime("%H:%M") <= "15:31"
            if not (nse or CM.mcx_open(t)):
                continue
            done = t
            chart_once(t)
            try:                                     # 📈 breakout / invalid → phone push + Telegram (browser மூடியிருந்தாலும்)
                from krt import ailab as AL
                from krt.chartroom import STATE as CRS
                from krt.notify import both
                AL.chart_alerts(CRS, t, both)
            except Exception:
                traceback.print_exc()
            try:                                     # 🔥 Sweep + CHOCH + Volume + Candle + AI
                if market_open(t):
                    from krt import combo as CB
                    from krt.ai import STATE as _AST2
                    from krt.instruments import load as _li
                    CB.run(get_angel(), _li(ROOT / "data" / "cache"), t, (_AST2.get("risk") or {}).get("dir"))
            except Exception:
                traceback.print_exc()
        except Exception as e:
            __import__("krt.chartroom", fromlist=["STATE"]).STATE["err"] = str(e)[:200]
            traceback.print_exc()


def mcx_loop():
    """🛢 Commodity (MCX): 9:00–23:55 (Mon–Fri) 3 நிமிடத்துக்கு ஒருமுறை — NSE close ஆனாலும் ஓடும்."""
    global ANGEL
    done = None
    while True:
        time.sleep(10)
        try:
            from krt import commodity as CM
            real = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)
            MCXE["beat"] = real.strftime("%H:%M:%S")
            t = real.floor("1min")
            if not angel_configured() or not CM.mcx_open(t) or t.minute % 3 or done == t or real.second < 8:
                continue
            done = t
            from krt.angel_api import Angel
            from krt.instruments import load as load_inst
            ANGEL = ANGEL or Angel()
            CM.run_once(ANGEL, load_inst(ROOT / "data" / "cache"), t)
            try:
                from krt import mannan as MN
                MN.run_commodity(ANGEL, load_inst(ROOT / "data" / "cache"), t)     # 👑 Mannan Commodity (அதே frames)
                MN.track_setups(ANGEL, t)
            except Exception as e:
                __import__("krt.mannan", fromlist=["STATE"]).STATE["CMD"]["err"] = str(e)[:200]
                traceback.print_exc()
            try:
                from krt.ai import pink_tick
                pink_tick(t)                     # 🩷 commodity calls-க்கும் pink alert (NSE close ஆன பிறகும்)
            except Exception:
                traceback.print_exc()
            MCXE["err"] = None
        except Exception as e:
            MCXE["err"] = str(e)[:200]
            traceback.print_exc()


def v4_run_once(t=None, mo=None):
    global ANGEL
    if not V4_LK.acquire(blocking=False):
        return False            # முந்தைய scan இன்னும் ஓடுது
    V4E["since"] = pd.Timestamp.now(tz="Asia/Kolkata").strftime("%H:%M:%S")
    try:
        from krt import v4
        t = t or now_ist()
        mo = market_open(t) if mo is None else mo
        v4.STATE["prog"] = "Angel login…"
        from krt.angel_api import Angel
        from krt.instruments import load as load_inst
        ANGEL = ANGEL or Angel()
        v4.STATE["prog"] = "Instrument master…"
        inst = load_inst(ROOT / "data" / "cache")
        sig = v4.scan(ANGEL, inst, STATE.get("full"), t, live=mo)
        if mo and sig:
            v4.to_calls(sig, t)
        V4E.update(err=None, t=str(t))
        return True
    except Exception as e:
        V4E["err"] = str(e)
        from krt import v4
        v4.STATE["prog"] = ""
        traceback.print_exc()
        return False
    finally:
        V4_LK.release()


def v4_backtest(days):
    global ANGEL
    from krt import v4
    try:
        v4.STATE.update(bt_running=True, bt_prog="")
        from krt.angel_api import Angel
        from krt.instruments import load as load_inst
        ANGEL = ANGEL or Angel()
        inst = load_inst(ROOT / "data" / "cache")
        v4.STATE["bt"] = v4.backtest(ANGEL, inst, days=days, progress=lambda m: v4.STATE.update(bt_prog=m))
    except Exception as e:
        traceback.print_exc()
        v4.STATE["bt"] = {"error": str(e)}
    finally:
        v4.STATE["bt_running"] = False


def ticker():
    """Market நேரத்தில் 30 sec-க்கு ஒருமுறை live price / option LTP / T1-SL update (deep scan நடந்தாலும்)."""
    global ANGEL
    while True:
        time.sleep(30)
        try:
            if not (market_open(now_ist()) and angel_configured() and STATE.get("full")):
                continue
            from krt.angel_api import Angel
            from krt.fullscan import fast_tick
            ANGEL = ANGEL or Angel()
            STATE["full"] = fast_tick(ANGEL, STATE["full"])
        except Exception:
            traceback.print_exc()


NEWS = {"items": [], "err": None, "t": None}
GU = {"data": None, "err": None}


def gu_loop():
    """GAMMA-UNWIND: market நேரத்தில் 5 நிமிடத்துக்கு ஒருமுறை (candle முடிந்த 2 நிமிடம் கழித்து)."""
    global ANGEL
    done = None
    while True:
        time.sleep(20)
        try:
            t = now_ist()
            slot = t.floor("5min")
            if not (market_open(t) and angel_configured()) or t.minute % 5 != 2 or done == slot:
                continue
            if t.hour * 60 + t.minute < 9 * 60 + 20:
                continue
            done = slot
            from krt.angel_api import Angel
            from krt.fullscan import C
            from krt.instruments import load as load_inst, contracts
            from krt import gamma_unwind as G
            from krt.calls import update_calls
            if not C.get("bars"):
                GU["err"] = "Daily data இன்னும் load ஆகவில்லை (deep scan முடிய காத்திருக்கிறது)"
                continue
            ANGEL = ANGEL or Angel()
            inst = load_inst(ROOT / "data" / "cache")
            ltp_of = {}
            mins = t.hour * 60 + t.minute
            need_sel = (mins >= 13 * 60 + 15 and "13:15" not in G.ST["sel"]) or ("09:20" not in G.ST["sel"] and "13:15" not in G.ST["sel"]) or G.ST["day"] != str(t.date())
            if need_sel:
                names = [n for n in inst["fno"] if n in inst["eq"]]
                qs = ANGEL.quotes({"NSE": [inst["eq"][n] for n in names]})
                ltp_of = {n: float((qs.get(inst["eq"][n]) or {}).get("ltp") or 0) for n in names}
            regime = {"trend": (STATE.get("full") or {}).get("trend")}
            from krt.store import STORE
            sl_today = sum(1 for c_ in STORE.load()["calls"].values()
                           if c_["kind"].startswith("GU-") and c_["date"] == str(t.date()) and c_["status"] == "SL HIT")
            snap = G.run(ANGEL, inst, C, ltp_of, t, regime, sl_today)
            entries = [s_ for s_ in snap["signals"] if s_["tier"] == "PRO ENTRY"]
            update_calls(ANGEL, pd.Timestamp(t.date()), t, True, [], [], [], [], {"10": [], "5": []}, add=False, gu=entries)
            GU.update(data=snap, err=None)
            C["_gu_snap"] = snap
        except Exception as e:
            traceback.print_exc()
            GU["err"] = str(e)


def news_loop():
    """10 நிமிடத்துக்கு ஒருமுறை Google News RSS — market + setup stocks."""
    from krt.news import refresh
    while True:
        try:
            f = STATE.get("full") or {}
            syms = []
            for key in ("best", "patterns", "ce", "pe"):
                for r in f.get(key) or []:
                    if r["symbol"] not in syms:
                        syms.append(r["symbol"])
            try:
                from krt.instruments import _MEM
                fno = (_MEM.get("data") or {}).get("fno") or []
            except Exception:
                fno = []
            c = refresh(syms, fno)
            NEWS.update(items=c["items"], err=c["err"], t=str(now_ist()))
            try:                                     # 📰 News Radar — focus list + alerts + confirmed calls
                global ANGEL
                from krt import newsradar as NR
                from krt.telegram import send as _tg
                ag_ = None
                if angel_configured() and market_open(now_ist()):
                    from krt.angel_api import Angel
                    from krt.instruments import load as load_inst
                    ANGEL = ANGEL or Angel()
                    ag_ = ANGEL
                from krt.notify import both as _both
                NR.run(ag_, load_inst(ROOT / "data" / "cache") if ag_ else {}, c["items"], now_ist(), _both, STATE.get("full"))
            except Exception:
                traceback.print_exc()
        except Exception as e:
            NEWS["err"] = str(e)
        time.sleep(60)


def power_loop():
    """🎯 POWER OI: ஒவ்வொரு 5-min candle முடிந்த 3 நிமிடத்தில் (9:33, 9:38…)."""
    global ANGEL
    done = None
    while True:
        time.sleep(15)
        try:
            t = now_ist()
            slot = t.floor("5min")
            if not (market_open(t) and angel_configured() and STATE.get("full")) or t.minute % 5 != 3 or done == slot:
                continue
            if t.hour * 60 + t.minute < 9 * 60 + 33:
                continue
            done = slot
            from krt.angel_api import Angel
            from krt.fullscan import run_power
            ANGEL = ANGEL or Angel()
            STATE["full"] = run_power(ANGEL, STATE["full"])
        except Exception:
            traceback.print_exc()


APP_VERSION = "v105"
EVC = {"t": 0, "d": None}


def events_loop():
    """📅 Results diary + 🌅 Pre-open + strike — weekdays 9:05–15:30, 60 sec-க்கு ஒருமுறை."""
    last_cal = 0
    while True:
        time.sleep(60)
        try:
            t = now_ist()
            hm = t.strftime("%H:%M")
            if t.weekday() >= 5 or not ("09:05" <= hm <= "15:30") or not angel_configured():
                continue
            from krt import events as EV
            from krt import fullscan as FS
            from krt import ailab as AL
            from krt.calls import STORE as _S
            from krt.instruments import load as load_inst
            ag, inst = get_angel(), load_inst(ROOT / "data" / "cache")
            if time.time() - last_cal > 600:
                last_cal = time.time()
                EV.refresh_calendar(_S, set((FS.C.get("bars") or {}).keys()), NEWS.get("items") or [], t.date())
            EV.diary(_S, ag, inst, t, STATE.get("full") or {}, live=market_open(t))
            P = EV.preopen(t, STATE.get("full") or {}, NEWS.get("items") or [])
            K = EV.STATE.setdefault("strikes", {})
            want = [(r["symbol"], r["side"], r.get("iep")) for r in (P.get("rows") or [])[:6] if P.get("date") == str(t.date())]
            want += [(r["symbol"], r["setup"]["side"], r.get("spot")) for r in EV.STATE.get("results") or [] if (r.get("setup") or {}).get("side")]
            n = 0
            for sym, side, spot in want:
                k = f"{t.date()}|{sym}|{side}"
                if k in K or not spot or n >= 3 or not market_open(t):
                    continue
                n += 1
                ce = side == "CE"
                try:
                    b = AL.best_strike(ag, inst, sym, side, float(spot), t, spot * (0.99 if ce else 1.01), spot * (1.02 if ce else 0.98), min_days=3)
                    K[k] = {x: (b.get("best") or {}).get(x) for x in ("strike", "expiry", "lot", "token", "exch", "contract", "ltp", "prem_sl", "prem_target", "rr", "delta", "score", "moneyness")}
                    K[k]["explain"] = b.get("explain")
                except Exception:
                    K[k] = None
        except Exception:
            traceback.print_exc()


def events_state():
    if time.time() - EVC["t"] > 30:
        try:
            from krt import events as EV
            from krt import daypicks as DP
            from krt.calls import STORE as _S
            t = now_ist()
            if not EV.STATE.get("results"):
                EV.diary(_S, None, {}, t, STATE.get("full") or {}, live=False)
            EVC.update(t=time.time(), d={"results": EV.STATE.get("results") or [], "preopen": EV.STATE.get("preopen"), "nse_err": EV.STATE.get("nse_err"),
                                          "strikes": EV.STATE.get("strikes") or {}, "day": DP.report(_S.load(), str(t.date()))})
        except Exception as e:
            EVC.update(t=time.time(), d={"err": str(e)[:200]})
    return EVC["d"]
LAB = {"t": 0, "d": None}


def store_state():
    from krt.calls import STORE as _S
    return {"remote": _S.remote, "error": _S.error, "load_failed": bool(getattr(_S, "load_failed", False)),
            "calls": len((_S.data or {}).get("calls") or {}), "dirty": _S.dirty}


def bp_inputs(D, t):
    from krt import fullscan as FSm, footprint as FPM
    from krt.ailab import STATE as LAB, decide
    from krt.ai import STATE as _AST
    from krt.chartroom import STATE as CRS
    from krt.calls import proven_sources
    mdir = (_AST.get("risk") or {}).get("dir")
    auto = ((LAB.get("auto") or {}).get("rows")) or {}
    lab = {cid: {"verdict": decide(D["calls"].get(cid), v, mdir)} for cid, v in auto.items()}
    guides = {}
    for g in (FPM.report() or {}).get("guide") or []:
        guides.setdefault(g["symbol"], g)
    return (CRS.get("calls_table") or []), lab, (FSm.C.get("levels") or {}), (FSm.C.get("live_q") or {}), guides, proven_sources(D)


def bp_run(t):
    from krt import bestpicks as BP
    from krt.calls import STORE as _S, CALLS_LOCK
    from krt.notify import both as _b
    rows = (sniper_state() or {}).get("rows") or []
    with CALLS_LOCK:
        D = _S.load()
        ct, lab, lv, lq, gd, pv = bp_inputs(D, t)
        new = BP.run(D, t, rows, ct, lab, lv, lq, gd, pv, _b)
        if new:
            _S.dirty = True
    BPC["t"] = 0


def fable_pre():
    """⚠ CALLS_LOCK is NOT reentrant: sniper_state / lab_report / journal may take it — compute them BEFORE locking (deadlock otherwise)."""
    return {"srows": (sniper_state() or {}).get("rows") or [], "brain": (lab_report() or {}).get("brain") or {}, "jr": journal() or {}}


def fable_ctx(D, t, pre):
    """Everything Fable needs: market, real module stats, and per-call analysis (best picks · sniper · chart · footprint · lab · history).
    Called UNDER CALLS_LOCK — must not call anything that takes the lock (use `pre`)."""
    from krt import bestpicks as BP, crash as CRH
    from krt.ai import STATE as _AST
    from krt.chartroom import STATE as CRS
    risk = _AST.get("risk") or {}
    full = STATE.get("full") or {}
    nifty = next((x for x in full.get("index") or [] if x.get("index") == "NIFTY"), {})
    brain = pre["brain"]
    cr = CRH.report()
    jr = pre["jr"]
    mods = {m["module"]: {k: m.get(k) for k in ("n", "win_rate", "exp", "net", "mdd")} for m in (jr.get("mods") or [])}
    ct, lab, lv, lq, gd, pv = bp_inputs(D, t)
    ctm = {r["id"]: r for r in ct}
    live = {r["id"]: r for r in (BP.STATE.get("rows") or [])}
    sq = {r["id"]: r for r in pre["srows"]}
    charts = {(x.get("call") or {}).get("symbol"): x.get("analysis") or {} for x in CRS.get("charts") or []}
    calls = list(D["calls"].values())
    extra = {}
    for c in calls:
        if c.get("date") != str(t.date()) or c.get("status") not in BP.OPEN:
            continue
        a = charts.get(c["symbol"]) or {}
        g = gd.get(c["symbol"]) or {}
        b, q, r = live.get(c["id"]) or {}, sq.get(c["id"]) or {}, ctm.get(c["id"]) or {}
        extra[c["id"]] = {"score": b.get("score"), "best_pick_why": b.get("why"), "entry_state": b.get("state"), "level_breaks": b.get("breaks"),
                          "sniper": {"score": q.get("score"), "tier": q.get("tier"), "parts": q.get("parts"), "mtf_aligned": q.get("aligned")},
                          "chart": {"verdict": r.get("verdict"), "methods_score": r.get("mscore"), "for": r.get("pro"), "against": r.get("con"),
                                    "pattern": a.get("pattern"), "candles": [x.get("name") for x in (a.get("candles") or [])][:3],
                                    "trend": (a.get("structure") or {}).get("trend"), "regime": (a.get("regime") or {}).get("kind")},
                          "footprint": g.get("head") if g.get("side") else None, "ai_lab": (lab.get(c["id"]) or {}).get("verdict"),
                          "history": BP.strike_history(calls, c["symbol"], c.get("side"), c.get("strike")), "sl_widened": c.get("sl_widened")}
    market = {"nifty_pct": nifty.get("pct"), "direction": risk.get("dir"), "breadth_up_pct": risk.get("up"), "breadth_down_pct": risk.get("dn"),
              "regime": brain.get("kind"), "crash_radar": {"level": cr.get("level"), "side": cr.get("side"), "signals": cr.get("signals")}}
    return {"market": market, "module_stats": mods, "extra": extra}


FBC = {"t": 0, "d": None}


def fable_once(t, force=False):
    from krt import fable as FB
    from krt.calls import STORE as _S, CALLS_LOCK, add_pick
    from krt.notify import both as _b
    pre = fable_pre()                                       # outside the lock
    with CALLS_LOCK:
        D = _S.load()
        if D.get("fable_picks"):
            FB.track(D, t)
            _S.dirty = True
        if not FB.cfg()["key"]:
            return []
        ctx = fable_ctx(D, t, pre)
        cands, prompt = FB.prepare(D, t, ctx)
    if not FB.should_run(t, cands, force):
        return []
    try:
        out = FB.ask_model(prompt)                          # slow part — outside the lock
    except Exception as e:
        FB.STATE["err"] = str(e)[:200]
        return []
    with CALLS_LOCK:
        D = _S.load()
        new = FB.apply(D, t, out, cands)
        if new:
            _S.dirty = True
        calls = dict(D["calls"])
    FBC["t"] = 0
    for p in new:
        try:
            _b(f"{'🪙 FABLE GOLD' if p['grade'] == 'GOLD' else '🧠 FABLE PICK'} · {p['symbol']} {p['strike']:g} {p['side']}\n"
               f"Buy ₹{p['entry_zone'][0]}–{p['entry_zone'][1]} · SL ₹{p['sl']} · T1 ₹{p['t1']} · T2 ₹{p['t2']} · T3 ₹{p['t3']}\n"
               f"Confidence {p['confidence']}/100 · " + " · ".join(p.get("why") or [])[:150], f"fable|{p['id']}", True)
        except Exception:
            pass
        if FB.cfg()["auto_paper"]:                          # Fable trades it itself — on PAPER only
            c = calls.get(p["id"]) or {}
            try:
                add_pick({**{k: c.get(k) for k in ("symbol", "side", "strike", "expiry", "contract", "token", "exch", "lot")}, "sl": p["sl"],
                          "from_src": "🧠 Fable", "src_modules": ["🧠 Fable"]}, c.get("ltp"), t, 1)
            except Exception:
                pass
    return new


def fable_loop():
    while True:
        time.sleep(60)
        try:
            t = now_ist()
            if market_open(t) or str(t.time()) < "23:00":
                fable_once(t)
        except Exception:
            traceback.print_exc()


def fable_state():
    if time.time() - FBC["t"] > 5:
        try:
            from krt import fable as FB
            from krt.calls import STORE as _S
            t = now_ist()
            FBC.update(t=time.time(), d=FB.report(_S.load(), str(t.date())))
        except Exception as e:
            FBC.update(t=time.time(), d={"err": str(e)[:200]})
    return FBC["d"]


def mood_run(t):
    from krt import mood as MD, footprint as FPM, newsradar as NR, brain as BR, bestpicks as BP
    from krt.ai import STATE as _AST
    from krt.calls import STORE as _S, CALLS_LOCK
    full = STATE.get("full") or {}
    with CALLS_LOCK:                                         # nothing inside takes CALLS_LOCK
        D = _S.load()
        MD.update(t, TICK.get("items") or {}, _AST.get("risk") or {}, full.get("index") or [], FPM.STATE.get("bars") or {},
                  NR.STATE.get("focus") or [], full.get("money") or {}, D.setdefault("mood_hist", {}))
        _S.dirty = True
        calls = D["calls"]
        guides = {}
        for g in (FPM.report() or {}).get("guide") or []:
            guides.setdefault(g["symbol"], g)
        allc = list(calls.values())
        MD.best_calls(BR.STATE.get("rows") or [], calls, guides, (full.get("money") or {}).get("rows") or [],
                      lambda s, sd, k: BP.strike_history(allc, s, sd, k))


def mood_state():
    from krt import mood as MD, footprint as FPM
    return {**{k: MD.STATE.get(k) for k in ("time", "idx", "sectors", "calls")}, "flow": FPM.FLOW["alerts"][:20]}


BRC = {"t": 0, "d": None}


def brain_run(t):
    from krt import brain as BR, bestpicks as BP, crash as CRH
    from krt.ai import STATE as _AST
    from krt.chartroom import STATE as CRS
    from krt.calls import STORE as _S, CALLS_LOCK, add_pick
    from krt.notify import both as _b
    srows = (sniper_state() or {}).get("rows") or []              # takes CALLS_LOCK — must be outside
    candles = {(x.get("call") or {}).get("symbol"): (x.get("analysis") or {}).get("candles") or [] for x in CRS.get("charts") or []}
    with CALLS_LOCK:
        D = _S.load()
        ct, lab, lv, lq, gd, pv = bp_inputs(D, t)
        new = BR.run(D, t, {"bp_rows": BP.STATE.get("rows") or [], "sniper_rows": srows, "charts_table": ct, "lab": lab, "guides": gd,
                            "mdir": (_AST.get("risk") or {}).get("dir"), "crash": CRH.report(), "candles": candles}, _b)
        if new:
            _S.dirty = True
        calls = dict(D["calls"])
    BRC["t"] = 0
    if new and os.environ.get("BRAIN_AUTO_PAPER", "1") == "1":         # Brain "takes" its own picks — on PAPER only
        for p in new:
            c = calls.get(p["id"]) or {}
            try:
                add_pick({**{k: c.get(k) for k in ("symbol", "side", "strike", "expiry", "contract", "token", "exch", "lot")}, "sl": c.get("sl"),
                          "from_src": "🧠 Brain", "src_modules": ["🧠 Brain"]}, c.get("ltp"), t, 1)
            except Exception:
                pass
    return new


def brain_state():
    if time.time() - BRC["t"] > 8:
        try:
            from krt import brain as BR
            from krt.calls import STORE as _S
            BRC.update(t=time.time(), d=BR.report(_S.load(), str(now_ist().date())))
        except Exception as e:
            BRC.update(t=time.time(), d={"err": str(e)[:200]})
    return BRC["d"]


BPC = {"t": 0, "d": None}


def bp_state():
    if time.time() - BPC["t"] > 10:
        try:
            from krt import bestpicks as BP, fullscan as FSm
            from krt.calls import STORE as _S
            from krt.chartroom import STATE as CRS
            t = now_ist()
            D = _S.load()
            R = BP.report(D, str(t.date()))
            calls = list(D["calls"].values())
            panel = {}
            for ch in CRS.get("charts") or []:                  # 📈 chart panel: levels + strike history
                c = ch.get("call") or {}
                if c.get("symbol"):
                    panel[c["symbol"]] = {"levels": (FSm.C.get("levels") or {}).get(c["symbol"]),
                                          "hist": BP.strike_history(calls, c["symbol"], c.get("side") or "CE", c.get("strike"))}
            R["panel"] = panel
            BPC.update(t=time.time(), d=R)
        except Exception as e:
            traceback.print_exc()
            BPC.update(t=time.time(), d={"err": str(e)[:200]})
    return BPC["d"]


SNC = {"t": 0, "d": None}


def sniper_state():
    if time.time() - SNC["t"] > 12:
        try:
            from krt import sqs as SQ, crash as CRH, footprint as FPM
            from krt.ailab import STATE as LAB
            from krt.ai import STATE as _AST
            from krt.chartroom import STATE as CRS
            from krt.calls import STORE as _S, CALLS_LOCK
            t = now_ist()
            day = str(t.date())
            mdir = (_AST.get("risk") or {}).get("dir")
            brain = (lab_report() or {}).get("brain") or {}
            charts = {(x.get("call") or {}).get("symbol"): x for x in CRS.get("charts") or []}
            guide = {}
            for g in (FPM.report() or {}).get("guide") or []:
                guide.setdefault(g["symbol"], g)
            enter = {e["symbol"]: e for e in (LAB.get("enter") or {}).get("rows") or []}
            rows = []
            with CALLS_LOCK:
                D = _S.load()
                for c in D["calls"].values():
                    if c.get("date") != day or c.get("status") not in SQ.OPEN or c.get("shadow") or c.get("kind") == "PICK":
                        continue
                    q = SQ.score(c, charts.get(c["symbol"]), guide.get(c["symbol"]), enter.get(c["symbol"]), brain, mdir)
                    if not c.get("sqs"):
                        c["sqs"] = {"score": q["score"], "tier": q["tier"], "time": t.strftime("%H:%M")}
                        _S.dirty = True
                    rows.append({**{k: c.get(k) for k in ("id", "symbol", "strike", "side", "entry", "sl", "targets", "ltp", "lot", "time", "source", "source_label", "pnl_lot",
                                                           "status", "token", "exch", "expiry", "contract", "sl_widened", "grade")}, **q})
                cal = SQ.calibrate(list(D["calls"].values()))
            rows.sort(key=lambda r: -r["score"])
            integ = SQ.integrity(t, TICK.get("t"), STATE.get("last_run"), CRS.get("time"), _S, ANGEL, FPM.STATE.get("feed_t"), market_open(t))
            SNC.update(t=time.time(), d={"rows": rows[:30], "top": rows[0] if rows else None, "integrity": integ, "crash": CRH.report(), "calib": cal,
                                          "regime": brain, "mdir": mdir, "journal": (journal() or {}).get("all"), "weights": SQ.W})
        except Exception as e:
            traceback.print_exc()
            SNC.update(t=time.time(), d={"err": str(e)[:200]})
    return SNC["d"]


CANC = {}


def candles_api(sym, tf):
    """📈 Chart Room multi-timeframe: 1 / 5 / 15 min candles (30 sec cache)."""
    from krt.instruments import INDEX_SPOT, load as load_inst
    k = f"{sym}|{tf}"
    if k in CANC and time.time() - CANC[k][0] < 30:
        return CANC[k][1]
    inst = load_inst(ROOT / "data" / "cache")
    if sym in INDEX_SPOT:
        ex, tok = INDEX_SPOT[sym]
    elif (inst.get("mcx_fut") or {}).get(sym):
        ex, tok = "MCX", inst["mcx_fut"][sym][0]
    else:
        ex, tok = "NSE", (inst.get("eq") or {}).get(sym)
    if not tok:
        return None
    iv = {"1": "ONE_MINUTE", "5": "FIVE_MINUTE", "15": "FIFTEEN_MINUTE"}.get(str(tf), "FIVE_MINUTE")
    t = now_ist()
    days = {"ONE_MINUTE": 2, "FIVE_MINUTE": 4, "FIFTEEN_MINUTE": 10}[iv]
    df = get_angel().candles(ex, tok, iv, t - pd.Timedelta(days=days), t)
    if df is None or df.empty:
        return None
    df = df.tail(120)
    out = [[i.strftime("%H:%M"), round(float(r["open"]), 2), round(float(r["high"]), 2), round(float(r["low"]), 2), round(float(r["close"]), 2), int(r["volume"])]
           for i, r in df.iterrows()]
    CANC[k] = (time.time(), out)
    return out


STC = {"t": 0, "d": None}


def strat_state():
    if time.time() - STC["t"] > 10:
        try:
            from krt import combo as CB, spreads as SPR
            from krt.calls import STORE as _S, module_health, proven_sources
            D = _S.load()
            t = now_ist()
            STC.update(t=time.time(), d={"combo": CB.STATE, "spreads": SPR.report(D), "health": module_health(D, t), "proven": sorted(proven_sources(D)),
                                          "mgu": [{"index": x.get("index"), **(x.get("mgu") or {})} for x in ((STATE.get("full") or {}).get("index") or []) if x.get("mgu")],
                                          "mgu_calls": sorted([c for c in D["calls"].values() if c.get("kind") == "MANNAN-GU"], key=lambda c: (c["date"], c.get("time") or ""), reverse=True)[:40],
                                          "combo_calls": sorted([c for c in D["calls"].values() if c.get("kind") == "COMBO"], key=lambda c: (c["date"], c.get("time") or ""), reverse=True)[:40]})
        except Exception as e:
            traceback.print_exc()
            STC.update(t=time.time(), d={"err": str(e)[:200]})
    return STC["d"]


FPC = {"t": 0, "d": None}


def fp_state():
    if time.time() - FPC["t"] > 8:
        try:
            from krt import footprint as FPM
            FPC.update(t=time.time(), d=FPM.report())
        except Exception as e:
            FPC.update(t=time.time(), d={"err": str(e)[:200]})
    return FPC["d"]


DSKC = {"t": 0, "d": None}


def dsk_state():
    if time.time() - DSKC["t"] > 10:
        try:
            from krt import dsk as DS
            from krt.calls import STORE as _S
            calls = list((_S.load().get("calls") or {}).values())
            if DS.STATE.get("time") is None:          # market மூடியிருந்தாலும் model / walk-forward காட்ட
                DS.model(calls)
                DS.STATE["model"] = {"wf": DS.MODEL["wf"], "n": DS.MODEL.get("n"), "imp": DS.MODEL.get("imp")}
            DSKC.update(t=time.time(), d={**DS.STATE, "journal": DS.journal(calls), "cfg": DS.CFG})
        except Exception as e:
            DSKC.update(t=time.time(), d={"err": str(e)[:200]})
    return DSKC["d"]


def get_angel():
    global ANGEL
    from krt.angel_api import Angel
    ANGEL = ANGEL or Angel()
    return ANGEL


def lab_report():
    if time.time() - LAB["t"] > 60:
        try:
            from krt import ailab as AL
            from krt.ai import STATE as AST
            from krt.calls import STORE as _S
            LAB.update(t=time.time(), d=AL.report(list((_S.load().get("calls") or {}).values()), STATE.get("full") or {}, AST.get("risk") or {}))
        except Exception as e:
            LAB.update(t=time.time(), d={"err": str(e)[:200]})
    return LAB["d"]


BOOT_T = time.time()
LOOP_ERR = {}


def _step(name, fn):
    """Run one loop step; never let it kill the steps after it. Last error is shown in the UI (status.sys.loop_err)."""
    try:
        fn()
        LOOP_ERR.pop(name, None)
    except Exception as e:
        LOOP_ERR[name] = {"time": now_ist().strftime("%H:%M:%S"), "err": f"{type(e).__name__}: {str(e)[:160]}"}
        traceback.print_exc()


def rss_mb():
    try:
        for ln in open("/proc/self/status"):
            if ln.startswith("VmRSS:"):
                return round(int(ln.split()[1]) / 1024)
    except Exception:
        pass
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    except Exception:
        return None


def sys_state():
    return {"up_min": round((time.time() - BOOT_T) / 60, 1), "rss_mb": rss_mb(), "loop_err": LOOP_ERR}


def light_loop():
    """v105: 🤖 Best Picks · 🌡 Mood · 🧠 Brain every 60 s on their OWN thread — they used to wait behind the heavy API chain
    (autolab / enter scan / chains …) and were skipped whenever anything before them failed."""
    time.sleep(20)
    while True:
        try:
            t = now_ist()
            hm = t.strftime("%H:%M")
            if t.weekday() < 5 and "09:15" <= hm <= "23:30":
                _step("bestpicks", lambda: bp_run(t))
                _step("mood", lambda: mood_run(t))
                _step("brain", lambda: brain_run(t))
        except Exception:
            traceback.print_exc()
        time.sleep(60)


def prebreak_loop():
    """🔭 Pre-Breakout Radar — market நேரத்தில் 60 sec-க்கு ஒருமுறை (daily bars + live quotes; candle API call இல்லை)."""
    global ANGEL
    while True:
        time.sleep(60)
        try:
            t = now_ist()
            if not (angel_configured() and market_open(t)) or GOKI_RUN.get("running"):
                continue
            from krt import ailab as AL
            from krt.angel_api import Angel
            from krt.instruments import load as load_inst
            ANGEL = ANGEL or Angel()
            _step("prebreak", lambda: AL.prebreak_run(ANGEL, load_inst(ROOT / "data" / "cache"), t, STATE.get("full") or {}))
            from krt.calls import STORE as _S0                # v105: every step isolated — one failure no longer skips the rest
            inst_ = load_inst(ROOT / "data" / "cache")
            _calls = lambda: list((_S0.load().get("calls") or {}).values())
            _step("autolab", lambda: AL.autolab_run(ANGEL, inst_, t, _calls(), STATE.get("full") or {}))
            _step("enter_scan", lambda: AL.enter_scan(ANGEL, inst_, t, STATE.get("full") or {}, _calls()))
            _step("enter_chains", lambda: AL.enter_chains(ANGEL, inst_, t))
            def _dp():
                from krt import daypicks as DP
                from krt.notify import both as _both
                DP.run(ANGEL, t, _calls(), _both)
            _step("daypicks", _dp)
            def _fp():
                from krt import footprint as FPM, bestpicks as _BPm
                from krt.ai import STATE as _AST
                from krt.notify import both as _bothf
                FPM.scan(ANGEL, inst_, t, _calls(), (_AST.get("risk") or {}).get("dir"),
                         extra=[r["symbol"] for r in (_BPm.STATE.get("rows") or [])[:6]], send=_bothf)
            _step("footprint", _fp)
            def _spr():
                from krt import spreads as SPR
                _ix = (STATE.get("full") or {}).get("index") or []
                SPR.run(ANGEL, t, _ix, next((x.get("pct") for x in _ix if x.get("index") == "NIFTY"), 0))
            _step("spreads", _spr)
            EVC["t"] = 0
            LAB["t"] = 0
            try:                                     # 🎯 DSK — 1–3 high-quality picks
                from krt import dsk as DS
                from krt.ai import STATE as AST
                from krt.calls import STORE as _S
                lr = lab_report() or {}
                DS.run(list((_S.load().get("calls") or {}).values()), STATE.get("full") or {}, t, AST.get("risk") or {}, lr.get("brain") or {})
            except Exception:
                traceback.print_exc()
        except Exception:
            traceback.print_exc()


def keepalive_loop():
    """😴 Render free plan: 15 நிமிடம் யாரும் site திறக்கலைன்னா server தூங்கிடும் → scan / calls / notifications நின்னுடும்
    (மாலை 6 மணிக்கு மேல் commodity calls வராதது இதனால் தான் இருக்கலாம்). Market நேரத்தில் 10 நிமிடத்துக்கு ஒருமுறை தன்னையே ping."""
    import urllib.request
    url = (os.getenv("RENDER_EXTERNAL_URL") or os.getenv("KEEPALIVE_URL") or "").rstrip("/")
    if not url:
        return
    while True:
        time.sleep(600)
        try:
            from krt import commodity as CM
            t = now_ist()
            if market_open(t) or CM.mcx_open(t) or ("08:45" <= t.strftime("%H:%M") <= "09:15" and t.weekday() < 5):
                urllib.request.urlopen(url + "/health", timeout=20).read()
                KEEP["t"] = real_hms()
        except Exception as e:
            KEEP["err"] = str(e)[:120]


KEEP = {"t": None, "err": None}
GOKI_RUN = {"running": False, "start": None, "done": None, "secs": None}
TICK = {"t": None, "items": {}, "err": None}


def tick_loop():
    """⚡ Live ticker: NIFTY / BANKNIFTY / FINNIFTY / SENSEX + MCX futures — 2 sec-க்கு ஒரு Angel quote (ஒரே call)."""
    global ANGEL
    while True:
        time.sleep(2)
        try:
            t = now_ist()
            from krt import commodity as CM
            nse, mcx = market_open(t), CM.mcx_open(t)
            if not angel_configured() or not (nse or mcx) or GOKI_RUN.get("running"):
                continue
            from krt.angel_api import Angel
            from krt.instruments import INDEX_SPOT, load as load_inst
            ANGEL = ANGEL or Angel()
            req, names = {}, {}
            if nse:
                for n, (ex, tok) in INDEX_SPOT.items():
                    req.setdefault(ex, []).append(tok)
                    names[tok] = n
                req.setdefault("NSE", []).append("99926017")          # India VIX (crash radar) — data வரலைன்னா skip
                names["99926017"] = "INDIA VIX"
            if mcx:
                inst = load_inst(ROOT / "data" / "cache")
                for n in CM.CFG["watch"]:
                    f = CM._fut(inst, n)
                    if f:
                        req.setdefault("MCX", []).append(f[0])
                        names[f[0]] = n
            if nse:                                  # 👣 footprint universe tokens — அதே request-ல் (extra API call இல்லை)
                try:
                    from krt import footprint as FPM
                    for ex, tks in FPM.tokens().items():
                        req.setdefault(ex, []).extend(tks)
                except Exception:
                    pass
            qs = ANGEL.quotes(req) if req else {}
            if nse:
                try:
                    FPM.feed(qs, t)
                    FPM.STATE["feed_t"] = str(t)[:19]
                except Exception:
                    pass
                try:                                 # ⚠ crash / surge radar (API call இல்லை)
                    from krt import crash as CRH
                    from krt.ai import STATE as _AST3
                    from krt.notify import both as _both3
                    CRH.tick(TICK["items"], t, _AST3.get("risk") or {}, ((FPM.STATE.get("bars") or {}).get("NIFTY") or {}).get(1), _both3)
                except Exception:
                    pass
            for tok, q in qs.items():
                n = names.get(tok)
                if n and q.get("ltp"):
                    TICK["items"][n] = {"ltp": float(q["ltp"]), "pct": round(float(q.get("percentChange") or 0), 2),
                                        "chg": round(float(q.get("netChange") or 0), 2), "mcx": n not in INDEX_SPOT and n != "INDIA VIX"}
            TICK.update(t=real_hms(), err=None)
        except Exception as e:
            TICK["err"] = str(e)[:120]
            time.sleep(5)


def mannan_loop():
    """👑 Jackpot Mannan — Index + Stock Options: 5-min candle முடிஞ்சு 1 நிமிடம் 25 sec-ல் (9:21–15:26). Commodity → mcx_loop-ல்."""
    global ANGEL
    done, trk = None, 0
    while True:
        time.sleep(5)
        try:
            real = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None)
            t = real.floor("1min")
            if angel_configured() and market_open(t) and time.time() - trk >= 30:     # 📋 setups LTP / result — 30 sec
                trk = time.time()
                try:
                    from krt import mannan as MN
                    from krt.angel_api import Angel
                    ANGEL = ANGEL or Angel()
                    MN.track_setups(ANGEL, t)
                except Exception:
                    traceback.print_exc()
            # V11: candle முடிஞ்சு ~20 sec-ல் முதல் scan (:00:20) + late data-க்கு 2-வது pass (:01:25)
            slot_a = t.minute % 5 == 0 and real.second >= 20
            slot_b = t.minute % 5 == 1 and real.second >= 25
            if not angel_configured() or not (slot_a or slot_b) or done == t or not market_open(t):
                continue
            if not ("09:20" <= t.strftime("%H:%M") <= "15:26") or GOKI_RUN.get("running"):
                continue
            done = t
            from krt import mannan as MN
            from krt.angel_api import Angel
            from krt.instruments import load as load_inst
            from krt import fullscan as FS
            ANGEL = ANGEL or Angel()
            inst = load_inst(ROOT / "data" / "cache")
            full = STATE.get("full") or {}
            for seg, fn in (("IDX", lambda: MN.run_index(ANGEL, inst, full, t)),
                            ("STK", lambda: MN.run_stocks(ANGEL, inst, full, FS.C.get("live_q") or {}, t))):
                try:
                    fn()
                except Exception as e:
                    MN.STATE[seg]["err"] = str(e)[:200]
                    traceback.print_exc()
            try:
                from krt.notify import notify_tick
                notify_tick(t)                          # 📲 Mannan calls / setups உடனே phone-க்கு
            except Exception:
                traceback.print_exc()
        except Exception:
            traceback.print_exc()


JRN = {"t": 0, "d": None}


def journal():
    if time.time() - JRN["t"] > 30:
        try:
            from krt.ai import trade_journal
            from krt.calls import STORE as _S
            JRN.update(t=time.time(), d=trade_journal(list((_S.load().get("calls") or {}).values())))
        except Exception as e:
            JRN.update(t=time.time(), d={"err": str(e)[:200]})
    return JRN["d"]


PHIST = {"t": 0, "d": None}


def pink_hist():
    if time.time() - PHIST["t"] > 15:
        try:
            from krt.ai import pink_history
            from krt.calls import STORE as _S
            PHIST.update(t=time.time(), d=pink_history(list((_S.load().get("calls") or {}).values())))
        except Exception as e:
            PHIST.update(t=time.time(), d={"err": str(e)[:200]})
    return PHIST["d"]


def radar_state():
    try:
        from krt.newsradar import STATE as RS
        return RS
    except Exception as e:
        return {"err": str(e)[:200]}


MREP = {"t": 0, "d": None}


def mannan_report():
    if time.time() - MREP["t"] > 5:
        try:
            from krt import mannan as MN
            from krt import fullscan as FS
            lp = {k: q.get("ltp") for k, q in (FS.C.get("live_q") or {}).items() if q.get("ltp")}
            for x in (STATE.get("full") or {}).get("index") or []:
                if x.get("spot"):
                    lp[x["index"]] = x["spot"]
            MREP.update(t=time.time(), d=MN.report(lp))
        except Exception as e:
            MREP.update(t=time.time(), d={"err": str(e)[:200]})
    return MREP["d"]


def real_hms():
    return pd.Timestamp.now(tz="Asia/Kolkata").strftime("%H:%M:%S")


def elite_loop():
    """👑 Elite: ஒவ்வொரு 15-min candle முடிந்த 1 நிமிடத்தில் (9:31, 9:46, 10:01…) — deep scan-க்கு காத்திருக்காது."""
    global ANGEL
    done = None
    while True:
        time.sleep(5)             # 15→5 sec: candle முடிஞ்சதும் சீக்கிரம் start
        try:
            t = now_ist()
            slot = t.floor("15min")
            if not (market_open(t) and angel_configured() and STATE.get("full")) or t.minute % 15 != 1 or done == slot:
                continue
            done = slot
            from krt.angel_api import Angel
            from krt.fullscan import run_elite_fast
            ANGEL = ANGEL or Angel()
            t0_ = time.time()
            GOKI_RUN.update(running=True, start=real_hms())
            try:
                with ANGEL.priority():          # 👑 Goki முதலில் — deep scan / V4 / chart loops காத்திருக்கும்
                    new_ = run_elite_fast(ANGEL, STATE["full"])
            finally:
                GOKI_RUN.update(running=False, done=real_hms(), secs=round(time.time() - t0_))
            g_ = (new_ or {}).get("goki")
            if isinstance(g_, dict):
                g_.update(done=GOKI_RUN["done"], secs=GOKI_RUN["secs"])
            cur_ = STATE.get("full")
            if cur_ is not new_ and isinstance(cur_, dict) and isinstance(new_, dict):
                cur_.update(goki=new_.get("goki"), elite=new_.get("elite"))   # deep scan நடுவில் STATE['full']-ஐ மாத்தியிருந்தா அதை அழிக்காம merge
            else:
                STATE["full"] = new_
        except Exception:
            traceback.print_exc()


def scheduler():
    """Market நேரத்தில் ஒவ்வொரு 15-min candle முடிந்த 1 நிமிடம் கழித்து auto scan."""
    while True:
        t = now_ist()
        slot = t.floor("15min")
        if market_open(t) and t.minute % 15 == 1 and STATE["slot"] != slot and angel_configured():
            STATE["slot"] = slot
            threading.Thread(target=do_scan, daemon=True).start()
        fslot = t.floor("5min")
        if market_open(t) and t.minute % 5 == 1 and STATE["fslot"] != fslot and angel_configured():
            STATE["fslot"] = fslot
            threading.Thread(target=do_full, daemon=True).start()
        time.sleep(15)


def next_auto():
    """Full scan: market நேரத்தில் 5 நிமிடத்துக்கு ஒருமுறை (முந்தைய scan முடிந்திருந்தால்)."""
    t = now_ist()
    for i in range(1, 60 * 24 * 4):
        c = t + pd.Timedelta(minutes=i)
        if c.minute % 5 == 1 and market_open(c):
            return str(c)
    return None


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _auth_ok(self):
        if not APP_PASSWORD:
            return True  # password set பண்ணலைன்னா login இல்லாமல் திறக்கும்
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                _, pw = base64.b64decode(h[6:]).decode("utf-8").split(":", 1)
                return pw == APP_PASSWORD
            except Exception:
                return False
        return False

    def _deny(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="KRT Terminal"')
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):                                   # v105: a crash returns a JSON error (Render showed a dropped connection as 502)
        try:
            return self._do_GET()
        except Exception as e:
            traceback.print_exc()
            try:
                return self._send(500, _json({"ok": False, "msg": f"Server error: {type(e).__name__}: {str(e)[:200]}", "answer": f"Server error: {type(e).__name__}: {str(e)[:200]}"}))
            except Exception:
                pass

    def do_POST(self):
        try:
            return self._do_POST()
        except Exception as e:
            traceback.print_exc()
            try:
                return self._send(500, _json({"ok": False, "msg": f"Server error: {type(e).__name__}: {str(e)[:200]}", "answer": f"Server error: {type(e).__name__}: {str(e)[:200]}"}))
            except Exception:
                pass

    def _do_GET(self):
        if self.path == "/health":
            return self._send(200, "ok", "text/plain")
        # 📲 service worker / manifest / icon — secret இல்லை, login இல்லாம (phone push register-க்கு)
        if self.path in ("/sw.js", "/manifest.json", "/icon.svg"):
            ct = {"/sw.js": "application/javascript; charset=utf-8", "/manifest.json": "application/manifest+json", "/icon.svg": "image/svg+xml"}[self.path]
            return self._send(200, (ROOT / "web" / self.path.lstrip("/")).read_bytes(), ct)
        if not self._auth_ok():
            return self._deny()
        if self.path in ("/", "/index.html"):
            return self._send(200, (ROOT / "web" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/push/key":
            try:
                from krt import notify as NT
                _, pub = NT.vapid()
                return self._send(200, _json({"ok": True, "key": pub, "subs": len(NT.subs()), "state": NT.STATE}))
            except Exception as e:
                return self._send(200, _json({"ok": False, "msg": f"Push setup பிழை: {e} (requirements.txt-ல் pywebpush இருக்கா?)"}))
        if self.path.startswith("/api/candles"):
            from urllib.parse import urlparse, parse_qs
            qq = parse_qs(urlparse(self.path).query)
            try:
                c_ = candles_api(str((qq.get("symbol") or [""])[0]).upper(), (qq.get("tf") or ["5"])[0]) if angel_configured() else None
            except Exception as e:
                return self._send(200, _json({"ok": False, "msg": str(e)[:120]}))
            return self._send(200, _json({"ok": bool(c_), "candles": c_ or []}))
        if self.path == "/api/ticks":
            return self._send(200, _json({**TICK, "v": APP_VERSION}))
        if self.path == "/api/status":
            cfg = load_settings().get("chartink", {})
            full_ = STATE.get("full")
            try:
                # ⚡ instant: STORE-ல் உள்ள இன்றைய calls (புது paper / exit / LTP) snapshot-ஐ விட fresh — நேரடியா merge
                from krt.calls import STORE as _CS, CALLS_LOCK as _CL
                if isinstance(full_, dict) and isinstance(full_.get("tracking"), dict):
                    day_ = str(now_ist().date())
                    with _CL:
                        fresh = {c["id"]: dict(c) for c in (_CS.load().get("calls") or {}).values() if c.get("date") == day_ and not c.get("shadow")}
                    tr_ = dict(full_["tracking"])
                    for key_ in ("today", "history"):
                        m_ = {c.get("id"): c for c in tr_.get(key_) or []}
                        m_.update(fresh)
                        tr_[key_] = sorted(m_.values(), key=lambda c: (c.get("date") or "", c.get("time") or ""), reverse=True)
                    full_ = dict(full_, tracking=tr_)
            except Exception:
                pass
            cl = saved_clauses()
            return self._send(200, _json({
                **{k: STATE[k] for k in ("scanning", "result", "error", "last_run", "full_error",
                                         "full_running", "full_last", "progress")}, "full": full_,
                "news": NEWS, "gu": GU, "goki_run": GOKI_RUN, "mannan": mannan_report(), "version": APP_VERSION, "keepalive": KEEP,
                "journal": journal(), "lab": lab_report(), "dsk": dsk_state(), "store": store_state(), "events": events_state(), "footprint": fp_state(), "strategies": strat_state(), "sniper": sniper_state(), "bestpicks": bp_state(), "fable": fable_state(), "brain": brain_state(), "mood": mood_state(), "sys": sys_state(),
                "pink_hist": pink_hist(), "radar": radar_state(), "mcx": dict(__import__("krt.commodity", fromlist=["STATE"]).STATE, err=MCXE["err"] or __import__("krt.commodity", fromlist=["STATE"]).STATE.get("err"), loop_beat=MCXE["beat"]), "telegram": __import__("krt.telegram", fromlist=["enabled"]).enabled(), "alerts": __import__("krt.telegram", fromlist=["status"]).status(), "chart": __import__("krt.chartroom", fromlist=["STATE"]).STATE,
                "configured": angel_configured(), "hosted": HOSTED, "now": str(now_ist()),
                "market_open": market_open(now_ist()), "next_auto": next_auto(),
                "chartink": {"ce_url": cfg.get("ce_url"), "pe_url": cfg.get("pe_url"),
                             "ce_saved": bool(cl.get("ce")), "pe_saved": bool(cl.get("pe"))},
            }))
        if self.path == "/api/v4":
            from krt import v4
            with v4.LOCK:
                st = {k: v4.STATE.get(k) for k in ("t", "indices", "setups", "errors", "market_open", "bt", "bt_running", "bt_prog", "prog", "tried", "journal")}
            st["running"] = V4_LK.locked()
            st["beat"], st["since"] = V4E.get("beat"), V4E.get("since")
            st["live_market"] = market_open(now_ist())
            st["settings"] = v4.settings()
            st["err"] = V4E["err"]
            return self._send(200, _json(st))
        self._send(404, _json({"error": "not found"}))

    def _do_POST(self):
        if not self._auth_ok():
            return self._deny()
        try:
            d = self._body()
        except Exception:
            return self._send(400, _json({"ok": False, "msg": "தவறான request"}))

        if self.path == "/api/level":
            try:
                from krt import ailab as AL
                from krt import fullscan as FS
                from krt.angel_api import Angel
                from krt.instruments import load as load_inst
                if not angel_configured():
                    return self._send(200, _json({"ok": False, "msg": "Angel One connect ஆகல"}))
                ag_ = get_angel()
                sym, lvl = str(d.get("symbol") or "").upper().strip(), float(d.get("level") or 0)
                if not sym or lvl <= 0:
                    return self._send(200, _json({"ok": False, "msg": "Symbol + level கொடுங்க (eg: VBL 430)"}))
                q = (FS.C.get("live_q") or {}).get(sym) or {}
                r = AL.level_lab(ag_, load_inst(ROOT / "data" / "cache"), sym, lvl, now_ist(), q.get("ltp"), q.get("vol_ratio"))
                try:
                    if not r.get("err"):
                        r["chain"] = AL.chain_flow(ag_, load_inst(ROOT / "data" / "cache"), sym, r.get("ltp") or lvl, now_ist(), r.get("lean"))
                except Exception:
                    pass
                return self._send(200, _json({"ok": not r.get("err"), "msg": r.get("err"), "lab": r}))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, _json({"ok": False, "msg": f"Level Lab பிழை: {e}"}))
        if self.path == "/api/results/add":
            try:
                from krt import events as EV
                from krt.calls import STORE as _S
                sym = str(d.get("symbol") or "").upper().strip()
                if not sym or not d.get("date"):
                    return self._send(200, _json({"ok": False, "msg": "Symbol + date கொடுங்க (eg: HAL · 2026-11-12)"}))
                dd = EV.add_manual(_S, sym, d["date"])
                EV.STATE["results"] = []
                EVC["t"] = 0
                return self._send(200, _json({"ok": True, "msg": f"✅ {sym} results {dd} diary-ல் சேர்த்தாச்சு"}))
            except Exception as e:
                return self._send(200, _json({"ok": False, "msg": f"பிழை: {e}"}))
        if self.path == "/api/push/subscribe":
            try:
                from krt import notify as NT
                n = NT.subscribe(d.get("sub"), self.headers.get("User-Agent", ""))
                NT.push("✅ KRT notifications ON", "இனி ஒவ்வொரு call / pink / setup / exit-உம் இந்த phone-க்கு வரும்.", tag="welcome")
                return self._send(200, _json({"ok": True, "msg": f"📲 Notifications ON ({n} device)"}))
            except Exception as e:
                return self._send(200, _json({"ok": False, "msg": f"Subscribe பிழை: {e}"}))
        if self.path == "/api/push/test":
            from krt import notify as NT
            n = NT.push("🔔 Test — KRT Terminal", "Notification சரியா வருது ✅ (BUY NIFTY 24000 CE · Entry ₹120 · SL ₹96 — test மட்டும்)", tag="test", urgent=True)
            return self._send(200, _json({"ok": bool(n), "msg": f"Test push {n} device-க்கு அனுப்பியாச்சு" if n else "Subscribe ஆன phone இல்லை — முதல்ல 📲 ON அழுத்துங்க"}))
        if self.path == "/api/v4/settings":
            from krt import v4
            return self._send(200, _json({"ok": True, "settings": v4.save_settings(d)}))
        if self.path == "/api/brain/ask":                   # 🧠 free, instant — reads Brain's live verdicts (no lock, no API)
            from krt import brain as BR
            from krt.ai import STATE as _AST
            return self._send(200, _json({"ok": True, "answer": BR.answer(d.get("q") or "", now_ist(), _AST.get("risk") or {})}))
        if self.path == "/api/fable/run":
            new = fable_once(now_ist(), force=True)
            from krt import fable as FB
            return self._send(200, _json({"ok": not FB.STATE.get("err"), "new": len(new), "msg": FB.STATE.get("err") or f"Fable checked — {len(new)} new pick(s)"}))
        if self.path == "/api/fable/ask":
            from krt import fable as FB
            from krt.calls import STORE as _S, CALLS_LOCK
            t = now_ist()
            pre = fable_pre()
            with CALLS_LOCK:
                D = _S.load()
                ctx = fable_ctx(D, t, pre)
                Dsnap = json.loads(json.dumps({"calls": D["calls"], "fable_picks": D.get("fable_picks") or {}}, default=str))
            ans = FB.ask(Dsnap, t, d.get("q") or "", ctx)
            FBC["t"] = 0
            return self._send(200, _json({"ok": True, "answer": ans}))
        if self.path == "/api/pick":
            global ANGEL
            from krt.calls import add_pick
            ltp = d.get("ltp")
            try:
                from krt.angel_api import Angel
                ANGEL = ANGEL or Angel()
                q = ANGEL.quotes({d.get("exch") or "NFO": [str(d.get("token"))]}).get(str(d.get("token"))) or {}
                ltp = float(q.get("ltp") or 0) or ltp
            except Exception:
                pass
            c, msg = add_pick(d, ltp, pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None), d.get("lots") or 1)
            if c:
                _snap_put(c)       # அடுத்த scan-க்கு காத்திருக்காம Paper Trade tab-ல் உடனே தெரியும்
            return self._send(200, _json({"ok": bool(c), "msg": msg, "id": (c or {}).get("id")}))
        if self.path == "/api/chart/scan":
            def _go():
                try:
                    chart_once(pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).floor("1min"))
                except Exception as e:
                    __import__("krt.chartroom", fromlist=["STATE"]).STATE["err"] = str(e)[:200]
            threading.Thread(target=_go, daemon=True).start()
            return self._send(200, _json({"ok": True, "msg": "Chart analysis ஓடுது — 20–40 sec"}))
        if self.path == "/api/whatsapp":
            from krt import telegram as TG
            if d.get("phone") and d.get("apikey"):
                TG.wa_save(d["phone"], d["apikey"])
            ok = TG.wa_send("✅ KRT Terminal WhatsApp alerts ON — இனி எல்லா calls-ம் இங்கே வரும்.") if d.get("test", True) else TG.wa_enabled()
            return self._send(200, _json({"ok": bool(ok), "msg": "✅ Saved — test message அனுப்பியாச்சு (10–30 sec-ல் WhatsApp-ல் வரும்)" if ok
                                          else "⚠ Phone + API key வேணும்", "status": TG.status()}))
        if self.path == "/api/mcx/scan":
            def _go():
                global ANGEL
                try:
                    from krt import commodity as CM
                    from krt.angel_api import Angel
                    from krt.instruments import load as load_inst
                    ANGEL = ANGEL or Angel()
                    CM.run_once(ANGEL, load_inst(ROOT / "data" / "cache"), pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).floor("1min"))
                except Exception as e:
                    MCXE["err"] = str(e)[:200]
            threading.Thread(target=_go, daemon=True).start()
            return self._send(200, _json({"ok": True, "msg": "Commodity scan ஆரம்பிச்சாச்சு — 30–60 sec"}))
        if self.path == "/api/pick/exit":
            from krt.calls import exit_pick, STORE as _ST
            c_ = (_ST.load()["calls"]).get(d.get("id")) or {}
            ltp = c_.get("ltp")
            try:
                from krt.angel_api import Angel
                ANGEL = ANGEL or Angel()
                q = ANGEL.quotes({c_.get("exch") or "NFO": [str(c_.get("token"))]}).get(str(c_.get("token"))) or {}
                ltp = float(q.get("ltp") or 0) or ltp
            except Exception:
                pass
            ok, msg = exit_pick(d.get("id"), ltp, pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None))
            if ok:
                _snap_put(_ST.load()["calls"].get(d.get("id")))
            return self._send(200, _json({"ok": ok, "msg": msg}))
        if self.path == "/api/pick/cancel":
            from krt.calls import cancel_pick
            ok = cancel_pick(d.get("id"), pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None))
            if ok:
                from krt.calls import STORE as _ST2
                _snap_put(_ST2.load()["calls"].get(d.get("id")))
            return self._send(200, _json({"ok": ok, "msg": "Cancel ஆச்சு" if ok else "முடியல"}))
        if self.path == "/api/v4/scan":
            if V4_LK.locked():
                return self._send(200, _json({"ok": False, "msg": "V4 scan ஏற்கனவே ஓடுது"}))
            threading.Thread(target=v4_run_once, daemon=True).start()
            return self._send(200, _json({"ok": True, "msg": "V4 scan ஆரம்பம்"}))
        if self.path == "/api/v4/backtest":
            from krt import v4
            if v4.STATE.get("bt_running"):
                return self._send(200, _json({"ok": False, "msg": "Backtest ஏற்கனவே ஓடுகிறது"}))
            threading.Thread(target=v4_backtest, args=(int(d.get("days") or 20),), daemon=True).start()
            return self._send(200, _json({"ok": True, "msg": "Backtest ஆரம்பம் (2-5 நிமிடம்)"}))
        if self.path == "/api/full":
            if STATE["full_running"]:
                return self._send(200, _json({"ok": False, "msg": "Full scan ஏற்கனவே ஓடுகிறது"}))
            threading.Thread(target=do_full, daemon=True).start()
            return self._send(200, _json({"ok": True, "msg": ""}))

        if self.path == "/api/scan":
            started = do_scan_async(d.get("at"))
            return self._send(200, _json({"ok": started, "msg": "" if started else "1 நிமிடம் கழித்து மறுபடி try பண்ணுங்க"}))

        if self.path == "/api/setup":
            if HOSTED:
                return self._send(200, _json({"ok": False, "msg": "Website-ல் Angel One details Render → Environment-ல் மட்டும் வைக்கவும்"}))
            import pyotp
            api, client = d.get("api_key", "").strip(), d.get("client_id", "").strip().upper()
            mpin, totp = d.get("mpin", "").strip(), d.get("totp", "").strip().replace(" ", "").upper()
            if not api or not client:
                return self._send(200, _json({"ok": False, "msg": "API key, Client ID இரண்டும் வேண்டும்"}))
            if not re.fullmatch(r"\d{4}", mpin):
                return self._send(200, _json({"ok": False, "msg": "MPIN 4 எண்கள் மட்டும்"}))
            try:
                pyotp.TOTP(totp).now()
                assert len(totp) >= 16
            except Exception:
                return self._send(200, _json({"ok": False, "msg": "TOTP secret தவறு — QR கீழே உள்ள text code-ஐ copy பண்ணுங்க"}))
            (ROOT / ".env").write_text(
                f"BROKER=angel\nANGEL_API_KEY={api}\nANGEL_CLIENT_ID={client}\nANGEL_MPIN={mpin}\nANGEL_TOTP_SECRET={totp}\n",
                encoding="utf-8")
            try:
                from dotenv import load_dotenv
                load_dotenv(ROOT / ".env", override=True)
                from krt.data.angel_provider import angel_login
                _, s = angel_login()
                name = (s.get("data") or {}).get("name", "")
                return self._send(200, _json({"ok": True, "msg": f"Angel One login OK — {name}"}))
            except Exception as e:
                return self._send(200, _json({"ok": False, "msg": f"Save ஆனது, ஆனால் login fail: {e}"}))

        if self.path == "/api/clause":
            side, clause = d.get("side"), (d.get("clause") or "").strip()
            if side not in ("ce", "pe"):
                return self._send(200, _json({"ok": False, "msg": "side தவறு"}))
            data = saved_clauses()
            if not clause:
                data.pop(side, None)
                msg = f"{side.upper()} clause நீக்கப்பட்டது — auto mode"
            elif clause.startswith("(") and "{" in clause:
                data[side] = clause
                msg = f"{side.upper()} clause saved ({len(clause)} characters)"
            else:
                return self._send(200, _json({"ok": False, "msg": "இது scan clause இல்லை — '( {' என்று தொடங்க வேண்டும்"}))
            CLAUSE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return self._send(200, _json({"ok": True, "msg": msg}))

        self._send(404, _json({"error": "not found"}))


LAST_START = [0.0]


def do_scan_async(at=None):
    # 60 second-க்குள் மறுபடி scan வேண்டாம் (Angel One rate limit பாதுகாப்பு)
    if STATE["scanning"] or time.time() - LAST_START[0] < 60:
        return False
    LAST_START[0] = time.time()
    threading.Thread(target=do_scan, args=(at,), daemon=True).start()
    return True


def restore():
    """Restart ஆனதும் கடைசி scan result-ஐ உடனே காட்டு + daily cache load."""
    try:
        from krt.store import SNAP
        from krt.fullscan import import_cache
        d = SNAP.load()
        if d.get("result"):
            r = d["result"]
            r["restored"] = d.get("saved")
            STATE.update(full=r, full_last=d.get("saved"))
        import_cache(d.get("cache"))
        from krt.store import BARS
        from krt.fullscan import import_bars
        ok = import_bars(BARS.load())
        print(" Snapshot restored:", d.get("saved"), "· bars:", ok, flush=True)
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    restore()
    threading.Thread(target=scheduler, daemon=True).start()
    threading.Thread(target=ticker, daemon=True).start()
    threading.Thread(target=news_loop, daemon=True).start()
    threading.Thread(target=gu_loop, daemon=True).start()
    threading.Thread(target=elite_loop, daemon=True).start()
    threading.Thread(target=power_loop, daemon=True).start()
    threading.Thread(target=v4_loop, daemon=True).start()
    threading.Thread(target=mcx_loop, daemon=True).start()
    threading.Thread(target=chart_loop, daemon=True).start()
    threading.Thread(target=mannan_loop, daemon=True).start()
    threading.Thread(target=tick_loop, daemon=True).start()
    threading.Thread(target=keepalive_loop, daemon=True).start()
    threading.Thread(target=fable_loop, daemon=True).start()
    threading.Thread(target=light_loop, daemon=True).start()
    threading.Thread(target=prebreak_loop, daemon=True).start()
    threading.Thread(target=events_loop, daemon=True).start()
    if angel_configured():  # start ஆனதும் ஒரு full scan
        threading.Thread(target=do_full, daemon=True).start()
    host = "0.0.0.0" if HOSTED else "127.0.0.1"
    url = f"http://127.0.0.1:{PORT}"
    srv = ThreadingHTTPServer((host, PORT), H)
    print(f"\n KRT Terminal ஓடுகிறது → {url if not HOSTED else 'hosted, port ' + str(PORT)}", flush=True)
    if not HOSTED:
        print(" இந்த window-ஐ close பண்ணா website நின்றுவிடும். Minimize பண்ணி வைங்க.\n")
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    srv.serve_forever()
