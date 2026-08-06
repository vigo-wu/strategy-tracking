# === hlband/state_extra.py ===
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
    try:
        A.hold_bars = int(raw.get("hold_bars", 0) or 0)
    except Exception:
        A.hold_bars = 0
    A._hold_count_day = str(raw.get("hold_count_day", "") or "")


def _state_extra_save(data):
    data["pending_entry"] = getattr(A, "pending_entry", None)
    data["pending_exit"] = getattr(A, "pending_exit", None)
    peak = getattr(A, "hold_peak", None)
    data["hold_peak"] = None if peak is None else float(peak)
    data["hold_bars"] = int(getattr(A, "hold_bars", 0) or 0)
    data["hold_count_day"] = str(getattr(A, "_hold_count_day", "") or "")
