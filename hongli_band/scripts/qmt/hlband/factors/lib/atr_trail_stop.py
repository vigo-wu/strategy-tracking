# === hlband/factors/lib/atr_trail_stop.py ===
def _factor_eval_atr_trail_stop(ctx):
    """峰值相对成本 > k1*ATR 武装：收盘<=成本 或 峰值回撤>=k2*ATR。"""
    market = (ctx or {}).get("market") or {}
    state = (ctx or {}).get("state") or {}
    lot = state.get("lot") or {}
    cost = lot.get("price")
    if cost is None:
        cost = state.get("cost")
    peak = lot.get("hold_peak")
    if peak is None:
        peak = state.get("hold_peak")
    price = market.get("close")
    atr = market.get("atr")
    try:
        atr_n = int(market.get("atr_n") or 0)
    except (TypeError, ValueError):
        atr_n = 0
    try:
        k1 = float(_factor_param(ctx, "atr_trail_stop", "k1"))
    except (TypeError, ValueError):
        k1 = 0.0
    try:
        k2 = float(_factor_param(ctx, "atr_trail_stop", "k2"))
    except (TypeError, ValueError):
        k2 = 0.0
    try:
        cost = float(cost or 0)
    except (TypeError, ValueError):
        cost = 0.0
    if atr_n <= 0 or k1 <= 0 or cost <= 0 or price is None or atr is None:
        return False, {}
    if peak is None:
        return False, {}
    try:
        peak = float(peak)
        atr = float(atr)
    except (TypeError, ValueError):
        return False, {}
    if peak <= 0 or atr <= 0:
        return False, {}
    if not (peak - cost > k1 * atr):
        return False, {"cost": cost, "peak": peak, "atr": atr, "armed": False}
    px = float(price)
    be = px <= cost
    giveback = False
    if k2 > 0:
        giveback = (peak - px) >= k2 * atr
    hit = bool(be or giveback)
    return hit, {
        "cost": cost,
        "price": px,
        "peak": peak,
        "atr": atr,
        "k1": k1,
        "k2": k2,
        "armed": True,
        "breakeven": bool(be),
        "giveback": bool(giveback),
    }
