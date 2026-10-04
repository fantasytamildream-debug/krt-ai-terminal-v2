"""Setup 4-ம் section: Previous level break engine (CE: PDH/PWH/PMH, PE: PDL/PWL/PML).
Completed candles மட்டும். Gap-open breakout fresh என்று காட்டப்படாது."""
import pandas as pd

CE_LEVELS = ("PDH", "PWH", "PMH")
PE_LEVELS = ("PDL", "PWL", "PML")


def detect(intraday: pd.DataFrame, levels: dict, now: pd.Timestamp, tf_min: int,
           targets_pool: list[float], cfg: dict) -> list[dict]:
    day = now.normalize()
    # completed candles only: candle start + tf <= now
    candles = intraday[(intraday.index.normalize() == day) &
                       (intraday.index + pd.Timedelta(minutes=tf_min) <= now)]
    if len(candles) < 2:
        return []
    day_open = float(candles["open"].iloc[0])
    last_close = float(candles["close"].iloc[-1])
    out = []

    for direction, names in (("CE", CE_LEVELS), ("PE", PE_LEVELS)):
        for name in names:
            if name not in levels:
                continue
            lvl = levels[name]
            crossed = (candles["close"] > lvl) if direction == "CE" else (candles["close"] < lvl)
            if not crossed.any():
                continue
            gap = day_open > lvl if direction == "CE" else day_open < lvl
            first_idx = crossed.idxmax()
            break_candle = candles.loc[first_idx]
            ext = (last_close - lvl) / lvl * 100 * (1 if direction == "CE" else -1)

            # still beyond level on latest completed candle?
            holding = crossed.iloc[-1]
            if not holding:
                status = "INVALIDATED"
            elif gap:
                status = "WATCH"  # gap setup → opening range / retest confirmation தேவை
            elif ext > cfg["entry"]["max_extension_pct"]:
                status = "EXTENDED"
            else:
                status = "CONFIRMED"

            if direction == "CE":
                sl = float(min(break_candle["low"], lvl * 0.997))
                tgts = [t for t in targets_pool if t > last_close][:3]
            else:
                sl = float(max(break_candle["high"], lvl * 1.003))
                tgts = sorted([t for t in targets_pool if t < last_close], reverse=True)[:3]
            if len(tgts) < cfg["entry"]["min_targets"]:
                status = "INSUFFICIENT TARGETS" if status == "CONFIRMED" else status

            out.append({
                "direction": direction, "setup": "Previous Level Break",
                "level_name": name, "level": round(lvl, 2), "gap": bool(gap),
                "break_time": first_idx, "break_close": round(float(break_candle["close"]), 2),
                "price": round(last_close, 2), "extension_pct": round(ext, 2),
                "entry_zone": (round(lvl, 2), round(lvl * (1.003 if direction == "CE" else 0.997), 2)),
                "sl": round(sl, 2), "targets": [round(t, 2) for t in tgts], "status": status,
            })
    return out
