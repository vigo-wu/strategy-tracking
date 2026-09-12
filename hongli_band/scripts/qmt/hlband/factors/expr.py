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
