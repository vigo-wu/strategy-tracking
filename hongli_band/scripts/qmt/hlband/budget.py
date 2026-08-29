# === hlband/budget.py ===
# 覆盖 common:single/orders._buy_budget。实盘共享账本：前两笔 50%/30%，第三笔吃剩余；回测 TRADE_BUDGET×档位。
# 勿改 scripts/qmt_common/single/orders.py。
def _dynamic_budget_on():
    if getattr(A, "is_backtest", False):
        return False
    return True


def _equal_split_on():
    return _dynamic_budget_on()


def _norm_code(code):
    return str(code or "").strip().upper()


def _book_entry_normalize(val):
    """把 BOOK_STOCKS 的 value 规范成 dict。str → {ma_type: str}；其它非 dict → {}。"""
    if isinstance(val, dict):
        return dict(val)
    if isinstance(val, (str, bytes)):
        s = str(val or "").strip()
        if s:
            return {"ma_type": s}
        return {}
    return {}


def _book_stock_map():
    """解析 BOOK_STOCKS → {norm_code: cfg_dict}。兼容 dict / 旧纯字符串序列。"""
    out = {}
    raw = globals().get("BOOK_STOCKS")
    if raw is None:
        return out
    if isinstance(raw, dict):
        for k, v in raw.items():
            code = _norm_code(k)
            if not code:
                continue
            out[code] = _book_entry_normalize(v)
        return out
    try:
        seq = list(raw)
    except Exception:
        return out
    for x in seq:
        if isinstance(x, (list, tuple)) and len(x) >= 1:
            code = _norm_code(x[0])
            cfg = _book_entry_normalize(x[1] if len(x) >= 2 else {})
        else:
            code = _norm_code(x)
            cfg = {}
        if code:
            out[code] = cfg
    return out


def _book_stock_set():
    return set(_book_stock_map().keys())


def _book_cfg(stock):
    """当前标的在 BOOK_STOCKS 中的子配置；不在池则 {}。"""
    ncode = _norm_code(stock)
    if not ncode:
        return {}
    return dict(_book_stock_map().get(ncode) or {})


def _code_in_book(code):
    ncode = _norm_code(code)
    if not ncode:
        return False
    s = _book_stock_set()
    if not s:
        return True
    return ncode in s


def _cfg_book_n():
    n_list = len(_book_stock_set())
    if n_list > 0:
        return n_list
    return 3


def _cfg_cash_ratio():
    try:
        v = float(globals().get("CASH_RATIO") or 0.95)
    except Exception:
        v = 0.95
    if v <= 0:
        return 0.95
    if v > 1.0:
        return 1.0
    return v


def _cfg_book_lot_max():
    try:
        n = int(globals().get("BOOK_LOT_MAX") or 3)
    except Exception:
        n = 3
    return max(1, n)


def _cfg_lot_open_frac():
    try:
        v = float(globals().get("LOT_OPEN_FRAC") or 0.50)
    except Exception:
        v = 0.50
    if v <= 0:
        v = 0.50
    if v > 1.0:
        v = 1.0
    return v


def _cfg_lot_add_frac():
    try:
        v = float(globals().get("LOT_ADD_FRAC") or 0.30)
    except Exception:
        v = 0.30
    if v <= 0:
        v = 0.30
    if v > 1.0:
        v = 1.0
    return v


def _cfg_lot_rest_frac():
    rest = 1.0 - _cfg_lot_open_frac() - _cfg_lot_add_frac()
    if rest < 0:
        return 0.0
    return rest


def _slot_targets():
    open_f = _cfg_lot_open_frac()
    add_f = _cfg_lot_add_frac()
    rest = _cfg_lot_rest_frac()
    max_n = _cfg_book_lot_max()
    if max_n <= 1:
        return [open_f]
    if max_n == 2:
        return [open_f, add_f]
    targets = [open_f, add_f, rest]
    if max_n > 3:
        targets = targets + [add_f] * (max_n - 3)
    return targets


def _frac_is_big(v):
    try:
        return abs(float(v) - _cfg_lot_open_frac()) < 0.02
    except Exception:
        return False


def _frac_is_add(v):
    try:
        return abs(float(v) - _cfg_lot_add_frac()) < 0.02
    except Exception:
        return False


def _vacant_rank(v):
    if _frac_is_big(v):
        return 0
    if _frac_is_add(v):
        return 1
    return 2


def _vacant_sort(vacant):
    vacant = list(vacant or [])
    vacant.sort(key=_vacant_rank)
    return vacant


def _snap_book_frac(raw, cap=0.0, mv=0.0, lot_id=1):
    """把金额或旧字段收成 0.50 / 0.30 / 剩余档。旧 0.25 收到 0.30。"""
    try:
        x = float(raw)
    except Exception:
        x = None
    if x is not None and x > 0:
        if x > 1.0 + 1e-9:
            if cap and cap > 0:
                x = x / float(cap)
            else:
                x = _cfg_lot_add_frac()
        targets = []
        for t in _slot_targets()[:3]:
            dup = False
            for s in targets:
                if abs(s - t) < 1e-12:
                    dup = True
                    break
            if not dup:
                targets.append(t)
        if not targets:
            return _cfg_lot_add_frac()
        best = targets[0]
        best_d = abs(x - best)
        add_f = _cfg_lot_add_frac()
        for t in targets[1:]:
            d = abs(x - t)
            if d < best_d - 1e-12:
                best, best_d = t, d
            elif abs(d - best_d) < 1e-12:
                if abs(t - add_f) < 0.02:
                    best = t
                    best_d = d
        return best
    if cap and cap > 0 and mv and mv > 0:
        return _snap_book_frac(float(mv) / float(cap), cap=0.0)
    try:
        lid = int(lot_id or 1)
    except Exception:
        lid = 1
    if lid <= 1:
        return _cfg_lot_open_frac()
    return _cfg_lot_add_frac()


