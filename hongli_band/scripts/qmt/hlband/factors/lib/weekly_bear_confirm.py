# === hlband/factors/lib/weekly_bear_confirm.py ===
def _w_bear_confirm_need():
    """最少 1：当天空头即可挂清仓；勿用 `x or 2`（0 会被当成缺省翻成 2）。"""
    raw = globals().get("W_BEAR_CONFIRM_DAYS", 2)
    try:
        n = int(2 if raw is None else raw)
    except Exception:
        n = 2
    return max(1, n)


def _factor_eval_weekly_bear_confirm(ctx):
    """连续 N 个信号日仍空头才确认清仓；读 streak，不改计数。"""
    state = (ctx or {}).get("state") or {}
    if "w_bear_confirmed" in state:
        return bool(state.get("w_bear_confirmed")), {"streak": state.get("w_bear_streak")}
    streak = int(state.get("w_bear_streak") or 0)
    need = _w_bear_confirm_need()
    return streak >= need, {"streak": streak, "need": need}
