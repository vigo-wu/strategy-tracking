# === hlband/factors/lib/vol_dry.py ===
def _f_vol_dry(ctx):
    m = ctx.get("market") or {}
    mid_n = int(m.get("mid_n") or 0)
    m20 = m.get("m20")
    v20 = m.get("v20")
    price = m.get("price")
    volumes = m.get("volumes")
    i = m.get("i")
    if mid_n <= 0 or m20 is None or v20 is None or price is None:
        return False, {}
    if volumes is None or i is None or i < 0:
        return False, {}
    vol = float(volumes[i])
    dry = (
        float(price) < float(m20)
        and float(v20) > 0
        and vol < float(v20) * float(VOL_DRY_RATIO)
    )
    return bool(dry), {}


_register_factor("vol_dry", _f_vol_dry, "vol_dry_skip", "gate")
