# === hlband/budget.py ===
# 覆盖 common:single/orders._buy_budget。实盘共享账本均分；回测仍用 TRADE_BUDGET。
# 勿改 scripts/qmt_common/single/orders.py。
def _dynamic_budget_on():
    if getattr(A, "is_backtest", False):
        return False
    return bool(globals().get("DYNAMIC_BUDGET", True))


def _equal_split_on():
    return _dynamic_budget_on() and bool(globals().get("EQUAL_SPLIT", True))


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
    mine = _norm_code(getattr(A, "stock", ""))
    if mine and ncode == mine:
        return True
    s = _book_stock_set()
    if not s:
        return True
    return ncode in s


def _cfg_book_n():
    n_list = len(_book_stock_set())
    try:
        n_cfg = int(globals().get("BOOK_N") or 0)
    except Exception:
        n_cfg = 0
    if n_list > 0:
        if n_cfg and n_cfg != n_list:
            _diag_once("book_n_mismatch", "BOOK_N=%s BOOK_STOCKS=%s" % (n_cfg, n_list))
        return n_list
    return max(1, n_cfg or 4)


def _cfg_min_lot():
    try:
        v = float(globals().get("MIN_LOT") or 0)
    except Exception:
        v = 0.0
    return max(0.0, v)


def _cfg_max_name_frac():
    try:
        v = float(globals().get("MAX_NAME_FRAC") or 0.50)
    except Exception:
        v = 0.50
    if v <= 0:
        v = 0.50
    if v > 1.0:
        v = 1.0
    return v


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


def _buy_budget_fixed(cash):
    """回测 / 关闭 DYNAMIC_BUDGET：沿用单笔 TRADE_BUDGET。"""
    budget = _trade_budget_cap()
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return budget if budget > 0 else 0.0
    ratio = float(globals().get("CASH_RATIO") or 0)
    if cash is None or cash <= 0:
        return budget
    if ratio > 0:
        by_ratio = float(cash) * ratio
        return min(budget, by_ratio) if budget > 0 else by_ratio
    return budget


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
        "src": "",
    }


def _name_limit(equity, cap, n, min_lot, name_frac):
    lim = min(name_frac * float(equity), cap - (n - 1) * min_lot)
    if lim < 0:
        return 0.0
    return float(lim)


def _water_fill(rooms, pool):
    """rooms: {stock: max_yuan}. 均分 pool，触顶后把剩余再分给未触顶的。"""
    lots = {}
    for s in rooms:
        lots[s] = 0.0
    try:
        remaining = float(pool)
    except Exception:
        remaining = 0.0
    if remaining <= 0:
        return lots
    active = [s for s in rooms if float(rooms.get(s) or 0) > 1e-6]
    guard = 0
    while active and remaining > 1e-6 and guard < 16:
        guard += 1
        share = remaining / float(len(active))
        nxt = []
        progressed = False
        for s in active:
            room = float(rooms.get(s) or 0) - lots[s]
            if room <= 1e-6:
                continue
            if share + 1e-9 >= room:
                lots[s] += room
                remaining -= room
                progressed = True
            else:
                lots[s] += share
                remaining -= share
                nxt.append(s)
                progressed = True
        if not nxt:
            break
        if len(nxt) == len(active) and share > 0:
            break
        if not progressed:
            break
        active = nxt
    return lots


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


def _book_checkin(day, window, now_s, buy=False, add=False, sell=False, sell_all=False):
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
    names[stock] = {
        "checkin": True,
        "buy": bool(buy),
        "add": bool(add),
        "sell": bool(sell),
        "sell_all": bool(sell_all),
        "hhmmss": str(now_s or ""),
    }
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
    _book_checkin(
        day,
        window,
        now_s,
        buy=buy,
        add=add,
        sell=sell,
        sell_all=sell_all,
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
            sells.append((str(stock), bool(rec.get("sell_all"))))
        if rec.get("buy") and (not rec.get("sell")):
            intents.append({"stock": str(stock), "add": bool(rec.get("add"))})
    return intents, sells


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
    intents = [{"stock": _norm_code(it.get("stock")), "add": bool(it.get("add"))} for it in intents if _code_in_book(it.get("stock"))]
    sells = [(_norm_code(st), sa) for st, sa in sells if _code_in_book(st)]
    cash_v = 0.0
    try:
        cash_v = float(cash) if cash is not None else 0.0
    except Exception:
        cash_v = 0.0
    for stock, sell_all in sells:
        if not sell_all:
            continue
        mv = float(held.pop(stock, 0) or 0)
        cash_v += mv
    book_mv = 0.0
    for mv in held.values():
        book_mv += float(mv or 0)
    k = len([1 for mv in held.values() if float(mv or 0) > 1e-6])
    n_new = 0
    for it in intents:
        st = it.get("stock")
        if float(held.get(st) or 0) <= 1e-6:
            n_new += 1
    n = _cfg_book_n()
    min_lot = _cfg_min_lot()
    k_after = k + n_new
    empty = max(0, n - k_after)
    reserve = empty * min_lot
    other_mv = float(broker.get("other_mv") or 0)
    equity = _account_equity(cash, float(broker.get("book_mv") or 0), other_mv)
    if sells:
        equity = cash_v + book_mv
    stock = _norm_code(getattr(A, "stock", ""))
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
        }
    )
    if equity is None or equity <= 0:
        snap["why"] = "no_E"
        return {}, snap
    ratio = _cfg_cash_ratio()
    name_frac = _cfg_max_name_frac()
    cap = ratio * float(equity)
    pool = cap - book_mv - reserve
    pool = min(pool, cash_v)
    if pool < 0:
        pool = 0.0
    name_lim = _name_limit(equity, cap, n, min_lot, name_frac)
    rooms = {}
    for it in intents:
        st = it.get("stock")
        mv = float(held.get(st) or 0)
        room = name_lim - mv
        if room < 0:
            room = 0.0
        rooms[st] = room
    lots = _water_fill(rooms, pool)
    my_lot = float(lots.get(stock) or 0)
    my_room = float(rooms.get(stock) or 0)
    n_buy = len(intents) if intents else 1
    snap.update(
        {
            "E": float(equity),
            "cap": cap,
            "acct_room": pool,
            "name_room": my_room,
            "lot": my_lot,
            "split": (pool / float(n_buy)) if n_buy else 0.0,
            "why": "split",
            "src": str(broker.get("src") or "broker"),
        }
    )
    return lots, snap


