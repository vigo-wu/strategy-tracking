# === hongli/backtest.py ===
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
def _bt_held_vol():
    return max(0, int(getattr(A, "bt_held", 0) or 0))


def _bt_locked_vol():
    return max(0, int(getattr(A, "bt_locked", 0) or 0))


def _bt_available_vol():
    """回测 T+1: 非当日买入的可卖股数（对应 QMT 可卖）。"""
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
        print("HongliT bt T+1 unlock day=", day, "was_locked=", _bt_locked_vol())
    A.bt_locked = 0
    A.bt_lock_day = day


def _bt_held_add(vol, buy_day=None):
    if not getattr(A, "is_backtest", False):
        return
    vol = max(0, int(vol))
    A.bt_held = _bt_held_vol() + vol
    if buy_day:
        _bt_roll_t1(str(buy_day)[:8])
        A.bt_locked = _bt_locked_vol() + vol


def _bt_held_set(vol):
    if not getattr(A, "is_backtest", False):
        return
    A.bt_held = max(0, int(vol))
    if A.bt_held < 100:
        A.bt_opened_at = ""
        A.bt_locked = 0
    else:
        A.bt_locked = min(_bt_locked_vol(), A.bt_held)


def _bt_recover_float(now=None, last=None):
    """影子持仓仍在但浮仓腿为空时，重新吸纳以便退出信号仍能触发。"""
    if not getattr(A, "is_backtest", False):
        return False
    held = _bt_held_vol()
    if held < 100:
        return False
    if _sell_float_vol() >= 100:
        return False
    px = float(last) if last and last > 0 else 0.0
    ot = str(getattr(A, "bt_opened_at", "") or "").strip()
    if not ot:
        ot = (now or datetime.datetime.now()).strftime("%Y%m%d%H%M%S")
    A.float_a = {
        "shares": held,
        "price": px,
        "cost": round(held * px, 2) if px > 0 else 0.0,
        "opened_at": ot,
    }
    A.float_b = None
    print("HongliT bt recover float from held", A.float_a)
    return True
