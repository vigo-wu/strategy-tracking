# === hlband/factors/lib/w_slope.py ===
def _factor_eval_w_slope(ctx):
    w_detail = ((ctx or {}).get("market") or {}).get("w_detail") or {}
    m5 = w_detail.get("ma5")
    m30 = w_detail.get("ma30")
    if m5 is None or m30 is None or m30 <= 0:
        return False, {"bias": None}
    bias = (float(m5) - float(m30)) / float(m30)
    if bias >= float(W_BIAS_LOW):
        return False, {"bias": bias}
    slope_ok = bool(w_detail.get("ma30_slope_up2"))
    return (not slope_ok), {"bias": bias, "slope_ok": slope_ok}
