# === qmt_common/single/orders.py ===
# 作用: 单仓买卖委托与成交落地
# 主要符号: _order_buy, _order_sell, _apply_buy_fill, _apply_sell_fill
# 钩子实现: _pending_on_buy_fill / _pending_on_sell_fill
# 预算: TRADE_BUDGET；可选 TRADE_BUDGET_BY_STOCK[A.stock]；可选 CASH_RATIO
# add=True: 已有仓上加仓；SCALE_LOTS 时记独立笔，否则均价合并（默认仍一票一仓）
# 实盘尾盘成交窗：限价 prType=11，买挂卖一、卖挂买一；不开涨跌停、不按收盘集合竞价价吃单。
# 开盘窗仍用 14/-1 市价。回测路径不变。
def _try_lots_buy(px, add, vol, opened_at):
    if not bool(globals().get("SCALE_LOTS")):
        return
    fn = globals().get("_lots_on_buy_fill")
    if callable(fn):
        fn(px, add=add, vol=vol, opened_at=opened_at)


def _trade_budget_cap():
    """单笔预算上限：优先 TRADE_BUDGET_BY_STOCK[A.stock]，否则 TRADE_BUDGET。"""
    stock = str(getattr(A, "stock", "") or "").strip()
    by_stock = globals().get("TRADE_BUDGET_BY_STOCK") or {}
    if stock and isinstance(by_stock, dict) and stock in by_stock:
        try:
            return float(by_stock[stock] or 0)
        except Exception:
            pass
    return float(globals().get("TRADE_BUDGET") or 0)


def _buy_budget(cash):
    budget = _trade_budget_cap()
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return budget if budget > 0 else 0.0
    ratio = float(globals().get("CASH_RATIO") or 0)
    if cash is None or cash <= 0:
        return budget
    if ratio > 0:
        by_ratio = float(cash) * ratio
        return min(budget, by_ratio) if budget > 0 else by_ratio
    return budget


def _apply_buy_fill(vol, price, opened_at, **extra):
    vol = int(vol)
    price = float(price) if price and price > 0 else 0.0
    if vol < 100:
        return
    add = bool(extra.pop("add", False))
    ot = str(opened_at or "").strip()
    if not ot:
        ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    if add and _has_position():
        old_s = _pos_shares()
        old_px = _pos_cost_price()
        new_s = old_s + vol
        new_px = (old_s * old_px + vol * price) / float(new_s)
        pos = dict(A.position)
        pos["shares"] = int(new_s)
        pos["price"] = float(new_px)
        pos["cost"] = round(new_s * new_px, 2)
        pos["lots"] = int(pos.get("lots", 1) or 1) + 1
        A.position = pos
        A.acted.add("BUY")
        buy_day = ot[:8] if len(ot) >= 8 else None
        _bt_held_add(vol, buy_day=buy_day)
        _try_lots_buy(price, True, vol, ot)
        _save_state()
        print(
            _strategy_tag(),
            "BUY add filled",
            {
                "add_shares": vol,
                "price": price,
                "lots": pos["lots"],
                "total": new_s,
                "avg": new_px,
            },
        )
        _event_log(
            "buy_add_filled",
            add_shares=vol,
            price=price,
            lots=pos["lots"],
            total=new_s,
            avg=new_px,
        )
        return
    pos = {
        "shares": vol,
        "price": price,
        "cost": round(vol * price, 2),
        "opened_at": ot,
        "lots": 1,
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
    _try_lots_buy(price, False, vol, ot)
    _save_state()
    print(_strategy_tag(), "BUY filled", A.position)
    _event_log("buy_filled", position=A.position, vol=vol, price=price, opened_at=ot)


def _apply_sell_fill(now, reason, last_hint, filled_vol, mark_half=False, lot_ids=None):
    """卖出成交后清空或缩减持仓. 仅按实际成交量改状态.
    SCALE_LOTS + lot_ids: 按笔减仓，不因 95% 误清剩余笔。"""
    want = _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol())
    filled_vol = int(filled_vol)
    if filled_vol < 100:
        return
    partial_lots = False
    if bool(globals().get("SCALE_LOTS")) and lot_ids:
        fn = globals().get("_exit_is_partial")
        if callable(fn):
            partial_lots = bool(fn(lot_ids))
    if (not partial_lots) and (
        filled_vol >= max(100, int(want * 0.95)) or filled_vol >= want
    ):
        _clear_after_sell(now, reason, last=last_hint)
        if mark_half:
            A.acted.add("HALF")
            _save_state()
        return
    remain = max(0, want - filled_vol)
    print(_strategy_tag(), "partial sell fill", filled_vol, "remain~", remain)
    _event_log(
        "partial_sell_fill",
        reason=reason,
        filled_vol=filled_vol,
        remain=remain,
        last=last_hint,
        lot_ids=lot_ids,
    )
    _bt_held_set(remain)
    lots_fn = globals().get("_lots_on_sell_fill")
    if bool(globals().get("SCALE_LOTS")) and callable(lots_fn):
        lots_fn(lot_ids, filled_vol)
    elif A.position:
        A.position["shares"] = remain
    if remain < 100 or not _has_position():
        _clear_after_sell(now, str(reason) + "/partial", last=last_hint)
    else:
        if mark_half:
            A.acted.add("HALF")
        acted = getattr(A, "acted", None)
        if isinstance(acted, set):
            acted.discard("SELL")
        _save_state()


