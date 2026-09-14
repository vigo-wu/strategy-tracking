# === fband/factors/lib/scale_arm.py ===
def _scale_arm_threshold(ctx=None):
    raw = _factor_param(ctx, "scale_arm", "arm", 0.03)
    try:
        arm = float(raw)
    except (TypeError, ValueError):
        arm = 0.03
    if arm <= 0:
        arm = 0.03
    return arm


def _scale_arm_need_bars(ctx=None):
    raw = _factor_param(ctx, "scale_arm", "bars", 8)
    try:
        return int(0 if raw is None else raw)
    except (TypeError, ValueError):
        return 0


def _scale_arm_hist_min(ctx=None):
    raw = _factor_param(ctx, "scale_arm", "hist_min", -0.01)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _scale_arm_hold_peak(state=None):
    st = state or {}
    peak = st.get("hold_peak")
    bars = st.get("hold_bars")
    cost = st.get("cost")
    obj = globals().get("A")
    if peak is None and obj is not None:
        peak = getattr(obj, "hold_peak", None)
    if bars is None and obj is not None:
        bars = getattr(obj, "hold_bars", 0)
    if cost is None:
        cost_fn = globals().get("_pos_cost_price")
        cost = cost_fn() if callable(cost_fn) else 0
    try:
        cost = float(cost or 0)
    except (TypeError, ValueError):
        cost = 0.0
    mx = 0.0
    if peak and cost > 0:
        mx = (float(peak) - float(cost)) / float(cost)
    return mx, int(bars or 0)


def _scale_arm_peak(ctx=None):
    """任一笔峰值浮盈与该笔持仓日。优先 ctx.state.lots。"""
    arm = _scale_arm_threshold(ctx)
    state = (ctx or {}).get("state") or {}
    lots = state.get("lots")
    lots_enabled = False
    enabled_fn = globals().get("_lots_enabled")
    if callable(enabled_fn):
        try:
            lots_enabled = bool(enabled_fn())
        except Exception:
            lots_enabled = False
    if lots is None and lots_enabled:
        lots_fn = globals().get("_ensure_lots")
        if callable(lots_fn):
            lots = lots_fn()
    if lots is None:
        return _scale_arm_hold_peak(state)
    mx = 0.0
    armed_bars = 0
    for lot in lots:
        try:
            ret = float(lot.get("hold_max_ret") or 0)
        except Exception:
            ret = 0.0
        bars = int(lot.get("hold_bars") or 0)
        if ret > mx:
            mx = ret
        if ret >= arm and bars > armed_bars:
            armed_bars = bars
    if mx <= 0:
        return _scale_arm_hold_peak(state)
    return mx, armed_bars


def _factor_eval_scale_arm(ctx):
    """峰值浮盈 >= arm，且该笔持仓日 >= bars，且周柱 >= hist_min。"""
    mx, armed_bars = _scale_arm_peak(ctx)
    arm = _scale_arm_threshold(ctx)
    detail = {"peak": mx, "armed_bars": armed_bars, "arm": arm}
    if mx < arm:
        return False, detail
    need_bars = _scale_arm_need_bars(ctx)
    detail["need_bars"] = need_bars
    if need_bars > 0 and armed_bars < need_bars:
        return False, detail
    hist_min = _scale_arm_hist_min(ctx)
    detail["hist_min"] = hist_min
    if hist_min is not None:
        w_detail = ((ctx or {}).get("market") or {}).get("w_detail") or {}
        h = w_detail.get("hist")
        if h is not None:
            detail["hist"] = float(h)
            if float(h) < float(hist_min):
                return False, detail
    return True, detail
