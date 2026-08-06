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


def _cross_up(a_prev, b_prev, a_now, b_now):
    if None in (a_prev, b_prev, a_now, b_now):
        return False
    return (a_prev <= b_prev) and (a_now > b_now)


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
    detail.update(
        {
            "ma5": m5,
            "ma10": m10,
            "ma30": m30,
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


def _eval_daily_buy(opens, highs, lows, closes, volumes):
    """买①缩量回踩 MA20/60；买② MA20 上方 KDJ 超卖。"""
    reasons = []
    ma20 = _sma(closes, D_MA_MID)
    ma60 = _sma(closes, D_MA_SLOW)
    vol10 = _sma(volumes, VOL_PULLBACK_N)
    vol20 = _sma(volumes, VOL_DRY_N)
    kdj = _calc_kdj(highs, lows, closes)
    if ma20 is None or ma60 is None or vol10 is None or vol20 is None or kdj is None:
        return False, reasons, {}
    i = len(closes) - 1
    if i < 2:
        return False, reasons, {}
    price = float(closes[i])
    open_px = float(opens[i])
    vol = float(volumes[i])
    m20 = _last_valid(ma20, i)
    m60 = _last_valid(ma60, i)
    v10 = _last_valid(vol10, i)
    v20 = _last_valid(vol20, i)
    _k, _d, j_arr = kdj
    j0 = _last_valid(j_arr, i)
    j1 = _last_valid(j_arr, i - 1)
    detail = {
        "ma20": m20,
        "ma60": m60,
        "vol10": v10,
        "vol20": v20,
        "j": j0,
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

    # 买①：回踩 MA20/MA60 + 量 < 10 日均量 * 0.9
    near = _near_ma(price, m20) or _near_ma(price, m60)
    shrink = v10 is not None and v10 > 0 and vol < v10 * float(VOL_PULLBACK_RATIO)
    if near and shrink:
        reasons.append("pullback_vol")

    # 买②：KDJ 超卖拐头，且收盘仍站上 MA20
    if (
        j0 is not None
        and j1 is not None
        and j1 < 0
        and j0 > j1
        and price > open_px
        and m20 is not None
        and price >= m20
    ):
        reasons.append("kdj_os")

    return bool(reasons), reasons, detail


def _eval_daily_sell(opens, highs, lows, closes, volumes):
    """卖① BIAS5 过大（放量滞涨/MACD 卖点已按 v1.5 规则移除）。"""
    reasons = []
    ma5 = _sma(closes, D_MA_FAST)
    if ma5 is None:
        return False, reasons, {}
    i = len(closes) - 1
    if i < 1:
        return False, reasons, {}
    c = float(closes[i])
    m5 = _last_valid(ma5, i)
    bias = _bias_pct(c, m5)
    detail = {"bias5": bias}
    if bias is not None and bias >= float(BIAS5_SELL):
        reasons.append("bias5")
    return bool(reasons), reasons, detail


def _weekly_bias_guard(w_detail):
    """周线 (MA5-MA30)/MA30 >= W_BIAS_HARD → 禁开。"""
    m5 = w_detail.get("ma5")
    m30 = w_detail.get("ma30")
    if m5 is None or m30 is None or m30 <= 0:
        return False, None
    bias = (float(m5) - float(m30)) / float(m30)
    return bias >= float(W_BIAS_HARD), bias


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


def _time_flat_hit(ret_pct, hold_bars):
    """持仓 >= TIME_FLAT_BARS 且盈亏落在 ±TIME_FLAT_BAND 内。"""
    if hold_bars is None or int(hold_bars) < int(TIME_FLAT_BARS):
        return False
    if ret_pct is None:
        return False
    return abs(float(ret_pct)) <= float(TIME_FLAT_BAND)


def _bump_hold_bars(day):
    """每个交易日持仓计 1 根。"""
    if getattr(A, "_hold_count_day", "") == day:
        return
    A.hold_bars = int(getattr(A, "hold_bars", 0) or 0) + 1
    A._hold_count_day = day


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
    "bias5": "卖点1-5日乖离过大",
    "trail_stop": "卖点2-移动止盈回撤",
    "time_flat": "卖点3-时间成本止损",
    "weekly_bear": "周线转空强制清仓",
    "stop_loss": "硬止损",
}
_BUY_LABELS = {
    "pullback_vol": "买点1-缩量回踩强支撑",
    "kdj_os": "买点2-MA20上KDJ超卖",
    "chase_skip": "追高过滤跳过",
    "w_bias_skip": "周线高位乖离禁开",
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

    price = float(closes_d[-1])
    open_px = float(opens_d[-1])
    high_px = float(highs_d[-1])
    if bt:
        _bt_recover_position(now=now, last=price)

    weekly_bull, weekly_bear, w_detail = _eval_weekly(closes_w)
    w_bias_block, w_bias = _weekly_bias_guard(w_detail)
    buy_ok, buy_reasons, b_detail = _eval_daily_buy(
        opens_d, highs_d, lows_d, closes_d, vols_d
    )
    if w_bias_block:
        buy_ok = False
        buy_reasons = ["w_bias_skip"] + [
            r for r in buy_reasons if r not in ("w_bias_skip",)
        ]
    sell_ok, sell_reasons, s_detail = _eval_daily_sell(
        opens_d, highs_d, lows_d, closes_d, vols_d
    )

    holding = _has_position() or (bt and _bt_held_vol() >= 100)
    cost = _pos_cost_price()
    if not holding:
        if getattr(A, "hold_peak", None) is not None or int(getattr(A, "hold_bars", 0) or 0):
            A.hold_peak = None
            A.hold_bars = 0
            A._hold_count_day = ""
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

    time_flat_hit = False
    if holding and (not stop_hit) and (not trail_hit) and _time_flat_hit(
        ret_pct, getattr(A, "hold_bars", 0)
    ):
        time_flat_hit = True
        sell_reasons = list(sell_reasons) + ["time_flat"]
        sell_ok = True

    skip_codes = ("chase_skip", "w_bias_skip", "vol_dry_skip")
    real_buys = [r for r in buy_reasons if r not in skip_codes]
    # v1.5：周线仅用乖离门控，不再要求旧版 weekly_bull
    buy_sig = bool((not w_bias_block) and buy_ok and real_buys)
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
            "n1d=%d n1w=%d close=%.4f "
            "w_bull=%s w_bear=%s w_ma5=%s w_ma30=%s w_hist=%s "
            "buy=%s buyR=%s sell=%s sellR=%s "
            "hold=%s ret=%s pe=%s px=%s bt_held=%s avail=%s"
            % (
                len(closes_d),
                len(closes_w),
                price,
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

    # ---- 先执行挂起的卖/买（本根开盘）----
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
            # 成交或提交后清掉信号挂起，避免 pe/px 粘滞
            A.pending_exit = None
            A.pending_entry = None
            A.hold_peak = None
            A.hold_bars = 0
            A._hold_count_day = ""
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
        # 执行日再校验：周线空头 / 高位乖离 / 无量阴跌
        if weekly_bear or w_bias_block or vol_dry_block:
            A.pending_entry = None
            _save_state()
            if weekly_bear:
                why = "weekly_bear"
            elif w_bias_block:
                why = "w_bias_skip"
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
        _save_state()
        if not ok:
            print("%s pending_entry cleared after buy fail/skip" % STRATEGY_NAME)
        return

    # ---- 评估新信号（收盘确认 → 次日开盘）----
    if holding:
        cur_ex = getattr(A, "pending_exit", None)
        if force_empty or sell_ok or stop_hit or trail_hit or time_flat_hit:
            if isinstance(cur_ex, dict):
                return
            if force_empty:
                reason = "weekly_bear"
            elif stop_hit:
                reason = "stop_loss"
            elif trail_hit:
                reason = "trail_stop"
            elif time_flat_hit:
                reason = "time_flat"
            else:
                reason = sell_reasons[0] if sell_reasons else "SELL"
            reasons = (["weekly_bear"] if force_empty else []) + list(sell_reasons)
            # 去重保序
            seen = set()
            uniq = []
            for r in reasons:
                if r not in seen:
                    seen.add(r)
                    uniq.append(r)
            A.pending_exit = {
                "mode": "day",
                "reason": reason,
                "signal_day": day,
                "signal_tag": tag,
                "close": price,
                "reasons": uniq,
            }
            A.pending_entry = None
            _save_state()
            print(
                "%s pending_exit set signal=%s label=%s all=%s day=%s close=%.4f"
                % (
                    STRATEGY_NAME,
                    reason,
                    _reason_label(reason, "sell"),
                    _format_reasons(uniq, "sell"),
                    day,
                    price,
                )
            )
        return

    if buy_sig and ("BUY" not in getattr(A, "acted", set())):
        if isinstance(getattr(A, "pending_entry", None), dict):
            return
        A.pending_entry = {
            "signal_day": day,
            "signal_tag": tag,
            "close": price,
            "reasons": list(real_buys),
        }
        A.pending_exit = None
        _save_state()
        primary = real_buys[0] if real_buys else "entry"
        print(
            "%s pending_entry set signal=%s label=%s all=%s day=%s close=%.4f"
            % (
                STRATEGY_NAME,
                primary,
                _reason_label(primary, "buy"),
                _format_reasons(real_buys, "buy"),
                day,
                price,
            )
        )
