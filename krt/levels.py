"""Previous Day / Week / Month levels — completed periods மட்டும்."""
import pandas as pd


def completed_levels(daily: pd.DataFrame, as_of: pd.Timestamp) -> dict:
    if daily is None or daily.empty or not isinstance(daily.index, pd.DatetimeIndex):
        return {}
    d = daily[daily.index.normalize() < as_of.normalize()]
    if d.empty:
        return {}
    out = {"PDH": float(d["high"].iloc[-1]), "PDL": float(d["low"].iloc[-1])}
    for tag, freq in (("W", "W"), ("M", "M")):
        per = d.index.to_period(freq)
        done = d[per < as_of.to_period(freq)]
        if done.empty:
            continue
        last = done.index.to_period(freq)[-1]
        blk = done[done.index.to_period(freq) == last]
        out[f"P{tag}H"] = float(blk["high"].max())
        out[f"P{tag}L"] = float(blk["low"].min())
    return out


def confluence(levels: dict, price: float, pct: float = 0.3) -> list[str]:
    """Price-க்கு அருகில் உள்ள multiple levels → LEVEL CONFLUENCE."""
    return [k for k, v in levels.items() if abs(v - price) / price * 100 <= pct]


def swing_levels(daily: pd.DataFrame, as_of: pd.Timestamp, window: int = 3, lookback: int = 120) -> list[float]:
    if daily is None or daily.empty or not isinstance(daily.index, pd.DatetimeIndex):
        return []
    """Target-க்கு visible swing highs/lows (completed days only)."""
    d = daily[daily.index.normalize() < as_of.normalize()].tail(lookback)
    w = 2 * window + 1
    hmax = d["high"].rolling(w, center=True).max()
    lmin = d["low"].rolling(w, center=True).min()
    lv = d["high"][d["high"] == hmax].tolist() + d["low"][d["low"] == lmin].tolist()
    return sorted(set(round(x, 2) for x in lv))
