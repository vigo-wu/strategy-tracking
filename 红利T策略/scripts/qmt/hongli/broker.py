# === hongli/broker.py ===
# 作用: 红利T 底仓隔离 / 可卖上限 / 浮仓对账
# 前置: common/broker_base；主要符号: _max_sell_vol, _reconcile_with_broker
def _base_shares():
    return max(0, int(globals().get("BASE_SHARES") or 0))


def _floatable_broker_vol(broker_vol):
    """超出 BASE_SHARES、可由本策略管理的股数。"""
    return max(0, int(broker_vol) - _base_shares())


def _adopt_share_cap(price):
    """对账吸纳上限: 仅按浮仓预算（非整户持仓）。"""
    budget = float(FLOAT_A_BUDGET)
    if _enable_float_b():
        budget += float(FLOAT_B_BUDGET)
    if price and price > 0:
        return _lot(price, budget)
    return int(budget // 100) * 100


def _max_sell_vol():
    """最多卖策略浮仓，永不碰 BASE_SHARES。始终受 T+1 约束。"""
    want = _sell_float_vol()
    if getattr(A, "is_backtest", False):
        want = max(want, _bt_held_vol())
        avail = _bt_available_vol()
        return max(0, min(want, avail))
    if want < 100:
        return 0
    if DRY_RUN:
        return _dry_t1_sellable(want)
    broker_vol, can, _cost = _broker_position(A.stock)
    floatable = _floatable_broker_vol(broker_vol)
    return max(0, min(want, int(can), floatable))


def _dry_t1_sellable(want):
    """DRY_RUN 的 T+1: 无券商可卖数据时，禁止同日历日卖出。"""
    want = int(want)
    if want < 100:
        return 0
    now = datetime.datetime.now()
    day = now.strftime("%Y%m%d")
    locked = 0
    for leg in (getattr(A, "float_a", None), getattr(A, "float_b", None)):
        if not _has_leg(leg):
            continue
        ot = _parse_opened_at(leg.get("opened_at"))
        if ot is not None and ot.strftime("%Y%m%d") == day:
            locked += int(leg.get("shares", 0) or 0)
    return max(0, want - locked)


def _reconcile_float_with_broker():
    """对齐 JSON 浮仓与券商可管理股数。有 pending 则跳过。永不碰 BASE_SHARES。"""
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return
    if getattr(A, "pending", None):
        print(_strategy_tag(), "reconcile skip: pending active")
        return
    broker_vol, _can, broker_cost = _broker_position(A.stock)
    floatable = _floatable_broker_vol(broker_vol)
    state_vol = _sell_float_vol()
    changed = False
    if floatable < 100:
        if state_vol > 0:
            print(
                _strategy_tag(),
                "reconcile: no floatable (broker=%s base=%s), clear float was %s"
                % (broker_vol, _base_shares(), state_vol),
            )
            A.float_a = None
            A.float_b = None
            changed = True
    elif state_vol <= 0:
        px = float(broker_cost) if broker_cost and broker_cost > 0 else 0.0
        cap = _adopt_share_cap(px if px > 0 else None)
        sh = int(min(floatable, cap) // 100) * 100
        if sh < 100:
            print(
                _strategy_tag(),
                "reconcile: broker has shares but adopt cap <100 (floatable=%s cap=%s); leave unmanaged"
                % (floatable, cap),
            )
        else:
            A.float_a = {
                "shares": sh,
                "price": px,
                "cost": round(sh * px, 2) if px > 0 else 0.0,
                "opened_at": datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
                "adopted": True,
            }
            A.float_b = None
            changed = True
            print(
                _strategy_tag(),
                "reconcile: adopt floatable as float_a",
                A.float_a,
                "broker=",
                broker_vol,
                "base=",
                _base_shares(),
            )
    elif state_vol > floatable:
        print(
            _strategy_tag(),
            "reconcile: shrink float",
            state_vol,
            "->",
            floatable,
            "(broker=%s base=%s)" % (broker_vol, _base_shares()),
        )
        _shrink_float_to_vol(floatable)
        changed = True
    if changed:
        _save_state()


def _reconcile_with_broker():
    """mode 暖机切实盘钩子。"""
    _reconcile_float_with_broker()


def _heartbeat_extra():
    return "A=%s B=%s pending=%s" % (
        _has_leg(getattr(A, "float_a", None)),
        _has_leg(getattr(A, "float_b", None)),
        bool(getattr(A, "pending", None)),
    )
