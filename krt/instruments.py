"""Angel One instrument master — low memory (stream parse), ஒரு நாளுக்கு ஒருமுறை.
F&O stocks, equity tokens, stock/index option contracts (அருகிலுள்ள 2 expiry)."""
import datetime as dt, json, re
from pathlib import Path
import requests

MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
INDEX_SPOT = {"NIFTY": ("NSE", "99926000"), "BANKNIFTY": ("NSE", "99926009"),
              "FINNIFTY": ("NSE", "99926037"), "SENSEX": ("BSE", "99919000")}
INDEX_OPT_EXCH = {"NIFTY": "NFO", "BANKNIFTY": "NFO", "FINNIFTY": "NFO", "SENSEX": "BFO"}
_MEM = {"day": None, "data": None}


def ist_today() -> dt.date:
    return (dt.datetime.utcnow() + dt.timedelta(hours=5, minutes=30)).date()


def _build(cache_dir: Path) -> dict:
    import ijson
    raw = cache_dir / "scrip_master_raw.json"
    with requests.get(MASTER_URL, stream=True, timeout=180) as r:
        r.raise_for_status()
        with open(raw, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    today = ist_today()
    eq, opts, fno = {}, {}, set()
    with open(raw, "rb") as f:
        for row in ijson.items(f, "item"):
            seg, sym = row.get("exch_seg"), row.get("symbol", "")
            if seg == "NSE" and sym.endswith("-EQ"):
                eq[sym[:-3]] = row["token"]
                continue
            it = row.get("instrumenttype")
            if seg not in ("NFO", "BFO") or it not in ("OPTSTK", "OPTIDX"):
                continue
            name = (row.get("name") or "").upper()
            if it == "OPTIDX" and name not in INDEX_OPT_EXCH:
                continue
            if it == "OPTSTK":
                fno.add(name)
            try:
                exp = dt.datetime.strptime(row["expiry"], "%d%b%Y").date()
            except Exception:
                continue
            if not (0 <= (exp - today).days <= 75) or not sym[-2:] in ("CE", "PE"):
                continue
            opts.setdefault(name, []).append(
                [row["token"], sym, exp.isoformat(), float(row["strike"]) / 100, sym[-2:],
                 int(float(row.get("lotsize") or 0)), seg])
    raw.unlink(missing_ok=True)
    for name, rows in opts.items():  # அருகிலுள்ள 2 expiry மட்டும்
        exps = sorted({r[2] for r in rows})[:2]
        opts[name] = [r for r in rows if r[2] in exps]
    return {"eq": eq, "fno": sorted(fno), "opts": opts}


def load(cache_dir: str | Path) -> dict:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    day = ist_today().isoformat()
    if _MEM["day"] == day:
        return _MEM["data"]
    f = cache_dir / f"instruments_{day}.json"
    if f.exists():
        data = json.loads(f.read_text(encoding="utf-8"))
    else:
        data = _build(cache_dir)
        f.write_text(json.dumps(data), encoding="utf-8")
        for old in cache_dir.glob("instruments_*.json"):
            if old != f:
                old.unlink(missing_ok=True)
    _MEM.update(day=day, data=data)
    return data


def contracts(data: dict, name: str, min_days: int = 2):
    """→ (expiry, rows) — expiry-க்கு min_days-க்கு குறைவு இருந்தால் அடுத்த expiry."""
    rows = data["opts"].get(name, [])
    if not rows:
        return None, []
    today = ist_today()
    exps = sorted({r[2] for r in rows})
    pick = next((e for e in exps if (dt.date.fromisoformat(e) - today).days >= min_days), exps[-1])
    return pick, [r for r in rows if r[2] == pick]
