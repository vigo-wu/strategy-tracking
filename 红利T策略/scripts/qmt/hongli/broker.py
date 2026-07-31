# === hongli/broker.py ===
# 作用: 资金/持仓可卖/底仓隔离/对账
# 主要符号: _available_cash, _max_sell_vol, _reconcile_float_with_broker
# 拼接序: 12/16 | 上一部: mode.py | 下一部: orders.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
def _available_cash():
    if getattr(A, "is_backtest", False):
        return 10**9
    accs = get_trade_detail_data(A.acct, A.acct_type, "account")
    if not accs:
        print("account not login", A.acct)
        return None
    return float(accs[0].m_dAvailable)


def _pos_code(p):
    return p.m_strInstrumentID + "." + p.m_strExchangeID


def _broker_position(stock):
    """返回标的 (总量, 可卖, 成本价)；无持仓则 (0,0,0)。"""
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return 0, 0, 0.0
    positions = get_trade_detail_data(A.acct, A.acct_type, "position")
    if not positions:
        return 0, 0, 0.0
    for p in positions:
        if _pos_code(p) != stock:
            continue
        vol = int(getattr(p, "m_nVolume", 0) or 0)
        can = int(getattr(p, "m_nCanUseVolume", 0) or 0)
        cost = 0.0
        for attr in ("m_dOpenPrice", "m_dCostPrice", "m_dAvgPrice"):
            v = getattr(p, attr, None)
            if v is not None:
                try:
                    cost = float(v)
                    if cost > 0:
                        break
                except Exception:
                    pass
        return vol, can, cost
    return 0, 0, 0.0


def _can_use_vol(stock):
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return 10**9
    _vol, can, _cost = _broker_position(stock)
    return int(can)


def _base_shares():
    return max(0, int(BASE_SHARES or 0))


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
    # 未知价格: 按预算以约 1 元最差手数估算上限
    return int(budget // 100) * 100


def _max_sell_vol():
    """最多卖策略浮仓，永不碰 BASE_SHARES。始终受 T+1 约束。"""
    want = _sell_float_vol()
    if getattr(A, "is_backtest", False):
        # 计入影子持仓；按 T+1 可卖封顶（对齐 QMT 可卖）
        want = max(want, _bt_held_vol())
        avail = _bt_available_vol()
        return max(0, min(want, avail))
    if want < 100:
        return 0
    if DRY_RUN:
        # 空跑仍遵守日历 T+1，使日志与实盘约束一致。
        return _dry_t1_sellable(want)
    broker_vol, can, _cost = _broker_position(A.stock)
    floatable = _floatable_broker_vol(broker_vol)
    # 实盘硬规则: 不超过 m_nCanUseVolume（当日买 = 可卖 0）。
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
        print("HongliT reconcile skip: pending active")
        return
    broker_vol, _can, broker_cost = _broker_position(A.stock)
    floatable = _floatable_broker_vol(broker_vol)
    state_vol = _sell_float_vol()
    changed = False
    if floatable < 100:
        if state_vol > 0:
            print(
                "HongliT reconcile: no floatable (broker=%s base=%s), clear float was %s"
                % (broker_vol, _base_shares(), state_vol)
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
                "HongliT reconcile: broker has shares but adopt cap <100 (floatable=%s cap=%s); leave unmanaged"
                % (floatable, cap)
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
                "HongliT reconcile: adopt floatable as float_a",
                A.float_a,
                "broker=",
                broker_vol,
                "base=",
                _base_shares(),
            )
    elif state_vol > floatable:
        print(
            "HongliT reconcile: shrink float",
            state_vol,
            "->",
            floatable,
            "(broker=%s base=%s)" % (broker_vol, _base_shares()),
        )
        _shrink_float_to_vol(floatable)
        changed = True
    if changed:
        _save_state()
