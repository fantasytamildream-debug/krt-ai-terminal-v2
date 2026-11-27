"""🤖 v152 MODULE AUTOPILOT — keeps the proven-but-strict modules alive every day.

When a module finds NO setup for whole trading days, its own entry rules are loosened one step a day (max 3 steps).
If calls taken on loosened days start losing (2 of the last 3), it steps back one level by itself. Nothing is invented:
the module still needs its own setup — the autopilot only widens the bar a little, and every loosened call is marked."""
import pandas as pd

TARGETS = {
    "GU": {"name": "Gamma Unwind Classic", "match": lambda s: s == "Gamma Unwind Classic",
           "steps": ["normal rules", "OI unwind need −1 % · quiet base +0.25 ATR · LITE −0.5 %", "OI unwind need −2 % · base +0.5 ATR · LITE −1 %",
                     "OI unwind need −3 % (floor) · base +0.75 ATR · LITE −1.5 %"]},
    "SILVER": {"name": "V4 ⚡ ICT Silver Bullet", "match": lambda s: "ICT Silver Bullet" in s and "🛢" not in s,
               "steps": ["normal rules (10:00–11:00 · 13:30–14:30, sweep + MSS + displacement + FVG retest)",
                         "windows widened 09:45–11:30 · 13:00–15:00", "+ displacement candle not required", "+ FVG retest not required (sweep + MSS + FVG)"]},
    "INDEXJP": {"name": "🔮 Index Jackpot", "match": lambda s: "Index Jackpot" in s,
                "steps": ["prediction ≥ 75 %", "prediction ≥ 71 %", "prediction ≥ 67 %", "prediction ≥ 63 % (floor)"]},
}
AP = {"lvl": {k: 0 for k in TARGETS}, "why": {}, "time": None, "hist": {}, "on": True}


def level(k):
    return int(AP["lvl"].get(k, 0)) if AP.get("on") else 0


def _tdays(a, b):
    """trading days strictly between dates a and b (weekdays)."""
    if not a:
        return 9
    return max(0, len(pd.bdate_range(pd.Timestamp(a) + pd.Timedelta(days=1), pd.Timestamp(b) - pd.Timedelta(days=1))))


def update(calls, today, store_hist=None):
    """calls: iterable of call dicts. Re-computes every level; returns the state for the UI."""
    if store_hist is not None:
        AP["hist"] = store_hist
    H = AP["hist"]
    for k, T in TARGETS.items():
        rows = [c for c in calls if T["match"](str(c.get("source") or "")) and c.get("kind") != "PICK"]
        dates = sorted({c["date"] for c in rows})
        last = dates[-1] if dates else None
        gap = _tdays(last, today) if last != today else 0
        lvl = min(3, gap)
        if last == today:
            lvl = int((H.get(today) or {}).get(k, AP["lvl"].get(k, 0)))       # a call came today → hold today's level
        relaxed = sorted([c for c in rows if (H.get(c["date"]) or {}).get(k, 0) > 0 and c.get("pnl_lot") is not None
                          and c.get("status") not in ("OPEN", "T1 HIT", "T2 HIT")], key=lambda c: (c["date"], c.get("time") or ""))[-3:]
        note = None
        if len(relaxed) >= 3 and sum(1 for c in relaxed if c["pnl_lot"] < 0) >= 2:
            lvl = max(0, lvl - 1)
            note = "2 of the last 3 loosened calls lost → stepped back one level"
        AP["lvl"][k] = lvl
        H.setdefault(today, {})[k] = lvl
        AP["why"][k] = {"last_call": last, "days_without": gap, "level": lvl, "rule": T["steps"][lvl], "note": note, "name": T["name"],
                        "relaxed_record": f"{sum(1 for c in relaxed if c['pnl_lot'] > 0)}/{len(relaxed)} loosened calls won" if relaxed else None}
    for d in sorted(H)[:-30]:
        H.pop(d, None)
    AP["time"] = pd.Timestamp.now().strftime("%H:%M")
    return state()


def state():
    return {"on": AP["on"], "time": AP["time"], "modules": AP["why"]}
