# === hlband/factors/lib/vol_dry.py ===
def _factor_eval_vol_dry(ctx):
    market = (ctx or {}).get("market") or {}
    if not market.get("daily_ready"):
        return False, {}
    mid_n = int(market.get("mid_n") or 0)
    m20 = market.get("ma20")
    price = market.get("close")
    v20 = market.get("v20")
    vol = market.get("vol")
    dry_below = (
        mid_n > 0
        and m20 is not None
        and price is not None
        and price < m20
        and v20 is not None
        and v20 > 0
        and vol is not None
        and vol < v20 * float(VOL_DRY_RATIO)
    )
    return bool(dry_below), {"dry_below": bool(dry_below)}
