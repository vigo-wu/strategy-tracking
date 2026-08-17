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
    slope_weeks = int(globals().get("W_MA30_SLOPE_WEEKS", 2) or 2)
    slope_up_n = False
    if slope_weeks > 0 and i >= slope_weeks:
        slope_up_n = True
        for k in range(slope_weeks):
            a = _last_valid(ma30, i - k)
            b = _last_valid(ma30, i - k - 1)
            if a is None or b is None or not (a > b):
                slope_up_n = False
                break
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


def _w_bear_confirm_need():
    """最少 1：当天空头即可挂清仓；勿用 `x or 2`（0 会被当成缺省翻成 2）。"""
    raw = globals().get("W_BEAR_CONFIRM_DAYS", 2)
    try:
        n = int(2 if raw is None else raw)
    except Exception:
        n = 2
    return max(1, n)


def _update_w_bear_streak(weekly_bear, sig_day, track):
    """
    连续 N 个信号日仍周线空头才确认清仓。
    track=False（实盘盘中 exec）不改计数，避免半成品 K 抖动。
    返回 (force_empty, streak)。
    """
    need = _w_bear_confirm_need()
    sig_day = str(sig_day or "")
    streak = int(getattr(A, "_w_bear_streak", 0) or 0)
    last = str(getattr(A, "_w_bear_last_day", "") or "")
    if not track:
        return bool(weekly_bear) and streak >= need, streak
    if not sig_day:
        return False, streak

    prev_streak = streak
    prev_last = last
    changed = False

    if sig_day == last:
        # 同一信号日：confirm 窗内可能先空后翻多（或相反），须跟最终电平
        if weekly_bear:
            if streak <= 0:
                streak = 1
                changed = True
        else:
            if streak > 0:
                streak = 0
                changed = True
    elif weekly_bear:
        if streak > 0 and last and sig_day > last:
            streak = streak + 1
        else:
            streak = 1
        changed = True
    else:
        streak = 0
        changed = True

    A._w_bear_streak = int(streak)
    A._w_bear_last_day = sig_day
    if changed or (sig_day != prev_last):
        if not getattr(A, "is_backtest", False):
            _save_state()
        if weekly_bear and (streak != prev_streak or sig_day != prev_last):
            print(
                "%s w_bear streak=%d/%d day=%s"
                % (STRATEGY_NAME, streak, need, sig_day)
            )
            _event_log(
                "w_bear_streak",
                streak=streak,
                need=need,
                signal_day=sig_day,
            )
        elif (not weekly_bear) and prev_streak:
            print(
                "%s w_bear streak reset day=%s (was %d)"
                % (STRATEGY_NAME, sig_day, prev_streak)
            )
            _event_log(
                "w_bear_streak_reset",
                signal_day=sig_day,
                was=prev_streak,
            )
    return streak >= need, streak


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

    # 无量阴跌不言底：跌破 MA20 且量 < 20 日均量 * VOL_DRY_RATIO → 全局禁开
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


def _trail_tier_params(max_profit):
    """按峰值浮盈选档，返回 (giveback, profit_floor)；未达起步档则 (None, None)。"""
    mp = float(max_profit)
    for lo, hi, giveback, floor in TRAIL_TIERS:
        if mp < float(lo):
            continue
        if hi is not None and mp >= float(hi):
            continue
        fl = None if floor is None else float(floor)
        return float(giveback), fl
    return None, None


def _trail_stop_hit(price, cost, peak=None):
    """阶梯移动止盈：峰值浮盈落档后，回撤超容忍 或 跌破利润底线。"""
    if cost is None or cost <= 0:
        return False
    if peak is None:
        peak = getattr(A, "hold_peak", None)
    if peak is None or peak <= 0:
        return False
    max_profit = (float(peak) - float(cost)) / float(cost)
    giveback_lim, profit_floor = _trail_tier_params(max_profit)
    if giveback_lim is None:
        return False
    giveback = (float(peak) - float(price)) / float(peak)
    if giveback > giveback_lim:
        return True
    if profit_floor is not None:
        cur_profit = (float(price) - float(cost)) / float(cost)
        if cur_profit < profit_floor:
            return True
    return False


