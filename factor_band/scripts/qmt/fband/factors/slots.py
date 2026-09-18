# === fband/factors/slots.py ===
def _copy_nested_table(src):
    """递归深拷贝嵌套 dict（structure 三层 / factor_params 两层皆可）。"""
    if not isinstance(src, dict):
        return src
    out = {}
    for fid, block in src.items():
        if isinstance(block, dict):
            out[str(fid)] = _copy_nested_table(block)
        else:
            out[str(fid)] = block
    return out


def _merge_nested_table(dst, incoming):
    """递归深合并；两边都是 dict 则下钻，否则覆盖。"""
    if not isinstance(incoming, dict):
        return dst
    if not isinstance(dst, dict):
        return _copy_nested_table(incoming)
    for fid, block in incoming.items():
        key = str(fid)
        if isinstance(block, dict):
            cur = dst.get(key)
            if not isinstance(cur, dict):
                dst[key] = {}
                cur = dst[key]
            _merge_nested_table(cur, block)
        else:
            dst[key] = block
    return dst


def _fold_tables_for_fingerprint(fp_src, st_src, overrides):
    """深合并 overrides.factor_params / structure。overrides 袋保持空（apply 后再算指纹）。"""
    fp = {}
    for fid, block in (fp_src or {}).items():
        if isinstance(block, dict):
            copied = dict(block)
            if "tiers" in copied:
                copied["tiers"] = _factor_tiers_as_lists(copied.get("tiers"))
            fp[str(fid)] = copied
        else:
            fp[str(fid)] = block
    st = _copy_nested_table(st_src)
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
    _merge_nested_table(st, ov.get("structure") if isinstance(ov.get("structure"), dict) else {})
    leftover = {}
    return fp, st, leftover


def _recipe_fingerprint(overrides=None, recipe=None):
    """表达式 + 折进表的阈值 + structure；不扫全因子开关。"""
    rec = recipe if recipe is not None else (globals().get("RECIPE") or {})
    fp, st, leftover = _fold_tables_for_fingerprint(
        rec.get("factor_params") or {}, rec.get("structure") or {}, overrides
    )
    payload = {
        "entry": rec.get("entry"),
        "exit": rec.get("exit"),
        "factor_params": fp,
        "structure": st,
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


def _recipe_log_value(fid, key, raw):
    if str(fid) == "trail_stop" and str(key) == "tiers":
        return json.dumps(
            _factor_tiers_as_lists(raw), ensure_ascii=True, separators=(",", ":")
        )
    return raw


def _recipe_log_structure_kv(need, win):
    rows = []
    rows.append(("ma.kind", win["ma"]["kind"]))
    if "d_ma_mid" in need:
        rows.append(("ma.1d.mid", win["ma"]["1d"]["mid"]))
    if "d_ma_slow" in need:
        rows.append(("ma.1d.slow", win["ma"]["1d"]["slow"]))
    if "weekly" in need:
        rows.append(("ma.1w.mid", win["ma"]["1w"]["mid"]))
        rows.append(("ma.1w.trend", win["ma"]["1w"]["trend"]))
    if "atr" in need:
        rows.append(("atr.n", win["atr"]["n"]))
    if "keltner" in need:
        rows.append(("keltner.ma_n", win["keltner"]["ma_n"]))
        rows.append(("keltner.atr_n", win["keltner"]["atr_n"]))
    return rows


def _recipe_log_kv():
    """启用叶子因子数字 + _market_need 用到的指标周期窗。点路径，只给 init。"""
    need = _market_need()
    win = _structure_windows()
    out = list(_recipe_log_structure_kv(need, win))
    leaves = globals().get("LEAVES") or {}
    walk = globals().get("_recipe_compute_leaves")
    used = walk() if callable(walk) else set()
    for fid, leaf in leaves.items():
        if str(fid) not in used:
            continue
        params = (leaf or {}).get("params") or {}
        for key in params:
            raw = _factor_param(None, fid, key)
            out.append(("%s.%s" % (fid, key), _recipe_log_value(fid, key, raw)))
    return out


def _slot_result(hit, reasons=None, detail=None, extra=None):
    out = {"hit": bool(hit), "reasons": list(reasons or []), "detail": detail or {}}
    if extra:
        out.update(extra)
    return out


def _eval_entry_slot(ctx, expr=None):
    recipe = globals().get("RECIPE") or {}
    tree = expr if expr is not None else recipe.get("entry")
    hit, reasons = _recipe_explain(tree, ctx)
    return _slot_result(hit, reasons)


def _eval_scale_in_slot(ctx, expr=None):
    recipe = globals().get("RECIPE") or {}
    tree = expr if expr is not None else recipe.get("scale_in")
    hit, reasons = _recipe_explain(tree, ctx)
    return _slot_result(hit, reasons)


def _eval_exit_slot(ctx, expr=None):
    recipe = globals().get("RECIPE") or {}
    tree = expr if expr is not None else recipe.get("exit")
    if tree is False or tree is None:
        return _slot_result(False)
    hit, reasons = _recipe_hit(tree, ctx)
    return _slot_result(hit, reasons)


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
