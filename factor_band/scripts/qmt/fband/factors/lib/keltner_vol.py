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
        ema_n = int(win["ema_n"] or 0)
    except (TypeError, ValueError, KeyError):
        ema_n = 0
    try:
        atr_n = int(win["atr_n"] or 0)
    except (TypeError, ValueError, KeyError):
        atr_n = 0
    mid = market.get("kc_mid")
    atr = market.get("kc_atr")
    price = market.get("close")
    if price is None:
        price = market.get("daily_detail", {}).get("price")
    if k <= 0 or ema_n <= 0 or atr_n <= 0 or None in (mid, atr, price):
        return False, {"k": k, "inside": False, "vol_streak": 0}
    upper = float(mid) + k * float(atr)
    lower = float(mid) - k * float(atr)
    inside = lower <= float(price) <= upper
    raw_ratio = _factor_param(ctx, "keltner_vol", "ratio")
    try:
        ratio = float(0.9 if raw_ratio is None else raw_ratio)
    except (TypeError, ValueError):
        ratio = 0.9
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
    volumes = market.get("volumes")
    vol_sma = _sma(volumes, vol_n) if vol_n > 0 else None
    vol_streak = 0
    if volumes is None or vol_sma is None:
        return False, {
            "k": k,
            "inside": inside,
            "vol_streak": 0,
            "upper": upper,
            "lower": lower,
        }
    i = int(market.get("i") or 0)
    for step in range(vol_need):
        j = i - step
        if j < 0:
            break
        vma = _last_valid(vol_sma, j)
        vj = float(volumes[j])
        if vma is None or vma <= 0 or vj >= vma * ratio:
            break
        vol_streak += 1
    hit = bool(inside and vol_streak >= vol_need)
    return hit, {
        "k": k,
        "inside": inside,
        "vol_streak": vol_streak,
        "upper": upper,
        "lower": lower,
    }
