# === hlband/factors/expr.py ===
def _recipe_off(expr):
    if expr is None or expr is False:
        return True
    if isinstance(expr, (list, tuple)) and len(expr) == 0:
        return True
    if isinstance(expr, str) and not str(expr).strip():
        return True
    return False


def _hit(expr, ctx):
    """求值布尔式。返回 (hit, reasons, detail)。
    and 短路（对齐现网 chase/vol_dry 先返回）；or 收集全部命中叶子。"""
    if _recipe_off(expr):
        return False, [], {}
    if isinstance(expr, str):
        fid = str(expr)
        spec = FACTORS.get(fid)
        if spec is None or not callable(spec.get("eval")):
            raise ValueError("unknown factor %s" % fid)
        ok, detail = spec["eval"](ctx)
        detail = detail if isinstance(detail, dict) else {}
        if ok:
            return True, [fid], detail
        return False, [], detail
    if not isinstance(expr, (list, tuple)) or not expr:
        return False, [], {}
    op = str(expr[0] or "").lower()
    args = list(expr[1:])
    if op == "not":
        if not args:
            return True, [], {}
        child = args[0]
        ok, reasons, detail = _hit(child, ctx)
        if ok:
            if isinstance(child, str):
                return False, [_factor_skip_reason(child)], detail
            return False, reasons, detail
        return True, [], detail
    if op == "and":
        acc_detail = {}
        for child in args:
            ok, reasons, detail = _hit(child, ctx)
            if isinstance(detail, dict):
                acc_detail.update(detail)
            if not ok:
                return False, reasons, acc_detail
        leaves = []
        for child in args:
            if isinstance(child, str):
                leaves.append(child)
        return True, leaves, acc_detail
    if op == "or":
        acc_reasons = []
        acc_detail = {}
        any_ok = False
        for child in args:
            ok, reasons, detail = _hit(child, ctx)
            if isinstance(detail, dict):
                acc_detail.update(detail)
            if ok:
                any_ok = True
                for r in reasons:
                    if r not in acc_reasons:
                        acc_reasons.append(r)
        return any_ok, acc_reasons, acc_detail
    raise ValueError("unknown recipe op %s" % op)
