"""Live news — Google News RSS (free). Headline keyword tag மட்டும் — news-ஐ வைத்து மட்டும் call இல்லை;
setup உள்ள stock-க்கு news ஆதரவு / எதிர் என்று காட்டும்."""
import re, time, urllib.parse
import xml.etree.ElementTree as ET
import requests

POS = ["surge", "jump", "rall", "gain", "upgrade", "beats", "record high", "order win", "bags", "wins order",
       "profit rises", "profit jumps", "buy rating", "target raised", "soars", "climbs", "strong q", "approval"]
NEG = ["fall", "slump", "plunge", "downgrade", "miss", "loss", "probe", "penalty", "fraud", "sell rating",
       "cut target", "resign", "tumble", "crash", "slides", "weak q", "raid", "default", "ban"]
CACHE = {"t": 0, "items": [], "err": None}


def _fetch(q):
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=en-IN&gl=IN&ceid=IN:en"
    r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for it in root.iter("item"):
        src = it.find("source")
        out.append({"title": (it.findtext("title") or "").strip(), "link": it.findtext("link"),
                    "time": it.findtext("pubDate"), "source": src.text if src is not None else ""})
    return out


def tag(title):
    t = title.lower()
    p = sum(w in t for w in POS)
    n = sum(w in t for w in NEG)
    return "POSITIVE" if p > n else "NEGATIVE" if n > p else "NEUTRAL"


def refresh(symbols, every=600):
    if time.time() - CACHE["t"] < every and CACHE["items"]:
        return CACHE
    items, seen = [], set()
    queries = [("MARKET", "NSE Nifty stock market today")] + [(s, f"{s} share NSE") for s in symbols[:10]]
    err = None
    for sym, q in queries:
        try:
            for x in _fetch(q)[:6]:
                if x["title"] in seen:
                    continue
                seen.add(x["title"])
                x["symbol"] = sym
                x["tag"] = tag(x["title"])
                items.append(x)
        except Exception as e:
            err = str(e)
        time.sleep(0.5)
    CACHE.update(t=time.time(), items=items, err=err)
    return CACHE
