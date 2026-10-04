"""Demo-க்கு random OHLCV data உருவாக்கும் (real data இல்லை)."""
import numpy as np, pandas as pd
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
cfg = yaml.safe_load(open(ROOT / "config/settings.yaml", encoding="utf-8"))
out = ROOT / "data/sample"; out.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(7)
days = pd.bdate_range(end="2026-10-01", periods=130)

for sym in cfg["universe"] + [cfg["index_symbol"]]:
    price = rng.uniform(300, 3000)
    daily, intra = [], []
    for d in days:
        bars, o = [], price
        for k in range(25):  # 09:15 → 15:15, 15m candles
            t = d + pd.Timedelta(hours=9, minutes=15 + 15 * k)
            c = o * (1 + rng.normal(0.0002, 0.003))
            h, l = max(o, c) * (1 + abs(rng.normal(0, .001))), min(o, c) * (1 - abs(rng.normal(0, .001)))
            v = int(rng.integers(20_000, 120_000) * (2 if k < 2 or k > 22 else 1))
            bars.append([t, o, h, l, c, v]); o = c
        b = pd.DataFrame(bars, columns=["time", "open", "high", "low", "close", "volume"])
        intra.append(b)
        daily.append([d, b.open.iloc[0], b.high.max(), b.low.min(), b.close.iloc[-1], b.volume.sum()])
        price = o * (1 + rng.normal(0, .004))
    pd.DataFrame(daily, columns=["date", "open", "high", "low", "close", "volume"]).set_index("date") \
        .to_csv(out / f"{sym}_daily.csv")
    pd.concat(intra).set_index("time").to_csv(out / f"{sym}_15m.csv")
print("Sample data ready →", out)
