# === hlband/factors/slots.py ===
_RECIPE_THRESHOLD_KEYS = (
    "D_MA_MID",
    "D_MA_SLOW",
    "W_MA_FAST",
    "W_MA_LIFE",
    "MACD_FAST",
    "MACD_SLOW",
    "MACD_SIGNAL",
)


def _fold_factor_params_for_fingerprint(fp_src, overrides, param_keys=None):
    """深合并 overrides.factor_params；袋里只留 D_MA_* / W_MA_* / MACD_*。"""
    fp = {}
    for fid, block in (fp_src or {}).items():
        if isinstance(block, dict):
            copied = dict(block)
            if "tiers" in copied:
                copied["tiers"] = _factor_tiers_as_lists(copied.get("tiers"))
            fp[str(fid)] = copied
        else:
            fp[str(fid)] = block
    leftover = {}
    allow = set(_RECIPE_THRESHOLD_KEYS)
    ov = dict(overrides or {})
    incoming = ov.get("factor_params")
    if isinstance(incoming, dict):
        for fid, block in incoming.items():
            if not isinstance(block, dict):
                continue
            cur = fp.get(str(fid))
            if not isinstance(cur, dict):
                cur = {}
                fp[str(fid)] = cur
            cur.update(block)
            if str(fid) == "trail_stop" and "tiers" in cur:
                cur["tiers"] = _factor_tiers_as_lists(cur.get("tiers"))
    for k in sorted(ov):
        ks = str(k)
        if ks == "factor_params":
            continue
        if ks in allow:
            leftover[ks] = ov[k]
    return fp, leftover


def _recipe_fingerprint(overrides=None, recipe=None):
    """表达式 + 折进表的阈值；不扫全因子开关。"""
    rec = recipe if recipe is not None else (globals().get("RECIPE") or {})
    fp, leftover = _fold_factor_params_for_fingerprint(
        rec.get("factor_params") or {}, overrides
    )
    payload = {
        "entry": rec.get("entry"),
        "exit": rec.get("exit"),
        "factor_params": fp,
        "overrides": leftover,
        "scale_in": rec.get("scale_in"),
        "scale_out": rec.get("scale_out"),
    }
    text = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
    )
    h = 2166136261
    for ch in text:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return "%08x" % h


def _slot_result(hit, reasons=None, detail=None, extra=None):
    out = {"hit": bool(hit), "reasons": list(reasons or []), "detail": detail or {}}
    if extra:
        out.update(extra)
    return out


def _entry_log_reasons(ctx):
    """对齐现网 _handle_stock：周线闸门 elif 链 + _eval_daily_buy 提前 return。"""
    daily = []
    if _factor_hit("chase", ctx):
        daily = ["chase_skip"]
    elif _factor_hit("vol_dry", ctx):
        daily = ["vol_dry_skip"]
    elif _factor_hit("pullback_vol", ctx):
        daily = ["pullback_vol"]
    if _factor_hit("weekly_bear", ctx):
        return ["weekly_bear"] + [r for r in daily if r != "weekly_bear"]
    if _factor_hit("w_bias", ctx):
        return ["w_bias_skip"] + [r for r in daily if r != "w_bias_skip"]
    if _factor_hit("w_slope", ctx):
        return ["w_slope_skip"] + [r for r in daily if r != "w_slope_skip"]
    return list(daily)


def _scale_trigger_reasons(ctx):
    reasons = []
    if _factor_hit("pullback_vol", ctx) and (not _factor_hit("chase", ctx)):
        reasons.append("pullback_vol")
    if _factor_hit("plat_break", ctx):
        reasons.append("plat_break")
    if _factor_hit("w_macd_golden", ctx):
        reasons.append("w_macd_golden")
    return reasons


def _eval_entry_slot(ctx, expr=None):
    recipe = globals().get("RECIPE") or {}
    tree = expr if expr is not None else recipe.get("entry")
    hit, reasons = _recipe_hit(tree, ctx)
    logs = _entry_log_reasons(ctx)
    return _slot_result(hit, logs if logs else reasons)


def _eval_scale_in_slot(ctx, expr=None):
    recipe = globals().get("RECIPE") or {}
    tree = expr if expr is not None else recipe.get("scale_in")
    hit, _reasons = _recipe_hit(tree, ctx)
    triggers = _scale_trigger_reasons(ctx)
    return _slot_result(hit, triggers, extra={"triggers": triggers})


def _eval_exit_slot(ctx, expr=None):
    recipe = globals().get("RECIPE") or {}
    ordered = expr if expr is not None else recipe.get("exit")
    if ordered is False or ordered is None:
        return _slot_result(False)
    if isinstance(ordered, (list, tuple)) and ordered and ordered[0] in ("and", "or", "not"):
        hit, reasons = _recipe_hit(ordered, ctx)
        return _slot_result(hit, reasons)
    for fid in list(ordered or ()):
        if str(fid) == "weekly_bear_confirm":
            if _factor_hit("weekly_bear_confirm", ctx):
                return _slot_result(True, ["weekly_bear"])
            continue
        if _factor_hit(fid, ctx):
            return _slot_result(True, [fid])
    return _slot_result(False)


def _eval_scale_out_slot(ctx, expr=None):
    recipe = globals().get("RECIPE") or {}
    tree = expr if expr is not None else recipe.get("scale_out")
    if tree is False or tree is None:
        return _slot_result(False)
    hit, reasons = _recipe_hit(tree, ctx)
    return _slot_result(hit, reasons)


def _eval_recipe_slots(ctx):
    recipe = globals().get("RECIPE") or {}
    return {
        "entry": _eval_entry_slot(ctx, recipe.get("entry")),
        "scale_in": _eval_scale_in_slot(ctx, recipe.get("scale_in")),
        "exit": _eval_exit_slot(ctx, recipe.get("exit")),
        "scale_out": _eval_scale_out_slot(ctx, recipe.get("scale_out")),
    }
