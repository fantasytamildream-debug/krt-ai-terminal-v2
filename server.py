"""KRT Terminal — local website. KRT.bat double-click செய்தால் இது ஓடும்.
உங்கள் PC-ல் மட்டும் (127.0.0.1) — வெளியே யாருக்கும் தெரியாது."""
import base64, json, os, re, sys, threading, time, traceback, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
try:                                              # v140: glibc gives every thread its own memory arena → RSS creeps to the 512 MB
    import ctypes as _ct                           # limit and the big-player loops pause. 2 arenas = same speed, far less RAM.
    _ct.CDLL("libc.so.6").mallopt(-8, 2)           # M_ARENA_MAX = 2
except Exception:
    pass
import pandas as pd

from krt.config import ROOT
from krt.runner import run_scan, now_ist, market_open, angel_configured
from krt.chartink import CLAUSE_FILE, saved_clauses
from krt.config import load_settings

# ───────────── v106 SELF-HEAL: new krt modules missing / uploaded to the wrong place ─────────────
# GitHub does not unzip, Windows renames duplicates to "brain (1).py", files land in the repo root …
# 1) search the whole project for a misplaced copy and load it as krt.<name>; 2) brain.py: fall back to the copy embedded below.
NEW_MODS = ["brain", "mood", "bestpicks", "fable", "sqs", "crash", "spreads", "combo", "footprint", "methods", "highprofit", "riser", "jarvis", "dhasvanth", "bigplayer", "coach", "bigvol", "jarvis_brain", "advance", "command", "guide", "jsniper", "smc", "bpadvice", "experts", "levelhist"]
_EMBED = {"brain": "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"}   # snapshot of krt/brain.py at v106 (real file wins when present)
HEAL = {"moved": {}, "embedded": [], "missing": []}


def _heal_modules():
    import glob, importlib, importlib.util, sys, zlib as _z
    import krt as _pkg
    for m in NEW_MODS:
        try:
            importlib.import_module(f"krt.{m}")
            continue
        except ImportError:
            pass
        cands = [p for p in glob.glob(str(ROOT / "**" / f"{m}*.py"), recursive=True)
                 if "__pycache__" not in p and "/tests/" not in p.replace("\\", "/") and Path(p).stem.split(" ")[0].split("(")[0] == m]
        cands.sort(key=lambda p: (Path(p).name != f"{m}.py", len(p)))
        done = False
        for p in cands:
            try:
                spec = importlib.util.spec_from_file_location(f"krt.{m}", p)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[f"krt.{m}"] = mod
                spec.loader.exec_module(mod)
                setattr(_pkg, m, mod)
                HEAL["moved"][m] = str(Path(p).relative_to(ROOT)) if str(p).startswith(str(ROOT)) else p
                done = True
                break
            except Exception:
                sys.modules.pop(f"krt.{m}", None)
        if not done and m in _EMBED:
            try:
                (ROOT / "krt" / f"{m}.py").write_bytes(_z.decompress(base64.b64decode(_EMBED[m])))
                importlib.invalidate_caches()
                importlib.import_module(f"krt.{m}")
                HEAL["embedded"].append(m)
                done = True
            except Exception:
                pass
        if not done:
            HEAL["missing"].append(m)


try:
    _heal_modules()
except Exception:
    traceback.print_exc()

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
        mem_guard("deep scan")                                 # v112: return the scan's pandas memory to the OS
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


def bigvol_loop():
    """🐋 v115: every minute — whole F&O market 15-min big-player volume sweep (only after a new candle closes) + all MCX commodities."""
    from krt import commodity as CM
    while True:
        n_ = pd.Timestamp.now(tz="Asia/Kolkata")         # v119: wake 15 s after every 5-min candle closes → whole market at once
        nxt = n_.floor("5min") + pd.Timedelta(minutes=5, seconds=15)
        time.sleep(max(5.0, (nxt - n_).total_seconds()))
        try:
            t = now_ist()
            nse, mcx = market_open(t), CM.mcx_open(t)
            if not angel_configured() or not (nse or mcx):
                continue
            if mem_core():
                loop_mark("bigvol", False, f"memory {MEM.get('rss')} MB")
                continue
            from krt import bigvol as BV, ailab as AL, fullscan as FSm
            from krt.angel_api import Angel
            from krt.instruments import load as load_inst
            from krt.calls import STORE as _S, OPEN as _OP
            from krt.notify import both as _b
            day = str(t.date())
            oi = AL.oi_flow((STATE.get("full") or {}).get("oi_buildup"), FSm.C.get("live_q"))
            pri = [r["symbol"] for r in oi if r.get("kind") in ("Long Built Up", "Short Built Up")][:10]
            pri += [c["symbol"] for c in (_S.load().get("calls") or {}).values() if c.get("date") == day and c.get("status") in _OP
                    and c.get("exch") != "MCX" and c["symbol"] not in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "MIDCPNIFTY")][:8]
            global ANGEL
            ANGEL = ANGEL or Angel()
            inst_ = load_inst(ROOT / "data" / "cache")
            t0 = t.tz_localize(None) if getattr(t, "tzinfo", None) else t
            BV.sweep(ANGEL, inst_, t0, list(dict.fromkeys(pri)), _b, mcx_only=not nse)
            loop_mark("bigvol")
            try:
                jv_combo_push(_b)                         # 🟡 v119: big players + an open call on the same side → yellow BUY alert
            except Exception:
                traceback.print_exc()
            if nse and "09:20" <= t0.strftime("%H:%M") <= "14:30":     # 🐋 v118: advance calls every 5 min
                from krt import advance as ADV
                from krt.calls import market_ok
                ADV.run(ANGEL, inst_, t0, oi, BV.get, FSm.C.get("live_q") or {}, market_ok, _b)
        except Exception:
            traceback.print_exc()
            time.sleep(120)


SMCC = {}          # symbol → (ts, frame) on-demand cache


def _smc_frame(ag, inst, sym, t0):
    """5-min candles (5 days) → CLOSED candles only."""
    from krt.instruments import INDEX_SPOT
    if sym in INDEX_SPOT:
        ex, tok = INDEX_SPOT[sym]
    else:
        ex, tok = "NSE", (inst.get("eq") or {}).get(sym)
    if not tok:
        return None
    df = ag.candles(ex, tok, "FIVE_MINUTE", t0 - pd.Timedelta(days=6), t0)
    if df is None or df.empty:
        return None
    lc = t0.floor("5min") - pd.Timedelta(minutes=5)
    return df[df.index <= lc].tail(300)


def _smc_add_calls(rows_):
    """Fresh TAKE setups on stocks → paper calls (kind SMC) through the normal option picker + quality gate."""
    from krt import smc as SMC, fullscan as FS, calls as CL
    from krt.instruments import load as load_inst
    t = now_ist().tz_localize(None)
    rows = []
    for s_ in rows_:
        rows.append({"symbol": s_["symbol"], "side": s_["side"], "price": s_["entry"], "sl": s_["sl"], "targets": s_.get("targets") or [],
                     "score": s_["score"], "stars": 5 if s_["score"] >= 85 else 4, "vol_ratio": None,
                     "reasons": [f"📐 {s_['kind']}: {s_.get('why') or ''}"[:120], f"score {s_['score']}/100 · R:R {s_.get('rr')}"]})
    inst = load_inst(ROOT / "data" / "cache")
    FS.pick_options(get_angel(), inst, rows)
    good = []
    for r in rows:
        o = r.get("option") or {}
        if "none" in o:
            continue
        FS.attach_plan(r, o, t, SMC.SRC)
        if (o.get("plan") or {}).get("entry"):
            good.append(r)
    return CL.add_simple(SMC.KIND, SMC.SRC, good, t)


def smc_loop():
    """📐 v122: SMC/ICT engine — 20 s after every 5-min candle closes, on indices + the stocks that matter right now."""
    global ANGEL
    while True:
        n_ = pd.Timestamp.now(tz="Asia/Kolkata")
        time.sleep(max(5.0, (n_.floor("5min") + pd.Timedelta(minutes=5, seconds=20) - n_).total_seconds()))
        try:
            t = now_ist()
            if not angel_configured() or not market_open(t) or mem_high():
                continue
            smc_run(t)
        except Exception:
            traceback.print_exc()
            time.sleep(60)


def smc_run(t):
    global ANGEL
    from krt import smc as SMC, fullscan as FSm, bigvol as BV, ailab as AL
    from krt.money import SECTOR
    from krt.angel_api import Angel
    from krt.instruments import load as load_inst
    from krt.calls import STORE as _S, CALLS_LOCK as _CL
    ANGEL = ANGEL or Angel()
    inst = load_inst(ROOT / "data" / "cache")
    t0 = t.tz_localize(None) if getattr(t, "tzinfo", None) else t
    syms = ["NIFTY", "BANKNIFTY"]
    syms += [r["symbol"] for r in (jarvis_state() or {}).get("top") or [] if r.get("exch") != "MCX"]
    M = (cc_state() or {}).get("movers") or {}
    for k in ("breakouts", "breakdowns", "gainers", "losers", "volume"):
        syms += [r["symbol"] for r in (M.get(k) or [])[:4]]
    syms += [r["symbol"] for r in sorted(BV.FEED.values(), key=lambda r: -(r.get("mult") or 0)) if r.get("date") == str(t0.date()) and r.get("exch") != "MCX"][:4]
    syms = [x for x in dict.fromkeys(syms) if x][:SMC_N]
    frames = {}
    for sym in syms:
        try:
            df = _smc_frame(ANGEL, inst, sym, t0)
            if df is not None and len(df) >= 25:
                frames[sym] = df
                SMCC[sym] = (time.time(), df)
        except Exception:
            pass
        time.sleep(0.35)
    full, money, nifty, lq, lv, age, rg, _ = _v3_inputs()
    oi = {r["symbol"]: r.get("kind") for r in AL.oi_flow(full.get("oi_buildup"), lq)}
    ctx = {"levels": lv, "live_q": lq, "oi": oi, "sectors": {x["sector"]: x["pct"] for x in money.get("sectors") or []}, "sector_of": SECTOR,
           "results": (events_state() or {}).get("results") or [], "market_open": market_open(t), "stale": bool(age is not None and age > 300),
           "regime": rg.get("label")}
    SMC.run(frames, t0, ctx, ANGEL, inst, _S, _CL, _smc_add_calls)
    try:
        _S.save()
    except Exception:
        pass


SMC_N = 18


def smc_state():
    try:
        from krt import smc as SMC
        from krt.calls import STORE as _S
        st = {k: SMC.STATE.get(k) for k in ("time", "rows", "setups", "rejected", "overview", "err", "scanned")}
        st["perf"] = SMC.performance(_S)
        st["patterns"], st["not_built"] = SMC.PATTERNS, SMC.NOT_BUILT
        return st
    except Exception as e:
        return {"err": str(e)[:100]}


