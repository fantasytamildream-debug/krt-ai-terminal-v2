"""Score = ranking மட்டும். Score 90 ≠ 90% win probability."""


def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def score(c: dict, rvol, rs, market: str, w: dict, liquidity: float = 0.5) -> int:
    setup_q = 1.0 if c["status"] == "CONFIRMED" else 0.5
    rs_q = 0.0 if rs is None else _clip((rs if c["direction"] == "CE" else -rs) / 5)
    vol_q = 0.0 if rvol is None else _clip((rvol - 1) / 1.5)
    align = (market == "TRENDING UP" and c["direction"] == "CE") or \
            (market == "TRENDING DOWN" and c["direction"] == "PE")
    align_q = 1.0 if align else (0.4 if market == "RANGE-BOUND" else 0.0)
    risk = abs(c["price"] - c["sl"]) or 1e-9
    rr = abs(c["targets"][0] - c["price"]) / risk if c["targets"] else 0
    rr_q = _clip(rr / 2)
    total = (w["setup_structure"] * setup_q + w["relative_strength"] * rs_q +
             w["volume"] * vol_q + w["alignment"] * align_q +
             w["room_reward_risk"] * rr_q + w["liquidity"] * liquidity)
    return round(total)
