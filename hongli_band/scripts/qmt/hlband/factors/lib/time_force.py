# === hlband/factors/lib/time_force.py ===
def _time_force_peak_ret(lot):
    if lot is None:
        mx = float(getattr(A, "hold_max_ret", 0) or 0)
        peak = getattr(A, "hold_peak", None)
        cost = _pos_cost_price()
    else:
        try:
            mx = float(lot.get("hold_max_ret") or 0)
        except Exception:
            mx = 0.0
        peak = lot.get("hold_peak")
        cost = float(lot.get("price") or 0)
    if peak and cost and float(cost) > 0:
        mx = max(mx, (float(peak) - float(cost)) / float(cost))
    return mx


def _time_force_already_skip(lot):
    if lot is None:
        return bool(getattr(A, "time_force_trend_skip", False))
    return bool(lot.get("time_force_trend_skip"))


def _time_force_mark_skip(lot, peak_ret, hold_bars, m60):
    if lot is None:
        A.time_force_trend_skip = True
        lid = None
    else:
        lot["time_force_trend_skip"] = True
        lid = lot.get("id")
    print(
        "%s time_force skip trend peak=%.2f%% ma60=%.4f hold=%s lot=%s"
        % (STRATEGY_NAME, float(peak_ret) * 100.0, m60, hold_bars, lid)
    )
    _event_log(
        "time_force_skip_trend",
        peak_ret=peak_ret,
        ma60=m60,
        hold_bars=hold_bars,
        lot_id=lid,
    )
    _save_state()


def _time_force_decide(price, closes, hold_bars, lot=None):
    """只读判定。返回 (hit, hook)。hook=(lot, peak_ret, hold_bars, m60) 需写 skip。"""
    try:
        bars_lim = int(TIME_FORCE_BARS)
    except (TypeError, ValueError):
        bars_lim = 0
    if bars_lim <= 0:
        return False, None
    try:
        slow_n = int(D_MA_SLOW or 0)
    except (TypeError, ValueError):
        slow_n = 0
    if slow_n <= 0:
        return False, None
    if hold_bars is None or int(hold_bars) <= bars_lim:
        return False, None
    ma60_arr = _price_ma(closes, slow_n)
    if ma60_arr is None:
        return False, None
    i = len(closes) - 1
    ma60 = _last_valid(ma60_arr, i)
    if ma60 is None or price is None:
        return False, None
    px = float(price)
    m60 = float(ma60)

    if px < m60:
        return True, None

    min_ret = _time_force_min_ret()
    peak_ret = _time_force_peak_ret(lot)
    already = _time_force_already_skip(lot)
    if min_ret > 0 and (already or peak_ret >= min_ret):
        hook = None if already else (lot, peak_ret, hold_bars, m60)
        return False, hook
    return True, None


def _time_force_hit(price, closes, hold_bars, lot=None):
    """智能时间成本。eval 只读；武装让路的写回在此包装内（测试/兼容旧调用）。"""
    hit, hook = _time_force_decide(price, closes, hold_bars, lot=lot)
    if hook is not None:
        _time_force_mark_skip(*hook)
    return hit


def _f_time_force(ctx):
    st = ctx.get("state") or {}
    m = ctx.get("market") or {}
    price = m.get("price")
    closes = m.get("closes")
    bars = st.get("hold_bars")
    lot = st.get("lot")
    if isinstance(lot, dict) and not lot:
        lot = None
    hit, hook = _time_force_decide(price, closes, bars, lot=lot)
    if hook is not None:
        ctx["_tf_hook"] = hook
    return bool(hit), {}


_register_factor("time_force", _f_time_force)
