# === hongli/orders.py ===
# 作用: 委托生命周期：pending、买卖、成交回填
# 主要符号: _process_pending, _order_buy, _order_sell
# 拼接序: 13/16 | 上一部: broker.py | 下一部: runtime.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
def _deal_fill(remark, stock):
    """汇总匹配 remark+标的 的成交 -> (量, 均价)。"""
    vol = 0
    notional = 0.0
    try:
        deals = get_trade_detail_data(A.acct, A.acct_type, "deal")
    except Exception as e:
        print("HongliT deal query fail", e)
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
        print("HongliT order query fail", e)
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
        print("HongliT cancel skip: no order id")
        return False
    # 优先 cancel(sysId, account, accountType, ContextInfo)
    for fn_name in ("cancel", "cancel_order", "cancelorder"):
        fn = globals().get(fn_name)
        if not callable(fn):
            continue
        try:
            fn(oid, A.acct, A.acct_type, C)
            print("HongliT cancel via", fn_name, oid)
            return True
        except TypeError:
            try:
                fn(oid, A.acct, A.acct_type)
                print("HongliT cancel via", fn_name, "(3arg)", oid)
                return True
            except Exception as e:
                print("HongliT", fn_name, "fail", e)
        except Exception as e:
            print("HongliT", fn_name, "fail", e)
    print("HongliT cancel unavailable; keep waiting for terminal status, oid=", oid)
    return False


def _apply_buy_fill(intent, vol, price, opened_at):
    vol = int(vol)
    price = float(price) if price and price > 0 else 0.0
    if vol < 100:
        return
    ot = str(opened_at or "").strip()
    if not ot:
        ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    leg = {
        "shares": vol,
        "price": price,
        "cost": round(vol * price, 2),
        "opened_at": ot,
    }
    if intent == "RA":
        A.float_a = leg
        A.acted.add("RA")
        if getattr(A, "is_backtest", False):
            A.bt_opened_at = ot
        print("HongliT R-A filled", A.float_a)
    elif intent == "RB":
        A.float_b = leg
        A.acted.add("RB")
        print("HongliT R-B filled", A.float_b)
    buy_day = ot[:8] if len(ot) >= 8 else None
    _bt_held_add(vol, buy_day=buy_day)
    _save_state()


def _apply_sell_fill(now, intent, last_hint, filled_vol):
    """卖出成交后清空或缩减浮仓。"""
    want = _sell_float_vol()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol())
    filled_vol = int(filled_vol)
    tag = intent or "SELL"
    if filled_vol >= max(100, int(want * 0.95)) or filled_vol >= want:
        _clear_float_after_sell(now, tag, last=last_hint)
        return
    if filled_vol >= 100:
        remain = max(0, want - filled_vol)
        print("HongliT partial sell fill", filled_vol, "remain~", remain)
        _shrink_float_to_vol(remain)
        _bt_held_set(remain)
        if remain < 100:
            _clear_float_after_sell(now, tag + "/partial", last=last_hint)
        else:
            # 当日剩余仍可卖（不要标记 acted SELL）
            _save_state()


def _clear_pending(reason=""):
    if getattr(A, "pending", None):
        print("HongliT pending clear", reason, A.pending.get("remark"))
    A.pending = None
    _save_state()


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
        "HongliT pending check",
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

    done_fill = traded >= target and target >= 100
    status_filled = status in _ORDER_FILLED
    status_dead = status in _ORDER_DEAD

    if done_fill or (status_filled and traded >= 100):
        use_vol = traded if traded >= 100 else deal_vol
        if side == "buy":
            _apply_buy_fill(intent, use_vol, px, pend.get("opened_at"))
        else:
            _apply_sell_fill(now, intent, pend.get("last_hint"), use_vol)
        _clear_pending("filled")
        return False

    if status_dead:
        if traded >= 100:
            if side == "buy":
                _apply_buy_fill(intent, traded, px, pend.get("opened_at"))
            else:
                _apply_sell_fill(now, intent, pend.get("last_hint"), traded)
            _clear_pending("dead-partial")
        else:
            _clear_pending("rejected/cancelled")
        return False

    # 超时: 请求撤单，终态前继续阻塞（防双单）
    if age >= float(PENDING_TIMEOUT_SEC):
        if not cancel_req:
            if od is not None:
                _try_cancel_order(od, C)
            else:
                print("HongliT pending timeout, order not visible yet; wait for cancel/orphan")
            pend["cancel_requested"] = True
            pend["cancel_at"] = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
            A.pending = pend
            _save_state()
            return True
        # 已请求过撤单
        cancel_at = _parse_opened_at(pend.get("cancel_at"))
        cancel_age = 0.0
        if cancel_at is not None and now is not None:
            cancel_age = (now - cancel_at).total_seconds()
        if od is None and cancel_age >= float(PENDING_ORPHAN_SEC):
            # 始终未见委托 - 多半提交失败；可安全解锁
            print("HongliT pending orphan clear (no order after cancel wait)")
            _clear_pending("orphan")
            return False
        # 仍存活或结算中 - 不清空、不重试
        return True

    return True


