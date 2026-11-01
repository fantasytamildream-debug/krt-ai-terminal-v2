"""Alerts: Telegram (optional) + 📱 WhatsApp (CallMeBot — free, personal number) — எல்லா call message-ம் இரண்டுக்கும் போகும்.
Telegram: env TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
WhatsApp: env WHATSAPP_PHONE (+91XXXXXXXXXX), WHATSAPP_APIKEY (CallMeBot) — அல்லது Settings-ல் save (data/whatsapp.json).
"""
import json, os, queue, threading, time
from pathlib import Path
from urllib.parse import quote

import requests

SENT = set()
WA_FILE = Path(__file__).resolve().parent.parent / "data" / "whatsapp.json"
WA = {"q": queue.Queue(), "started": False, "sent": 0, "fail": 0, "last_err": None, "last_ok": None}


def wa_cfg():
    ph, key = os.getenv("WHATSAPP_PHONE"), os.getenv("WHATSAPP_APIKEY")
    if not (ph and key) and WA_FILE.exists():
        try:
            d = json.loads(WA_FILE.read_text(encoding="utf-8"))
            ph, key = d.get("phone"), d.get("apikey")
        except Exception:
            pass
    return (ph or "").strip(), (key or "").strip()


def wa_save(phone, apikey):
    WA_FILE.parent.mkdir(parents=True, exist_ok=True)
    WA_FILE.write_text(json.dumps({"phone": phone.strip(), "apikey": apikey.strip()}), encoding="utf-8")


def wa_enabled():
    ph, key = wa_cfg()
    return bool(ph and key)


def _wa_worker():
    while True:
        text = WA["q"].get()
        ph, key = wa_cfg()
        if not (ph and key):
            continue
        for attempt in range(2):
            try:
                r = requests.get(f"https://api.callmebot.com/whatsapp.php?phone={quote(ph)}&text={quote(text[:1500])}&apikey={quote(key)}", timeout=20)
                if r.ok and "error" not in r.text.lower()[:200]:
                    WA["sent"] += 1
                    WA["last_ok"] = time.strftime("%H:%M:%S")
                    break
                WA["last_err"] = r.text[:150]
            except Exception as e:
                WA["last_err"] = str(e)[:150]
            time.sleep(6)
        else:
            WA["fail"] += 1
        time.sleep(4)          # CallMeBot rate-limit: messages இடையே இடைவெளி


def wa_send(text):
    if not wa_enabled():
        return False
    if not WA["started"]:
        WA["started"] = True
        threading.Thread(target=_wa_worker, daemon=True).start()
    WA["q"].put(text)
    return True


def enabled():
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")) or wa_enabled()


def send(text, key=None):
    if key and key in SENT:
        return False
    ok = False
    if wa_enabled():
        ok = wa_send("🔔 KRT\n" + text) or ok
    if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        try:
            r = requests.post(f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/sendMessage",
                              json={"chat_id": os.getenv("TELEGRAM_CHAT_ID"), "text": text}, timeout=10)
            ok = r.ok or ok
        except Exception:
            pass
    if ok and key:
        SENT.add(key)
    return ok


def status():
    ph, _ = wa_cfg()
    return {"whatsapp": wa_enabled(), "phone": (ph[:3] + "•••••" + ph[-3:]) if len(ph) > 6 else ph, "sent": WA["sent"], "fail": WA["fail"],
            "last_ok": WA["last_ok"], "last_err": WA["last_err"], "queue": WA["q"].qsize(),
            "telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))}
