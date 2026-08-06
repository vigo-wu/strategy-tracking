# === hlband/strategy.py ===
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


def _cross_down(a_prev, b_prev, a_now, b_now):
    if None in (a_prev, b_prev, a_now, b_now):
        return False
    return (a_prev >= b_prev) and (a_now < b_now)


def _eval_weekly(closes_w):
    """返回 (bull, bear, detail)。对照表: 多头=5周在上+零轴上红柱; 空头=破30周或零轴下死叉。"""
    detail = {
        "ma5": None,
        "ma10": None,
        "ma30": None,
        "dif": None,
        "dea": None,
        "hist": None,
        "close": None,
    }
    ma5 = _sma(closes_w, W_MA_FAST)
    ma10 = _sma(closes_w, W_MA_MID)
    ma30 = _sma(closes_w, W_MA_LIFE)
    macd = _calc_macd(closes_w)
    if ma5 is None or ma10 is None or ma30 is None or macd is None:
        return False, False, detail
    dif, dea, hist = macd
    i = len(closes_w) - 1
    if i < 1:
        return False, False, detail
    c = float(closes_w[i])
    m5 = _last_valid(ma5, i)
    m10 = _last_valid(ma10, i)
    m30 = _last_valid(ma30, i)
    m30_prev = _last_valid(ma30, i - 1)
    d0 = _last_valid(dif, i)
    e0 = _last_valid(dea, i)
    h0 = _last_valid(hist, i)
    h1 = _last_valid(hist, i - 1)
    d1 = _last_valid(dif, i - 1)
    e1 = _last_valid(dea, i - 1)
    m30_prev2 = _last_valid(ma30, i - 2) if i >= 2 else None
    slope_up_n = False
    if m30 is not None and m30_prev is not None and m30_prev2 is not None:
        # 连续 2 周向上：ma30[t]>ma30[t-1] 且 ma30[t-1]>ma30[t-2]
        slope_up_n = (m30 > m30_prev) and (m30_prev > m30_prev2)
    detail.update(
        {
            "ma5": m5,
            "ma10": m10,
            "ma30": m30,
            "ma30_prev": m30_prev,
            "ma30_slope_up2": slope_up_n,
            "dif": d0,
            "dea": e0,
            "hist": h0,
            "hist_prev": h1,
            "close": c,
        }
    )
    if None in (m5, m10, m30, d0, e0, h0):
        return False, False, detail

    ma30_ok = (m30_prev is None) or (m30 >= m30_prev * 0.998)
    bull = (m5 > m10) and (d0 > 0) and (h0 > 0) and ma30_ok
    death_below = _cross_down(d1, e1, d0, e0) and (d0 < 0) and (e0 < 0)
    bear = (c < m30) or death_below
    return bull, bear, detail


def _eval_daily_buy(closes, volumes):
    """买点：缩量回踩 MA20/MA60。"""
    reasons = []
    ma20 = _sma(closes, D_MA_MID)
    ma60 = _sma(closes, D_MA_SLOW)
    vol10 = _sma(volumes, VOL_PULLBACK_N)
    vol20 = _sma(volumes, VOL_DRY_N)
    if ma20 is None or ma60 is None or vol10 is None or vol20 is None:
        return False, reasons, {}
    i = len(closes) - 1
    if i < 2:
        return False, reasons, {}
    price = float(closes[i])
    vol = float(volumes[i])
    m20 = _last_valid(ma20, i)
    m60 = _last_valid(ma60, i)
    v10 = _last_valid(vol10, i)
    v20 = _last_valid(vol20, i)
    detail = {
        "ma20": m20,
        "ma60": m60,
        "vol10": v10,
        "vol20": v20,
    }

    prev = float(closes[i - 1]) if closes[i - 1] else 0.0
    if prev > 0 and (price - prev) / prev >= float(CHASE_MAX_PCT):
        return False, ["chase_skip"], detail

    # 无量阴跌不言底：跌破 MA20 且量 < 20 日均量 * 0.7 → 全局禁开
    dry_below = (
        m20 is not None
        and price < m20
        and v20 is not None
        and v20 > 0
        and vol < v20 * float(VOL_DRY_RATIO)
    )
    if dry_below:
        return False, ["vol_dry_skip"], detail

    # 缩量回踩 MA20/MA60 + 量 < 10 日均量 * 0.9
    near = _near_ma(price, m20) or _near_ma(price, m60)
    shrink = v10 is not None and v10 > 0 and vol < v10 * float(VOL_PULLBACK_RATIO)
    if near and shrink:
        reasons.append("pullback_vol")

    return bool(reasons), reasons, detail