def _lot_row_from_dict(lot):
    if not isinstance(lot, dict):
        return None
    try:
        sh = int(lot.get("shares") or 0)
    except Exception:
        sh = 0
    if sh < 100:
        return None
    try:
        px = float(lot.get("price") or 0)
    except Exception:
        px = 0.0
    try:
        lid = int(lot.get("id") or 0)
    except Exception:
        lid = 0
    raw_frac = lot.get("book_frac")
    return {
        "id": lid,
        "mv": float(sh) * float(px) if px > 0 else 0.0,
        "frac": raw_frac,
        "shares": sh,
    }


def _lots_from_state_raw(raw):
    if not isinstance(raw, dict):
        return "", []
    stock = _norm_code(raw.get("stock") or "")
    rows = []
    lots = raw.get("lots")
    if isinstance(lots, list):
        for lot in lots:
            row = _lot_row_from_dict(lot)
            if row:
                rows.append(row)
    if rows:
        return stock, rows
    pos = raw.get("position")
    if isinstance(pos, dict):
        try:
            vol = int(pos.get("shares") or 0)
        except Exception:
            vol = 0
        try:
            px = float(pos.get("price") or 0)
        except Exception:
            px = 0.0
        if vol >= 100 and px > 0:
            rows.append({"id": 1, "mv": float(vol) * float(px), "frac": None, "shares": vol})
    return stock, rows


def _state_glob_lots():
    """各图 STATE → {stock: [lot_row,...]}。"""
    out = {}
    base = str(globals().get("STATE_FILE") or "").strip()
    if not base or "{stock}" not in base:
        return out
    folder = os.path.dirname(base)
    fname = os.path.basename(base)
    mid = fname.find("{stock}")
    if mid < 0:
        return out
    pre = fname[:mid]
    post = fname[mid + len("{stock}"):]
    book_name = os.path.basename(_book_path() or "")
    try:
        names = os.listdir(folder) if folder else []
    except Exception:
        return out
    for fn in names:
        if book_name and fn == book_name:
            continue
        if not (fn.startswith(pre) and fn.endswith(post)):
            continue
        path = os.path.join(folder, fn) if folder else fn
        try:
            raw = json.loads(open(path, "r").read())
        except Exception:
            continue
        stock, rows = _lots_from_state_raw(raw)
        if stock and rows:
            out[stock] = rows
    return out


def _collect_book_lot_rows(held=None):
    """池内各笔。本图内存仓覆盖 STATE。held 有市值但无分笔时补 1 笔。"""
    rows_by = _state_glob_lots()
    mine = _norm_code(getattr(A, "stock", ""))
    live = []
    for lot in getattr(A, "lots", None) or []:
        row = _lot_row_from_dict(lot)
        if row:
            live.append(row)
    if mine:
        if live:
            rows_by[mine] = live
        elif not _has_position():
            rows_by[mine] = []
    if held:
        for code, mv in held.items():
            st = _norm_code(code)
            if not st or not _code_in_book(st):
                continue
            try:
                v = float(mv or 0)
            except Exception:
                v = 0.0
            if v <= 1e-6:
                continue
            if st not in rows_by or not rows_by.get(st):
                rows_by[st] = [{"id": 1, "mv": v, "frac": None, "shares": 0}]
    kept = {}
    for st, rows in rows_by.items():
        code = _norm_code(st)
        if code and _code_in_book(code):
            kept[code] = rows
    return kept


def _finalize_lot_fracs(rows_by, cap):
    out = {}
    for stock, rows in (rows_by or {}).items():
        nxt = []
        for row in rows or []:
            item = dict(row)
            item["frac"] = _snap_book_frac(
                item.get("frac"),
                cap=cap,
                mv=item.get("mv") or 0,
                lot_id=item.get("id") or 1,
            )
            nxt.append(item)
        out[_norm_code(stock)] = nxt
    return out


def _occupied_fracs(rows_by):
    out = []
    for rows in (rows_by or {}).values():
        for row in rows or []:
            out.append(float(row.get("frac") or 0))
    return out


def _book_n_held_live(held=None):
    if getattr(A, "is_backtest", False):
        n = 0
        for lot in getattr(A, "lots", None) or []:
            if isinstance(lot, dict) and int(lot.get("shares") or 0) >= 100:
                n += 1
        return int(n)
    rows = _collect_book_lot_rows(held)
    n = 0
    for recs in rows.values():
        n += len(recs or [])
    return int(n)


def _book_scale_blocked():
    """全池满 3 笔，或大仓空且只剩 1 槽（留给开仓）。"""
    n_held = _book_n_held_live()
    if n_held >= _cfg_book_lot_max():
        return True, "book_lot_cap"
    if getattr(A, "is_backtest", False):
        if _chart_next_frac(False) <= 1e-9:
            return True, "scale_cap"
        return False, ""
    rows = _finalize_lot_fracs(_collect_book_lot_rows(), 0)
    occupied = _occupied_fracs(rows)
    vacant = _vacant_slots(occupied)
    slots_left = _cfg_book_lot_max() - len(occupied)
    if _vacant_has_big(vacant) and slots_left <= 1:
        return True, "scale_cap"
    return False, ""


def _vacant_slots(occupied):
    targets = _slot_targets()
    used = [False] * len(targets)
    for raw in occupied or []:
        f = _snap_book_frac(raw)
        matched = None
        for i, t in enumerate(targets):
            if used[i]:
                continue
            if abs(t - f) < 0.02:
                matched = i
                break
        if matched is None:
            best_i = None
            best_d = None
            for i, t in enumerate(targets):
                if used[i]:
                    continue
                d = abs(t - f)
                if best_i is None or d < best_d - 1e-12:
                    best_i, best_d = i, d
                elif abs(d - best_d) < 1e-12:
                    if _frac_is_big(targets[best_i]) and (not _frac_is_big(t)):
                        best_i, best_d = i, d
            matched = best_i
        if matched is not None:
            used[matched] = True
    vacant = [targets[i] for i in range(len(targets)) if not used[i]]
    return _vacant_sort(vacant)


def _vacant_has_big(vacant):
    for v in vacant or []:
        if _frac_is_big(v):
            return True
    return False


def _vacant_has_small(vacant):
    for v in vacant or []:
        if not _frac_is_big(v):
            return True
    return False


