"""Telegram alert (optional). Render Environment-ல் TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID இருந்தால் மட்டும்."""
import os, requests

SENT = set()


def enabled():
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def send(text, key=None):
    if key and key in SENT:
        return False
    if not enabled():
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/sendMessage",
                          json={"chat_id": os.getenv("TELEGRAM_CHAT_ID"), "text": text}, timeout=10)
        if r.ok and key:
            SENT.add(key)
        return r.ok
    except Exception:
        return False
