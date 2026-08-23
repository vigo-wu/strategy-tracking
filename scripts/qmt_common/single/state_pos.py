# === qmt_common/single/state_pos.py ===
# 作用: 单仓 A.position 读写辅助
# 主要符号: _has_position, _pos_shares, _pos_cost_price, _reset_day, _clear_after_sell
def _reset_day(day):
    if getattr(A, "acted_day", "") != day:
        A.acted_day = day
        A.acted = set()
        try:
            _save_state()
        except Exception:
            pass


def _has_position():
    pos = getattr(A, "position", None)
    return isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= _vol_step()


def _pos_shares():
    if not _has_position():
        return 0
    return int(A.position.get("shares", 0) or 0)


def _pos_cost_price():
    if not _has_position():
        return 0.0
    return float(A.position.get("price", 0) or 0)


def _clear_after_sell(now, reason, last=None):
    cleared = getattr(A, "position", None)
    print(_strategy_tag(), "SELL done", reason, "last=", last, "cleared", cleared)
    _event_log("sell_done", sell_reason=reason, last=last, cleared=cleared)
    A.position = None
    A.lots = []
    A.acted.add("SELL")
    if getattr(A, "is_backtest", False):
        A.bt_held = 0
        A.bt_locked = 0
        A.bt_opened_at = ""
    _save_state()
