# === cbauct/strategy.py ===
# 定稿 model.md v2.8:
#   深市: 临停埋 143（禁超时撤）→ 14:57 封板后撤未成单再挂顶格
#   沪市: 14:57 起连续竞价，从 143 阶梯撤补追至 157.30


def _has_position():
    """可转债：任意张数>0 即视为有仓（防部分成交影子丢失后重复满仓）。"""
    pos = getattr(A, "position", None)
    return isinstance(pos, dict) and int(pos.get("shares", 0) or 0) > 0


def _cb_lot(price, budget):
    lot = int(globals().get("LOT_SIZE") or 10)
    if price is None or price <= 0 or budget <= 0 or lot <= 0:
        return 0
    return int(float(budget) // (float(price) * lot)) * lot


def _remaining_buy_budget(cash):
    """预算扣减已持仓成本，防止部分成交后再按满额重挂。"""
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
    pos = {
        "shares": new_sh,
        "price": avg,
        "cost": round(new_cost, 2),
        "opened_at": ot
        if prev_sh <= 0
        else str((prev or {}).get("opened_at") or ot),
    }
    for k, v in extra.items():
        if v is not None:
            pos[k] = v
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
    day = buy_day or ""
    if day:
        A.buy_done_day = day
    _save_state()
    print(_strategy_tag(), "BUY filled", A.position, "add_vol=", vol, "lot=", lot)
    _event_log(
        "buy_filled",
        position=A.position,
        vol=vol,
        price=price,
        opened_at=ot,
        add_vol=vol,
    )


def _pending_on_buy_fill(pend, vol, px):
    extra = pend.get("extra_pos") if isinstance(pend.get("extra_pos"), dict) else {}
    _apply_cb_buy_fill(vol, px, pend.get("opened_at") or pend.get("submitted_at"), **extra)


def _order_buy_limit(C, price, now, budget=None, intent="BUY"):
    """限价买入 prType=11。"""
    lot = int(globals().get("LOT_SIZE") or 10)
    price = _px_round(price)
    if price <= 0:
        return False
    if getattr(A, "pending", None):
        print(_strategy_tag(), "buy skip: pending active")
        _event_log("buy_skip", reason="pending_active")
        return False
    if _has_position() or (
        getattr(A, "is_backtest", False) and _bt_held_vol() > 0
    ):
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

    ot = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    msg = _new_remark(intent, "BUY", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@limit", price, intent)
    exempt = set(str(x) for x in (globals().get("PENDING_TIMEOUT_EXEMPT_INTENTS") or ()))
    no_timeout = str(intent) in exempt
    if DRY_RUN:
        if bool(globals().get("DRY_RUN_FILL_IMMEDIATE", False)):
            _apply_cb_buy_fill(vol, price, ot, intent=intent)
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
            "extra_pos": {"intent": intent},
        }
        A.buy_done_day = ot[:8]
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
            dry_keep=True,
        )
        if (
            bool(globals().get("DRY_RUN_FILL_ON_LIMIT", True))
            and price + 1e-9 >= _limit_up()
        ):
            _apply_cb_buy_fill(vol, price, ot, intent=intent)
            A.pending = None
            _save_state()
            print(_strategy_tag(), "DRY fill on limit", price)
        return True
    try:
        # prType=11 指定价；quickTrade=1 即时报单（集合竞价/连续均可挂）
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
        _apply_cb_buy_fill(vol, price, ot, intent=intent)
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
        "extra_pos": {"intent": intent},
    }
    A.buy_done_day = ot[:8]
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
    )
    return True


def _request_pending_cancel(C, now, reason):
    """主动撤当前 pending；未见委托时不打 cancel_requested，避免永久卡住。"""
    pend = getattr(A, "pending", None)
    if not isinstance(pend, dict):
        return False
    if pend.get("cancel_requested"):
        return True
    # DRY 虚拟单：直接清掉，供同 bar 重挂
    if DRY_RUN and bool(pend.get("dry_keep")):
        print(_strategy_tag(), "DRY cancel", reason, "px=", pend.get("price_hint"))
        _event_log(
            "chase_cancel",
            reason=reason,
            price=pend.get("price_hint"),
            remark=pend.get("remark"),
            dry=True,
        )
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
        # 委托尚未回写：不标记 cancel_requested，下根再试
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
    _event_log(
        "chase_cancel",
        reason=reason,
        price=pend.get("price_hint"),
        remark=remark,
        order_seen=True,
    )
    return True