def smc_chart(sym):
    """Chart payload for one symbol: from the last scan, else computed on demand (60 s cache)."""
    from krt import smc as SMC
    ch = (SMC.STATE.get("charts") or {}).get(sym)
    if ch:
        return {"ok": True, "chart": ch, "setups": [s for s in SMC.STATE.get("setups") or [] if s["symbol"] == sym], "src": "scan " + str(SMC.STATE.get("time"))}
    hit = SMCC.get(sym)
    if not hit or time.time() - hit[0] > 60:
        from krt.instruments import load as load_inst
        t0 = now_ist().tz_localize(None)
        df = _smc_frame(get_angel(), load_inst(ROOT / "data" / "cache"), sym, t0)
        if df is None or len(df) < 25:
            return {"ok": False, "msg": f"No 5-min candles for {sym} from Angel."}
        SMCC[sym] = hit = (time.time(), df)
        if len(SMCC) > 25:
            for k in sorted(SMCC, key=lambda k: SMCC[k][0])[:10]:
                SMCC.pop(k, None)
    from krt import fullscan as FSm
    an = SMC.analyse(hit[1], (FSm.C.get("levels") or {}).get(sym), sym)
    sts = SMC.setups(an, sym)
    slim = [{k: v for k, v in s.items() if k not in ("events", "sweep", "mss", "bos")} for s in sts]
    return {"ok": True, "chart": SMC.chart_payload(an, sts), "setups": slim, "mtf": SMC.mtf(hit[1]), "src": "on demand · closed 5-min candles"}


def early_loop():
    """⚡ v120: every minute (5 s after the minute) — live-quote volume per F&O stock → EARLY big BUY / SELL before the 5-min candle closes."""
    global ANGEL
    while True:
        n_ = pd.Timestamp.now(tz="Asia/Kolkata")
        time.sleep(max(3.0, (n_.floor("1min") + pd.Timedelta(minutes=1, seconds=5) - n_).total_seconds()))
        try:
            t = now_ist()
            hm = t.strftime("%H:%M")
            if not angel_configured() or not market_open(t) or not ("09:17" <= hm <= "15:25"):
                continue
            if mem_core():
                loop_mark("early", False, f"memory {MEM.get('rss')} MB")
                continue
            from krt import bigvol as BV
            from krt.angel_api import Angel
            from krt.instruments import load as load_inst
            from krt.notify import both as _b
            ANGEL = ANGEL or Angel()
            t0 = t.tz_localize(None) if getattr(t, "tzinfo", None) else t
            try:
                from krt import crash as _CRm
                _n10 = _CRm._chg("NIFTY", t, 10)
            except Exception:
                _n10 = None
            hit_ = BV.early(ANGEL, load_inst(ROOT / "data" / "cache"), t0, _b, nifty10=_n10)
            loop_mark("early", BV.ES.get("err") is None, BV.ES.get("err"))
            if hit_:
                jv_combo_push(_b)                         # an early spike on an open call's side → 🟡 yellow BUY at once
        except Exception:
            traceback.print_exc()
            time.sleep(60)


def paper_fast_loop():
    """⚡ v110: every 5 sec — LTP / SL / targets / P&L for OPEN calls + paper trades (one quote call)."""
    global ANGEL
    while True:
        time.sleep(5)
        try:
            t = now_ist()
            from krt import commodity as CM
            if not angel_configured() or not (market_open(t) or CM.mcx_open(t)) or GOKI_RUN.get("running"):
                continue
            from krt.angel_api import Angel
            from krt.calls import fast_track
            ANGEL = ANGEL or Angel()
            fast_track(ANGEL, pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).floor("s"))
        except Exception:
            traceback.print_exc()
            time.sleep(10)


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


def gu_log(snap, t):
    """v128: every GU run → a small permanent log (survives restarts): contracts checked, how close the best one came, what failed."""
    try:
        from krt.calls import STORE as _S, CALLS_LOCK as _CL
        cons = snap.get("contracts") or []
        best, bn = None, -1
        for c in cons:
            cl_ = (c.get("eval") or {}).get("classic") or {}
            ck = cl_.get("checks") or {}
            n_ = sum(1 for v in ck.values() if v)
            if ck and n_ > bn:
                best, bn = (c, cl_, ck), n_
        row = {"time": t.strftime("%H:%M"), "contracts": len(cons), "ok": sum(1 for c in cons if ((c.get("eval") or {}).get("classic") or {}).get("ok")),
               "lite": sum(1 for c in cons if ((c.get("eval") or {}).get("classic") or {}).get("lite")),
               "zones": len(snap.get("zones") or []), "dte": sorted({c.get("dte") for c in cons if c.get("dte") is not None})[:3]}
        if best:
            c, cl_, ck = best
            row["best"] = f"{c['symbol']} {c.get('strike'):g} {c.get('side')} (exp {c.get('expiry')}, {c.get('dte')}d) · {bn}/{len(ck)} checks · OI −{cl_.get('drop')}%"
            row["failed"] = [k for k, v in ck.items() if not v][:5]
        with _CL:
            d = _S.load()
            L = d.setdefault("gu_runs", {})
            L.setdefault(str(t.date()), []).append(row)
            del L[str(t.date())][:-80]
            for k in sorted(L)[:-5]:
                L.pop(k, None)
            _S.dirty = True
    except Exception:
        traceback.print_exc()


def gu_runs_state():
    from krt.calls import STORE as _S
    L = _S.load().get("gu_runs") or {}
    day = sorted(L)[-1] if L else None
    return {"day": day, "rows": list(reversed((L.get(day) or [])[-40:])) if day else []}


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
            # v136 FIX: when the morning selection found 0 strikes, gamma_unwind.run() retries the selection — but we only fetched
            # stock prices on the very first run, so every retry ran with NO prices → "Watch strikes 0" until 13:15 (GU silent)
            need_sel = need_sel or (not G.ST.get("contracts") and G.ST.get("sel_try", 0) < 12)
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
            gu_log(snap, t)
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


APP_VERSION = "v141"
EVC = {"t": 0, "d": None}


def events_loop():
    """📅 Results diary + 🌅 Pre-open + strike — weekdays 9:05–15:30, 60 sec-க்கு ஒருமுறை."""
    last_cal = 0
    while True:
        time.sleep(60)
        try:
            t = now_ist()
            hm = t.strftime("%H:%M")
            from krt import events as EV
            from krt import fullscan as FS
            from krt import ailab as AL
            from krt.calls import STORE as _S
            from krt.instruments import load as load_inst
            if time.time() - last_cal > 1800:            # v109: every 30 min, every day (weekends too) — upcoming results ready for Monday
                last_cal = time.time()
                try:
                    inst0 = load_inst(ROOT / "data" / "cache")
                except Exception:
                    inst0 = {}
                _step("results_cal", lambda: EV.refresh_calendar(_S, EV.fno_names(FS.C.get("bars"), inst0), NEWS.get("items") or [], t.date()))
                _step("results_diary", lambda: EV.diary(_S, None, {}, t, STATE.get("full") or {}, live=False))
                EVC["t"] = 0
            if t.weekday() >= 5 or not ("09:05" <= hm <= "15:30") or not angel_configured():
                continue
            ag, inst = get_angel(), load_inst(ROOT / "data" / "cache")
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
                                          "sources": EV.STATE.get("src") or {},
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


def jarvis_ctx(D, t, srows, integ):
    """Called UNDER CALLS_LOCK — must not call lock-taking helpers (sniper_state is computed before, passed in)."""
    from krt import crash as CRH, events as EV
    from krt.ai import STATE as _AST
    from krt.ailab import STATE as LAB
    from krt.chartroom import STATE as CRS
    full = STATE.get("full") or {}
    ct, lab, lv, lq, gd, pv = bp_inputs(D, t)
    return {"calls": list(D["calls"].values()), "charts": {(x.get("call") or {}).get("symbol"): x.get("analysis") or {} for x in CRS.get("charts") or []},
            "sniper": {r["id"]: r for r in srows}, "guides": gd, "enter": {e["symbol"]: e for e in (LAB.get("enter") or {}).get("rows") or []},
            "money_oi": {r.get("symbol"): r.get("oi") for r in (full.get("money") or {}).get("rows") or []},
            "idx": {x.get("index"): x for x in full.get("index") or []}, "levels": lv, "live_q": lq, "mdir": (_AST.get("risk") or {}).get("dir"),
            "crash": CRH.report(), "integrity": integ, "results": EV.STATE.get("results") or [], "ticks": TICK.get("items") or {}}


def jbrain_run(t):
    """🧠 v116 JARVIS Brain — regime, strategy×regime learning, lessons, mistake journal, level maps (read-only, no lock)."""
    from krt import jarvis_brain as JB, fullscan as FSm
    from krt.calls import STORE as _S, MARKET, breadth_now, OPEN as _OP
    from krt.crash import STATE as _CRS
    from krt.chartroom import STATE as CRS
    D = _S.load()
    calls = list((D.get("calls") or {}).values())
    day = str(t.date())
    lab = lab_report() or {}
    bv = bigvol_state() or {}
    dh = dhas_state() or {}
    bp = bp_state() or {}
    syms = [c["symbol"] for c in calls if c.get("date") == day and c.get("status") in _OP and c.get("exch") != "MCX"
            and c["symbol"] not in JB.IDX and not c.get("shadow")]
    syms += [r["symbol"] for r in (lab.get("big") or [])[:5] if r.get("symbol")]
    syms += [r["symbol"] for r in (bv.get("rows") or [])[:6] if r.get("exch") != "MCX"]
    full = STATE.get("full") or {}
    JB.run(calls, t.tz_localize(None) if getattr(t, "tzinfo", None) else t, {
        "nifty_pct": MARKET.get("nifty_pct"), "breadth": breadth_now(), "trend": full.get("trend"), "crash": dict(_CRS) if isinstance(_CRS, dict) else {},
        "levels": FSm.C.get("levels") or {}, "live_q": FSm.C.get("live_q") or {}, "orb": FSm.C.get("orb") or {}, "bars": FSm.C.get("bars") or {},
        "charts": {(x.get("call") or {}).get("symbol"): x.get("analysis") or {} for x in CRS.get("charts") or []},
        "level_syms": list(dict.fromkeys(syms))[:10], "bigvol": bv, "radar": lab.get("big") or [], "dhas_top": dh.get("top") or [],
        "best": bp.get("today") or []})


def jarvis_run(t):
    from krt import jarvis as JV
    from krt.calls import STORE as _S, CALLS_LOCK
    from krt.notify import both as _b
    sn = sniper_state() or {}                                # takes CALLS_LOCK — outside
    brain = ((lab_report() or {}).get("brain") or {}).get("kind")
    with CALLS_LOCK:
        D = _S.load()
        JV.scan(jarvis_ctx(D, t, sn.get("rows") or [], sn.get("integrity") or {}), t)
        D["_regime"] = brain or ""
        new = JV.publish(D, t, _b)
        ev = JV.track(D, t, _b)
        if new or ev or (D.get("jarvis") or {}).get("calls"):
            _S.dirty = True
    JVC["t"] = 0


JVC = {"t": 0, "d": None}


V3C = {"cc": (0, None), "guide": (0, None), "sn": (0, None)}


def _v3_inputs():
    from krt import fullscan as FSm, ailab as AL, guide as GD
    from krt.calls import breadth_now
    full = STATE.get("full") or {}
    money = full.get("money") or {}
    nifty = next((x for x in full.get("index") or [] if x.get("index") == "NIFTY"), None) or {}
    ch = money.get("chain") or {}
    nifty = {"pct": nifty.get("pct"), "spot": nifty.get("spot") or ch.get("spot"), "support": nifty.get("support") or ch.get("support"),
             "resistance": nifty.get("resistance") or ch.get("resistance"), "pcr": nifty.get("pcr") or ch.get("pcr")}
    lq = FSm.C.get("live_q") or {}
    lt = FSm.C.get("live_q_t")
    try:
        age = (now_ist().tz_localize(None) - pd.Timestamp(lt)).total_seconds() if lt is not None else None
    except Exception:
        age = None
    b = breadth_now()
    try:
        from krt.crash import report as _cr
        crash = _cr()
    except Exception:
        crash = {}
    mo = market_open(now_ist())
    rg = GD.regime(nifty if nifty.get("pct") is not None else None, {"up": b[0], "down": b[1]} if b else None, money.get("sectors"), money.get("oi"),
                   crash, stale=bool(mo and age is not None and age > 300), now=now_ist().tz_localize(None))
    return full, money, nifty, lq, FSm.C.get("levels") or {}, age, rg, AL


