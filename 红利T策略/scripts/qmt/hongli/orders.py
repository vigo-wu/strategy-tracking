# === hongli/orders.py ===
# 作用: 红利T 双浮仓腿买卖与成交落地
# 前置: common/orders_pending；实现 _pending_on_* 钩子
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
        print(_strategy_tag(), "R-A filled", A.float_a)
    elif intent == "RB":
        A.float_b = leg
        A.acted.add("RB")
        print(_strategy_tag(), "R-B filled", A.float_b)
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
        print(_strategy_tag(), "partial sell fill", filled_vol, "remain~", remain)
        _shrink_float_to_vol(remain)
        _bt_held_set(remain)
        if remain < 100:
            _clear_float_after_sell(now, tag + "/partial", last=last_hint)
        else:
            _save_state()


def _pending_on_buy_fill(pend, vol, px):
    _apply_buy_fill(pend.get("intent"), vol, px, pend.get("opened_at"))


def _pending_on_sell_fill(pend, now, vol, px):
    _apply_sell_fill(now, pend.get("intent"), pend.get("last_hint"), vol)


def _order_buy(C, vol, remark_tag, intent, price_hint, opened_at, now):
    """提交买入。DRY_RUN 即时；回测 passorder+即时；实盘 pending 至成交。"""
    if getattr(A, "is_backtest", False) and intent == "RA" and _bt_held_vol() >= 100:
        print(_strategy_tag(), "R-A skip bt_held=", _bt_held_vol())
        return False
    msg = _new_remark(remark_tag, "BUY", vol)
    print(("[DRY] " if DRY_RUN else "") + msg)
    if DRY_RUN:
        _apply_buy_fill(intent, vol, price_hint, opened_at)
        return True
    try:
        passorder(A.buy_code, 1101, A.acct, A.stock, 14, -1, vol, "HongliT_v219", 1, msg, C)
    except Exception as e:
        print(_strategy_tag(), "passorder BUY fail", e)
        return False
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
                _strategy_tag(),
                "sell skip T+1 avail=",
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
        avail = _max_sell_vol()
        vol = min(want, avail)
        if vol < 100:
            if DRY_RUN:
                print(
                    _strategy_tag(),
                    "[DRY] sell skip T+1 want=",
                    want,
                    "sellable=",
                    avail,
                    "tag=",
                    remark_tag,
                )
            else:
                broker_vol, can, _cost = _broker_position(A.stock)
                print(
                    _strategy_tag(),
                    "sell skip T+1/live can_use=",
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
        print(_strategy_tag(), "passorder SELL fail", e)
        return False
    if getattr(A, "is_backtest", False):
        held_before = _bt_held_vol()
        if vol >= held_before:
            _clear_float_after_sell(now, intent or remark_tag, last=last_hint)
        else:
            remain = held_before - vol
            print(
                _strategy_tag(),
                "T+1 partial sell",
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
