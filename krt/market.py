import pandas as pd


def classify(index_daily: pd.DataFrame, as_of: pd.Timestamp) -> str:
    d = index_daily[index_daily.index.normalize() < as_of.normalize()]
    if len(d) < 50:
        return "UNCLEAR — WAIT"
    c = d["close"]
    e20, e50 = c.ewm(span=20).mean(), c.ewm(span=50).mean()
    slope = e20.iloc[-1] - e20.iloc[-5]
    if c.iloc[-1] > e20.iloc[-1] > e50.iloc[-1] and slope > 0:
        return "TRENDING UP"
    if c.iloc[-1] < e20.iloc[-1] < e50.iloc[-1] and slope < 0:
        return "TRENDING DOWN"
    rng = (d["high"].tail(10).max() - d["low"].tail(10).min()) / c.iloc[-1] * 100
    return "RANGE-BOUND" if rng < 4 else "UNCLEAR — WAIT"


def relative_strength(stock_daily, index_daily, as_of, days: int = 20) -> float | None:
    s = stock_daily[stock_daily.index.normalize() < as_of.normalize()]["close"]
    i = index_daily[index_daily.index.normalize() < as_of.normalize()]["close"]
    if len(s) <= days or len(i) <= days:
        return None
    return round((s.iloc[-1] / s.iloc[-days - 1] - i.iloc[-1] / i.iloc[-days - 1]) * 100, 2)