CCST = {}
OQC = {}            # v126 option quote cache: token → (ts, quote)
MOVSEEN = {}        # (day, tab, symbol) → first time it showed in that Top Movers tab


def opt_quotes(items, ttl=20):
    """items: [(exch, token)] → {token: {"ltp", "bid", "ask", "oi", "vol"}} — one batched Angel quote call, cached 20 s."""
    now_ = time.time()
    need = {}
    for ex, tk in items:
        if not tk:
            continue
        hit = OQC.get(str(tk))
        if not hit or now_ - hit[0] > ttl:
            need.setdefault(ex or "NFO", []).append(str(tk))
    if need and angel_configured() and market_open(now_ist()):
        try:
            qs = get_angel().quotes({k: v[:50] for k, v in need.items()}) or {}
            for tk, q in qs.items():
                dp = q.get("depth") or {}
                bid = next((float(x.get("price") or 0) for x in dp.get("buy") or [] if float(x.get("price") or 0) > 0), None)
                ask = next((float(x.get("price") or 0) for x in dp.get("sell") or [] if float(x.get("price") or 0) > 0), None)
                OQC[str(tk)] = (now_, {"ltp": float(q.get("ltp") or 0) or None, "bid": bid, "ask": ask, "oi": q.get("opnInterest"), "vol": q.get("tradeVolume")})
        except Exception:
            traceback.print_exc()
    if len(OQC) > 2000:
        for k in sorted(OQC, key=lambda k: OQC[k][0])[:800]:
            OQC.pop(k, None)
    return {str(tk): (OQC.get(str(tk)) or (0, {}))[1] for _, tk in items if tk}


MANNAN_SRC = ["Index OI", "5-min ORB", "Gamma Unwind Classic", "🛢 🥈 Order Flow + Profile", "👑 Mannan Commodity",
              "Breakout CE", "V4 ⚡ ICT Silver Bullet", "👑 Money Machine"]
MNC = {"t": 0, "d": None}
# v137: match by NAME only — the medal (🥇🥈🥉) and the "V4"/"🛢" prefix change, so "V4 🥈 Order Flow + Profile" was missed
MANNAN_KEYS = ["index oi", "5-min orb", "gamma unwind classic", "order flow + profile", "mannan commodity", "breakout ce", "ict silver bullet",
               "money machine"]


def _mn_key(src):
    s = re.sub(r"[^a-z0-9+\- ]", " ", str(src or "").lower())
    s = " ".join(w for w in s.split() if w != "v4")
    return s if s in MANNAN_KEYS else None


def mannan_state():
    """👑 v129 your 8 chosen strategies — every call today, the moment it is created, with a TAKE / WAIT / LATE / DON'T TAKE answer and a
    confidence % = the strategy's real win rate (all its closed calls) adjusted for today's conditions. 2 s cache."""
    if time.time() - MNC["t"] < 2 and MNC["d"]:
        return MNC["d"]
    from krt.calls import STORE as _S, PROVEN, OPEN as _OP, MARKET, _is_dup_shadow, proven_sources
    d = _S.load()
    if not PROVEN.get("tiers"):
        try:
            proven_sources(d)
        except Exception:
            pass
    T_ = PROVEN.get("tiers") or {}
    day = str(now_ist().date())
    npct = MARKET.get("nifty_pct")
    rows = []
    for c in (d.get("calls") or {}).values():
        if c.get("date") != day or c.get("kind") == "PICK" or not _mn_key(c.get("source")) or _is_dup_shadow(c):
            continue
        tr = T_.get(c.get("source")) or {}
        base = max(35, min(80, tr.get("win") or 50))
        conf, why = float(base), [f"{c.get('source')}: {tr.get('win', '–')}% win over {tr.get('n', '–')} calls"]
        mcx = c.get("kind") in ("MCX", "MANNAN-CMD") or c.get("exch") == "MCX"
        if not mcx and npct is not None:
            if (c.get("side") == "CE" and npct >= 0.25) or (c.get("side") == "PE" and npct <= -0.25):
                conf += 8
                why.append(f"NIFTY {npct:+.2f}% — with the market")
            elif (c.get("side") == "CE" and npct <= -0.25) or (c.get("side") == "PE" and npct >= 0.25):
                conf -= 15
                why.append(f"NIFTY {npct:+.2f}% — AGAINST the market")
        if (c.get("vol_ratio") or 0) >= 1.5:
            conf += 4
            why.append(f"volume {c.get('vol_ratio')}×")
        if c.get("pink"):
            conf += 5
            why.append("pink module")
        if c.get("grade") == "A":
            conf += 3
        e, sl, ltp = float(c.get("entry") or 0), float(c.get("sl") or 0), float(c.get("ltp") or c.get("entry") or 0)
        T = c.get("targets") or []
        st = c.get("status")
        if st not in _OP:
            v, t = "DONE", f"Finished — {st} ({'+' if (c.get('pnl_lot') or 0) >= 0 else '−'}₹{abs(round(c.get('pnl_lot') or 0)):,}/lot)"
        elif c.get("hits"):
            v, t = "HOLD", f"T1 hit — hold half, SL at entry ₹{e:g}. New entry now = late."
        elif c.get("shadow"):
            conf -= 20
            v, t = "DON'T TAKE", f"Hidden by the filter — {c.get('shadow_why') or 'filter'}"
        elif e and ltp > e * 1.05:
            conf -= 10
            v, t = "LATE", f"Premium ran {round((ltp / e - 1) * 100)}% above entry — wait for a pullback near ₹{e:g}, don't chase."
        elif e and sl and ltp <= sl + (e - sl) * 0.3:
            v, t = "AVOID", f"Close to SL ₹{sl:g} — skip."
        elif conf >= 60:
            v, t = "TAKE", f"Entry OK near ₹{e:g} (up to ₹{round(e * 1.05, 2):g}) · SL ₹{sl:g}" + (f" · T1 ₹{T[0]:g}" if T else "") + " · 1 lot, risk ≤ ₹2,500."
        else:
            v, t = "WAIT", f"Weaker today ({round(conf)}%) — skip or half size; entry near ₹{e:g}, SL ₹{sl:g}."
        rows.append({"id": c["id"], "time": str(c.get("time") or "")[:5], "source": c.get("source_label") or c.get("source"), "src": c.get("source"),
                     "symbol": c["symbol"], "strike": c.get("strike"), "side": c.get("side"), "expiry": c.get("expiry"), "entry": e or None, "sl": sl or None,
                     "targets": T[:3], "ltp": ltp or None, "status": st, "pnl_lot": c.get("pnl_lot"), "lot": c.get("lot"), "token": c.get("token"),
                     "exch": c.get("exch"), "contract": c.get("contract"), "hidden": bool(c.get("shadow")), "verdict": v, "txt": t,
                     "conf": int(max(5, min(95, round(conf)))), "why": why})
    order = {"TAKE": 0, "WAIT": 1, "HOLD": 2, "LATE": 3, "AVOID": 4, "DON'T TAKE": 5, "DONE": 6}
    rows.sort(key=lambda r: r["time"], reverse=True)              # newest first …
    rows.sort(key=lambda r: order.get(r["verdict"], 9))           # … inside each group (TAKE on top)
    d_ = {"time": now_ist().strftime("%H:%M:%S"), "rows": rows, "sources": MANNAN_SRC, "nifty": npct, "market_open": market_open(now_ist())}
    MNC.update(t=time.time(), d=d_)
    return d_


BHC = {"d": {}, "trk": None, "slot": None, "today": {}, "err": None, "time": None}


def behav_loop():
    """🧠 v135 Market Behaviour Brain: 6 months of 5-min memory, live answer after every 5-min candle, re-learns every evening."""
    global ANGEL
    from krt import behaviour as BH
    built_day = None
    while True:
        time.sleep(15)
        try:
            if not angel_configured():
                continue
            t = now_ist()
            from krt.angel_api import Angel
            ANGEL = ANGEL or Angel()
            hm = t.hour * 60 + t.minute
            stale = BH.M["built"] is not None and not BH.M.get("fresh") and time.time() - BHC.get("tried", 0) > 1200
            need = BH.M["built"] is None or stale or (t.weekday() < 5 and hm >= 15 * 60 + 40 and built_day != str(t.date()))
            if need and (stale or not (market_open(t) and BH.M["built"] is not None)):
                BHC["tried"] = time.time()
                ok = BH.build(ROOT / "data" / "cache", ANGEL, t)
                if ok and hm >= 15 * 60 + 40:
                    built_day = str(t.date())
                loop_mark("behaviour", ok, None if ok else BH.M.get("err"))
                if not ok:
                    time.sleep(300)
                continue
            if not (t.weekday() < 5 and 9 * 60 + 20 <= hm <= 15 * 60 + 32):
                continue
            slot = t.floor("5min")
            if BHC["slot"] == slot or t.second < 10 and t.minute % 5 == 0:
                continue
            BHC["slot"] = slot
            today = {}
            for n, (ex_, tok) in BH.TOKS.items():
                df = ANGEL.candles(ex_, tok, "FIVE_MINUTE", t.normalize() + pd.Timedelta(hours=9, minutes=15), t)
                if df is not None and len(df):
                    today[n] = df
            out = {}
            for n in BH.TOKS:
                if n in today:
                    _ti = TICK["items"].get(n) or {}
                    _pc = (float(_ti["ltp"]) / (1 + float(_ti["pct"]) / 100)) if _ti.get("ltp") and _ti.get("pct") is not None else None
                    out[n] = BH.live(n, today[n], today.get(BH.OTHER[n]), t, _pc)
            BHC.update(d=out, today=today, time=real_hms(), err=None)
            try:
                from krt.calls import STORE as _S, CALLS_LOCK as _CL
                BHC["trk"] = BH.track(out.get("NIFTY"), _S, t.tz_localize(None) if t.tzinfo else t, today.get("NIFTY"), _CL)
            except Exception:
                traceback.print_exc()
            loop_mark("behaviour")
        except Exception as e:
            traceback.print_exc()
            BHC["err"] = str(e)[:120]
            loop_mark("behaviour", False, str(e)[:80])


def behaviour_state():
    from krt import behaviour as BH
    tu = {k: v for k, v in (BH.M.get("tuned") or {}).items() if k != "scores"}
    if tu.get("skill") is not None:
        tu["skill"] = float(tu["skill"])
    days = {n: len(set(h[0]["date"])) for n, h in (BH.M.get("hist") or {}).items()}
    picks = {}
    for n, A in (BHC["d"] or {}).items():                       # v137: the option to look at, for the side the brain favours
        if not A:
            continue
        try:
            spot = float((TICK["items"].get(n) or {}).get("ltp") or A["spot"])
            p = A.get("p") or {}
            sides = [A["side"]] if A.get("side") else ["CE", "PE"]
            L = []
            for sd in sides:
                st = _cc_strike(n, sd, spot)
                if not st:
                    continue
                q = opt_quotes([(st.get("exch"), st.get("token"))]).get(str(st.get("token"))) or {}
                L.append({**st, "ltp": q.get("ltp"), "mode": "BUY" if A.get("side") else ("IF IT BREAKS UP" if sd == "CE" else "IF IT BREAKS DOWN")})
            picks[n] = L
        except Exception:
            traceback.print_exc()
    try:
        from krt.ai import STATE as _AIS
        _rk = _AIS.get("risk") or {}
        breadth = {"up": _rk.get("up"), "dn": _rk.get("dn")}
    except Exception:
        breadth = None
    return {"time": BHC["time"], "answers": BHC["d"], "picks": picks, "breadth": breadth, "track": BHC["trk"], "tuned": tu, "built": BH.M.get("built"), "days": days,
            "err": BHC["err"] or BH.M.get("err"), "market_open": market_open(now_ist())}


