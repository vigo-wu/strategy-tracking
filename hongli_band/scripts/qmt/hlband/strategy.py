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


def _cross_up(a_prev, b_prev, a_now, b_now):
    if None in (a_prev, b_prev, a_now, b_now):
        return False
    return (a_prev <= b_prev) and (a_now > b_now)


def _eval_weekly(closes_w):
    """返回 (bull, bear, detail)。
    多头(仅日志): MA5>MA13 且 DIF>0 且红柱 且生命线未明显走平。
    空头: 收盘破 MA34（W_MA_LIFE）或 DIF/DEA 零轴下死叉。"""
    detail = {
        "ma5": None,
        "ma10": None,
        "ma30": None,
        "dif": None,
        "dea": None,
        "hist": None,
        "close": None,
    }
    ma5 = _price_ma(closes_w, W_MA_FAST)
    ma10 = _price_ma(closes_w, W_MA_MID)
    ma30 = _price_ma(closes_w, W_MA_LIFE)
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
    d2 = _last_valid(dif, i - 2) if i >= 2 else None
    e2 = _last_valid(dea, i - 2) if i >= 2 else None
    golden_now = _cross_up(d1, e1, d0, e0)
    golden_prev = _cross_up(d2, e2, d1, e1) if i >= 2 else False
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
            "dif_prev": d1,
            "dea_prev": e1,
            "hist": h0,
            "hist_prev": h1,
            "macd_golden_now": golden_now,
            "macd_golden_prev": golden_prev,
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
    ma20 = _price_ma(closes, D_MA_MID)
    ma60 = _price_ma(closes, D_MA_SLOW)
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
    """周线 (MA5-MA34)/MA34 >= W_BIAS_HARD → 禁开。"""
    m5 = w_detail.get("ma5")
    m30 = w_detail.get("ma30")
    if m5 is None or m30 is None or m30 <= 0:
        return False, None
    bias = (float(m5) - float(m30)) / float(m30)
    return bias >= float(W_BIAS_HARD), bias


def _weekly_low_slope_guard(w_detail):
    """低位 (MA5-MA34)/MA34 < W_BIAS_LOW 且生命线 MA34 未连续向上 → 禁开。"""
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
        changed = True
    elif hi > float(peak):
        A.hold_peak = hi
        changed = True
    else:
        changed = False
    if cost and float(cost) > 0:
        mx = (float(A.hold_peak) - float(cost)) / float(cost)
        prev = float(getattr(A, "hold_max_ret", 0) or 0)
        if mx > prev:
            A.hold_max_ret = mx
            changed = True
    return changed


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


def _time_force_min_ret():
    try:
        return float(globals().get("TIME_FORCE_MIN_RET") or 0)
    except Exception:
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


def _time_force_hit(price, closes, hold_bars, lot=None):
    """智能时间成本：持仓 > TIME_FORCE_BARS 后，破日线 MA60 强制平仓。
    BARS<=0 关闭整条规则（MIN_RET=0 只关掉让路，不是关闭）。
    仍站上 MA60 时：峰值已达 TIME_FORCE_MIN_RET（阶梯止盈起步档）则不按日历强平；
    从未武装的死钱仓豁免 GRACE 日后强平。"""
    try:
        bars_lim = int(TIME_FORCE_BARS)
    except (TypeError, ValueError):
        bars_lim = 0
    if bars_lim <= 0:
        return False
    if hold_bars is None or int(hold_bars) <= bars_lim:
        return False
    ma60_arr = _price_ma(closes, D_MA_SLOW)
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
        "time_force_trend_skip": bool(getattr(A, "time_force_trend_skip", False)),
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
        A.time_force_trend_skip = False
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
    A.time_force_trend_skip = bool(lot.get("time_force_trend_skip"))


def _infer_round_scaled():
    """旧状态无 round_scaled 时：剩余笔 id>1 或同时 >=2 笔，视为本轮已加过仓。"""
    if _lots_enabled():
        mx = 0
        n = 0
        for lot in getattr(A, "lots", None) or []:
            if not isinstance(lot, dict):
                continue
            try:
                sh = int(lot.get("shares") or 0)
            except Exception:
                sh = 0
            if sh < 100:
                continue
            n += 1
            try:
                mx = max(mx, int(lot.get("id") or 0))
            except Exception:
                pass
        return n >= 2 or mx > 1
    pos = getattr(A, "position", None) or {}
    try:
        return int(pos.get("lots", 1) or 1) >= 2
    except Exception:
        return False


def _round_scaled_now():
    if bool(getattr(A, "round_scaled", False)):
        return True
    if not _infer_round_scaled():
        return False
    A.round_scaled = True
    try:
        _save_state()
    except Exception:
        pass
    return True


def _scale_peak_ret():
    mx = 0.0
    armed_bars = 0
    arm = float(globals().get("SCALE_ARM") or 0)
    if arm <= 0:
        arm = 0.03
    if _lots_enabled():
        for lot in _ensure_lots():
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
            peak = getattr(A, "hold_peak", None)
            cost = _pos_cost_price()
            if peak and cost > 0:
                mx = (float(peak) - float(cost)) / float(cost)
            armed_bars = int(getattr(A, "hold_bars", 0) or 0)
        return mx, armed_bars
    peak = getattr(A, "hold_peak", None)
    cost = _pos_cost_price()
    if peak and cost > 0:
        mx = (float(peak) - float(cost)) / float(cost)
    armed_bars = int(getattr(A, "hold_bars", 0) or 0)
    return mx, armed_bars


