# === hwr/strategy.py ===
def _bar_hhmm(dt):
    if dt is None:
        return "0000"
    return dt.strftime("%H%M")


def _in_buy_time_window(dt):
    """14:48 <= t <= 14:55（含两端）。"""
    t = _bar_hhmm(dt)
    return (t >= str(BUY_TIME_START)) and (t <= str(BUY_TIME_END))


def _is_next_day_hold(now):
    """持仓且当前日 > 买入日。"""
    if not (_has_position() or (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100)):
        return False
    ed = _entry_date()
    if ed is None:
        ot = getattr(A, "bt_opened_at", "") if getattr(A, "is_backtest", False) else ""
        ed_dt = _parse_opened_at(ot)
        if ed_dt is None:
            return False
        ed = ed_dt.date()
    if now is None:
        return False
    return now.date() > ed


def _eval_signals(price, buy_ok, today_vwap, bar_dt, now):
    """返回 (buy, sell_reason)。"""
    buy = bool(buy_ok) and _in_buy_time_window(bar_dt)

    sell_reason = None
    if not _is_next_day_hold(now):
        return buy, sell_reason

    t = _bar_hhmm(bar_dt if getattr(A, "is_backtest", False) else now)
    cost = _pos_cost_price()
    if cost <= 0 or price is None:
        if t >= str(FORCE_EXIT_HHMM):
            sell_reason = "t1_force_1430"
        return buy, sell_reason

    ret = (float(price) - cost) / cost

    # 1) 硬止损 -1.5%
    if ret <= -float(STOP_LOSS):
        return buy, "stop_loss"

    # 2) >=09:35 动态追踪 / 硬止盈
    if t >= str(TRAIL_START_HHMM):
        if ret >= float(TARGET_PROFIT):
            return buy, "take_profit"
        if (
            today_vwap is not None
            and ret > float(TRAIL_ARM_RET)
            and float(price) < float(today_vwap)
        ):
            return buy, "trail_vwap"

    # 3) >=14:30 保底清仓
    if t >= str(FORCE_EXIT_HHMM):
        return buy, "t1_force_1430"

    return buy, sell_reason


# -------------------- 主逻辑 --------------------
def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = now.strftime("%H%M%S")
    day = now.strftime("%Y%m%d")
    hhmm = _bar_hhmm(bar_dt if bt else now)

    if not bt:
        if getattr(A, "pending", None):
            if _process_pending(C, now):
                _live_heartbeat("pending")
                return
        if now_s < DECISION_START or now_s > DECISION_END:
            _live_heartbeat("outside_session")
            return
        if LIVE_ONLY_LAST_BAR:
            try:
                if hasattr(C, "is_last_bar") and (not C.is_last_bar()):
                    return
            except Exception:
                pass
        _live_heartbeat("in_session")
    else:
        _bt_roll_t1(day)
        _bt_recover_position(now=now)

    _reset_day(day)

    cash = _available_cash()
    if cash is None:
        _live_heartbeat("no_cash_or_login")
        return

    ohlcv = _get_ohlcv(C, A.stock)
    if ohlcv is None:
        _live_heartbeat("ohlcv_none")
        return
    high, low, close, volume = ohlcv
    price = float(close[-1])
    if bt:
        _bt_recover_position(now=now, last=price)

    buy_ok, vwap, day_high, mom10, vol_ratio = _buy_filters(close, high, volume)
    tc, tv = _today_slice(close, volume, hhmm)
    today_vwap = _vwap(tc, tv)

    buy, sell_reason = _eval_signals(price, buy_ok, today_vwap, bar_dt, now)
    holding = _has_position() or (bt and _bt_held_vol() >= 100)
    ret_pct = None
    cost = _pos_cost_price()
    if holding and cost > 0:
        ret_pct = (price - cost) / cost

    interesting = buy or bool(sell_reason) or holding
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 60 == 0):
        A.ready_logged = True
        print(
            "%s" % STRATEGY_NAME,
            day,
            hhmm,
            "n=%d close=%.4f vwap=%s hi=%s mom10=%s volR=%s tVwap=%s buy=%s sell=%s hold=%s ret=%s bt_held=%s avail=%s"
            % (
                len(close),
                price,
                None if vwap is None else round(float(vwap), 4),
                None if day_high is None else round(float(day_high), 4),
                None if mom10 is None else ("%.2f%%" % (mom10 * 100.0)),
                None if vol_ratio is None else round(float(vol_ratio), 2),
                None if today_vwap is None else round(float(today_vwap), 4),
                buy,
                sell_reason,
                holding,
                None if ret_pct is None else ("%.2f%%" % (ret_pct * 100.0)),
                _bt_held_vol() if bt else "-",
                _bt_available_vol() if bt else "-",
            ),
        )

    # 先卖后买
    if sell_reason and holding:
        _order_sell(C, sell_reason, price, now)
        return
    if buy and (not holding) and ("BUY" not in getattr(A, "acted", set())):
        budget = _buy_budget(cash)
        _order_buy(C, price, now, budget)


