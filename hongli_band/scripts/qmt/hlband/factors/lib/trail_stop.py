# === hlband/factors/lib/trail_stop.py ===
def _trail_tier_params(max_profit):
    """按峰值浮盈选档，返回 (giveback, profit_floor)；未达起步档则 (None, None)。"""
    mp = float(max_profit)
    for lo, hi, giveback, floor in TRAIL_TIERS:
        if mp < float(lo):
            continue
        if hi is not None and mp >= float(hi):
            continue
        fl = None if floor is None else float(floor)
        return float(giveback), fl
    return None, None


def _trail_stop_hit(price, cost, peak=None):
    """阶梯移动止盈：峰值浮盈落档后，回撤超容忍 或 跌破利润底线。"""
    if cost is None or cost <= 0:
        return False
    if peak is None:
        peak = getattr(A, "hold_peak", None)
    if peak is None or peak <= 0:
        return False
    max_profit = (float(peak) - float(cost)) / float(cost)
    giveback_lim, profit_floor = _trail_tier_params(max_profit)
    if giveback_lim is None:
        return False
    giveback = (float(peak) - float(price)) / float(peak)
    if giveback > giveback_lim:
        return True
    if profit_floor is not None:
        cur_profit = (float(price) - float(cost)) / float(cost)
        if cur_profit < profit_floor:
            return True
    return False


def _factor_eval_trail_stop(ctx):
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
    try:
        cost = float(cost or 0)
    except (TypeError, ValueError):
        cost = 0.0
    if price is None:
        return False, {}
    return bool(_trail_stop_hit(price, cost, peak=peak)), {"cost": cost, "peak": peak}
