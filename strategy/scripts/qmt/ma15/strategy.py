# === ma15/strategy.py ===
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


def _stock_allowed():
    code = str(globals().get("TRADE_CODE") or "").strip()
    if not code:
        return True
    stock = str(getattr(A, "stock", "") or "")
    return stock.startswith(code)


def _in_entry_window(hhmm):
    allow = globals().get("ENTRY_HHMM_ALLOW") or ()
    return str(hhmm) in set([str(x) for x in allow])


def _entry_fill_banned(hhmm):
    ban = globals().get("ENTRY_FILL_BAN") or ()
    return str(hhmm) in set([str(x) for x in ban])


def _prev_15m_dt(dt):
    if dt is None:
        return None
    h = int(dt.hour)
    m = int(dt.minute)
    if h == 13 and m == 15:
        return dt.replace(hour=11, minute=30, second=0, microsecond=0)
    if h == 9 and m == 45:
        prev = dt - datetime.timedelta(days=1)
        return prev.replace(hour=15, minute=0, second=0, microsecond=0)
    return dt - datetime.timedelta(minutes=15)


def _drop_live_forming(C, now, bar_dt):
    if getattr(A, "is_backtest", False):
        return False
    try:
        if hasattr(C, "is_last_bar") and (not C.is_last_bar()):
            return False
    except Exception:
        pass
    if now is None or bar_dt is None:
        return True
    return now < bar_dt


def _slice_ohlcv(opens, highs, lows, closes, vols):
    if closes is None or len(closes) < 2:
        return None
    return opens[:-1], highs[:-1], lows[:-1], closes[:-1], vols[:-1]


def _h1_ok(closes_h):
    ma_f = _sma(closes_h, H_MA_FAST)
    ma_s = _sma(closes_h, H_MA_SLOW)
    if ma_f is None or ma_s is None:
        return False, {}
    i = len(closes_h) - 1
    if i < 1:
        return False, {}
    f0 = _last_valid(ma_f, i)
    s0 = _last_valid(ma_s, i)
    f1 = _last_valid(ma_f, i - 1)
    detail = {"h_ma20": f0, "h_ma60": s0}
    if None in (f0, s0, f1):
        return False, detail
    ok = (f0 > s0) and (f0 >= f1)
    return ok, detail


def _trend_ok(closes):
    ma_f = _sma(closes, MA_FAST)
    ma_s = _sma(closes, MA_SLOW)
    if ma_f is None or ma_s is None:
        return False, None, None, {}
    i = len(closes) - 1
    if i < 1:
        return False, None, None, {}
    f0 = _last_valid(ma_f, i)
    s0 = _last_valid(ma_s, i)
    s1 = _last_valid(ma_s, i - 1)
    c0 = float(closes[i])
    detail = {"ma20": f0, "ma60": s0}
    if None in (f0, s0, s1):
        return False, ma_f, ma_s, detail
    ok = (f0 > s0) and (s0 >= s1) and (c0 > s0)
    return ok, ma_f, ma_s, detail


def _index_dump(opens, closes, vols):
    if not closes or len(closes) < int(VOL_MA_N):
        return True, "index_na_skip", {}
    i = len(closes) - 1
    o0 = float(opens[i])
    c0 = float(closes[i])
    v0 = float(vols[i])
    vm = _sma(vols, VOL_MA_N)
    vma = _last_valid(vm, i) if vm is not None else None
    detail = {"idx_ret": None if o0 <= 0 else (c0 - o0) / o0, "idx_vol": v0, "idx_mavol": vma}
    if o0 <= 0 or vma is None or vma <= 0:
        return True, "index_na_skip", detail
    ret = (c0 - o0) / o0
    dump = (ret <= float(INDEX_DUMP_RET)) and (v0 >= vma * float(INDEX_DUMP_VOL))
    if dump:
        return True, "index_dump_skip", detail
    return False, "", detail


