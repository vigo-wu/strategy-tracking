# === qmt_common/orders_pending.py ===
# 作用: 委托查询、撤单、pending 生命周期
# 主要符号: _process_pending, _deal_fill, _try_cancel_order, _new_remark
# 钩子(策略必须提供): _pending_on_buy_fill(pend, vol, px)
#                     _pending_on_sell_fill(pend, now, vol, px)
#                     _save_state
def _deal_fill_ex(remark, stock):
    """汇总匹配 remark+标的 的成交 -> (量, 均价, query_ok)。

    query_ok=False：接口失败；绝不能当成「无成交」去清影子 pending。
    """
    vol = 0
    notional = 0.0
    try:
        deals = get_trade_detail_data(A.acct, A.acct_type, "deal")
    except Exception as e:
        print(_strategy_tag(), "deal query fail", e)
        _event_log("deal_query_fail", error=str(e))
        return 0, 0.0, False
    if deals is None:
        _event_log("deal_query_fail", error="deals_none")
        return 0, 0.0, False
    for d in deals:
        if str(getattr(d, "m_strRemark", "") or "") != remark:
            continue
        code = getattr(d, "m_strInstrumentID", "") + "." + getattr(d, "m_strExchangeID", "")
        if code != stock:
            continue
        v = int(getattr(d, "m_nVolume", 0) or 0)
        px = float(getattr(d, "m_dPrice", 0) or 0)
        if v > 0:
            vol += v
            notional += v * px
    avg = (notional / float(vol)) if vol > 0 else 0.0
    return vol, avg, True


def _deal_fill(remark, stock):
    """汇总匹配 remark+标的 的成交 -> (量, 均价)。兼容旧调用。"""
    vol, avg, _ok = _deal_fill_ex(remark, stock)
    return vol, avg


def _shadow_reorder_block_arm():
    """影子强清后短冷却，避免同轮/紧接重挂双开。"""
    try:
        ms = float(globals().get("PENDING_SHADOW_REORDER_COOLDOWN_MS") or 2000.0)
    except Exception:
        ms = 2000.0
    if ms <= 0:
        A._shadow_reorder_block_until_ms = 0.0
        return
    now_ms = 0.0
    try:
        now_ms = datetime.datetime.now().timestamp() * 1000.0
    except Exception:
        now_ms = 0.0
    A._shadow_reorder_block_until_ms = now_ms + ms
    _event_log(
        "shadow_reorder_block",
        cooldown_ms=ms,
        until_ms=float(A._shadow_reorder_block_until_ms or 0),
    )


def _shadow_reorder_blocked(now=None):
    until = float(getattr(A, "_shadow_reorder_block_until_ms", 0) or 0)
    if until <= 0:
        return False
    now_ms = 0.0
    try:
        if now is not None and hasattr(now, "timestamp"):
            now_ms = now.timestamp() * 1000.0
        else:
            now_ms = datetime.datetime.now().timestamp() * 1000.0
    except Exception:
        now_ms = 0.0
    return now_ms < until


def _find_order_ex(remark, stock):
    """查找委托 -> (order_or_None, query_ok)。

    query_ok=False：接口失败，绝不能当成「已撤/不存在」去清 pending（防双挂）。
    """
    try:
        orders = get_trade_detail_data(A.acct, A.acct_type, "order")
    except Exception as e:
        print(_strategy_tag(), "order query fail", e)
        _event_log("order_query_fail", error=str(e))
        return None, False
    if orders is None:
        _event_log("order_query_fail", error="orders_none")
        return None, False
    hit = None
    for od in orders:
        if str(getattr(od, "m_strRemark", "") or "") != remark:
            continue
        code = getattr(od, "m_strInstrumentID", "") + "." + getattr(od, "m_strExchangeID", "")
        if code != stock:
            continue
        hit = od
    return hit, True


def _find_order(remark, stock):
    od, _ok = _find_order_ex(remark, stock)
    return od


def _order_traded_vol(od):
    if od is None:
        return 0
    for attr in ("m_nVolumeTraded", "m_nDealVolume", "m_nTradedVolume"):
        v = getattr(od, attr, None)
        if v is not None:
            try:
                return int(v)
            except Exception:
                pass
    return 0


