# === pbs/strategy.py ===
# model.md — 仅买入抢筹：开盘/隔夜人工；策略只跑 Mode B 尾盘沪深分流


def _has_position():
    pos = getattr(A, "position", None)
    return isinstance(pos, dict) and int(pos.get("shares", 0) or 0) > 0


def _cb_lot(price, budget):
    lot = int(globals().get("LOT_SIZE") or 10)
    if price is None or price <= 0 or budget <= 0 or lot <= 0:
        return 0
    return int(float(budget) // (float(price) * lot)) * lot


def _remaining_buy_budget(cash):
    cap = _buy_budget(cash)
    try:
        cap = float(cap or 0)
    except Exception:
        cap = 0.0
    pos = getattr(A, "position", None)
    if not isinstance(pos, dict):
        return max(0.0, cap)
    sh = int(pos.get("shares", 0) or 0)
    if sh <= 0:
        return max(0.0, cap)
    spent = float(pos.get("cost", 0) or 0)
    if spent <= 0:
        spent = sh * float(pos.get("price", 0) or 0)
    return max(0.0, cap - spent)


def _intent_entry_mode(intent):
    if intent in ("SZ_CLOSE", "SH_CLOSE"):
        return "B"
    return ""


def _entry_mode_of(pos=None):
    pos = pos if pos is not None else getattr(A, "position", None)
    if isinstance(pos, dict):
        m = str(pos.get("entry_mode", "") or "")
        if m:
            return m
        return _intent_entry_mode(str(pos.get("intent", "") or ""))
    return str(getattr(A, "entry_mode", "") or "")


def _apply_cb_buy_fill(vol, price, opened_at, **extra):
    lot = int(globals().get("LOT_SIZE") or 10)
    vol = int(vol)
    price = float(price) if price and price > 0 else 0.0
    if vol <= 0:
        return
    ot = str(opened_at or "").strip()
    if not ot:
        ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    prev = getattr(A, "position", None)
    prev_sh = int(prev.get("shares", 0) or 0) if isinstance(prev, dict) else 0
    prev_cost = float(prev.get("cost", 0) or 0) if isinstance(prev, dict) else 0.0
    new_sh = prev_sh + vol
    new_cost = prev_cost + round(vol * price, 2)
    avg = (new_cost / float(new_sh)) if new_sh > 0 else price
    intent = str(extra.get("intent") or "")
    entry_mode = str(extra.get("entry_mode") or "") or _intent_entry_mode(intent)
    pos = {
        "shares": new_sh,
        "price": avg,
        "cost": round(new_cost, 2),
        "opened_at": ot if prev_sh <= 0 else str((prev or {}).get("opened_at") or ot),
    }
    for k, v in extra.items():
        if v is not None:
            pos[k] = v
    if entry_mode:
        pos["entry_mode"] = entry_mode
        A.entry_mode = entry_mode
    A.position = pos
    if not hasattr(A, "acted") or A.acted is None:
        A.acted = set()
    A.acted.add("BUY")
    if getattr(A, "is_backtest", False):
        A.bt_opened_at = pos["opened_at"]
    buy_day = str(pos["opened_at"])[:8] if len(str(pos["opened_at"])) >= 8 else None
    _bt_held_add(vol, buy_day=buy_day)
    if getattr(A, "is_backtest", False):
        A.bt_locked = 0
    if buy_day:
        A.buy_done_day = buy_day
    _save_state()
    print(_strategy_tag(), "BUY filled", A.position, "add_vol=", vol, "lot=", lot)
    _event_log(
        "buy_filled",
        position=A.position,
        vol=vol,
        price=price,
        opened_at=ot,
        entry_mode=entry_mode,
    )


def _pending_on_buy_fill(pend, vol, px):
    extra = pend.get("extra_pos") if isinstance(pend.get("extra_pos"), dict) else {}
    _apply_cb_buy_fill(vol, px, pend.get("opened_at") or pend.get("submitted_at"), **extra)


def _order_buy_limit(C, price, now, budget=None, intent="BUY", entry_mode=None):
    lot = int(globals().get("LOT_SIZE") or 10)
    price = _px_round(price)
    if price <= 0:
        return False
    wait_sec = float(globals().get("LOG_WAIT_SEC") or 5.0)
    if _shadow_reorder_blocked(now):
        if _log_due("shadow_reorder_block", now, wait_sec):
            print(_strategy_tag(), "buy skip: shadow reorder cooldown")
            _event_log("buy_skip", reason="shadow_reorder_cooldown")
        return False
    if getattr(A, "pending", None):
        if _log_due("buy_skip_pending", now, wait_sec):
            print(_strategy_tag(), "buy skip: pending active")
            _event_log("buy_skip", reason="pending_active")
        return False
    if _has_position() or (getattr(A, "is_backtest", False) and _bt_held_vol() > 0):
        if _log_due("buy_skip_holding", now, wait_sec):
            print(_strategy_tag(), "buy skip: already holding")
            _event_log("buy_skip", reason="already_holding")
        return False
    if "BUY" in getattr(A, "acted", set()):
        return False

    if budget is None:
        cash = _available_cash()
        budget = _remaining_buy_budget(cash)
    vol = _cb_lot(price, budget)
    if vol < lot:
        if _log_due("buy_skip_lot", now, wait_sec):
            print(_strategy_tag(), "buy skip lot", "price=", price, "budget=", budget)
            _event_log("buy_skip", reason="lot", price=price, budget=budget)
        return False
    cash = _available_cash()
    if cash is not None and cash < price * vol:
        vol = _cb_lot(price, min(budget, float(cash)))
        if vol < lot:
            if _log_due("buy_skip_cash", now, wait_sec):
                print(_strategy_tag(), "buy skip cash", cash)
                _event_log("buy_skip", reason="cash", cash=cash, price=price)
            return False

    if not entry_mode:
        entry_mode = _intent_entry_mode(intent)
    extra_pos = {"intent": intent}
    if entry_mode:
        extra_pos["entry_mode"] = entry_mode

    ot = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    msg = _new_remark(intent, "BUY", vol)
    # 重试路径下报单前日志节流；申报成功日志不节流
    if _log_due("buy_order_try", now, wait_sec):
        print(("[DRY] " if DRY_RUN else "") + msg, "@limit", price, intent)
    exempt = set(str(x) for x in (globals().get("PENDING_TIMEOUT_EXEMPT_INTENTS") or ()))
    no_timeout = str(intent) in exempt
    if DRY_RUN:
        if bool(globals().get("DRY_RUN_FILL_IMMEDIATE", False)):
            _apply_cb_buy_fill(vol, price, ot, **extra_pos)
            return True
        A.pending = {
            "remark": msg,
            "side": "buy",
            "intent": intent,
            "vol": int(vol),
            "stock": A.stock,
            "price_hint": float(price),
            "opened_at": ot,
            "submitted_at": ot,
            "cancel_requested": False,
            "no_timeout": no_timeout,
            "dry_keep": True,
            "extra_pos": extra_pos,
        }
        A.sh_last_order_px = float(price)
        _save_state()
        print(_strategy_tag(), "DRY pending", vol, "@", price, intent)
        _event_log(
            "buy_submitted",
            vol=vol,
            price=price,
            remark=msg,
            intent=intent,
            dry_run=True,
            entry_mode=entry_mode,
        )
        if bool(globals().get("DRY_RUN_FILL_ON_LIMIT", True)) and price + 1e-9 >= _limit_up():
            _apply_cb_buy_fill(vol, price, ot, **extra_pos)
            A.pending = None
            _save_state()
            print(_strategy_tag(), "DRY fill on limit", price)
        return True
    try:
        passorder(
            A.buy_code,
            1101,
            A.acct,
            A.stock,
            11,
            float(price),
            vol,
            _strategy_tag(),
            int(getattr(A, "passorder_quick", 1) or 1),
            msg,
            C,
        )
    except Exception as e:
        if _log_due("passorder_fail", now, wait_sec):
            print(_strategy_tag(), "passorder BUY limit fail", e)
            _event_log("passorder_fail", side="buy", error=str(e), vol=vol, price=price)
        return False
    if getattr(A, "is_backtest", False):
        _apply_cb_buy_fill(vol, price, ot, **extra_pos)
        return True
    A.pending = {
        "remark": msg,
        "side": "buy",
        "intent": intent,
        "vol": int(vol),
        "stock": A.stock,
        "price_hint": float(price),
        "opened_at": ot,
        "submitted_at": ot,
        "cancel_requested": False,
        "no_timeout": no_timeout,
        "extra_pos": extra_pos,
    }
    A.sh_last_order_px = float(price)
    _save_state()
    print(_strategy_tag(), "BUY submitted limit", vol, "@", price, msg, intent)
    _event_log(
        "buy_submitted",
        vol=vol,
        price=price,
        remark=msg,
        intent=intent,
        dry_run=False,
        entry_mode=entry_mode,
    )
    return True


def _request_pending_cancel(C, now, reason):
    pend = getattr(A, "pending", None)
    if not isinstance(pend, dict):
        return False
    if pend.get("cancel_requested"):
        return True
    if DRY_RUN and bool(pend.get("dry_keep")):
        print(_strategy_tag(), "DRY cancel", reason, "px=", pend.get("price_hint"))
        _event_log("chase_cancel", reason=reason, price=pend.get("price_hint"), dry=True)
        A.pending = None
        _save_state()
        return True
    remark = str(pend.get("remark", "") or "")
    stock = str(pend.get("stock", A.stock) or A.stock)
    od, qok = _find_order_ex(remark, stock)
    if not qok:
        print(_strategy_tag(), "chase cancel defer: order query fail", reason)
        _event_log("chase_cancel_defer", reason=reason, error="order_query_fail")
        return False
    if od is None:
        print(_strategy_tag(), "chase cancel defer: order not visible yet", reason)
        _event_log("chase_cancel_defer", reason=reason, error="order_not_visible")
        return False
    pend["order_seen"] = True
    _try_cancel_order(od, C)
    pend["cancel_requested"] = True
    pend["cancel_at"] = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    pend["cancel_reason"] = str(reason or "")
    A.pending = pend
    _save_state()
    print(_strategy_tag(), "chase cancel requested", reason, "px=", pend.get("price_hint"))
    _event_log("chase_cancel", reason=reason, price=pend.get("price_hint"), remark=remark)
    return True


def _reconcile_with_broker():
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return
    if _available_cash() is None:
        print(_strategy_tag(), "reconcile skip: not login")
        return
    stock = str(getattr(A, "stock", "") or "")
    try:
        positions = get_trade_detail_data(A.acct, A.acct_type, "position")
    except Exception as e:
        print(_strategy_tag(), "reconcile position query fail", e)
        return
    if positions is None:
        return
    vol = 0
    cost = 0.0
    found = False
    for p in positions:
        if _pos_code(p) != stock:
            continue
        found = True
        vol = int(getattr(p, "m_nVolume", 0) or 0)
        for attr in ("m_dOpenPrice", "m_dCostPrice", "m_dAvgPrice"):
            v = getattr(p, attr, None)
            if v is not None:
                try:
                    cost = float(v)
                    if cost > 0:
                        break
                except Exception:
                    pass
        break
    if found and vol > 0:
        cur = int((getattr(A, "position", None) or {}).get("shares", 0) or 0)
        if cur != vol or (not _has_position()):
            ot = ""
            entry_mode = str(getattr(A, "entry_mode", "") or "")
            if isinstance(getattr(A, "position", None), dict):
                ot = str(A.position.get("opened_at", "") or "")
                if not entry_mode:
                    entry_mode = str(A.position.get("entry_mode", "") or "")
            if not ot:
                ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            A.position = {
                "shares": vol,
                "price": float(cost) if cost > 0 else float(
                    (getattr(A, "position", None) or {}).get("price", 0) or 0
                ),
                "cost": round(vol * float(cost), 2) if cost > 0 else 0.0,
                "opened_at": ot,
                "reconciled": True,
            }
            if entry_mode:
                A.position["entry_mode"] = entry_mode
                A.entry_mode = entry_mode
            if not hasattr(A, "acted") or A.acted is None:
                A.acted = set()
            A.acted.add("BUY")
            A.buy_done_day = ot[:8] if len(ot) >= 8 else datetime.datetime.now().strftime("%Y%m%d")
            _save_state()
            print(_strategy_tag(), "reconcile sync from broker vol=", vol, "cost=", cost)
        return
    if (not found or vol <= 0) and _has_position():
        print(_strategy_tag(), "reconcile clear shadow (broker flat) was=", A.position)
        A.position = None
        A.entry_mode = ""
        if hasattr(A, "acted") and isinstance(A.acted, set):
            A.acted.discard("BUY")
        A.buy_done_day = ""
        _save_state()


def _in_window(now_s, start, end):
    return str(start) <= str(now_s) <= str(end)


def _now_ms(now):
    if now is None:
        now = datetime.datetime.now()
    try:
        return now.timestamp() * 1000.0
    except Exception:
        return 0.0


def _log_due(key, now=None, sec=None):
    """墙钟节流：到期返回 True 并打戳。定时器高频下代替 C.barpos % N。"""
    if sec is None:
        sec = globals().get("LOG_STATUS_SEC")
    try:
        sec = float(sec if sec is not None else 10.0)
    except Exception:
        sec = 10.0
    if sec <= 0:
        return True
    store = getattr(A, "_log_at_ms", None)
    if not isinstance(store, dict):
        store = {}
        A._log_at_ms = store
    k = str(key or "")
    now_ms = _now_ms(now)
    last = float(store.get(k, 0) or 0)
    if last > 0 and (now_ms - last) < sec * 1000.0:
        return False
    store[k] = now_ms
    return True


def _close_buy_price():
    cfg = globals().get("CLOSE_BUY_PRICE")
    if cfg is not None:
        try:
            v = float(cfg)
            if v > 0:
                return _px_round(v)
        except Exception:
            pass
    return _limit_up()


def _handle_mode_b_close(C, now, now_s, day):
    """尾盘：14:57 起顶格申报；以柜台见单为委托成功，成交非目标。"""
    if not bool(globals().get("ENABLE_MODE_B", True)):
        return
    start = str(globals().get("CLOSE_BUY_START") or "145700")
    end = str(globals().get("CLOSE_BUY_END") or "145955")
    if not _in_window(now_s, start, end):
        return
    if _has_position():
        return
    if ("BUY" in getattr(A, "acted", set())) and (not getattr(A, "pending", None)):
        return

    pend = getattr(A, "pending", None)
    if isinstance(pend, dict):
        # 已报出：等柜台 ack（order_seen）/ 废单 / 影子强清；顶格常不成交属正常
        return

    px = _close_buy_price()
    if px <= 0:
        return
    mkt = _market_tag()
    intent = "SZ_CLOSE" if mkt == "SZ" else "SH_CLOSE"
    wait_sec = float(globals().get("LOG_WAIT_SEC") or 5.0)
    # 仍按 50ms 重试；日志约 LOG_WAIT_SEC 一条，避免刷屏
    if _log_due("close_buy_try", now, wait_sec):
        print("%s %s buy @%.3f now=%s (limit-up until submit ok)" % (STRATEGY_NAME, intent, px, now_s))
        _event_log("close_buy_try", intent=intent, price=px, now_s=now_s, mkt=mkt)
    if _order_buy_limit(C, px, now, intent=intent, entry_mode="B"):
        print("%s %s submitted @%.3f now=%s (wait order ack)" % (STRATEGY_NAME, intent, px, now_s))
        _event_log("close_buy_submitted", intent=intent, price=px, now_s=now_s)
        return
    if _log_due("close_buy_retry", now, wait_sec):
        print("%s %s submit fail -> retry @%.3f" % (STRATEGY_NAME, intent, px))
        _event_log("close_buy_retry", intent=intent, price=px, now_s=now_s)


def _in_critical_live_window(now_s):
    """收盘申报时窗：即使非末 bar 也要跑。"""
    return _in_window(
        now_s,
        str(globals().get("CLOSE_BUY_START") or "145700"),
        str(globals().get("CLOSE_BUY_END") or "145955"),
    )


def _before_close_window(now_s):
    """14:57 前：策略空转，尽量不打日志。"""
    start = str(globals().get("CLOSE_BUY_START") or "145700")
    return str(now_s) < start


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    day = now.strftime("%Y%m%d")
    tag = _bar_tag(bar_dt)
    in_close = _in_critical_live_window(now_s)
    before_close = _before_close_window(now_s)

    if not bt:
        if getattr(A, "pending", None):
            _process_pending(C, now)
        # tick 主图：每笔都决策；非 tick 仍可用末 bar / critical 窗
        only_last = bool(globals().get("LIVE_ONLY_LAST_BAR", False))
        if str(getattr(A, "period", "")) == "tick":
            only_last = False
        if only_last and (not in_close):
            try:
                if hasattr(C, "is_last_bar") and (not C.is_last_bar()):
                    return
            except Exception:
                pass
        # 收盘窗外不打心跳，避免全日刷屏
        if in_close:
            _live_heartbeat("live")
    else:
        _bt_roll_t1(day)
        _bt_recover_position(now=now)

    _reset_day(day)

    cash = _available_cash()
    if cash is None:
        if in_close:
            _live_heartbeat("no_cash_or_login")
        return

    holding = _has_position() or (bt and _bt_held_vol() > 0)
    mkt = _market_tag()

    # 已持仓：抢筹目标达成，不再交易
    if holding:
        return

    if ("BUY" in getattr(A, "acted", set())) and (not getattr(A, "pending", None)):
        return

    # 14:57 前静默等待（init 日志仍保留；买卖关键事件仍会打）
    if before_close:
        return

    listing = _is_listing_day(C, day)
    if not listing:
        if in_close and _log_due("skip_not_listing", now, globals().get("LOG_STATUS_SEC")):
            print("%s skip: not listing day" % STRATEGY_NAME, day, A.stock)
            _event_log("skip_not_listing_day", day=day, stock=A.stock)
        return

    # 行情仅用于状态行；收盘顶格申报不依赖 OHLCV
    last_px = 0.0
    open_px = 0.0
    n_bars = 0
    ohlcv = None
    if in_close:
        ohlcv = _get_ohlcv(C, A.stock)
    if ohlcv is not None:
        opens, highs, lows, closes, vols = ohlcv
        n_bars = len(closes)
        open_px = float(opens[-1]) if opens else 0.0
        bar_last = float(closes[-1]) if closes else 0.0
        last_px = _tick_last(C, fallback=bar_last)
        if last_px <= 0:
            last_px = _px_round(bar_last)
        if bt:
            try:
                bar_high = float(highs[-1])
            except Exception:
                bar_high = last_px
            if bar_high > last_px:
                last_px = _px_round(bar_high)
            _bt_recover_position(now=now, last=last_px)

    # 仅收盘窗内打状态行 / bars.jsonl
    if in_close:
        do_status = (not getattr(A, "ready_logged", False)) or _log_due(
            "status", now, globals().get("LOG_STATUS_SEC")
        )
        if do_status:
            A.ready_logged = True
            print(
                "%s" % STRATEGY_NAME,
                day,
                now_s,
                "mkt=%s n=%d last=%.3f open=%.3f hold=%s mode=%s "
                "buy_done=%s pending=%s close_px=%.3f"
                % (
                    mkt,
                    n_bars,
                    last_px,
                    open_px,
                    holding,
                    _entry_mode_of(),
                    getattr(A, "buy_done_day", ""),
                    bool(getattr(A, "pending", None)),
                    _close_buy_price(),
                ),
            )
            _bar_log(
                day=day,
                hhmmss=now_s,
                n=n_bars,
                last=round(last_px, 6),
                open=round(open_px, 6),
                hold=holding,
                mkt=mkt,
                buy_done=str(getattr(A, "buy_done_day", "") or ""),
                tag=tag,
                pending=bool(getattr(A, "pending", None)),
            )

    if mkt in ("SZ", "SH"):
        _handle_mode_b_close(C, now, now_s, day)
    elif in_close:
        if _log_due("unknown_market", now, globals().get("LOG_STATUS_SEC")):
            print("%s unknown market stock=%s" % (STRATEGY_NAME, A.stock))
            _event_log("unknown_market", stock=A.stock)
