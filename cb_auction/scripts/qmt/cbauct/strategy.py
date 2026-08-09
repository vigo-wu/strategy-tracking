# === cbauct/strategy.py ===
# 定稿:
#   开盘竞价: 9:15 全标的 @130 限价买
#   收盘竞价: ≤5亿提示 157.30；>5亿提示可确认收盘价；卖出手动（回测可模拟）


def _has_position():
    """可转债一手=10张；覆盖 common 的 >=100 判定。"""
    pos = getattr(A, "position", None)
    lot = int(globals().get("LOT_SIZE") or 10)
    return isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= lot


def _cb_lot(price, budget):
    lot = int(globals().get("LOT_SIZE") or 10)
    if price is None or price <= 0 or budget <= 0 or lot <= 0:
        return 0
    return int(float(budget) // (float(price) * lot)) * lot


def _apply_cb_buy_fill(vol, price, opened_at, **extra):
    lot = int(globals().get("LOT_SIZE") or 10)
    vol = int(vol)
    price = float(price) if price and price > 0 else 0.0
    if vol < lot:
        return
    ot = str(opened_at or "").strip()
    if not ot:
        ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    pos = {
        "shares": vol,
        "price": price,
        "cost": round(vol * price, 2),
        "opened_at": ot,
    }
    for k, v in extra.items():
        if v is not None:
            pos[k] = v
    A.position = pos
    A.acted.add("BUY")
    if getattr(A, "is_backtest", False):
        A.bt_opened_at = ot
    buy_day = ot[:8] if len(ot) >= 8 else None
    _bt_held_add(vol, buy_day=buy_day)
    # 可转债 T+0：回测当日即可卖（仅影响 BACKTEST_SIM_SELL）
    if getattr(A, "is_backtest", False):
        A.bt_locked = 0
    day = buy_day or ""
    if day:
        A.buy_done_day = day
    _save_state()
    print(_strategy_tag(), "BUY filled", A.position)
    _event_log("buy_filled", position=A.position, vol=vol, price=price, opened_at=ot)


def _pending_on_buy_fill(pend, vol, px):
    extra = pend.get("extra_pos") if isinstance(pend.get("extra_pos"), dict) else {}
    _apply_cb_buy_fill(vol, px, pend.get("opened_at") or pend.get("submitted_at"), **extra)


def _order_buy_limit(C, price, now, budget=None):
    """限价买入 prType=11；用于开盘竞价挂 130。"""
    lot = int(globals().get("LOT_SIZE") or 10)
    if getattr(A, "pending", None):
        print(_strategy_tag(), "buy skip: pending active")
        _event_log("buy_skip", reason="pending_active")
        return False
    if _has_position() or (
        getattr(A, "is_backtest", False) and _bt_held_vol() >= lot
    ):
        print(_strategy_tag(), "buy skip: already holding")
        _event_log("buy_skip", reason="already_holding")
        return False
    if "BUY" in getattr(A, "acted", set()):
        return False

    if budget is None:
        cash = _available_cash()
        budget = _buy_budget(cash)
    vol = _cb_lot(price, budget)
    if vol < lot:
        print(_strategy_tag(), "buy skip lot", "price=", price, "budget=", budget)
        _event_log("buy_skip", reason="lot", price=price, budget=budget)
        return False
    cash = _available_cash()
    if cash is not None and cash < price * vol:
        vol = _cb_lot(price, cash)
        if vol < lot:
            print(_strategy_tag(), "buy skip cash", cash)
            _event_log("buy_skip", reason="cash", cash=cash, price=price)
            return False

    ot = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    msg = _new_remark("BUY", "BUY", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@limit", price)
    if DRY_RUN:
        _apply_cb_buy_fill(vol, price, ot)
        return True
    try:
        # prType=11 指定价；quickTrade=1 即时报单（集合竞价可挂）
        passorder(
            A.buy_code,
            1101,
            A.acct,
            A.stock,
            11,
            float(price),
            vol,
            _strategy_tag(),
            1,
            msg,
            C,
        )
    except Exception as e:
        print(_strategy_tag(), "passorder BUY limit fail", e)
        _event_log("passorder_fail", side="buy", error=str(e), vol=vol, price=price)
        return False
    if getattr(A, "is_backtest", False):
        _apply_cb_buy_fill(vol, price, ot)
        return True
    A.pending = {
        "remark": msg,
        "side": "buy",
        "intent": "BUY",
        "vol": int(vol),
        "stock": A.stock,
        "price_hint": float(price),
        "opened_at": ot,
        "submitted_at": ot,
        "cancel_requested": False,
        "extra_pos": {},
    }
    A.buy_done_day = ot[:8]
    _save_state()
    print(_strategy_tag(), "BUY submitted limit", vol, "@", price, msg)
    _event_log("buy_submitted", vol=vol, price=price, remark=msg, dry_run=False)
    return True


def _cb_sim_sell(now, reason, price):
    """仅回测：按提示价清空影子仓（T+0）。"""
    if not getattr(A, "is_backtest", False):
        return False
    if not _has_position() and _bt_held_vol() < int(globals().get("LOT_SIZE") or 10):
        return False
    A.bt_locked = 0
    vol = max(_pos_shares(), _bt_held_vol())
    print(
        "[BT-SIM] %s SELL" % _strategy_tag(),
        reason,
        "vol=",
        vol,
        "@",
        price,
    )
    _event_log(
        "bt_sim_sell",
        sell_reason=reason,
        vol=vol,
        price=price,
    )
    _clear_after_sell(now, reason, last=price)
    return True


def _in_window(now_s, start, end):
    return str(start) <= str(now_s) <= str(end)


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    day = now.strftime("%Y%m%d")
    tag = _bar_tag(bar_dt)

    if not bt:
        if getattr(A, "pending", None):
            if _process_pending(C, now):
                _live_heartbeat("pending")
                return
        if LIVE_ONLY_LAST_BAR:
            try:
                if hasattr(C, "is_last_bar") and (not C.is_last_bar()):
                    return
            except Exception:
                pass
        _live_heartbeat("live")
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
    opens, highs, lows, closes, vols = ohlcv
    last_px = float(closes[-1])
    open_px = float(opens[-1])

    if bt:
        _bt_recover_position(now=now, last=last_px)

    holding = _has_position() or (
        bt and _bt_held_vol() >= int(globals().get("LOT_SIZE") or 10)
    )
    size_yi = _issue_size_yi()
    small = _is_small_issue()
    hint_px = _sell_hint_price(last_px)

    buy_start = str(globals().get("BUY_START") or "091500")
    buy_end = str(globals().get("BUY_END") or "092500")
    hint_start = str(globals().get("SELL_HINT_START") or "145700")
    hint_end = str(globals().get("SELL_HINT_END") or "150000")
    buy_px = float(globals().get("OPEN_BUY_PRICE") or 130.0)

    interesting = holding or getattr(A, "pending", None) or (
        str(getattr(A, "buy_done_day", "") or "") == day
    )
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 30 == 0):
        A.ready_logged = True
        print(
            "%s" % STRATEGY_NAME,
            day,
            now_s,
            "n=%d last=%.4f open=%.4f hold=%s size=%s small=%s hint=%s "
            "buy_done=%s pending=%s bt_held=%s"
            % (
                len(closes),
                last_px,
                open_px,
                holding,
                size_yi,
                small,
                hint_px,
                getattr(A, "buy_done_day", ""),
                bool(getattr(A, "pending", None)),
                _bt_held_vol() if bt else "-",
            ),
        )
        _bar_log(
            day=day,
            hhmmss=now_s,
            n=len(closes),
            last=round(last_px, 6),
            open=round(open_px, 6),
            hold=holding,
            size_yi=size_yi,
            small=small,
            hint=hint_px,
            buy_done=str(getattr(A, "buy_done_day", "") or ""),
            tag=tag,
        )

    # ---- 开盘竞价限价买 ----
    in_buy = _in_window(now_s, buy_start, buy_end)
    already_bought = str(getattr(A, "buy_done_day", "") or "") == day
    if (
        in_buy
        and (not holding)
        and (not already_bought)
        and ("BUY" not in getattr(A, "acted", set()))
        and (not getattr(A, "pending", None))
    ):
        print(
            "%s OPEN_AUCTION buy @%.2f window=%s-%s size=%s"
            % (STRATEGY_NAME, buy_px, buy_start, buy_end, size_yi)
        )
        _event_log(
            "open_auction_buy",
            price=buy_px,
            size_yi=size_yi,
            window="%s-%s" % (buy_start, buy_end),
        )
        ok = _order_buy_limit(C, buy_px, now)
        if ok:
            A.buy_done_day = day
            _save_state()
        return

    # ---- 收盘：手动卖出提示；回测可选模拟 ----
    in_hint = _in_window(now_s, hint_start, hint_end)
    if in_hint and holding:
        if str(getattr(A, "sell_hint_day", "") or "") != day:
            A.sell_hint_day = day
            _save_state()
            mode = "小盘顶格" if small else "可确认收盘价"
            print(
                "%s MANUAL_SELL hint mode=%s price=%s size=%s亿 last=%.4f "
                "(实盘请手动挂卖，策略不下单)"
                % (STRATEGY_NAME, mode, hint_px, size_yi, last_px)
            )
            _event_log(
                "manual_sell_hint",
                mode=mode,
                price=hint_px,
                size_yi=size_yi,
                last=last_px,
            )

        if (
            bt
            and bool(globals().get("BACKTEST_SIM_SELL", True))
            and str(getattr(A, "sim_sell_day", "") or "") != day
            and hint_px is not None
        ):
            reason = "close_limit_up" if small else "close_confirm"
            if _cb_sim_sell(now, reason, float(hint_px)):
                A.sim_sell_day = day
                _save_state()
            return
