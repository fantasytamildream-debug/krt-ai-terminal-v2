import pandas as pd
from .levels import completed_levels, swing_levels
from .volume import same_time_rvol, participation_tag
from .market import classify, relative_strength
from .scoring import score
from .setups import level_break
from .signals import Signal

PRIORITY = {"CONFIRMED": 0, "WATCH": 1, "INSUFFICIENT TARGETS": 2, "EXTENDED": 3}


def scan(provider, cfg: dict, now: pd.Timestamp, watch: dict | None = None) -> dict:
    """watch: {symbol: {"CE","PE"}}. None → config universe, இரண்டு direction-ும்."""
    if watch is None:
        watch = {s: {"CE", "PE"} for s in cfg["universe"]}
    idx_daily = provider.daily(cfg["index_symbol"])
    market = classify(idx_daily, now)
    rows, signals = [], []
    for sym, allowed in watch.items():
        if provider.is_stale(sym, now):
            rows.append({"symbol": sym, "status": "STALE / NO DATA — BLOCKED"})
            continue
        daily, intra = provider.daily(sym), provider.intraday(sym)
        lv = completed_levels(daily, now)
        pool = sorted({round(x, 2) for x in swing_levels(daily, now) + list(lv.values())})
        rvol = same_time_rvol(intra, now, cfg["volume"]["lookback_days"])
        rs = relative_strength(daily, idx_daily, now)
        vol_ok = rvol is not None and rvol >= cfg["volume"]["rvol_pass"]

        by_dir = {}
        for c in level_break.detect(intra, lv, now, cfg["timeframe_minutes"], pool, cfg):
            if c["status"] == "INVALIDATED" or c["direction"] not in allowed:
                continue  # failed CE ≠ auto PE
            if c["status"] == "CONFIRMED" and not vol_ok:
                c["status"] = "WATCH"
            by_dir.setdefault(c["direction"], []).append(c)

        for direction, cs in by_dir.items():
            cs.sort(key=lambda c: (PRIORITY.get(c["status"], 9), abs(c["extension_pct"])))
            c = dict(cs[0])
            names = [x["level_name"] for x in cs]
            c["level_name"] = "+".join(names)
            tags = ["LEVEL CONFLUENCE"] if len(names) > 1 else []
            tags.append(participation_tag(rvol, cfg["volume"]))
            sc = score(c, rvol, rs, market, cfg["score_weights"])
            rows.append({"symbol": sym, **c, "rvol": rvol, "rs": rs, "score": sc, "tags": tags})
            if c["status"] == "CONFIRMED":
                signals.append(Signal(sym, direction, c["setup"], c["level_name"],
                                      c["entry_zone"], c["sl"], tuple(c["targets"]),
                                      str(c["break_time"]), str(now), c["price"], sc,
                                      tuple([f"{c['level_name']} break", *tags])))

    ranked = sorted([r for r in rows if "score" in r], key=lambda r: -r["score"])
    return {
        "market": market, "time": now,
        "ce": [r for r in ranked if r["direction"] == "CE"][:5],
        "pe": [r for r in ranked if r["direction"] == "PE"][:5],
        "blocked": [r for r in rows if "score" not in r],
        "signals": signals,
    }