def _vol_ok(closes, vols):
    i = len(closes) - 1
    v0 = float(vols[i])
    vm = _sma(vols, VOL_MA_N)
    vma = _last_valid(vm, i) if vm is not None else None
    if vma is None or vma <= 0:
        return False, {}
    if v0 >= vma * float(VOL_PULLBACK_RATIO):
        return False, {"mavol": vma, "vol": v0}
    return True, {"mavol": vma, "vol": v0}


def _eval_buy(opens, highs, lows, closes, vols, hhmm, h1_ok, idx_block, idx_why):
    reasons = []
    trend, ma20_arr, _ma60_arr, t_detail = _trend_ok(closes)
    detail = dict(t_detail)
    detail["trend_ok"] = trend
    if idx_block:
        return False, [idx_why or "index_na_skip"], detail
    if not h1_ok:
        return False, ["h1_skip"], detail
    if not trend:
        return False, ["trend_skip"], detail
    if not _in_entry_window(hhmm):
        return False, ["time_skip"], detail
    vok, v_detail = _vol_ok(closes, vols)
    detail.update(v_detail)
    if not vok:
        return False, ["vol_skip"], detail
    i = len(closes) - 1
    if i < 1:
        return False, ["short"], detail
    ma20 = _last_valid(ma20_arr, i)
    if ma20 is None or ma20 <= 0:
        return False, ["ma_na"], detail
    low = float(lows[i])
    close = float(closes[i])
    if low > ma20 * (1.0 + float(MA_TOUCH_TOL)):
        return False, ["touch_skip"], detail
    if close < ma20 * (1.0 - float(MA_BREAK_TOL)):
        return False, ["break_skip"], detail
    hammer = _is_hammer(opens[i], highs[i], lows[i], closes[i])
    bounce = _is_bounce(opens[i], highs[i], lows[i], closes[i])
    engulf = _is_engulf(
        opens[i - 1], closes[i - 1], opens[i], closes[i], vols[i - 1], vols[i]
    )
    if hammer:
        reasons.append("hammer")
    elif bounce:
        reasons.append("bounce")
    if engulf:
        reasons.append("engulf")
    if not reasons:
        return False, ["pattern_skip"], detail
    return True, reasons, detail


def _stall_hit(closes, ma20_arr, hold_bars, hold_max_ret):
    abort = float(globals().get("STALL_ABORT_RET") or 0)
    try:
        mx = float(hold_max_ret) if hold_max_ret is not None else 0.0
    except Exception:
        mx = 0.0
    if abort > 0 and mx >= abort:
        return False
    need = int(STALL_BARS)
    if hold_bars is None or int(hold_bars) < need:
        return False
    i = len(closes) - 1
    if i < need:
        return False
    ma_now = _last_valid(ma20_arr, i)
    ma_old = _last_valid(ma20_arr, i - need)
    if ma_now is None or ma_old is None or ma_now <= 0:
        return False
    band = float(STALL_BAND)
    for k in range(need):
        px = float(closes[i - k])
        ma = _last_valid(ma20_arr, i - k)
        if ma is None or ma <= 0:
            return False
        if abs(px - ma) / ma > band:
            return False
    flat = abs(ma_now - ma_old) / ma_now <= float(STALL_MA_FLAT)
    return flat


