# === qmt_common/single/ex_rights.py ===
# 作用: 持仓过除权除息时缩放 cost/peak/股数，避免 trail/止损被跳空误触发
# 主要符号: _maybe_apply_ex_rights, _clear_ex_rights_state
# 因子: C.get_divid_factors → [红利, 送, 转, 配, 配股价, 股改, dr]
# 配股默认未认购（股数不含 allot）；实盘 pending 延后用券商量判定认购
_EX_ADJUSTED_DIV = (
    "follow",
    "front",
    "back",
    "front_ratio",
    "back_ratio",
)
_EX_ALLOT_TIMEOUT_DAYS = 30
_EX_LOT = 100


def _clear_ex_rights_state():
    A.ex_rights_applied = []
    A.ex_rights_allot_pending = []


def _ex_applied_list():
    raw = getattr(A, "ex_rights_applied", None)
    if not isinstance(raw, list):
        A.ex_rights_applied = []
        return A.ex_rights_applied
    return raw


def _ex_allot_pending_list():
    raw = getattr(A, "ex_rights_allot_pending", None)
    if not isinstance(raw, list):
        A.ex_rights_allot_pending = []
        return A.ex_rights_allot_pending
    return raw


def _ex_day_from_key(key):
    """除权 dict key（ms/秒时间戳或可解析串）→ YYYYMMDD（东八区日历日）。"""
    norm = globals().get("_norm_bar_day")
    try:
        ms = int(float(key))
    except Exception:
        if callable(norm):
            return str(norm(key) or "")
        s = str(key or "").strip()
        return s[:8] if len(s) >= 8 and s[:8].isdigit() else ""
    if ms > 10**12:
        sec = ms / 1000.0
    elif ms > 10**9:
        sec = float(ms)
    else:
        if callable(norm):
            return str(norm(key) or "")
        return ""
    try:
        dt = datetime.datetime.utcfromtimestamp(sec) + datetime.timedelta(hours=8)
        return dt.strftime("%Y%m%d")
    except Exception:
        return ""


def _ex_open_day():
    days = []
    for lot in getattr(A, "lots", None) or []:
        if not isinstance(lot, dict):
            continue
        ot = str(lot.get("opened_at") or "")
        if len(ot) >= 8 and ot[:8].isdigit():
            days.append(ot[:8])
    pos = getattr(A, "position", None)
    if isinstance(pos, dict):
        ot = str(pos.get("opened_at") or "")
        if len(ot) >= 8 and ot[:8].isdigit():
            days.append(ot[:8])
    if not days:
        return ""
    return min(days)