def _new_remark(tag, side, vol):
    # 唯一 remark，避免成交/委托匹配到旧单
    ts = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return "HongliT %s %s %s x%d %s" % (side, tag, A.stock, int(vol), ts)


def _order_buy(C, vol, remark_tag, intent, price_hint, opened_at, now):
    """提交买入。DRY_RUN 即时；回测 passorder+即时；实盘 pending 至成交。"""
    # 回测保护: 影子持仓仍在时不再新开腿
    if getattr(A, "is_backtest", False) and intent == "RA" and _bt_held_vol() >= 100:
        print("HongliT R-A skip bt_held=", _bt_held_vol())
        return False
    msg = _new_remark(remark_tag, "BUY", vol)
    print(("[DRY] " if DRY_RUN else "") + msg)
    if DRY_RUN:
        _apply_buy_fill(intent, vol, price_hint, opened_at)
        return True
    try:
        passorder(A.buy_code, 1101, A.acct, A.stock, 14, -1, vol, "HongliT_v219", 1, msg, C)
    except Exception as e:
        print("HongliT passorder BUY fail", e)
        return False
    # 回测: 仍 passorder 以便 QMT 出成交日志；状态立即落地
    if getattr(A, "is_backtest", False):
        _apply_buy_fill(intent, vol, price_hint, opened_at)
        return True
    A.pending = {
        "remark": msg,
        "side": "buy",
        "intent": intent,
        "vol": int(vol),
        "stock": A.stock,
        "price_hint": float(price_hint),
        "opened_at": opened_at,
        "submitted_at": (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S"),
        "cancel_requested": False,
    }
    _save_state()
    return True


def _order_sell(C, vol, remark_tag, intent, last_hint, now):
    """提交卖出。DRY_RUN 即时；回测 passorder+即时；实盘 pending 至成交。

    T+1（回测+实盘）: 下单量不超过可卖；跳过时绝不清浮仓。
    实盘可卖 = m_nCanUseVolume；回测可卖 = bt_held - bt_locked。
    """
    want = int(vol)
    if getattr(A, "is_backtest", False):
        if now is not None:
            _bt_roll_t1(now.strftime("%Y%m%d"))
        want = max(want, _bt_held_vol(), _sell_float_vol())
        avail = _bt_available_vol()
        vol = min(want, avail)
        if vol < 100:
            print(
                "HongliT sell skip T+1 avail=",
                avail,
                "held=",
                _bt_held_vol(),
                "locked=",
                _bt_locked_vol(),
                "want=",
                want,
                "tag=",
                remark_tag,
            )
            return False
    else:
        # 实盘 / DRY_RUN: 一律用 _max_sell_vol 封顶（可卖或空跑日历 T+1）
        avail = _max_sell_vol()
        vol = min(want, avail)
        if vol < 100:
            if DRY_RUN:
                print(
                    "HongliT [DRY] sell skip T+1 want=",
                    want,
                    "sellable=",
                    avail,
                    "tag=",
                    remark_tag,
                )
            else:
                broker_vol, can, _cost = _broker_position(A.stock)
                print(
                    "HongliT sell skip T+1/live can_use=",
                    can,
                    "broker=",
                    broker_vol,
                    "float=",
                    _sell_float_vol(),
                    "want=",
                    want,
                    "tag=",
                    remark_tag,
                )
            return False
    msg = _new_remark(remark_tag, "SELL", vol)
    print(("[DRY] " if DRY_RUN else "") + msg)
    if DRY_RUN:
        # 空跑仅按 T+1 上限清算「卖出」部分
        if vol >= _sell_float_vol():
            _clear_float_after_sell(now, intent or remark_tag, last=last_hint)
        else:
            remain = max(0, _sell_float_vol() - vol)
            _shrink_float_to_vol(remain)
            if remain < 100:
                _clear_float_after_sell(now, (intent or remark_tag) + "/partial", last=last_hint)
            else:
                _save_state()
        return True
    try:
        passorder(A.sell_code, 1101, A.acct, A.stock, 14, -1, vol, "HongliT_v219", 1, msg, C)
    except Exception as e:
        print("HongliT passorder SELL fail", e)
        return False
    # 回测: 仅按实际可卖量落地（含 T+1）；0 成交绝不清仓
    if getattr(A, "is_backtest", False):
        held_before = _bt_held_vol()
        if vol >= held_before:
            _clear_float_after_sell(now, intent or remark_tag, last=last_hint)
        else:
            remain = held_before - vol
            print(
                "HongliT T+1 partial sell",
                vol,
                "remain=",
                remain,
                "locked=",
                _bt_locked_vol(),
            )
            _shrink_float_to_vol(remain)
            _bt_held_set(remain)
            if remain < 100:
                _clear_float_after_sell(now, (intent or remark_tag) + "/partial", last=last_hint)
            else:
                _save_state()
        return True
    # 实盘: pending 至券商成交；此处不清浮仓（T+1 跳过不得抹状态）
    A.pending = {
        "remark": msg,
        "side": "sell",
        "intent": intent or remark_tag,
        "vol": int(vol),
        "stock": A.stock,
        "last_hint": last_hint,
        "submitted_at": (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S"),
        "cancel_requested": False,
    }
    _save_state()
    return True