def _take_vacant(vacant, want_big):
    vacant = list(vacant or [])
    idx = None
    for i, v in enumerate(vacant):
        if want_big and _frac_is_big(v):
            idx = i
            break
        if (not want_big) and (not _frac_is_big(v)):
            idx = i
            break
    if idx is None:
        return None, vacant
    got = vacant.pop(idx)
    return got, vacant


def _rank_buy_intents(intents, vacant):
    need_big = _vacant_has_big(vacant)
    ranked = list(intents or [])

    def key(it):
        add = 1 if it.get("add") else 0
        if need_big:
            pri = add
        else:
            pri = 0 if add else 1
        return (pri, str(it.get("hhmmss") or ""), str(it.get("stock") or ""))

    ranked.sort(key=key)
    return ranked


def _remainder_frac(occupied):
    """已占用档位之后，相对 cap 还剩多少（第三笔用）。"""
    s = 0.0
    for raw in occupied or []:
        s += float(_snap_book_frac(raw) or 0)
    left = 1.0 - s
    if left < 0:
        return 0.0
    return left


def _chart_next_frac(opening):
    """回测/非均分：本图下一笔占 TRADE_BUDGET 的比例。最后一槽吃剩余。"""
    opening = bool(opening)
    sleeve = float(_trade_budget_cap() or 0)
    live = []
    for lot in getattr(A, "lots", None) or []:
        row = _lot_row_from_dict(lot)
        if row:
            live.append(row)
    mine = _norm_code(getattr(A, "stock", "")) or "_"
    rows_by = _finalize_lot_fracs({mine: live}, sleeve)
    occupied = _occupied_fracs(rows_by)
    vacant = _vacant_slots(occupied)
    n_held = len(occupied)
    slots_left = _cfg_book_lot_max() - n_held
    if slots_left <= 0:
        return 0.0
    if (not opening) and _vacant_has_big(vacant) and slots_left <= 1:
        return 0.0
    if slots_left <= 1:
        return _remainder_frac(occupied)
    if opening:
        if _vacant_has_big(vacant):
            return _cfg_lot_open_frac()
        if _vacant_has_small(vacant):
            return _cfg_lot_add_frac()
        return 0.0
    if _vacant_has_small(vacant):
        return _cfg_lot_add_frac()
    return 0.0


def _buy_budget_fixed(cash):
    """回测：TRADE_BUDGET × 本图下一档。"""
    budget = _trade_budget_cap()
    opening = not (
        _has_position()
        or (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100)
    )
    frac = _chart_next_frac(opening)
    lot = float(budget or 0) * float(frac or 0)
    if lot < 0:
        lot = 0.0
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return lot
    ratio = float(globals().get("CASH_RATIO") or 0)
    if cash is None or cash <= 0:
        return lot
    if ratio > 0:
        by_ratio = float(cash) * ratio
        return min(lot, by_ratio) if lot > 0 else 0.0
    return lot


def _pos_row_mv(p, vol):
    mv = 0.0
    raw_mv = getattr(p, "m_dMarketValue", None)
    if raw_mv is not None:
        try:
            mv = float(raw_mv)
        except Exception:
            mv = 0.0
    if mv <= 0:
        last = getattr(p, "m_dLastPrice", None)
        if last is None:
            last = getattr(p, "m_dOpenPrice", None)
        try:
            if last is not None and float(last) > 0:
                mv = float(last) * float(vol)
        except Exception:
            mv = 0.0
    return float(mv or 0)


def _query_broker_book():
    """白名单持股只数与市值；同时给出其它股票市值。失败则回落本地账本。"""
    stock = _norm_code(getattr(A, "stock", ""))
    out = {
        "ok": False,
        "k": 0,
        "k_other": 0,
        "book_mv": 0.0,
        "other_mv": 0.0,
        "name_mv": 0.0,
        "name_vol": 0,
        "held": {},
        "src": "",
    }
    if getattr(A, "is_backtest", False):
        return out
    try:
        positions = get_trade_detail_data(A.acct, A.acct_type, "position")
    except Exception as e:
        print(_strategy_tag(), "book query fail, try local", e)
        _event_log("book_query_fail", error=str(e))
        return _query_local_book(stock)
    if positions is None:
        return _query_local_book(stock)
    k = 0
    k_other = 0
    book_mv = 0.0
    other_mv = 0.0
    name_mv = 0.0
    name_vol = 0
    held = {}
    for p in positions:
        try:
            vol = int(getattr(p, "m_nVolume", 0) or 0)
        except Exception:
            vol = 0
        if vol < 100:
            continue
        code = _norm_code(_pos_code(p))
        mv = _pos_row_mv(p, vol)
        if _code_in_book(code):
            k += 1
            book_mv += mv
            held[code] = mv
            if code == _norm_code(stock):
                name_mv = mv
                name_vol = vol
        else:
            k_other += 1
            other_mv += mv
    out["ok"] = True
    out["k"] = int(k)
    out["k_other"] = int(k_other)
    out["book_mv"] = float(book_mv)
    out["other_mv"] = float(other_mv)
    out["name_mv"] = float(name_mv)
    out["name_vol"] = int(name_vol)
    out["held"] = held
    out["src"] = "broker"
    _broker_cache_save(held, k, book_mv, other_mv, k_other)
    return out


def _broker_cache_save(held, k, book_mv, other_mv=0.0, k_other=0):
    data = _book_load()
    if not isinstance(data, dict):
        data = {}
    data["broker"] = {
        "ts": datetime.datetime.now().strftime("%Y%m%d %H%M%S"),
        "held": dict(held or {}),
        "k": int(k or 0),
        "k_other": int(k_other or 0),
        "book_mv": float(book_mv or 0),
        "other_mv": float(other_mv or 0),
    }
    _book_save(data)


