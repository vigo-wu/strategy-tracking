# === pbs/state_extra.py ===
def _state_extra_load(raw):
    A.buy_done_day = str(raw.get("buy_done_day", "") or "")
    A.am_buy_day = str(raw.get("am_buy_day", "") or "")
    A.sz_preplace_day = str(raw.get("sz_preplace_day", "") or "")
    A.sz_close_buy_day = str(raw.get("sz_close_buy_day", "") or "")
    A.sz_escalate_day = str(raw.get("sz_escalate_day", "") or "")
    A.sz_escalate_alert_ms = float(raw.get("sz_escalate_alert_ms", 0) or 0)
    A.sh_chase_day = str(raw.get("sh_chase_day", "") or "")
    A.sh_last_order_px = float(raw.get("sh_last_order_px", 0) or 0)
    A.sh_chase_at_ms = float(raw.get("sh_chase_at_ms", 0) or 0)
    A.entry_mode = str(raw.get("entry_mode", "") or "")


def _state_extra_save(data):
    data["buy_done_day"] = str(getattr(A, "buy_done_day", "") or "")
    data["am_buy_day"] = str(getattr(A, "am_buy_day", "") or "")
    data["sz_preplace_day"] = str(getattr(A, "sz_preplace_day", "") or "")
    data["sz_close_buy_day"] = str(getattr(A, "sz_close_buy_day", "") or "")
    data["sz_escalate_day"] = str(getattr(A, "sz_escalate_day", "") or "")
    data["sz_escalate_alert_ms"] = float(getattr(A, "sz_escalate_alert_ms", 0) or 0)
    data["sh_chase_day"] = str(getattr(A, "sh_chase_day", "") or "")
    data["sh_last_order_px"] = float(getattr(A, "sh_last_order_px", 0) or 0)
    data["sh_chase_at_ms"] = float(getattr(A, "sh_chase_at_ms", 0) or 0)
    data["entry_mode"] = str(getattr(A, "entry_mode", "") or "")