RMC = {"t": 0, "d": None, "trk": 0, "cal": None}


def roadmap_state():
    """🗺 v133 Level Roadmap for the 4 indices — live, light (no status bundle), cached 3 s."""
    if time.time() - RMC["t"] < 3 and RMC["d"]:
        return RMC["d"]
    from krt import roadmap as RMP
    t = now_ist()
    full = STATE.get("full") or {}
    I = {x.get("index"): x for x in full.get("index") or []}
    P = full.get("predict") or {}
    acc = (P.get("acc") or {}).get("dir_pct")
    today = str(full.get("session") or "")[:10] == str(t.date())
    out = {}
    for n in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"):
        ix = I.get(n) or {}
        if today:
            RMP.seed_day(n, t, ix.get("day_high"), ix.get("day_low"))
        spot = (TICK["items"].get(n) or {}).get("ltp") or ix.get("spot")
        try:
            out[n] = RMP.build(n, spot, t, ix if today else {}, P if (n == "NIFTY" and today) else None, acc)
        except Exception as e:
            out[n] = {"err": str(e)[:120]}
    if market_open(t) and time.time() - RMC["trk"] > 60:
        RMC["trk"] = time.time()
        try:
            from krt.calls import STORE as _S, CALLS_LOCK as _CL
            RMC["cal"] = RMP.track(out.get("NIFTY"), _S, t, _CL)
        except Exception:
            traceback.print_exc()
    RMC.update(t=time.time(), d={"time": real_hms(), "market_open": market_open(t), "maps": out, "calibration": RMC["cal"]})
    return RMC["d"]


EXC = {"t": 0, "d": None}


def experts_state():
    """🎓 v127 expert-style picks (4 screens) — 20 s cache. Strikes from the instrument master, premiums live."""
    if time.time() - EXC["t"] < 20 and EXC["d"]:
        return EXC["d"]
    try:
        from krt import experts as EX, smc as SMC
        from krt.money import SECTOR
        from krt.ailab import STATE as LAB
        from krt.calls import STORE as _S, PROVEN, OPEN as _OP
        from krt import fullscan as FSm
        full, money, nifty, lq, lv, age, rg, AL = _v3_inputs()
        oi = {r["symbol"]: r.get("kind") for r in AL.oi_flow(full.get("oi_buildup"), lq)}
        npct = nifty.get("pct")
        rs, sma = EX._rs_table(FSm.C.get("bars") or {})
        secs = {x["sector"]: x["pct"] for x in money.get("sectors") or []}
        pb = (LAB.get("prebreak") or {}).get("rows") or []
        A = EX.price_action_oi(lq, lv, oi, npct)
        B = EX.quality_rank(lq, secs, SECTOR, oi, npct, rs, sma)
        C = EX.vcp_breakout(pb, rs, sma, lq)
        jv = (jarvis_state() or {}).get("top") or []
        lab = [e for e in (LAB.get("enter") or {}).get("rows") or [] if e.get("status") == "OK"]
        sm = SMC.STATE.get("setups") or []
        ccd = cc_state() or {}
        big = ccd.get("big") or []
        mv = [r for t in ("gainers", "losers", "breakouts", "breakdowns") for r in ((ccd.get("movers") or {}).get(t) or [])]
        day = str(now_ist().date())
        T_ = PROVEN.get("tiers") or {}
        calls = [c for c in (_S.load().get("calls") or {}).values() if c.get("date") == day and c.get("status") in _OP and not c.get("shadow")
                 and c.get("kind") != "PICK"]
        star = [c for c in calls if (T_.get(c.get("source") or c.get("kind")) or {}).get("tier") == "STAR"]
        srcs = [("JARVIS TAKE", 2, [(r["symbol"], r["side"]) for r in jv if r.get("verdict") == "TAKE"]),
                ("AI Lab ENTER", 2, [(e["symbol"], e["side"]) for e in lab if (e.get("confidence") or 0) >= 80]),
                ("AI Lab watch", 1, [(e["symbol"], e["side"]) for e in lab if (e.get("confidence") or 0) < 80]),
                ("SMC/ICT", 2, [(x["symbol"], x["side"]) for x in sm if x.get("decision") == "TAKE"]),
                ("SMC forming", 1, [(x["symbol"], x["side"]) for x in sm if x.get("decision") == "WAIT" and x.get("zone")]),
                ("Big players", 2, [(r["symbol"], (r.get("opt") or {}).get("side")) for r in big if (r.get("ai") or {}).get("tag") == "TAKE" and r.get("opt")]),
                ("Top Movers guide", 1, [(r["symbol"], "CE" if r["ai"]["tag"] == "BUY CE" else "PE") for r in mv if (r.get("ai") or {}).get("tag", "").startswith("BUY")]),
                ("⭐ star strategy call", 2, [(c["symbol"], c["side"]) for c in star]),
                ("PA+OI screen", 1, [(p["symbol"], p["side"]) for p in A]), ("Quality screen", 1, [(p["symbol"], p["side"]) for p in B]),
                ("VCP screen", 1, [(p["symbol"], p["side"]) for p in C]),
                ("Pre-breakout", 1, [(p["symbol"], p["side"]) for p in pb if p.get("status") == "BREAKING"])]
        mdir = "CE" if (npct or 0) >= 0.25 else "PE" if (npct or 0) <= -0.25 else None
        D = EX.consensus(srcs, mdir)
        allp = A + B + C + D
        its = []
        for p_ in allp:
            c_ = next((c for c in calls if c["symbol"] == p_["symbol"] and c.get("side") == p_["side"]), None)
            if c_:
                p_["call"] = {"id": c_["id"], "entry": c_.get("entry"), "sl": c_.get("sl"), "targets": (c_.get("targets") or [])[:3], "ltp": c_.get("ltp"),
                              "strike": c_.get("strike"), "src": c_.get("source")}
            px = (lq.get(p_["symbol"]) or {}).get("ltp")
            p_["ltp"] = px
            if px:
                st_ = _cc_strike(p_["symbol"], p_["side"], px)
                if st_:
                    p_["strike"] = dict(st_)
                    its.append((st_.get("exch"), st_.get("token")))
        qq = opt_quotes(its)
        for p_ in allp:
            if p_.get("strike"):
                p_["strike"]["ltp"] = (qq.get(str(p_["strike"].get("token"))) or {}).get("ltp")
        d = {"time": now_ist().strftime("%d %b %H:%M:%S"), "nifty": npct, "boxes": [
            {"key": "pa", "title": "📈 Price Action + OI + Market Direction", "style": "Gaurav Reddy's approach", "rule": "trade only with NIFTY · price past PDH/PDL and holding VWAP · fresh OI build-up on the same side", "picks": A},
            {"key": "qr", "title": "🏅 Quality stock selection + setup ranking", "style": "Asit Baran Pati's approach", "rule": "strongest / weakest sectors · relative strength vs NIFTY · clean daily trend · liquid · not extended", "picks": B},
            {"key": "vcp", "title": "🌀 VCP + volume breakout + relative strength", "style": "Mark Minervini's method (long-only)", "rule": "tightening ranges + drying volume near the 20-day high · RS rating ≥70 · buy only the breakout with ≥1.5× volume", "picks": C},
            {"key": "con", "title": "🎓 Experienced-trader consensus", "style": "all terminal engines vote", "rule": "JARVIS · AI Lab · SMC · big players · Top Movers · ⭐ star calls · the 3 screens — more independent agreement ranks higher", "picks": D}]}
    except Exception as e:
        traceback.print_exc()
        d = {"err": str(e)[:150]}
    EXC.update(t=time.time(), d=d)
    return d


def bp_rows(n=30, mkt=None):
    """🐋 v126 today's big-player spikes (newest alert first) + strike + live premium + TAKE / WAIT / LATE / AVOID."""
    from krt import bigvol as BV, bpadvice as BA, fullscan as FSm, guide as GD
    day = str(now_ist().date())
    lq = FSm.C.get("live_q") or {}
    rows = [dict(r) for r in BV.FEED.values() if r.get("date") == day]
    # v140: ⚡ live early spikes join the table too — it kept moving even when the 5-min candle sweep was paused (memory) at 13:09
    have = {(r["symbol"], r["side"]) for r in rows if (r.get("seen") or "") >= (now_ist() - pd.Timedelta(minutes=15)).strftime("%H:%M:%S")}
    for e in BV.EARLY.values():
        if e.get("date") == day and (e["symbol"], e["side"]) not in have:
            p_, m_ = float(e.get("price") or 0), float(e.get("move") or 0)
            p0 = p_ / (1 + m_ / 100) if p_ else 0          # price 2 minutes before the spike → the spike's range
            rows.append({**e, "seen": str(e.get("full") or "")[11:19], "end": e["time"], "now": p_, "low": min(p_, p0), "high": max(p_, p0)})
    rows.sort(key=lambda r: (not r.get("backfill"), (r.get("seen") or r.get("end") or "")), reverse=True)
    rows = rows[:n]
    q = opt_quotes([((r.get("opt") or {}).get("exch"), (r.get("opt") or {}).get("token")) for r in rows])
    t0 = now_ist().tz_localize(None)
    for r in rows:
        o = r.get("opt") or {}
        oq = q.get(str(o.get("token"))) or {}
        r["opt_ltp"] = oq.get("ltp")
        npx = (lq.get(r["symbol"]) or {}).get("ltp") or r.get("now") or r.get("price")
        r["now"] = npx
        r["ai"] = BA.advise(r, npx, oq.get("ltp"), mkt, t0)
    return rows


def _cc_strike(sym, side, px):
    """Nearest listed strike (nearest expiry ≥1 day) — cached per day / symbol / side / 1% price bucket."""
    key = (str(now_ist().date()), sym, side, round(px / max(px * 0.01, 0.05)))
    if key not in CCST:
        from krt import bigvol as BV
        from krt.instruments import load as load_inst
        CCST[key] = BV.strike_for(load_inst(ROOT / "data" / "cache"), sym, side, px)
        if len(CCST) > 3000:
            CCST.clear()
    return CCST[key]