def _held_from_state_raw(raw):
    """一份 STATE JSON -> (stock, mv, vol)。"""
    if not isinstance(raw, dict):
        return "", 0.0, 0
    stock = str(raw.get("stock") or "")
    stock = _norm_code(stock)
    pos = raw.get("position")
    vol = 0
    px = 0.0
    if isinstance(pos, dict):
        try:
            vol = int(pos.get("shares") or 0)
        except Exception:
            vol = 0
        try:
            px = float(pos.get("price") or 0)
        except Exception:
            px = 0.0
    if vol < 100:
        vol = 0
        lots = raw.get("lots")
        if isinstance(lots, list):
            for lot in lots:
                if not isinstance(lot, dict):
                    continue
                try:
                    sh = int(lot.get("shares") or 0)
                except Exception:
                    sh = 0
                if sh < 100:
                    continue
                vol += sh
                try:
                    px = float(lot.get("price") or px or 0)
                except Exception:
                    pass
    if vol < 100 or px <= 0:
        return stock, 0.0, 0
    return stock, float(vol) * float(px), int(vol)


def _state_glob_held():
    """读各图 STATE_FILE，得到 {stock: mv}。"""
    held = {}
    base = str(globals().get("STATE_FILE") or "").strip()
    if not base or "{stock}" not in base:
        return held
    folder = os.path.dirname(base)
    fname = os.path.basename(base)
    mid = fname.find("{stock}")
    if mid < 0:
        return held
    pre = fname[:mid]
    post = fname[mid + len("{stock}"):]
    book_name = os.path.basename(_book_path() or "")
    try:
        names = os.listdir(folder) if folder else []
    except Exception:
        return held
    for fn in names:
        if book_name and fn == book_name:
            continue
        if not (fn.startswith(pre) and fn.endswith(post)):
            continue
        path = os.path.join(folder, fn) if folder else fn
        try:
            raw = json.loads(open(path, "r").read())
        except Exception:
            continue
        stock, mv, _vol = _held_from_state_raw(raw)
        if stock and mv > 1e-6:
            held[stock] = mv
    return held


def _query_local_book(stock):
    """持仓查询失败：上次券商快照 + 各图 STATE + 本图内存仓。"""
    out = {
        "ok": False,
        "k": 0,
        "k_other": 0,
        "book_mv": 0.0,
        "other_mv": 0.0,
        "name_mv": 0.0,
        "name_vol": 0,
        "held": {},
        "src": "local",
    }
    data = _book_load()
    cache = data.get("broker") if isinstance(data.get("broker"), dict) else None
    held = {}
    if cache and isinstance(cache.get("held"), dict):
        for code, mv in cache.get("held").items():
            try:
                v = float(mv or 0)
            except Exception:
                v = 0.0
            if v > 1e-6 and _code_in_book(code):
                held[_norm_code(code)] = v
    other_mv = 0.0
    k_other = 0
    if cache:
        try:
            other_mv = float(cache.get("other_mv") or 0)
        except Exception:
            other_mv = 0.0
        try:
            k_other = int(cache.get("k_other") or 0)
        except Exception:
            k_other = 0
    for code, mv in _state_glob_held().items():
        if _code_in_book(code):
            held[_norm_code(code)] = mv
    name_vol = 0
    if _has_position():
        sh = _pos_shares()
        px = _pos_cost_price()
        if sh >= 100 and px > 0:
            held[_norm_code(stock)] = float(sh) * float(px)
            name_vol = int(sh)
    if (not held) and (cache is None):
        print(_strategy_tag(), "book local empty, skip buy")
        _event_log("book_local_empty")
        return out
    book_mv = 0.0
    k = 0
    for mv in held.values():
        book_mv += float(mv or 0)
        k += 1
    name_mv = float(held.get(_norm_code(stock)) or 0)
    out["ok"] = True
    out["k"] = int(k)
    out["k_other"] = int(k_other)
    out["book_mv"] = float(book_mv)
    out["other_mv"] = float(other_mv)
    out["name_mv"] = name_mv
    out["name_vol"] = int(name_vol)
    out["held"] = held
    print(
        "%s book fallback local k=%s k_other=%s book_mv=%.0f other_mv=%.0f name_mv=%.0f cache=%s"
        % (STRATEGY_NAME, k, k_other, book_mv, other_mv, name_mv, bool(cache))
    )
    _event_log(
        "book_fallback_local",
        k=k,
        k_other=k_other,
        book_mv=book_mv,
        other_mv=other_mv,
        name_mv=name_mv,
        names=list(held.keys()),
        has_cache=bool(cache),
    )
    return out


def _account_equity(cash, book_mv, other_mv=0.0):
    """E_s = 总资产 - 其它股票市值；失败则现金 + 池内市值。"""
    if getattr(A, "is_backtest", False):
        return None
    try:
        accs = get_trade_detail_data(A.acct, A.acct_type, "account")
        if accs:
            raw = getattr(accs[0], "m_dTotalAsset", None)
            if raw is not None and float(raw) > 0:
                es = float(raw) - float(other_mv or 0)
                if es > 0:
                    return es
    except Exception as e:
        print(_strategy_tag(), "equity query fail", e)
        _event_log("equity_query_fail", error=str(e))
    try:
        c = float(cash or 0)
    except Exception:
        c = 0.0
    return c + float(book_mv or 0)


def _empty_fill_snap():
    return {
        "E": 0.0,
        "N": _cfg_book_n(),
        "k": 0,
        "k_after": 0,
        "k_other": 0,
        "empty": 0,
        "reserve": 0.0,
        "lot": 0.0,
        "book_mv": 0.0,
        "other_mv": 0.0,
        "name_mv": 0.0,
        "cap": 0.0,
        "acct_room": 0.0,
        "name_room": 0.0,
        "opening": False,
        "cash": 0.0,
        "why": "",
        "n_buy": 0,
        "split": 0.0,
        "fill_cap": 0.0,
        "name_lim": 0.0,
        "scale_lim": 0.0,
        "rsv_empty": False,
        "fill_res": False,
        "frac": 0.0,
        "n_held": 0,
        "vacant": "",
        "src": "",
    }


def _name_room(lim, mv):
    try:
        left = float(lim or 0) - float(mv or 0)
    except Exception:
        left = 0.0
    if left < 0:
        return 0.0
    return left


def _book_path():
    return str(globals().get("BOOK_FILE") or "").strip()