def _pending_on_buy_fill(pend, vol, px):
    extra = pend.get("extra_pos") if isinstance(pend.get("extra_pos"), dict) else {}
    _apply_buy_fill(vol, px, pend.get("opened_at") or pend.get("submitted_at"), **extra)


def _pending_on_sell_fill(pend, now, vol, px):
    intent = str(pend.get("intent", "") or "")
    last_hint = pend.get("last_hint")
    if last_hint is None:
        last_hint = px
    mark_half = bool(pend.get("mark_half"))
    lot_ids = pend.get("lot_ids")
    _apply_sell_fill(now, intent, last_hint, vol, mark_half=mark_half, lot_ids=lot_ids)


def _in_live_close_exec(now):
    """是否处于实盘尾盘成交窗（PENDING_EXEC_*）。"""
    if getattr(A, "is_backtest", False):
        return False
    now_s = (now or datetime.datetime.now()).strftime("%H%M%S")
    fn = globals().get("_in_close_exec_window")
    if callable(fn):
        try:
            return bool(fn(now_s))
        except Exception:
            pass
    start = str(globals().get("PENDING_EXEC_START") or "")
    end = str(globals().get("PENDING_EXEC_END") or "")
    if start and end:
        return start <= now_s < end
    return False


def _round_order_px(stock, px):
    px = float(px or 0)
    if px <= 0:
        return 0.0
    code = str(stock or "").split(".")[0]
    if len(code) == 6 and code[:1] in ("1", "5"):
        return round(px + 1e-12, 3)
    return round(px + 1e-12, 2)


def _tick_field(obj, names):
    if obj is None:
        return 0.0
    for name in names:
        if isinstance(obj, dict):
            raw = obj.get(name)
        else:
            raw = getattr(obj, name, None)
        if raw is None or raw == "":
            continue
        try:
            v = float(raw)
        except Exception:
            continue
        if v > 0:
            return v
    return 0.0


def _seq_first_px(val):
    if val is None or val == "":
        return 0.0
    if isinstance(val, (list, tuple)):
        if not val:
            return 0.0
        try:
            return float(val[0] or 0)
        except Exception:
            return 0.0
    try:
        return float(val)
    except Exception:
        return 0.0


def _get_stock_tick(C, stock):
    ticks = None
    if C is not None:
        for meth in ("get_full_tick", "get_tick"):
            fn = getattr(C, meth, None)
            if not callable(fn):
                continue
            try:
                ticks = fn([stock])
            except Exception:
                ticks = None
            if ticks:
                break
    if ticks is None:
        gfn = globals().get("get_full_tick")
        if callable(gfn):
            try:
                ticks = gfn([stock])
            except Exception:
                ticks = None
    if isinstance(ticks, dict):
        t = ticks.get(stock)
        if t is None:
            t = ticks.get(str(stock).split(".")[0])
        return t
    return ticks


def _level1_px(t, array_names, scalar_names):
    if t is None:
        return 0.0
    for name in array_names:
        if isinstance(t, dict):
            raw = t.get(name)
        else:
            raw = getattr(t, name, None)
        px = _seq_first_px(raw)
        if px > 0:
            return px
    return _tick_field(t, scalar_names)


