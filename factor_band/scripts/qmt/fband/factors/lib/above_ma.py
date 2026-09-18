# === fband/factors/lib/above_ma.py ===
def _factor_eval_above_ma(ctx):
    try:
        n = int(_structure_windows()["ma"]["1d"]["trend"] or 0)
    except (TypeError, ValueError, KeyError):
        n = 0
    if n <= 0:
        return True, {"n": n, "off": True}
    market = (ctx or {}).get("market") or {}
    if not market.get("daily_ready"):
        return False, {"n": n}
    raw_sm = _factor_param(ctx, "above_ma", "slope_m")
    try:
        slope_m = int(5 if raw_sm is None else raw_sm)
    except (TypeError, ValueError):
        slope_m = 5
    raw_ms = _factor_param(ctx, "above_ma", "min_slope")
    try:
        min_slope = float(0.0 if raw_ms is None else raw_ms)
    except (TypeError, ValueError):
        min_slope = 0.0
    price = market.get("close")
    if price is None:
        price = market.get("daily_detail", {}).get("price")
    ma = market.get("d_trend")
    i = int(market.get("i") or 0)
    trend_arr = market.get("d_trend_arr")
    ns = (
        _norm_slope_from_ma(trend_arr, slope_m)
        if trend_arr is not None
        else None
    )
    norm = _last_valid(ns, i) if ns is not None else None
    detail = {
        "n": n,
        "ma": ma,
        "price": None if price is None else float(price),
        "slope_m": slope_m,
        "min_slope": min_slope,
        "norm_slope": norm,
    }
    if price is None or ma is None:
        return False, detail
    slope_ok = norm is not None and float(norm) >= min_slope
    hit = bool(float(price) > float(ma) and slope_ok)
    return hit, detail
