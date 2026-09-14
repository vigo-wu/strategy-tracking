# === fband/factors/lib/above_ema.py ===
def _factor_eval_above_ema(ctx):
    try:
        n = int(_structure_windows()["ema"]["1d"]["trend"] or 0)
    except (TypeError, ValueError, KeyError):
        n = 0
    if n <= 0:
        return True, {"n": n, "off": True}
    market = (ctx or {}).get("market") or {}
    if not market.get("daily_ready"):
        return False, {"n": n}
    price = market.get("close")
    if price is None:
        price = market.get("daily_detail", {}).get("price")
    ma = market.get("ma_trend")
    if price is None or ma is None:
        return False, {"n": n, "ma": ma, "price": price}
    hit = float(price) > float(ma)
    return hit, {"n": n, "ma": ma, "price": float(price)}
