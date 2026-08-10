# === cbauct/strategy.py ===
# model.md v3.0:
#   Mode A: 早盘 130 抢筹 → 14:57 后封板卖 157.30（T+0）
#   Mode B: 早盘失败 → 深市 143 埋单/升级顶格；沪市 143 阶梯追至 157.30
#   Day2: 高开锁利 / 1.5% 移动止盈 / 低开止损


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


def _entry_mode_of(pos=None):
    pos = pos if pos is not None else getattr(A, "position", None)
    if isinstance(pos, dict):
        m = str(pos.get("entry_mode", "") or "")
        if m:
            return m
        intent = str(pos.get("intent", "") or "")
        if intent in ("SZ_AM", "SH_AM"):
            return "A"
        if intent in ("SZ_PREPLACE", "SZ_CLOSE", "SH_OPEN", "SH_CHASE"):
            return "B"
    m = str(getattr(A, "entry_mode", "") or "")
    return m


def _is_mode_a_pos():
    return _entry_mode_of() == "A"


def _is_mode_b_pos():
    return _entry_mode_of() == "B"


def _pos_opened_day():
    pos = getattr(A, "position", None)
    if not isinstance(pos, dict):
        return ""
    ot = str(pos.get("opened_at", "") or "")
    return ot[:8] if len(ot) >= 8 else ""


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
    entry_mode = str(extra.get("entry_mode") or "")
    if not entry_mode:
        if intent in ("SZ_AM", "SH_AM"):
            entry_mode = "A"
        elif intent in ("SZ_PREPLACE", "SZ_CLOSE", "SH_OPEN", "SH_CHASE"):
            entry_mode = "B"
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
    # 可转债 T+0：回测不锁仓
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
        entry_mode=entry_mode,
    )


def _apply_cb_sell_fill(now, reason, last_hint, filled_vol, mark_half=False):
    lot = int(globals().get("LOT_SIZE") or 10)
    want = _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol())
    filled_vol = int(filled_vol)
    if filled_vol < lot:
        return
    if filled_vol >= max(lot, int(want * 0.95)) or filled_vol >= want:
        _clear_after_sell(now, reason, last=last_hint)
        A.entry_mode = ""
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
    )
    if A.position:
        A.position["shares"] = remain
    _bt_held_set(remain)
    if remain < lot:
        _clear_after_sell(now, str(reason) + "/partial", last=last_hint)
        A.entry_mode = ""
    else:
        if mark_half:
            A.acted.add("HALF")
        _save_state()


def _pending_on_buy_fill(pend, vol, px):
    extra = pend.get("extra_pos") if isinstance(pend.get("extra_pos"), dict) else {}
    _apply_cb_buy_fill(vol, px, pend.get("opened_at") or pend.get("submitted_at"), **extra)


def _pending_on_sell_fill(pend, now, vol, px):
    intent = str(pend.get("intent", "") or "")
    last_hint = pend.get("last_hint")
    if last_hint is None:
        last_hint = px
    mark_half = bool(pend.get("mark_half"))
    _apply_cb_sell_fill(now, intent, last_hint, vol, mark_half=mark_half)


def _max_sell_vol(now=None):
    """可转债 T+0：当日买入亦可卖（回测/DRY 不套用股票 T+1）。"""
    want = _pos_shares()
    lot = int(globals().get("LOT_SIZE") or 10)
    if getattr(A, "is_backtest", False):
        held = max(want, _bt_held_vol())
        return max(0, held)
    if want < lot:
        return 0
    if DRY_RUN:
        return want
    broker_vol, can, _cost = _broker_position(A.stock)
    return max(0, min(want, int(can), int(broker_vol)))


