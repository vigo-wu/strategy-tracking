# === hlband/factors/intent.py ===
def _intent_blank():
    return {
        "side": None,
        "target": None,
        "lot_ids": None,
        "frac": None,
        "reasons": [],
        "shares": 0,
    }


def _intent_pack(side, target, reasons=None, lot_ids=None, frac=None, shares=0):
    return {
        "side": side,
        "target": target,
        "lot_ids": list(lot_ids) if lot_ids else None,
        "frac": frac,
        "reasons": list(reasons or []),
        "shares": int(shares or 0),
    }


def _arbitrate_intent(
    entry=None,
    scale_in=None,
    exit_slot=None,
    scale_out=None,
    scale_gate_ok=False,
    holding=False,
    lot_ids=None,
    shares=0,
):
    """仓位仲裁。优先级写死：flat > reduce > add > open。"""
    entry = entry or {}
    scale_in = scale_in or {}
    exit_slot = exit_slot or {}
    scale_out = scale_out or {}
    if holding and exit_slot.get("hit"):
        return _intent_pack(
            "sell",
            "flat",
            exit_slot.get("reasons"),
            lot_ids,
            shares=shares,
        )
    if holding and scale_out.get("hit"):
        return _intent_pack(
            "sell",
            "reduce",
            scale_out.get("reasons"),
            lot_ids,
            frac=scale_out.get("frac"),
            shares=shares,
        )
    if holding and scale_in.get("hit") and scale_gate_ok:
        return _intent_pack("buy", "add", scale_in.get("reasons") or scale_in.get("triggers"))
    if (not holding) and entry.get("hit"):
        return _intent_pack("buy", "open", entry.get("reasons"))
    return _intent_blank()
