# === qmt_common/single/lots.py ===
# 作用: 同一标的多笔独立仓（SCALE_LOTS）；A.position 仍是合计，供经纪/T+1
# 主要符号: _lots_enabled, _ensure_lots, _pos_lots, _lots_on_buy_fill,
#           _lots_on_sell_fill, _order_sell(lot_ids=)
# 默认关：未设 SCALE_LOTS 时一票一仓，行为与无本片段时相同
# 策略可在 lot 字典上挂 hold_peak 等字段；本模块原样保留
def _lots_enabled():
    return bool(globals().get("SCALE_LOTS", False))


def _scale_lots():
    """兼容旧策略名；与 _lots_enabled 相同。"""
    return _lots_enabled()


def _lot_from_agg():
    pos = getattr(A, "position", None) or {}
    px = float(pos.get("price", 0) or 0)
    peak = getattr(A, "hold_peak", None)
    cp = getattr(A, "hold_close_peak", None)
    if peak is None:
        peak = px
    if cp is None:
        cp = px
    return {
        "id": 1,
        "shares": int(pos.get("shares", 0) or 0),
        "price": px,
        "opened_at": str(pos.get("opened_at", "") or ""),
        "hold_peak": peak,
        "hold_close_peak": cp,
        "hold_max_ret": float(getattr(A, "hold_max_ret", 0) or 0),
        "hold_bars": int(getattr(A, "hold_bars", 0) or 0),
        "hold_count_bar": str(getattr(A, "_hold_count_bar", "") or ""),
    }


def _ensure_lots():
    lots = getattr(A, "lots", None)
    cleaned = []
    if isinstance(lots, list):
        for lot in lots:
            if isinstance(lot, dict) and int(lot.get("shares", 0) or 0) >= _vol_step():
                cleaned.append(lot)
    if cleaned:
        A.lots = cleaned
        return cleaned
    if _has_position():
        A.lots = [_lot_from_agg()]
        return A.lots
    A.lots = []
    return A.lots


def _next_lot_id():
    mx = 0
    for lot in getattr(A, "lots", None) or []:
        try:
            mx = max(mx, int(lot.get("id") or 0))
        except Exception:
            pass
    return mx + 1


def _new_lot(shares, price, opened_at=""):
    px = float(price) if price else 0.0
    ot = str(opened_at or "")
    if not ot:
        pos = getattr(A, "position", None)
        if isinstance(pos, dict):
            ot = str(pos.get("opened_at") or "")
    if not ot:
        ot = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return {
        "id": _next_lot_id(),
        "shares": int(shares),
        "price": px,
        "opened_at": ot,
        "hold_peak": px,
        "hold_close_peak": px,
        "hold_max_ret": 0.0,
        "hold_bars": 0,
        "hold_count_bar": "",
    }


def _sync_position_from_lots():
    lots = []
    for lot in getattr(A, "lots", None) or []:
        if isinstance(lot, dict) and int(lot.get("shares", 0) or 0) >= _vol_step():
            lots.append(lot)
    A.lots = lots
    if not lots:
        A.position = None
        return
    total = 0
    cost_sum = 0.0
    ot = ""
    for lot in lots:
        sh = int(lot.get("shares") or 0)
        px = float(lot.get("price") or 0)
        total += sh
        cost_sum += sh * px
        if not ot:
            ot = str(lot.get("opened_at") or "")
    avg = (cost_sum / float(total)) if total else 0.0
    A.position = {
        "shares": int(total),
        "price": float(avg),
        "cost": round(total * avg, 2),
        "opened_at": ot,
        "lots": len(lots),
    }
    if getattr(A, "is_backtest", False):
        held = _bt_held_vol()
        if held < _vol_step() and total >= _vol_step():
            print(_strategy_tag(), "restore bt_held from lots", total)
            A.bt_held = total
        elif held != total:
            print(
                _strategy_tag(),
                "lots vs bt_held mismatch lots=",
                total,
                "held=",
                held,
            )


def _mirror_hold_from_lots():
    lots = getattr(A, "lots", None) or []
    if not lots:
        A.hold_peak = None
        A.hold_close_peak = None
        A.hold_max_ret = 0.0
        A.hold_bars = 0
        A._hold_count_bar = ""
        return
    lot = lots[0]
    A.hold_peak = lot.get("hold_peak")
    A.hold_close_peak = lot.get("hold_close_peak")
    A.hold_max_ret = float(lot.get("hold_max_ret") or 0)
    A.hold_bars = int(lot.get("hold_bars") or 0)
    A._hold_count_bar = str(lot.get("hold_count_bar") or "")


def _bump_lot_bars(lot, bar_tag):
    if str(lot.get("hold_count_bar") or "") == str(bar_tag):
        return False
    lot["hold_bars"] = int(lot.get("hold_bars") or 0) + 1
    lot["hold_count_bar"] = str(bar_tag)
    return True