def _time_force_hit(price, closes, hold_bars, lot=None):
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

    if lot is None:
        grace_until = getattr(A, "time_force_grace_until", None)
    else:
        grace_until = lot.get("time_force_grace_until")
    if grace_until is None:
        until = int(hold_bars) + int(TIME_FORCE_GRACE_BARS)
        if lot is None:
            A.time_force_grace_until = until
        else:
            lot["time_force_grace_until"] = until
        print(
            "%s time_force grace ma60=%.4f hold=%s until_bars=%s lot=%s"
            % (STRATEGY_NAME, m60, hold_bars, until, None if lot is None else lot.get("id"))
        )
        _event_log(
            "time_force_grace",
            ma60=m60,
            hold_bars=hold_bars,
            until_bars=until,
            lot_id=None if lot is None else lot.get("id"),
        )
        _save_state()
        return False
    return int(hold_bars) > int(grace_until)


def _lot_from_agg():
    pos = getattr(A, "position", None) or {}
    px = float(pos.get("price", 0) or 0)
    peak = getattr(A, "hold_peak", None)
    if peak is None:
        peak = px
    cost = px if px > 0 else 0.0
    mx = 0.0
    if cost > 0 and peak is not None:
        mx = (float(peak) - cost) / cost
    return {
        "id": 1,
        "shares": int(pos.get("shares", 0) or 0),
        "price": px,
        "opened_at": str(pos.get("opened_at", "") or ""),
        "hold_peak": peak,
        "hold_close_peak": peak,
        "hold_max_ret": mx,
        "hold_bars": int(getattr(A, "hold_bars", 0) or 0),
        "hold_count_bar": str(getattr(A, "_hold_count_day", "") or ""),
        "time_force_grace_until": getattr(A, "time_force_grace_until", None),
    }


def _mirror_hold_from_lots():
    lots = getattr(A, "lots", None) or []
    if not lots:
        A.hold_peak = None
        A.hold_close_peak = None
        A.hold_max_ret = 0.0
        A.hold_bars = 0
        A._hold_count_bar = ""
        A._hold_count_day = ""
        A.time_force_grace_until = None
        return
    lot = lots[0]
    A.hold_peak = lot.get("hold_peak")
    A.hold_close_peak = lot.get("hold_close_peak")
    A.hold_max_ret = float(lot.get("hold_max_ret") or 0)
    A.hold_bars = int(lot.get("hold_bars") or 0)
    tag = str(lot.get("hold_count_bar") or "")
    A._hold_count_bar = tag
    A._hold_count_day = tag
    A.time_force_grace_until = lot.get("time_force_grace_until")


def _scale_ready():
    if not bool(globals().get("SCALE_ENABLE")):
        return False
    holding_now = _has_position() or (
        getattr(A, "is_backtest", False) and _bt_held_vol() >= 100
    )
    if not holding_now:
        return False
    if _pos_lots() >= int(globals().get("SCALE_MAX") or 1):
        return False
    mx = 0.0
    if _lots_enabled():
        for lot in _ensure_lots():
            try:
                mx = max(mx, float(lot.get("hold_max_ret") or 0))
            except Exception:
                pass
        if mx <= 0:
            peak = getattr(A, "hold_peak", None)
            cost = _pos_cost_price()
            if peak and cost > 0:
                mx = (float(peak) - float(cost)) / float(cost)
    else:
        peak = getattr(A, "hold_peak", None)
        cost = _pos_cost_price()
        if peak and cost > 0:
            mx = (float(peak) - float(cost)) / float(cost)
    arm = float(globals().get("SCALE_ARM") or 0)
    if arm <= 0:
        arm = 0.03
    return mx >= arm


def _eval_lot_sell(price, closes, lot):
    reasons = []
    cost = float(lot.get("price") or 0)
    if cost > 0 and price <= cost * (1.0 - float(STOP_LOSS)):
        reasons.append("stop_loss")
        return True, reasons
    if _trail_stop_hit(price, cost, peak=lot.get("hold_peak")):
        reasons.append("trail_stop")
        return True, reasons
    if _time_force_hit(price, closes, lot.get("hold_bars", 0), lot=lot):
        reasons.append("time_force")
        return True, reasons
    return False, reasons


