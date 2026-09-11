# === hlband/factors/intent.py ===
def _active_lots():
    lots = []
    for lot in getattr(A, "lots", None) or []:
        if not isinstance(lot, dict):
            continue
        try:
            sh = int(lot.get("shares") or 0)
        except Exception:
            sh = 0
        if sh > 0:
            lots.append(lot)
    return lots


def _pick_scale_out_lot(lots):
    if not lots:
        return None
    mode = str(globals().get("SCALE_OUT_LOT") or "last").strip().lower()
    if mode == "first":
        return lots[0]
    return lots[-1]


def _resolve_intent(
    holding,
    force_empty,
    skip_sell,
    sell_ok,
    sell_reasons,
    exit_ids,
    exit_shares,
    scale_out_hit,
    scale_out_reasons,
    scale_in_hit,
    scale_in_reasons,
    scale_ok,
    entry_hit,
    entry_real,
):
    """纯数据 Intent。不写 pending、不碰 budget。"""
    intent = {
        "target": None,
        "sell_all": False,
        "reason": "",
        "reasons": [],
        "lot_ids": [],
        "shares": 0,
        "add": False,
    }
    if skip_sell:
        force_empty = False
        sell_ok = False
        scale_out_hit = False
    if holding and force_empty and bool(globals().get("RECIPE_EXIT_WEEKLY_BEAR", True)):
        lots = _active_lots()
        lot_ids = [int(l.get("id") or 0) for l in lots] if lots else list(exit_ids or [])
        shares = sum(int(l.get("shares") or 0) for l in lots) if lots else int(exit_shares or 0)
        intent.update(
            {
                "target": "flat",
                "sell_all": True,
                "reason": "weekly_bear",
                "reasons": ["weekly_bear"],
                "lot_ids": lot_ids,
                "shares": shares,
            }
        )
        return intent
    if holding and sell_ok:
        reasons = [r for r in (sell_reasons or []) if r and r != "skip_add_bar"]
        reason = reasons[0] if reasons else "SELL"
        intent.update(
            {
                "target": "flat",
                "sell_all": False,
                "reason": reason,
                "reasons": reasons,
                "lot_ids": list(exit_ids or []),
                "shares": int(exit_shares or 0),
            }
        )
        return intent
    if holding and scale_out_hit:
        lots = _active_lots()
        if len(lots) >= 2:
            picked = _pick_scale_out_lot(lots)
            if picked is not None:
                lid = int(picked.get("id") or 0)
                sh = int(picked.get("shares") or 0)
                rs = list(scale_out_reasons or []) or ["scale_out"]
                intent.update(
                    {
                        "target": "reduce",
                        "sell_all": False,
                        "reason": rs[0],
                        "reasons": rs,
                        "lot_ids": [lid],
                        "shares": sh,
                    }
                )
                return intent
    if holding and scale_in_hit and scale_ok:
        rs = list(scale_in_reasons or [])
        intent.update(
            {
                "target": "add",
                "add": True,
                "reason": rs[0] if rs else "entry",
                "reasons": rs,
            }
        )
        return intent
    if (not holding) and entry_hit:
        rs = list(entry_real or [])
        intent.update(
            {
                "target": "open",
                "add": False,
                "reason": rs[0] if rs else "entry",
                "reasons": rs,
            }
        )
        return intent
    return intent
