# === hlband/factors/registry.py ===
def _factor_registry():
    out = {}
    missing = []
    leaves = globals().get("LEAVES") or {}
    for fid in leaves:
        key = str(fid)
        fn = globals().get("_factor_eval_" + key)
        if callable(fn):
            out[key] = fn
        else:
            missing.append(key)
    if missing:
        raise RuntimeError("LEAVES 缺 _factor_eval_: %s" % ",".join(missing))
    return out


_factor_registry()


def _factor_eval(fid, ctx):
    fn = _factor_registry().get(str(fid or ""))
    if fn is None:
        return False, {}
    ok, detail = fn(ctx)
    return bool(ok), detail or {}


def _factor_hit(fid, ctx):
    ok, _detail = _factor_eval(fid, ctx)
    return bool(ok)