def _collect_lot_exits(price, closes, force_empty):
    lots = _ensure_lots()
    if not lots:
        return False, [], [], 0
    if force_empty:
        lot_ids = [int(l.get("id") or 0) for l in lots]
        shares = sum(int(l.get("shares") or 0) for l in lots)
        return True, ["weekly_bear"], lot_ids, shares
    exits = []
    for lot in lots:
        ok, reasons = _eval_lot_sell(price, closes, lot)
        if ok:
            exits.append((lot, reasons))
    if not exits:
        return False, [], [], 0
    lot_ids = [int(item[0].get("id") or 0) for item in exits]
    shares = sum(int(item[0].get("shares") or 0) for item in exits)
    reasons = []
    for _lot, rs in exits:
        for r in rs:
            if r not in reasons:
                reasons.append(r)
    return True, reasons, lot_ids, shares


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


def _calendar_prev_weekday(yyyymmdd):
    """自然日回退到上一工作日（跳过周末；节假日以行情轴为准）。"""
    try:
        d = datetime.datetime.strptime(str(yyyymmdd), "%Y%m%d")
    except Exception:
        return str(yyyymmdd)
    d -= datetime.timedelta(days=1)
    while int(d.weekday()) >= 5:
        d -= datetime.timedelta(days=1)
    return d.strftime("%Y%m%d")


def _last_closed_bar_day(C, today):
    """上一根已收盘日线交易日；优先行情时间轴，否则跳过周末的自然日。"""
    today = str(today)
    days = None
    try:
        days = _get_daily_bar_days(C, A.stock, count=8)
    except Exception:
        days = None
    if days:
        last = str(days[-1])
        if last >= today and len(days) >= 2:
            return str(days[-2])
        if last and last < today:
            return last
    return _calendar_prev_weekday(today)


def _live_signal_day(C, today):
    """开盘兜底/盘中校验用的信号日：上一根已收盘交易日（保证 signal_day < 今日可成交）。"""
    return _last_closed_bar_day(C, today)


def _mark_confirmed_eval(day):
    """收盘确认完成（当日完整 K）。"""
    A._confirmed_eval_day = str(day)
    _save_state()


def _mark_fallback_done(day):
    """开盘兜底评估完成；不写 confirmed，以免挡住今日收盘确认。"""
    A._fallback_done_day = str(day)
    _save_state()


def _mark_signal_eval_done(day, is_confirm):
    if is_confirm:
        _mark_confirmed_eval(day)
    else:
        _mark_fallback_done(day)


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


def _in_pending_exec_window(now_s):
    """回测不限时；实盘仅开盘附近允许按开盘价成交信号 pending。"""
    if getattr(A, "is_backtest", False):
        return True
    start = str(globals().get("PENDING_EXEC_START", "093000") or "093000")
    end = str(globals().get("PENDING_EXEC_END", "094500") or "094500")
    return start <= str(now_s) < end


def _log_pending_defer_once(kind, day, now_s, signal_day):
    """开盘窗外 defer 每个交易日每种 pending 只打一次日志，避免盘中刷屏。"""
    kind = str(kind or "")
    day = str(day or "")
    attr = "_defer_log_%s_day" % kind
    if str(getattr(A, attr, "") or "") == day:
        return
    setattr(A, attr, day)
    print(
        "%s pending_%s defer outside open window now=%s signal_day=%s"
        % (STRATEGY_NAME, kind, now_s, signal_day)
    )
    _event_log(
        "pending_%s_defer" % kind,
        now=now_s,
        signal_day=signal_day,
        exec_end=str(globals().get("PENDING_EXEC_END", "094500") or "094500"),
    )


def _should_emit_bar_status(C, now, force, status_idle):
    """
    状态行是否输出。
    force（信号上升沿）立刻打；回测逐 bar 对 idle 不节流；
    实盘仅持仓/挂起、无新沿时按 LIVE_HEARTBEAT_SEC 节流。
    """
    if not getattr(A, "ready_logged", False):
        return True
    if force:
        return True
    if getattr(A, "is_backtest", False):
        if status_idle:
            return True
        try:
            return int(getattr(C, "barpos", 0) or 0) % 20 == 0
        except Exception:
            return False
    if status_idle:
        sec = int(globals().get("LIVE_HEARTBEAT_SEC") or 60)
        if sec <= 0:
            return True
        last = getattr(A, "_bar_status_at", None)
        if last is not None and now is not None:
            try:
                if (now - last).total_seconds() < float(sec):
                    return False
            except Exception:
                pass
        return True
    try:
        return int(getattr(C, "barpos", 0) or 0) % 20 == 0
    except Exception:
        return False


