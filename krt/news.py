"""Live news — Moneycontrol, Economic Times, Business Standard RSS + Google News (setup stocks).
புதியது முதலில், கடந்த 24 மணி நேரம் மட்டும். F&O stock பெயர் headline-ல் இருந்தால் tag.
Headline வார்த்தை tag மட்டும் — news-ஐ வைத்து மட்டும் call இல்லை."""
import re, time, urllib.parse
import datetime as dt
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
import requests

FEEDS = [
    ("Moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml"),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/marketreports.xml"),
    ("Moneycontrol", "https://www.moneycontrol.com/rss/buzzingstocks.xml"),
    ("Economic Times", "https://economictimes.indiatimes.com/markets/stocks/rss.cms"),
    ("Business Standard", "https://www.business-standard.com/rss/markets-106.rss"),
]
ALIAS = {"HDFCBANK": ["HDFC BANK"], "ICICIBANK": ["ICICI BANK"], "SBIN": ["SBI", "STATE BANK"], "INFY": ["INFOSYS"],
         "RELIANCE": ["RELIANCE IND", "RIL"], "TATASTEEL": ["TATA STEEL"], "TATAPOWER": ["TATA POWER"],
         "BAJFINANCE": ["BAJAJ FINANCE"], "BAJAJFINSV": ["BAJAJ FINSERV"], "KOTAKBANK": ["KOTAK"],
         "AXISBANK": ["AXIS BANK"], "HINDUNILVR": ["HUL", "HINDUSTAN UNILEVER"], "BHARTIARTL": ["AIRTEL"],
         "MARUTI": ["MARUTI"], "M&M": ["MAHINDRA & MAHINDRA", "M&M"], "LT": ["L&T", "LARSEN"],
         "SUNPHARMA": ["SUN PHARMA"], "ASIANPAINT": ["ASIAN PAINTS"], "ULTRACEMCO": ["ULTRATECH"],
         "ADANIENT": ["ADANI ENTERPRISES"], "ADANIPORTS": ["ADANI PORTS"], "ADANIPOWER": ["ADANI POWER"],
         "HEROMOTOCO": ["HERO MOTOCORP"], "EICHERMOT": ["EICHER"], "BAJAJ-AUTO": ["BAJAJ AUTO"],
         "TECHM": ["TECH MAHINDRA"], "HCLTECH": ["HCL TECH"], "POWERGRID": ["POWER GRID"],
         "COALINDIA": ["COAL INDIA"], "INDUSINDBK": ["INDUSIND"], "DRREDDY": ["DR REDDY"], "DIVISLAB": ["DIVI'S", "DIVIS"],
         "APOLLOHOSP": ["APOLLO HOSPITALS"], "TATACONSUM": ["TATA CONSUMER"], "JSWSTEEL": ["JSW STEEL"],
         "HINDALCO": ["HINDALCO"], "BPCL": ["BPCL"], "IOC": ["INDIAN OIL"], "ONGC": ["ONGC"], "NTPC": ["NTPC"],
         "PAYTM": ["PAYTM", "ONE 97"], "NAUKRI": ["INFO EDGE", "NAUKRI"], "ZOMATO": ["ZOMATO", "ETERNAL"],
         "DMART": ["DMART", "AVENUE SUPERMARTS"], "COLPAL": ["COLGATE"], "ABCAPITAL": ["ADITYA BIRLA CAPITAL"],
         "PETRONET": ["PETRONET"], "HINDPETRO": ["HPCL", "HINDUSTAN PETROLEUM"], "UJJIVANSFB": ["UJJIVAN"]}
POS = ["surge", "jump", "rall", "gain", "upgrade", "beats", "record high", "order win", "bags", "wins order", "rises",
       "profit up", "buy rating", "target raised", "soars", "climbs", "strong q", "approval", "outperform", "top gainer"]
NEG = ["fall", "slump", "plunge", "downgrade", "miss", "loss", "probe", "penalty", "fraud", "sell rating", "declin",
       "cut target", "resign", "tumble", "crash", "slides", "weak q", "raid", "default", "ban", "top loser", "selloff"]
CACHE = {"feeds_t": 0, "google_t": 0, "feed_items": [], "google_items": [], "items": [], "err": None}
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _parse(content, source):
    root = ET.fromstring(content)
    out = []
    for it in root.iter("item"):
        src = it.find("source")
        try:
            t = parsedate_to_datetime(it.findtext("pubDate")).astimezone(IST)
        except Exception:
            t = None
        out.append({"title": (it.findtext("title") or "").strip(), "link": it.findtext("link"),
                    "dt": t, "source": src.text if src is not None else source})
    return out


def _get(url, source):
    r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return _parse(r.content, source)


def tag(title):
    t = title.lower()
    p, n = sum(w in t for w in POS), sum(w in t for w in NEG)
    return "POSITIVE" if p > n else "NEGATIVE" if n > p else "NEUTRAL"


def match(title, fno):
    T = " " + re.sub(r"[^A-Z0-9&' ]", " ", title.upper()) + " "
    hits = []
    for s in fno:
        keys = ALIAS.get(s, []) + ([s] if len(s) >= 3 else [])
        if any(f" {k} " in T for k in keys):
            hits.append(s)
    return hits[:3]


def refresh(symbols, fno, feed_every=180, google_every=600):
    now = time.time()
    err = None
    if now - CACHE["feeds_t"] >= feed_every:
        items = []
        for src, url in FEEDS:
            try:
                items += _get(url, src)
            except Exception as e:
                err = f"{src}: {e}"
        CACHE.update(feed_items=items, feeds_t=now)
    if now - CACHE["google_t"] >= google_every:
        items = []
        for s in symbols[:10]:
            try:
                q = urllib.parse.quote(f"{s} share NSE")
                for x in _get(f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en", "Google News")[:5]:
                    x["force"] = s
                    items.append(x)
            except Exception as e:
                err = f"Google: {e}"
            time.sleep(0.3)
        CACHE.update(google_items=items, google_t=now)
    cutoff = dt.datetime.now(IST) - dt.timedelta(hours=24)
    seen, out = set(), []
    for x in CACHE["feed_items"] + CACHE["google_items"]:
        k = x["title"][:80]
        if k in seen or (x["dt"] and x["dt"] < cutoff):
            continue
        seen.add(k)
        syms = match(x["title"], fno)
        if x.get("force") and x["force"] not in syms:
            syms.insert(0, x["force"])
        out.append({"title": x["title"], "link": x["link"], "source": x["source"],
                    "time": x["dt"].strftime("%d-%m %H:%M") if x["dt"] else "", "ts": x["dt"].timestamp() if x["dt"] else 0,
                    "symbols": syms, "symbol": syms[0] if syms else "MARKET", "tag": tag(x["title"])})
    out.sort(key=lambda x: -x["ts"])
    CACHE.update(items=out[:120], err=err)
    return CACHE