def _ex_floor_lot(shares):
    """买卖手数对齐（向下）；除权送转股数不要用这个，会吞零股。"""
    try:
        n = int(round(float(shares)))
    except Exception:
        return 0
    if n < _EX_LOT:
        return 0
    return (n // _EX_LOT) * _EX_LOT


def _ex_round_shares(shares):
    """除权后股数：四舍五入到股，允许零股（送转常见）。"""
    try:
        n = int(round(float(shares)))
    except Exception:
        return 0
    return max(n, 0)


def _ex_parse_row(row):
    """→ dict interest/bonus/gift/allot/allot_px/dr；非法 None。"""
    if not isinstance(row, (list, tuple)) or len(row) < 7:
        return None
    try:
        interest = float(row[0] or 0)
        bonus = float(row[1] or 0)
        gift = float(row[2] or 0)
        allot = float(row[3] or 0)
        allot_px = float(row[4] or 0)
        dr = float(row[6] or 0)
    except Exception:
        return None
    return {
        "interest": interest,
        "bonus": bonus,
        "gift": gift,
        "allot": allot,
        "allot_px": allot_px,
        "dr": dr,
        "share_mul_base": 1.0 + bonus + gift,
        "share_mul_sub": 1.0 + bonus + gift + allot,
    }


def _ex_skip_adjusted_backtest():
    """回测且行情已是静态复权时跳过 STATE 缩放；PIT（none+因子）激活则不跳过。"""
    if not getattr(A, "is_backtest", False):
        return False
    if bool(getattr(A, "_pit_front_active", False)):
        return False
    fn = globals().get("_dividend_type")
    div = ""
    if callable(fn):
        try:
            div = str(fn() or "").strip().lower()
        except Exception:
            div = ""
    if not div:
        div = str(globals().get("DIVIDEND_TYPE") or "").strip().lower()
    if div in ("", "chart", "main"):
        div = "follow"
    return div in _EX_ADJUSTED_DIV


def _divid_factors_cached(C, stock):
    cache = getattr(A, "_divid_factors_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        A._divid_factors_cache = cache
    key = str(stock or "")
    if key in cache:
        return cache[key]
    out = {}
    try:
        raw = C.get_divid_factors(stock)
        if isinstance(raw, dict):
            out = raw
    except Exception as e:
        diag = globals().get("_diag_once")
        if callable(diag):
            diag("divid_factors_fail", e)
        out = {}
    cache[key] = out
    return out


def _divid_events_since(factors, open_day, applied, asof_day=""):
    """开仓日后未应用事件，按日升序 [(day, parsed), ...]。
    无 open_day 时只处理 asof_day 当日，避免空 applied 回放全部历史。"""
    applied_set = set(str(x) for x in (applied or []))
    asof = str(asof_day or "")
    items = []
    if not isinstance(factors, dict):
        return items
    for key, row in factors.items():
        day = _ex_day_from_key(key)
        if not day or day in applied_set:
            continue
        if open_day:
            if day < open_day:
                continue
        elif asof:
            if day != asof:
                continue
        else:
            continue
        if asof and day > asof:
            continue
        parsed = _ex_parse_row(row)
        if not parsed:
            continue
        items.append((day, parsed))
    items.sort(key=lambda x: x[0])
    return items


def _ex_scale_price_fields(dr):
    if dr is None or float(dr) <= 1.0:
        return False
    div = float(dr)
    changed = False

    def _div_one(val):
        if val is None:
            return None, False
        try:
            v = float(val)
        except Exception:
            return val, False
        if v <= 0:
            return val, False
        return v / div, True

    peak, ok = _div_one(getattr(A, "hold_peak", None))
    if ok:
        A.hold_peak = peak
        changed = True
    cp, ok = _div_one(getattr(A, "hold_close_peak", None))
    if ok:
        A.hold_close_peak = cp
        changed = True

    pos = getattr(A, "position", None)
    if isinstance(pos, dict):
        px, ok = _div_one(pos.get("price"))
        if ok:
            pos["price"] = px
            changed = True
        c2, ok = _div_one(pos.get("cost"))
        if ok and float(pos.get("shares") or 0) <= 0:
            pos["cost"] = c2
            changed = True
        elif float(pos.get("shares") or 0) >= _EX_LOT and float(pos.get("price") or 0) > 0:
            pos["cost"] = round(
                float(pos["shares"]) * float(pos["price"]), 2
            )

    for lot in getattr(A, "lots", None) or []:
        if not isinstance(lot, dict):
            continue
        for fld in ("price", "hold_peak", "hold_close_peak"):
            nv, ok = _div_one(lot.get(fld))
            if ok:
                lot[fld] = nv
                changed = True
    return changed


def _ex_scale_shares(share_mul):
    mul = float(share_mul)
    if abs(mul - 1.0) < 1e-12:
        return False
    changed = False
    lots = getattr(A, "lots", None) or []
    if lots and bool(globals().get("SCALE_LOTS", False)):
        for lot in lots:
            if not isinstance(lot, dict):
                continue
            old = int(lot.get("shares") or 0)
            new = _ex_round_shares(old * mul)
            if new != old:
                lot["shares"] = new
                changed = True
        sync = globals().get("_sync_position_from_lots")
        if callable(sync):
            sync()
            changed = True
    else:
        pos = getattr(A, "position", None)
        if isinstance(pos, dict):
            old = int(pos.get("shares") or 0)
            new = _ex_round_shares(old * mul)
            if new != old:
                pos["shares"] = new
                if float(pos.get("price") or 0) > 0:
                    pos["cost"] = round(new * float(pos["price"]), 2)
                changed = True
    if getattr(A, "is_backtest", False):
        for attr in ("bt_held", "bt_locked"):
            old = int(getattr(A, attr, 0) or 0)
            if old <= 0:
                continue
            new = _ex_round_shares(old * mul)
            if new != old:
                setattr(A, attr, new)
                changed = True
    return changed


def _ex_recompute_max_ret():
    lots = getattr(A, "lots", None) or []
    if lots and bool(globals().get("SCALE_LOTS", False)):
        for lot in lots:
            if not isinstance(lot, dict):
                continue
            cost = float(lot.get("price") or 0)
            peak = lot.get("hold_peak")
            if cost > 0 and peak is not None:
                try:
                    lot["hold_max_ret"] = (float(peak) - cost) / cost
                except Exception:
                    pass
        mir = globals().get("_mirror_hold_from_lots")
        if callable(mir):
            mir()
        return
    cost = 0.0
    pos = getattr(A, "position", None)
    if isinstance(pos, dict):
        cost = float(pos.get("price") or 0)
    peak = getattr(A, "hold_peak", None)
    if cost > 0 and peak is not None:
        try:
            A.hold_max_ret = (float(peak) - cost) / cost
        except Exception:
            pass


def _ex_cost_snapshot():
    """认购加权用：聚合价 + 各 lot 价。"""
    pos = getattr(A, "position", None)
    agg = float(pos.get("price") or 0) if isinstance(pos, dict) else 0.0
    lot_px = {}
    for lot in getattr(A, "lots", None) or []:
        if not isinstance(lot, dict):
            continue
        try:
            lid = int(lot.get("id") or 0)
        except Exception:
            continue
        lot_px[str(lid)] = float(lot.get("price") or 0)
    return {"agg": agg, "lots": lot_px}


def _ex_total_shares():
    """优先 lots 合计；lots 空或不足一手时回落 position（SCALE_LOTS 尚未 ensure 时）。"""
    if bool(globals().get("SCALE_LOTS", False)):
        total = 0
        for lot in getattr(A, "lots", None) or []:
            if isinstance(lot, dict):
                total += int(lot.get("shares") or 0)
        if total >= _EX_LOT:
            return int(total)
    pos = getattr(A, "position", None)
    if isinstance(pos, dict):
        return int(pos.get("shares") or 0)
    return 0


def _ex_ensure_lots():
    """SCALE_LOTS 时先从 position 重建 lots，避免除权读到空 lots。"""
    if not bool(globals().get("SCALE_LOTS", False)):
        return
    fn = globals().get("_ensure_lots")
    if callable(fn):
        try:
            fn()
        except Exception:
            pass


def _ex_set_total_shares(new_total):
    new_total = int(new_total)
    lots = [x for x in (getattr(A, "lots", None) or []) if isinstance(x, dict)]
    if lots and bool(globals().get("SCALE_LOTS", False)):
        old_total = sum(int(x.get("shares") or 0) for x in lots)
        if old_total <= 0:
            return False
        assigned = 0
        for i, lot in enumerate(lots):
            if i == len(lots) - 1:
                sh = max(new_total - assigned, 0)
            else:
                sh = _ex_round_shares(
                    new_total * int(lot.get("shares") or 0) / float(old_total)
                )
                assigned += sh
            lot["shares"] = max(sh, 0)
        sync = globals().get("_sync_position_from_lots")
        if callable(sync):
            sync()
        return True
    pos = getattr(A, "position", None)
    if isinstance(pos, dict):
        pos["shares"] = new_total
        if float(pos.get("price") or 0) > 0:
            pos["cost"] = round(new_total * float(pos["price"]), 2)
        return True
    return False


def _ex_apply_subscribe_cost(snap, interest, allot, allot_px, share_mul_sub):
    mul = float(share_mul_sub)
    if mul <= 0:
        return
    add = float(allot) * float(allot_px)
    interest = float(interest or 0)
    lots = getattr(A, "lots", None) or []
    lot_map = (snap or {}).get("lots") or {}
    if lots and bool(globals().get("SCALE_LOTS", False)):
        for lot in lots:
            if not isinstance(lot, dict):
                continue
            lid = str(int(lot.get("id") or 0))
            old = float(lot_map.get(lid, lot.get("price") or 0) or 0)
            lot["price"] = (old - interest + add) / mul
        sync = globals().get("_sync_position_from_lots")
        if callable(sync):
            sync()
    else:
        old = float((snap or {}).get("agg") or 0)
        pos = getattr(A, "position", None)
        if isinstance(pos, dict):
            pos["price"] = (old - interest + add) / mul
            sh = int(pos.get("shares") or 0)
            if sh >= _EX_LOT:
                pos["cost"] = round(sh * float(pos["price"]), 2)


def _ex_apply_one_event(day, parsed, live_pending):
    """应用单日除权（默认未认购）。返回 (changed, skipped_same_day)。"""
    open_day = _ex_open_day()
    if open_day and day == open_day:
        return False, True
    dr = float(parsed.get("dr") or 0)
    base_mul = float(parsed.get("share_mul_base") or 1.0)
    changed = False
    vol0 = _ex_total_shares()
    cost_snap = _ex_cost_snapshot()
    if dr > 1.0:
        if _ex_scale_price_fields(dr):
            changed = True
    if _ex_scale_shares(base_mul):
        changed = True
    _ex_recompute_max_ret()
    allot = float(parsed.get("allot") or 0)
    if live_pending and allot > 0 and vol0 >= _EX_LOT:
        pending = _ex_allot_pending_list()
        pending.append(
            {
                "day": str(day),
                "vol0": int(vol0),
                "share_mul_base": base_mul,
                "share_mul_sub": float(parsed.get("share_mul_sub") or 1.0),
                "interest": float(parsed.get("interest") or 0),
                "allot": allot,
                "allot_px": float(parsed.get("allot_px") or 0),
                "cost_snap": cost_snap,
            }
        )
        A.ex_rights_allot_pending = pending
        changed = True
    return changed, False


def _ex_natural_day_diff(day_a, day_b):
    try:
        a = datetime.datetime.strptime(str(day_a), "%Y%m%d")
        b = datetime.datetime.strptime(str(day_b), "%Y%m%d")
        return abs((b - a).days)
    except Exception:
        return 0


def _ex_check_allot_pending(day):
    """延后认购 / 超时。返回是否有变更。"""
    pending = list(_ex_allot_pending_list())
    if not pending:
        return False
    if getattr(A, "is_backtest", False):
        return False
    stock = str(getattr(A, "stock", "") or "")
    broker_vol = 0
    try:
        fn = globals().get("_broker_position")
        if callable(fn):
            vol, _can, _cost = fn(stock)
            broker_vol = int(vol or 0)
    except Exception:
        broker_vol = 0
    keep = []
    changed = False
    for item in pending:
        if not isinstance(item, dict):
            continue
        eday = str(item.get("day") or "")
        if eday and _ex_natural_day_diff(eday, day) > int(
            globals().get("EX_ALLOT_TIMEOUT_DAYS", _EX_ALLOT_TIMEOUT_DAYS)
        ):
            print(
                _strategy_tag(),
                "ex_rights_allot_timeout",
                eday,
                "asof",
                day,
            )
            _event_log("ex_rights_allot_timeout", event_day=eday, day=day)
            changed = True
            continue
        vol0 = int(item.get("vol0") or 0)
        base_mul = float(item.get("share_mul_base") or 1.0)
        sub_mul = float(item.get("share_mul_sub") or 1.0)
        exp_unsub = _ex_round_shares(vol0 * base_mul)
        exp_sub = _ex_round_shares(vol0 * sub_mul)
        if broker_vol < _EX_LOT:
            keep.append(item)
            continue
        d_sub = abs(broker_vol - exp_sub)
        d_unsub = abs(broker_vol - exp_unsub)
        if d_sub < d_unsub and d_sub <= _EX_LOT:
            _ex_set_total_shares(broker_vol)
            _ex_apply_subscribe_cost(
                item.get("cost_snap"),
                item.get("interest"),
                item.get("allot"),
                item.get("allot_px"),
                sub_mul,
            )
            _ex_recompute_max_ret()
            print(
                _strategy_tag(),
                "ex_rights_allot_subscribed",
                eday,
                "vol",
                broker_vol,
            )
            _event_log(
                "ex_rights_allot_subscribed",
                event_day=eday,
                broker_vol=broker_vol,
                exp_sub=exp_sub,
            )
            changed = True
            continue
        if abs(broker_vol - _ex_total_shares()) >= _EX_LOT and d_unsub <= _EX_LOT:
            if _ex_set_total_shares(broker_vol):
                print(
                    _strategy_tag(),
                    "ex_rights_shares_reconcile",
                    broker_vol,
                )
                _event_log(
                    "ex_rights_shares_reconcile",
                    broker_vol=broker_vol,
                    event_day=eday,
                )
                changed = True
        keep.append(item)
    A.ex_rights_allot_pending = keep
    return changed


def _ex_reconcile_shares_live():
    """无配股 pending 时，送转等到账后用券商量纠偏（一手容忍）。"""
    if getattr(A, "is_backtest", False):
        return False
    if _ex_allot_pending_list():
        return False
    stock = str(getattr(A, "stock", "") or "")
    try:
        fn = globals().get("_broker_position")
        if not callable(fn):
            return False
        vol, _can, _cost = fn(stock)
        broker_vol = int(vol or 0)
    except Exception:
        return False
    if broker_vol < _EX_LOT:
        return False
    cur = _ex_total_shares()
    if abs(broker_vol - cur) < _EX_LOT:
        return False
    if _ex_set_total_shares(broker_vol):
        print(_strategy_tag(), "ex_rights_shares_reconcile", broker_vol)
        _event_log(
            "ex_rights_shares_reconcile",
            broker_vol=broker_vol,
            prev=cur,
        )
        return True
    return False


def _maybe_apply_ex_rights(C, day):
    """持仓卖点评估前调用：补做除权缩放 + 配股认购延后判定。"""
    day = str(day or "")
    holding = False
    try:
        holding = bool(_has_position())
    except Exception:
        holding = False
    if not holding:
        bt = getattr(A, "is_backtest", False)
        if bt:
            try:
                holding = int(_bt_held_vol()) >= _EX_LOT
            except Exception:
                holding = False
    if not holding:
        return False
    if _ex_skip_adjusted_backtest():
        return False
    stock = str(getattr(A, "stock", "") or "")
    if not stock or C is None:
        return False
    _ex_ensure_lots()
    applied = _ex_applied_list()
    open_day = _ex_open_day()
    factors = _divid_factors_cached(C, stock)
    events = _divid_events_since(factors, open_day, applied, asof_day=day)
    live_pending = not getattr(A, "is_backtest", False)
    changed = False
    applied_days = []
    for eday, parsed in events:
        ch, same = _ex_apply_one_event(eday, parsed, live_pending)
        applied.append(eday)
        applied_days.append(eday)
        if ch:
            changed = True
        if same:
            _event_log("ex_rights_skip_open_day", event_day=eday, open_day=open_day)
        elif ch:
            _event_log(
                "ex_rights_applied",
                event_day=eday,
                dr=parsed.get("dr"),
                share_mul=parsed.get("share_mul_base"),
                allot=parsed.get("allot"),
                allot_subscribed=False,
            )
            print(
                _strategy_tag(),
                "ex_rights_applied",
                eday,
                "dr=",
                parsed.get("dr"),
                "mul=",
                parsed.get("share_mul_base"),
            )
    A.ex_rights_applied = applied
    if _ex_check_allot_pending(day):
        changed = True
    if _ex_reconcile_shares_live():
        changed = True
    if changed or applied_days:
        try:
            _save_state()
        except Exception:
            pass
    return changed
