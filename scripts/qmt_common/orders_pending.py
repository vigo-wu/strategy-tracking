# === qmt_common/orders_pending.py ===
# 作用: 委托查询、撤单、pending 生命周期
# 主要符号: _process_pending, _deal_fill, _try_cancel_order, _new_remark
# 钩子(策略必须提供): _pending_on_buy_fill(pend, vol, px)
#                     _pending_on_sell_fill(pend, now, vol, px)
#                     _save_state
def _deal_fill(remark, stock):
    """汇总匹配 remark+标的 的成交 -> (量, 均价)。"""
    vol = 0
    notional = 0.0
    try:
        deals = get_trade_detail_data(A.acct, A.acct_type, "deal")
    except Exception as e:
        print(_strategy_tag(), "deal query fail", e)
        _event_log("deal_query_fail", error=str(e))
        return 0, 0.0
    if not deals:
        return 0, 0.0
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
    return vol, avg


def _find_order(remark, stock):
    try:
        orders = get_trade_detail_data(A.acct, A.acct_type, "order")
    except Exception as e:
        print(_strategy_tag(), "order query fail", e)
        _event_log("order_query_fail", error=str(e))
        return None
    if not orders:
        return None
    hit = None
    for od in orders:
        if str(getattr(od, "m_strRemark", "") or "") != remark:
            continue
        code = getattr(od, "m_strInstrumentID", "") + "." + getattr(od, "m_strExchangeID", "")
        if code != stock:
            continue
        hit = od
    return hit


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


def _new_remark(tag, side, vol):
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return "%s %s %s %s x%d %s" % (_strategy_tag(), side, tag, A.stock, int(vol), ts)


def _process_pending(C, now):
    """实盘: 处理 pending；超时先撤；仅终态清空。仍阻塞则返回 True。"""
    pend = getattr(A, "pending", None)
    if not pend:
        return False
    if getattr(A, "is_backtest", False) or DRY_RUN:
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

    deal_vol, deal_avg = _deal_fill(remark, stock)
    od = _find_order(remark, stock)
    status = int(getattr(od, "m_nOrderStatus", -1) or -1) if od is not None else -1
    traded = max(deal_vol, _order_traded_vol(od))
    px = deal_avg if deal_avg > 0 else float(pend.get("price_hint", 0) or 0)
    cancel_req = bool(pend.get("cancel_requested"))

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
    )

    filled = globals().get("_ORDER_FILLED") or (56, 8)
    dead = globals().get("_ORDER_DEAD") or (54, 57, 53, 5, 6, 9)
    done_fill = traded >= target and target >= 100
    status_filled = status in filled
    status_dead = status in dead

    if done_fill or (status_filled and traded >= 100):
        use_vol = traded if traded >= 100 else deal_vol
        if side == "buy":
            _pending_on_buy_fill(pend, use_vol, px)
        else:
            _pending_on_sell_fill(pend, now, use_vol, px)
        _clear_pending("filled")
        return False

    if status_dead:
        if traded >= 100:
            if side == "buy":
                _pending_on_buy_fill(pend, traded, px)
            else:
                _pending_on_sell_fill(pend, now, traded, px)
            _clear_pending("dead-partial")
        else:
            _clear_pending("rejected/cancelled")
        return False

    timeout = float(globals().get("PENDING_TIMEOUT_SEC") or 180)
    orphan = float(globals().get("PENDING_ORPHAN_SEC") or 60)
    if age >= timeout:
        if not cancel_req:
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
        cancel_at = _parse_opened_at(pend.get("cancel_at"))
        cancel_age = 0.0
        if cancel_at is not None and now is not None:
            cancel_age = (now - cancel_at).total_seconds()
        if od is None and cancel_age >= orphan:
            print(_strategy_tag(), "pending orphan clear (no order after cancel wait)")
            _event_log(
                "pending_orphan",
                remark=remark,
                intent=intent,
                cancel_age_sec=int(cancel_age),
            )
            _clear_pending("orphan")
            return False
        return True

    return True