def _eval_sell(price, cost, close_peak, closes, ma20_arr, hold_bars, hhmm, hold_max_ret, trend_ok):
    reasons = []
    ma20 = _last_valid(ma20_arr, -1) if ma20_arr is not None else None
    stop_after = str(globals().get("STOP_MA_AFTER_HHMM") or "1015")
    if (
        ma20 is not None
        and ma20 > 0
        and str(hhmm) >= stop_after
        and price < ma20 * (1.0 - float(STOP_MA_PCT))
    ):
        reasons.append("stop_ma")
        return True, reasons
    if cost > 0 and price <= cost * (1.0 - float(STOP_LOSS)):
        reasons.append("stop_loss")
        return True, reasons
    try:
        mx = float(hold_max_ret) if hold_max_ret is not None else 0.0
    except Exception:
        mx = 0.0
    abort_tb = float(globals().get("TREND_BREAK_ABORT_RET") or 0.001)
    min_red = float(globals().get("TREND_BREAK_MIN_RET") or -0.004)
    cur_ret = (price - cost) / cost if cost > 0 else 0.0
    if (
        (not trend_ok)
        and cost > 0
        and cur_ret <= min_red
        and mx < abort_tb
        and str(hhmm) >= stop_after
    ):
        reasons.append("trend_break")
        return True, reasons
    if cost > 0:
        ret = (price - cost) / cost
        hard_tp = bool(globals().get("TAKE_PROFIT_HARD"))
        leave_ok = (ma20 is not None and ma20 > 0 and price >= ma20 * (1.0 + float(TAKE_LEAVE)))
        if hard_tp and ret >= float(TAKE_PROFIT) and leave_ok:
            wait_scale = False
            if bool(globals().get("SCALE_ENABLE")) and trend_ok:
                max_lots = int(globals().get("SCALE_MAX") or 1)
                giveup = int(globals().get("SCALE_GIVEUP_BARS") or 0)
                lots = 1
                pos = getattr(A, "position", None)
                if isinstance(pos, dict):
                    try:
                        lots = max(1, int(pos.get("lots", 1) or 1))
                    except Exception:
                        lots = 1
                arm = float(globals().get("SCALE_ARM") or TAKE_PROFIT)
                bars = int(hold_bars or 0)
                if lots < max_lots and mx >= arm and (giveup <= 0 or bars < giveup):
                    wait_scale = True
            if not wait_scale:
                reasons.append("take_profit")
                return True, reasons
    if close_peak is not None and cost > 0:
        pk = float(close_peak)
        peak_ret = (pk - float(cost)) / float(cost) if pk > 0 else 0.0
        arm = float(TAKE_PROFIT)
        if peak_ret >= arm and pk > 0:
            gb = float(GIVEBACK)
            tight_after = float(globals().get("GIVEBACK_TIGHT_AFTER") or 0)
            tight = float(globals().get("GIVEBACK_TIGHT") or 0)
            if tight_after > 0 and tight > 0 and peak_ret >= tight_after:
                gb = tight
            if (pk - price) / pk >= gb:
                reasons.append("giveback")
                return True, reasons
    if _stall_hit(closes, ma20_arr, hold_bars, hold_max_ret):
        reasons.append("stall")
        return True, reasons
    return False, reasons


def _clear_hold_meta():
    A.hold_peak = None
    A.hold_close_peak = None
    A.hold_max_ret = 0.0
    A.hold_bars = 0
    A._hold_count_bar = ""


def _bump_hold_bars(bar_tag):
    if getattr(A, "_hold_count_bar", "") == bar_tag:
        return
    A.hold_bars = int(getattr(A, "hold_bars", 0) or 0) + 1
    A._hold_count_bar = bar_tag


def _update_peaks(high_px, close_px, cost):
    hi = float(high_px)
    cl = float(close_px)
    changed = False
    peak = getattr(A, "hold_peak", None)
    if peak is None:
        base = float(cost) if cost and cost > 0 else hi
        A.hold_peak = max(base, hi)
        changed = True
    elif hi > float(peak):
        A.hold_peak = hi
        changed = True
    cp = getattr(A, "hold_close_peak", None)
    if cp is None:
        A.hold_close_peak = cl
        changed = True
    elif cl > float(cp):
        A.hold_close_peak = cl
        changed = True
    if cost and float(cost) > 0:
        r_cl = (cl - float(cost)) / float(cost)
        r_hi = (hi - float(cost)) / float(cost)
        mx = max(r_cl, r_hi)
        prev = getattr(A, "hold_max_ret", None)
        try:
            prev_f = float(prev) if prev is not None else None
        except Exception:
            prev_f = None
        if prev_f is None or mx > prev_f:
            A.hold_max_ret = mx
            changed = True
    return changed