def _scale_gate(w_detail=None, price=None):
    """加仓门槛：(ok, why)。why 仅失败时有值。"""
    if not bool(globals().get("SCALE_ENABLE")):
        return False, "scale_off"
    holding_now = _has_position() or (
        getattr(A, "is_backtest", False) and _bt_held_vol() >= 100
    )
    if not holding_now:
        return False, "scale_no_pos"
    if bool(globals().get("SCALE_ONCE_PER_ROUND", True)) and _round_scaled_now():
        return False, "scale_once"
    if _pos_lots() >= int(globals().get("SCALE_MAX") or 1):
        return False, "scale_max"
    blocked, why_b = _book_scale_blocked()
    if blocked:
        return False, why_b or "book_lot_cap"
    arm = float(globals().get("SCALE_ARM") or 0)
    if arm <= 0:
        arm = 0.03
    mx, armed_bars = _scale_peak_ret()
    if mx < arm:
        return False, "scale_arm"
    need_bars = int(globals().get("SCALE_ARM_BARS") or 0)
    if need_bars > 0 and armed_bars < need_bars:
        return False, "scale_bars"
    hist_min = globals().get("SCALE_W_HIST_MIN")
    if hist_min is not None and w_detail is not None:
        h = w_detail.get("hist")
        if h is not None and float(h) < float(hist_min):
            return False, "scale_w_hist"
    return True, ""


def _scale_ready(w_detail=None):
    ok, _why = _scale_gate(w_detail)
    return ok


def _daily_plat_break(closes, highs, lows):
    """日线收盘确认突破前期平台：回看窗口振幅够窄，今日收盘站上窗口最高价，昨收仍在平台内。"""
    lookback = int(globals().get("SCALE_PLAT_LOOKBACK") or 20)
    max_range = float(globals().get("SCALE_PLAT_MAX_RANGE") or 0.10)
    buf = float(globals().get("SCALE_PLAT_BREAK_BUF") or 0.0)
    if lookback < 5 or max_range <= 0:
        return False
    if closes is None or highs is None or lows is None:
        return False
    n = len(closes)
    if n < lookback + 1 or len(highs) != n or len(lows) != n:
        return False
    if n < 2:
        return False
    plat = _plat_window(highs, lows, lookback)
    if plat is None:
        return False
    plat_high, plat_low = plat
    rng = (float(plat_high) - float(plat_low)) / float(plat_low)
    if rng > max_range:
        return False
    hurdle = float(plat_high) * (1.0 + buf)
    px = float(closes[-1])
    prev = float(closes[-2])
    if px <= hurdle:
        return False
    if prev > hurdle:
        return False
    return True


def _weekly_macd_golden_expand(w_detail):
    """近两周周线 MACD 金叉，且当前红柱比上周放大。"""
    if not w_detail:
        return False
    h0 = w_detail.get("hist")
    h1 = w_detail.get("hist_prev")
    if h0 is None or h1 is None:
        return False
    hist = float(h0)
    hist_prev = float(h1)
    if hist <= 0 or hist <= hist_prev:
        return False
    golden_now = bool(w_detail.get("macd_golden_now"))
    golden_prev = bool(w_detail.get("macd_golden_prev"))
    if not (golden_now or golden_prev):
        return False
    if golden_now and (not golden_prev):
        return True
    ratio = float(globals().get("SCALE_W_HIST_EXPAND_RATIO") or 1.0)
    if ratio <= 1.0:
        return True
    base = abs(hist_prev) if abs(hist_prev) > 1e-12 else hist
    return hist >= base * ratio


def _eval_scale_push(closes, highs, lows, w_detail, pullback=False):
    """加仓触发：缩量回踩 或 日线破平台 或 周线 MACD 金叉柱放大。"""
    reasons = []
    if pullback:
        reasons.append("pullback_vol")
    if _daily_plat_break(closes, highs, lows):
        reasons.append("plat_break")
    if _weekly_macd_golden_expand(w_detail):
        reasons.append("w_macd_golden")
    return bool(reasons), reasons


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
    A.time_force_trend_skip = False
    A.round_scaled = False


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
    clock = str(getattr(A, "clock_prev_closed_day", "") or "")
    if clock and (not getattr(A, "is_backtest", False)):
        return clock
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
        # 同日尾盘可成交；隔夜残留次日可成交。实际报单还受 _can_exec_signal_pending 约束。
        return bool(sig_day) and sig_day <= day
    if sig_tag and bar_tag:
        return sig_tag < bar_tag
    if sig_day and sig_day <= day:
        return True
    return False


def _cfg_hhmmss(key, default):
    return str(globals().get(key, default) or default)


def _in_hhmmss_window(now_s, start, end, inclusive_end=False):
    s = str(now_s)
    if inclusive_end:
        return start <= s <= end
    return start <= s < end


def _in_close_exec_window(now_s):
    start = _cfg_hhmmss("PENDING_EXEC_START", "145600")
    end = _cfg_hhmmss("PENDING_EXEC_END", "145700")
    return _in_hhmmss_window(now_s, start, end, inclusive_end=False)


def _in_open_exec_window(now_s):
    start = _cfg_hhmmss("OPEN_EXEC_START", "093000")
    end = _cfg_hhmmss("OPEN_EXEC_END", "094500")
    return _in_hhmmss_window(now_s, start, end, inclusive_end=False)


def _can_exec_signal_pending(pend, day, now_s):
    """回测随时；实盘当日信号仅尾盘，隔夜残留开盘窗（尾盘也可补）。"""
    if getattr(A, "is_backtest", False):
        return True
    if not _live_close_confirm_on():
        return True
    if not isinstance(pend, dict):
        return False
    sig_day = str(pend.get("signal_day", "") or "")
    if _in_close_exec_window(now_s):
        return True
    if _in_open_exec_window(now_s) and sig_day and sig_day < str(day):
        return True
    return False


