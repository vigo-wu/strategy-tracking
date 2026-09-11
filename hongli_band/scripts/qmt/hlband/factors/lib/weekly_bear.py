# === hlband/factors/lib/weekly_bear.py ===
def _f_weekly_bear(ctx):
    return bool((ctx.get("clock") or {}).get("weekly_bear")), {}


_register_factor("weekly_bear", _f_weekly_bear, "weekly_bear", "gate")