def _pos_lots():
    pos = getattr(A, "position", None)
    if not isinstance(pos, dict):
        return 0
    try:
        return max(1, int(pos.get("lots", 1) or 1))
    except Exception:
        return 1


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
    try:
        mx = float(getattr(A, "hold_max_ret", 0) or 0)
    except Exception:
        mx = 0.0
    arm = float(globals().get("SCALE_ARM") or 0)
    if arm <= 0:
        arm = float(TAKE_PROFIT)
    return mx >= arm


def _pending_ready(pend, day, exec_tag):
    if not isinstance(pend, dict):
        return False
    sig_tag = str(pend.get("signal_tag", "") or "")
    if sig_tag and exec_tag:
        return sig_tag < exec_tag
    sig_day = str(pend.get("signal_day", "") or "")
    return bool(sig_day) and sig_day < day


def _reset_peaks_after_scale(px):
    """加仓后回吐从新高起算，不把第一笔收盘最高带到更低均价上。"""
    if not bool(globals().get("SCALE_RESET_PEAK", True)):
        return
    try:
        pxf = float(px) if px else 0.0
    except Exception:
        pxf = 0.0
    if pxf <= 0:
        return
    A.hold_peak = pxf
    A.hold_close_peak = pxf
    cost = _pos_cost_price()
    try:
        cost_f = float(cost) if cost else 0.0
    except Exception:
        cost_f = 0.0
    prev = float(getattr(A, "hold_max_ret", 0) or 0)
    if cost_f > 0:
        A.hold_max_ret = max(prev, (pxf - cost_f) / cost_f)
    print(
        "%s scale peak reset px=%.4f avg=%.4f max_ret=%.2f%%"
        % (STRATEGY_NAME, pxf, cost_f, float(A.hold_max_ret) * 100.0)
    )
    _event_log("scale_peak_reset", px=pxf, avg=cost_f, max_ret=A.hold_max_ret)


def _after_signal_buy_filled(px, day, add=False):
    A.pending_entry = None
    A.pending_exit = None
    if add:
        _reset_peaks_after_scale(px)
        _save_state()
        return
    try:
        A.hold_peak = float(px) if px else None
    except Exception:
        A.hold_peak = None
    A.hold_close_peak = A.hold_peak
    A.hold_max_ret = 0.0
    A.hold_bars = 0
    A._hold_count_bar = ""
    _save_state()


def _after_signal_sell_filled():
    A.pending_exit = None
    A.pending_entry = None
    _clear_hold_meta()
    acted = getattr(A, "acted", None)
    if isinstance(acted, set):
        acted.discard("BUY")
        acted.discard("SELL")
    _save_state()


def _pending_on_buy_fill(pend, vol, px):
    extra = pend.get("extra_pos") if isinstance(pend.get("extra_pos"), dict) else {}
    _apply_buy_fill(vol, px, pend.get("opened_at") or pend.get("submitted_at"), **extra)
    ot = str(pend.get("opened_at") or pend.get("submitted_at") or "")
    day = ot[:8] if len(ot) >= 8 else datetime.datetime.now().strftime("%Y%m%d")
    _after_signal_buy_filled(px, day, add=bool(extra.get("add")))


def _pending_on_sell_fill(pend, now, vol, px):
    intent = str(pend.get("intent", "") or "")
    last_hint = pend.get("last_hint")
    if last_hint is None:
        last_hint = px
    mark_half = bool(pend.get("mark_half"))
    _apply_sell_fill(now, intent, last_hint, vol, mark_half=mark_half)
    if not _has_position() and not (
        getattr(A, "is_backtest", False) and _bt_held_vol() >= 100
    ):
        _after_signal_sell_filled()
    else:
        A.pending_exit = None
        _save_state()