def cc_state():
    """🏛 V3.0 Command Center: top strip + top movers (5 s cache)."""
    if time.time() - V3C["cc"][0] < 5 and V3C["cc"][1]:
        return V3C["cc"][1]
    try:
        from krt import command as CMD, guide as GD, bigvol as BV
        from krt.calls import STORE as _S, OPEN as _OP
        full, money, nifty, lq, lv, age, rg, AL = _v3_inputs()
        oi = AL.oi_flow(full.get("oi_buildup"), lq)
        day = str(now_ist().date())
        cl = [c for c in (_S.load().get("calls") or {}).values() if c.get("date") == day and c.get("kind") == "PICK"]     # YOUR paper trades
        closed = [c for c in cl if c.get("status") not in _OP and c.get("pnl_lot") is not None]
        net = round(sum(c["pnl_lot"] for c in closed))
        streak = 0
        for c in sorted(closed, key=lambda c: str(c.get("exit_time") or ""), reverse=True):
            if (c.get("pnl_lot") or 0) < 0:
                streak += 1
            else:
                break
        risk = {"net": net, "open": sum(1 for c in cl if c.get("status") in _OP), "closed": len(closed), "sl_streak": streak, "whose": "your paper trades",
                "status": "LOCKED" if net <= -7500 else "COOLDOWN" if streak >= 2 else "OK"}
        scan = {"last": STATE.get("full_last"), "running": STATE.get("full_running"), "age": None if age is None else int(age),
                "fresh": "LIVE" if age is not None and age <= 180 else "STALE" if age is not None else "NO DATA", "market_open": market_open(now_ist())}
        d = {"strip": GD.strip(rg, BV.feed_report().get("summary"), risk, scan), "regime": rg,
             "movers": CMD.movers(lq, lv, oi, BV.get, mkt=("BEAR" if "BEAR" in str(rg.get("label")) else "BULL" if "BULL" in str(rg.get("label")) else None),
                                  strike_of=_cc_strike), "time": now_ist().strftime("%d %b %H:%M:%S")}
        M_ = d["movers"]
        day_, hm_ = str(now_ist().date()), now_ist().strftime("%H:%M")
        its = []
        for tab in ("gainers", "losers", "volume", "oi", "breakouts", "breakdowns"):
            for i_, r_ in enumerate(M_.get(tab) or []):
                k_ = (day_, tab, r_["symbol"])
                MOVSEEN.setdefault(k_, hm_)
                r_["since"] = MOVSEEN[k_]
                st_ = (r_.get("ai") or {}).get("strike") or {}
                if i_ < 15 and st_.get("token"):
                    its.append((st_.get("exch"), st_.get("token")))
        if len(MOVSEEN) > 5000:
            for k_ in [k_ for k_ in MOVSEEN if k_[0] != day_]:
                MOVSEEN.pop(k_, None)
        qq_ = opt_quotes(its)
        for tab in ("gainers", "losers", "volume", "oi", "breakouts", "breakdowns"):
            for r_ in M_.get(tab) or []:
                st_ = (r_.get("ai") or {}).get("strike") or {}
                if st_.get("token"):
                    r_["opt_ltp"] = (qq_.get(str(st_["token"])) or {}).get("ltp")
        d["big"] = bp_rows(30, "BEAR" if "BEAR" in str(rg.get("label")) else "BULL" if "BULL" in str(rg.get("label")) else None)
    except Exception as e:
        traceback.print_exc()
        d = {"err": str(e)[:120]}
    V3C["cc"] = (time.time(), d)
    return d


def guide_state():
    """🧭 Market Guide box (10 s cache)."""
    if time.time() - V3C["guide"][0] < 10 and V3C["guide"][1]:
        return V3C["guide"][1]
    try:
        from krt import guide as GD, bigvol as BV, coach as CO
        from krt.calls import STORE as _S
        full, money, nifty, lq, lv, age, rg, AL = _v3_inputs()
        jv = jarvis_state() or {}
        calls = list((_S.load().get("calls") or {}).values())
        d = GD.build(rg, jbrain_state(), money, nifty, jv.get("top") or [], list(BV.FEED.values()), list(BV.EARLY.values()), calls,
                     (adv_state() or {}).get("calls") or [], (events_state() or {}).get("results") or [],
                     coach_of=lambda c: CO.advise(c), now=now_ist().tz_localize(None),
                     smc=__import__("krt.smc", fromlist=["STATE"]).STATE.get("setups") or [],
                     breadth=(lambda b: {"up": b[0], "down": b[1]} if b else None)(__import__("krt.calls", fromlist=["breadth_now"]).breadth_now()))
    except Exception as e:
        traceback.print_exc()
        d = {"err": str(e)[:120]}
    V3C["guide"] = (time.time(), d)
    return d


def jsniper_state():
    """🎯 JARVIS Sniper cards (5 s cache)."""
    if time.time() - V3C["sn"][0] < 5 and V3C["sn"][1]:
        return V3C["sn"][1]
    try:
        from krt import jsniper as JS, bigvol as BV, v4 as V4
        full, money, nifty, lq, lv, age, rg, AL = _v3_inputs()
        jv = jarvis_state() or {}
        jb = jbrain_state() or {}
        d = JS.build(jv.get("top") or [], lq, lv, money.get("sectors"), (events_state() or {}).get("results") or [], jb.get("avoid") or [],
                     list(BV.EARLY.values()), V4.STATE.get("setups") or [], rg.get("label"), age if market_open(now_ist()) else None)
    except Exception as e:
        traceback.print_exc()
        d = {"err": str(e)[:120]}
    V3C["sn"] = (time.time(), d)
    return d


def adv_state():
    try:
        from krt import advance as ADV
        from krt.calls import STORE as _S
        return ADV.report(list((_S.load().get("calls") or {}).values()), str(now_ist().date()))
    except Exception as e:
        return {"err": str(e)[:100]}


JVP = {"pushed": set()}           # v123: was JVC — clashed with the JARVIS cache and broke /api/status after a restart


def jv_combos():
    """🟡 Big-player spike TODAY on a stock that has an OPEN call on the same side (BUY→CE, SELL→PE) → strongest alert."""
    from krt import bigvol as BV
    from krt.calls import STORE as _S, OPEN as _OP
    day = str(now_ist().date())
    calls = [c for c in (_S.load().get("calls") or {}).values() if c.get("date") == day and c.get("status") in _OP and not c.get("shadow")
             and c.get("kind") != "PICK"]
    by = {}
    for c in calls:
        by.setdefault((c["symbol"], c["side"]), c)
    out = []
    dlab = pd.Timestamp(day).strftime("%d %b")
    for r in list(BV.FEED.values()) + list(BV.EARLY.values()):
        if r["date"] != day or r["side"] not in ("BUY", "SELL"):
            continue
        c = by.get((r["symbol"], "CE" if r["side"] == "BUY" else "PE"))
        if not c:
            continue
        ear = bool(r.get("early"))
        ct = r["time"] if ear else r["time"][11:16]
        seen = r["time"] if ear else (r.get("seen") or ct)[:5]
        if r.get("backfill"):
            seen = r.get("end") or ct
        ctime = str(c.get("time") or "")[:5]
        # v124: the big-player move must be close to the call (≤45 min before it, or after it) — an old spike is not a reason now
        try:
            gap = (pd.Timestamp(f"{day} {ctime}") - pd.Timestamp(f"{day} {ct}")).total_seconds() / 60
        except Exception:
            gap = 0
        if gap > 45:
            continue
        t_ = max(seen, ctime)                     # the combo exists only once BOTH happened → that is its time
        out.append({"key": f"{c['id']}|{r['time']}", "t": t_, "d": day, "dl": dlab, "k": "combo", "side": c["side"], "id": c["id"],
                    "when": f"{dlab} · JARVIS alert {t_} · call {ctime} · big {r['side']} {'seen ' + seen if ear else 'candle ' + ct}",
                    "txt": f"BUY {c['symbol']} {c.get('strike') or ''} {c['side']} — {c.get('source')} call ({ctime}) + {'⚡ early ' if ear else ''}big {r['side']} {r['mult']}× at {ct} "
                           f"@ ₹{r['price']:g} · entry ₹{c.get('entry')} · SL ₹{c.get('sl')} · T1 ₹{(c.get('targets') or ['–'])[0]} · LTP ₹{c.get('ltp')}"})
    out.sort(key=lambda a: a["t"], reverse=True)
    return out


def jv_combo_push(send):
    for a in jv_combos():
        if a["key"] in JVP["pushed"]:
            continue
        JVP["pushed"].add(a["key"])
        try:
            send("🟡 JARVIS: " + a["txt"], "combo|" + a["key"], True)
        except Exception:
            pass


def jv_alerts():
    """🔔 v118 JARVIS alert feed (like the bell panel): big-player spikes + every new call today, newest first."""
    out = []
    try:
        from krt import bigvol as BV
        from krt.calls import STORE as _S
        day = str(now_ist().date())
        dlab = pd.Timestamp(day).strftime("%d %b")
        for r in BV.EARLY.values():
            if r["date"] == day:
                o = r.get("opt") or {}
                out.append({"t": r["time"], "d": r["date"], "dl": dlab, "k": "early", "side": r["side"], "exch": "NSE", "sym": r["symbol"],
                            "when": f"⚡ {dlab} · seen {r['time']} (live, candle not closed yet)",
                            "txt": f"EARLY big {r['side']} building in {r['symbol']} · last 2 min vol {r['mult']}× normal · {r['move']:+.2f}% @ {r['price']:g}"
                                   + (f" → watch {o['strike']:g} {o['side']}" if o else "")})
        for r in BV.FEED.values():
            if r["date"] == day:
                o = r.get("opt") or {}
                bf = bool(r.get("backfill"))
                out.append({"t": (r.get("end") if bf else (r.get("seen") or r["time"][11:16]))[:5], "d": r["date"], "dl": dlab, "k": "whale", "side": r["side"],
                            "exch": r.get("exch"), "sym": r["symbol"], "old": bf,
                            "when": f"{dlab} · candle {r['time'][11:16]}–{r.get('end') or ''} · "
                                    + ("loaded after a server restart (old candle, not new)" if bf else f"alert {(r.get('seen') or '')[:5]}"),
                            "txt": (f"Big {r['side']} in {r['symbol']} · {r['mult']}× avg vol @ {r['price']:g}" if r["side"] != "ABSORB" else
                                    f"Big volume (absorption) in {r['symbol']} · {r['mult']}× avg vol @ {r['price']:g}")
                                   + (f" → watch {o['strike']:g} {o['side']}" if o else "")})
        for c in (_S.load().get("calls") or {}).values():
            if c.get("date") == day and not c.get("shadow") and c.get("kind") != "PICK":
                out.append({"t": str(c.get("time"))[:5], "d": day, "dl": dlab, "when": f"{dlab} · call {str(c.get('time'))[:5]}",
                            "k": "adv" if c.get("kind") == "ADVANCE" else "call", "side": c.get("side"),
                            "txt": f"{c.get('source')}: {c['symbol']} {c.get('strike') or ''} {c['side']} · entry ₹{c.get('entry')} · SL ₹{c.get('sl')}"})
    except Exception as e:
        out.append({"t": "", "d": "", "k": "err", "txt": str(e)[:80]})
    out.sort(key=lambda a: a["t"], reverse=True)
    try:
        out = jv_combos()[:20] + out                      # 🟡 combos always on top
    except Exception:
        pass
    return out[:100]


