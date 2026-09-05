# === qmt_common/backtest.py ===
# 作用: 回测影子持仓与 T+1 锁定
# 主要符号: _bt_held_*, _bt_locked_*, _bt_roll_t1, _allow_t0
# 说明: 仓位恢复（_bt_recover_*）由策略侧实现
# 策略可设 ALLOW_T0=True（ETF 等当日可卖）；默认 False 保持 T+1
def _allow_t0():
    return bool(globals().get("ALLOW_T0", False))


def _bt_held_vol():
    return max(0, int(getattr(A, "bt_held", 0) or 0))


def _bt_locked_vol():
    return max(0, int(getattr(A, "bt_locked", 0) or 0))


def _bt_available_vol():
    """回测可卖：T+1 为 held-locked；ALLOW_T0 时为 held。"""
    if _allow_t0():
        return _bt_held_vol()
    return max(0, _bt_held_vol() - _bt_locked_vol())


def _bt_roll_t1(day):
    """新日历日解锁此前买入，变为可卖。"""
    if not getattr(A, "is_backtest", False):
        return
    day = str(day or "")
    if not day:
        return
    if str(getattr(A, "bt_lock_day", "") or "") == day:
        return
    if _bt_locked_vol() > 0:
        print(_strategy_tag(), "bt T+1 unlock day=", day, "was_locked=", _bt_locked_vol())
    A.bt_locked = 0
    A.bt_lock_day = day


def _bt_held_add(vol, buy_day=None):
    if not getattr(A, "is_backtest", False):
        return
    vol = max(0, int(vol))
    A.bt_held = _bt_held_vol() + vol
    if _allow_t0():
        return
    if buy_day:
        _bt_roll_t1(str(buy_day)[:8])
        A.bt_locked = _bt_locked_vol() + vol


def _bt_held_set(vol):
    if not getattr(A, "is_backtest", False):
        return
    A.bt_held = max(0, int(vol))
    if A.bt_held <= 0:
        A.bt_opened_at = ""
        A.bt_locked = 0
    else:
        A.bt_locked = min(_bt_locked_vol(), A.bt_held)