def _bar_signal_rising_edge(buy_sig, sell_ok, force_empty):
    """
    相对上一 tick 的买卖/强平上升沿。
    电平一直为真时不再强制打状态行（避免收盘确认窗刷屏）。
    """
    cur = (bool(buy_sig), bool(sell_ok), bool(force_empty))
    prev = getattr(A, "_bar_sig_prev", None)
    A._bar_sig_prev = cur
    if prev is None:
        return bool(cur[0] or cur[1] or cur[2])
    return (
        (cur[0] and not prev[0])
        or (cur[1] and not prev[1])
        or (cur[2] and not prev[2])
    )


def _after_signal_buy_filled(px, day, add=False):
    """买入成交后初始化持仓元数据并清信号 pending。"""
    A.pending_entry = None
    A.pending_exit = None
    if _lots_enabled():
        lots = getattr(A, "lots", None) or []
        if lots and day:
            lots[-1]["hold_count_bar"] = str(day)
            if not add:
                lots[-1]["hold_bars"] = 0
        _mirror_hold_from_lots()
        _save_state()
        return
    if not add:
        try:
            A.hold_peak = float(px) if px else None
        except Exception:
            A.hold_peak = None
        A.hold_bars = 0
        A._hold_count_day = str(day or "")
        A.time_force_grace_until = None
    _save_state()


def _after_signal_sell_filled():
    """卖出成交（或已空仓）后清信号 pending 与持仓元数据。"""
    A.pending_exit = None
    A.pending_entry = None
    A.lots = []
    _clear_hold_meta()
    _save_state()


def _finish_sell_fill():
    if _lots_enabled() and getattr(A, "lots", None):
        A.pending_exit = None
        acted = getattr(A, "acted", None)
        if isinstance(acted, set):
            acted.discard("SELL")
        _save_state()
        return
    _after_signal_sell_filled()


def _pending_on_buy_fill(pend, vol, px):
    """覆盖 common：成交后再清 pending_entry / 写 hold_meta（废单则保留信号 pending）。"""
    extra = pend.get("extra_pos") if isinstance(pend.get("extra_pos"), dict) else {}
    _apply_buy_fill(vol, px, pend.get("opened_at") or pend.get("submitted_at"), **extra)
    ot = str(pend.get("opened_at") or pend.get("submitted_at") or "")
    day = ot[:8] if len(ot) >= 8 else datetime.datetime.now().strftime("%Y%m%d")
    _after_signal_buy_filled(px, day, add=bool(extra.get("add")))


def _pending_on_sell_fill(pend, now, vol, px):
    """覆盖 common：成交后再清 pending_exit；部分成交仍持仓则保留 hold_meta。"""
    intent = str(pend.get("intent", "") or "")
    last_hint = pend.get("last_hint")
    if last_hint is None:
        last_hint = px
    mark_half = bool(pend.get("mark_half"))
    lot_ids = pend.get("lot_ids")
    if not lot_ids:
        pe = getattr(A, "pending_exit", None)
        if isinstance(pe, dict):
            lot_ids = pe.get("lot_ids")
    _apply_sell_fill(now, intent, last_hint, vol, mark_half=mark_half, lot_ids=lot_ids)
    _finish_sell_fill()


