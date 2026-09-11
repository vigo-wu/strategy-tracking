# === hlband/factors/lib/chase.py ===
def _f_chase(ctx):
    m = ctx.get("market") or {}
    closes = m.get("closes")
    i = m.get("i")
    if closes is None or i is None or i < 1:
        return False, {}
    price = float(closes[i])
    prev = float(closes[i - 1]) if closes[i - 1] else 0.0
    if prev > 0 and (price - prev) / prev >= float(CHASE_MAX_PCT):
        return True, {}
    return False, {}


_register_factor("chase", _f_chase, "chase_skip", "gate")
