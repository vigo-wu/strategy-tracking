# === hlband/factors/registry.py ===
def _factor_registry():
    return {
        "pullback_vol": _factor_eval_pullback_vol,
        "chase": _factor_eval_chase,
        "vol_dry": _factor_eval_vol_dry,
        "w_bias": _factor_eval_w_bias,
        "w_slope": _factor_eval_w_slope,
        "weekly_bear": _factor_eval_weekly_bear,
        "weekly_bear_confirm": _factor_eval_weekly_bear_confirm,
        "plat_break": _factor_eval_plat_break,
        "w_macd_golden": _factor_eval_w_macd_golden,
        "stop_loss": _factor_eval_stop_loss,
        "atr_stop": _factor_eval_atr_stop,
        "trail_stop": _factor_eval_trail_stop,
        "atr_trail_stop": _factor_eval_atr_trail_stop,
        "time_force": _factor_eval_time_force,
    }


def _factor_eval(fid, ctx):
    fn = _factor_registry().get(str(fid or ""))
    if fn is None:
        return False, {}
    ok, detail = fn(ctx)
    return bool(ok), detail or {}


def _factor_hit(fid, ctx):
    ok, _detail = _factor_eval(fid, ctx)
    return bool(ok)
