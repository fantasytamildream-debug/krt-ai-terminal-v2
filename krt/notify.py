"""📲 PHONE NOTIFICATIONS — Web Push (browser / tab மூடியிருந்தாலும் phone-ல் notification வரும்) + Telegram / WhatsApp.

• Phone-ல் site-ஐ ஒருமுறை திறந்து "📲 Phone notifications ON" அழுத்தினா போதும் (Android Chrome / Edge; iPhone = Home Screen-ல் add பண்ணின பிறகு).
• VAPID keys தானா உருவாகி STORE-ல் save ஆகும் (Render restart-லும் அதே keys).
• Server தூங்கிட்டா (Render free plan) push போகாது → server.py keepalive_loop அதை தடுக்கும்.
"""
import base64
import json
import threading
import time

LK = threading.Lock()
STATE = {"sent": 0, "fail": 0, "last": None, "err": None}


def _store():
    from .calls import CALLS_LOCK, STORE
    return STORE, CALLS_LOCK


def vapid():
    """(Vapid02, public_key_b64url) — STORE-ல் இல்லைன்னா புதுசா உருவாக்கி save."""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid02
    STORE, CL = _store()
    with CL:
        d = STORE.load()
        k = d.get("vapid")
        if not k:
            v = Vapid02()
            v.generate_keys()
            pem = v.private_pem().decode()
            pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
            k = d["vapid"] = {"pem": pem, "pub": base64.urlsafe_b64encode(pub).decode().rstrip("=")}
            STORE.dirty = True
            STORE.save(force=True)
    return Vapid02.from_pem(k["pem"].encode()), k["pub"]


def subscribe(sub, ua=""):
    if not isinstance(sub, dict) or not sub.get("endpoint") or not (sub.get("keys") or {}).get("p256dh"):
        raise ValueError("subscription தவறு")
    STORE, CL = _store()
    with CL:
        d = STORE.load()
        S = d.setdefault("push_subs", {})
        S[sub["endpoint"]] = {"sub": sub, "ua": ua[:120], "t": time.strftime("%Y-%m-%d %H:%M")}
        STORE.dirty = True
        STORE.save(force=True)
    return len(S)


def subs():
    STORE, _ = _store()
    return list((STORE.load().get("push_subs") or {}).values())


def push(title, body, tag=None, url="/", urgent=False, wait=False):
    """எல்லா subscribed phones-க்கும் Web Push. 404/410 = phone unsubscribe → நீக்கும்."""
    L = subs()
    if not L:
        return 0

    def go():
        from pywebpush import WebPushException, webpush
        try:
            V, _ = vapid()
        except Exception as e:
            STATE["err"] = f"vapid: {e}"[:150]
            return
        dead, ok = [], 0
        data = json.dumps({"title": title[:120], "body": body[:400], "tag": tag or title[:40], "url": url, "urgent": bool(urgent)})
        for s in L:
            try:
                webpush(s["sub"], data, vapid_private_key=V, vapid_claims={"sub": "mailto:krt-alerts@example.com"}, ttl=900,
                        headers={"Urgency": "high" if urgent else "normal"}, timeout=10)
                ok += 1
            except WebPushException as e:
                code = getattr(getattr(e, "response", None), "status_code", None)
                if code in (404, 410):
                    dead.append(s["sub"]["endpoint"])
                STATE["fail"] += 1
                STATE["err"] = f"{code}: {str(e)[:120]}"
            except Exception as e:
                STATE["fail"] += 1
                STATE["err"] = str(e)[:150]
        STATE["sent"] += ok
        STATE["last"] = time.strftime("%H:%M:%S")
        if dead:
            STORE, CL = _store()
            with CL:
                d = STORE.load()
                for ep in dead:
                    (d.get("push_subs") or {}).pop(ep, None)
                STORE.dirty = True
    if wait:
        go()
    else:
        threading.Thread(target=go, daemon=True).start()
    return len(L)


def both(text, key=None, urgent=False):
    """Telegram / WhatsApp (telegram.send) + Web Push ஒன்றாக — exit / radar alerts-க்கு."""
    from .telegram import send
    try:
        send(text, key)
    except Exception:
        pass
    lines = str(text).split("\n")
    push(lines[0], "\n".join(lines[1:]) or lines[0], tag=key, urgent=urgent)
    return True


def _name(c):
    return f"{c['symbol']} {c.get('strike')} {c.get('side')}"


def notify_tick(now):
    """இன்றைய ஒவ்வொரு புது call (எல்லா modules · stock / index / MCX) + Mannan setup → ஒருமுறை push.
    முதல் தடவை பார்க்கும்போது 5 நிமிடத்துக்கு மேல் பழைய call-க்கு push இல்லை (deploy spam தவிர்க்க)."""
    STORE, CL = _store()
    day = str(now.date())
    out = []
    with CL:
        d = STORE.load()
        for c in (d.get("calls") or {}).values():
            if c.get("date") != day or c.get("shadow") or c.get("_np"):
                continue
            c["_np"] = now.strftime("%H:%M")
            STORE.dirty = True
            try:
                age = (now - __import__("pandas").Timestamp(c.get("signal_time") or f"{day} {c.get('time')}")).total_seconds()
            except Exception:
                age = 0
            if age > 300 or c.get("status") not in ("OPEN", "T1 HIT"):
                continue
            out.append(("call", c))
        for x in (d.get("mannan_setups") or {}).values():
            if x.get("date") != day or x.get("_np"):
                continue
            x["_np"] = now.strftime("%H:%M")
            STORE.dirty = True
            if not x.get("call") and x.get("strike") and x.get("status") == "OPEN":
                out.append(("setup", x))
    for kind, c in out[:8]:
        pk = c.get("pink") if kind == "call" else None
        if kind == "call":
            title = (("🩷🩷 DARK PINK" if (pk or {}).get("tier") == "dark" else "🩷 PINK") + " · " if pk else "🔔 ") + f"BUY {_name(c)}"
            body = (f"Entry ₹{c.get('entry')} · SL ₹{c.get('sl')} · T1 ₹{(c.get('targets') or [None])[0]}\n"
                    f"{c.get('source_label') or c.get('source') or c.get('kind')} · {c.get('time')}" + (f" · win {pk['win']}%" if pk else "")
                    + (f"\n👉 {c['guide']}" if c.get("guide") else ""))
        else:
            title = f"📋 Mannan setup · {_name(c)}"
            body = f"Entry ₹{c.get('entry')} · SL ₹{c.get('sl')} · T1 ₹{(c.get('targets') or [None])[0]}\n{c.get('reason') or ''}"
        push(title, body, tag=f"{kind}|{c.get('id')}", urgent=bool(pk))
    return len(out)
