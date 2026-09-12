# === hlband/factors/lib/time_force.py ===
def _trail_arm():
    """档 1 起步 peak_lo；time_force 让路与网格 init 指纹共用。"""
    tiers = _factor_param(None, "trail_stop", "tiers")
    try:
        return float(tiers[0][0])
    except (IndexError, TypeError, ValueError):
        return None


def _time_force_min_ret():
    arm = _trail_arm()
    if arm is None:
        return 0.0
    try:
        return float(arm)
    except (TypeError, ValueError):
        return 0.0


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


def _time_force_hit(price, closes, hold_bars, lot=None, ctx=None):
    """智能时间成本：持仓 > time_force.bars 后评估出场。
    bars<=0 关闭整条规则。
    d_ma.slow<=0 时慢线地板不存在，同样不触发（BARS 仍独立）。
    收盘破日线慢均线 → 立即强制平仓。
    仍站上慢线时：峰值已达 TRAIL 档1 peak_lo 则不按日历强平；
    从未武装的死钱仓立即强平。"""
    try:
        raw_bars = _factor_param(ctx, "time_force", "bars")
        bars_lim = int(raw_bars)
    except (TypeError, ValueError):
        bars_lim = 0
    if bars_lim <= 0:
        return False
    try:
        slow_n = int(_structure_windows()["d_ma"]["slow"] or 0)
    except (TypeError, ValueError):
        slow_n = 0
    if slow_n <= 0:
        return False
    if hold_bars is None or int(hold_bars) <= bars_lim:
        return False
    ma60_arr = _price_ma(closes, slow_n)
    if ma60_arr is None:
        return False
    i = len(closes) - 1
    ma60 = _last_valid(ma60_arr, i)
    if ma60 is None or price is None:
        return False
    px = float(price)
    m60 = float(ma60)

    if px < m60:
        return True

    min_ret = _time_force_min_ret()
    peak_ret = _time_force_peak_ret(lot)
    already = _time_force_already_skip(lot)
    if min_ret > 0 and (already or peak_ret >= min_ret):
        if not already:
            _time_force_mark_skip(lot, peak_ret, hold_bars, m60)
        return False

    return True


def _factor_eval_time_force(ctx):
    market = (ctx or {}).get("market") or {}
    state = (ctx or {}).get("state") or {}
    lot = state.get("lot")
    closes = market.get("closes")
    price = market.get("close")
    if lot is None:
        hold_bars = state.get("hold_bars")
        if hold_bars is None:
            hold_bars = getattr(A, "hold_bars", 0)
    else:
        hold_bars = lot.get("hold_bars", 0)
    return bool(_time_force_hit(price, closes, hold_bars, lot=lot, ctx=ctx)), {}
