# === hlband/factors/lib/pullback_vol.py ===
def _near_ma(price, ma, tol=None):
    if tol is None:
        tol = _factor_param(None, "pullback_vol", "tol")
    tol = float(tol)
    if price is None or ma is None or ma <= 0:
        return False
    return abs(float(price) - float(ma)) / float(ma) <= tol


def _factor_eval_pullback_vol(ctx):
    market = (ctx or {}).get("market") or {}
    if not market.get("daily_ready"):
        return False, {"vol_streak": 0}
    mid_n = int(market.get("mid_n") or 0)
    slow_n = int(market.get("slow_n") or 0)
    price = market.get("close")
    if price is None:
        price = market.get("daily_detail", {}).get("price")
    m20 = market.get("ma20")
    m60 = market.get("ma60")
    vol10 = market.get("vol10")
    volumes = market.get("volumes")
    i = int(market.get("i") or 0)
    vol_need = int(market.get("vol_need") or _vol_pullback_confirm_need())
    near = False
    if mid_n > 0:
        near = near or _near_ma(price, m20)
    if slow_n > 0:
        near = near or _near_ma(price, m60)
    ratio = float(_factor_param(ctx, "pullback_vol", "ratio"))
    vol_streak = 0
    if volumes is None or vol10 is None:
        return False, {"vol_streak": 0, "near": near}
    for k in range(vol_need):
        j = i - k
        vma = _last_valid(vol10, j)
        vj = float(volumes[j])
        if vma is None or vma <= 0 or vj >= vma * ratio:
            break
        vol_streak += 1
    hit = bool(near and vol_streak >= vol_need)
    return hit, {"vol_streak": vol_streak, "near": near}