def _order_buy_limit(C, price, now, budget=None, intent="BUY", entry_mode=None):
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

    if not entry_mode:
        if intent in ("SZ_AM", "SH_AM"):
            entry_mode = "A"
        elif intent in ("SZ_PREPLACE", "SZ_CLOSE", "SH_OPEN", "SH_CHASE"):
            entry_mode = "B"
    extra_pos = {"intent": intent}
    if entry_mode:
        extra_pos["entry_mode"] = entry_mode

    ot = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    msg = _new_remark(intent, "BUY", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@limit", price, intent)
    exempt = set(str(x) for x in (globals().get("PENDING_TIMEOUT_EXEMPT_INTENTS") or ()))
    no_timeout = str(intent) in exempt
    if DRY_RUN:
        # VERIFY 开盘竞价：130 不会触达 DRY_RUN_FILL_ON_LIMIT，须模拟抢筹成交才能验 ModeA 卖出
        fill_now = bool(globals().get("DRY_RUN_FILL_IMMEDIATE", False))
        if (not fill_now) and intent in ("SZ_AM", "SH_AM") and _verify_any_day():
            fill_now = True
        if fill_now:
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
            entry_mode=entry_mode,
        )
        if (
            bool(globals().get("DRY_RUN_FILL_ON_LIMIT", True))
            and price + 1e-9 >= _limit_up()
        ):
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
            1,
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
        entry_mode=entry_mode,
    )
    return True


