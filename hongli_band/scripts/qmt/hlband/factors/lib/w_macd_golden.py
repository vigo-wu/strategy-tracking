# === hlband/factors/lib/w_macd_golden.py ===
def _factor_eval_w_macd_golden(ctx):
    w_detail = ((ctx or {}).get("market") or {}).get("w_detail") or {}
    if not w_detail:
        return False, {}
    h0 = w_detail.get("hist")
    h1 = w_detail.get("hist_prev")
    if h0 is None or h1 is None:
        return False, {}
    hist = float(h0)
    hist_prev = float(h1)
    if hist <= 0 or hist <= hist_prev:
        return False, {}
    golden_now = bool(w_detail.get("macd_golden_now"))
    golden_prev = bool(w_detail.get("macd_golden_prev"))
    if not (golden_now or golden_prev):
        return False, {}
    if golden_now and (not golden_prev):
        return True, {"golden_now": True}
    ratio = float(globals().get("SCALE_W_HIST_EXPAND_RATIO") or 1.0)
    if ratio <= 1.0:
        return True, {"ratio": ratio}
    base = abs(hist_prev) if abs(hist_prev) > 1e-12 else hist
    hit = hist >= base * ratio
    return bool(hit), {"hist": hist, "hist_prev": hist_prev}