def _book_window_id(now_s):
    s = str(now_s or "")
    open_s = _cfg_hhmmss("OPEN_EXEC_START", "093000")
    open_e = _cfg_hhmmss("OPEN_EXEC_END", "094500")
    conf_s = _cfg_hhmmss("SIGNAL_CONFIRM_START", "145600")
    close_e = _cfg_hhmmss("PENDING_EXEC_END", "145700")
    if open_s <= s < open_e:
        return "open"
    if conf_s <= s <= close_e:
        return "close"
    return ""


def _book_freeze_s(window):
    if window == "open":
        return str(globals().get("BOOK_FREEZE_OPEN") or "093200")
    return str(globals().get("BOOK_FREEZE_CLOSE") or "145630")


def _book_load():
    path = _book_path()
    if not path:
        return {}
    try:
        raw = open(path, "r").read()
    except Exception:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _book_save(data):
    path = _book_path()
    if not path:
        return False
    text = json.dumps(data, ensure_ascii=False)
    tmp = path + ".tmp." + str(os.getpid())
    try:
        fh = open(tmp, "w")
        fh.write(text)
        fh.close()
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(_strategy_tag(), "book save fail", e)
        _event_log("book_save_fail", error=str(e))
        try:
            os.remove(tmp)
        except Exception:
            pass
        return False


def _sell_fracs_from_exit():
    px = getattr(A, "pending_exit", None)
    if not isinstance(px, dict):
        return []
    ids = px.get("lot_ids") or []
    try:
        idset = set(int(x) for x in ids)
    except Exception:
        idset = set()
    out = []
    for lot in getattr(A, "lots", None) or []:
        if not isinstance(lot, dict):
            continue
        try:
            lid = int(lot.get("id") or 0)
        except Exception:
            lid = 0
        if idset and lid not in idset:
            continue
        if not idset:
            continue
        row = _lot_row_from_dict(lot)
        if not row:
            continue
        out.append(_snap_book_frac(row.get("frac"), mv=row.get("mv"), lot_id=lid))
    return out


def _book_checkin(
    day,
    window,
    now_s,
    buy=False,
    add=False,
    sell=False,
    sell_all=False,
    n_lots=0,
    round_scaled=False,
    sell_fracs=None,
):
    """本图写入共享账本一条打卡。"""
    if not _equal_split_on():
        return
    if not window:
        return
    stock = _norm_code(getattr(A, "stock", ""))
    if not stock:
        return
    data = _book_load()
    broker_keep = data.get("broker") if isinstance(data.get("broker"), dict) else None
    if str(data.get("day") or "") != str(day) or str(data.get("window") or "") != str(window):
        data = {"day": str(day), "window": str(window), "names": {}}
        if broker_keep:
            data["broker"] = broker_keep
    names = data.get("names")
    if not isinstance(names, dict):
        names = {}
        data["names"] = names
    rec = {
        "checkin": True,
        "buy": bool(buy),
        "add": bool(add),
        "sell": bool(sell),
        "sell_all": bool(sell_all),
        "hhmmss": str(now_s or ""),
        "n_lots": int(n_lots or 0),
        "round_scaled": bool(round_scaled),
    }
    if sell_fracs:
        rec["sell_fracs"] = [float(x) for x in sell_fracs]
    names[stock] = rec
    _book_save(data)


def _sync_signal_book(day, now_s, buy_sig, scale_sig, holding, sell_ok, force_empty):
    if not _equal_split_on():
        return
    window = _book_window_id(now_s)
    if not window:
        return
    pe = getattr(A, "pending_entry", None)
    px = getattr(A, "pending_exit", None)
    sell = bool(isinstance(px, dict) or sell_ok or force_empty)
    buy = bool(isinstance(pe, dict)) or bool(buy_sig) or (bool(scale_sig) and bool(holding))
    add = False
    if isinstance(pe, dict) and pe.get("add"):
        add = True
    elif scale_sig and holding:
        add = True
    if sell:
        buy = False
        add = False
    sell_all = False
    if isinstance(px, dict):
        reasons = px.get("reasons") or []
        if (not px.get("lot_ids")) or ("weekly_bear" in reasons):
            sell_all = True
    n_lots = 0
    for lot in getattr(A, "lots", None) or []:
        if isinstance(lot, dict) and int(lot.get("shares") or 0) >= 100:
            n_lots += 1
    _book_checkin(
        day,
        window,
        now_s,
        buy=buy,
        add=add,
        sell=sell,
        sell_all=sell_all,
        n_lots=n_lots,
        round_scaled=bool(getattr(A, "round_scaled", False)),
        sell_fracs=_sell_fracs_from_exit() if sell else None,
    )


def _book_is_frozen(now_s, data=None):
    if not _equal_split_on():
        return True
    window = _book_window_id(now_s)
    if not window:
        return False
    if data is None:
        data = _book_load()
    if str(data.get("window") or "") != window:
        data = {}
    names = data.get("names") if isinstance(data.get("names"), dict) else {}
    n_ok = 0
    for stock, rec in names.items():
        if not _code_in_book(stock):
            continue
        if isinstance(rec, dict) and rec.get("checkin"):
            n_ok += 1
    if n_ok >= _cfg_book_n():
        return True
    return str(now_s or "") >= _book_freeze_s(window)


def _book_buy_intents(data, now_s):
    """冻结后纳入均分的买单。超时打卡不计入。"""
    window = str(data.get("window") or "")
    names = data.get("names") if isinstance(data.get("names"), dict) else {}
    n_ok = 0
    for stock, rec in names.items():
        if not _code_in_book(stock):
            continue
        if isinstance(rec, dict) and rec.get("checkin"):
            n_ok += 1
    frozen_by_n = n_ok >= _cfg_book_n()
    freeze_s = _book_freeze_s(window)
    frozen_by_time = str(now_s or "") >= freeze_s
    cutoff = "999999" if frozen_by_n else freeze_s
    intents = []
    sells = []
    for stock, rec in names.items():
        if not isinstance(rec, dict) or (not rec.get("checkin")):
            continue
        hh = str(rec.get("hhmmss") or "")
        if hh > cutoff:
            continue
        if rec.get("sell"):
            fracs = rec.get("sell_fracs") or []
            sells.append((str(stock), bool(rec.get("sell_all")), list(fracs), str(rec.get("hhmmss") or "")))
        if rec.get("buy") and (not rec.get("sell")):
            intents.append(
                {
                    "stock": str(stock),
                    "add": bool(rec.get("add")),
                    "hhmmss": str(rec.get("hhmmss") or ""),
                }
            )
    return intents, sells


