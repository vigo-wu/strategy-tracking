# === ma15/state_extra.py ===
def _state_extra_load(raw):
    pe = raw.get("pending_entry")
    A.pending_entry = pe if isinstance(pe, dict) else None
    px = raw.get("pending_exit")
    A.pending_exit = px if isinstance(px, dict) else None
    peak = raw.get("hold_peak")
    try:
        A.hold_peak = float(peak) if peak is not None else None
    except Exception:
        A.hold_peak = None
    cp = raw.get("hold_close_peak")
    try:
        A.hold_close_peak = float(cp) if cp is not None else None
    except Exception:
        A.hold_close_peak = None
    try:
        A.hold_bars = int(raw.get("hold_bars", 0) or 0)
    except Exception:
        A.hold_bars = 0
    A._hold_count_bar = str(raw.get("hold_count_bar", "") or "")
    try:
        A.hold_max_ret = float(raw.get("hold_max_ret", 0) or 0)
    except Exception:
        A.hold_max_ret = 0.0
    A._eval_bar_tag = str(raw.get("eval_bar_tag", "") or "")
    A.stall_cool_day = str(raw.get("stall_cool_day", "") or "")


def _state_extra_save(data):
    data["pending_entry"] = getattr(A, "pending_entry", None)
    data["pending_exit"] = getattr(A, "pending_exit", None)
    peak = getattr(A, "hold_peak", None)
    data["hold_peak"] = None if peak is None else float(peak)
    cp = getattr(A, "hold_close_peak", None)
    data["hold_close_peak"] = None if cp is None else float(cp)
    data["hold_bars"] = int(getattr(A, "hold_bars", 0) or 0)
    data["hold_count_bar"] = str(getattr(A, "_hold_count_bar", "") or "")
    data["hold_max_ret"] = float(getattr(A, "hold_max_ret", 0) or 0)
    data["eval_bar_tag"] = str(getattr(A, "_eval_bar_tag", "") or "")
    data["stall_cool_day"] = str(getattr(A, "stall_cool_day", "") or "")
