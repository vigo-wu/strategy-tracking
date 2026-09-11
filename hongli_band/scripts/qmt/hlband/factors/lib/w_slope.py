# === hlband/factors/lib/w_slope.py ===
def _f_w_slope(ctx):
    w_detail = (ctx.get("market") or {}).get("w_detail") or {}
    m5 = w_detail.get("ma5")
    m30 = w_detail.get("ma30")
    if m5 is None or m30 is None or m30 <= 0:
        return False, {"w_bias_low": None}
    bias = (float(m5) - float(m30)) / float(m30)
    if bias >= float(W_BIAS_LOW):
        return False, {"w_bias_low": bias}
    slope_ok = bool(w_detail.get("ma30_slope_up2"))
    return (not slope_ok), {"w_bias_low": bias}


def _weekly_low_slope_guard(w_detail):
    """低位 (MA5-MA34)/MA34 < W_BIAS_LOW 且生命线 MA34 未连续向上 → 禁开。"""
    ctx = {"market": {"w_detail": w_detail or {}}, "state": {}, "clock": {}}
    ok, detail = _f_w_slope(ctx)
    return ok, detail.get("w_bias_low")


_register_factor("w_slope", _f_w_slope, "w_slope_skip", "gate")
