# === hlband/factors/lib/plat_break.py ===
def _daily_plat_break(closes, highs, lows):
    """日线收盘确认突破前期平台：回看窗口振幅够窄，今日收盘站上窗口最高价，昨收仍在平台内。"""
    lookback = int(globals().get("SCALE_PLAT_LOOKBACK") or 20)
    max_range = float(globals().get("SCALE_PLAT_MAX_RANGE") or 0.10)
    buf = float(globals().get("SCALE_PLAT_BREAK_BUF") or 0.0)
    if lookback < 5 or max_range <= 0:
        return False
    if closes is None or highs is None or lows is None:
        return False
    n = len(closes)
    if n < lookback + 1 or len(highs) != n or len(lows) != n:
        return False
    if n < 2:
        return False
    plat = _plat_window(highs, lows, lookback)
    if plat is None:
        return False
    plat_high, plat_low = plat
    rng = (float(plat_high) - float(plat_low)) / float(plat_low)
    if rng > max_range:
        return False
    hurdle = float(plat_high) * (1.0 + buf)
    px = float(closes[-1])
    prev = float(closes[-2])
    if px <= hurdle:
        return False
    if prev > hurdle:
        return False
    return True


def _f_plat_break(ctx):
    m = ctx.get("market") or {}
    return _daily_plat_break(m.get("closes"), m.get("highs"), m.get("lows")), {}


_register_factor("plat_break", _f_plat_break)