def _order_sys_id(od):
    if od is None:
        return None
    for attr in ("m_strOrderSysID", "m_strOrderID", "m_nOrderID", "m_nRef"):
        v = getattr(od, attr, None)
        if v is None or v == "" or v == 0:
            continue
        return v
    return None


def _try_cancel_order(od, C):
    """尽力通过 QMT 内置撤单（API 名因版本而异）。"""
    oid = _order_sys_id(od)
    if oid is None:
        print(_strategy_tag(), "cancel skip: no order id")
        _event_log("cancel_skip", reason="no_order_id")
        return False
    for fn_name in ("cancel", "cancel_order", "cancelorder"):
        fn = globals().get(fn_name)
        if not callable(fn):
            continue
        try:
            fn(oid, A.acct, A.acct_type, C)
            print(_strategy_tag(), "cancel via", fn_name, oid)
            _event_log("cancel", via=fn_name, oid=str(oid))
            return True
        except TypeError:
            try:
                fn(oid, A.acct, A.acct_type)
                print(_strategy_tag(), "cancel via", fn_name, "(3arg)", oid)
                _event_log("cancel", via=fn_name, oid=str(oid), argc=3)
                return True
            except Exception as e:
                print(_strategy_tag(), fn_name, "fail", e)
                _event_log("cancel_fail", via=fn_name, error=str(e), oid=str(oid))
        except Exception as e:
            print(_strategy_tag(), fn_name, "fail", e)
            _event_log("cancel_fail", via=fn_name, error=str(e), oid=str(oid))
    print(_strategy_tag(), "cancel unavailable; keep waiting, oid=", oid)
    _event_log("cancel_unavailable", oid=str(oid))
    return False


def _clear_pending(reason=""):
    pend = getattr(A, "pending", None)
    if pend:
        print(_strategy_tag(), "pending clear", reason, pend.get("remark"))
        _event_log(
            "pending_clear",
            reason=reason,
            remark=pend.get("remark"),
            side=pend.get("side"),
            intent=pend.get("intent"),
            vol=pend.get("vol"),
        )
    A.pending = None
    _save_state()
    if str(reason or "") == "shadow_never_seen":
        _shadow_reorder_block_arm()


def _pending_check_should_log(
    intent, status, traded, cancel_req, order_seen, order_qok, age, force=False
):
    """pending_check 日志节流：状态变化、强制、或达到间隔才打。

    PENDING_CHECK_LOG_SEC：未配置或 <=0 = 每次都打（opt-in 节流）；>0 才节流。
    """
    if force:
        try:
            now_ms = datetime.datetime.now().timestamp() * 1000.0
        except Exception:
            now_ms = 0.0
        A._pending_check_log_ms = now_ms
        return True

    raw = globals().get("PENDING_CHECK_LOG_SEC", None)
    if raw is None:
        return True
    try:
        log_sec = float(raw)
    except Exception:
        return True
    if log_sec <= 0:
        return True

    fp = "%s|%s|%s|%s|%s|%s" % (
        str(intent or ""),
        str(status),
        str(int(traded or 0)),
        "1" if cancel_req else "0",
        "1" if order_seen else "0",
        "1" if order_qok else "0",
    )
    last_fp = str(getattr(A, "_pending_check_fp", "") or "")
    changed = fp != last_fp
    now_ms = 0.0
    try:
        now_ms = datetime.datetime.now().timestamp() * 1000.0
    except Exception:
        now_ms = 0.0
    last_ms = float(getattr(A, "_pending_check_log_ms", 0) or 0)
    due = (last_ms <= 0) or ((now_ms - last_ms) >= log_sec * 1000.0)
    if (not changed) and (not due):
        return False
    A._pending_check_fp = fp
    A._pending_check_log_ms = now_ms
    return True


def _shadow_clear_intent_ok(intent):
    """必须显式配置 PENDING_SHADOW_CLEAR_INTENTS；未配/空元组 = 不启用强清。"""
    allow = globals().get("PENDING_SHADOW_CLEAR_INTENTS", None)
    if allow is None:
        return False
    try:
        s = set(str(x) for x in allow)
    except Exception:
        return False
    if not s:
        return False
    return str(intent) in s


