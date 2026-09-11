# === hlband/factors/lib/w_macd_golden.py ===
def _weekly_macd_golden_expand(w_detail):
    """近两周周线 MACD 金叉，且当前红柱比上周放大。"""
    if not w_detail:
        return False
    h0 = w_detail.get("hist")
    h1 = w_detail.get("hist_prev")
    if h0 is None or h1 is None:
        return False
    hist = float(h0)
    hist_prev = float(h1)
    if hist <= 0 or hist <= hist_prev:
        return False
    golden_now = bool(w_detail.get("macd_golden_now"))
    golden_prev = bool(w_detail.get("macd_golden_prev"))
    if not (golden_now or golden_prev):
        return False
    if golden_now and (not golden_prev):
        return True
    ratio = float(globals().get("SCALE_W_HIST_EXPAND_RATIO") or 1.0)
    if ratio <= 1.0:
        return True
    base = abs(hist_prev) if abs(hist_prev) > 1e-12 else hist
    return hist >= base * ratio


def _f_w_macd_golden(ctx):
    m = ctx.get("market") or {}
    return _weekly_macd_golden_expand(m.get("w_detail") or {}), {}


_register_factor("w_macd_golden", _f_w_macd_golden)
