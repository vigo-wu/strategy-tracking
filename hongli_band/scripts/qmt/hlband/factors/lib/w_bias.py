# === hlband/factors/lib/w_bias.py ===
def _factor_eval_w_bias(ctx):
    w_detail = ((ctx or {}).get("market") or {}).get("w_detail") or {}
    m5 = w_detail.get("ma5")
    m30 = w_detail.get("ma30")
    if m5 is None or m30 is None or m30 <= 0:
        return False, {"bias": None}
    bias = (float(m5) - float(m30)) / float(m30)
    return bias >= float(W_BIAS_HARD), {"bias": bias}
