# === hlband/factors/lib/stop_loss.py ===
def _f_stop_loss(ctx):
    st = ctx.get("state") or {}
    m = ctx.get("market") or {}
    cost = float(st.get("cost") or 0)
    price = m.get("price")
    if cost <= 0 or price is None:
        return False, {}
    return float(price) <= cost * (1.0 - float(STOP_LOSS)), {}


_register_factor("stop_loss", _f_stop_loss)