def _signal_exec_px(pend, day, now_s, open_px, last_px):
    """尾盘/回测同日用收盘现价；隔夜残留用开盘价。"""
    sig_day = str((pend or {}).get("signal_day", "") or "")
    if getattr(A, "is_backtest", False):
        if sig_day and sig_day < str(day):
            return float(open_px), "open"
        return float(last_px), "close"
    if _in_close_exec_window(now_s):
        return float(last_px), "close"
    return float(open_px), "open"


def _log_pending_defer_once(kind, day, now_s, signal_day):
    """成交窗外 defer 每个交易日每种 pending 只打一次日志，避免盘中刷屏。"""
    kind = str(kind or "")
    day = str(day or "")
    attr = "_defer_log_%s_day" % kind
    if str(getattr(A, attr, "") or "") == day:
        return
    setattr(A, attr, day)
    print(
        "%s pending_%s defer outside exec window now=%s signal_day=%s"
        % (STRATEGY_NAME, kind, now_s, signal_day)
    )
    _event_log(
        "pending_%s_defer" % kind,
        now=now_s,
        signal_day=signal_day,
        close_exec_end=_cfg_hhmmss("PENDING_EXEC_END", "145700"),
        open_exec_end=_cfg_hhmmss("OPEN_EXEC_END", "094500"),
    )


def _should_emit_bar_status(C, now, force, status_idle):
    """
    状态行是否输出。
    force（信号上升沿）立刻打；回测逐根打（空仓也打，避免误以为停住）；
    实盘无新沿时一律按 LIVE_HEARTBEAT_SEC 节流（空仓/持仓/挂起相同）。
    """
    if not getattr(A, "ready_logged", False):
        return True
    if force:
        return True
    if getattr(A, "is_backtest", False):
        return True
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


def _lot_open_day(lot):
    ot = str((lot or {}).get("opened_at") or "")
    return ot[:8] if len(ot) >= 8 else ""


def _pending_exit_unfilled_ids():
    """pending_exit.lot_ids 中仍持有的笔；无 lot_ids 视为整仓出清残留。"""
    pe = getattr(A, "pending_exit", None)
    if not isinstance(pe, dict):
        return []
    lots = getattr(A, "lots", None) or []
    raw_ids = pe.get("lot_ids")
    idset = None
    if raw_ids:
        try:
            idset = set(int(x) for x in raw_ids)
        except Exception:
            idset = None
    remain = []
    for lot in lots:
        if not isinstance(lot, dict):
            continue
        try:
            sh = int(lot.get("shares") or 0)
            lid = int(lot.get("id") or 0)
        except Exception:
            continue
        if sh < 100 or lid <= 0:
            continue
        if idset is None or lid in idset:
            remain.append(lid)
    return remain


def _refresh_pending_exit_remain(remain_ids):
    pe = getattr(A, "pending_exit", None)
    if not isinstance(pe, dict):
        return
    remain_ids = [int(x) for x in (remain_ids or []) if x]
    pe["lot_ids"] = list(remain_ids)
    shares = 0
    idset = set(remain_ids)
    for lot in getattr(A, "lots", None) or []:
        if not isinstance(lot, dict):
            continue
        try:
            if int(lot.get("id") or 0) in idset:
                shares += int(lot.get("shares") or 0)
        except Exception:
            continue
    pe["shares"] = int(shares)
    A.pending_exit = pe


def _log_skip_sell_eval_day(day):
    day = str(day or "")
    if str(getattr(A, "_skip_sell_eval_logged", "") or "") == day:
        return
    A._skip_sell_eval_logged = day
    print(
        "%s skip sell eval after add fill day=%s last_add=%s"
        % (STRATEGY_NAME, day, getattr(A, "_last_add_signal", "") or "-")
    )
    _event_log(
        "skip_sell_eval_day",
        day=day,
        last_add=getattr(A, "_last_add_signal", "") or "",
        last_add_day=getattr(A, "_last_add_day", "") or "",
    )


def _log_sell_lot_can_use(now, day, lot_ids, want_vol, reason):
    """核对按笔卖出 vs 券商合计 can_use：当日新仓可能实际卖掉旧仓。"""
    avail = None
    try:
        avail = _max_sell_vol(now)
    except Exception:
        avail = None
    idset = None
    if lot_ids:
        try:
            idset = set(int(x) for x in lot_ids)
        except Exception:
            idset = None
    target = []
    others = []
    same_day_target = []
    older_other = []
    for lot in getattr(A, "lots", None) or []:
        if not isinstance(lot, dict):
            continue
        try:
            lid = int(lot.get("id") or 0)
            sh = int(lot.get("shares") or 0)
        except Exception:
            continue
        if sh < 100 or lid <= 0:
            continue
        open_day = _lot_open_day(lot)
        brief = {
            "id": lid,
            "shares": sh,
            "opened_at": str(lot.get("opened_at") or ""),
            "open_day": open_day,
            "hold_bars": lot.get("hold_bars"),
        }
        is_tgt = idset is None or lid in idset
        if is_tgt:
            target.append(brief)
            if open_day and open_day == str(day):
                same_day_target.append(lid)
        else:
            others.append(brief)
            if open_day and open_day < str(day):
                older_other.append(lid)
    last_add_day = str(getattr(A, "_last_add_day", "") or "")
    last_add = str(getattr(A, "_last_add_signal", "") or "")
    risk = bool(same_day_target) and (avail is None or int(avail) >= 100) and (
        bool(older_other) or bool(others)
    )
    print(
        "%s SELL lot-can_use reason=%s lots=%s want=%s avail=%s "
        "same_day_lots=%s other=%s last_add=%s@%s risk=%s"
        % (
            STRATEGY_NAME,
            reason,
            lot_ids if lot_ids is not None else "-",
            want_vol,
            avail,
            same_day_target or "-",
            [x.get("id") for x in others] or "-",
            last_add or "-",
            last_add_day or "-",
            risk,
        )
    )
    _event_log(
        "sell_lot_can_use",
        reason=reason,
        lot_ids=lot_ids,
        want=want_vol,
        avail=avail,
        target=target,
        other=others,
        same_day_lots=same_day_target,
        last_add=last_add,
        last_add_day=last_add_day,
        risk=risk,
    )
    if risk:
        print(
            "%s WARN SELL lots=%s opened today; broker can_use may fill older lots, "
            "not necessarily lots=%s (plat_break add same-day trail is the typical case)"
            % (STRATEGY_NAME, same_day_target, lot_ids)
        )
        _event_log(
            "sell_lot_can_use_risk",
            lot_ids=lot_ids,
            same_day_lots=same_day_target,
            avail=avail,
            last_add=last_add,
            last_add_day=last_add_day,
        )


