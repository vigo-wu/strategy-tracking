# === hlband/factors/expr.py ===
def _recipe_hit(expr, ctx):
    """hit(and/or/not)；叶子 = 因子 id。False/None = 恒假。"""
    if expr is False or expr is None:
        return False, []
    if expr is True:
        return True, []
    if isinstance(expr, str):
        ok, _detail = _factor_eval(expr, ctx)
        return bool(ok), [expr] if ok else []
    if not isinstance(expr, (list, tuple)) or not expr:
        return False, []
    op = expr[0]
    if op == "not":
        if len(expr) < 2:
            return False, []
        ok, _rs = _recipe_hit(expr[1], ctx)
        return (not ok), []
    if op == "and":
        reasons = []
        for node in expr[1:]:
            ok, rs = _recipe_hit(node, ctx)
            if not ok:
                return False, []
            reasons.extend(rs)
        return True, reasons
    if op == "or":
        for node in expr[1:]:
            ok, rs = _recipe_hit(node, ctx)
            if ok:
                return True, rs
        return False, []
    ok, _detail = _factor_eval(op, ctx)
    return bool(ok), [op] if ok else []


def _recipe_block_reasons(expr, ctx):
    """未命中时第一个挡住的叶子。["not","chase"] 失败 → chase。"""
    if expr is False or expr is None or expr is True:
        return []
    if isinstance(expr, str):
        ok, _detail = _factor_eval(expr, ctx)
        return [] if ok else [expr]
    if not isinstance(expr, (list, tuple)) or not expr:
        return []
    op = expr[0]
    if op == "not":
        if len(expr) < 2:
            return []
        inner = expr[1]
        ok, rs = _recipe_hit(inner, ctx)
        if not ok:
            return []
        if isinstance(inner, str):
            return [inner]
        return list(rs) if rs else []
    if op == "and":
        for node in expr[1:]:
            ok, _rs = _recipe_hit(node, ctx)
            if not ok:
                return _recipe_block_reasons(node, ctx)
        return []
    if op == "or":
        for node in expr[1:]:
            rs = _recipe_block_reasons(node, ctx)
            if rs:
                return rs
        return []
    ok, _detail = _factor_eval(op, ctx)
    return [] if ok else [op]


def _recipe_explain(expr, ctx):
    """命中用 _recipe_hit 的 reasons；未命中用第一个挡住的叶子。"""
    hit, reasons = _recipe_hit(expr, ctx)
    if hit:
        return True, reasons
    return False, _recipe_block_reasons(expr, ctx)


def _recipe_not_leaves(expr):
    """顶层 and 下的 ["not", leaf] 叶子 id。不走进 or 子树。"""
    if not isinstance(expr, (list, tuple)) or not expr:
        return []
    if expr[0] == "and":
        out = []
        for node in expr[1:]:
            if (
                isinstance(node, (list, tuple))
                and len(node) >= 2
                and node[0] == "not"
                and isinstance(node[1], str)
            ):
                out.append(node[1])
        return out
    if expr[0] == "not" and len(expr) >= 2 and isinstance(expr[1], str):
        return [expr[1]]
    return []
