# === fband/factors/lib/keltner_vol.py ===
def _factor_eval_keltner_vol(ctx):
    market = (ctx or {}).get("market") or {}
    if not market.get("daily_ready"):
        return False, {"vol_streak": 0, "inside": False}
    try:
        k = float(_factor_param(ctx, "keltner_vol", "k"))
    except (TypeError, ValueError):
        k = 0.0
    win = _structure_windows()["keltner"]
    try:
        ma_n = int(win["ma_n"] or 0)
    except (TypeError, ValueError, KeyError):
        ma_n = 0
    try:
        atr_n = int(win["atr_n"] or 0)
    except (TypeError, ValueError, KeyError):
        atr_n = 0
    mid = market.get("kc_mid")
    atr = market.get("kc_atr")
    price = market.get("close")
    if price is None:
        price = market.get("daily_detail", {}).get("price")
    if k <= 0 or ma_n <= 0 or atr_n <= 0 or None in (mid, atr, price):
        return False, {"k": k, "inside": False, "vol_streak": 0}
    upper = float(mid) + k * float(atr)
    lower = float(mid) - k * float(atr)
    inside = lower <= float(price) <= upper
    raw_ratio = _factor_param(ctx, "keltner_vol", "ratio")
    try:
        ratio = float(0.9 if raw_ratio is None else raw_ratio)
    except (TypeError, ValueError):
        ratio = 0.9
    raw_min = _factor_param(ctx, "keltner_vol", "min_ratio")
    try:
        min_ratio = float(0.5 if raw_min is None else raw_min)
    except (TypeError, ValueError):
        min_ratio = 0.5
    raw_vn = _factor_param(ctx, "keltner_vol", "vol_n")
    try:
        vol_n = int(10 if raw_vn is None else raw_vn)
    except (TypeError, ValueError):
        vol_n = 10
    raw_need = _factor_param(ctx, "keltner_vol", "confirm_days")
    try:
        vol_need = int(2 if raw_need is None else raw_need)
    except (TypeError, ValueError):
        vol_need = 2
    vol_need = max(1, vol_need)
    raw_sm = _factor_param(ctx, "keltner_vol", "slope_m")
    try:
        slope_m = int(5 if raw_sm is None else raw_sm)
    except (TypeError, ValueError):
        slope_m = 5
    raw_ms = _factor_param(ctx, "keltner_vol", "min_slope")
    try:
        min_slope = float(0.0 if raw_ms is None else raw_ms)
    except (TypeError, ValueError):
        min_slope = 0.0
    volumes = market.get("volumes")
    vol_sma = _sma(volumes, vol_n) if vol_n > 0 else None
    vol_streak = 0
    if volumes is None or vol_sma is None:
        return False, {
            "k": k,
            "min_ratio": min_ratio,
            "inside": inside,
            "vol_streak": 0,
            "upper": upper,
            "lower": lower,
            "slope_m": slope_m,
            "min_slope": min_slope,
            "norm_slope": None,
        }
    i = int(market.get("i") or 0)
    for step in range(vol_need):
        j = i - step
        if j < 0:
            break
        vma = _last_valid(vol_sma, j)
        vj = float(volumes[j])
        too_low = (
            min_ratio > 0
            and vma is not None
            and vma > 0
            and vj < vma * min_ratio
        )
        if vma is None or vma <= 0 or vj >= vma * ratio or too_low:
            break
        vol_streak += 1
    kc_mid_arr = market.get("kc_mid_arr")
    ns = (
        _norm_slope_from_ma(kc_mid_arr, slope_m)
        if kc_mid_arr is not None
        else None
    )
    norm = _last_valid(ns, i) if ns is not None else None
    slope_ok = norm is not None and float(norm) >= min_slope
    hit = bool(inside and vol_streak >= vol_need and slope_ok)
    return hit, {
        "k": k,
        "min_ratio": min_ratio,
        "inside": inside,
        "vol_streak": vol_streak,
        "upper": upper,
        "lower": lower,
        "slope_m": slope_m,
        "min_slope": min_slope,
        "norm_slope": norm,
    }
