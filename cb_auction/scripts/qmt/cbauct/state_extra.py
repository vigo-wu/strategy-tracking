# === cbauct/state_extra.py ===
def _state_extra_load(raw):
    A.buy_done_day = str(raw.get("buy_done_day", "") or "")
    A.sell_hint_day = str(raw.get("sell_hint_day", "") or "")
    A.sim_sell_day = str(raw.get("sim_sell_day", "") or "")


def _state_extra_save(data):
    data["buy_done_day"] = str(getattr(A, "buy_done_day", "") or "")
    data["sell_hint_day"] = str(getattr(A, "sell_hint_day", "") or "")
    data["sim_sell_day"] = str(getattr(A, "sim_sell_day", "") or "")
