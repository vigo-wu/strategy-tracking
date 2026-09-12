# === hlband/factors/lib/chase.py ===
def _factor_eval_chase(ctx):
    market = (ctx or {}).get("market") or {}
    if not market.get("daily_ready"):
        return False, {}
    closes = market.get("closes")
    i = int(market.get("i") or 0)
    if closes is None or i < 1:
        return False, {}
    price = float(market.get("close") if market.get("close") is not None else closes[i])
    prev = float(closes[i - 1]) if closes[i - 1] else 0.0
    if prev <= 0:
        return False, {"prev": prev}
    chg = (price - prev) / prev
    return chg >= float(CHASE_MAX_PCT), {"chg": chg}