def _apply_virtual_sells(rows_by, held, cash_v, sells):
    rows_by = dict(rows_by or {})
    held = dict(held or {})
    try:
        cash_v = float(cash_v or 0)
    except Exception:
        cash_v = 0.0
    for item in sells or []:
        stock = _norm_code(item[0] if item else "")
        sell_all = bool(item[1]) if item and len(item) > 1 else False
        fracs = list(item[2]) if item and len(item) > 2 else []
        if not stock:
            continue
        rows = list(rows_by.get(stock) or [])
        if sell_all:
            mv = 0.0
            for r in rows:
                mv += float(r.get("mv") or 0)
            if mv <= 1e-6:
                mv = float(held.get(stock) or 0)
            cash_v += mv
            held.pop(stock, None)
            rows_by[stock] = []
            continue
        want = [_snap_book_frac(x) for x in fracs]
        if not want:
            if rows:
                rows = sorted(
                    rows,
                    key=lambda r: _vacant_rank(r.get("frac")),
                )
                dropped = rows.pop(0)
                cash_v += float(dropped.get("mv") or 0)
            left_mv = 0.0
            for r in rows:
                left_mv += float(r.get("mv") or 0)
            if left_mv > 1e-6:
                held[stock] = left_mv
            else:
                held.pop(stock, None)
            rows_by[stock] = rows
            continue
        remain = []
        for r in rows:
            f = _snap_book_frac(r.get("frac"))
            hit = None
            for i, w in enumerate(want):
                if abs(w - f) < 0.02:
                    hit = i
                    break
            if hit is None:
                remain.append(r)
            else:
                cash_v += float(r.get("mv") or 0)
                want.pop(hit)
        rows_by[stock] = remain
        left_mv = 0.0
        for r in remain:
            left_mv += float(r.get("mv") or 0)
        if left_mv > 1e-6:
            held[stock] = left_mv
        else:
            held.pop(stock, None)
    return rows_by, held, cash_v


def _allocate_equal(cash, now_s):
    """返回 (lots_by_stock, snap_base)。无券商且无本地账本时 why=book_fail。"""
    snap = _empty_fill_snap()
    broker = _query_broker_book()
    if not broker.get("ok"):
        snap["why"] = "book_fail"
        return {}, snap
    held = {}
    for code, mv in (broker.get("held") or {}).items():
        try:
            v = float(mv or 0)
        except Exception:
            v = 0.0
        if v > 1e-6:
            held[_norm_code(code)] = v
    data = _book_load()
    intents, sells = _book_buy_intents(data, now_s)
    clean_intents = []
    for it in intents:
        if not _code_in_book(it.get("stock")):
            continue
        clean_intents.append(
            {
                "stock": _norm_code(it.get("stock")),
                "add": bool(it.get("add")),
                "hhmmss": str(it.get("hhmmss") or ""),
            }
        )
    intents = clean_intents
    clean_sells = []
    for item in sells:
        st = _norm_code(item[0] if item else "")
        if not _code_in_book(st):
            continue
        sa = bool(item[1]) if item and len(item) > 1 else False
        fracs = list(item[2]) if item and len(item) > 2 else []
        clean_sells.append((st, sa, fracs))
    sells = clean_sells
    cash_v = 0.0
    try:
        cash_v = float(cash) if cash is not None else 0.0
    except Exception:
        cash_v = 0.0
    other_mv = float(broker.get("other_mv") or 0)
    equity = _account_equity(cash, float(broker.get("book_mv") or 0), other_mv)
    ratio = _cfg_cash_ratio()
    n = _cfg_book_n()
    stock = _norm_code(getattr(A, "stock", ""))
    cap_guess = ratio * float(equity) if equity and equity > 0 else 0.0
    rows_by = _finalize_lot_fracs(_collect_book_lot_rows(held), cap_guess)
    rows_by, held, cash_v = _apply_virtual_sells(rows_by, held, cash_v, sells)
    book_mv = 0.0
    for mv in held.values():
        book_mv += float(mv or 0)
    if sells:
        equity = cash_v + book_mv
    k = len([1 for mv in held.values() if float(mv or 0) > 1e-6])
    n_new = 0
    for it in intents:
        st = it.get("stock")
        if float(held.get(st) or 0) <= 1e-6:
            n_new += 1
    k_after = k + n_new
    empty = max(0, n - k_after)
    reserve = 0.0
    name_mv = float(held.get(stock) or 0)
    snap.update(
        {
            "N": n,
            "k": k,
            "k_after": k_after,
            "k_other": int(broker.get("k_other") or 0),
            "empty": empty,
            "reserve": reserve,
            "book_mv": book_mv,
            "other_mv": other_mv,
            "name_mv": name_mv,
            "cash": cash_v,
            "n_buy": len(intents),
            "opening": name_mv <= 1e-6,
            "rsv_empty": False,
            "fill_res": False,
        }
    )
    if equity is None or equity <= 0:
        snap["why"] = "no_E"
        return {}, snap
    cap = ratio * float(equity)
    name_lim = cap
    scale_lim = cap
    rows_by = _finalize_lot_fracs(rows_by, cap)
    occupied = _occupied_fracs(rows_by)
    vacant = _vacant_slots(occupied)
    n_held = len(occupied)
    slots_left = _cfg_book_lot_max() - n_held
    free = cap - book_mv
    if free < 0:
        free = 0.0
    free = min(free, cash_v)
    lots = {}
    fracs_by = {}
    why_by = {}
    ranked = _rank_buy_intents(intents, vacant)
    remain_free = free
    remain_vacant = list(vacant)
    remain_slots = slots_left
    for it in ranked:
        st = it.get("stock")
        is_add = bool(it.get("add"))
        why_hit = ""
        frac = 0.0
        if remain_slots <= 0:
            why_hit = "book_lot_cap"
        elif is_add:
            if _vacant_has_big(remain_vacant) and remain_slots <= 1:
                why_hit = "scale_cap"
            elif not _vacant_has_small(remain_vacant):
                why_hit = "book_lot_cap"
            else:
                frac, remain_vacant = _take_vacant(remain_vacant, False)
                frac = float(frac or 0)
        else:
            if _vacant_has_big(remain_vacant):
                frac, remain_vacant = _take_vacant(remain_vacant, True)
            elif _vacant_has_small(remain_vacant):
                frac, remain_vacant = _take_vacant(remain_vacant, False)
            else:
                why_hit = "book_lot_cap"
            frac = float(frac or 0)
        lot = 0.0
        last_slot = remain_slots <= 1
        # 最后一槽：金额吃 cap-已占用-现金限制；book_frac 仍用本档 frac。
        if frac > 0 and remain_free > 1e-6:
            lim = scale_lim if is_add else name_lim
            room = _name_room(lim, float(held.get(st) or 0) + float(lots.get(st) or 0))
            if last_slot:
                lot = min(remain_free, room)
            else:
                lot = min(frac * cap, remain_free, room)
            if lot < 0:
                lot = 0.0
            if lot > 0:
                lots[st] = float(lots.get(st) or 0) + lot
                remain_free -= lot
                remain_slots -= 1
                # 金额可吃剩余；档位标签仍用空档 0.50/0.30/剩余档，避免 snap 把第三笔收成大仓。
                fracs_by[st] = frac
            else:
                why_hit = "scale_cap" if is_add else "buy_cap"
                if frac:
                    remain_vacant.insert(0, frac)
                    remain_vacant = _vacant_sort(remain_vacant)
        elif frac > 0:
            why_hit = "scale_cap" if is_add else "buy_cap"
            remain_vacant.insert(0, frac)
            remain_vacant = _vacant_sort(remain_vacant)
        if why_hit:
            why_by[st] = why_hit
    my_add = False
    for it in intents:
        if _norm_code(it.get("stock")) == stock and it.get("add"):
            my_add = True
    my_lot = float(lots.get(stock) or 0)
    my_frac = float(fracs_by.get(stock) or 0)
    my_why = str(why_by.get(stock) or "")
    if my_lot > 1e-6:
        my_why = "split"
    elif not my_why:
        if remain_slots <= 0 or n_held >= _cfg_book_lot_max():
            my_why = "book_lot_cap"
        elif my_add:
            my_why = "scale_cap"
        else:
            my_why = "buy_cap" if intents else "split"
    fill_cap = my_frac * cap if my_frac > 0 else 0.0
    n_buy = len(intents) if intents else 0
    snap.update(
        {
            "E": float(equity),
            "cap": cap,
            "acct_room": remain_free,
            "name_room": _name_room(name_lim if not my_add else scale_lim, name_mv + my_lot),
            "name_lim": name_lim,
            "scale_lim": scale_lim,
            "fill_cap": fill_cap,
            "lot": my_lot,
            "split": (free / float(n_buy)) if n_buy else 0.0,
            "n_buy": n_buy,
            "why": my_why or "split",
            "src": str(broker.get("src") or "broker"),
            "frac": my_frac,
            "n_held": n_held,
            "vacant": ",".join(["%.2f" % float(x) for x in vacant]),
        }
    )
    return lots, snap