def _reconcile_with_broker():
    """实盘启动/暖机切活：用券商持仓校正影子仓，防状态丢失后重复买。"""
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return
    if _available_cash() is None:
        print(_strategy_tag(), "reconcile skip: not login")
        _event_log("reconcile_skip", reason="not_login")
        return
    lot = int(globals().get("LOT_SIZE") or 10)
    stock = str(getattr(A, "stock", "") or "")
    try:
        positions = get_trade_detail_data(A.acct, A.acct_type, "position")
    except Exception as e:
        print(_strategy_tag(), "reconcile position query fail", e)
        _event_log("reconcile_fail", error=str(e))
        return
    if positions is None:
        _event_log("reconcile_fail", error="positions_none")
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
            if isinstance(getattr(A, "position", None), dict):
                ot = str(A.position.get("opened_at", "") or "")
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
            if not hasattr(A, "acted") or A.acted is None:
                A.acted = set()
            A.acted.add("BUY")
            day = ot[:8] if len(ot) >= 8 else datetime.datetime.now().strftime("%Y%m%d")
            A.buy_done_day = day
            _save_state()
            print(_strategy_tag(), "reconcile sync from broker vol=", vol, "cost=", cost)
            _event_log("reconcile_sync", vol=vol, cost=cost)
        return
    # 已登录且持仓列表确认无此标的（或量为0）→ 清影子仓，避免假持仓挡买入
    if (not found or vol <= 0) and _has_position():
        print(
            _strategy_tag(),
            "reconcile clear shadow (broker flat) was=",
            A.position,
        )
        _event_log("reconcile_clear", was=A.position, broker_vol=vol, found=found)
        A.position = None
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


def _handle_sz(C, now, now_s, day, last_px):
    """深市两段：临停埋 143 → 封板后撤未成单再挂 157.30。"""
    reopen = _reopen_cap()
    limit_up = _limit_up()
    pre_s = str(globals().get("SZ_PREPLACE_START") or "130000")
    pre_e = str(globals().get("SZ_PREPLACE_END") or "145459")
    close_s = str(globals().get("SZ_CLOSE_BUY_START") or "145700")
    close_e = str(globals().get("SZ_CLOSE_BUY_END") or "145950")
    alert_sec = float(globals().get("SZ_ESCALATE_ALERT_SEC") or 2.0)

    # 阶段1：临停期埋首段顶格（禁 157.30）
    if _in_window(now_s, pre_s, pre_e):
        if str(getattr(A, "sz_preplace_day", "") or "") == day:
            return
        if _has_position() or getattr(A, "pending", None):
            return
        print(
            "%s SZ_PREPLACE buy @%.3f window=%s-%s (禁挂涨停顶格)"
            % (STRATEGY_NAME, reopen, pre_s, pre_e)
        )
        _event_log("sz_preplace", price=reopen, window="%s-%s" % (pre_s, pre_e))
        if _order_buy_limit(C, reopen, now, intent="SZ_PREPLACE"):
            A.sz_preplace_day = day
            A.buy_done_day = day
            _save_state()
        return

    # 阶段2：复牌后仅当最新价已封全天上限，才挂收盘顶格
    if not _in_window(now_s, close_s, close_e):
        return
    if str(getattr(A, "sz_close_buy_day", "") or "") == day:
        return
    if _has_position():
        return
    if last_px + 1e-9 < limit_up:
        if C.barpos % 5 == 0:
            print(
                "%s SZ_CLOSE wait limit_up last=%.3f need=%.3f"
                % (STRATEGY_NAME, last_px, limit_up)
            )
        return

    pend = getattr(A, "pending", None)
    if isinstance(pend, dict):
        # 143 未成且已封板：必须先撤，否则卡在不可撤的收盘竞价里踏空
        intent = str(pend.get("intent", "") or "")
        old_px = float(pend.get("price_hint") or 0)
        if not pend.get("cancel_requested"):
            A.sz_escalate_day = day
            print(
                "%s SZ_ESCALATE cancel old=%.3f intent=%s -> then @%.3f"
                % (STRATEGY_NAME, old_px, intent, limit_up)
            )
            _event_log(
                "sz_escalate_cancel",
                old=old_px,
                intent=intent,
                target=limit_up,
                last=last_px,
            )
            _request_pending_cancel(C, now, "sz_escalate_to_limit")
            A.sz_escalate_alert_ms = _now_ms(now)
            _save_state()
            # DRY 即时清掉 pending 时可同 bar 继续挂顶格
            if getattr(A, "pending", None):
                return
            pend = None
        else:
            # 撤单中仍未清：周期告警（可能已进入不可撤时段）
            now_ms = _now_ms(now)
            last_alert = float(getattr(A, "sz_escalate_alert_ms", 0) or 0)
            if last_alert <= 0 or (now_ms - last_alert) >= alert_sec * 1000.0:
                A.sz_escalate_alert_ms = now_ms
                print(
                    "%s SZ_ESCALATE ALERT: 143未撤掉无法挂157.30 pending=%s "
                    "px=%.3f - 若已进收盘竞价请人工处理"
                    % (STRATEGY_NAME, intent, old_px)
                )
                _event_log(
                    "sz_escalate_alert",
                    intent=intent,
                    price=old_px,
                    last=last_px,
                    cancel_requested=True,
                )
                _save_state()
            return

    if isinstance(pend, dict):
        return

    # pending 已清（撤成/废单）：挂顶格
    print(
        "%s SZ_CLOSE buy @%.3f last=%.3f window=%s-%s"
        % (STRATEGY_NAME, limit_up, last_px, close_s, close_e)
    )
    _event_log(
        "sz_close_buy",
        price=limit_up,
        last=last_px,
        window="%s-%s" % (close_s, close_e),
        escalated=str(getattr(A, "sz_escalate_day", "") or "") == day,
    )
    if _order_buy_limit(C, limit_up, now, intent="SZ_CLOSE"):
        A.sz_close_buy_day = day
        A.buy_done_day = day
        _save_state()


