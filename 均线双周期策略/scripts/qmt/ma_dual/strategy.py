# === ma_dual/strategy.py ===
def _bar_hhmm(dt):
    if dt is None:
        return "0000"
    return dt.strftime("%H%M")


def _bar_hhmmss(dt):
    if dt is None:
        return "000000"
    return dt.strftime("%H%M%S")


def _bar_tag(dt):
    if dt is None:
        return ""
    return dt.strftime("%Y%m%d%H%M%S")


def _eval_daily(closes_d):
    """返回 (daily_ok, daily_break, ma20, ma60, close)."""
    ma20 = _sma(closes_d, D_MA_FAST)
    ma60 = _sma(closes_d, D_MA_SLOW)
    if ma20 is None or ma60 is None:
        return False, False, None, None, None
    i = len(closes_d) - 1
    c = float(closes_d[i])
    m20 = float(ma20[i]) if ma20[i] == ma20[i] else None
    m60 = float(ma60[i]) if ma60[i] == ma60[i] else None
    if m20 is None or m60 is None:
        return False, False, None, None, c
    daily_ok = (c > m20) and (m20 > m60)
    daily_break = c < m20
    return daily_ok, daily_break, m20, m60, c


def _eval_hourly_buy(closes_h, ma5, ma10, ma120):
    """金叉 + MA120 支撑. 返回 (buy_signal, detail)."""
    detail = {"support": False, "golden": False, "ma5": None, "ma10": None, "ma120": None}
    if closes_h is None or ma5 is None or ma10 is None or ma120 is None:
        return False, detail
    if len(closes_h) < 2:
        return False, detail
    i = len(closes_h) - 1
    c = float(closes_h[i])
    f0 = float(ma5[i]) if ma5[i] == ma5[i] else None
    f1 = float(ma5[i - 1]) if ma5[i - 1] == ma5[i - 1] else None
    m0 = float(ma10[i]) if ma10[i] == ma10[i] else None
    m1 = float(ma10[i - 1]) if ma10[i - 1] == ma10[i - 1] else None
    s0 = float(ma120[i]) if ma120[i] == ma120[i] else None
    detail["ma5"] = f0
    detail["ma10"] = m0
    detail["ma120"] = s0
    if f0 is None or f1 is None or m0 is None or m1 is None or s0 is None:
        return False, detail
    detail["support"] = c >= s0 * (1.0 - float(MA120_TOL))
    detail["golden"] = (f1 <= m1) and (f0 > m0)
    return bool(detail["support"] and detail["golden"]), detail


def _eval_hourly_stop(price, cost, lows_h):
    """返回 (stop, reason)."""
    if cost is None or cost <= 0 or price is None:
        return False, None
    ret = (float(price) - float(cost)) / float(cost)
    if ret <= -float(STOP_LOSS):
        return True, "stop_1h"
    if USE_SWING_STOP:
        # 入场前低点存于 position.swing_low; 若无则用近期低点
        sl = 0.0
        if _has_position():
            sl = float(A.position.get("swing_low", 0) or 0)
        if sl <= 0:
            sl = _swing_low(lows_h)
        if sl > 0 and float(price) < sl:
            return True, "stop_swing"
    return False, None


def _pending_ready(pend, day, bar_tag, mode):
    """mode: hour | day. 信号 bar 之后的下一根才执行."""
    if not isinstance(pend, dict):
        return False
    sig_tag = str(pend.get("signal_tag", "") or "")
    sig_day = str(pend.get("signal_day", "") or "")
    if mode == "day":
        return bool(sig_day) and sig_day < day
    # hour: 信号 tag 严格早于当前 bar
    if sig_tag and bar_tag:
        return sig_tag < bar_tag
    if sig_day and sig_day < day:
        return True
    return False