def _update_lot_peaks(lot, high_px, close_px):
    hi = float(high_px)
    cl = float(close_px)
    cost = float(lot.get("price") or 0)
    changed = False
    peak = lot.get("hold_peak")
    if peak is None:
        base = cost if cost > 0 else hi
        lot["hold_peak"] = max(base, hi)
        changed = True
    elif hi > float(peak):
        lot["hold_peak"] = hi
        changed = True
    cp = lot.get("hold_close_peak")
    if cp is None:
        lot["hold_close_peak"] = cl
        changed = True
    elif cl > float(cp):
        lot["hold_close_peak"] = cl
        changed = True
    if cost > 0:
        mx = max((cl - cost) / cost, (hi - cost) / cost)
        prev = lot.get("hold_max_ret")
        try:
            prev_f = float(prev) if prev is not None else None
        except Exception:
            prev_f = None
        if prev_f is None or mx > prev_f:
            lot["hold_max_ret"] = mx
            changed = True
    return changed


def _pos_lots():
    if _lots_enabled():
        return len(_ensure_lots())
    pos = getattr(A, "position", None)
    if not isinstance(pos, dict):
        return 0
    try:
        return max(1, int(pos.get("lots", 1) or 1))
    except Exception:
        return 1


def _lots_want_vol(lot_ids):
    if not lot_ids:
        return None
    try:
        idset = set(int(x) for x in lot_ids)
    except Exception:
        return None
    total = 0
    for lot in getattr(A, "lots", None) or []:
        try:
            if int(lot.get("id") or 0) in idset:
                total += int(lot.get("shares") or 0)
        except Exception:
            pass
    if total < _vol_step():
        return None
    return int(total)


def _exit_is_partial(lot_ids):
    if (not _lots_enabled()) or (not lot_ids):
        return False
    try:
        idset = set(int(x) for x in lot_ids)
    except Exception:
        return False
    for lot in _ensure_lots():
        try:
            if int(lot.get("id") or 0) not in idset:
                return True
        except Exception:
            pass
    return False


def _lots_on_buy_fill(px, add=False, vol=None, opened_at=""):
    if not _lots_enabled():
        return
    if vol is None:
        total = _pos_shares()
        if getattr(A, "is_backtest", False):
            total = max(total, _bt_held_vol())
        have = 0
        if add:
            for lot in getattr(A, "lots", None) or []:
                try:
                    have += int(lot.get("shares") or 0)
                except Exception:
                    pass
        vol = total if not add else (total - have)
    vol = int(vol or 0)
    if not add:
        A.lots = []
    elif not (getattr(A, "lots", None) or []):
        A.lots = [_lot_from_agg()]
        _sync_position_from_lots()
        _mirror_hold_from_lots()
        return
    if vol < _vol_step():
        if add and not (getattr(A, "lots", None) or []):
            A.lots = [_lot_from_agg()]
        _sync_position_from_lots()
        _mirror_hold_from_lots()
        return
    A.lots.append(_new_lot(vol, px, opened_at))
    _sync_position_from_lots()
    _mirror_hold_from_lots()
    print(_strategy_tag(), "lots now n=%s" % len(A.lots), A.lots)
    _event_log("lots_update", action="buy", add=add, lots=A.lots)


def _lots_on_sell_fill(lot_ids, filled_vol):
    if not _lots_enabled():
        return
    lots = list(getattr(A, "lots", None) or [])
    if not lots:
        return
    remain_fill = int(filled_vol or 0)
    idset = None
    if lot_ids:
        try:
            idset = set(int(x) for x in lot_ids)
        except Exception:
            idset = None
    new_lots = []
    for lot in lots:
        try:
            lid = int(lot.get("id") or 0)
        except Exception:
            lid = 0
        if idset is not None and lid not in idset:
            new_lots.append(lot)
            continue
        if remain_fill < _vol_step():
            new_lots.append(lot)
            continue
        sh = int(lot.get("shares") or 0)
        if sh <= remain_fill:
            remain_fill -= sh
        else:
            lot = dict(lot)
            lot["shares"] = sh - remain_fill
            remain_fill = 0
            new_lots.append(lot)
    A.lots = new_lots
    _sync_position_from_lots()
    _mirror_hold_from_lots()
    print(_strategy_tag(), "lots now n=%s" % len(A.lots), A.lots)
    _event_log("lots_update", action="sell", lot_ids=lot_ids, lots=A.lots)


def _heartbeat_extra():
    lots = getattr(A, "lots", None) or []
    if not lots:
        return ""
    bits = []
    for lot in lots:
        try:
            bits.append(
                "L%s:%s@%.4f"
                % (lot.get("id"), lot.get("shares"), float(lot.get("price") or 0))
            )
        except Exception:
            pass
    return "lots=" + ",".join(bits)