def _fill_budget_snapshot(cash, opening=None):
    snap = _empty_fill_snap()
    if opening is None:
        opening = not (
            _has_position()
            or (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100)
        )
    opening = bool(opening)
    if not _dynamic_budget_on():
        frac = _chart_next_frac(opening)
        lot = float(_buy_budget_fixed(cash) or 0)
        snap["lot"] = lot
        snap["frac"] = frac
        snap["opening"] = opening
        try:
            snap["n_held"] = int(_pos_lots() or 0)
        except Exception:
            snap["n_held"] = 0
        snap["why"] = "fixed" if lot > 1e-6 else "book_lot_cap"
        return snap
    now = datetime.datetime.now()
    now_s = now.strftime("%H%M%S")
    if _equal_split_on():
        if not _book_is_frozen(now_s):
            snap["why"] = "wait"
            return snap
        _lots, snap = _allocate_equal(cash, now_s)
        snap["opening"] = bool(opening)
        return snap
    book = _query_broker_book()
    if not book.get("ok"):
        snap["why"] = "book_fail"
        return snap
    book_mv = float(book.get("book_mv") or 0)
    other_mv = float(book.get("other_mv") or 0)
    name_mv = float(book.get("name_mv") or 0)
    name_vol = int(book.get("name_vol") or 0)
    k = int(book.get("k") or 0)
    name_on_book = name_vol >= 100
    if opening is None:
        opening = (not name_on_book) and (not _has_position())
    opening = bool(opening)
    if opening and (not name_on_book):
        k_after = k + 1
    else:
        k_after = k
    n = _cfg_book_n()
    empty = max(0, n - k_after)
    reserve = 0.0
    equity = _account_equity(cash, book_mv, other_mv)
    try:
        cash_v = float(cash) if cash is not None else 0.0
    except Exception:
        cash_v = 0.0
    snap.update(
        {
            "N": n,
            "k": k,
            "k_after": k_after,
            "k_other": int(book.get("k_other") or 0),
            "empty": empty,
            "reserve": reserve,
            "book_mv": book_mv,
            "other_mv": other_mv,
            "name_mv": name_mv,
            "opening": opening,
            "cash": cash_v,
            "rsv_empty": False,
            "fill_res": False,
        }
    )
    if equity is None or equity <= 0:
        snap["why"] = "no_E"
        return snap
    ratio = _cfg_cash_ratio()
    cap = ratio * float(equity)
    name_lim = cap
    scale_lim = cap
    frac = _chart_next_frac(opening)
    fill_cap = float(frac) * cap
    if opening:
        name_room = _name_room(name_lim, name_mv)
        acct_room = cap - book_mv - reserve
    else:
        name_room = _name_room(scale_lim, name_mv)
        acct_room = cap - book_mv
    lot = min(acct_room, name_room, cash_v, fill_cap)
    if lot < 0:
        lot = 0.0
    why = "fill"
    if lot <= 1e-6:
        if frac <= 1e-9:
            why = "scale_cap" if not opening else "book_lot_cap"
        else:
            why = "buy_cap" if opening else "scale_cap"
    snap.update(
        {
            "E": float(equity),
            "cap": cap,
            "acct_room": acct_room,
            "name_room": name_room,
            "name_lim": name_lim,
            "scale_lim": scale_lim,
            "fill_cap": fill_cap,
            "lot": lot,
            "frac": frac,
            "why": why,
            "src": str(book.get("src") or "broker"),
        }
    )
    return snap


