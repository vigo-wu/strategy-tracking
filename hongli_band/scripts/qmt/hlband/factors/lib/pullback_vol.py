# === hlband/factors/lib/pullback_vol.py ===
def _f_pullback_vol(ctx):
    """贴中/慢均线 + 连续缩量。不含 chase / vol_dry。"""
    m = ctx.get("market") or {}
    closes = m.get("closes")
    volumes = m.get("volumes")
    vol10 = m.get("vol10")
    i = m.get("i")
    vol_need = int(m.get("vol_need") or 1)
    detail = {
        "ma20": m.get("m20"),
        "ma60": m.get("m60"),
        "vol10": m.get("v10"),
        "vol20": m.get("v20"),
        "vol_need": vol_need,
        "vol_streak": 0,
    }
    if vol10 is None or m.get("vol20") is None:
        return False, detail
    if closes is None or volumes is None or i is None:
        return False, detail
    if i < max(2, vol_need):
        return False, detail
    price = float(closes[i])
    mid_n = int(m.get("mid_n") or 0)
    slow_n = int(m.get("slow_n") or 0)
    near = False
    if mid_n > 0:
        near = near or _near_ma(price, m.get("m20"))
    if slow_n > 0:
        near = near or _near_ma(price, m.get("m60"))
    ratio = float(VOL_PULLBACK_RATIO)
    vol_streak = 0
    for k in range(vol_need):
        j = i - k
        vma = _last_valid(vol10, j)
        vj = float(volumes[j])
        if vma is None or vma <= 0 or vj >= vma * ratio:
            break
        vol_streak += 1
    detail["vol_streak"] = vol_streak
    if near and vol_streak >= vol_need:
        return True, detail
    return False, detail


_register_factor("pullback_vol", _f_pullback_vol)
