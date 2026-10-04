def planned_risk(entry: float, sl: float, lot_size: int, charges: float) -> float:
    return round((entry - sl) * lot_size + charges, 2)


def risk_check(entry, sl, lot_size, cfg: dict) -> tuple[bool, float, str]:
    r = planned_risk(entry, sl, lot_size, cfg["charges_slippage"])
    cap = cfg["max_risk_per_trade"]
    if cfg.get("account_risk_limit"):
        cap = min(cap, cfg["account_risk_limit"])
    if r > cap:
        return False, r, "SKIP — RISK ABOVE LIMIT"
    return True, r, "RISK OK"
