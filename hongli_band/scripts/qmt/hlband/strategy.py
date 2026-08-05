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
    """周线多头前提下: 买①缩量回踩 OR 买②零轴上二次金叉 OR 买③KDJ超卖拐头。"""
    reasons = []
    ma20 = _sma(closes, D_MA_MID)
    ma60 = _sma(closes, D_MA_SLOW)
    vol_ma = _sma(volumes, VOL_MA_N)
    macd = _calc_macd(closes)
    kdj = _calc_kdj(highs, lows, closes)
    if ma20 is None or ma60 is None or vol_ma is None or macd is None or kdj is None:
        return False, reasons, {}
    i = len(closes) - 1
    if i < 2:
        return False, reasons, {}
    price = float(closes[i])
    open_px = float(opens[i])
    vol = float(volumes[i])
    m20 = _last_valid(ma20, i)
    m60 = _last_valid(ma60, i)
    vma = _last_valid(vol_ma, i)
    dif, dea, hist = macd
    d0 = _last_valid(dif, i)
    e0 = _last_valid(dea, i)
    d1 = _last_valid(dif, i - 1)
    e1 = _last_valid(dea, i - 1)
    _k, _d, j_arr = kdj
    j0 = _last_valid(j_arr, i)
    j1 = _last_valid(j_arr, i - 1)
    detail = {
        "ma20": m20,
        "ma60": m60,
        "vol_ma": vma,
        "dif": d0,
        "dea": e0,
        "j": j0,
    }

    # 风控: 不追高
    prev = float(closes[i - 1]) if closes[i - 1] else 0.0
    if prev > 0 and (price - prev) / prev >= float(CHASE_MAX_PCT):
        return False, ["chase_skip"], detail

    # 买① 缩量回踩 20/60
    near = _near_ma(price, m20) or _near_ma(price, m60)
    shrink = (vma is not None and vma > 0 and vol <= vma * float(VOL_SHRINK_RATIO))
    if near and shrink:
        reasons.append("pullback_vol")

    # 买② 零轴上二次金叉
    if (
        d0 is not None
        and e0 is not None
        and d0 > 0
        and e0 > 0
        and _cross_up(d1, e1, d0, e0)
    ):
        reasons.append("macd_2nd_gc")

    # 买③ KDJ J<0 后拐头 + 止跌阳线
    if (
        j0 is not None
        and j1 is not None
        and j1 < 0
        and j0 > j1
        and price > open_px
    ):
        reasons.append("kdj_os")

    return bool(reasons), reasons, detail


def _eval_daily_sell(opens, highs, lows, closes, volumes):
    """卖①乖离 OR 卖②放量滞涨 OR 卖③动能死叉/柱缩短背离。"""
    reasons = []
    ma5 = _sma(closes, D_MA_FAST)
    vol_ma = _sma(volumes, VOL_MA_N)
    macd = _calc_macd(closes)
    if ma5 is None or vol_ma is None or macd is None:
        return False, reasons, {}
    i = len(closes) - 1
    if i < 2:
        return False, reasons, {}
    o, h, l, c = float(opens[i]), float(highs[i]), float(lows[i]), float(closes[i])
    vol = float(volumes[i])
    m5 = _last_valid(ma5, i)
    vma = _last_valid(vol_ma, i)
    bias = _bias_pct(c, m5)
    body_r, upper_r, _yang = _candle_metrics(o, h, l, c)
    look = int(HIGH_LOOKBACK)
    prior = closes[max(0, i - look) : i]
    is_new_high = bool(prior) and c >= float(np.max(prior))
    detail = {"bias5": bias, "vol_ma": vma, "new_high": is_new_high}

    if bias is not None and bias >= float(BIAS5_SELL):
        reasons.append("bias5")

    spike = vma is not None and vma > 0 and vol >= vma * float(VOL_SPIKE_RATIO)
    stagnate = (upper_r >= float(UPPER_SHADOW_RATIO)) or (body_r <= float(DOJI_BODY_RATIO))
    if is_new_high and spike and stagnate:
        reasons.append("vol_stagnate")

    dif, dea, hist = macd
    d0 = _last_valid(dif, i)
    e0 = _last_valid(dea, i)
    d1 = _last_valid(dif, i - 1)
    e1 = _last_valid(dea, i - 1)
    h0 = _last_valid(hist, i)
    h1 = _last_valid(hist, i - 1)
    if _cross_down(d1, e1, d0, e0) and d0 is not None and d0 > 0:
        reasons.append("macd_death")
    elif (
        is_new_high
        and h0 is not None
        and h1 is not None
        and h0 > 0
        and h0 < h1
    ):
        reasons.append("macd_div")

    return bool(reasons), reasons, detail


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


# 卖出/买入原因码 -> 可读说明（对齐 model.md）
_SELL_LABELS = {
    "bias5": "卖点1-5日乖离过大",
    "vol_stagnate": "卖点2-放量滞涨",
    "macd_death": "卖点3-MACD死叉",
    "macd_div": "卖点3-MACD红柱背离",
    "weekly_bear": "周线转空强制清仓",
    "stop_loss": "硬止损",
}
_BUY_LABELS = {
    "pullback_vol": "买点1-缩量回踩",
    "macd_2nd_gc": "买点2-零轴上二次金叉",
    "kdj_os": "买点3-KDJ超卖拐头",
    "chase_skip": "追高过滤跳过",
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
    if bt:
        _bt_recover_position(now=now, last=price)

    weekly_bull, weekly_bear, w_detail = _eval_weekly(closes_w)
    buy_ok, buy_reasons, b_detail = _eval_daily_buy(
        opens_d, highs_d, lows_d, closes_d, vols_d
    )
    sell_ok, sell_reasons, s_detail = _eval_daily_sell(
        opens_d, highs_d, lows_d, closes_d, vols_d
    )

    holding = _has_position() or (bt and _bt_held_vol() >= 100)
    cost = _pos_cost_price()
    stop_hit = False
    if holding and cost > 0 and price <= cost * (1.0 - float(STOP_LOSS)):
        stop_hit = True
        sell_reasons = list(sell_reasons) + ["stop_loss"]
        sell_ok = True

    ret_pct = None
    if holding and cost > 0:
        ret_pct = (price - cost) / cost

    buy_sig = bool(weekly_bull and buy_ok and buy_reasons and "chase_skip" not in buy_reasons)
    force_empty = bool(weekly_bear)

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
        # 周线已转空则取消待买
        if weekly_bear:
            A.pending_entry = None
            _save_state()
            print("%s pending_entry cancel weekly_bear" % STRATEGY_NAME)
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
        # 成功或手数不足等都清 pending_entry，避免长期 pe=True
        A.pending_entry = None
        A.pending_exit = None
        _save_state()
        if not ok:
            print("%s pending_entry cleared after buy fail/skip" % STRATEGY_NAME)
        return

    # ---- 评估新信号（收盘确认 → 次日开盘）----
    if holding:
        cur_ex = getattr(A, "pending_exit", None)
        if force_empty or sell_ok or stop_hit:
            if isinstance(cur_ex, dict):
                return
            reason = "weekly_bear" if force_empty else (
                sell_reasons[0] if sell_reasons else "SELL"
            )
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
            "reasons": list(buy_reasons),
        }
        A.pending_exit = None
        _save_state()
        primary = buy_reasons[0] if buy_reasons else "entry"
        print(
            "%s pending_entry set signal=%s label=%s all=%s day=%s close=%.4f"
            % (
                STRATEGY_NAME,
                primary,
                _reason_label(primary, "buy"),
                _format_reasons(buy_reasons, "buy"),
                day,
                price,
            )
        )