def _weekly_bias_guard(w_detail):
    """周线 (MA5-MA30)/MA30 >= W_BIAS_HARD → 禁开。"""
    m5 = w_detail.get("ma5")
    m30 = w_detail.get("ma30")
    if m5 is None or m30 is None or m30 <= 0:
        return False, None
    bias = (float(m5) - float(m30)) / float(m30)
    return bias >= float(W_BIAS_HARD), bias


def _weekly_low_slope_guard(w_detail):
    """低位 (MA5-MA30)/MA30 < W_BIAS_LOW 且 MA30 未连续 2 周向上 → 禁开。"""
    m5 = w_detail.get("ma5")
    m30 = w_detail.get("ma30")
    if m5 is None or m30 is None or m30 <= 0:
        return False, None
    bias = (float(m5) - float(m30)) / float(m30)
    if bias >= float(W_BIAS_LOW):
        return False, bias
    slope_ok = bool(w_detail.get("ma30_slope_up2"))
    return (not slope_ok), bias


def _update_hold_peak(high_px, cost):
    """持仓期跟踪最高价（移动止盈用）。"""
    hi = float(high_px)
    peak = getattr(A, "hold_peak", None)
    if peak is None:
        base = float(cost) if cost and cost > 0 else hi
        A.hold_peak = max(base, hi)
        return True
    if hi > float(peak):
        A.hold_peak = hi
        return True
    return False


def _trail_stop_hit(price, cost):
    """曾浮盈 >= TRAIL_ACTIVATE 且自峰值回撤 > TRAIL_GIVEBACK。"""
    if cost is None or cost <= 0:
        return False
    peak = getattr(A, "hold_peak", None)
    if peak is None or peak <= 0:
        return False
    max_profit = (float(peak) - float(cost)) / float(cost)
    giveback = (float(peak) - float(price)) / float(peak)
    return (max_profit >= float(TRAIL_ACTIVATE)) and (giveback > float(TRAIL_GIVEBACK))


def _time_force_hit(price, closes, hold_bars):
    """智能时间成本：持仓 > TIME_FORCE_BARS 后，破日线 MA60 强制平仓；
    仍站上 MA60 则豁免一次并再观察 TIME_FORCE_GRACE_BARS 日，期满强制平仓。"""
    if hold_bars is None or int(hold_bars) <= int(TIME_FORCE_BARS):
        return False
    ma60_arr = _sma(closes, D_MA_SLOW)
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

    # 站上 MA60：豁免一次，多观察 GRACE 日；期满仍强制平仓
    grace_until = getattr(A, "time_force_grace_until", None)
    if grace_until is None:
        until = int(hold_bars) + int(TIME_FORCE_GRACE_BARS)
        A.time_force_grace_until = until
        print(
            "%s time_force grace ma60=%.4f hold=%s until_bars=%s"
            % (STRATEGY_NAME, m60, hold_bars, until)
        )
        return False
    return int(hold_bars) > int(grace_until)


def _clear_hold_meta():
    A.hold_peak = None
    A.hold_bars = 0
    A._hold_count_day = ""
    A.time_force_grace_until = None


