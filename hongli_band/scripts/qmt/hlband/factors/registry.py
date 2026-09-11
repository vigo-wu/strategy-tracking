# === hlband/factors/registry.py ===
FACTORS = {}
FACTOR_SKIP_REASON = {
    "chase": "chase_skip",
    "vol_dry": "vol_dry_skip",
    "w_bias": "w_bias_skip",
    "w_slope": "w_slope_skip",
    "weekly_bear": "weekly_bear",
}


def _register_factor(fid, eval_fn, skip_reason=None, kind="signal"):
    """kind 不是槽归属：gate 只表示 not 失败时的 skip 码要从入场 real 里剔除。"""
    fid = str(fid or "")
    if not fid:
        return
    k = str(kind or "signal").strip().lower()
    if k not in ("gate", "signal"):
        k = "signal"
    FACTORS[fid] = {
        "eval": eval_fn,
        "skip_reason": str(skip_reason or FACTOR_SKIP_REASON.get(fid) or fid),
        "kind": k,
    }


def _factor_skip_reason(fid):
    spec = FACTORS.get(str(fid or ""))
    if spec:
        return str(spec.get("skip_reason") or fid)
    return str(FACTOR_SKIP_REASON.get(fid) or fid)


def _factor_gate_reasons():
    out = set()
    for spec in FACTORS.values():
        if not isinstance(spec, dict):
            continue
        if str(spec.get("kind") or "signal") != "gate":
            continue
        sr = str(spec.get("skip_reason") or "")
        if sr:
            out.add(sr)
    return out
