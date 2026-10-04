"""Chartink public scanner → stock list.
Chartink-க்கு official API இல்லை. இது unofficial method; site மாறினால் break ஆகலாம்.
15 நிமிடத்துக்கு ஒருமுறை மட்டும் call செய்யவும்."""
import html, json, re
from pathlib import Path
import requests

CLAUSE_FILE = Path(__file__).resolve().parent.parent / "config" / "chartink_clauses.json"


def saved_clauses() -> dict:
    """File-ல் save ஆனது + Render env vars (CHARTINK_CE_CLAUSE / CHARTINK_PE_CLAUSE)."""
    import os
    try:
        data = json.loads(CLAUSE_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    for side in ("ce", "pe"):
        v = os.getenv(f"CHARTINK_{side.upper()}_CLAUSE", "").strip()
        if v and side not in data:
            data[side] = v
    return data

BASE = "https://chartink.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


class ChartinkError(Exception):
    pass


def _csrf(page: str) -> str | None:
    for pat in (r'name=["\']csrf-token["\'][^>]*content=["\']([^"\']+)',
                r'content=["\']([^"\']+)["\'][^>]*name=["\']csrf-token'):
        m = re.search(pat, page)
        if m:
            return m.group(1)
    return None


def _extract_clause(page: str) -> str | None:
    text = html.unescape(page)
    cands = []
    for m in re.finditer(r'"((?:\\.|[^"\\]){15,})"', text):
        s = m.group(1)
        try:
            s = json.loads(f'"{s}"')
        except Exception:
            pass
        cands.append(s)
    cands += [m.group(1) for m in re.finditer(r"'((?:\\.|[^'\\]){15,})'", text)]
    cands += [m.group(1) for m in re.finditer(r"<textarea[^>]*>(.*?)</textarea>", text, re.S)]
    good = [c.strip() for c in cands
            if c.strip().startswith("(") and "{" in c
            and any(k in c for k in ("latest", "daily", "close", "min", "volume"))]
    return max(good, key=len) if good else None


def fetch(url: str, clause: str | None = None, timeout: int = 25) -> list[dict]:
    s = requests.Session()
    r = s.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    token = _csrf(r.text)
    if not token:
        raise ChartinkError("Chartink page-ல் csrf token கிடைக்கவில்லை")
    clause = clause or _extract_clause(r.text)
    if not clause:
        raise ChartinkError("Scan clause கிடைக்கவில்லை. Scan public-ஆ இருக்கா check பண்ணுங்க, "
                            "அல்லது config/settings.yaml-ல் clause paste பண்ணுங்க")
    p = s.post(f"{BASE}/screener/process", data={"scan_clause": clause},
               headers={**UA, "x-csrf-token": token, "x-requested-with": "XMLHttpRequest",
                        "referer": url}, timeout=timeout)
    p.raise_for_status()
    try:
        js = p.json()
    except ValueError:
        raise ChartinkError("Chartink result JSON இல்லை (block / login தேவைப்படலாம்)")
    if js.get("scan_error"):
        raise ChartinkError(f"Chartink scan error: {js['scan_error']}")
    return js.get("data") or []


def symbols(rows: list[dict]) -> list[str]:
    seen, out = set(), []
    for r in rows:
        sym = (r.get("nsecode") or "").strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def build_watchlist(cfg: dict) -> tuple[dict, list[str]]:
    """→ ({symbol: {"CE"} / {"PE"} / both}, messages)"""
    ck = cfg.get("chartink") or {}
    saved = saved_clauses()
    watch, msgs = {}, []
    for side in ("ce", "pe"):
        url = ck.get(f"{side}_url")
        if not url:
            continue
        try:
            clause = saved.get(side) or ck.get(f"{side}_clause") or None
            syms = symbols(fetch(url, clause))
            syms = syms[: ck.get("max_per_side", 25)]
            src = "saved clause" if clause else "auto"
            msgs.append(f"Chartink {side.upper()} ({src}): {len(syms)} stocks  {', '.join(syms[:12])}{' ...' if len(syms) > 12 else ''}")
            for sym in syms:
                watch.setdefault(sym, set()).add(side.upper())
        except Exception as e:
            msgs.append(f"⚠ Chartink {side.upper()} failed: {e}")
    return watch, msgs