def _new_remark(tag, side, vol):
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return "%s %s %s %s x%d %s" % (_strategy_tag(), side, tag, A.stock, int(vol), ts)


def _process_pending(C, now):
    """实盘: 处理 pending；超时先撤；仅终态清空。仍阻塞则返回 True。"""
    pend = getattr(A, "pending", None)
    if not pend:
        return False
    if getattr(A, "is_backtest", False):
        A.pending = None
        return False
    if DRY_RUN:
        # dry_keep：保留虚拟挂单，供策略测撤补/升级；否则沿用旧行为立刻清空
        if bool(pend.get("dry_keep")):
            if bool(pend.get("cancel_requested")):
                _clear_pending("dry_cancel")
                return False
            return True
        A.pending = None
        return False

    remark = str(pend.get("remark", "") or "")
    stock = str(pend.get("stock", A.stock) or A.stock)
    side = str(pend.get("side", "") or "")
    intent = str(pend.get("intent", "") or "")
    target = int(pend.get("vol", 0) or 0)
    submitted = _parse_opened_at(pend.get("submitted_at"))
    age = 0.0
    if submitted is not None and now is not None:
        age = (now - submitted).total_seconds()

    # 见单后降频查 pending（抢筹场景见单即目标达成）
    if bool(pend.get("order_seen")):
        try:
            after_sec = float(globals().get("PENDING_AFTER_ACK_POLL_SEC") or 0)
        except Exception:
            after_sec = 0.0
        if after_sec > 0:
            last_ms = float(getattr(A, "_pending_after_ack_ms", 0) or 0)
            now_ms = 0.0
            try:
                now_ms = datetime.datetime.now().timestamp() * 1000.0
            except Exception:
                now_ms = 0.0
            if last_ms > 0 and (now_ms - last_ms) < after_sec * 1000.0:
                return True
            A._pending_after_ack_ms = now_ms

    ack_order_only = bool(globals().get("PENDING_ACK_ORDER_ONLY", False))
    shadow_order_only = bool(globals().get("PENDING_SHADOW_ORDER_ONLY", False))
    # 见单前可不查成交，优先确认委托进场
    if ack_order_only and (not bool(pend.get("order_seen"))):
        deal_vol, deal_avg, deal_qok = 0, 0.0, True
    else:
        deal_vol, deal_avg, deal_qok = _deal_fill_ex(remark, stock)
    od, order_qok = _find_order_ex(remark, stock)
    status = int(getattr(od, "m_nOrderStatus", -1) or -1) if od is not None else -1
    traded = max(deal_vol, _order_traded_vol(od))
    px = deal_avg if deal_avg > 0 else float(pend.get("price_hint", 0) or 0)
    cancel_req = bool(pend.get("cancel_requested"))
    if od is not None and not pend.get("order_seen"):
        pend["order_seen"] = True
        pend["shadow_miss_hits"] = 0
        A.pending = pend
        try:
            _save_state()
        except Exception:
            pass
        # 委托成功确认：柜台查询已见到本 remark 委托（不以成交为准）
        print(
            _strategy_tag(),
            "order acked intent=%s status=%s age=%.1fs remark=%s"
            % (intent, status, age, remark),
        )
        _event_log(
            "order_acked",
            intent=intent,
            status=status,
            age_sec=round(age, 3),
            remark=remark,
            side=side,
            vol=target,
            price=float(pend.get("price_hint") or 0),
        )
        try:
            A._pending_after_ack_ms = datetime.datetime.now().timestamp() * 1000.0
        except Exception:
            A._pending_after_ack_ms = 0.0

    order_seen = bool(pend.get("order_seen"))

    shadow_sec = 0.0
    try:
        shadow_sec = float(globals().get("PENDING_SHADOW_CLEAR_SEC") or 0)
    except Exception:
        shadow_sec = 0.0
    shadow_intent = _shadow_clear_intent_ok(intent)
    # 影子：默认须成交查询成功且为0；PENDING_SHADOW_ORDER_ONLY 时只看委托
    if shadow_order_only:
        shadow_candidate = (
            shadow_sec > 0
            and shadow_intent
            and (not cancel_req)
            and (not order_seen)
            and order_qok
            and (od is None)
            and age >= shadow_sec
        )
    else:
        shadow_candidate = (
            shadow_sec > 0
            and shadow_intent
            and (not cancel_req)
            and (not order_seen)
            and order_qok
            and (od is None)
            and deal_qok
            and int(deal_vol or 0) <= 0
            and age >= shadow_sec
        )
    # 影子候选窗口内强制打 pending_check，保留未见单取证（通常仅数次命中）
    force_pending_log = bool(shadow_candidate)

    if _pending_check_should_log(
        intent,
        status,
        traded,
        cancel_req,
        order_seen,
        order_qok,
        age,
        force=force_pending_log,
    ):
        print(
            _strategy_tag(),
            "pending check",
            intent,
            "deal=",
            deal_vol,
            "traded=",
            traded,
            "status=",
            status,
            "age=%.0fs" % age,
            "cancel_req=",
            cancel_req,
            "qok=",
            order_qok,
            "seen=",
            order_seen,
        )
        _event_log(
            "pending_check",
            intent=intent,
            side=side,
            deal=deal_vol,
            traded=traded,
            status=status,
            age_sec=int(age),
            cancel_req=cancel_req,
            target=target,
            remark=remark,
            order_qok=order_qok,
            order_seen=order_seen,
            shadow_candidate=bool(shadow_candidate),
        )

    filled = globals().get("_ORDER_FILLED") or (56, 8)
    dead = globals().get("_ORDER_DEAD") or (54, 57, 53, 5, 6, 9)
    # 股票默认 100；可转债等可在策略 config 设 LOT_SIZE=10
    lot = int(globals().get("LOT_SIZE") or 100)
    if lot <= 0:
        lot = 100
    done_fill = traded >= target and target >= lot
    status_filled = status in filled
    status_dead = status in dead

    if done_fill or (status_filled and traded >= lot):
        use_vol = traded if traded >= lot else deal_vol
        if side == "buy":
            _pending_on_buy_fill(pend, use_vol, px)
        else:
            _pending_on_sell_fill(pend, now, use_vol, px)
        _clear_pending("filled")
        return False

    if status_dead:
        if traded > 0:
            if side == "buy":
                _pending_on_buy_fill(pend, traded, px)
            else:
                _pending_on_sell_fill(pend, now, traded, px)
            _clear_pending("dead-partial")
        else:
            _clear_pending("rejected/cancelled")
        return False

    # 委托已离簿但成交查询显示有量：先记账，禁止当影子重挂
    # 抢筹-only 模式（PENDING_SHADOW_ORDER_ONLY）不做成交补记，避免拖慢/误判
    if (
        (not shadow_order_only)
        and (not cancel_req)
        and (not order_seen)
        and order_qok
        and (od is None)
        and deal_qok
        and int(deal_vol or 0) > 0
    ):
        use_vol = int(deal_vol)
        print(
            _strategy_tag(),
            "deal without open order -> fill intent=%s vol=%s"
            % (intent, use_vol),
        )
        _event_log(
            "deal_without_order",
            intent=intent,
            vol=use_vol,
            price=px,
            remark=remark,
            age_sec=round(age, 3),
        )
        if side == "buy":
            _pending_on_buy_fill(pend, use_vol, px)
        else:
            _pending_on_sell_fill(pend, now, use_vol, px)
        _clear_pending("deal_without_order")
        return False

    # 未见单影子 pending：委托未见 + 成交查询成功且为0；命中间隔 + 二次确认
    # PENDING_SHADOW_CLEAR_INTENTS 必须显式配置
    if shadow_sec > 0 and shadow_intent:
        if shadow_candidate:
            try:
                need_hits = int(globals().get("PENDING_SHADOW_CLEAR_HITS") or 3)
            except Exception:
                need_hits = 3
            if need_hits < 1:
                need_hits = 1
            try:
                hit_gap_ms = float(globals().get("PENDING_SHADOW_CLEAR_HIT_GAP_MS") or 1000)
            except Exception:
                hit_gap_ms = 1000.0
            if hit_gap_ms < 0:
                hit_gap_ms = 0.0
            now_ms = 0.0
            try:
                now_ms = datetime.datetime.now().timestamp() * 1000.0
            except Exception:
                now_ms = 0.0
            last_hit_ms = float(pend.get("shadow_miss_hit_ms") or 0)
            can_hit = (last_hit_ms <= 0) or ((now_ms - last_hit_ms) >= hit_gap_ms)
            if can_hit:
                hits = int(pend.get("shadow_miss_hits") or 0) + 1
                pend["shadow_miss_hits"] = hits
                pend["shadow_miss_hit_ms"] = now_ms
                A.pending = pend
                try:
                    _save_state()
                except Exception:
                    pass
            else:
                hits = int(pend.get("shadow_miss_hits") or 0)
            if can_hit and hits >= need_hits:
                od2, qok2 = _find_order_ex(remark, stock)
                if shadow_order_only:
                    confirm_ok = bool(qok2) and (od2 is None)
                    deal2, avg2, deal_qok2 = 0, 0.0, True
                else:
                    deal2, avg2, deal_qok2 = _deal_fill_ex(remark, stock)
                    confirm_ok = (
                        bool(qok2)
                        and (od2 is None)
                        and bool(deal_qok2)
                        and int(deal2 or 0) <= 0
                    )
                _event_log(
                    "pending_shadow_confirm",
                    intent=intent,
                    age_sec=round(age, 3),
                    shadow_sec=shadow_sec,
                    hits=hits,
                    need_hits=need_hits,
                    hit_gap_ms=hit_gap_ms,
                    order_qok=bool(order_qok),
                    order_seen=bool(order_seen),
                    deal_qok=bool(deal_qok),
                    deal=int(deal_vol or 0),
                    shadow_order_only=bool(shadow_order_only),
                    confirm_ok=confirm_ok,
                    confirm_qok=bool(qok2),
                    confirm_od=(od2 is not None),
                    confirm_deal_qok=bool(deal_qok2),
                    confirm_deal=int(deal2 or 0),
                    remark=remark,
                )
                if confirm_ok:
                    print(
                        _strategy_tag(),
                        "pending shadow clear: never acked intent=%s age=%.1fs hits=%d"
                        % (intent, age, hits),
                    )
                    _event_log(
                        "pending_shadow_clear",
                        intent=intent,
                        age_sec=round(age, 3),
                        shadow_sec=shadow_sec,
                        hits=hits,
                        need_hits=need_hits,
                        order_qok=True,
                        order_seen=False,
                        deal_qok=bool(deal_qok2),
                        deal=int(deal2 or 0),
                        status=status,
                        remark=remark,
                    )
                    _clear_pending("shadow_never_seen")
                    return False
                if od2 is not None:
                    pend["order_seen"] = True
                    print(
                        _strategy_tag(),
                        "order acked (shadow confirm) intent=%s remark=%s"
                        % (intent, remark),
                    )
                    _event_log(
                        "order_acked",
                        intent=intent,
                        status=int(getattr(od2, "m_nOrderStatus", -1) or -1),
                        age_sec=round(age, 3),
                        remark=remark,
                        side=side,
                        via="shadow_confirm",
                    )
                elif (not shadow_order_only) and deal_qok2 and int(deal2 or 0) > 0:
                    use_vol = int(deal2)
                    fill_px = avg2 if avg2 > 0 else px
                    if side == "buy":
                        _pending_on_buy_fill(pend, use_vol, fill_px)
                    else:
                        _pending_on_sell_fill(pend, now, use_vol, fill_px)
                    _clear_pending("deal_without_order_confirm")
                    return False
                pend["shadow_miss_hits"] = 0
                pend["shadow_miss_hit_ms"] = 0
                A.pending = pend
                try:
                    _save_state()
                except Exception:
                    pass
                if (not confirm_ok) and (od2 is None):
                    print(
                        _strategy_tag(),
                        "pending shadow confirm fail; keep pending intent=%s"
                        % intent,
                    )
        else:
            if int(pend.get("shadow_miss_hits") or 0) > 0:
                pend["shadow_miss_hits"] = 0
                pend["shadow_miss_hit_ms"] = 0
                A.pending = pend
                try:
                    _save_state()
                except Exception:
                    pass

    timeout = float(globals().get("PENDING_TIMEOUT_SEC") or 180)
    orphan = float(globals().get("PENDING_ORPHAN_SEC") or 60)
    retry_sec = float(globals().get("CANCEL_RETRY_SEC") or 1.0)

    # 主动撤单中：周期重试；仅「曾经见过委托 + 查询成功 + 委托已消失」才可清 pending
    if cancel_req:
        cancel_at = _parse_opened_at(pend.get("cancel_at"))
        cancel_age = 0.0
        if cancel_at is not None and now is not None:
            cancel_age = (now - cancel_at).total_seconds()
        if not order_qok:
            print(_strategy_tag(), "cancel wait: order query fail, keep pending")
            _event_log(
                "cancel_wait_query_fail",
                remark=remark,
                intent=intent,
                cancel_age_sec=int(cancel_age),
            )
            return True
        if od is not None:
            last_retry = _parse_opened_at(pend.get("cancel_retry_at"))
            retry_age = 1e9
            if last_retry is not None and now is not None:
                retry_age = (now - last_retry).total_seconds()
            if last_retry is None or retry_age >= retry_sec:
                ok = _try_cancel_order(od, C)
                pend["cancel_retry_at"] = (now or datetime.datetime.now()).strftime(
                    "%Y%m%d%H%M%S"
                )
                A.pending = pend
                _save_state()
                if not ok:
                    print(
                        _strategy_tag(),
                        "cancel retry fail; order still open age=%.0fs" % cancel_age,
                    )
                    _event_log(
                        "cancel_retry_fail",
                        remark=remark,
                        intent=intent,
                        cancel_age_sec=int(cancel_age),
                    )
            return True
        # 查询成功且委托列表中已无此单
        if pend.get("order_seen") and cancel_age >= orphan:
            if traded > 0:
                if side == "buy":
                    _pending_on_buy_fill(pend, traded, px)
                else:
                    _pending_on_sell_fill(pend, now, traded, px)
                _clear_pending("cancel_gone_partial")
            else:
                print(
                    _strategy_tag(),
                    "pending clear after cancel: order seen then gone",
                )
                _event_log(
                    "pending_cancel_confirmed",
                    remark=remark,
                    intent=intent,
                    cancel_age_sec=int(cancel_age),
                )
                _clear_pending("cancel_confirmed_gone")
            return False
        if cancel_age >= orphan and (not pend.get("order_seen")):
            # 从未见到委托：拒绝 orphan 清，避免旧单仍在时双挂
            print(
                _strategy_tag(),
                "orphan blocked: order never seen, keep pending age=%.0fs"
                % cancel_age,
            )
            _event_log(
                "pending_orphan_blocked",
                remark=remark,
                intent=intent,
                cancel_age_sec=int(cancel_age),
                reason="order_never_seen",
            )
        return True

    if age >= timeout:
        exempt = globals().get("PENDING_TIMEOUT_EXEMPT_INTENTS") or ()
        try:
            exempt_set = set(str(x) for x in exempt)
        except Exception:
            exempt_set = set()
        if intent in exempt_set or bool(pend.get("no_timeout")):
            # 长生命周期挂单（如深市临停埋单/沪市首单）禁止超时撤
            log_sec = float(globals().get("PENDING_TIMEOUT_EXEMPT_LOG_SEC") or 300)
            last_log = _parse_opened_at(pend.get("timeout_exempt_log_at"))
            need_log = last_log is None
            if (not need_log) and now is not None and last_log is not None:
                need_log = (now - last_log).total_seconds() >= log_sec
            if need_log:
                print(
                    _strategy_tag(),
                    "pending timeout exempt intent=",
                    intent,
                    "age=%.0fs" % age,
                )
                _event_log(
                    "pending_timeout_exempt",
                    remark=remark,
                    intent=intent,
                    age_sec=int(age),
                )
                pend["timeout_exempt_log_at"] = (
                    now or datetime.datetime.now()
                ).strftime("%Y%m%d%H%M%S")
                A.pending = pend
                try:
                    _save_state()
                except Exception:
                    pass
            return True
        if od is not None:
            _try_cancel_order(od, C)
        else:
            print(_strategy_tag(), "pending timeout, order not visible yet")
            _event_log("pending_timeout", remark=remark, intent=intent, age_sec=int(age))
        pend["cancel_requested"] = True
        pend["cancel_at"] = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
        A.pending = pend
        _save_state()
        return True

    return True