def _order_sell_limit(C, reason, price, now, want_vol=None):
    """限价卖出 prType=11；可转债 T+0 + LOT_SIZE。"""
    lot = int(globals().get("LOT_SIZE") or 10)
    price = _px_round(price)
    if price <= 0:
        return False
    if getattr(A, "pending", None):
        print(_strategy_tag(), "sell skip: pending active")
        _event_log("sell_skip", reason="pending_active", sell_reason=reason)
        return False
    if not _has_position() and not (
        getattr(A, "is_backtest", False) and _bt_held_vol() > 0
    ):
        return False
    if "SELL" in getattr(A, "acted", set()):
        return False

    want = int(want_vol) if want_vol is not None else _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol()) if want_vol is None else want
    if want < lot:
        return False

    avail = _max_sell_vol(now)
    vol = int(min(want, avail) // lot) * lot
    if vol < lot:
        print(
            _strategy_tag(),
            "sell skip avail",
            reason,
            "avail=",
            avail,
            "want=",
            want,
        )
        _event_log(
            "sell_skip",
            reason="avail",
            sell_reason=reason,
            avail=avail,
            want=want,
        )
        return False

    msg = _new_remark(reason or "SELL", "SELL", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@limit", price, reason)
    exempt = set(str(x) for x in (globals().get("PENDING_TIMEOUT_EXEMPT_INTENTS") or ()))
    no_timeout = str(reason) in exempt
    if DRY_RUN:
        if bool(globals().get("DRY_RUN_FILL_IMMEDIATE", False)):
            _apply_cb_sell_fill(now, reason, price, vol)
            return True
        A.pending = {
            "remark": msg,
            "side": "sell",
            "intent": reason or "SELL",
            "vol": int(vol),
            "stock": A.stock,
            "price_hint": float(price),
            "last_hint": float(price),
            "submitted_at": (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S"),
            "cancel_requested": False,
            "no_timeout": no_timeout,
            "dry_keep": True,
            "mark_half": False,
        }
        A.sh_last_order_px = float(price)
        _save_state()
        print(_strategy_tag(), "DRY sell pending", vol, "@", price, reason)
        _event_log(
            "sell_submitted",
            vol=vol,
            price=price,
            sell_reason=reason,
            dry_run=True,
            dry_keep=True,
        )
        if (
            bool(globals().get("DRY_RUN_FILL_ON_LIMIT", True))
            and price + 1e-9 >= _limit_up()
        ):
            # 卖出挂顶格：DRY 下视为对手盘吃掉
            _apply_cb_sell_fill(now, reason, price, vol)
            A.pending = None
            _save_state()
            print(_strategy_tag(), "DRY sell fill on limit", price)
        return True
    try:
        passorder(
            A.sell_code,
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
        print(_strategy_tag(), "passorder SELL limit fail", e)
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
        _apply_cb_sell_fill(now, reason, price, vol)
        return True
    A.pending = {
        "remark": msg,
        "side": "sell",
        "intent": reason or "SELL",
        "vol": int(vol),
        "stock": A.stock,
        "price_hint": float(price),
        "last_hint": float(price),
        "submitted_at": (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S"),
        "cancel_requested": False,
        "no_timeout": no_timeout,
        "mark_half": False,
    }
    A.sh_last_order_px = float(price)
    _save_state()
    print(_strategy_tag(), "SELL submitted limit", vol, "@", price, reason, msg)
    _event_log(
        "sell_submitted",
        vol=vol,
        price=price,
        sell_reason=reason,
        remark=msg,
        dry_run=False,
    )
    return True


def _order_sell_mkt(C, reason, now, want_vol=None):
    """市价/对手方卖出（次日止盈止损）；prType=14。"""
    lot = int(globals().get("LOT_SIZE") or 10)
    if getattr(A, "pending", None):
        print(_strategy_tag(), "sell skip: pending active")
        _event_log("sell_skip", reason="pending_active", sell_reason=reason)
        return False
    if not _has_position() and not (
        getattr(A, "is_backtest", False) and _bt_held_vol() > 0
    ):
        return False
    if "SELL" in getattr(A, "acted", set()):
        return False

    want = int(want_vol) if want_vol is not None else _pos_shares()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol()) if want_vol is None else want
    if want < lot:
        return False
    avail = _max_sell_vol(now)
    vol = int(min(want, avail) // lot) * lot
    if vol < lot:
        print(_strategy_tag(), "sell skip avail", reason, "avail=", avail)
        _event_log("sell_skip", reason="avail", sell_reason=reason, avail=avail)
        return False

    msg = _new_remark(reason or "SELL", "SELL", vol)
    print(("[DRY] " if DRY_RUN else "") + msg, "@mkt", reason)
    if DRY_RUN:
        _apply_cb_sell_fill(now, reason, 0.0, vol)
        return True
    try:
        passorder(
            A.sell_code,
            1101,
            A.acct,
            A.stock,
            14,
            -1,
            vol,
            _strategy_tag(),
            1,
            msg,
            C,
        )
    except Exception as e:
        print(_strategy_tag(), "passorder SELL mkt fail", e)
        _event_log("passorder_fail", side="sell", error=str(e), vol=vol, sell_reason=reason)
        return False
    if getattr(A, "is_backtest", False):
        _apply_cb_sell_fill(now, reason, 0.0, vol)
        return True
    A.pending = {
        "remark": msg,
        "side": "sell",
        "intent": reason or "SELL",
        "vol": int(vol),
        "stock": A.stock,
        "price_hint": 0.0,
        "last_hint": 0.0,
        "submitted_at": (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S"),
        "cancel_requested": False,
        "mark_half": False,
    }
    _save_state()
    print(_strategy_tag(), "SELL submitted mkt", vol, reason, msg)
    _event_log("sell_submitted", vol=vol, sell_reason=reason, remark=msg, dry_run=False)
    return True


def _request_pending_cancel(C, now, reason):
    """主动撤当前 pending；未见委托时不打 cancel_requested，避免永久卡住。"""
    pend = getattr(A, "pending", None)
    if not isinstance(pend, dict):
        return False
    if pend.get("cancel_requested"):
        return True
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
            day = ot[:8] if len(ot) >= 8 else datetime.datetime.now().strftime("%Y%m%d")
            A.buy_done_day = day
            _save_state()
            print(_strategy_tag(), "reconcile sync from broker vol=", vol, "cost=", cost)
            _event_log("reconcile_sync", vol=vol, cost=cost)
        return
    if (not found or vol <= 0) and _has_position():
        print(
            _strategy_tag(),
            "reconcile clear shadow (broker flat) was=",
            A.position,
        )
        _event_log("reconcile_clear", was=A.position, broker_vol=vol, found=found)
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
    """当前秒内毫秒 0–999。"""
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
    """上市日前夜：LISTING_DATE_MAP 命中明日，或日K推断明日为首日。

    VERIFY 模式不把「每天晚上」当成前夜（否则任意日晚间乱挂 130）；
    仅当显式 LISTING_DATE_MAP 指向明日时仍允许验隔夜委托。
    """
    if now is None:
        return False
    try:
        tomorrow = (now + datetime.timedelta(days=1)).strftime("%Y%m%d")
    except Exception:
        return False
    mapped = _listing_date_str()
    if mapped:
        return mapped == tomorrow
    if _verify_any_day():
        return False
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
    """模式A：深市隔夜/早盘挂 130；沪市卡点挂 130。

    VERIFY_AUCTION_ANY_DAY：任意交易日可走开盘竞价窗（沪市放宽至集合竞价时段、跳过毫秒卡点）。
    """
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
    verify = _verify_any_day()

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
        print(
            "%s SZ_AM buy @%.3f window listing/eve now=%s verify=%s"
            % (STRATEGY_NAME, px, now_s, verify)
        )
        _event_log("sz_am_buy", price=px, now_s=now_s, verify=verify)
        if _order_buy_limit(C, px, now, intent="SZ_AM", entry_mode="A"):
            A.am_buy_day = day
            A.buy_done_day = day
            _save_state()
            return True
        return False

    if mkt == "SH":
        if not _is_listing_day(C, day):
            return False
        if verify:
            am_s = str(globals().get("SH_AM_BUY_START_VERIFY") or "091500")
            am_e = str(globals().get("SH_AM_BUY_END_VERIFY") or "092459")
        else:
            am_s = str(globals().get("SH_AM_BUY_START") or "092459")
            am_e = str(globals().get("SH_AM_BUY_END") or "092459")
        if not _in_window(now_s, am_s, am_e):
            return False
        # 首日实盘毫秒卡点；回测 / VERIFY 联调跳过（1m 分辨率够不着 100ms）
        if (not bt) and (not verify):
            ms0 = int(globals().get("SH_AM_BUY_MS_START") or 850)
            ms1 = int(globals().get("SH_AM_BUY_MS_END") or 950)
            ms = _now_ms_of_second(now)
            if ms < ms0 or ms > ms1:
                return False
        print(
            "%s SH_AM buy @%.3f card-point now=%s ms=%s verify=%s"
            % (STRATEGY_NAME, px, now_s, _now_ms_of_second(now), verify)
        )
        _event_log(
            "sh_am_buy",
            price=px,
            now_s=now_s,
            ms=_now_ms_of_second(now),
            verify=verify,
        )
        if _order_buy_limit(C, px, now, intent="SH_AM", entry_mode="A"):
            A.am_buy_day = day
            A.buy_done_day = day
            _save_state()
            return True
        return False

    return False


def _cleanup_am_pending(C, now, now_s):
    """早盘未成：过 09:25 后撤单，腾出 Mode B。"""
    after = str(globals().get("AM_CANCEL_AFTER") or "092500")
    if str(now_s) < after:
        return False
    pend = getattr(A, "pending", None)
    if not isinstance(pend, dict):
        return False
    intent = str(pend.get("intent", "") or "")
    if intent not in ("SZ_AM", "SH_AM"):
        return False
    if pend.get("cancel_requested"):
        return True
    print("%s AM cancel unfilled intent=%s" % (STRATEGY_NAME, intent))
    _event_log("am_cancel", intent=intent, now_s=now_s)
    return _request_pending_cancel(C, now, "am_unfilled")


def _handle_sz_sell(C, now, now_s, day, last_px):
    """模式A 深市：封板后以 157.30 卖出。"""
    if not bool(globals().get("ENABLE_MODE_A", True)):
        return
    start = str(globals().get("SELL_START") or "145700")
    end = str(globals().get("SELL_END") or "145955")
    if not _in_window(now_s, start, end):
        return
    if str(getattr(A, "sz_sell_day", "") or "") == day:
        return
    if not _has_position() or not _is_mode_a_pos():
        return
    limit_up = _limit_up()
    # VERIFY：非首日盘面不会封板，跳过 last>=157.30 门闩，只验卖出通道
    if (not _verify_any_day()) and last_px + 1e-9 < limit_up:
        if C.barpos % 5 == 0:
            print(
                "%s SZ_SELL wait limit_up last=%.3f need=%.3f"
                % (STRATEGY_NAME, last_px, limit_up)
            )
        return
    print(
        "%s SZ_SELL @%.3f last=%.3f verify=%s"
        % (STRATEGY_NAME, limit_up, last_px, _verify_any_day())
    )
    _event_log("sz_sell", price=limit_up, last=last_px, verify=_verify_any_day())
    if _order_sell_limit(C, "SZ_SELL", limit_up, now):
        A.sz_sell_day = day
        _save_state()


def _handle_sh_sell_chase(C, now, now_s, day, last_px):
    """模式A 沪市：从笼子上限阶梯追卖至 157.30。"""
    if not bool(globals().get("ENABLE_MODE_A", True)):
        return
    start = str(globals().get("SELL_START") or "145700")
    end = str(globals().get("SELL_END") or "145955")
    if not _in_window(now_s, start, end):
        return
    if not _has_position() or not _is_mode_a_pos():
        return

    reopen = _reopen_cap()
    limit_up = _limit_up()
    target = _cage_cap(last_px if last_px > 0 else reopen)
    if target < reopen:
        target = reopen
    interval = float(globals().get("SH_CHASE_INTERVAL_MS") or 50)
    min_step = float(globals().get("CHASE_MIN_STEP") or 0.01)
    now_ms = _now_ms(now)
    pend = getattr(A, "pending", None)

    if isinstance(pend, dict):
        last_ms = float(getattr(A, "sh_chase_at_ms", 0) or 0)
        if last_ms > 0 and (now_ms - last_ms) < interval:
            if not pend.get("cancel_requested"):
                return
        side = str(pend.get("side", "") or "")
        if side != "sell":
            return
        old_px = float(pend.get("price_hint") or 0)
        if old_px + 1e-9 >= limit_up:
            return
        if target > old_px + min_step:
            if not pend.get("cancel_requested"):
                A.sh_chase_at_ms = now_ms
                print(
                    "%s SH_SELL_CHASE cancel->%.3f old=%.3f last=%.3f"
                    % (STRATEGY_NAME, target, old_px, last_px)
                )
                _event_log(
                    "sh_sell_chase",
                    target=target,
                    old=old_px,
                    last=last_px,
                )
                _request_pending_cancel(C, now, "sell_cage_up")
                if getattr(A, "pending", None):
                    return
            else:
                return
        else:
            return

    if "SELL" in getattr(A, "acted", set()):
        return
    if str(getattr(A, "sh_sell_day", "") or "") == day and not getattr(A, "pending", None):
        # 已挂过且无 pending：可能已成交或废单；有仓则允许继续追
        pass

    A.sh_chase_at_ms = now_ms
    intent = "SH_SELL" if target + 1e-9 >= limit_up else "SH_SELL_CHASE"
    print(
        "%s %s @%.3f last=%.3f"
        % (STRATEGY_NAME, intent, target, last_px)
    )
    _event_log("sh_sell", intent=intent, price=target, last=last_px)
    if _order_sell_limit(C, intent, target, now):
        A.sh_sell_day = day
        A.sh_last_order_px = float(target)
        _save_state()


def _handle_sz_mode_b(C, now, now_s, day, last_px):
    """深市 Mode B：临停埋 143 → 封板后撤未成单再挂 157.30。"""
    if not bool(globals().get("ENABLE_MODE_B", True)):
        return
    reopen = _reopen_cap()
    limit_up = _limit_up()
    pre_s = str(globals().get("SZ_PREPLACE_START") or "130000")
    pre_e = str(globals().get("SZ_PREPLACE_END") or "145459")
    close_s = str(globals().get("SZ_CLOSE_BUY_START") or "145700")
    close_e = str(globals().get("SZ_CLOSE_BUY_END") or "145950")
    alert_sec = float(globals().get("SZ_ESCALATE_ALERT_SEC") or 2.0)

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
        if _order_buy_limit(C, reopen, now, intent="SZ_PREPLACE", entry_mode="B"):
            A.sz_preplace_day = day
            A.buy_done_day = day
            _save_state()
        return

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
            if getattr(A, "pending", None):
                return
            pend = None
        else:
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
    if _order_buy_limit(C, limit_up, now, intent="SZ_CLOSE", entry_mode="B"):
        A.sz_close_buy_day = day
        A.buy_done_day = day
        _save_state()


def _handle_sh_mode_b(C, now, now_s, day, last_px):
    """沪市 Mode B：143 起阶梯追至 157.30。"""
    if not bool(globals().get("ENABLE_MODE_B", True)):
        return
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
    interval = float(globals().get("SH_CHASE_INTERVAL_MS") or 50)
    min_step = float(globals().get("CHASE_MIN_STEP") or 0.01)
    now_ms = _now_ms(now)
    pend = getattr(A, "pending", None)
    if isinstance(pend, dict):
        last_ms = float(getattr(A, "sh_chase_at_ms", 0) or 0)
        if last_ms > 0 and (now_ms - last_ms) < interval:
            if pend.get("cancel_requested"):
                pass
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
                if getattr(A, "pending", None):
                    return
            else:
                if C.barpos % 3 == 0:
                    print(
                        "%s SH_CHASE wait cancel old=%.3f target=%.3f"
                        % (STRATEGY_NAME, old_px, target)
                    )
                return
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
    if _order_buy_limit(C, target, now, intent=intent, entry_mode="B"):
        A.sh_chase_day = day
        A.sh_last_order_px = float(target)
        A.buy_done_day = day
        _save_state()


def _underlying_open_gap(C, day, cb_open, cost):
    """开盘缺口：优先正股；否则转债开盘相对昨收（勿用成本价，否则 ModeB 顶格买次日几乎必触发止损）。"""
    stock = str(getattr(A, "stock", "") or "")
    mp = globals().get("UNDERLYING_MAP") or {}
    und = str(mp.get(stock) or "").strip()
    if und:
        try:
            md = C.get_market_data_ex(
                fields=["open", "close"],
                stock_code=[und],
                period="1d",
                end_time=str(day),
                count=3,
                dividend_type="none",
                fill_data=False,
                subscribe=False,
            )
            opens = _series_from_ex(md, und, "open")
            closes = _series_from_ex(md, und, "close")
            if opens is not None and closes is not None and len(opens) >= 1:
                o = float(opens[-1])
                prev = float(closes[-2]) if len(closes) >= 2 else float(closes[-1])
                if prev > 0 and o > 0:
                    return (o / prev) - 1.0, "underlying"
        except Exception as e:
            _diag_once("underlying_gap_fail", e)
    prev = _prev_close_px(C, day)
    if prev > 0 and cb_open and cb_open > 0:
        return (float(cb_open) / float(prev)) - 1.0, "cb_vs_prev"
    if cost and cost > 0 and cb_open and cb_open > 0:
        return (float(cb_open) / float(cost)) - 1.0, "cb_vs_cost"
    return None, "none"


def _handle_day2_exit(C, now, now_s, day, last_px, open_px):
    """模式B 隔夜仓：次日高开锁利 / 移动止盈 / 低开止损。"""
    if not bool(globals().get("ENABLE_DAY2_EXIT", True)):
        return
    if not _has_position():
        return
    # Mode A 若首日未卖掉，次日也按同一退出规则处理
    opened = _pos_opened_day()
    if opened and opened >= day:
        return

    if str(getattr(A, "d2_check_day", "") or "") != day:
        A.d2_check_day = day
        A.d2_auc_checked = False
        A.d2_day_high = 0.0
        A.d2_open_px = 0.0

    cost = float((getattr(A, "position", None) or {}).get("price", 0) or 0)
    if cost <= 0:
        cost = float(last_px or 0)

    # 记录次日开盘参考价
    if float(getattr(A, "d2_open_px", 0) or 0) <= 0 and open_px and open_px > 0:
        A.d2_open_px = float(open_px)
        _save_state()
    d2_open = float(getattr(A, "d2_open_px", 0) or 0) or float(open_px or 0)

    # 1) 集合竞价高开锁利（回测常无 09:15–09:25 K，09:30 首根用开盘价补一次）
    auc_s = str(globals().get("D2_AUCTION_START") or "091500")
    auc_e = str(globals().get("D2_AUCTION_END") or "092459")
    trail_s = str(globals().get("D2_TRAIL_START") or "093000")
    trail_e = str(globals().get("D2_TRAIL_END") or "093500")
    gap_up = float(globals().get("D2_GAP_UP_MIN") or 0.05)
    in_auc = _in_window(now_s, auc_s, auc_e)
    auc_catchup = (
        (not in_auc)
        and str(now_s) >= trail_s
        and str(now_s) <= trail_e
        and str(getattr(A, "d2_auction_day", "") or "") != day
        and float(getattr(A, "d2_open_px", 0) or 0) > 0
        and not bool(getattr(A, "d2_auc_checked", False))
    )
    if (in_auc or auc_catchup) and str(getattr(A, "d2_auction_day", "") or "") != day:
        A.d2_auc_checked = True
        ref = d2_open if d2_open > 0 else last_px
        if cost > 0 and ref > 0 and (ref / cost - 1.0) >= gap_up:
            print(
                "%s D2_AUCTION sell gap=%.2f%% ref=%.3f cost=%.3f catchup=%s"
                % (
                    STRATEGY_NAME,
                    (ref / cost - 1.0) * 100.0,
                    ref,
                    cost,
                    auc_catchup,
                )
            )
            _event_log(
                "d2_auction_sell",
                ref=ref,
                cost=cost,
                gap=ref / cost - 1.0,
                catchup=auc_catchup,
            )
            if _order_sell_limit(C, "D2_AUCTION", _px_round(ref), now) or _order_sell_mkt(
                C, "D2_AUCTION", now
            ):
                A.d2_auction_day = day
                _save_state()
            return

    # 2) 09:30 低开止损（正股或转债相对昨收）
    gap_dn = float(globals().get("D2_GAP_DOWN_STOP") or -0.02)
    if (
        str(now_s) >= trail_s
        and str(getattr(A, "d2_stop_day", "") or "") != day
        and str(now_s) <= trail_e
    ):
        gap, src = _underlying_open_gap(C, day, d2_open or open_px, cost)
        if gap is not None and gap <= gap_dn:
            print(
                "%s D2_STOP sell gap=%.2f%% src=%s"
                % (STRATEGY_NAME, gap * 100.0, src)
            )
            _event_log("d2_stop_sell", gap=gap, src=src)
            if _order_sell_mkt(C, "D2_STOP", now):
                A.d2_stop_day = day
                _save_state()
            return

    # 3) 开盘后移动止盈：自最高点回撤
    dd = float(globals().get("D2_TRAIL_DRAWDOWN") or 0.015)
    if _in_window(now_s, trail_s, trail_e):
        hi = float(getattr(A, "d2_day_high", 0) or 0)
        if last_px > hi:
            A.d2_day_high = float(last_px)
            hi = float(last_px)
            _save_state()
        if (
            hi > 0
            and last_px > 0
            and (hi - last_px) / hi >= dd
            and str(getattr(A, "d2_trail_day", "") or "") != day
        ):
            print(
                "%s D2_TRAIL sell hi=%.3f last=%.3f dd=%.2f%%"
                % (STRATEGY_NAME, hi, last_px, ((hi - last_px) / hi) * 100.0)
            )
            _event_log("d2_trail_sell", high=hi, last=last_px, dd=(hi - last_px) / hi)
            if _order_sell_mkt(C, "D2_TRAIL", now):
                A.d2_trail_day = day
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
                pass
            else:
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
    try:
        bar_high = float(highs[-1])
    except Exception:
        bar_high = bar_last
    last_px = _tick_last(C, fallback=bar_last)
    if last_px <= 0:
        last_px = _px_round(bar_last)
    # 沪市阶梯追单：回测用当根 high 近似 last 抬升（避免只用收盘漏追）
    chase_px = last_px
    if bt and bar_high > chase_px:
        chase_px = _px_round(bar_high)

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
            "mkt=%s n=%d last=%.3f open=%.3f hold=%s mode=%s size=%s "
            "buy_done=%s pending=%s cage=%.3f"
            % (
                mkt,
                len(closes),
                last_px,
                open_px,
                holding,
                _entry_mode_of(),
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

    # ---- 持仓：Mode A 复牌卖 / Mode B 次日出局 ----
    if holding:
        if "SELL" in getattr(A, "acted", set()) and (not getattr(A, "pending", None)):
            return
        opened = _pos_opened_day()
        if opened and opened < day:
            _handle_day2_exit(C, now, now_s, day, last_px, open_px)
            return
        if _is_listing_day(C, day) or _verify_any_day():
            if mkt == "SZ":
                _handle_sz_sell(C, now, now_s, day, last_px)
            elif mkt == "SH":
                _handle_sh_sell_chase(C, now, now_s, day, chase_px)
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

    # ---- Mode A 早盘 ----
    if _try_morning_buy(C, now, now_s, day):
        return

    # 早盘未成：撤单腾出 Mode B
    if _cleanup_am_pending(C, now, now_s):
        if getattr(A, "pending", None):
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