def _live_opponent_px(C, side, fallback):
    """买=卖一，卖=买一；取不到则回落 last。"""
    t = _get_stock_tick(C, getattr(A, "stock", ""))
    if str(side) == "buy":
        raw = _level1_px(
            t,
            ("askPrice", "askPrices", "ask", "asks"),
            ("askPrice1", "ask1", "AskPrice1", "askPr1", "m_dAskPrice"),
        )
        kind = "ask1"
    else:
        raw = _level1_px(
            t,
            ("bidPrice", "bidPrices", "bid", "bids"),
            ("bidPrice1", "bid1", "BidPrice1", "bidPr1", "m_dBidPrice"),
        )
        kind = "bid1"
    if raw <= 0:
        raw = float(fallback or 0)
        kind = "last"
    px = _round_order_px(getattr(A, "stock", ""), raw)
    return px, kind


def _passorder_live(C, side, vol, last_px, msg, now):
    """实盘报单。尾盘窗限价挂卖一/买一；其余仍市价。"""
    vol = int(vol)
    last_px = float(last_px or 0)
    if _in_live_close_exec(now):
        px, kind = _live_opponent_px(C, side, last_px)
        if px > 0:
            code = A.buy_code if str(side) == "buy" else A.sell_code
            print(
                _strategy_tag(),
                "passorder quote-limit",
                side,
                kind,
                "pr=11",
                "px=",
                px,
                "last=",
                last_px,
                "vol=",
                vol,
            )
            _event_log(
                "passorder_quote_limit",
                side=side,
                kind=kind,
                pr_type=11,
                px=px,
                last=last_px,
                vol=vol,
            )
            passorder(code, 1101, A.acct, A.stock, 11, px, vol, _strategy_tag(), 2, msg, C)
            return px
    code = A.buy_code if str(side) == "buy" else A.sell_code
    qt = 1
    force_qt = getattr(A, "_force_quicktrade", None)
    if force_qt is not None:
        try:
            qt = int(force_qt)
        except Exception:
            qt = 1
    passorder(code, 1101, A.acct, A.stock, 14, -1, vol, _strategy_tag(), qt, msg, C)
    return last_px


def _order_buy(C, price, now, budget=None, add=False, **extra_pos):
    """提交买入. DRY 即时; 回测 passorder+即时; 实盘 pending 至成交.
    add=True 允许在已有仓上加仓；SCALE_LOTS 时每笔独立，否则均价合并。默认仍一票一仓。"""
    if getattr(A, "pending", None):
        print(_strategy_tag(), "buy skip: pending active")
        _event_log("buy_skip", reason="pending_active")
        return False
    holding_now = _has_position() or (
        getattr(A, "is_backtest", False) and _bt_held_vol() >= 100
    )
    if holding_now and not add:
        print(_strategy_tag(), "buy skip: already holding")
        _event_log("buy_skip", reason="already_holding")
        return False
    if add and not holding_now:
        add = False
    if (not add) and ("BUY" in getattr(A, "acted", set())):
        return False

    if budget is None:
        cash = _available_cash()
        budget = _buy_budget(cash)
    vol = _lot(price, budget)
    if vol < 100:
        print(_strategy_tag(), "buy skip lot", "price=", price, "budget=", budget)
        _event_log("buy_skip", reason="lot", price=price, budget=budget)
        return False
    cash = _available_cash()
    freeze_px = float(price or 0)
    if (not getattr(A, "is_backtest", False)) and (not DRY_RUN) and _in_live_close_exec(now):
        prot, _kind = _live_opponent_px(C, "buy", price)
        if prot > freeze_px:
            freeze_px = prot
    if cash is not None and freeze_px > 0 and cash < freeze_px * vol:
        vol = _lot(freeze_px, cash)
        if vol < 100:
            print(_strategy_tag(), "buy skip cash", cash)
            _event_log("buy_skip", reason="cash", cash=cash, price=price, freeze_px=freeze_px)
            return False

    extra_pos = dict(extra_pos or {})
    if add:
        extra_pos["add"] = True
    ot = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    msg = _new_remark("BUY", "ADD" if add else "BUY", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@", price)
    if DRY_RUN:
        _apply_buy_fill(vol, price, ot, **extra_pos)
        return True
    try:
        _passorder_live(C, "buy", vol, price, msg, now)
    except Exception as e:
        print(_strategy_tag(), "passorder BUY fail", e)
        _event_log("passorder_fail", side="buy", error=str(e), vol=vol, price=price)
        return False
    if getattr(A, "is_backtest", False):
        _apply_buy_fill(vol, price, ot, **extra_pos)
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
        "extra_pos": extra_pos or {},
    }
    _save_state()
    print(_strategy_tag(), "BUY submitted", vol, msg)
    _event_log("buy_submitted", vol=vol, price=price, remark=msg, dry_run=False)
    return True