def _on_signal_order_ok(side, px=None, day=None, add=False):
    live_waiting = (not getattr(A, "is_backtest", False)) and (
        not DRY_RUN
    ) and isinstance(getattr(A, "pending", None), dict)
    if live_waiting:
        print("%s %s submitted keep signal pending until fill" % (STRATEGY_NAME, side))
        _event_log("signal_pending_keep_until_fill", side=side)
        _save_state()
        return
    if side == "buy":
        _after_signal_buy_filled(px, day, add=add)
    else:
        _after_signal_sell_filled()


_SELL_LABELS = {
    "stop_ma": "MA20硬止损",
    "stop_loss": "成本止损",
    "trend_break": "15m趋势破坏",
    "stall": "贴线动能衰竭",
    "take_profit": "浮盈止盈",
    "giveback": "收盘最高回吐",
}
_BUY_LABELS = {
    "hammer": "长脚十字/假阴护盘",
    "bounce": "回踩收阳",
    "engulf": "放量反包",
    "time_skip": "时段过滤",
    "vol_skip": "缩量未达标",
    "h1_skip": "小时趋势未向上",
    "trend_skip": "15m非多头排列",
    "index_dump_skip": "大盘放量杀跌",
    "index_na_skip": "指数数据缺失",
    "touch_skip": "未触及MA20",
    "break_skip": "收盘有效跌破MA20",
    "pattern_skip": "无锤子/回踩阳/反包",
    "entry_expire": "买入pending隔日作废",
    "entry_late_skip": "尾盘不买",
}


def _reason_label(code, kind="sell"):
    code = str(code or "")
    table = _SELL_LABELS if kind == "sell" else _BUY_LABELS
    return table.get(code, code)


def _format_reasons(codes, kind="sell"):
    codes = [str(x) for x in (codes or []) if x]
    if not codes:
        return "-"
    return ",".join(["%s(%s)" % (c, _reason_label(c, kind)) for c in codes])


def _mark_eval(tag):
    A._eval_bar_tag = str(tag or "")
    _save_state()