def _on_signal_order_ok(side, px=None, day=None, add=False):
    """下单返回 True：实盘等成交回调；回测/DRY 立即清信号 pending 并写 hold_meta。"""
    live_waiting = (not getattr(A, "is_backtest", False)) and (
        not DRY_RUN
    ) and isinstance(getattr(A, "pending", None), dict)
    if live_waiting:
        print(
            "%s %s submitted keep signal pending until fill"
            % (STRATEGY_NAME, side)
        )
        _event_log("signal_pending_keep_until_fill", side=side)
        _save_state()
        return
    if side == "buy":
        _after_signal_buy_filled(px, day, add=add)
        return
    _finish_sell_fill()


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
    "weekly_bear": "周线空头禁开",
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
    # 收盘确认：用当日完整 K；开盘：日 K 去未收盘根，周 K 含未收盘根
    prev_d = False
    prev_w = False
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
    # v1.10 误把开盘兜底写成 confirmed=今日，会挡收盘确认；盘中执行时段自动清掉
    if (
        live_cc
        and phase == "exec"
        and str(getattr(A, "_confirmed_eval_day", "") or "") == day
    ):
        print(
            "%s clear mis-marked confirmed_eval_day=%s (was open fallback)"
            % (STRATEGY_NAME, day)
        )
        _event_log("clear_mis_confirmed_eval_day", day=day)
        A._confirmed_eval_day = ""
        _save_state()
    # 开盘兜底：上一根已收盘日尚未确认、今日尚未兜底、无挂起
    prev_closed_day = _last_closed_bar_day(C, day) if live_cc else day
    confirmed_day = str(getattr(A, "_confirmed_eval_day", "") or "")
    need_fallback = (
        live_cc
        and phase == "exec"
        and confirmed_day < str(prev_closed_day)
        and str(getattr(A, "_fallback_done_day", "") or "") != day
        and (not isinstance(getattr(A, "pending_entry", None), dict))
        and (not isinstance(getattr(A, "pending_exit", None), dict))
    )
    if live_cc and phase == "confirm":
        highs_s, closes_s, vols_s = highs_d, closes_d, vols_d
        closes_ws = closes_w
        sig_day_daily = day
        sig_day_weekly = day
    elif need_fallback or (live_cc and phase == "exec"):
        # 开盘兜底 / 盘中执行：日 K 去掉未收盘根，避免未完成日线误触 vol_dry 等；
        # 周 K 含本周未收盘根，与 confirm/回测一致（新周首日即可 weekly_bear 撤买入 pending）
        # 日信号日=上一完整交易日；周线 streak/清仓信号日=今日（与含未收盘周根对齐）
        prev_d = True
        prev_w = False
        highs_s = _drop_forming_bar(highs_d)
        closes_s = _drop_forming_bar(closes_d)
        vols_s = _drop_forming_bar(vols_d)
        closes_ws = closes_w
        if closes_s is None or len(closes_s) < 3 or closes_ws is None or len(closes_ws) < 3:
            _live_heartbeat("ohlcv_confirm_short")
            return
        sig_day_daily = prev_closed_day
        sig_day_weekly = day
    else:
        # 回测：信号评估用完整序列
        highs_s, closes_s, vols_s = highs_d, closes_d, vols_d
        closes_ws = closes_w
        sig_day_daily = day
        sig_day_weekly = day

    price = float(closes_s[-1])
    high_px = float(highs_s[-1])
    if bt:
        _bt_recover_position(now=now, last=float(closes_d[-1]))

    weekly_bull, weekly_bear, w_detail = _eval_weekly(closes_ws)
    # 清仓二次确认只在 bt / confirm / 开盘兜底累计；盘中 exec 不改 streak
    track_bear = (not live_cc) or (phase == "confirm") or bool(need_fallback)
    force_empty, w_bear_n = _update_w_bear_streak(
        weekly_bear, sig_day_weekly, track=track_bear
    )
    w_bias_block, w_bias = _weekly_bias_guard(w_detail)
    w_slope_block, _w_bias_low = _weekly_low_slope_guard(w_detail)
    buy_ok, buy_reasons, b_detail = _eval_daily_buy(closes_s, vols_s)
    if weekly_bear:
        buy_ok = False
        buy_reasons = ["weekly_bear"] + [
            r for r in buy_reasons if r not in ("weekly_bear",)
        ]
    elif w_bias_block:
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
    exit_ids = []
    exit_shares = 0
    if _lots_enabled():
        if not holding:
            if getattr(A, "lots", None):
                A.lots = []
            if (
                getattr(A, "hold_peak", None) is not None
                or int(getattr(A, "hold_bars", 0) or 0)
                or getattr(A, "time_force_grace_until", None) is not None
            ):
                _clear_hold_meta()
        else:
            _ensure_lots()
            changed = False
            for lot in A.lots:
                if _bump_lot_bars(lot, day):
                    changed = True
                if _update_lot_peaks(lot, high_px, price):
                    changed = True
            _mirror_hold_from_lots()
            if changed:
                _save_state()
    elif not holding:
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
    trail_hit = False
    time_force_hit = False
    if holding and _lots_enabled():
        sell_ok, sell_reasons, exit_ids, exit_shares = _collect_lot_exits(
            price, closes_s, force_empty
        )
        stop_hit = "stop_loss" in sell_reasons
        trail_hit = "trail_stop" in sell_reasons
        time_force_hit = "time_force" in sell_reasons
    else:
        if holding and cost > 0 and price <= cost * (1.0 - float(STOP_LOSS)):
            stop_hit = True
            sell_reasons = list(sell_reasons) + ["stop_loss"]
            sell_ok = True

        if holding and (not stop_hit) and _trail_stop_hit(price, cost):
            trail_hit = True
            sell_reasons = list(sell_reasons) + ["trail_stop"]
            sell_ok = True

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

    ret_pct = None
    if holding and cost > 0:
        ret_pct = (price - cost) / cost

    skip_codes = (
        "chase_skip",
        "w_bias_skip",
        "w_slope_skip",
        "vol_dry_skip",
        "weekly_bear",
    )
    real_buys = [r for r in buy_reasons if r not in skip_codes]
    buy_sig = bool(
        (not weekly_bear)
        and (not w_bias_block)
        and (not w_slope_block)
        and buy_ok
        and real_buys
    )
    vol_dry_block = "vol_dry_skip" in buy_reasons

    pe_now = bool(getattr(A, "pending_entry", None))
    px_now = bool(getattr(A, "pending_exit", None))
    # 信号上升沿强制打；电平持续为真时走 idle 节流（避免 confirm 窗刷屏）
    force_bar_log = _bar_signal_rising_edge(buy_sig, sell_ok, force_empty)
    status_idle = (bool(holding) or pe_now or px_now) and (not force_bar_log)
    if _should_emit_bar_status(C, now, force_bar_log, status_idle):
        A.ready_logged = True
        if not getattr(A, "is_backtest", False):
            A._bar_status_at = now
        print(
            "%s" % STRATEGY_NAME,
            day,
            hhmm,
            "n1d=%d n1w=%d close=%.4f sig_d=%s sig_w=%s phase=%s prev_d=%s prev_w=%s "
            "w_bull=%s w_bear=%s w_bn=%s/%s w_ma5=%s w_ma30=%s w_hist=%s "
            "buy=%s buyR=%s sell=%s sellR=%s "
            "hold=%s nlot=%s ret=%s pe=%s px=%s bt_held=%s avail=%s"
            % (
                len(closes_s),
                len(closes_ws),
                price,
                sig_day_daily,
                sig_day_weekly,
                phase,
                prev_d,
                prev_w,
                weekly_bull,
                weekly_bear,
                w_bear_n,
                _w_bear_confirm_need(),
                None if w_detail.get("ma5") is None else round(w_detail["ma5"], 4),
                None if w_detail.get("ma30") is None else round(w_detail["ma30"], 4),
                None if w_detail.get("hist") is None else round(w_detail["hist"], 4),
                buy_sig,
                ",".join(buy_reasons) if buy_reasons else "-",
                sell_ok or force_empty,
                ",".join((["weekly_bear"] if force_empty else []) + sell_reasons) or "-",
                holding,
                _pos_lots() if holding else 0,
                None if ret_pct is None else ("%.2f%%" % (ret_pct * 100.0)),
                pe_now,
                px_now,
                _bt_held_vol() if bt else "-",
                _bt_available_vol() if bt else "-",
            ),
        )
        _bar_log(
            day=day,
            hhmm=hhmm,
            n1d=len(closes_s),
            n1w=len(closes_ws),
            close=round(price, 6),
            sig_d=sig_day_daily,
            sig_w=sig_day_weekly,
            phase=phase,
            prev_d=prev_d,
            prev_w=prev_w,
            w_bull=weekly_bull,
            w_bear=weekly_bear,
            w_bn=w_bear_n,
            w_bn_need=_w_bear_confirm_need(),
            w_ma5=None if w_detail.get("ma5") is None else round(w_detail["ma5"], 4),
            w_ma30=None if w_detail.get("ma30") is None else round(w_detail["ma30"], 4),
            w_hist=None if w_detail.get("hist") is None else round(w_detail["hist"], 4),
            buy=buy_sig,
            buyR=",".join(buy_reasons) if buy_reasons else "-",
            sell=bool(sell_ok or force_empty),
            sellR=",".join((["weekly_bear"] if force_empty else []) + sell_reasons) or "-",
            hold=holding,
            nlot=_pos_lots() if holding else 0,
            ret=None if ret_pct is None else round(ret_pct * 100.0, 4),
            pe=pe_now,
            px=px_now,
        )

    # ---- 先执行挂起的卖/买（仅开盘窗；收盘确认不按开盘价成交）----
    can_exec_pending = (not live_cc) or _in_pending_exec_window(now_s)
    pe_exit = getattr(A, "pending_exit", None)
    if holding and isinstance(pe_exit, dict):
        if _pending_ready(pe_exit, day, tag, "day"):
            if not can_exec_pending:
                _log_pending_defer_once(
                    "exit", day, now_s, pe_exit.get("signal_day")
                )
            else:
                reason = str(pe_exit.get("reason", "SELL") or "SELL")
                reasons = pe_exit.get("reasons") or [reason]
                print(
                    "%s SELL by signal=%s label=%s all=%s lots=%s shares=%s signal_day=%s @open=%.4f"
                    % (
                        STRATEGY_NAME,
                        reason,
                        _reason_label(reason, "sell"),
                        _format_reasons(reasons, "sell"),
                        pe_exit.get("lot_ids") or "-",
                        pe_exit.get("shares") if pe_exit.get("shares") is not None else _pos_shares(),
                        pe_exit.get("signal_day"),
                        open_px,
                    )
                )
                _event_log(
                    "sell_by_signal",
                    signal=reason,
                    label=_reason_label(reason, "sell"),
                    all_reasons=_format_reasons(reasons, "sell"),
                    signal_day=pe_exit.get("signal_day"),
                    open=open_px,
                    lot_ids=pe_exit.get("lot_ids"),
                    shares=pe_exit.get("shares"),
                )
                lot_ids = pe_exit.get("lot_ids")
                want_vol = pe_exit.get("shares")
                ok = _order_sell(
                    C,
                    reason,
                    open_px,
                    now,
                    want_vol=None if want_vol is None else int(want_vol),
                    lot_ids=lot_ids,
                )
                if ok:
                    _on_signal_order_ok("sell")
                else:
                    print(
                        "%s pending_exit keep after sell fail/skip signal=%s"
                        % (STRATEGY_NAME, reason)
                    )
                    _event_log(
                        "pending_exit_keep_after_fail",
                        sell_reason=reason,
                        signal_day=pe_exit.get("signal_day"),
                    )
                return

    pe_entry = getattr(A, "pending_entry", None)
    pe_is_add = isinstance(pe_entry, dict) and bool(pe_entry.get("add"))
    if (
        ((not holding) or pe_is_add)
        and isinstance(pe_entry, dict)
        and (pe_is_add or ("BUY" not in getattr(A, "acted", set())))
        and _pending_ready(pe_entry, day, tag, "day")
    ):
        # 撤单校验用当 bar 周线（含未收盘周根）与日线过滤；与 confirm/bt 一致
        if pe_is_add and not holding:
            A.pending_entry = None
            _save_state()
            print("%s pending_entry cancel add_no_pos" % STRATEGY_NAME)
            _event_log("pending_entry_cancel", reason="add_no_pos")
            return
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
            _event_log(
                "pending_entry_cancel",
                reason=why,
                signal_day=pe_entry.get("signal_day"),
            )
            return
        if not can_exec_pending:
            _log_pending_defer_once(
                "entry", day, now_s, pe_entry.get("signal_day")
            )
        else:
            reasons = pe_entry.get("reasons") or []
            primary = reasons[0] if reasons else "entry"
            kind = "add" if pe_is_add else "buy"
            print(
                "%s %s by signal=%s label=%s all=%s signal_day=%s @open=%.4f"
                % (
                    STRATEGY_NAME,
                    "BUY add" if pe_is_add else "BUY",
                    primary,
                    _reason_label(primary, "buy"),
                    _format_reasons(reasons, "buy"),
                    pe_entry.get("signal_day"),
                    open_px,
                )
            )
            _event_log(
                "buy_by_signal" if not pe_is_add else "buy_add_by_signal",
                signal=primary,
                label=_reason_label(primary, "buy"),
                all_reasons=_format_reasons(reasons, "buy"),
                signal_day=pe_entry.get("signal_day"),
                open=open_px,
                add=pe_is_add,
            )
            budget = _buy_budget(cash)
            ok = _order_buy(C, open_px, now, budget, add=pe_is_add)
            if ok:
                _on_signal_order_ok("buy", px=open_px, day=day, add=pe_is_add)
            else:
                print(
                    "%s pending_entry keep after %s fail/skip signal=%s"
                    % (STRATEGY_NAME, kind, primary)
                )
                _event_log(
                    "pending_entry_keep_after_fail",
                    signal=primary,
                    signal_day=pe_entry.get("signal_day"),
                    add=pe_is_add,
                )
            return

    # ---- 新信号：回测当根；实盘仅收盘确认或开盘兜底 ----
    allow_new = True
    is_confirm = live_cc and phase == "confirm"
    if live_cc:
        if is_confirm:
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
                    _mark_signal_eval_done(day, is_confirm)
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
            # 周线清仓用 sig_w；日线卖点用 sig_d
            exit_sig_day = (
                sig_day_weekly
                if (force_empty or reason == "weekly_bear")
                else sig_day_daily
            )
            A.pending_exit = {
                "mode": "day",
                "reason": reason,
                "signal_day": exit_sig_day,
                "signal_tag": tag,
                "close": price,
                "reasons": uniq,
            }
            if _lots_enabled() and exit_ids:
                A.pending_exit["lot_ids"] = list(exit_ids)
                A.pending_exit["shares"] = int(exit_shares)
            A.pending_entry = None
            if live_cc:
                _mark_signal_eval_done(day, is_confirm)
            else:
                _save_state()
            print(
                "%s pending_exit set signal=%s label=%s all=%s lots=%s shares=%s day=%s close=%.4f phase=%s"
                % (
                    STRATEGY_NAME,
                    reason,
                    _reason_label(reason, "sell"),
                    _format_reasons(uniq, "sell"),
                    exit_ids or "-",
                    exit_shares or _pos_shares(),
                    exit_sig_day,
                    price,
                    phase,
                )
            )
            _event_log(
                "pending_exit_set",
                signal=reason,
                label=_reason_label(reason, "sell"),
                all_reasons=_format_reasons(uniq, "sell"),
                signal_day=exit_sig_day,
                close=price,
                phase=phase,
                lot_ids=exit_ids or None,
                shares=exit_shares or None,
            )
        elif buy_sig and _scale_ready():
            if isinstance(getattr(A, "pending_entry", None), dict):
                if live_cc:
                    _mark_signal_eval_done(day, is_confirm)
                return
            A.pending_entry = {
                "signal_day": sig_day_daily,
                "signal_tag": tag,
                "close": price,
                "reasons": list(real_buys),
                "add": True,
            }
            A.pending_exit = None
            if live_cc:
                _mark_signal_eval_done(day, is_confirm)
            else:
                _save_state()
            primary = real_buys[0] if real_buys else "entry"
            print(
                "%s pending_entry set add signal=%s label=%s all=%s day=%s close=%.4f lots=%s phase=%s"
                % (
                    STRATEGY_NAME,
                    primary,
                    _reason_label(primary, "buy"),
                    _format_reasons(real_buys, "buy"),
                    sig_day_daily,
                    price,
                    _pos_lots(),
                    phase,
                )
            )
            _event_log(
                "pending_entry_set",
                signal=primary,
                label=_reason_label(primary, "buy"),
                all_reasons=_format_reasons(real_buys, "buy"),
                signal_day=sig_day_daily,
                close=price,
                phase=phase,
                add=True,
            )
        elif live_cc:
            _mark_signal_eval_done(day, is_confirm)
        return

    if buy_sig and ("BUY" not in getattr(A, "acted", set())):
        if isinstance(getattr(A, "pending_entry", None), dict):
            if live_cc:
                _mark_signal_eval_done(day, is_confirm)
            return
        A.pending_entry = {
            "signal_day": sig_day_daily,
            "signal_tag": tag,
            "close": price,
            "reasons": list(real_buys),
        }
        A.pending_exit = None
        if live_cc:
            _mark_signal_eval_done(day, is_confirm)
        else:
            _save_state()
        primary = real_buys[0] if real_buys else "entry"
        print(
            "%s pending_entry set signal=%s label=%s all=%s day=%s close=%.4f phase=%s"
            % (
                STRATEGY_NAME,
                primary,
                _reason_label(primary, "buy"),
                _format_reasons(real_buys, "buy"),
                sig_day_daily,
                price,
                phase,
            )
        )
        _event_log(
            "pending_entry_set",
            signal=primary,
            label=_reason_label(primary, "buy"),
            all_reasons=_format_reasons(real_buys, "buy"),
            signal_day=sig_day_daily,
            close=price,
            phase=phase,
        )
    elif live_cc:
        _mark_signal_eval_done(day, is_confirm)
