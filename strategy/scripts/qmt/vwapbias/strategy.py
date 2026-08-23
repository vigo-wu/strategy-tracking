# === vwapbias/strategy.py ===
def _t6(x):
    s = str(x or "").strip().replace(":", "")
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return "000000"
    return digits.zfill(6)[-6:]


def _bar_hhmmss(dt):
    if dt is None:
        return "000000"
    return dt.strftime("%H%M%S")


def _session_phase(t6):
    t = _t6(t6)
    start = _t6(globals().get("DECISION_START") or "093000")
    end = _t6(globals().get("DECISION_END") or "150000")
    lunch_a = _t6(globals().get("LUNCH_START") or "113000")
    lunch_b = _t6(globals().get("LUNCH_END") or "130000")
    warm_am = _t6(globals().get("OPEN_SKIP_AM_END") or "093500")
    warm_pm_a = _t6(globals().get("OPEN_SKIP_PM_START") or "130000")
    warm_pm_b = _t6(globals().get("OPEN_SKIP_PM_END") or "130500")
    no_new = _t6(globals().get("NO_NEW_ENTRY") or "144000")
    flat = _t6(globals().get("FLAT_START") or "145000")
    if t < start or t > end:
        return "closed"
    if lunch_a <= t < lunch_b:
        return "lunch"
    if (start <= t < warm_am) or (warm_pm_a <= t < warm_pm_b):
        return "warmup"
    if flat <= t <= end:
        return "flatten"
    if no_new <= t < flat:
        return "sell_only"
    return "trade"


def _max_lots():
    mx = int(globals().get("SCALE_MAX") or 2)
    if bool(globals().get("ENABLE_L3")):
        return max(mx, 3)
    return max(1, min(mx, 2))


def _lot_budget(weight):
    cap = _trade_budget_cap()
    return float(cap) * float(weight)


def _reset_acted_bar(tag):
    if str(getattr(A, "acted_closed", "") or "") == str(tag):
        return
    A.acted_closed = str(tag)
    A.acted = set()


def _profit_lot_ids(price):
    ids = []
    lots = _ensure_lots() if _lots_enabled() else []
    if not lots:
        return ids
    px = float(price)
    for lot in lots:
        try:
            cost = float(lot.get("price") or 0)
            lid = int(lot.get("id") or 0)
        except Exception:
            continue
        if lid and cost > 0 and px >= cost:
            ids.append(lid)
    return ids


def _tp_lot_ids(price, tp):
    ids = []
    tp = float(tp or 0)
    if tp <= 0:
        return ids
    lots = _ensure_lots() if _lots_enabled() else []
    if not lots:
        return ids
    px = float(price)
    for lot in lots:
        try:
            cost = float(lot.get("price") or 0)
            lid = int(lot.get("id") or 0)
        except Exception:
            continue
        if lid and cost > 0 and (px - cost) / cost >= tp:
            ids.append(lid)
    return ids


def _univ_skip_reason(stock, day, px, tick, C):
    expect = str(globals().get("EXPECT_STOCK") or "").strip().upper()
    if expect and str(stock).upper() != expect:
        return "wrong_symbol"
    for bad in (globals().get("FORBID_STOCKS") or ()):
        if str(stock).upper() == str(bad).upper():
            return "forbid_stock"
    adv_min = float(globals().get("ADV_MIN") or 0)
    if adv_min > 0:
        adv = _get_daily_adv(C, stock, day)
        if adv is None:
            if not getattr(A, "is_backtest", False):
                return "adv_unknown"
        elif adv < adv_min:
            return "adv"
    spread_max = float(globals().get("SPREAD_MAX") or 0)
    if (not getattr(A, "is_backtest", False)) and spread_max > 0:
        sp = _tick_spread(tick)
        if sp is not None and sp > spread_max:
            return "spread"
    near = float(globals().get("LIMIT_NEAR") or 0)
    if near > 0 and px and px > 0:
        pre = _tick_num(tick, "lastClose")
        if pre is None:
            pre = _get_prev_close(C, stock, day)
        if pre and pre > 0:
            ret = abs(float(px) / float(pre) - 1.0)
            if ret >= near:
                return "limit"
    return None