def jbrain_state():
    try:
        from krt import jarvis_brain as JB, fullscan as FSm
        rep = JB.report()
        try:                                       # v126: level map → strike to buy + live premium + when to enter
            lq = FSm.C.get("live_q") or {}
            L = [dict(m) for m in (rep.get("levels") or [])]
            its = []
            for m in L:
                px = (lq.get(m["symbol"]) or {}).get("ltp") or m.get("px")
                m["px_live"] = px
                if m.get("bias") in ("CE", "PE") and px:
                    st_ = _cc_strike(m["symbol"], m["bias"], px)
                    m["strike_buy"] = st_
                    if st_ and st_.get("token"):
                        its.append((st_.get("exch"), st_["token"]))
            qq = opt_quotes(its)
            for m in L:
                st_, px = m.get("strike_buy") or {}, m.get("px_live")
                if st_:
                    st_["ltp"] = (qq.get(str(st_.get("token"))) or {}).get("ltp")
                trig = m.get("buy_above") if m.get("bias") == "CE" else m.get("sell_below") if m.get("bias") == "PE" else None
                if not (m.get("bias") and px and trig):
                    m["when"] = "No side yet — wait for price to break a level with a 5-min close."
                elif (m["bias"] == "CE" and px > trig) or (m["bias"] == "PE" and px < trig):
                    far = abs(px - trig) / trig * 100
                    m["when"] = (f"Level already broken ({'above' if m['bias'] == 'CE' else 'below'} {trig:,.1f}) — "
                                 + (f"OK to enter now (only {far:.1f}% past it)" if far <= 0.6 else f"{far:.1f}% past it — wait for a retest of {trig:,.1f}, don't chase"))
                else:
                    m["when"] = f"Wait — enter only on a 5-min close {'above' if m['bias'] == 'CE' else 'below'} {trig:,.1f} ({abs(px - trig) / trig * 100:.1f}% away)."
            rep["levels"] = L
        except Exception:
            traceback.print_exc()
        return rep
    except Exception as e:
        return {"err": str(e)[:100]}


def bigvol_state():
    try:
        from krt import bigvol as BV
        rep = BV.feed_report()
        try:                                       # v126: AI action + live premium for the newest 30 spikes (same as Command Center)
            big = (V3C["cc"][1] or {}).get("big") or []
            rep["ai"] = {f"{r['symbol']}|{r['time']}": {"ai": r.get("ai"), "opt_ltp": r.get("opt_ltp"), "now": r.get("now")} for r in big}
        except Exception:
            pass
        return rep
    except Exception as e:
        return {"err": str(e)[:100]}


def jarvis_state():
    if time.time() - JVC["t"] > 5:
        try:
            from krt import jarvis as JV
            from krt.calls import STORE as _S
            JVC.update(t=time.time(), d=JV.report(_S.load(), now_ist()))
        except Exception as e:
            traceback.print_exc()
            JVC.update(t=time.time(), d={"err": str(e)[:200]})
    return JVC["d"]


def dhas_run(t):
    """🏹 DHASVANTH — grade new calls of the 5 strategies against the 9.5 checklist (frozen at signal time)."""
    from krt import dhasvanth as DH, fullscan as FSm
    from krt.calls import STORE as _S, CALLS_LOCK
    from krt.notify import both as _b
    try:
        from krt.money import SECTOR as _SEC
        from krt.mood import STATE as _MS
        sm = {z.get("sector"): z.get("score") for z in _MS.get("sectors") or []}
        sector_of = {k: {"name": v, "score": sm.get(v)} for k, v in _SEC.items()}
    except Exception:
        sector_of = {}
    D0 = _S.load()
    if market_open(t) and angel_configured():
        try:
            from krt.instruments import load as load_inst
            DH.prefetch(list((D0.get("calls") or {}).values()), D0.get("dhas") or {}, t, get_angel(), load_inst(ROOT / "data" / "cache"))
        except Exception:
            traceback.print_exc()
    with CALLS_LOCK:
        D = _S.load()
        ctx = jarvis_ctx(D, t, [], {})
        full = STATE.get("full") or {}
        ctx.update(bars=FSm.C.get("bars") or {}, trend=full.get("trend"), sector_of=sector_of, full=full)
        if DH.run(D, ctx, t, None, None, _b):
            _S.dirty = True
    DHC["t"] = 0


DHC = {"t": 0, "d": None}
FLC = {"t": 0, "d": None}


def filtered_state():
    """🏆 v110 BEST MODE — today's calls the quality filter hid (still tracked) + proof: filtered vs shown P&L."""
    if time.time() - FLC["t"] < 10:
        return FLC["d"]
    try:
        from krt.calls import STORE as _S, BEST, breadth_now, MARKET, OPEN as _OP
        day = str(now_ist().date())
        cs = [c for c in (_S.load().get("calls") or {}).values() if c.get("date") == day and c.get("kind") != "PICK" and c.get("status") != "VOID"]
        from krt.calls import _is_dup_shadow, PROVEN, proven_sources
        allsh = [c for c in cs if c.get("shadow")]
        dup = [c for c in allsh if _is_dup_shadow(c)]                         # v125: copies of a trade already shown — not separate ideas
        ret = [c for c in allsh if c.get("shadow_code") == "Q_RETIRED"]
        sh = [c for c in allsh if not _is_dup_shadow(c) and c.get("shadow_code") != "Q_RETIRED"]
        ok = [c for c in cs if not c.get("shadow")]
        st = lambda L: {"n": len(L), "closed": sum(1 for c in L if c.get("status") not in _OP), "win": sum(1 for c in L if c.get("status") not in _OP and (c.get("pnl_lot") or 0) > 0),
                        "net": round(sum(c.get("pnl_lot") or 0 for c in L))}
        rows = [{k: c.get(k) for k in ("id", "time", "symbol", "strike", "side", "source", "entry", "sl", "ltp", "status", "pnl_lot", "shadow_why")}
                for c in sorted(sh, key=lambda c: c.get("time") or "", reverse=True)]
        bym = {}
        for c in sh:
            m_ = bym.setdefault(c.get("source"), {"source": c.get("source"), "n": 0, "net": 0, "why": c.get("shadow_why")})
            m_["n"] += 1
            m_["net"] += round(c.get("pnl_lot") or 0)
        try:
            proven_sources(_S.load())
        except Exception:
            pass
        T_ = PROVEN.get("tiers") or {}
        tiers = {"star": sorted([dict(v, source=k) for k, v in T_.items() if v["tier"] == "STAR"], key=lambda v: -v["net"]),
                 "retired": sorted([dict(v, source=k) for k, v in T_.items() if v["tier"] == "RETIRED"], key=lambda v: v["net"])}
        b = breadth_now()
        FLC.update(t=time.time(), d={"on": BEST["on"], "rows": rows[:80], "hidden": st(sh), "shown": st(ok), "breadth": b, "nifty": MARKET.get("nifty_pct"),
                                     "dups": st(dup), "retired_today": st(ret), "by_module": sorted(bym.values(), key=lambda m: -m["n"]), "tiers": tiers,
                                     "live": bool(MARKET.get("nifty_live_t") and time.time() - MARKET["nifty_live_t"] < 30)})
    except Exception as e:
        FLC.update(t=time.time(), d={"err": str(e)[:150]})
    return FLC["d"]


def dhas_state():
    if time.time() - DHC["t"] > 5:
        try:
            from krt import dhasvanth as DH
            from krt.calls import STORE as _S
            DHC.update(t=time.time(), d=DH.report(_S.load(), now_ist()))
        except Exception as e:
            traceback.print_exc()
            DHC.update(t=time.time(), d={"err": str(e)[:200]})
    return DHC["d"]


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
        day_ = str(t.date())
        held = {(x.get("symbol"), x.get("side")) for x in calls.values() if x.get("kind") == "PICK" and x.get("date") == day_}
        for p in new:
            c = calls.get(p["id"]) or {}
            from krt.calls import market_ok as _mok
            if (c.get("symbol"), c.get("side")) in held or c.get("shadow") or _mok(c):
                continue                                # v110/v113: one paper trade per stock+side per day · live market must agree
            held.add((c.get("symbol"), c.get("side")))
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
            try:                                              # 🧭 v113: AI coach line on every pick
                from krt import coach as CO, riser as RS_
                from krt.calls import market_ok, PROVEN
                from krt.ailab import oi_flow
                byid = {c["id"]: c for c in calls}
                oi_side = {r["symbol"]: r["side"] for r in oi_flow((STATE.get("full") or {}).get("oi_buildup"), FSm.C.get("live_q"))
                           if r.get("kind") in ("Long Built Up", "Short Built Up")}
                rise = {r["id"]: r for r in RS_.STATE.get("live") or []}
                for p_ in R.get("today") or []:
                    c_ = dict(byid.get(p_.get("id")) or p_)
                    p_["coach"] = CO.advise(c_, market_ok(c_), oi_side.get(c_.get("symbol")), rise.get(c_.get("id")), c_.get("source") in PROVEN["set"])
            except Exception:
                traceback.print_exc()
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
    tf = str(tf).upper()
    iv = {"1": "ONE_MINUTE", "3": "THREE_MINUTE", "5": "FIVE_MINUTE", "15": "FIFTEEN_MINUTE", "30": "THIRTY_MINUTE", "60": "ONE_HOUR",
          "D": "ONE_DAY", "W": "ONE_DAY"}.get(tf, "FIVE_MINUTE")
    t = now_ist()
    days = {"ONE_MINUTE": 2, "THREE_MINUTE": 3, "FIVE_MINUTE": 4, "FIFTEEN_MINUTE": 10, "THIRTY_MINUTE": 15, "ONE_HOUR": 30, "ONE_DAY": 900 if tf == "W" else 250}[iv]
    df = get_angel().candles(ex, tok, iv, t - pd.Timedelta(days=days), t)
    if df is None or df.empty:
        return None
    if tf == "W":                                            # weekly = real daily bars resampled (Mon–Fri)
        df = df.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    df = df.tail(120)
    fmt = "%d-%b" if tf in ("D", "W") else "%H:%M"
    out = [[i.strftime(fmt), round(float(r["open"]), 2), round(float(r["high"]), 2), round(float(r["low"]), 2), round(float(r["close"]), 2), int(r["volume"]),
            i.strftime("%Y-%m-%d")] for i, r in df.iterrows()]
    CANC[k] = (time.time(), out)
    return out


STRC = {"t": 0, "d": None}          # v132: was also named STC — clashed with the status cache below


def strat_state():
    if time.time() - STRC["t"] > 10:
        try:
            from krt import combo as CB, spreads as SPR
            from krt.calls import STORE as _S, module_health, proven_sources
            D = _S.load()
            t = now_ist()
            STRC.update(t=time.time(), d={"combo": CB.STATE, "spreads": SPR.report(D), "health": module_health(D, t), "proven": sorted(proven_sources(D)),
                                          "mgu": [{"index": x.get("index"), **(x.get("mgu") or {})} for x in ((STATE.get("full") or {}).get("index") or []) if x.get("mgu")],
                                          "mgu_calls": sorted([c for c in D["calls"].values() if c.get("kind") == "MANNAN-GU"], key=lambda c: (c["date"], c.get("time") or ""), reverse=True)[:40],
                                          "combo_calls": sorted([c for c in D["calls"].values() if c.get("kind") == "COMBO"], key=lambda c: (c["date"], c.get("time") or ""), reverse=True)[:40]})
        except Exception as e:
            traceback.print_exc()
            STRC.update(t=time.time(), d={"err": str(e)[:200]})
    return STRC["d"]


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


STATUS_LOCK = threading.Lock()
SWR = {}


def _swr(fn, every=2):
    """v133 stale-while-revalidate: heavy sections (Angel quotes, option chains) refresh in a BACKGROUND thread;
    the status build takes the last finished copy instantly (page data was taking 21 s: cc 11 s + sniper 6 s + guide 4 s)."""
    k = fn.__name__

    def run():
        e = SWR.get(k)
        if e is None:
            v = fn()
            SWR[k] = {"v": v, "t": time.time(), "busy": False}
            return v
        if not e["busy"] and time.time() - e["t"] > every:
            e["busy"] = True

            def bg():
                try:
                    e.update(v=fn(), t=time.time())
                except Exception:
                    traceback.print_exc()
                finally:
                    e["busy"] = False
            threading.Thread(target=bg, daemon=True, name="swr-" + k).start()
        return e["v"]
    run.__name__ = k
    return run
