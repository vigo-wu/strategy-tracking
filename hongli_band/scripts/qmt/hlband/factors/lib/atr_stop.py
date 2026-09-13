# === hlband/factors/lib/atr_stop.py ===
def _factor_eval_atr_stop(ctx):
    """收盘 <= 成本 - k * ATR。n<=0 或 k<=0 关掉。"""
    market = (ctx or {}).get("market") or {}
    state = (ctx or {}).get("state") or {}
    lot = state.get("lot") or {}
    cost = lot.get("price")
    if cost is None:
        cost = state.get("cost")
    price = market.get("close")
    atr = market.get("atr")
    try:
        atr_n = int(market.get("atr_n") or 0)
    except (TypeError, ValueError):
        atr_n = 0
    try:
        k = float(_factor_param(ctx, "atr_stop", "k"))
    except (TypeError, ValueError):
        k = 0.0
    try:
        cost = float(cost or 0)
    except (TypeError, ValueError):
        cost = 0.0
    if atr_n <= 0 or k <= 0 or cost <= 0 or price is None or atr is None:
        return False, {}
    try:
        atr = float(atr)
    except (TypeError, ValueError):
        return False, {}
    if atr <= 0:
        return False, {}
    hit = float(price) <= cost - k * atr
    return bool(hit), {"cost": cost, "price": float(price), "atr": atr, "k": k}