def _try_sell(C, reason, price, now, lot_ids=None):
    ok = _order_sell(C, reason, price, now, lot_ids=lot_ids)
    if ok:
        print(_strategy_tag(), reason, "px=", round(float(price), 4))
        _event_log("sell_signal", sell_reason=reason, price=price, lot_ids=lot_ids)
    return ok


def _try_buy(C, tag, price, now, weight, add):
    budget = _lot_budget(weight)
    ok = _order_buy(C, price, now, budget=budget, add=add)
    if ok:
        A.hold_peak_ret = None
        print(_strategy_tag(), tag, "px=", round(float(price), 4), "budget=", round(budget, 2))
        _event_log("buy_signal", tag=tag, price=price, budget=budget, add=add)
    return ok


def _mark_after_sell():
    A.hold_peak_ret = None
    holding = _has_position() or (
        getattr(A, "is_backtest", False) and _bt_held_vol() >= _vol_step()
    )
    if holding:
        A.scale_out_lock = True
    else:
        A.scale_out_lock = False


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    day = now.strftime("%Y%m%d")

    if not bt:
        if getattr(A, "pending", None):
            if _process_pending(C, now):
                _live_heartbeat("pending")
                return
        if now_s < _t6(DECISION_START) or now_s > _t6(DECISION_END):
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

    if bt:
        nprog = int(getattr(A, "_bt_prog", 0) or 0) + 1
        A._bt_prog = nprog
        if nprog <= 5 or nprog % 120 == 0:
            print(
                _strategy_tag(),
                "progress n=",
                nprog,
                "barpos=",
                getattr(C, "barpos", None),
                "day=",
                day,
                "now=",
                now.strftime("%Y%m%d%H%M%S"),
            )

    cash = _available_cash()
    if cash is None:
        _live_heartbeat("no_cash_or_login")
        return

    pack = _get_ohlcv_1m(C, A.stock)
    if pack is None:
        _live_heartbeat("ohlcv_1m_none")
        return
    opens, highs, lows, closes, volumes, amounts, times = pack
    today_idx = _today_indices(times, day)
    if not today_idx:
        _diag_once(
            "no_today_1m",
            "day=",
            day,
            "n=",
            len(times or []),
            "t0=",
            times[0] if times else "",
            "t1=",
            times[-1] if times else "",
            "barpos=",
            getattr(C, "barpos", None),
        )
        nprog = int(getattr(A, "_bt_prog", 0) or 0)
        if (not bt) or nprog <= 5:
            print(
                _strategy_tag(),
                "no_today_1m",
                "day=",
                day,
                "t0=",
                times[0] if times else "",
                "t1=",
                times[-1] if times else "",
            )
        return

    if bt:
        closed_i = today_idx[-1]
    else:
        if len(today_idx) < 2:
            _live_heartbeat("no_closed_1m")
            return
        closed_i = today_idx[-2]

    closed_tag = times[closed_i] if closed_i < len(times) else now.strftime("%Y%m%d%H%M%S")
    if str(getattr(A, "acted_closed", "") or "") == str(closed_tag):
        if not bt:
            _live_heartbeat("acted_bar")
        return
    _reset_acted_bar(closed_tag)

    sig_s = closed_tag[8:14] if len(closed_tag) >= 14 else now_s
    session_s = now_s if not bt else sig_s
    phase = _session_phase(session_s)

    day_closed = [j for j in today_idx if j <= closed_i]
    vwap, vwap_src = _cum_vwap(amounts, volumes, highs, lows, closes, day_closed)
    px = float(closes[closed_i])
    bias = _bias_of(px, vwap)

    tick = None if bt else _get_tick(C, A.stock)
    live_px = _tick_num(tick, "lastPrice") if tick else None
    if live_px is None:
        live_px = px
    stop_px = live_px if not bt else px
    tick_vw = _tick_vwap(tick) if tick else None

    holding = _has_position() or (bt and _bt_held_vol() >= _vol_step())
    if holding and (not _has_position()):
        _bt_recover_position(now=now, last=px)

    if vwap is None or bias is None:
        print(_strategy_tag(), "vwap not ready", "src=", vwap_src, "bar=", closed_tag)
        _event_log("vwap_skip", vwap_src=vwap_src, bar=closed_tag)
        A.acted_closed = closed_tag
        _save_state()
        return

    if not getattr(A, "ready_logged", False):
        A.ready_logged = True
        print(
            _strategy_tag(),
            "ready",
            A.stock,
            "VOL_STEP=",
            _vol_step(),
            "ALLOW_T0=",
            ALLOW_T0,
            "SCALE_LOTS=",
            SCALE_LOTS,
        )

    noisy = (
        bt
        or holding
        or (abs(float(bias)) >= abs(float(BIAS_L1)))
        or phase in ("flatten", "sell_only", "warmup")
        or str(getattr(A, "_printed_day", "") or "") != day
    )
    if noisy:
        A._printed_day = day
        print(
            _strategy_tag(),
            "bar",
            closed_tag,
            "phase=",
            phase,
            "close=",
            round(px, 4),
            "vwap=",
            round(float(vwap), 4),
            "vwap_src=",
            vwap_src,
            "bias=",
            round(float(bias) * 100.0, 3),
            "tick_vwap=",
            None if tick_vw is None else round(float(tick_vw), 4),
            "lots=",
            _pos_lots(),
            "held=",
            _pos_shares(),
        )
    _bar_log(
        bar=closed_tag,
        phase=phase,
        close=px,
        vwap=vwap,
        vwap_src=vwap_src,
        bias=bias,
        lots=_pos_lots(),
        held=_pos_shares(),
    )

    if phase in ("closed", "lunch", "warmup"):
        A.acted_closed = closed_tag
        _save_state()
        if phase == "warmup" and not bt:
            _live_heartbeat("open_skip")
        return

    did = False
    if holding:
        cost = _pos_cost_price()
        if phase == "flatten":
            did = _try_sell(C, "eod_flatten", stop_px, now)
            if did:
                _mark_after_sell()
        elif cost > 0 and (stop_px - cost) / cost <= -float(STOP_LOSS):
            did = _try_sell(C, "stop_loss", stop_px, now)
            if did:
                A.risk_skip_day = day
                _mark_after_sell()
                _save_state()
        elif phase in ("trade", "sell_only"):
            ret_now = (float(stop_px) - cost) / cost if cost > 0 else 0.0
            peak = getattr(A, "hold_peak_ret", None)
            try:
                peak = float(peak) if peak is not None else None
            except Exception:
                peak = None
            if peak is None or ret_now > peak:
                A.hold_peak_ret = ret_now
                peak = ret_now
            arm = float(globals().get("TRAIL_ARM") or 0)
            give = float(globals().get("TRAIL_GIVE") or 0)
            if (not did) and arm > 0 and give > 0 and peak >= arm and ret_now <= (peak - give):
                did = _try_sell(C, "trail_stop", stop_px, now)
                if did:
                    _mark_after_sell()
            tp = float(globals().get("TAKE_PROFIT") or 0)
            if (not did) and tp > 0:
                if _lots_enabled():
                    lids = _tp_lot_ids(px, tp)
                    if lids:
                        did = _try_sell(C, "take_profit", px, now, lot_ids=lids)
                        if did:
                            _mark_after_sell()
                elif cost > 0 and (px - cost) / cost >= tp:
                    did = _try_sell(C, "take_profit", px, now)
                    if did:
                        _mark_after_sell()
            fade_ok = bias >= float(BIAS_FADE) and len(day_closed) >= 2
            if fade_ok and bias < float(BIAS_FADE) + 0.004:
                fade_ok = _fade_vol_ok(
                    volumes, day_closed[-1], day_closed[-2], float(VOL_GAP)
                )
            if (not did) and fade_ok:
                did = _try_sell(C, "fade_sell", px, now)
                if did:
                    _mark_after_sell()
            if (not did) and bias >= float(REVERSION_BIAS):
                if _lots_enabled():
                    lids = _profit_lot_ids(px)
                    if lids:
                        did = _try_sell(C, "vwap_reversion", px, now, lot_ids=lids)
                        if did:
                            _mark_after_sell()
                else:
                    if cost <= 0 or px >= cost:
                        did = _try_sell(C, "vwap_reversion", px, now)
                        if did:
                            _mark_after_sell()

    holding = _has_position() or (bt and _bt_held_vol() >= _vol_step())
    if not holding:
        A.scale_out_lock = False
        A.hold_peak_ret = None
    can_buy = phase == "trade"
    if can_buy and str(getattr(A, "risk_skip_day", "") or "") == day:
        can_buy = False
        _diag_once("risk_skip_" + day, day)
        _event_log("buy_skip", reason="risk_skip", day=day)
    if can_buy and bool(getattr(A, "scale_out_lock", False)) and holding:
        can_buy = False
        _diag_once("scale_out_" + day, day)
        _event_log("buy_skip", reason="scale_out_lock", day=day)
    if can_buy and "SELL" in getattr(A, "acted", set()):
        can_buy = False
    if can_buy and getattr(A, "pending", None):
        can_buy = False

    if can_buy:
        live_check_px = live_px
        why = _univ_skip_reason(A.stock, day, live_check_px, tick, C)
        if why:
            _diag_once("univ_" + str(why) + "_" + day, why)
            _event_log("univ_skip", reason=why, price=live_check_px)
        else:
            nlot = _pos_lots() if holding else 0
            mx = _max_lots()
            if nlot >= mx:
                _event_log("buy_skip", reason="lot_skip", n=nlot, max_lots=mx)
            else:
                bias_l1 = float(BIAS_L1)
                bias_l2 = float(BIAS_L2)
                bias_l3 = float(BIAS_L3)
                impulse = _impulse_ok(
                    opens,
                    closes,
                    day_closed,
                    int(DOWN_BARS),
                    float(LAST_DROP),
                    float(IMPULSE_SUM),
                )
                prev_c = None
                if len(day_closed) >= 2:
                    prev_c = closes[day_closed[-2]]
                reversal = _reversal_ok(
                    opens[closed_i],
                    highs[closed_i],
                    lows[closed_i],
                    closes[closed_i],
                    float(SHADOW_RATIO),
                    prev_c,
                )
                deep_open = nlot == 0 and bias <= float(BIAS_L2)
                if (not impulse) or ((not reversal) and (not deep_open)):
                    _diag_once(
                        "skip_sig_" + day,
                        "impulse=",
                        impulse,
                        "reversal=",
                        reversal,
                        "bias=",
                        round(float(bias) * 100.0, 3),
                    )
                    if bias <= float(BIAS_L1):
                        _diag_once(
                            "skip_l1_" + day,
                            "impulse=",
                            impulse,
                            "reversal=",
                            reversal,
                            "deep=",
                            deep_open,
                            "bias=",
                            round(float(bias) * 100.0, 3),
                        )
                else:
                    want_l3 = (
                        bool(ENABLE_L3)
                        and nlot >= 2
                        and bias <= bias_l3
                    )
                    want_l2 = nlot >= 1 and bias <= bias_l2
                    if want_l2:
                        c0 = _pos_cost_price()
                        if c0 > 0 and px < c0:
                            want_l2 = False
                            _diag_once("l2_uw_" + day, round(float(px), 4), round(float(c0), 4))
                            _event_log(
                                "buy_skip",
                                reason="l2_underwater",
                                price=px,
                                cost=c0,
                                day=day,
                            )
                    want_l1 = nlot == 0 and bias <= bias_l1
                    if want_l3:
                        did = _try_buy(C, "buy_l3", px, now, float(LOT_W3), True)
                    elif want_l2:
                        did = _try_buy(C, "buy_l2", px, now, float(LOT_W2), True)
                    elif want_l1:
                        did = _try_buy(C, "buy_l1", px, now, float(LOT_W1), False)

    A.acted_closed = closed_tag
    _save_state()