STB = {"start": None, "tid": None, "where": None, "last_ms": None, "slow": [], "built": None}   # v132 status-build watchdog


def _status_watch():
    """A status build has run > 45 s → log WHERE it is stuck (Render logs) once, and expose it in /api/ticks."""
    st = STB.get("start")
    if not st or time.time() - st < 45 or STB.get("where"):
        return
    try:
        fr = sys._current_frames().get(STB.get("tid"))
        if fr is not None:
            stk = traceback.format_stack(fr)[-6:]
            STB["where"] = " ← ".join(x.strip().splitlines()[0].replace('File "', "").split(", in ")[-1] + "@" + x.strip().split(", line ")[1].split(",")[0]
                                      for x in reversed(stk) if ", line " in x)[:300]
            print("⚠ STATUS BUILD STUCK", int(time.time() - st), "s:\n" + "".join(stk), flush=True)
    except Exception:
        STB["where"] = "unknown"
STC = {"t": 0, "b": None, "gz": None}


def mem_guard(tag=""):
    """v112: free RAM back to the OS (glibc keeps freed pandas memory otherwise). → current RSS MB."""
    import gc
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass
    r = rss_mb() or 0
    MEM.update(rss=r, t=time.strftime("%H:%M:%S"), tag=tag, peak=max(MEM.get("peak") or 0, r))
    return r


MEM = {"rss": 0, "peak": 0, "t": None, "tag": "", "skipped": 0}
MEM_HIGH = int(os.environ.get("KRT_MEM_HIGH", "400"))       # MB: above this, optional loops pause for one cycle


LOOPS = {}          # v125: loop name → {"ok": last good run, "skip": skips, "why": last skip reason}


def loop_mark(name, ok=True, why=None):
    L = LOOPS.setdefault(name, {"ok": None, "skip": 0, "why": None})
    if ok:
        L.update(ok=now_ist().strftime("%H:%M:%S"), why=None)
    else:
        L["skip"] += 1
        L["why"] = why


def free_optional():
    """Drop rebuildable caches (SMC frames, strike cache, Command Center cache) before giving up on a core loop."""
    try:
        SMCC.clear()
        CCST.clear()
        from krt import command as _CMD, smc as _SM
        _CMD.CACHE.clear()
        _SM.STATE["charts"] = {}
    except Exception:
        pass


def mem_core():
    """v125: core loops (big players ⚡ early + 5-min sweep) only pause near the real 512 MB limit, after freeing optional caches."""
    r = rss_mb() or 0
    if r >= MEM_HIGH:
        free_optional()
        r = mem_guard("core")
    return r >= MEM_HIGH + 70


def mem_high():
    r = rss_mb() or 0
    if r >= MEM_HIGH:
        r = mem_guard("high")
    if r >= MEM_HIGH:
        MEM["skipped"] += 1
        return True
    return False


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


IDC = {"t": 0, "d": None}


def idx_diag_state():
    if time.time() - IDC["t"] > 10:
        try:
            from krt.calls import STORE as _S, index_diag
            IDC.update(t=time.time(), d=index_diag(_S.load(), now_ist()))
        except Exception as e:
            IDC.update(t=time.time(), d={"err": str(e)[:160]})
    return IDC["d"]


def sys_state():
    return {"up_min": round((time.time() - BOOT_T) / 60, 1), "rss_mb": rss_mb(), "loop_err": LOOP_ERR, "heal": HEAL, "mem": MEM}


def riser_loop():
    """🚀 every 20 s: premium climbing fast on an open call → early alert (no API calls)."""
    time.sleep(30)
    while True:
        try:
            t = now_ist()
            if t.weekday() < 5 and "09:15" <= t.strftime("%H:%M") <= "23:30":
                from krt import riser as RS
                from krt.calls import STORE as _S, CALLS_LOCK
                from krt.notify import both as _b
                with CALLS_LOCK:
                    calls = [dict(c) for c in (_S.load().get("calls") or {}).values() if c.get("date") == str(t.date())]
                _step("riser", lambda: RS.scan(calls, t, _b))
        except Exception:
            traceback.print_exc()
        time.sleep(10)                                # v113: every 10 s (open-call prices now refresh every 5 s)


def riser_state():
    """🚀 rising list + 🧭 coach line + stock volume / OI flow (v113)."""
    from krt import riser as RS_, coach as CO, fullscan as FSm
    R = RS_.report(str(now_ist().date()))
    try:
        from krt.calls import STORE as _S, market_ok, PROVEN
        from krt.ailab import oi_flow
        calls = (_S.load().get("calls") or {})
        fl = {r["symbol"]: r for r in oi_flow((STATE.get("full") or {}).get("oi_buildup"), FSm.C.get("live_q"))}
        live = []
        for r in R.get("live") or []:
            c = dict(calls.get(r["id"]) or {})
            f = fl.get(r["symbol"]) or {}
            q = ((FSm.C.get("live_q") or {}).get(r["symbol"]) or {})
            live.append(dict(r, vr=q.get("vol_ratio"), oi=(f.get("kind") or "") + (f" · {f['flow']}" if f.get("flow") else ""),
                             coach=CO.advise(c, market_ok(c), f.get("side") if f.get("kind") in ("Long Built Up", "Short Built Up") else None, r,
                                             c.get("source") in PROVEN["set"]) if c else None))
        R = dict(R, live=live)
    except Exception:
        traceback.print_exc()
    return R


HPC = {"t": 0, "d": None}


