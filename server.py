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


def _json(o):
    return json.dumps(o, default=str, ensure_ascii=False)


def do_scan(at=None):
    with LOCK:
        if STATE["scanning"]:
            return False
        STATE["scanning"] = True
    try:
        if not angel_configured():
            raise RuntimeError("Angel One connect ஆகவில்லை — demo data காட்டப்படாது")
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
        from krt.angel_api import Angel
        from krt.fullscan import run_full
        ANGEL = ANGEL or Angel()
        res = run_full(ANGEL, lambda m: STATE.update(progress=m))
        STATE.update(full=res, full_error=None)
    except Exception as e:
        traceback.print_exc()
        STATE["full_error"] = str(e)
    finally:
        STATE.update(full_last=str(now_ist()), full_running=False, progress="")
    return True


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
    t = now_ist()
    for i in range(1, 60 * 24 * 4):
        c = t + pd.Timedelta(minutes=i)
        if c.minute % 15 == 1 and market_open(c):
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

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, "ok", "text/plain")
        if not self._auth_ok():
            return self._deny()
        if self.path in ("/", "/index.html"):
            return self._send(200, (ROOT / "web" / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/status":
            cfg = load_settings().get("chartink", {})
            cl = saved_clauses()
            return self._send(200, _json({
                **{k: STATE[k] for k in ("scanning", "result", "error", "last_run", "full", "full_error",
                                         "full_running", "full_last", "progress")},
                "configured": angel_configured(), "hosted": HOSTED, "now": str(now_ist()),
                "market_open": market_open(now_ist()), "next_auto": next_auto(),
                "chartink": {"ce_url": cfg.get("ce_url"), "pe_url": cfg.get("pe_url"),
                             "ce_saved": bool(cl.get("ce")), "pe_saved": bool(cl.get("pe"))},
            }))
        self._send(404, _json({"error": "not found"}))

    def do_POST(self):
        if not self._auth_ok():
            return self._deny()
        try:
            d = self._body()
        except Exception:
            return self._send(400, _json({"ok": False, "msg": "தவறான request"}))

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


if __name__ == "__main__":
    threading.Thread(target=scheduler, daemon=True).start()
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
