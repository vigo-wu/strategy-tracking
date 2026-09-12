# === hlband/factors/lib/plat_break.py ===
def _plat_window(highs, lows, lookback, end_i=None):
    """不含 end_i 的回看窗口平台高低点；(plat_high, plat_low) 或 None。"""
    if highs is None or lows is None:
        return None
    n = min(len(highs), len(lows))
    lookback = int(lookback)
    if lookback < 2 or n < lookback + 1:
        return None
    i = n - 1 if end_i is None else int(end_i)
    if i < lookback:
        return None
    win_h = [float(x) for x in highs[i - lookback:i]]
    win_l = [float(x) for x in lows[i - lookback:i]]
    if not win_h or not win_l:
        return None
    plat_high = max(win_h)
    plat_low = min(win_l)
    if plat_high <= 0 or plat_low <= 0:
        return None
    return plat_high, plat_low


def _factor_eval_plat_break(ctx):
    market = (ctx or {}).get("market") or {}
    closes = market.get("closes")
    highs = market.get("highs")
    lows = market.get("lows")
    raw_lb = _factor_param(ctx, "plat_break", "lookback")
    raw_rng = _factor_param(ctx, "plat_break", "max_range")
    raw_buf = _factor_param(ctx, "plat_break", "break_buf")
    try:
        lookback = int(20 if raw_lb is None else raw_lb)
    except (TypeError, ValueError):
        lookback = 20
    try:
        max_range = float(0.10 if raw_rng is None else raw_rng)
    except (TypeError, ValueError):
        max_range = 0.10
    try:
        buf = float(0.0 if raw_buf is None else raw_buf)
    except (TypeError, ValueError):
        buf = 0.0
    if lookback < 5 or max_range <= 0:
        return False, {}
    if closes is None or highs is None or lows is None:
        return False, {}
    n = len(closes)
    if n < lookback + 1 or len(highs) != n or len(lows) != n:
        return False, {}
    if n < 2:
        return False, {}
    plat = _plat_window(highs, lows, lookback)
    if plat is None:
        return False, {}
    plat_high, plat_low = plat
    rng = (float(plat_high) - float(plat_low)) / float(plat_low)
    if rng > max_range:
        return False, {"range": rng}
    hurdle = float(plat_high) * (1.0 + buf)
    px = float(closes[-1])
    prev = float(closes[-2])
    if px <= hurdle:
        return False, {"hurdle": hurdle}
    if prev > hurdle:
        return False, {"hurdle": hurdle, "prev": prev}
    return True, {"plat_high": plat_high, "plat_low": plat_low}