def hp_state():
    if time.time() - HPC["t"] > 10:
        try:
            from krt import highprofit as HP, riser as RS
            from krt.calls import STORE as _S
            HPC.update(t=time.time(), d=HP.report(_S.load(), str(now_ist().date()), RS.STATE.get("live")))
        except Exception as e:
            HPC.update(t=time.time(), d={"err": str(e)[:200]})
    return HPC["d"]


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
                if not mem_high():                             # v112: under memory pressure skip the optional AI layers this minute
                    _step("jarvis_brain", lambda: jbrain_run(t))   # 🧠 regime + learning + mistakes + level maps
                    _step("jarvis", lambda: jarvis_run(t))     # 🤖 JARVIS — Boss of the Boss calls
                    _step("dhasvanth", lambda: dhas_run(t))    # 🏹 DHASVANTH — 9.5 checklist for the 5 best strategies
                mem_guard("light")
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
                    _nf = next((x for x in (STATE.get("full") or {}).get("index") or [] if x.get("index") == "NIFTY"), {})
                    if str((STATE.get("full") or {}).get("session") or "")[:10] == str(t.date()):
                        CRH.seed_day(t, _nf.get("day_high"), _nf.get("day_low"))     # v131: day high survives a restart (slow-bleed signal)
                    CRH.tick(TICK["items"], t, _AST3.get("risk") or {}, ((FPM.STATE.get("bars") or {}).get("NIFTY") or {}).get(1), _both3,
                             ((FPM.STATE.get("bars") or {}).get("BANKNIFTY") or {}).get(1))
                except Exception:
                    pass
            for tok, q in qs.items():
                n = names.get(tok)
                if n and q.get("ltp"):
                    TICK["items"][n] = {"ltp": float(q["ltp"]), "pct": round(float(q.get("percentChange") or 0), 2),
                                        "chg": round(float(q.get("netChange") or 0), 2), "mcx": n not in INDEX_SPOT and n != "INDIA VIX"}
            TICK.update(t=real_hms(), err=None)
            if nse:
                try:                                 # 🗺 v133 level roadmap — keep live index ticks (no API call)
                    from krt import roadmap as RMP
                    for n_ in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"):
                        RMP.push(n_, t, (TICK["items"].get(n_) or {}).get("ltp"))
                except Exception:
                    pass
            try:                                     # v110: market filters use LIVE NIFTY % (was Friday's % until the deep scan finished)
                from krt.calls import MARKET as _MKT
                if (TICK["items"].get("NIFTY") or {}).get("ltp") and nse:
                    _MKT.update(nifty_pct=TICK["items"]["NIFTY"]["pct"], nifty_live_t=time.time())
            except Exception:
                pass
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

    def _send_status(self):
        b = STC["b"]
        if "gzip" in (self.headers.get("Accept-Encoding") or ""):
            if STC["gz"] is None:
                import gzip
                STC["gz"] = gzip.compress(b, 5)
            g = STC["gz"]
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(g)))
            self.end_headers()
            self.wfile.write(g)
            return
        return self._send(200, b)

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
        STC["t"] = 0                                     # v112: next status shows the change at once
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
        if self.path.startswith("/api/cc/"):            # 🏛 v121 Command Center: real option chain + strike premium chart
            from urllib.parse import urlparse, parse_qs
            qq = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            if not angel_configured():
                return self._send(200, _json({"ok": False, "msg": "Angel One not configured — no live data (nothing is made up)."}))
            try:
                from krt import command as CMD
                from krt.instruments import load as load_inst
                if self.path.startswith("/api/cc/chain"):
                    sym = str(qq.get("symbol") or "").upper()
                    r_ = CMD._c(f"ch|{sym}|{qq.get('expiry')}", 15, lambda: CMD.chain(get_angel(), load_inst(ROOT / "data" / "cache"), sym, qq.get("expiry")))
                    return self._send(200, _json(r_))
                if self.path.startswith("/api/cc/levels"):
                    sym = str(qq.get("symbol") or "").upper()

                    def _lh():
                        from krt import levelhist as LH
                        from krt.instruments import INDEX_SPOT
                        inst_ = load_inst(ROOT / "data" / "cache")
                        ex, tok = INDEX_SPOT[sym] if sym in INDEX_SPOT else ("NSE", (inst_.get("eq") or {}).get(sym))
                        if not tok:
                            return {"ok": False, "msg": f"{sym}: no token"}
                        t0 = now_ist().tz_localize(None)
                        df = get_angel().candles(ex, tok, "ONE_DAY", t0 - pd.Timedelta(days=740), t0)
                        if df is None or len(df) < 120:
                            return {"ok": False, "msg": f"{sym}: not enough daily history from Angel"}
                        if market_open(now_ist()):
                            df = df[df.index.date < t0.date()]          # today's daily candle is not closed yet
                        from krt import fullscan as FSm
                        px = (FSm.C.get("live_q") or {}).get(sym, {}).get("ltp")
                        r_ = LH.analyse(df, px)
                        return dict(r_ or {}, ok=bool(r_), symbol=sym, msg=None if r_ else "not enough history")
                    return self._send(200, _json(CMD._c(f"lh|{sym}", 6 * 3600 if not market_open(now_ist()) else 1800, _lh)))
                if self.path.startswith("/api/cc/opt"):
                    lot = float(qq["lot"]) if qq.get("lot") else None
                    return self._send(200, _json(CMD.opt_candles(get_angel(), qq.get("exch") or "NFO", str(qq.get("token") or ""), qq.get("tf") or "5", lot)))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, _json({"ok": False, "msg": str(e)[:150]}))
            return self._send(404, _json({"ok": False}))
        if self.path.startswith("/api/smc/chart"):      # 📐 v122 SMC chart with boxes
            from urllib.parse import urlparse, parse_qs
            sym = str((parse_qs(urlparse(self.path).query).get("symbol") or [""])[0]).upper()
            if not angel_configured():
                return self._send(200, _json({"ok": False, "msg": "Angel One not configured."}))
            try:
                return self._send(200, _json(smc_chart(sym)))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, _json({"ok": False, "msg": str(e)[:150]}))
        if self.path.startswith("/api/candles"):
            from urllib.parse import urlparse, parse_qs
            qq = parse_qs(urlparse(self.path).query)
            try:
                c_ = candles_api(str((qq.get("symbol") or [""])[0]).upper(), (qq.get("tf") or ["5"])[0]) if angel_configured() else None
            except Exception as e:
                return self._send(200, _json({"ok": False, "msg": str(e)[:120]}))
            return self._send(200, _json({"ok": bool(c_), "candles": c_ or []}))
        if self.path == "/api/mannan":                  # 👑 v129 Mannan Strategy Box — fast (polled every 3 s)
            try:
                return self._send(200, _json(mannan_state()))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, _json({"err": str(e)[:120], "rows": []}))
        if self.path == "/api/behaviour":
            try:
                return self._send(200, _json(behaviour_state()))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, _json({"err": str(e)[:120], "answers": {}}))
        if self.path == "/api/roadmap":
            try:
                return self._send(200, _json(roadmap_state()))
            except Exception as e:
                traceback.print_exc()
                return self._send(200, _json({"err": str(e)[:120], "maps": {}}))
        if self.path == "/api/ticks":
            _status_watch()
            sb = STB.get("start")
            try:
                from krt import crash as _CR, bigvol as _BV
                _cr = {k: _CR.STATE.get(k) for k in ("level", "side", "signals", "time")}
                _cr["turn"] = {k: _CR.TURN.get(k) for k in ("side", "since", "off", "day", "text", "strong")} if _CR.TURN.get("side") else None
                _td = now_ist().strftime("%Y-%m-%d")
                _bg = sorted([r for r in list(_BV.FEED.values()) if r.get("date") == _td and r.get("side") in ("BUY", "SELL") and not r.get("backfill")]
                             + [r for r in list(_BV.EARLY.values()) if r.get("date") == _td], key=lambda r: r.get("seen") or str(r.get("full") or "")[11:19], reverse=True)[:8]
                _big = [{"k": f"{r['symbol']}|{r['time']}|{'E' if r.get('early') else 'C'}", "symbol": r["symbol"], "side": r["side"], "mult": r.get("mult"),
                         "early": bool(r.get("early")), "time": str(r["time"])[-5:], "strike": (r.get("opt") or {}).get("strike"),
                         "opt": (r.get("opt") or {}).get("side")} for r in _bg]
                _big = [b for b in _big] + [{"k": f"SCR|{r['symbol']}|{r['time']}|{r['side']}", "symbol": r["symbol"], "side": r["side"], "crash": True,
                         "m10": r["m10"], "vol": r["vol"], "time": r["time"], "strike": (r.get("opt") or {}).get("strike"), "opt": (r.get("opt") or {}).get("side"),
                         "sl": r.get("ul_sl"), "price": r.get("price")} for r in sorted(_BV.SCR.values(), key=lambda r: r["full"], reverse=True)[:6] if r["date"] == _td]
                try:
                    from krt import footprint as _FPm
                    _big += [{"k": f"IDX|{x['key']}", "symbol": x["symbol"], "side": "BUY" if x["side"] == "CE" else "SELL", "index": True,
                              "mult": None, "delta": x.get("delta_pct"), "stack": x.get("stack"), "time": x["time"], "px": x.get("px")}
                             for x in list(_FPm.STATE.get("signals") or [])[-30:]
                             if x.get("date") == _td and x["symbol"] in ("NIFTY", "BANKNIFTY", "SENSEX") and abs(x.get("delta_pct") or 0) >= 60 and (x.get("stack") or 0) >= 3][-4:]
                except Exception:
                    pass
                from krt import riser as _RS
                _rise = [{"k": f"{a['id']}|{a['ltp']}", "symbol": a["symbol"], "strike": a.get("strike"), "side": a.get("side"), "chg3m": a.get("chg3m"),
                          "state": a.get("state"), "hidden": a.get("hidden"), "ltp": a.get("ltp"), "time": a.get("time"), "act": a.get("act")}
                         for a in list(_RS.STATE.get("alerts") or [])[:6]]
            except Exception:
                _cr, _big, _rise = None, [], []
            try:
                from krt.calls import CALLS_LOCK as _CLk
                _lk = _CLk.held()
            except Exception:
                _lk = None
            return self._send(200, _json({**TICK, "v": APP_VERSION, "crash": _cr, "big": _big, "rise": _rise,
                                          "sbusy": ({"s": int(time.time() - sb), "where": STB.get("where"), "lock": _lk} if sb and time.time() - sb > 20 else None),
                                          "lock": (_lk if _lk and _lk["s"] >= 15 else None)}))
        if self.path == "/api/status":
            # v112: build the big status JSON at most once per 3 s and share it across clients (lower peak RAM), gzip once.
            # v132: if another request is already building, serve the LAST status at once (was: wait in a queue → page stuck on "Loading…")
            got = STATUS_LOCK.acquire(False) if STC["b"] else STATUS_LOCK.acquire(timeout=100)
            if not got:
                _status_watch()
                if STC["b"]:
                    return self._send_status()
                return self._send(503, _json({"err": "status is being built — retrying"}))
            try:
              STB.update(start=time.time(), tid=threading.get_ident(), where=None)
              if time.time() - STC["t"] >= 3 or not STC["b"]:
                cfg = load_settings().get("chartink", {})
                full_ = STATE.get("full")
                try:
                    # ⚡ instant: STORE-ல் உள்ள இன்றைய calls (புது paper / exit / LTP) snapshot-ஐ விட fresh — நேரடியா merge
                    from krt.calls import STORE as _CS, CALLS_LOCK as _CL
                    if isinstance(full_, dict) and isinstance(full_.get("tracking"), dict):
                        day_ = str(now_ist().date())
                        if not _CL.acquire(timeout=3):          # v136: a slow loop holding the lock must not freeze the page
                            raise TimeoutError("calls lock busy")
                        try:
                            fresh = {c["id"]: dict(c) for c in (_CS.load().get("calls") or {}).values() if c.get("date") == day_ and not c.get("shadow")}
                        finally:
                            _CL.release()
                        tr_ = dict(full_["tracking"])
                        for key_ in ("today", "history"):
                            m_ = {c.get("id"): c for c in tr_.get(key_) or []}
                            m_.update(fresh)
                            tr_[key_] = sorted(m_.values(), key=lambda c: (c.get("date") or "", c.get("time") or ""), reverse=True)
                        full_ = dict(full_, tracking=tr_)
                except Exception:
                    pass
                cl = saved_clauses()

                _slow = []

                def _safe(fn):
                    t_ = time.time()
                    try:
                        return fn()
                    except Exception as e_:             # one broken section must never take the whole page down (HTTP 500)
                        traceback.print_exc()
                        return {"err": f"{getattr(fn, '__name__', 'section')}: {type(e_).__name__}: {str(e_)[:120]}"}
                    finally:
                        if time.time() - t_ > 1.5:
                            _slow.append(f"{getattr(fn, '__name__', '?')} {time.time() - t_:.1f}s")
                STC.update(t=time.time(), gz=None, b=_json({
                    **{k: STATE[k] for k in ("scanning", "result", "error", "last_run", "full_error",
                                             "full_running", "full_last", "progress")}, "full": full_,
                    "news": NEWS, "gu": GU, "goki_run": GOKI_RUN, "mannan": _safe(mannan_report), "version": APP_VERSION, "keepalive": KEEP,
                    "journal": _safe(journal), "lab": _safe(lab_report), "dsk": _safe(dsk_state), "store": _safe(store_state), "events": _safe(events_state), "footprint": _safe(fp_state), "strategies": _safe(strat_state), "sniper": _safe(sniper_state), "bestpicks": _safe(bp_state), "fable": _safe(fable_state), "brain": _safe(brain_state), "mood": _safe(mood_state), "sys": _safe(sys_state), "index_diag": _safe(idx_diag_state), "highprofit": _safe(hp_state), "jarvis": _safe(jarvis_state), "dhasvanth": _safe(dhas_state), "bigvol": _safe(_swr(bigvol_state)), "jbrain": _safe(_swr(jbrain_state)), "advance": _safe(adv_state), "jv_alerts": _safe(jv_alerts), "filtered": _safe(filtered_state),
                    "cc": _safe(_swr(cc_state)), "experts": _safe(_swr(experts_state)), "gu_runs": _safe(gu_runs_state), "loops": dict(LOOPS, mem=MEM.get("rss")), "guide": _safe(_swr(guide_state)), "jsniper": _safe(_swr(jsniper_state)), "smc": _safe(_swr(smc_state)),
                    "riser": _safe(_swr(riser_state)),
                    "pink_hist": _safe(pink_hist), "radar": _safe(radar_state), "mcx": dict(__import__("krt.commodity", fromlist=["STATE"]).STATE, err=MCXE["err"] or __import__("krt.commodity", fromlist=["STATE"]).STATE.get("err"), loop_beat=MCXE["beat"]), "telegram": __import__("krt.telegram", fromlist=["enabled"]).enabled(), "alerts": __import__("krt.telegram", fromlist=["status"]).status(), "chart": __import__("krt.chartroom", fromlist=["STATE"]).STATE,
                    "configured": angel_configured(), "hosted": HOSTED, "now": str(now_ist()),
                    "status_build": {"last_ms": STB.get("last_ms"), "slow": STB.get("slow"), "built": real_hms()},
                    "market_open": market_open(now_ist()), "next_auto": next_auto(),
                    "chartink": {"ce_url": cfg.get("ce_url"), "pe_url": cfg.get("pe_url"),
                                 "ce_saved": bool(cl.get("ce")), "pe_saved": bool(cl.get("pe"))},
                }).encode("utf-8"))
                STB.update(last_ms=round((time.time() - STB["start"]) * 1000), slow=_slow[:8])
                if STB["last_ms"] > 8000:
                    print("⚠ slow status build", STB["last_ms"], "ms:", _slow, flush=True)
            finally:
                STB.update(start=None, where=None)
                STATUS_LOCK.release()
            return self._send_status()                  # socket write outside the lock (slow phone never blocks others)
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
        if self.path == "/api/jarvis/ask":                  # 🤖 answers from JARVIS's current scan (no lock, no API)
            from krt import jarvis as JV, jarvis_brain as JB
            q_ = d.get("q") or ""
            return self._send(200, _json({"ok": True, "answer": JB.answer(q_, lambda x: JV.answer(x, now_ist()))}))
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
            return self._send(200, _json({"ok": bool(c), "msg": msg, "id": (c or {}).get("id"), "call": c}))
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
    threading.Thread(target=behav_loop, daemon=True).start()
    try:
        from krt import predict as _PRD
        _PRD.LIVE["fn"] = lambda: (TICK["items"].get("NIFTY") or {}).get("ltp") if market_open(now_ist()) else None
    except Exception:
        traceback.print_exc()
    threading.Thread(target=paper_fast_loop, daemon=True).start()
    threading.Thread(target=bigvol_loop, daemon=True).start()
    threading.Thread(target=early_loop, daemon=True).start()
    threading.Thread(target=smc_loop, daemon=True).start()
    threading.Thread(target=keepalive_loop, daemon=True).start()
    threading.Thread(target=fable_loop, daemon=True).start()
    threading.Thread(target=light_loop, daemon=True).start()
    threading.Thread(target=riser_loop, daemon=True).start()
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
