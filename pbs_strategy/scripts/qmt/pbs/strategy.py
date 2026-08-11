# === pbs/strategy.py ===
# model.md v1.1 — 仅买入抢筹：Mode A 早盘 130 / Mode B 尾盘沪深分流


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
    if intent in ("SZ_AM", "SH_AM"):
        return "A"
    if intent in ("SZ_PREPLACE", "SZ_CLOSE", "SH_OPEN", "SH_CHASE"):
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
    if getattr(A, "pending", None):
        print(_strategy_tag(), "buy skip: pending active")
        _event_log("buy_skip", reason="pending_active")
        return False
    if _has_position() or (getattr(A, "is_backtest", False) and _bt_held_vol() > 0):
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
        print(_strategy_tag(), "buy skip lot", "price=", price, "budget=", budget)
        _event_log("buy_skip", reason="lot", price=price, budget=budget)
        return False
    cash = _available_cash()
    if cash is not None and cash < price * vol:
        vol = _cb_lot(price, min(budget, float(cash)))
        if vol < lot:
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


def _now_ms_of_second(now):
    if now is None:
        now = datetime.datetime.now()
    try:
        return int(now.microsecond // 1000)
    except Exception:
        return 0


def _listing_date_str(stock=None):
    stock = str(stock or getattr(A, "stock", "") or "")
    mp = globals().get("LISTING_DATE_MAP") or {}
    if stock in mp:
        return str(mp.get(stock) or "")
    return ""


def _is_eve_before_listing(C, now, day):
    if now is None:
        return False
    try:
        tomorrow = (now + datetime.timedelta(days=1)).strftime("%Y%m%d")
    except Exception:
        return False
    mapped = _listing_date_str()
    if mapped:
        return mapped == tomorrow
    try:
        return bool(_is_listing_day(C, tomorrow))
    except Exception:
        return False


def _morning_buy_price():
    cfg = globals().get("MORNING_BUY_PRICE")
    if cfg is not None:
        try:
            v = float(cfg)
            if v > 0:
                return _px_round(v)
        except Exception:
            pass
    return _px_round(globals().get("HALT_BASE_PRICE") or 130.0)


def _try_morning_buy(C, now, now_s, day):
    """Mode A：深市隔夜/早盘挂 130；沪市卡点挂 130。"""
    if not bool(globals().get("ENABLE_MODE_A", True)):
        return False
    if _has_position() or getattr(A, "pending", None):
        return False
    if str(getattr(A, "am_buy_day", "") or "") == day:
        return False
    if "BUY" in getattr(A, "acted", set()):
        return False

    mkt = _market_tag()
    px = _morning_buy_price()
    bt = getattr(A, "is_backtest", False)

    if mkt == "SZ":
        eve_s = str(globals().get("SZ_AM_EVE_START") or "203000")
        eve_e = str(globals().get("SZ_AM_EVE_END") or "223000")
        am_s = str(globals().get("SZ_AM_BUY_START") or "000000")
        am_e = str(globals().get("SZ_AM_BUY_END") or "092459")
        ok = False
        if _in_window(now_s, am_s, am_e) and _is_listing_day(C, day):
            ok = True
        elif _in_window(now_s, eve_s, eve_e) and _is_eve_before_listing(C, now, day):
            ok = True
        if not ok:
            return False
        print("%s SZ_AM buy @%.3f now=%s" % (STRATEGY_NAME, px, now_s))
        _event_log("sz_am_buy", price=px, now_s=now_s)
        if _order_buy_limit(C, px, now, intent="SZ_AM", entry_mode="A"):
            A.am_buy_day = day
            _save_state()
            return True
        return False

    if mkt == "SH":
        if not _is_listing_day(C, day):
            return False
        am_s = str(globals().get("SH_AM_BUY_START") or "092459")
        am_e = str(globals().get("SH_AM_BUY_END") or "092459")
        if not _in_window(now_s, am_s, am_e):
            return False
        # 实盘：毫秒卡点；分笔回测：该秒内每笔都允许（无可靠微秒则不筛 ms）
        if not bt:
            ms0 = int(globals().get("SH_AM_BUY_MS_START") or 850)
            ms1 = int(globals().get("SH_AM_BUY_MS_END") or 950)
            ms = _now_ms_of_second(now)
            if ms < ms0 or ms > ms1:
                return False
        elif str(getattr(A, "period", "")) == "tick":
            ms = _now_ms_of_second(now)
            # 仅当 bar 带微秒时按卡点筛；秒级时间戳则放行该秒全部 tick
            if getattr(now, "microsecond", 0) > 0:
                ms0 = int(globals().get("SH_AM_BUY_MS_START") or 850)
                ms1 = int(globals().get("SH_AM_BUY_MS_END") or 950)
                if ms < ms0 or ms > ms1:
                    return False
        print(
            "%s SH_AM buy @%.3f card-point now=%s ms=%s"
            % (STRATEGY_NAME, px, now_s, _now_ms_of_second(now))
        )
        _event_log("sh_am_buy", price=px, now_s=now_s, ms=_now_ms_of_second(now))
        if _order_buy_limit(C, px, now, intent="SH_AM", entry_mode="A"):
            A.am_buy_day = day
            _save_state()
            return True
        return False

    return False


def _cleanup_am_pending(C, now, now_s):
    """撤未成早盘单；撤单卡住超时则强清影子 pending，避免堵死 Mode B。

    返回 True：本 bar 仍应等待早盘撤单（暂不进 Mode B）。
    返回 False：不因早盘 pending 阻塞（无单 / 已清 / 未到撤单时点）。
    """
    after = str(globals().get("AM_CANCEL_AFTER") or "092501")
    if str(now_s) < after:
        return False
    pend = getattr(A, "pending", None)
    if not isinstance(pend, dict):
        return False
    intent = str(pend.get("intent", "") or "")
    if intent not in ("SZ_AM", "SH_AM"):
        return False

    if not pend.get("cancel_requested"):
        print("%s AM cancel unfilled intent=%s" % (STRATEGY_NAME, intent))
        _event_log("am_cancel", intent=intent, now_s=now_s)
        _request_pending_cancel(C, now, "am_unfilled")
        return True

    stuck_sec = float(globals().get("AM_CANCEL_STUCK_SEC") or 30.0)
    cancel_at = _parse_opened_at(pend.get("cancel_at"))
    age = 0.0
    if cancel_at is not None and now is not None:
        try:
            age = (now - cancel_at).total_seconds()
        except Exception:
            age = 0.0
    if age >= stuck_sec:
        print(
            "%s AM cancel stuck -> force clear pending intent=%s age=%.0fs"
            % (STRATEGY_NAME, intent, age)
        )
        _event_log(
            "am_cancel_stuck_clear",
            intent=intent,
            age_sec=int(age),
            stuck_sec=stuck_sec,
            price=pend.get("price_hint"),
            remark=pend.get("remark"),
        )
        A.pending = None
        _save_state()
        return False

    if C.barpos % 5 == 0:
        print(
            "%s AM cancel in-flight intent=%s age=%.0fs stuck_after=%.0fs"
            % (STRATEGY_NAME, intent, age, stuck_sec)
        )
    return True


def _handle_sz_mode_b(C, now, now_s, day, last_px):
    """深市 Mode B：临停埋 143 → 14:55-14:56 撤单 → 等复牌就绪/到点强制按笼子顶挂。

    关键：14:57 起收盘集合不可撤；撤 143 必须在 14:57 前；收盘只挂一次。
    """
    if not bool(globals().get("ENABLE_MODE_B", True)):
        return
    reopen = _reopen_cap()
    limit_up = _limit_up()
    pre_s = str(globals().get("SZ_PREPLACE_START") or "093000")
    pre_e = str(globals().get("SZ_PREPLACE_END") or "145459")
    esc_s = str(globals().get("SZ_ESCALATE_CANCEL_START") or "145500")
    esc_e = str(globals().get("SZ_ESCALATE_CANCEL_END") or "145659")
    close_s = str(globals().get("SZ_CLOSE_BUY_START") or "145701")
    close_e = str(globals().get("SZ_CLOSE_BUY_END") or "145950")
    alert_sec = float(globals().get("SZ_ESCALATE_ALERT_SEC") or 2.0)

    # 1) 临停预挂 143
    if _in_window(now_s, pre_s, pre_e):
        if str(getattr(A, "sz_preplace_day", "") or "") == day:
            return
        if _has_position() or getattr(A, "pending", None):
            return
        print("%s SZ_PREPLACE buy @%.3f (禁挂涨停顶格)" % (STRATEGY_NAME, reopen))
        _event_log("sz_preplace", price=reopen)
        if _order_buy_limit(C, reopen, now, intent="SZ_PREPLACE", entry_mode="B"):
            A.sz_preplace_day = day
            _save_state()
        return

    # 2) 14:57 前必须撤掉未成 143（不可撤窗口前）
    if _in_window(now_s, esc_s, esc_e):
        pend = getattr(A, "pending", None)
        if not isinstance(pend, dict):
            return
        intent = str(pend.get("intent", "") or "")
        if intent not in ("SZ_PREPLACE",):
            return
        if pend.get("cancel_requested"):
            now_ms = _now_ms(now)
            last_alert = float(getattr(A, "sz_escalate_alert_ms", 0) or 0)
            if last_alert <= 0 or (now_ms - last_alert) >= alert_sec * 1000.0:
                A.sz_escalate_alert_ms = now_ms
                print(
                    "%s SZ_ESCALATE wait cancel intent=%s px=%.3f"
                    % (STRATEGY_NAME, intent, float(pend.get("price_hint") or 0))
                )
                _event_log("sz_escalate_wait", intent=intent, price=pend.get("price_hint"))
                _save_state()
            return
        A.sz_escalate_day = day
        old_px = float(pend.get("price_hint") or 0)
        print(
            "%s SZ_ESCALATE pre-14:57 cancel old=%.3f intent=%s"
            % (STRATEGY_NAME, old_px, intent)
        )
        _event_log("sz_escalate_cancel", old=old_px, intent=intent, window="%s-%s" % (esc_s, esc_e))
        _request_pending_cancel(C, now, "sz_pre_1457_cancel")
        A.sz_escalate_alert_ms = _now_ms(now)
        _save_state()
        return

    # 3) 收盘集合：就绪后按笼子顶挂一次；到点强制挂（不可撤，故不再撤补）
    if not _in_window(now_s, close_s, close_e):
        return
    if str(getattr(A, "sz_close_buy_day", "") or "") == day:
        return
    if _has_position():
        return

    pend = getattr(A, "pending", None)
    if isinstance(pend, dict):
        intent = str(pend.get("intent", "") or "")
        old_px = float(pend.get("price_hint") or 0)
        # 14:57 后仍挂着 143：不可再撤，只能告警
        now_ms = _now_ms(now)
        last_alert = float(getattr(A, "sz_escalate_alert_ms", 0) or 0)
        if last_alert <= 0 or (now_ms - last_alert) >= alert_sec * 1000.0:
            A.sz_escalate_alert_ms = now_ms
            print(
                "%s SZ_CLOSE BLOCKED: pending=%s px=%.3f (14:57后不可撤，错失升级)"
                % (STRATEGY_NAME, intent, old_px)
            )
            _event_log(
                "sz_close_blocked",
                intent=intent,
                price=old_px,
                last=last_px,
                cancel_requested=bool(pend.get("cancel_requested")),
            )
            _save_state()
        return

    target = _cage_cap(C, last_px if last_px > 0 else reopen)
    if target <= 0:
        return

    ready_last = float(globals().get("SZ_CLOSE_READY_LAST") or 0)
    if ready_last <= 0:
        ready_last = float(reopen)
    force_at = str(globals().get("SZ_CLOSE_FORCE_AT") or "145745")
    ready = last_px + 1e-9 >= ready_last
    force = str(now_s) >= force_at
    if (not ready) and (not force):
        if C.barpos % 3 == 0:
            print(
                "%s SZ_CLOSE wait reopen last=%.3f need>=%.3f cage=%.3f force_at=%s"
                % (STRATEGY_NAME, last_px, ready_last, target, force_at)
            )
            _event_log(
                "sz_close_wait",
                last=last_px,
                ready_last=ready_last,
                cage=target,
                force_at=force_at,
            )
        return

    reason = "force" if (force and not ready) else "ready"
    print(
        "%s SZ_CLOSE buy @%.3f last=%.3f limit=%.3f reason=%s"
        % (STRATEGY_NAME, target, last_px, limit_up, reason)
    )
    _event_log(
        "sz_close_buy",
        price=target,
        last=last_px,
        limit_up=limit_up,
        reason=reason,
        ready=ready,
        force=force,
    )
    if _order_buy_limit(C, target, now, intent="SZ_CLOSE", entry_mode="B"):
        A.sz_close_buy_day = day
        _save_state()


def _handle_sh_mode_b(C, now, now_s, day, last_px):
    """沪市 Mode B：按盘口笼子阶梯追至 157.30。"""
    if not bool(globals().get("ENABLE_MODE_B", True)):
        return
    start = str(globals().get("SH_CHASE_START") or "145700")
    end = str(globals().get("SH_CHASE_END") or "145955")
    if not _in_window(now_s, start, end):
        return
    if _has_position():
        return

    limit_up = _limit_up()
    target = _cage_cap(C, last_px)
    if target <= 0:
        return
    interval = float(globals().get("SH_CHASE_INTERVAL_MS") or 50)
    min_step = float(globals().get("CHASE_MIN_STEP") or 0.01)
    now_ms = _now_ms(now)
    pend = getattr(A, "pending", None)

    if isinstance(pend, dict):
        last_ms = float(getattr(A, "sh_chase_at_ms", 0) or 0)
        if last_ms > 0 and (now_ms - last_ms) < interval and (not pend.get("cancel_requested")):
            return
        old_px = float(pend.get("price_hint") or 0)
        if old_px + 1e-9 >= limit_up:
            return
        if target > old_px + min_step:
            if not pend.get("cancel_requested"):
                A.sh_chase_at_ms = now_ms
                print(
                    "%s SH_CHASE cancel->%.3f old=%.3f last=%.3f"
                    % (STRATEGY_NAME, target, old_px, last_px)
                )
                _event_log("sh_chase", target=target, old=old_px, last=last_px)
                _request_pending_cancel(C, now, "cage_up")
                if getattr(A, "pending", None):
                    return
            else:
                return
        else:
            return

    if "BUY" in getattr(A, "acted", set()):
        return
    A.sh_chase_at_ms = now_ms
    intent = "SH_OPEN" if str(getattr(A, "sh_chase_day", "") or "") != day else "SH_CHASE"
    print("%s %s buy @%.3f last=%.3f" % (STRATEGY_NAME, intent, target, last_px))
    _event_log("sh_buy", intent=intent, price=target, last=last_px)
    if _order_buy_limit(C, target, now, intent=intent, entry_mode="B"):
        A.sh_chase_day = day
        A.sh_last_order_px = float(target)
        _save_state()


def _in_critical_live_window(now_s):
    """卡点/撤补/深市升级等时窗：即使非末 bar 也要跑。"""
    windows = (
        (
            str(globals().get("SH_AM_BUY_START") or "092459"),
            str(globals().get("SH_AM_BUY_END") or "092459"),
        ),
        (
            str(globals().get("AM_CANCEL_AFTER") or "092501"),
            "093000",
        ),
        (
            str(globals().get("SZ_PREPLACE_START") or "093000"),
            str(globals().get("SZ_PREPLACE_END") or "145459"),
        ),
        (
            str(globals().get("SZ_ESCALATE_CANCEL_START") or "145500"),
            str(globals().get("SZ_ESCALATE_CANCEL_END") or "145659"),
        ),
        (
            str(globals().get("SZ_CLOSE_BUY_START") or "145701"),
            str(globals().get("SZ_CLOSE_BUY_END") or "145950"),
        ),
        (
            str(globals().get("SH_CHASE_START") or "145700"),
            str(globals().get("SH_CHASE_END") or "145955"),
        ),
    )
    for s, e in windows:
        if _in_window(now_s, s, e):
            return True
    # 深市隔夜窗（若模型夜间仍在跑）
    if _in_window(
        now_s,
        str(globals().get("SZ_AM_EVE_START") or "203000"),
        str(globals().get("SZ_AM_EVE_END") or "223000"),
    ):
        return True
    return False


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    day = now.strftime("%Y%m%d")
    tag = _bar_tag(bar_dt)

    if not bt:
        if getattr(A, "pending", None):
            _process_pending(C, now)
        # tick 主图：每笔都决策；非 tick 仍可用末 bar / critical 窗
        only_last = bool(globals().get("LIVE_ONLY_LAST_BAR", False))
        if str(getattr(A, "period", "")) == "tick":
            only_last = False
        if only_last and (not _in_critical_live_window(now_s)):
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
    bar_last = float(closes[-1])
    open_px = float(opens[-1])
    try:
        bar_high = float(highs[-1])
    except Exception:
        bar_high = bar_last
    last_px = _tick_last(C, fallback=bar_last)
    if last_px <= 0:
        last_px = _px_round(bar_last)
    chase_px = last_px
    if bt and bar_high > chase_px:
        chase_px = _px_round(bar_high)

    if bt:
        _bt_recover_position(now=now, last=last_px)

    holding = _has_position() or (bt and _bt_held_vol() > 0)
    mkt = _market_tag()

    interesting = holding or getattr(A, "pending", None) or (
        str(getattr(A, "buy_done_day", "") or "") == day
    )
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 30 == 0):
        A.ready_logged = True
        print(
            "%s" % STRATEGY_NAME,
            day,
            now_s,
            "mkt=%s n=%d last=%.3f open=%.3f hold=%s mode=%s "
            "buy_done=%s pending=%s cage=%.3f"
            % (
                mkt,
                len(closes),
                last_px,
                open_px,
                holding,
                _entry_mode_of(),
                getattr(A, "buy_done_day", ""),
                bool(getattr(A, "pending", None)),
                _cage_cap(C, last_px),
            ),
        )
        _bar_log(
            day=day,
            hhmmss=now_s,
            n=len(closes),
            last=round(last_px, 6),
            open=round(open_px, 6),
            hold=holding,
            mkt=mkt,
            buy_done=str(getattr(A, "buy_done_day", "") or ""),
            tag=tag,
        )

    # 已持仓：抢筹目标达成，不再交易
    if holding:
        return

    if ("BUY" in getattr(A, "acted", set())) and (not getattr(A, "pending", None)):
        return

    listing = _is_listing_day(C, day)
    eve = _is_eve_before_listing(C, now, day)
    if (not listing) and (not eve):
        if C.barpos % 60 == 0:
            print("%s skip: not listing day" % STRATEGY_NAME, day, A.stock)
            _event_log("skip_not_listing_day", day=day, stock=A.stock)
        return

    if _try_morning_buy(C, now, now_s, day):
        return

    # True=早盘撤单进行中；卡住超时已在 _cleanup_am_pending 强清，不再堵 Mode B
    if _cleanup_am_pending(C, now, now_s):
        return

    if not listing:
        return

    if mkt == "SZ":
        _handle_sz_mode_b(C, now, now_s, day, last_px)
    elif mkt == "SH":
        _handle_sh_mode_b(C, now, now_s, day, chase_px)
    else:
        if C.barpos % 60 == 0:
            print("%s unknown market stock=%s" % (STRATEGY_NAME, A.stock))
            _event_log("unknown_market", stock=A.stock)
