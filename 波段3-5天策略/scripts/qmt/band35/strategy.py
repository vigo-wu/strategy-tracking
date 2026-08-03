# === band35/strategy.py ===
def _bar_hhmm(dt):
    if dt is None:
        return "0000"
    return dt.strftime("%H%M")


def _in_buy_time_window(dt):
    t = _bar_hhmm(dt)
    return (t >= str(BUY_TIME_START)) and (t < str(BUY_TIME_END))


def _eval_signals(price, k, d, prev_k, prev_d, bar_dt, ma10, now):
    """返回 (buy, sell_reason)。sell_reason 为 None 表示不卖。"""
    buy = (
        price is not None
        and ma10 is not None
        and price > ma10
        and k < BUY_K_MAX
        and d < BUY_D_MAX
        and k > d
        and prev_k <= prev_d
        and _in_buy_time_window(bar_dt)
    )

    sell_reason = None
    if _has_position() or (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100):
        cost = _pos_cost_price()
        if k > SELL_K_MIN and k < d and prev_k >= prev_d:
            sell_reason = "tech_death"
        elif cost > 0 and price <= cost * (1.0 - STOP_LOSS):
            sell_reason = "stop_loss"
        elif ma10 is not None and price < ma10 * float(DAILY_BREAK_RATIO):
            sell_reason = "daily_break"
        elif cost > 0 and price >= cost * (1.0 + TAKE_PROFIT):
            sell_reason = "take_profit"
        else:
            opened = A.position.get("opened_at") if A.position else getattr(A, "bt_opened_at", "")
            if _hold_calendar_days(opened, now) >= MAX_HOLD_DAYS:
                sell_reason = "max_hold"

    return buy, sell_reason


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = now.strftime("%H%M%S")
    day = now.strftime("%Y%m%d")

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

    ohlc = _get_ohlc(C, A.stock)
    if ohlc is None:
        _live_heartbeat("ohlc_none")
        return
    high, low, close = ohlc
    kd = _calc_kdj(high, low, close)
    if kd is None:
        _live_heartbeat("kdj_none")
        return
    k_arr, d_arr = kd
    price = float(close[-1])
    k = float(k_arr[-1])
    d = float(d_arr[-1])
    prev_k = float(k_arr[-2])
    prev_d = float(d_arr[-2])

    daily_close, ma10 = _get_daily_ma(C, A.stock)
    if bt:
        _bt_recover_position(now=now, last=price)

    buy, sell_reason = _eval_signals(
        price, k, d, prev_k, prev_d, bar_dt, ma10, now
    )
    holding = _has_position() or (bt and _bt_held_vol() >= 100)
    hold_d = 0
    if holding and A.position:
        hold_d = _hold_calendar_days(A.position.get("opened_at"), now)

    interesting = buy or bool(sell_reason) or holding
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 20 == 0):
        A.ready_logged = True
        print(
            "%s" % STRATEGY_NAME,
            day,
            _bar_hhmm(bar_dt),
            "n=%d close=%.4f K=%.2f D=%.2f ma10=%s buy=%s sell=%s hold=%s days=%s bt_held=%s avail=%s"
            % (
                len(close),
                price,
                k,
                d,
                None if ma10 is None else round(ma10, 4),
                buy,
                sell_reason,
                holding,
                hold_d,
                _bt_held_vol() if bt else "-",
                _bt_available_vol() if bt else "-",
            ),
        )

    if sell_reason and holding:
        _order_sell(C, sell_reason, price, now)
        return
    if buy and (not holding) and ("BUY" not in getattr(A, "acted", set())):
        if ma10 is None:
            print("%s buy skip: no daily MA" % STRATEGY_NAME)
            return
        _order_buy(C, price, now)
