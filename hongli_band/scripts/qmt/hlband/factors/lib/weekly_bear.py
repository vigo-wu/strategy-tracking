# === hlband/factors/lib/weekly_bear.py ===
def _factor_eval_weekly_bear(ctx):
    """当天空头（禁开/撤买）。确认清仓走 weekly_bear_confirm。"""
    w_detail = ((ctx or {}).get("market") or {}).get("w_detail") or {}
    c = w_detail.get("close")
    m30 = w_detail.get("ma30")
    d0 = w_detail.get("dif")
    e0 = w_detail.get("dea")
    d1 = w_detail.get("dif_prev")
    e1 = w_detail.get("dea_prev")
    if None in (c, m30, d0, e0):
        return False, {}
    death_below = _cross_down(d1, e1, d0, e0) and (d0 < 0) and (e0 < 0)
    bear = (c < m30) or death_below
    return bool(bear), {"death_below": bool(death_below)}
