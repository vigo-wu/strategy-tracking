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
    gu = raw.get("time_force_grace_until")
    try:
        A.time_force_grace_until = None if gu is None else int(gu)
    except Exception:
        A.time_force_grace_until = None
    A.time_force_trend_skip = bool(raw.get("time_force_trend_skip"))
    A._confirmed_eval_day = str(raw.get("confirmed_eval_day", "") or "")
    A._fallback_done_day = str(raw.get("fallback_done_day", "") or "")
    try:
        A._w_bear_streak = int(raw.get("w_bear_streak", 0) or 0)
    except Exception:
        A._w_bear_streak = 0
    A._w_bear_last_day = str(raw.get("w_bear_last_day", "") or "")
    A.round_scaled = bool(raw.get("round_scaled"))
    A._skip_sell_eval_day = str(raw.get("skip_sell_eval_day", "") or "")
    A._last_add_day = str(raw.get("last_add_day", "") or "")
    A._last_add_signal = str(raw.get("last_add_signal", "") or "")


def _state_extra_save(data):
    data["pending_entry"] = getattr(A, "pending_entry", None)
    data["pending_exit"] = getattr(A, "pending_exit", None)
    peak = getattr(A, "hold_peak", None)
    data["hold_peak"] = None if peak is None else float(peak)
    data["hold_bars"] = int(getattr(A, "hold_bars", 0) or 0)
    data["hold_count_day"] = str(getattr(A, "_hold_count_day", "") or "")
    gu = getattr(A, "time_force_grace_until", None)
    data["time_force_grace_until"] = None if gu is None else int(gu)
    data["time_force_trend_skip"] = bool(getattr(A, "time_force_trend_skip", False))
    data["confirmed_eval_day"] = str(getattr(A, "_confirmed_eval_day", "") or "")
    data["fallback_done_day"] = str(getattr(A, "_fallback_done_day", "") or "")
    data["w_bear_streak"] = int(getattr(A, "_w_bear_streak", 0) or 0)
    data["w_bear_last_day"] = str(getattr(A, "_w_bear_last_day", "") or "")
    data["round_scaled"] = bool(getattr(A, "round_scaled", False))
    data["skip_sell_eval_day"] = str(getattr(A, "_skip_sell_eval_day", "") or "")
    data["last_add_day"] = str(getattr(A, "_last_add_day", "") or "")
    data["last_add_signal"] = str(getattr(A, "_last_add_signal", "") or "")