def _should_log_bar(C, now, force):
    if force:
        return True
    if getattr(A, "is_backtest", False):
        try:
            return int(getattr(C, "barpos", 0) or 0) % 16 == 0
        except Exception:
            return True
    sec = int(globals().get("LIVE_HEARTBEAT_SEC") or 60)
    last = getattr(A, "_bar_status_at", None)
    if last is not None and now is not None and sec > 0:
        try:
            if (now - last).total_seconds() < float(sec):
                return False
        except Exception:
            pass
    return True


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    day = now.strftime("%Y%m%d")
    tag = _bar_tag(bar_dt)

    if not _stock_allowed():
        _diag_once("stock_skip", "want=", TRADE_CODE, "got=", getattr(A, "stock", ""))
        return

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
        _live_heartbeat("session")
    else:
        _bt_roll_t1(day)
        _bt_recover_position(now=now)

    _reset_day(day)

    cash = _available_cash()
    if cash is None:
        _live_heartbeat("no_cash_or_login")
        return

    ohlcv = _get_ohlcv_15m(C, A.stock)
    if ohlcv is None:
        _live_heartbeat("ohlcv_15m_none")
        return
    opens, highs, lows, closes, vols = ohlcv
    exec_open = float(opens[-1])
    exec_tag = tag
    drop = _drop_live_forming(C, now, bar_dt)
    if drop:
        sliced = _slice_ohlcv(opens, highs, lows, closes, vols)
        if sliced is None:
            _live_heartbeat("ohlcv_forming_short")
            return
        opens, highs, lows, closes, vols = sliced
        complete_dt = _prev_15m_dt(bar_dt)
    else:
        complete_dt = bar_dt
    complete_tag = _bar_tag(complete_dt)
    sig_hhmm = _bar_hhmm(complete_dt)
    sig_day = complete_dt.strftime("%Y%m%d") if complete_dt else day
    end_sig = complete_dt.strftime("%Y%m%d%H%M%S") if complete_dt else None

    if len(closes) < max(int(MA_SLOW), 80):
        _diag_once("m15_short", "n=", len(closes))
        return

    ohlcv_h = _get_ohlcv_1h(C, A.stock, end=end_sig)
    if ohlcv_h is None:
        _live_heartbeat("ohlcv_1h_none")
        return
    _oh, _hh, _lh, closes_h, _vh = ohlcv_h
    if drop and closes_h is not None and len(closes_h) >= 2:
        closes_h = list(closes_h[:-1])
    if closes_h is None or len(closes_h) < int(H_MA_SLOW) + 2:
        _diag_once("h1_short", "n=", 0 if not closes_h else len(closes_h))
        return

    idx = _get_ohlcv_index_15m(C, end=end_sig)
    idx_block = False
    idx_why = ""
    idx_detail = {}
    if idx is None:
        idx_block = True
        idx_why = "index_na_skip"
    else:
        io, _ih, _il, ic, iv = idx
        if drop and ic is not None and len(ic) >= 2:
            io, ic, iv = io[:-1], ic[:-1], iv[:-1]
        idx_block, idx_why, idx_detail = _index_dump(io, ic, iv)

    price = float(closes[-1])
    high_px = float(highs[-1])
    if bt:
        _bt_recover_position(now=now, last=price)

    h1_ok, h_detail = _h1_ok(closes_h)
    buy_ok, buy_reasons, b_detail = _eval_buy(
        opens, highs, lows, closes, vols, sig_hhmm, h1_ok, idx_block, idx_why
    )
    ma20_arr = _sma(closes, MA_FAST)

    holding = _has_position() or (bt and _bt_held_vol() >= 100)
    cost = _pos_cost_price()
    if not holding:
        if (
            getattr(A, "hold_peak", None) is not None
            or getattr(A, "hold_close_peak", None) is not None
            or int(getattr(A, "hold_bars", 0) or 0)
            or float(getattr(A, "hold_max_ret", 0) or 0)
        ):
            _clear_hold_meta()
    else:
        _bump_hold_bars(complete_tag)
        if _update_peaks(high_px, price, cost):
            _save_state()

    sell_ok, sell_reasons = False, []
    if holding:
        sell_ok, sell_reasons = _eval_sell(
            price,
            cost,
            getattr(A, "hold_close_peak", None),
            closes,
            ma20_arr,
            getattr(A, "hold_bars", 0),
            sig_hhmm,
            getattr(A, "hold_max_ret", 0),
            bool(b_detail.get("trend_ok")),
        )

    skip_codes = (
        "time_skip",
        "vol_skip",
        "h1_skip",
        "trend_skip",
        "index_dump_skip",
        "index_na_skip",
        "touch_skip",
        "break_skip",
        "pattern_skip",
        "ma_na",
        "short",
    )
    real_buys = [r for r in buy_reasons if r not in skip_codes]
    buy_sig = bool(real_buys)

    pe_now = bool(getattr(A, "pending_entry", None))
    px_now = bool(getattr(A, "pending_exit", None))
    ret_pct = None
    if holding and cost > 0:
        ret_pct = (price - cost) / cost
    if _should_log_bar(C, now, bool(buy_sig or sell_ok)):
        if not bt:
            A._bar_status_at = now
        print(
            "%s" % STRATEGY_NAME,
            day,
            sig_hhmm,
            "n15=%d n1h=%d close=%.4f drop=%s "
            "h1=%s buy=%s buyR=%s sell=%s sellR=%s hold=%s ret=%s pe=%s px=%s"
            % (
                len(closes),
                len(closes_h),
                price,
                drop,
                h1_ok,
                buy_sig,
                ",".join(buy_reasons) if buy_reasons else "-",
                sell_ok,
                ",".join(sell_reasons) if sell_reasons else "-",
                holding,
                None if ret_pct is None else ("%.2f%%" % (ret_pct * 100.0)),
                pe_now,
                px_now,
            ),
        )
        _bar_log(
            day=day,
            hhmm=sig_hhmm,
            n15=len(closes),
            n1h=len(closes_h),
            close=round(price, 6),
            drop=drop,
            h1=h1_ok,
            buy=buy_sig,
            buyR=",".join(buy_reasons) if buy_reasons else "-",
            sell=sell_ok,
            sellR=",".join(sell_reasons) if sell_reasons else "-",
            hold=holding,
            ret=None if ret_pct is None else round(ret_pct * 100.0, 4),
            pe=pe_now,
            px=px_now,
            idx=idx_why or "-",
            ma20=None if b_detail.get("ma20") is None else round(b_detail["ma20"], 4),
            h_ma20=None if h_detail.get("h_ma20") is None else round(h_detail["h_ma20"], 4),
        )

    pe_entry = getattr(A, "pending_entry", None)
    if isinstance(pe_entry, dict):
        sig_d = str(pe_entry.get("signal_day", "") or "")
        if sig_d and sig_d < day:
            A.pending_entry = None
            _save_state()
            print("%s pending_entry cancel entry_expire signal_day=%s" % (STRATEGY_NAME, sig_d))
            _event_log("pending_entry_cancel", reason="entry_expire", signal_day=sig_d)
            pe_entry = None

    pe_exit = getattr(A, "pending_exit", None)
    if holding and isinstance(pe_exit, dict) and _pending_ready(pe_exit, day, exec_tag):
        reason = str(pe_exit.get("reason", "SELL") or "SELL")
        reasons = pe_exit.get("reasons") or [reason]
        print(
            "%s SELL by signal=%s label=%s all=%s signal_day=%s signal_tag=%s @open=%.4f"
            % (
                STRATEGY_NAME,
                reason,
                _reason_label(reason, "sell"),
                _format_reasons(reasons, "sell"),
                pe_exit.get("signal_day"),
                pe_exit.get("signal_tag"),
                exec_open,
            )
        )
        _event_log(
            "sell_by_signal",
            signal=reason,
            signal_tag=pe_exit.get("signal_tag"),
            open=exec_open,
        )
        ok = _order_sell(C, reason, exec_open, now)
        if ok:
            _on_signal_order_ok("sell")
        else:
            print("%s pending_exit keep after sell fail/skip signal=%s" % (STRATEGY_NAME, reason))
            _event_log("pending_exit_keep_after_fail", sell_reason=reason)
        return

    pe_entry = getattr(A, "pending_entry", None)
    exec_hhmm = _bar_hhmm(bar_dt)
    pe_is_add = isinstance(pe_entry, dict) and bool(pe_entry.get("add"))
    if (
        ((not holding) or pe_is_add)
        and isinstance(pe_entry, dict)
        and _pending_ready(pe_entry, day, exec_tag)
        and _entry_fill_banned(exec_hhmm)
    ):
        A.pending_entry = None
        _save_state()
        print(
            "%s pending_entry cancel entry_late_skip hhmm=%s signal_day=%s"
            % (STRATEGY_NAME, exec_hhmm, pe_entry.get("signal_day"))
        )
        _event_log(
            "pending_entry_cancel",
            reason="entry_late_skip",
            hhmm=exec_hhmm,
            signal_day=pe_entry.get("signal_day"),
        )
        return

    pe_entry = getattr(A, "pending_entry", None)
    pe_is_add = isinstance(pe_entry, dict) and bool(pe_entry.get("add"))
    if (
        ((not holding) or pe_is_add)
        and isinstance(pe_entry, dict)
        and _pending_ready(pe_entry, day, exec_tag)
    ):
        if pe_is_add and not holding:
            A.pending_entry = None
            _save_state()
            print("%s pending_entry cancel add_no_pos" % STRATEGY_NAME)
            _event_log("pending_entry_cancel", reason="add_no_pos")
            return
        reasons = pe_entry.get("reasons") or []
        primary = reasons[0] if reasons else "entry"
        kind = "add" if pe_is_add else "buy"
        print(
            "%s %s by signal=%s label=%s all=%s signal_day=%s signal_tag=%s @open=%.4f"
            % (
                STRATEGY_NAME,
                "BUY add" if pe_is_add else "BUY",
                primary,
                _reason_label(primary, "buy"),
                _format_reasons(reasons, "buy"),
                pe_entry.get("signal_day"),
                pe_entry.get("signal_tag"),
                exec_open,
            )
        )
        _event_log(
            "buy_by_signal" if not pe_is_add else "buy_add_by_signal",
            signal=primary,
            signal_tag=pe_entry.get("signal_tag"),
            open=exec_open,
            add=pe_is_add,
        )
        budget = _buy_budget(cash)
        ok = _order_buy(C, exec_open, now, budget, add=pe_is_add)
        if ok:
            _on_signal_order_ok("buy", px=exec_open, day=day, add=pe_is_add)
        else:
            print(
                "%s pending_entry keep after %s fail/skip signal=%s"
                % (STRATEGY_NAME, kind, primary)
            )
            _event_log("pending_entry_keep_after_fail", signal=primary, add=pe_is_add)
        return

    if str(getattr(A, "_eval_bar_tag", "") or "") == complete_tag:
        return

    if holding:
        if sell_ok:
            if isinstance(getattr(A, "pending_exit", None), dict):
                _mark_eval(complete_tag)
                return
            reason = sell_reasons[0] if sell_reasons else "SELL"
            A.pending_exit = {
                "reason": reason,
                "signal_day": sig_day,
                "signal_tag": complete_tag,
                "close": price,
                "reasons": list(sell_reasons),
            }
            A.pending_entry = None
            _mark_eval(complete_tag)
            print(
                "%s pending_exit set signal=%s label=%s all=%s tag=%s close=%.4f"
                % (
                    STRATEGY_NAME,
                    reason,
                    _reason_label(reason, "sell"),
                    _format_reasons(sell_reasons, "sell"),
                    complete_tag,
                    price,
                )
            )
            _event_log(
                "pending_exit_set",
                signal=reason,
                signal_tag=complete_tag,
                close=price,
            )
        elif buy_sig and _scale_ready():
            if isinstance(getattr(A, "pending_entry", None), dict):
                _mark_eval(complete_tag)
                return
            A.pending_entry = {
                "signal_day": sig_day,
                "signal_tag": complete_tag,
                "close": price,
                "reasons": list(real_buys),
                "add": True,
            }
            A.pending_exit = None
            _mark_eval(complete_tag)
            primary = real_buys[0] if real_buys else "entry"
            print(
                "%s pending_entry set add signal=%s label=%s all=%s tag=%s close=%.4f lots=%s"
                % (
                    STRATEGY_NAME,
                    primary,
                    _reason_label(primary, "buy"),
                    _format_reasons(real_buys, "buy"),
                    complete_tag,
                    price,
                    _pos_lots(),
                )
            )
            _event_log(
                "pending_entry_set",
                signal=primary,
                signal_tag=complete_tag,
                close=price,
                add=True,
            )
        else:
            _mark_eval(complete_tag)
        return

    if buy_sig:
        if isinstance(getattr(A, "pending_entry", None), dict):
            _mark_eval(complete_tag)
            return
        A.pending_entry = {
            "signal_day": sig_day,
            "signal_tag": complete_tag,
            "close": price,
            "reasons": list(real_buys),
        }
        A.pending_exit = None
        _mark_eval(complete_tag)
        primary = real_buys[0] if real_buys else "entry"
        print(
            "%s pending_entry set signal=%s label=%s all=%s tag=%s close=%.4f"
            % (
                STRATEGY_NAME,
                primary,
                _reason_label(primary, "buy"),
                _format_reasons(real_buys, "buy"),
                complete_tag,
                price,
            )
        )
        _event_log(
            "pending_entry_set",
            signal=primary,
            signal_tag=complete_tag,
            close=price,
        )
    else:
        _mark_eval(complete_tag)
