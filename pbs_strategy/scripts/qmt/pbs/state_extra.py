# === pbs/state_extra.py ===
def _state_extra_load(raw):
    A.buy_done_day = str(raw.get("buy_done_day", "") or "")
    A.entry_mode = str(raw.get("entry_mode", "") or "")


def _state_extra_save(data):
    data["buy_done_day"] = str(getattr(A, "buy_done_day", "") or "")
    data["entry_mode"] = str(getattr(A, "entry_mode", "") or "")