def _bump_hold_bars(day):
    """每个交易日持仓计 1 根。"""
    if getattr(A, "_hold_count_day", "") == day:
        return
    A.hold_bars = int(getattr(A, "hold_bars", 0) or 0) + 1
    A._hold_count_day = day


def _drop_forming_bar(seq):
    """去掉正在形成的最新一根（实盘未收盘 K）。"""
    if seq is None:
        return None
    if len(seq) < 2:
        return list(seq) if seq else seq
    return list(seq[:-1])


def _live_close_confirm_on():
    return (not getattr(A, "is_backtest", False)) and bool(
        globals().get("LIVE_CLOSE_CONFIRM", True)
    )


def _live_signal_day(today):
    """开盘兜底挂起用的信号日：墙钟昨日历日，保证 signal_day < 今日可成交。"""
    try:
        d = datetime.datetime.strptime(str(today), "%Y%m%d") - datetime.timedelta(
            days=1
        )
        return d.strftime("%Y%m%d")
    except Exception:
        return str(today)


def _mark_confirmed_eval(day):
    A._confirmed_eval_day = str(day)
    _save_state()


def _pending_ready(pend, day, bar_tag, mode):
    if not isinstance(pend, dict):
        return False
    sig_tag = str(pend.get("signal_tag", "") or "")
    sig_day = str(pend.get("signal_day", "") or "")
    if mode == "day":
        return bool(sig_day) and sig_day < day
    if sig_tag and bar_tag:
        return sig_tag < bar_tag
    if sig_day and sig_day < day:
        return True
    return False


_SELL_LABELS = {
    "trail_stop": "卖点1-移动止盈回撤",
    "time_force": "卖点2-时间成本智能平仓",
    "weekly_bear": "周线转空强制清仓",
    "stop_loss": "硬止损",
}
_BUY_LABELS = {
    "pullback_vol": "买点1-缩量回踩强支撑",
    "chase_skip": "追高过滤跳过",
    "w_bias_skip": "周线高位乖离禁开",
    "w_slope_skip": "低位周线MA30未连升禁开",
    "vol_dry_skip": "无量阴跌禁开",
}


def _reason_label(code, kind="sell"):
    code = str(code or "")
    table = _SELL_LABELS if kind == "sell" else _BUY_LABELS
    return table.get(code, code)