# -------------------- 主逻辑 --------------------
def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    day = now.strftime("%Y%m%d")
    tag = _bar_tag(bar_dt)
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

    ohlcv_h = _get_ohlcv_1h(C, A.stock)
    if ohlcv_h is None:
        _live_heartbeat("ohlcv_1h_none")
        return
    opens_h, highs_h, lows_h, closes_h, _vols_h = ohlcv_h

    ohlcv_d = _get_ohlcv_1d(C, A.stock)
    if ohlcv_d is None:
        _live_heartbeat("ohlcv_1d_none")
        return
    _od, _hd, _ld, closes_d, _vd = ohlcv_d

    ma5 = _sma(closes_h, H_MA_FAST)
    ma10 = _sma(closes_h, H_MA_MID)
    ma120 = _sma(closes_h, H_MA_SLOW)
    if ma5 is None or ma10 is None or ma120 is None:
        _live_heartbeat("ind_none")
        return

    price = float(closes_h[-1])
    open_px = float(opens_h[-1])
    if bt:
        _bt_recover_position(now=now, last=price)

    daily_ok, daily_break, d_ma20, d_ma60, d_close = _eval_daily(closes_d)
    buy_sig, h_detail = _eval_hourly_buy(closes_h, ma5, ma10, ma120)

    holding = _has_position() or (bt and _bt_held_vol() >= 100)
    cost = _pos_cost_price()
    stop_hit, stop_reason = (False, None)
    if holding:
        stop_hit, stop_reason = _eval_hourly_stop(price, cost, lows_h)

    ret_pct = None
    if holding and cost > 0:
        ret_pct = (price - cost) / cost

    interesting = buy_sig or daily_break or stop_hit or holding or bool(
        getattr(A, "pending_entry", None) or getattr(A, "pending_exit", None)
    )
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 20 == 0):
        A.ready_logged = True
        print(
            "%s" % STRATEGY_NAME,
            day,
            hhmm,
            "n1h=%d n1d=%d close=%.4f open=%.4f "
            "d_ok=%s d_brk=%s d_ma20=%s d_ma60=%s "
            "ma5=%s ma10=%s ma120=%s support=%s golden=%s "
            "buy=%s stop=%s hold=%s ret=%s "
            "pe=%s px=%s bt_held=%s avail=%s"
            % (
                len(closes_h),
                len(closes_d),
                price,
                open_px,
                daily_ok,
                daily_break,
                None if d_ma20 is None else round(d_ma20, 4),
                None if d_ma60 is None else round(d_ma60, 4),
                None if h_detail.get("ma5") is None else round(h_detail["ma5"], 4),
                None if h_detail.get("ma10") is None else round(h_detail["ma10"], 4),
                None if h_detail.get("ma120") is None else round(h_detail["ma120"], 4),
                h_detail.get("support"),
                h_detail.get("golden"),
                buy_sig,
                stop_reason,
                holding,
                None if ret_pct is None else ("%.2f%%" % (ret_pct * 100.0)),
                bool(getattr(A, "pending_entry", None)),
                bool(getattr(A, "pending_exit", None)),
                _bt_held_vol() if bt else "-",
                _bt_available_vol() if bt else "-",
            ),
        )

    # ---- 先执行挂起的卖/买（本根开盘）----
    pe_exit = getattr(A, "pending_exit", None)
    if holding and isinstance(pe_exit, dict):
        mode = str(pe_exit.get("mode", "hour") or "hour")
        if _pending_ready(pe_exit, day, tag, mode):
            reason = str(pe_exit.get("reason", "SELL") or "SELL")
            _order_sell(C, reason, open_px, now)
            return

    pe_entry = getattr(A, "pending_entry", None)
    if (
        (not holding)
        and isinstance(pe_entry, dict)
        and ("BUY" not in getattr(A, "acted", set()))
        and _pending_ready(pe_entry, day, tag, "hour")
    ):
        budget = _buy_budget(cash)
        sl = float(pe_entry.get("swing_low", 0) or 0)
        _order_buy(C, open_px, now, budget, swing_low=sl)
        return

    # ---- 评估新信号（收盘确认 → 挂到下一根；已有挂起不刷新 tag，避免推迟执行）----
    if holding:
        cur_ex = getattr(A, "pending_exit", None)
        if daily_break:
            if not isinstance(cur_ex, dict):
                A.pending_exit = {
                    "mode": "day",
                    "reason": "daily_break",
                    "signal_day": day,
                    "signal_tag": tag,
                    "close": price,
                    "d_close": d_close,
                }
                _save_state()
                print("%s pending_exit set" % STRATEGY_NAME, A.pending_exit)
            elif str(cur_ex.get("mode")) != "day":
                # 小时止损挂起升级为日线破位（保留更早 signal_day 以便尽快次日开盘）
                A.pending_exit = {
                    "mode": "day",
                    "reason": "daily_break",
                    "signal_day": str(cur_ex.get("signal_day") or day),
                    "signal_tag": str(cur_ex.get("signal_tag") or tag),
                    "close": price,
                    "d_close": d_close,
                }
                _save_state()
                print("%s pending_exit upgrade daily_break" % STRATEGY_NAME, A.pending_exit)
            return
        if stop_hit and stop_reason:
            if isinstance(cur_ex, dict):
                return
            A.pending_exit = {
                "mode": "hour",
                "reason": stop_reason,
                "signal_day": day,
                "signal_tag": tag,
                "close": price,
            }
            _save_state()
            print("%s pending_exit set" % STRATEGY_NAME, A.pending_exit)
            return
        return

    # 无仓: 双周期共振买点
    if buy_sig and daily_ok and ("BUY" not in getattr(A, "acted", set())):
        if isinstance(getattr(A, "pending_entry", None), dict):
            return
        sl = _swing_low(lows_h[:-1] if len(lows_h) > 1 else lows_h)
        A.pending_entry = {
            "signal_day": day,
            "signal_tag": tag,
            "swing_low": sl,
            "close": price,
        }
        A.pending_exit = None
        _save_state()
        print("%s pending_entry set" % STRATEGY_NAME, A.pending_entry)