def _after_signal_buy_filled(px, day, add=False):
    """买入成交后初始化持仓元数据并清信号 pending。"""
    pe = getattr(A, "pending_entry", None)
    add_reasons = []
    book_frac = None
    if isinstance(pe, dict):
        add_reasons = [str(x) for x in (pe.get("reasons") or []) if x]
        if pe.get("book_frac") is not None:
            try:
                book_frac = float(pe.get("book_frac"))
            except Exception:
                book_frac = None
    A.pending_entry = None
    A.pending_exit = None
    A.round_scaled = True if add else False
    if add:
        d = str(day or "")
        A._skip_sell_eval_day = d
        A._last_add_day = d
        A._last_add_signal = ",".join(add_reasons) if add_reasons else "add"
        print(
            "%s skip sell eval after add fill day=%s signal=%s"
            % (STRATEGY_NAME, d, A._last_add_signal)
        )
        _event_log(
            "skip_sell_eval_after_add",
            day=d,
            signal=A._last_add_signal,
        )
    if _lots_enabled():
        lots = getattr(A, "lots", None) or []
        if lots and day:
            lots[-1]["hold_count_bar"] = str(day)
            if not add:
                lots[-1]["hold_bars"] = 0
        if lots and book_frac is not None:
            lots[-1]["book_frac"] = float(book_frac)
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
        A.time_force_trend_skip = False
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
        remain = _pending_exit_unfilled_ids()
        if remain:
            _refresh_pending_exit_remain(remain)
            acted = getattr(A, "acted", None)
            if isinstance(acted, set):
                acted.discard("SELL")
            pe = getattr(A, "pending_exit", None) or {}
            print(
                "%s pending_exit keep after partial fill lots=%s shares=%s"
                % (STRATEGY_NAME, remain, pe.get("shares"))
            )
            _event_log(
                "pending_exit_keep_partial",
                lot_ids=remain,
                shares=pe.get("shares"),
            )
            _save_state()
            return
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
    "skip_add_bar": "加仓成交后当日不评卖",
}
_BUY_LABELS = {
    "pullback_vol": "买点1-缩量回踩强支撑",
    "plat_break": "加仓-日线突破前期平台",
    "w_macd_golden": "加仓-周线MACD金叉柱放大",
    "chase_skip": "追高过滤跳过",
    "w_bias_skip": "周线高位乖离禁开",
    "w_slope_skip": "低位周线MA34未连升禁开",
    "vol_dry_skip": "无量阴跌禁开",
    "weekly_bear": "周线空头禁开",
    "scale_once": "本轮已加仓",
    "book_lot_cap": "跟踪池已满三笔跳过买入",
    "buy_cap": "账户或单标的额度已满跳过开仓",
    "scale_cap": "账户或单标的额度已满跳过加仓",
    "wait": "等待共享账本冻结",
    "book_fail": "持股查询失败且无本地账本不下单",
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


def _try_exec_pending_exit(C, now, now_s, day, tag, open_px, last_px, holding):
    """成交就绪的 pending_exit。True=调用方应 return。"""
    if not holding:
        return False
    pe_exit = getattr(A, "pending_exit", None)
    if not isinstance(pe_exit, dict):
        return False
    if not _pending_ready(pe_exit, day, tag, "day"):
        return False
    if not _can_exec_signal_pending(pe_exit, day, now_s):
        _log_pending_defer_once("exit", day, now_s, pe_exit.get("signal_day"))
        return False
    px, px_kind = _signal_exec_px(pe_exit, day, now_s, open_px, last_px)
    reason = str(pe_exit.get("reason", "SELL") or "SELL")
    reasons = pe_exit.get("reasons") or [reason]
    print(
        "%s SELL by signal=%s label=%s all=%s lots=%s shares=%s signal_day=%s @%s=%.4f"
        % (
            STRATEGY_NAME,
            reason,
            _reason_label(reason, "sell"),
            _format_reasons(reasons, "sell"),
            pe_exit.get("lot_ids") or "-",
            pe_exit.get("shares") if pe_exit.get("shares") is not None else _pos_shares(),
            pe_exit.get("signal_day"),
            px_kind,
            px,
        )
    )
    _event_log(
        "sell_by_signal",
        signal=reason,
        label=_reason_label(reason, "sell"),
        all_reasons=_format_reasons(reasons, "sell"),
        signal_day=pe_exit.get("signal_day"),
        px=px,
        px_kind=px_kind,
        lot_ids=pe_exit.get("lot_ids"),
        shares=pe_exit.get("shares"),
    )
    lot_ids = pe_exit.get("lot_ids")
    want_vol = pe_exit.get("shares")
    _log_sell_lot_can_use(now, day, lot_ids, want_vol, reason)
    ok = _order_sell(
        C,
        reason,
        px,
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
    return True


def _try_exec_pending_entry(
    C,
    now,
    now_s,
    day,
    tag,
    open_px,
    last_px,
    holding,
    cash,
    weekly_bear,
    w_bias_block,
    w_slope_block,
    vol_dry_block,
    w_detail,
    force_empty,
    sell_ok,
    stop_hit,
    trail_hit,
    time_force_hit,
):
    """成交就绪的 pending_entry。'done'=return；'force_eval'=让路卖点；None=继续。"""
    if str(getattr(A, "_universe_pass", "") or "") == "eval":
        return None
    pe_entry = getattr(A, "pending_entry", None)
    pe_is_add = isinstance(pe_entry, dict) and bool(pe_entry.get("add"))
    if not (
        ((not holding) or pe_is_add)
        and isinstance(pe_entry, dict)
        and (pe_is_add or ("BUY" not in getattr(A, "acted", set())))
        and _pending_ready(pe_entry, day, tag, "day")
    ):
        return None
    if pe_is_add and not holding:
        A.pending_entry = None
        _save_state()
        print("%s pending_entry cancel add_no_pos" % STRATEGY_NAME)
        _event_log("pending_entry_cancel", reason="add_no_pos")
        return "done"
    sell_block = bool(
        pe_is_add
        and (force_empty or sell_ok or stop_hit or trail_hit or time_force_hit)
    )
    scale_ok, scale_why = _scale_gate(w_detail, price=last_px) if pe_is_add else (True, "")
    if sell_block or (pe_is_add and (not scale_ok)):
        why = "scale_sell_block" if sell_block else scale_why
        A.pending_entry = None
        _save_state()
        print("%s pending_entry cancel %s" % (STRATEGY_NAME, why))
        _event_log(
            "pending_entry_cancel",
            reason=why,
            signal_day=pe_entry.get("signal_day"),
        )
        if sell_block:
            return "force_eval"
        return "done"
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
        return "done"
    if not _can_exec_signal_pending(pe_entry, day, now_s):
        _log_pending_defer_once("entry", day, now_s, pe_entry.get("signal_day"))
        return None
    if _equal_split_on() and (not _book_is_frozen(now_s)):
        _log_pending_defer_once("book", day, now_s, pe_entry.get("signal_day"))
        return None
    px, px_kind = _signal_exec_px(pe_entry, day, now_s, open_px, last_px)
    reasons = pe_entry.get("reasons") or []
    primary = reasons[0] if reasons else "entry"
    kind = "add" if pe_is_add else "buy"
    cap_ok, cap_why, snap = _fill_room_ok(px, opening=not pe_is_add)
    if isinstance(pe_entry, dict):
        pe_entry["book_frac"] = snap.get("frac")
        A.pending_entry = pe_entry
    if _dynamic_budget_on():
        _log_fill_budget(snap, kind)
    if cap_why in ("wait", "book_fail", "no_E"):
        _log_pending_defer_once(cap_why or "wait", day, now_s, pe_entry.get("signal_day"))
        return None
    if not cap_ok:
        A.pending_entry = None
        _save_state()
        why = cap_why or ("scale_cap" if pe_is_add else "buy_cap")
        print("%s pending_entry cancel %s" % (STRATEGY_NAME, why))
        _event_log(
            "pending_entry_cancel",
            reason=why,
            signal_day=pe_entry.get("signal_day"),
            E=snap.get("E"),
            N=snap.get("N"),
            k=snap.get("k"),
            reserve=snap.get("reserve"),
            lot=snap.get("lot"),
            book_mv=snap.get("book_mv"),
            other_mv=snap.get("other_mv"),
            name_mv=snap.get("name_mv"),
            n_buy=snap.get("n_buy"),
            why=snap.get("why"),
        )
        return "done"
    print(
        "%s %s by signal=%s label=%s all=%s signal_day=%s @%s=%.4f"
        % (
            STRATEGY_NAME,
            "BUY add" if pe_is_add else "BUY",
            primary,
            _reason_label(primary, "buy"),
            _format_reasons(reasons, "buy"),
            pe_entry.get("signal_day"),
            px_kind,
            px,
        )
    )
    _event_log(
        "buy_by_signal" if not pe_is_add else "buy_add_by_signal",
        signal=primary,
        label=_reason_label(primary, "buy"),
        all_reasons=_format_reasons(reasons, "buy"),
        signal_day=pe_entry.get("signal_day"),
        px=px,
        px_kind=px_kind,
        add=pe_is_add,
    )
    budget = float(snap.get("lot") or 0)
    ok = _order_buy(C, px, now, budget, add=pe_is_add, book_frac=snap.get("frac"))
    if ok:
        _on_signal_order_ok("buy", px=px, day=day, add=pe_is_add)
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
    return "done"


def _need_open_fallback(day, prev_closed, live_cc, phase):
    if not (live_cc and phase == "exec"):
        return False
    confirmed_day = str(getattr(A, "_confirmed_eval_day", "") or "")
    return (
        confirmed_day < str(prev_closed or "")
        and str(getattr(A, "_fallback_done_day", "") or "") != str(day)
        and (not isinstance(getattr(A, "pending_entry", None), dict))
        and (not isinstance(getattr(A, "pending_exit", None), dict))
    )


def _live_tick_open_last(C):
    """开盘成交价：优先 tick open/last；没有则该票补 2 根日 K。"""
    stock = str(getattr(A, "stock", "") or "")
    t = None
    try:
        t = _get_stock_tick(C, stock)
    except Exception:
        t = None
    last = _tick_field(t, ("lastPrice", "last", "price", "close"))
    open_px = _tick_field(
        t, ("open", "openPrice", "lastOpen", "openPx", "open_price")
    )
    if last > 0 and open_px > 0:
        return float(open_px), float(last), "tick"
    ohlcv = None
    try:
        key = "d1open"
        st = stock.replace(".", "_")
        if st:
            key = "d1open_%s" % st
        ohlcv = _get_ohlcv_period(C, stock, "1d", 2, 1, key)
    except Exception:
        ohlcv = None
    if ohlcv:
        opens_d, _h, _l, closes_d, _v = ohlcv
        op = float(opens_d[-1]) if opens_d else 0.0
        cl = float(closes_d[-1]) if closes_d else 0.0
        if op > 0 or cl > 0:
            return op if op > 0 else cl, cl if cl > 0 else op, "bar2"
    return 0.0, 0.0, "none"


def _handle_open_exec_no_fallback(C, ctx):
    """开盘无兜底：打卡 + tick 成交。True=结束该票；False=exec 轮买入需拉日+周。"""
    now = ctx["now"]
    now_s = ctx["now_s"]
    day = ctx["day"]
    tag = ctx["tag"]
    upass = str(getattr(A, "_universe_pass", "") or "")
    pe = getattr(A, "pending_entry", None)
    px = getattr(A, "pending_exit", None)
    holding = _has_position()
    if upass != "exec":
        if isinstance(pe, dict):
            return False
        buy_sig = False
        scale_sig = isinstance(pe, dict) and bool(pe.get("add"))
        sell_ok = isinstance(px, dict)
        force_empty = False
        if isinstance(px, dict):
            reasons = px.get("reasons") or []
            if str(px.get("reason") or "") == "weekly_bear" or "weekly_bear" in reasons:
                force_empty = True
        _sync_signal_book(
            day, now_s, buy_sig, scale_sig, holding, sell_ok, force_empty
        )
        if isinstance(px, dict):
            t_open, t_last, _src = _live_tick_open_last(C)
            if t_last > 0:
                _try_exec_pending_exit(
                    C,
                    now,
                    now_s,
                    day,
                    tag,
                    t_open if t_open > 0 else t_last,
                    t_last,
                    holding,
                )
        return True
    if isinstance(pe, dict):
        return False
    if isinstance(px, dict):
        t_open, t_last, _src = _live_tick_open_last(C)
        if t_last > 0:
            _try_exec_pending_exit(
                C,
                now,
                now_s,
                day,
                tag,
                t_open if t_open > 0 else t_last,
                t_last,
                holding,
            )
        return True
    return True


def _handle_clock_gate(C, from_timer=False):
    """实例门禁。from_timer 用墙钟、不算 is_last_bar。None=本轮跳过。"""
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    day = now.strftime("%Y%m%d")
    tag = _bar_tag(bar_dt)
    hhmm = _bar_hhmm(bar_dt if bt else now)
    live_cc = _live_close_confirm_on()
    conf_start = str(globals().get("SIGNAL_CONFIRM_START", "145600") or "145600")
    conf_end = str(globals().get("SIGNAL_CONFIRM_END", "160000") or "160000")
    in_exec = (not bt) and (DECISION_START <= now_s < conf_start)
    in_confirm = (not bt) and (conf_start <= now_s <= conf_end)
    phase = "bt" if bt else "live"
    live_work = ""
    if bt:
        _bt_roll_t1(day)
        _bt_recover_position(now=now)
        return {
            "bt": True,
            "now": now,
            "now_s": now_s,
            "day": day,
            "tag": tag,
            "hhmm": hhmm,
            "live_cc": live_cc,
            "phase": "bt",
            "live_work": "",
            "bar_dt": bar_dt,
        }
    if from_timer:
        fn = globals().get("_compute_live_work")
        if callable(fn):
            live_work = str(fn(now_s, day) or "")
        if not live_work:
            if not getattr(A, "_universe_loop", False):
                _live_heartbeat("outside_session")
            return None
        if live_work == "signal":
            phase = "confirm"
        elif live_work == "open_exec":
            phase = "exec"
        else:
            phase = "pending"
        return {
            "bt": False,
            "now": now,
            "now_s": now_s,
            "day": day,
            "tag": tag,
            "hhmm": hhmm,
            "live_cc": live_cc,
            "phase": phase,
            "live_work": live_work,
            "bar_dt": bar_dt,
        }
    if live_cc:
        if (not in_exec) and (not in_confirm):
            _live_heartbeat("outside_session")
            return None
        phase = "confirm" if in_confirm else "exec"
    else:
        if now_s < DECISION_START or now_s > DECISION_END:
            _live_heartbeat("outside_session")
            return None
        phase = "session"
    if LIVE_ONLY_LAST_BAR:
        try:
            if hasattr(C, "is_last_bar") and (not C.is_last_bar()):
                return None
        except Exception:
            pass
    _live_heartbeat(phase)
    return {
        "bt": False,
        "now": now,
        "now_s": now_s,
        "day": day,
        "tag": tag,
        "hhmm": hhmm,
        "live_cc": live_cc,
        "phase": phase,
        "live_work": "",
        "bar_dt": bar_dt,
    }


def _handle_stock(C, ctx):
    bt = ctx["bt"]
    now = ctx["now"]
    now_s = ctx["now_s"]
    day = ctx["day"]
    tag = ctx["tag"]
    hhmm = ctx["hhmm"]
    live_cc = ctx["live_cc"]
    phase = ctx["phase"]
    live_work = str(ctx.get("live_work") or "")
    upass = str(getattr(A, "_universe_pass", "") or "")
    # 收盘确认：用当日完整日 K；周 K 不含未收盘周（与回测 0000 原生 1w 一致）
    # 开盘：日 K 去未收盘根；周 K 同样不含未收盘周
    prev_d = False
    prev_w = False

    if not bt:
        if getattr(A, "pending", None):
            if _process_pending(C, now):
                if not getattr(A, "_universe_loop", False):
                    _live_heartbeat("pending")
                return
        if live_work == "pending":
            return

    _reset_day(day)

    if (not bt) and live_work == "open_exec":
        prev_closed = str(
            ctx.get("prev_closed")
            or getattr(A, "clock_prev_closed_day", "")
            or ""
        )
        need_fb_early = _need_open_fallback(day, prev_closed, live_cc, phase)
        if (not need_fb_early) and _handle_open_exec_no_fallback(C, ctx):
            return

    if (not bt) and live_work == "signal" and upass == "exec":
        pe_only = getattr(A, "pending_entry", None)
        px_only = getattr(A, "pending_exit", None)
        if not isinstance(pe_only, dict) and not isinstance(px_only, dict):
            return
        if (not isinstance(pe_only, dict)) and isinstance(px_only, dict):
            holding_x = _has_position()
            t_open, t_last, _src = _live_tick_open_last(C)
            if t_last > 0:
                _try_exec_pending_exit(
                    C,
                    now,
                    now_s,
                    day,
                    tag,
                    t_open if t_open > 0 else t_last,
                    t_last,
                    holding_x,
                )
            return

    cash = _available_cash()
    if cash is None:
        if live_work:
            cash = 0.0
        else:
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
        highs_s, lows_s, closes_s, vols_s = highs_d, lows_d, closes_d, vols_d
        closes_ws = closes_w
        sig_day_daily = day
        sig_day_weekly = day
    elif need_fallback or (live_cc and phase == "exec"):
        # 开盘兜底 / 盘中执行：日 K 去掉未收盘根，避免未完成日线误触 vol_dry 等；
        # 周 K 已在 _get_ohlcv_1w 丢掉未收盘周，与 confirm/回测一致
        # 日信号日=上一完整交易日；周线 streak 仍按今日计（看的是上一完整周）
        prev_d = True
        prev_w = False
        highs_s = _drop_forming_bar(highs_d)
        lows_s = _drop_forming_bar(lows_d)
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
        highs_s, lows_s, closes_s, vols_s = highs_d, lows_d, closes_d, vols_d
        closes_ws = closes_w
        sig_day_daily = day
        sig_day_weekly = day

    price = float(closes_s[-1])
    high_px = float(highs_s[-1])
    exec_open_px = open_px
    exec_last_px = price
    if (not bt) and live_work == "open_exec" and (not need_fallback):
        t_open, t_last, _src = _live_tick_open_last(C)
        if t_last > 0:
            exec_open_px = t_open if t_open > 0 else t_last
            exec_last_px = t_last
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
                or bool(getattr(A, "time_force_trend_skip", False))
                or bool(getattr(A, "round_scaled", False))
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
            or bool(getattr(A, "time_force_trend_skip", False))
            or bool(getattr(A, "round_scaled", False))
        ):
            _clear_hold_meta()
    else:
        _bump_hold_bars(day)
        if _update_hold_peak(high_px, cost):
            _save_state()

    stop_hit = False
    trail_hit = False
    time_force_hit = False
    skip_sell_eval = str(getattr(A, "_skip_sell_eval_day", "") or "") == str(day)
    force_empty_act = False if skip_sell_eval else bool(force_empty)
    if skip_sell_eval and holding:
        _log_skip_sell_eval_day(day)
        sell_ok = False
        sell_reasons = ["skip_add_bar"]
        exit_ids = []
        exit_shares = 0
    elif holding and _lots_enabled():
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
        skip_before = bool(getattr(A, "time_force_trend_skip", False))
        if holding and (not stop_hit) and (not trail_hit) and _time_force_hit(
            price, closes_s, getattr(A, "hold_bars", 0)
        ):
            time_force_hit = True
            sell_reasons = list(sell_reasons) + ["time_force"]
            sell_ok = True
        elif (
            holding
            and (
                (grace_before is None and getattr(A, "time_force_grace_until", None) is not None)
                or ((not skip_before) and bool(getattr(A, "time_force_trend_skip", False)))
            )
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
    scale_push_ok, scale_push_reasons = _eval_scale_push(
        closes_s,
        highs_s,
        lows_s,
        w_detail,
        pullback=("pullback_vol" in real_buys),
    )
    scale_ok, scale_why = _scale_gate(w_detail, price=price)
    scale_sig = bool(
        scale_ok
        and scale_push_ok
        and (not weekly_bear)
        and (not w_bias_block)
        and (not w_slope_block)
        and (not vol_dry_block)
    )

    if not bt and upass != "exec":
        _sync_signal_book(
            day,
            now_s,
            buy_sig,
            scale_sig,
            holding,
            sell_ok,
            force_empty_act,
        )

    pe_now = bool(getattr(A, "pending_entry", None))
    px_now = bool(getattr(A, "pending_exit", None))
    # 信号上升沿强制打；实盘其余按 LIVE_HEARTBEAT_SEC；回测 idle 用 status_idle
    force_bar_log = _bar_signal_rising_edge(buy_sig or scale_sig, sell_ok, force_empty)
    status_idle = (bool(holding) or pe_now or px_now) and (not force_bar_log)
    if upass != "exec" and _should_emit_bar_status(C, now, force_bar_log, status_idle):
        A.ready_logged = True
        if not getattr(A, "is_backtest", False):
            A._bar_status_at = now
        print(
            "%s" % STRATEGY_NAME,
            day,
            hhmm,
            "barpos=%s n1d=%d n1w=%d close=%.4f sig_d=%s sig_w=%s phase=%s prev_d=%s prev_w=%s "
            "w_bull=%s w_bear=%s w_bn=%s/%s w_ma5=%s w_ma30=%s w_hist=%s "
            "buy=%s buyR=%s scale=%s scaleR=%s sell=%s sellR=%s "
            "hold=%s nlot=%s ret=%s pe=%s px=%s bt_held=%s avail=%s"
            % (
                getattr(C, "barpos", "-"),
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
                scale_sig,
                (
                    ",".join(scale_push_reasons)
                    if scale_push_reasons
                    else (scale_why or "-")
                ),
                sell_ok or force_empty_act,
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
            scale=scale_sig,
            scaleR=(
                ",".join(scale_push_reasons)
                if scale_push_reasons
                else (scale_why or "-")
            ),
            sell=bool(sell_ok or force_empty_act),
            sellR=",".join((["weekly_bear"] if force_empty else []) + sell_reasons) or "-",
            hold=holding,
            nlot=_pos_lots() if holding else 0,
            ret=None if ret_pct is None else round(ret_pct * 100.0, 4),
            pe=pe_now,
            px=px_now,
        )

    # ---- 先执行挂起的卖/买（尾盘按收盘价；隔夜残留开盘按开盘价）----
    if _try_exec_pending_exit(C, now, now_s, day, tag, exec_open_px, exec_last_px, holding):
        return
    force_eval = False
    entry_act = _try_exec_pending_entry(
        C,
        now,
        now_s,
        day,
        tag,
        exec_open_px,
        exec_last_px,
        holding,
        cash,
        weekly_bear,
        w_bias_block,
        w_slope_block,
        vol_dry_block,
        w_detail,
        force_empty,
        sell_ok,
        stop_hit,
        trail_hit,
        time_force_hit,
    )
    if entry_act == "done":
        return
    if entry_act == "force_eval":
        force_eval = True
    if upass == "exec" and (not force_eval):
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
    if not allow_new and not force_eval:
        return

    if holding:
        cur_ex = getattr(A, "pending_exit", None)
        if force_empty_act or sell_ok or stop_hit or trail_hit or time_force_hit:
            if isinstance(cur_ex, dict):
                if live_cc:
                    _mark_signal_eval_done(day, is_confirm)
                return
            if force_empty_act:
                reason = "weekly_bear"
            elif stop_hit:
                reason = "stop_loss"
            elif trail_hit:
                reason = "trail_stop"
            elif time_force_hit:
                reason = "time_force"
            else:
                reason = sell_reasons[0] if sell_reasons else "SELL"
            reasons = (["weekly_bear"] if force_empty_act else []) + list(sell_reasons)
            seen = set()
            uniq = []
            for r in reasons:
                if r not in seen and r != "skip_add_bar":
                    seen.add(r)
                    uniq.append(r)
            # 周线清仓用 sig_w；日线卖点用 sig_d
            exit_sig_day = (
                sig_day_weekly
                if (force_empty_act or reason == "weekly_bear")
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
            _try_exec_pending_exit(C, now, now_s, day, tag, exec_open_px, exec_last_px, holding)
        elif scale_sig:
            if isinstance(getattr(A, "pending_entry", None), dict):
                if live_cc:
                    _mark_signal_eval_done(day, is_confirm)
                return
            A.pending_entry = {
                "signal_day": sig_day_daily,
                "signal_tag": tag,
                "close": price,
                "reasons": list(scale_push_reasons),
                "add": True,
            }
            A.pending_exit = None
            if live_cc:
                _mark_signal_eval_done(day, is_confirm)
            else:
                _save_state()
            primary = scale_push_reasons[0] if scale_push_reasons else "entry"
            print(
                "%s pending_entry set add signal=%s label=%s all=%s day=%s close=%.4f lots=%s phase=%s"
                % (
                    STRATEGY_NAME,
                    primary,
                    _reason_label(primary, "buy"),
                    _format_reasons(scale_push_reasons, "buy"),
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
                all_reasons=_format_reasons(scale_push_reasons, "buy"),
                signal_day=sig_day_daily,
                close=price,
                phase=phase,
                add=True,
            )
            _try_exec_pending_entry(
                C,
                now,
                now_s,
                day,
                tag,
                exec_open_px,
                exec_last_px,
                holding,
                cash,
                weekly_bear,
                w_bias_block,
                w_slope_block,
                vol_dry_block,
                w_detail,
                force_empty,
                sell_ok,
                stop_hit,
                trail_hit,
                time_force_hit,
            )
        elif live_cc:
            _mark_signal_eval_done(day, is_confirm)
        return

    if buy_sig and ("BUY" not in getattr(A, "acted", set())):
        if _book_n_held_live() >= _cfg_book_lot_max():
            if live_cc:
                _mark_signal_eval_done(day, is_confirm)
            print("%s skip open book_lot_cap n_held=%s" % (STRATEGY_NAME, _book_n_held_live()))
            _event_log("pending_entry_skip", reason="book_lot_cap", n_held=_book_n_held_live())
            return
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
        _try_exec_pending_entry(
            C,
            now,
            now_s,
            day,
            tag,
            exec_open_px,
            exec_last_px,
            holding,
            cash,
            weekly_bear,
            w_bias_block,
            w_slope_block,
            vol_dry_block,
            w_detail,
            force_empty,
            sell_ok,
            stop_hit,
            trail_hit,
            time_force_hit,
        )
    elif live_cc:
        _mark_signal_eval_done(day, is_confirm)


def _handle(C):
    ctx = _handle_clock_gate(C, from_timer=False)
    if ctx is None:
        return
    _handle_stock(C, ctx)