def _format_reasons(codes, kind="sell"):
    codes = [str(x) for x in (codes or []) if x]
    if not codes:
        return "-"
    parts = ["%s(%s)" % (c, _reason_label(c, kind)) for c in codes]
    return ",".join(parts)


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    day = now.strftime("%Y%m%d")
    tag = _bar_tag(bar_dt)
    hhmm = _bar_hhmm(bar_dt if bt else now)
    live_cc = _live_close_confirm_on()
    conf_start = str(globals().get("SIGNAL_CONFIRM_START", "150000") or "150000")
    conf_end = str(globals().get("SIGNAL_CONFIRM_END", "160000") or "160000")
    in_exec = (not bt) and (DECISION_START <= now_s < conf_start)
    in_confirm = (not bt) and (conf_start <= now_s <= conf_end)
    # 收盘确认：用当日完整 K；开盘兜底：用昨收（去未收盘根）
    use_prev_bar = False
    phase = "bt" if bt else "live"

    if not bt:
        if getattr(A, "pending", None):
            if _process_pending(C, now):
                _live_heartbeat("pending")
                return
        if live_cc:
            if (not in_exec) and (not in_confirm):
                _live_heartbeat("outside_session")
                return
            phase = "confirm" if in_confirm else "exec"
        else:
            if now_s < DECISION_START or now_s > DECISION_END:
                _live_heartbeat("outside_session")
                return
            phase = "session"
        if LIVE_ONLY_LAST_BAR:
            try:
                if hasattr(C, "is_last_bar") and (not C.is_last_bar()):
                    return
            except Exception:
                pass
        _live_heartbeat(phase)
    else:
        _bt_roll_t1(day)
        _bt_recover_position(now=now)

    _reset_day(day)

    cash = _available_cash()
    if cash is None:
        _live_heartbeat("no_cash_or_login")
        return

    ohlcv_d = _get_ohlcv_1d(C, A.stock)
    if ohlcv_d is None:
        _live_heartbeat("ohlcv_1d_none")
        return
    opens_d, highs_d, lows_d, closes_d, vols_d = ohlcv_d

    ohlcv_w = _get_ohlcv_1w(C, A.stock)
    if ohlcv_w is None:
        _live_heartbeat("ohlcv_1w_none")
        return
    _ow, _hw, _lw, closes_w, _vw = ohlcv_w

    open_px = float(opens_d[-1])
    # 开盘兜底：仅当完全没有确认记录且无挂起（收盘窗口未跑到）
    need_fallback = (
        live_cc
        and phase == "exec"
        and (not str(getattr(A, "_confirmed_eval_day", "") or ""))
        and (not isinstance(getattr(A, "pending_entry", None), dict))
        and (not isinstance(getattr(A, "pending_exit", None), dict))
    )
    if live_cc and phase == "confirm":
        highs_s, closes_s, vols_s = highs_d, closes_d, vols_d
        closes_ws = closes_w
        sig_day = day
    elif need_fallback:
        use_prev_bar = True
        highs_s = _drop_forming_bar(highs_d)
        closes_s = _drop_forming_bar(closes_d)
        vols_s = _drop_forming_bar(vols_d)
        closes_ws = _drop_forming_bar(closes_w)
        if closes_s is None or len(closes_s) < 3 or closes_ws is None or len(closes_ws) < 3:
            _live_heartbeat("ohlcv_confirm_short")
            return
        sig_day = _live_signal_day(day)
    else:
        # 回测 / 盘中执行：信号评估用完整序列（盘中不新挂，仅供撤单校验与日志）
        highs_s, closes_s, vols_s = highs_d, closes_d, vols_d
        closes_ws = closes_w
        sig_day = day

    price = float(closes_s[-1])
    high_px = float(highs_s[-1])
    if bt:
        _bt_recover_position(now=now, last=float(closes_d[-1]))

    weekly_bull, weekly_bear, w_detail = _eval_weekly(closes_ws)
    w_bias_block, w_bias = _weekly_bias_guard(w_detail)
    w_slope_block, _w_bias_low = _weekly_low_slope_guard(w_detail)
    buy_ok, buy_reasons, b_detail = _eval_daily_buy(closes_s, vols_s)
    if w_bias_block:
        buy_ok = False
        buy_reasons = ["w_bias_skip"] + [
            r for r in buy_reasons if r not in ("w_bias_skip",)
        ]
    elif w_slope_block:
        buy_ok = False
        buy_reasons = ["w_slope_skip"] + [
            r for r in buy_reasons if r not in ("w_slope_skip",)
        ]
    sell_ok = False
    sell_reasons = []

    holding = _has_position() or (bt and _bt_held_vol() >= 100)
    cost = _pos_cost_price()
    if not holding:
        if (
            getattr(A, "hold_peak", None) is not None
            or int(getattr(A, "hold_bars", 0) or 0)
            or getattr(A, "time_force_grace_until", None) is not None
        ):
            _clear_hold_meta()
    else:
        _bump_hold_bars(day)
        if _update_hold_peak(high_px, cost):
            _save_state()

    stop_hit = False
    if holding and cost > 0 and price <= cost * (1.0 - float(STOP_LOSS)):
        stop_hit = True
        sell_reasons = list(sell_reasons) + ["stop_loss"]
        sell_ok = True

    trail_hit = False
    if holding and (not stop_hit) and _trail_stop_hit(price, cost):
        trail_hit = True
        sell_reasons = list(sell_reasons) + ["trail_stop"]
        sell_ok = True

    ret_pct = None
    if holding and cost > 0:
        ret_pct = (price - cost) / cost

    time_force_hit = False
    grace_before = getattr(A, "time_force_grace_until", None)
    if holding and (not stop_hit) and (not trail_hit) and _time_force_hit(
        price, closes_s, getattr(A, "hold_bars", 0)
    ):
        time_force_hit = True
        sell_reasons = list(sell_reasons) + ["time_force"]
        sell_ok = True
    elif (
        holding
        and grace_before is None
        and getattr(A, "time_force_grace_until", None) is not None
    ):
        _save_state()

    skip_codes = ("chase_skip", "w_bias_skip", "w_slope_skip", "vol_dry_skip")
    real_buys = [r for r in buy_reasons if r not in skip_codes]
    buy_sig = bool(
        (not w_bias_block) and (not w_slope_block) and buy_ok and real_buys
    )
    force_empty = bool(weekly_bear)
    vol_dry_block = "vol_dry_skip" in buy_reasons

    interesting = (
        buy_sig
        or sell_ok
        or force_empty
        or holding
        or bool(getattr(A, "pending_entry", None) or getattr(A, "pending_exit", None))
    )
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 20 == 0):
        A.ready_logged = True
        print(
            "%s" % STRATEGY_NAME,
            day,
            hhmm,
            "n1d=%d n1w=%d close=%.4f sig_day=%s phase=%s prev=%s "
            "w_bull=%s w_bear=%s w_ma5=%s w_ma30=%s w_hist=%s "
            "buy=%s buyR=%s sell=%s sellR=%s "
            "hold=%s ret=%s pe=%s px=%s bt_held=%s avail=%s"
            % (
                len(closes_s),
                len(closes_ws),
                price,
                sig_day,
                phase,
                use_prev_bar,
                weekly_bull,
                weekly_bear,
                None if w_detail.get("ma5") is None else round(w_detail["ma5"], 4),
                None if w_detail.get("ma30") is None else round(w_detail["ma30"], 4),
                None if w_detail.get("hist") is None else round(w_detail["hist"], 4),
                buy_sig,
                ",".join(buy_reasons) if buy_reasons else "-",
                sell_ok or force_empty,
                ",".join((["weekly_bear"] if force_empty else []) + sell_reasons) or "-",
                holding,
                None if ret_pct is None else ("%.2f%%" % (ret_pct * 100.0)),
                bool(getattr(A, "pending_entry", None)),
                bool(getattr(A, "pending_exit", None)),
                _bt_held_vol() if bt else "-",
                _bt_available_vol() if bt else "-",
            ),
        )

    # ---- 先执行挂起的卖/买（开盘时段）----
    pe_exit = getattr(A, "pending_exit", None)
    if holding and isinstance(pe_exit, dict):
        if _pending_ready(pe_exit, day, tag, "day"):
            reason = str(pe_exit.get("reason", "SELL") or "SELL")
            reasons = pe_exit.get("reasons") or [reason]
            print(
                "%s SELL by signal=%s label=%s all=%s signal_day=%s @open=%.4f"
                % (
                    STRATEGY_NAME,
                    reason,
                    _reason_label(reason, "sell"),
                    _format_reasons(reasons, "sell"),
                    pe_exit.get("signal_day"),
                    open_px,
                )
            )
            ok = _order_sell(C, reason, open_px, now)
            A.pending_exit = None
            A.pending_entry = None
            _clear_hold_meta()
            _save_state()
            if not ok:
                print("%s pending_exit cleared after sell fail/skip" % STRATEGY_NAME)
            return

    pe_entry = getattr(A, "pending_entry", None)
    if (
        (not holding)
        and isinstance(pe_entry, dict)
        and ("BUY" not in getattr(A, "acted", set()))
        and _pending_ready(pe_entry, day, tag, "day")
    ):
        if weekly_bear or w_bias_block or w_slope_block or vol_dry_block:
            A.pending_entry = None
            _save_state()
            if weekly_bear:
                why = "weekly_bear"
            elif w_bias_block:
                why = "w_bias_skip"
            elif w_slope_block:
                why = "w_slope_skip"
            else:
                why = "vol_dry_skip"
            print("%s pending_entry cancel %s" % (STRATEGY_NAME, why))
            return
        reasons = pe_entry.get("reasons") or []
        primary = reasons[0] if reasons else "entry"
        print(
            "%s BUY by signal=%s label=%s all=%s signal_day=%s @open=%.4f"
            % (
                STRATEGY_NAME,
                primary,
                _reason_label(primary, "buy"),
                _format_reasons(reasons, "buy"),
                pe_entry.get("signal_day"),
                open_px,
            )
        )
        budget = _buy_budget(cash)
        ok = _order_buy(C, open_px, now, budget)
        A.pending_entry = None
        A.pending_exit = None
        if ok:
            A.hold_peak = float(open_px)
            A.hold_bars = 0
            A._hold_count_day = day
            A.time_force_grace_until = None
        _save_state()
        if not ok:
            print("%s pending_entry cleared after buy fail/skip" % STRATEGY_NAME)
        return

    # ---- 新信号：回测当根；实盘仅收盘确认或开盘兜底 ----
    allow_new = True
    if live_cc:
        if phase == "confirm":
            if getattr(A, "_confirmed_eval_day", "") == day:
                allow_new = False
        elif need_fallback:
            allow_new = True
        else:
            allow_new = False
    if not allow_new:
        return

    if holding:
        cur_ex = getattr(A, "pending_exit", None)
        if force_empty or sell_ok or stop_hit or trail_hit or time_force_hit:
            if isinstance(cur_ex, dict):
                if live_cc:
                    _mark_confirmed_eval(day)
                return
            if force_empty:
                reason = "weekly_bear"
            elif stop_hit:
                reason = "stop_loss"
            elif trail_hit:
                reason = "trail_stop"
            elif time_force_hit:
                reason = "time_force"
            else:
                reason = sell_reasons[0] if sell_reasons else "SELL"
            reasons = (["weekly_bear"] if force_empty else []) + list(sell_reasons)
            seen = set()
            uniq = []
            for r in reasons:
                if r not in seen:
                    seen.add(r)
                    uniq.append(r)
            A.pending_exit = {
                "mode": "day",
                "reason": reason,
                "signal_day": sig_day,
                "signal_tag": tag,
                "close": price,
                "reasons": uniq,
            }
            A.pending_entry = None
            if live_cc:
                A._confirmed_eval_day = day
            _save_state()
            print(
                "%s pending_exit set signal=%s label=%s all=%s day=%s close=%.4f phase=%s"
                % (
                    STRATEGY_NAME,
                    reason,
                    _reason_label(reason, "sell"),
                    _format_reasons(uniq, "sell"),
                    sig_day,
                    price,
                    phase,
                )
            )
        elif live_cc:
            _mark_confirmed_eval(day)
        return

    if buy_sig and ("BUY" not in getattr(A, "acted", set())):
        if isinstance(getattr(A, "pending_entry", None), dict):
            if live_cc:
                _mark_confirmed_eval(day)
            return
        A.pending_entry = {
            "signal_day": sig_day,
            "signal_tag": tag,
            "close": price,
            "reasons": list(real_buys),
        }
        A.pending_exit = None
        if live_cc:
            A._confirmed_eval_day = day
        _save_state()
        primary = real_buys[0] if real_buys else "entry"
        print(
            "%s pending_entry set signal=%s label=%s all=%s day=%s close=%.4f phase=%s"
            % (
                STRATEGY_NAME,
                primary,
                _reason_label(primary, "buy"),
                _format_reasons(real_buys, "buy"),
                sig_day,
                price,
                phase,
            )
        )
    elif live_cc:
        _mark_confirmed_eval(day)