def _handle_sh(C, now, now_s, day, last_px):
    """沪市连续竞价：143 起阶梯追至 157.30。"""
    start = str(globals().get("SH_CHASE_START") or "145700")
    end = str(globals().get("SH_CHASE_END") or "145955")
    if not _in_window(now_s, start, end):
        return
    if _has_position():
        return

    reopen = _reopen_cap()
    limit_up = _limit_up()
    target = _cage_cap(last_px if last_px > 0 else reopen)
    if target < reopen:
        target = reopen
    interval = float(globals().get("SH_CHASE_INTERVAL_MS") or 200)
    min_step = float(globals().get("CHASE_MIN_STEP") or 0.01)
    now_ms = _now_ms(now)
    pend = getattr(A, "pending", None)
    # 节流只抑制「重复发起撤单」；pending 已空时允许立刻重挂
    if isinstance(pend, dict):
        last_ms = float(getattr(A, "sh_chase_at_ms", 0) or 0)
        if last_ms > 0 and (now_ms - last_ms) < interval:
            if pend.get("cancel_requested"):
                pass  # 撤单等待中仍可走下面告警分支
            else:
                return

    if isinstance(pend, dict):
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
                # DRY 即时清 pending 后同 bar 重挂
                if getattr(A, "pending", None):
                    return
            else:
                if C.barpos % 3 == 0:
                    print(
                        "%s SH_CHASE wait cancel old=%.3f target=%.3f"
                        % (STRATEGY_NAME, old_px, target)
                    )
                return
            # fall through when dry cancel cleared pending
        else:
            return

    if "BUY" in getattr(A, "acted", set()):
        return
    A.sh_chase_at_ms = now_ms
    intent = "SH_OPEN" if str(getattr(A, "sh_chase_day", "") or "") != day else "SH_CHASE"
    print(
        "%s %s buy @%.3f last=%.3f cage=%.3f"
        % (STRATEGY_NAME, intent, target, last_px, target)
    )
    _event_log("sh_buy", intent=intent, price=target, last=last_px)
    if _order_buy_limit(C, target, now, intent=intent):
        A.sh_chase_day = day
        A.sh_last_order_px = float(target)
        A.buy_done_day = day
        _save_state()


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
                # pending 处理中仍允许沪市在同 bar 评估是否追单
                pass
            else:
                # pending 已清空（成交/废单），继续本 bar 逻辑
                pass
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
    bar_last = float(closes[-1])
    open_px = float(opens[-1])
    last_px = _tick_last(C, fallback=bar_last)
    if last_px <= 0:
        last_px = _px_round(bar_last)

    if bt:
        _bt_recover_position(now=now, last=last_px)

    holding = _has_position() or (bt and _bt_held_vol() > 0)
    mkt = _market_tag()
    size_yi = _issue_size_yi()

    interesting = holding or getattr(A, "pending", None) or (
        str(getattr(A, "buy_done_day", "") or "") == day
    )
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 30 == 0):
        A.ready_logged = True
        print(
            "%s" % STRATEGY_NAME,
            day,
            now_s,
            "mkt=%s n=%d last=%.3f open=%.3f hold=%s size=%s "
            "buy_done=%s pending=%s cage=%.3f"
            % (
                mkt,
                len(closes),
                last_px,
                open_px,
                holding,
                size_yi,
                getattr(A, "buy_done_day", ""),
                bool(getattr(A, "pending", None)),
                _cage_cap(last_px),
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
            size_yi=size_yi,
            buy_done=str(getattr(A, "buy_done_day", "") or ""),
            tag=tag,
        )

    # 已成交则停；有 pending 时沪市仍可撤补追单
    if holding:
        return
    if ("BUY" in getattr(A, "acted", set())) and (not getattr(A, "pending", None)):
        return

    if not _is_listing_day(C, day):
        if C.barpos % 60 == 0:
            print("%s skip: not listing day" % STRATEGY_NAME, day, A.stock)
            _event_log("skip_not_listing_day", day=day, stock=A.stock)
        return

    if mkt == "SZ":
        _handle_sz(C, now, now_s, day, last_px)
    elif mkt == "SH":
        _handle_sh(C, now, now_s, day, last_px)
    else:
        if C.barpos % 60 == 0:
            print("%s unknown market stock=%s" % (STRATEGY_NAME, A.stock))
            _event_log("unknown_market", stock=A.stock)
