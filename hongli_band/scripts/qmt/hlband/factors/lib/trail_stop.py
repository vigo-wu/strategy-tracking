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


def _trail_arm():
    """档 1 起步 peak_lo；time_force 让路与网格 init 指纹共用。"""
    tiers = globals().get("TRAIL_TIERS") or ()
    try:
        return float(tiers[0][0])
    except (IndexError, TypeError, ValueError):
        return None


def _time_force_min_ret():
    arm = _trail_arm()
    if arm is None:
        return 0.0
    try:
        return float(arm)
    except (TypeError, ValueError):
        return 0.0


def _f_trail_stop(ctx):
    st = ctx.get("state") or {}
    m = ctx.get("market") or {}
    price = m.get("price")
    cost = st.get("cost")
    peak = st.get("hold_peak")
    if price is None:
        return False, {}
    return _trail_stop_hit(price, cost, peak=peak), {}


_register_factor("trail_stop", _f_trail_stop)