def _log_fill_budget(snap, tag=""):
    snap = snap or {}
    print(
        "%s fill%s E=%.0f N=%s k=%s k_other=%s reserve=%.0f lot=%.0f fill_cap=%.0f "
        "name_lim=%.0f scale_lim=%.0f book_mv=%.0f other_mv=%.0f name_mv=%.0f "
        "n_buy=%s n_held=%s frac=%.2f vacant=%s split=%.0f why=%s src=%s"
        % (
            STRATEGY_NAME,
            (" " + str(tag)) if tag else "",
            float(snap.get("E") or 0),
            snap.get("N"),
            snap.get("k"),
            snap.get("k_other"),
            float(snap.get("reserve") or 0),
            float(snap.get("lot") or 0),
            float(snap.get("fill_cap") or 0),
            float(snap.get("name_lim") or 0),
            float(snap.get("scale_lim") or 0),
            float(snap.get("book_mv") or 0),
            float(snap.get("other_mv") or 0),
            float(snap.get("name_mv") or 0),
            snap.get("n_buy"),
            snap.get("n_held"),
            float(snap.get("frac") or 0),
            snap.get("vacant") or "-",
            float(snap.get("split") or 0),
            snap.get("why") or "-",
            snap.get("src") or "-",
        )
    )
    _event_log(
        "fill_budget",
        tag=str(tag or ""),
        E=snap.get("E"),
        N=snap.get("N"),
        k=snap.get("k"),
        k_after=snap.get("k_after"),
        k_other=snap.get("k_other"),
        reserve=snap.get("reserve"),
        lot=snap.get("lot"),
        book_mv=snap.get("book_mv"),
        other_mv=snap.get("other_mv"),
        name_mv=snap.get("name_mv"),
        empty=snap.get("empty"),
        opening=snap.get("opening"),
        why=snap.get("why"),
        n_buy=snap.get("n_buy"),
        n_held=snap.get("n_held"),
        frac=snap.get("frac"),
        vacant=snap.get("vacant"),
        fill_cap=snap.get("fill_cap"),
        name_lim=snap.get("name_lim"),
        scale_lim=snap.get("scale_lim"),
        src=snap.get("src"),
    )


def _fill_room_ok(price=None, opening=None):
    """额度是否够买至少 100 股。why=buy_cap / scale_cap / wait / book_fail。"""
    cash = _available_cash()
    snap = _fill_budget_snapshot(cash, opening=opening)
    why0 = str(snap.get("why") or "")
    if why0 in ("wait", "book_fail", "no_E"):
        return False, why0, snap
    lot = float(snap.get("lot") or 0)
    is_open = bool(opening) if opening is not None else bool(snap.get("opening"))
    if why0 in ("book_lot_cap", "scale_cap", "buy_cap") and lot <= 1e-6:
        return False, why0, snap
    why = "buy_cap" if is_open else "scale_cap"
    if lot <= 0:
        return False, why, snap
    if price is not None:
        try:
            px = float(price)
        except Exception:
            px = 0.0
        if px > 0 and _lot(px, lot) < 100:
            return False, why, snap
    return True, "", snap


def _buy_budget(cash):
    """覆盖 common：实盘分档；回测回落 TRADE_BUDGET。"""
    if not _dynamic_budget_on():
        return _buy_budget_fixed(cash)
    snap = _fill_budget_snapshot(cash)
    if str(snap.get("why") or "") in ("wait", "book_fail", "no_E"):
        return 0.0
    lot = float(snap.get("lot") or 0)
    return lot if lot > 0 else 0.0


def _heartbeat_extra():
    parts = []
    watch = getattr(A, "watch", None)
    if watch:
        parts.append("watch=%s" % len(watch))
        parts.append("chart=%s" % (getattr(A, "chart_stock", "") or "-"))
        parts.append("drive=%s" % (getattr(A, "_drive", "") or "timer"))
        parts.append("work=%s" % (getattr(A, "_live_work", "") or "-"))
    lots = getattr(A, "lots", None) or []
    if lots:
        bits = []
        for lot in lots:
            try:
                bits.append(
                    "L%s:%s@%.4f"
                    % (lot.get("id"), lot.get("shares"), float(lot.get("price") or 0))
                )
            except Exception:
                pass
        if bits:
            parts.append("lots=" + ",".join(bits))
    if _dynamic_budget_on():
        try:
            cash = _available_cash()
            snap = _fill_budget_snapshot(cash)
            parts.append(
                "E=%.0f N=%s k=%s k_other=%s reserve=%.0f lot=%.0f fill_cap=%.0f "
                "name_lim=%.0f scale_lim=%.0f book_mv=%.0f other_mv=%.0f name_mv=%.0f "
                "n_buy=%s n_held=%s frac=%.2f vacant=%s why=%s src=%s"
                % (
                    float(snap.get("E") or 0),
                    snap.get("N"),
                    snap.get("k"),
                    snap.get("k_other"),
                    float(snap.get("reserve") or 0),
                    float(snap.get("lot") or 0),
                    float(snap.get("fill_cap") or 0),
                    float(snap.get("name_lim") or 0),
                    float(snap.get("scale_lim") or 0),
                    float(snap.get("book_mv") or 0),
                    float(snap.get("other_mv") or 0),
                    float(snap.get("name_mv") or 0),
                    snap.get("n_buy"),
                    snap.get("n_held"),
                    float(snap.get("frac") or 0),
                    snap.get("vacant") or "-",
                    snap.get("why") or "-",
                    snap.get("src") or "-",
                )
            )
        except Exception:
            pass
    return " ".join(parts)
