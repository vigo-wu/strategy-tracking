# === hlband/factors/lib/stop_loss.py ===
def _factor_eval_stop_loss(ctx):
    market = (ctx or {}).get("market") or {}
    state = (ctx or {}).get("state") or {}
    lot = state.get("lot") or {}
    cost = lot.get("price")
    if cost is None:
        cost = state.get("cost")
    price = market.get("close")
    try:
        cost = float(cost or 0)
    except (TypeError, ValueError):
        cost = 0.0
    if cost <= 0 or price is None:
        return False, {}
    hit = float(price) <= cost * (1.0 - float(STOP_LOSS))
    return bool(hit), {"cost": cost, "price": float(price)}
