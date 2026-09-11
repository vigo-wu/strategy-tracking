# === hlband/factors/slots.py ===
def _recipe_json():
    payload = {
        "entry": globals().get("RECIPE_ENTRY"),
        "exits": globals().get("RECIPE_EXITS"),
        "scale_in": globals().get("RECIPE_SCALE_IN"),
        "scale_out": globals().get("RECIPE_SCALE_OUT"),
        "exit_w_bear": bool(globals().get("RECIPE_EXIT_WEEKLY_BEAR", True)),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _or_leaves(expr):
    if isinstance(expr, str) and expr:
        return [expr]
    if isinstance(expr, (list, tuple)) and expr and str(expr[0]).lower() == "or":
        return [x for x in expr[1:] if isinstance(x, str)]
    if isinstance(expr, (list, tuple)) and expr and str(expr[0]).lower() == "and":
        for child in expr[1:]:
            if isinstance(child, (list, tuple)) and child and str(child[0]).lower() == "or":
                return [x for x in child[1:] if isinstance(x, str)]
    return []


def _recipe_not_gates(expr):
    """顶层 / and 直接子节点里的 ["not", leaf]。不进 or、不做通用遍历。"""
    out = []
    if not isinstance(expr, (list, tuple)) or not expr:
        return out
    op = str(expr[0] or "").lower()
    if op == "not":
        child = expr[1] if len(expr) > 1 else None
        if isinstance(child, str) and child:
            out.append(child)
        return out
    if op != "and":
        return out
    for child in expr[1:]:
        if isinstance(child, (list, tuple)) and child and str(child[0]).lower() == "not":
            leaf = child[1] if len(child) > 1 else None
            if isinstance(leaf, str) and leaf:
                out.append(leaf)
    return out


def _pending_gate_hit(ctx, add):
    """只复评槽里的 not 闸门，不要求信号叶子仍为真（pending 粘性）。
    开仓走 RECIPE_ENTRY，加仓走 RECIPE_SCALE_IN。失败 (False, [skip码])。"""
    expr = globals().get("RECIPE_SCALE_IN" if add else "RECIPE_ENTRY")
    for fid in _recipe_not_gates(expr):
        ok, reasons, _d = _hit(["not", fid], ctx)
        if not ok:
            why = reasons[0] if reasons else _factor_skip_reason(fid)
            return False, [why]
    return True, []


def _eval_entry_slot(ctx):
    expr = globals().get("RECIPE_ENTRY")
    hit, reasons, detail = _hit(expr, ctx)
    skip = _factor_gate_reasons()
    real = [r for r in reasons if r not in skip]
    return bool(hit and real), reasons, real, detail


def _eval_scale_in_slot(ctx):
    expr = globals().get("RECIPE_SCALE_IN")
    hit, reasons, _detail = _hit(expr, ctx)
    leaves = _or_leaves(expr)
    gates = _factor_gate_reasons()
    push = []
    if leaves:
        for fid in leaves:
            ok, rs, _d = _hit(fid, ctx)
            if ok:
                for r in rs:
                    if r not in push:
                        push.append(r)
    else:
        for r in reasons:
            if r and r not in gates and r not in push:
                push.append(r)
    return bool(hit), push


def _eval_scale_out_slot(ctx):
    expr = globals().get("RECIPE_SCALE_OUT")
    if _recipe_off(expr):
        return False, []
    hit, reasons, _d = _hit(expr, ctx)
    return bool(hit), reasons


def _eval_lot_exits_recipe(ctx, lots, force_empty):
    """按 RECIPE_EXITS 有序列表评每笔。返回 (ok, reasons, lot_ids, shares, hooks)。"""
    if not lots:
        return False, [], [], 0, []
    if force_empty:
        lot_ids = [int(l.get("id") or 0) for l in lots]
        shares = sum(int(l.get("shares") or 0) for l in lots)
        return True, ["weekly_bear"], lot_ids, shares, []
    exits = []
    hooks = []
    order = list(globals().get("RECIPE_EXITS") or ())
    for lot in lots:
        sub = _ctx_with_lot(ctx, lot)
        hit_reasons = []
        for fid in order:
            ok, rs, _d = _hit(fid, sub)
            hook = sub.get("_tf_hook")
            if hook is not None:
                hooks.append(hook)
                sub["_tf_hook"] = None
            if ok:
                hit_reasons = list(rs) if rs else [fid]
                break
        if hit_reasons:
            exits.append((lot, hit_reasons))
    if not exits:
        return False, [], [], 0, hooks
    lot_ids = [int(item[0].get("id") or 0) for item in exits]
    shares = sum(int(item[0].get("shares") or 0) for item in exits)
    reasons = []
    for _lot, rs in exits:
        for r in rs:
            if r not in reasons:
                reasons.append(r)
    return True, reasons, lot_ids, shares, hooks


def _apply_tf_hooks(hooks):
    for hook in hooks or ():
        if hook is None:
            continue
        _time_force_mark_skip(*hook)
