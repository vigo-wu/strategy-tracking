# === hwr/helpers.py ===
def _entry_date():
    if not _has_position():
        return None
    ot = _parse_opened_at(A.position.get("opened_at"))
    if ot is None:
        return None
    return ot.date()
