# === hlband/factors/lib/w_bias.py ===
def _f_w_bias(ctx):
    w_detail = (ctx.get("market") or {}).get("w_detail") or {}
    m5 = w_detail.get("ma5")
    m30 = w_detail.get("ma30")
    if m5 is None or m30 is None or m30 <= 0:
        return False, {"w_bias": None}
    bias = (float(m5) - float(m30)) / float(m30)
    return bias >= float(W_BIAS_HARD), {"w_bias": bias}


def _weekly_bias_guard(w_detail):
    """周线 (MA5-MA34)/MA34 >= W_BIAS_HARD → 禁开。"""
    ctx = {"market": {"w_detail": w_detail or {}}, "state": {}, "clock": {}}
    ok, detail = _f_w_bias(ctx)
    return ok, detail.get("w_bias")


_register_factor("w_bias", _f_w_bias, "w_bias_skip", "gate")
