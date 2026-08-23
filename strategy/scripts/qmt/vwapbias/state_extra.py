# === vwapbias/state_extra.py ===
def _state_extra_load(raw):
    A.acted_closed = str(raw.get("acted_closed", "") or "")
    A.risk_skip_day = str(raw.get("risk_skip_day", "") or "")
    A.scale_out_lock = bool(raw.get("scale_out_lock", False))
    pk = raw.get("hold_peak_ret", None)
    try:
        A.hold_peak_ret = float(pk) if pk is not None and pk != "" else None
    except Exception:
        A.hold_peak_ret = None


def _state_extra_save(data):
    data["acted_closed"] = str(getattr(A, "acted_closed", "") or "")
    data["risk_skip_day"] = str(getattr(A, "risk_skip_day", "") or "")
    data["scale_out_lock"] = bool(getattr(A, "scale_out_lock", False))
    pk = getattr(A, "hold_peak_ret", None)
    data["hold_peak_ret"] = None if pk is None else float(pk)
