import pandas as pd


def same_time_rvol(intraday: pd.DataFrame, ts: pd.Timestamp, lookback_days: int = 10) -> float | None:
    """இன்று ts வரை cumulative volume ÷ கடந்த N நாட்களின் அதே நேர cumulative average."""
    day = ts.normalize()
    norm = intraday.index.normalize()
    today = intraday[(norm == day) & (intraday.index <= ts)]
    prev_days = sorted(set(norm[norm < day]))[-lookback_days:]
    hist = []
    for d in prev_days:
        dd = intraday[norm == d]
        hist.append(dd[dd.index.time <= ts.time()]["volume"].sum())
    avg = sum(hist) / len(hist) if hist else 0
    return round(today["volume"].sum() / avg, 2) if avg > 0 else None


def participation_tag(rvol: float | None, cfg: dict) -> str:
    if rvol is None:
        return "NO DATA"
    if rvol >= cfg["rvol_high_participation"]:
        return "HIGH PARTICIPATION"
    if rvol >= cfg["rvol_pass"]:
        return "VOLUME OK"
    return "LOW VOLUME"
