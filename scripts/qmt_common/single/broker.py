# === qmt_common/single/broker.py ===
# 作用: 单仓可卖上限（T+1 / can_use）
# 主要符号: _max_sell_vol, _dry_t1_sellable
def _dry_t1_sellable(want, now):
    """DRY_RUN 可卖: 默认禁止同日历日卖出当日买入仓; ALLOW_T0 则放行。"""
    want = int(want)
    if want < _vol_step():
        return 0
    if not _has_position():
        return 0
    if _allow_t0():
        return want
    ot = _parse_opened_at(A.position.get("opened_at"))
    if ot is not None and now is not None and ot.date() == now.date():
        return 0
    return want


def _max_sell_vol(now=None):
    """最多可卖股数; 默认 T+1, ALLOW_T0 时回测/DRY 不锁当日仓. skip 时调用方绝不清仓."""
    want = _pos_shares()
    if getattr(A, "is_backtest", False):
        if now is not None:
            _bt_roll_t1(now.strftime("%Y%m%d"))
        want = max(want, _bt_held_vol())
        return max(0, min(want, _bt_available_vol()))
    if want < _vol_step():
        return 0
    if DRY_RUN:
        return _dry_t1_sellable(want, now or datetime.datetime.now())
    broker_vol, can, _cost = _broker_position(A.stock)
    return max(0, min(want, int(can), int(broker_vol)))