def _order_sell(C, reason, price, now, want_vol=None, mark_half=False, lot_ids=None):
    """提交卖出. T+1: 下单量不超过可卖; skip 绝不清仓.
    lot_ids: SCALE_LOTS 时指定要平的笔；部分笔自动 mark_half。"""
    if getattr(A, "pending", None):
        print(_strategy_tag(), "sell skip: pending active")
        _event_log("sell_skip", reason="pending_active", sell_reason=reason)
        return False
    if not _has_position() and not (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100):
        return False
    if lot_ids:
        fn = globals().get("_exit_is_partial")
        if callable(fn) and fn(lot_ids):
            mark_half = True
        if want_vol is None:
            wv = globals().get("_lots_want_vol")
            if callable(wv):
                want_vol = wv(lot_ids)
    if (not mark_half) and ("SELL" in getattr(A, "acted", set())):
        return False

    want = int(want_vol) if want_vol is not None else _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol()) if want_vol is None else want
    if want < 100:
        return False

    avail = _max_sell_vol(now)
    vol = int(min(want, avail) // 100) * 100
    if vol < 100:
        if getattr(A, "is_backtest", False):
            print(
                _strategy_tag(),
                "sell skip T+1",
                reason,
                "avail=",
                avail,
                "held=",
                _bt_held_vol(),
                "locked=",
                _bt_locked_vol(),
                "want=",
                want,
            )
            _event_log(
                "sell_skip",
                reason="t1_bt",
                sell_reason=reason,
                avail=avail,
                held=_bt_held_vol(),
                locked=_bt_locked_vol(),
                want=want,
            )
        elif DRY_RUN:
            print(
                _strategy_tag(),
                "[DRY] sell skip T+1",
                reason,
                "want=",
                want,
                "sellable=",
                avail,
            )
            _event_log(
                "sell_skip",
                reason="t1_dry",
                sell_reason=reason,
                want=want,
                sellable=avail,
            )
        else:
            broker_vol, can, _cost = _broker_position(A.stock)
            print(
                _strategy_tag(),
                "sell skip T+1/live",
                reason,
                "can_use=",
                can,
                "broker=",
                broker_vol,
                "want=",
                want,
            )
            _event_log(
                "sell_skip",
                reason="t1_live",
                sell_reason=reason,
                can_use=can,
                broker=broker_vol,
                want=want,
            )
        return False

    msg = _new_remark(reason or "SELL", "SELL", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@", price)
    if DRY_RUN:
        _apply_sell_fill(now, reason, price, vol, mark_half=mark_half, lot_ids=lot_ids)
        return True
    try:
        _passorder_live(C, "sell", vol, price, msg, now)
    except Exception as e:
        print(_strategy_tag(), "passorder SELL fail", e)
        _event_log(
            "passorder_fail",
            side="sell",
            error=str(e),
            vol=vol,
            price=price,
            sell_reason=reason,
        )
        return False
    if getattr(A, "is_backtest", False):
        _apply_sell_fill(now, reason, price, vol, mark_half=mark_half, lot_ids=lot_ids)
        return True
    A.pending = {
        "remark": msg,
        "side": "sell",
        "intent": reason or "SELL",
        "vol": int(vol),
        "stock": A.stock,
        "price_hint": float(price),
        "last_hint": price,
        "submitted_at": (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S"),
        "cancel_requested": False,
        "mark_half": bool(mark_half),
        "lot_ids": list(lot_ids) if lot_ids else None,
    }
    _save_state()
    print(_strategy_tag(), "SELL submitted", vol, reason, msg)
    _event_log(
        "sell_submitted",
        vol=vol,
        price=price,
        sell_reason=reason,
        remark=msg,
        dry_run=False,
    )
    return True
