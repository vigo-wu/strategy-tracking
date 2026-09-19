# === fband/factors/lib/atr_stop.py ===
def _factor_eval_atr_stop(ctx):
    """收盘 <= 成本 * (1 - k * ATR% / 100)。n<=0 或 k<=0 关掉。"""
    market = (ctx or {}).get("market") or {}
    state = (ctx or {}).get("state") or {}
    lot = state.get("lot") or {}
    cost = lot.get("price")
    if cost is None:
        cost = state.get("cost")
    price = market.get("close")
    atr = market.get("atr")
    atr_pct = market.get("atr_pct")
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
    if (
        atr_n <= 0
        or k <= 0
        or cost <= 0
        or price is None
        or atr is None
        or atr_pct is None
    ):
        return False, {}
    try:
        atr = float(atr)
        atr_pct = float(atr_pct)
    except (TypeError, ValueError):
        return False, {}
    if atr <= 0 or atr_pct <= 0:
        return False, {}
    hit = float(price) <= cost * (1.0 - k * atr_pct / 100.0)
    return bool(hit), {
        "cost": cost,
        "price": float(price),
        "atr": atr,
        "atr_pct": atr_pct,
        "k": k,
    }
