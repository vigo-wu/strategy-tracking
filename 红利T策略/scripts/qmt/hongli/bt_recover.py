# === hongli/bt_recover.py ===
# 作用: 红利T 回测影子仓恢复为浮仓腿
# 前置: common/backtest + state(_sell_float_vol)
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
    print(_strategy_tag(), "bt recover float from held", A.float_a)
    return True