def _fill_budget_snapshot(cash, opening=None):
    snap = _empty_fill_snap()
    if not _dynamic_budget_on():
        snap["lot"] = float(_buy_budget_fixed(cash) or 0)
        snap["why"] = "fixed"
        return snap
    now = datetime.datetime.now()
    now_s = now.strftime("%H%M%S")
    if _equal_split_on():
        if not _book_is_frozen(now_s):
            snap["why"] = "wait"
            return snap
        _lots, snap = _allocate_equal(cash, now_s)
        if opening is not None:
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
    min_lot = _cfg_min_lot()
    empty = max(0, n - k_after)
    reserve = empty * min_lot
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
        }
    )
    if equity is None or equity <= 0:
        snap["why"] = "no_E"
        return snap
    ratio = _cfg_cash_ratio()
    name_frac = _cfg_max_name_frac()
    cap = ratio * float(equity)
    name_lim = _name_limit(equity, cap, n, min_lot, name_frac)
    name_room = name_lim - name_mv
    acct_room = cap - book_mv - reserve
    lot = min(acct_room, name_room, cash_v)
    if lot < 0:
        lot = 0.0
    snap.update(
        {
            "E": float(equity),
            "cap": cap,
            "acct_room": acct_room,
            "name_room": name_room,
            "lot": lot,
            "why": "fill",
            "src": str(book.get("src") or "broker"),
        }
    )
    return snap


def _log_fill_budget(snap, tag=""):
    snap = snap or {}
    print(
        "%s fill%s E=%.0f N=%s k=%s k_other=%s reserve=%.0f lot=%.0f book_mv=%.0f other_mv=%.0f name_mv=%.0f "
        "n_buy=%s split=%.0f why=%s src=%s"
        % (
            STRATEGY_NAME,
            (" " + str(tag)) if tag else "",
            float(snap.get("E") or 0),
            snap.get("N"),
            snap.get("k"),
            snap.get("k_other"),
            float(snap.get("reserve") or 0),
            float(snap.get("lot") or 0),
            float(snap.get("book_mv") or 0),
            float(snap.get("other_mv") or 0),
            float(snap.get("name_mv") or 0),
            snap.get("n_buy"),
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
    """覆盖 common：实盘均分/填满；回测回落 TRADE_BUDGET。"""
    if not _dynamic_budget_on():
        return _buy_budget_fixed(cash)
    snap = _fill_budget_snapshot(cash)
    if str(snap.get("why") or "") in ("wait", "book_fail", "no_E"):
        return 0.0
    lot = float(snap.get("lot") or 0)
    return lot if lot > 0 else 0.0


def _heartbeat_extra():
    parts = []
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
                "E=%.0f N=%s k=%s k_other=%s reserve=%.0f lot=%.0f book_mv=%.0f other_mv=%.0f name_mv=%.0f "
                "n_buy=%s why=%s src=%s"
                % (
                    float(snap.get("E") or 0),
                    snap.get("N"),
                    snap.get("k"),
                    snap.get("k_other"),
                    float(snap.get("reserve") or 0),
                    float(snap.get("lot") or 0),
                    float(snap.get("book_mv") or 0),
                    float(snap.get("other_mv") or 0),
                    float(snap.get("name_mv") or 0),
                    snap.get("n_buy"),
                    snap.get("why") or "-",
                    snap.get("src") or "-",
                )
            )
        except Exception:
            pass
    return " ".join(parts)
