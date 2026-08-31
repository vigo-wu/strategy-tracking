# === qmt_common/single/state_io.py ===
# 作用: 单仓 JSON 状态读写（回测不落盘）
# 主要符号: _load_state, _save_state
# 前置: STATE_FILE, STRATEGY_VER；可选扩展字段由 _state_extra_load/_state_extra_save
# STATE_FILE 为基路径；有 A.stock 时按标的分文件，多模型实例互不覆盖
#   例 ...\hlband_qmt_state.json + 513530.SH → ...\hlband_qmt_state_513530_SH.json
#   或 STATE_FILE 含 {stock} 占位符时直接替换
# 例行 loaded/empty 按 path+内容指纹每会话只打一次；load fail / mismatch / save fail 始终打
def _state_stock_tag():
    stock = str(getattr(A, "stock", "") or "").strip()
    if not stock:
        return ""
    return (
        stock.replace(".", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace(" ", "")
    )


def _state_path():
    base = str(STATE_FILE or "").strip()
    if not base:
        return base
    tag = _state_stock_tag()
    if not tag:
        return base
    if "{stock}" in base:
        return base.replace("{stock}", tag)
    root, ext = os.path.splitext(base)
    if not ext:
        ext = ".json"
    return root + "_" + tag + ext


def _state_load_path():
    """优先分标的文件；缺失时回退旧版共用 STATE_FILE（由 _load_state 再校验 stock）。"""
    path = _state_path()
    if path and os.path.isfile(path):
        return path
    legacy = str(STATE_FILE or "").strip()
    if legacy and legacy != path and os.path.isfile(legacy):
        return legacy
    return path


def _state_map(name):
    d = getattr(A, name, None)
    if not isinstance(d, dict):
        d = {}
        setattr(A, name, d)
    return d


def _state_log_once(path, sig):
    """同一 path+内容指纹每会话只打一次例行 state 日志。失败/mismatch 不走这里。"""
    path = str(path or "")
    sig = str(sig or "")
    d = _state_map("_state_log_sig")
    if d.get(path) == sig:
        return False
    d[path] = sig
    return True


def _state_content_fp(data):
    slim = dict((k, v) for k, v in (data or {}).items() if k != "updated")
    fn = globals().get("_live_json_safe")
    try:
        body = fn(slim) if callable(fn) else slim
        return json.dumps(body, sort_keys=True, ensure_ascii=True, default=str)
    except Exception:
        return repr(slim)


def _state_build_data():
    data = {
        "stock": getattr(A, "stock", ""),
        "version": str(globals().get("STRATEGY_VER") or ""),
        "position": getattr(A, "position", None),
        "lots": list(getattr(A, "lots", None) or []) if isinstance(getattr(A, "lots", None), list) else [],
        "acted_day": getattr(A, "acted_day", ""),
        "acted": sorted(list(getattr(A, "acted", set()) or [])),
        "pending": getattr(A, "pending", None),
    }
    extra = globals().get("_state_extra_save")
    if callable(extra):
        try:
            extra(data)
        except Exception as e:
            print(_strategy_tag(), "state extra save fail", e)
            _event_log("state_extra_save_fail", error=str(e))
    return data


def _state_remember_saved(path, fp):
    _state_map("_state_saved_fp")[str(path or "")] = str(fp or "")


def _state_already_saved(path, fp):
    return _state_map("_state_saved_fp").get(str(path or "")) == str(fp or "")


def _load_state():
    if "{stock}" in str(STATE_FILE or "") and (not _state_stock_tag()):
        return
    A.position = None
    A.lots = []
    A.acted_day = ""
    A.acted = set()
    A.pending = None
    path = _state_load_path()
    if not path or not os.path.isfile(path):
        key = path or STATE_FILE
        if _state_log_once(key, "empty"):
            print(_strategy_tag(), "state: empty (no file)", key)
            _event_log("state_empty", path=key)
        return
    try:
        with open(path, "r") as f:
            raw = json.load(f)
    except Exception as e:
        print(_strategy_tag(), "state load fail", e)
        _event_log("state_load_fail", error=str(e), path=path)
        return
    if not isinstance(raw, dict):
        return
    if str(raw.get("stock", "")) and str(raw.get("stock")) != str(getattr(A, "stock", "")):
        print(_strategy_tag(), "state stock mismatch, ignore", raw.get("stock"), getattr(A, "stock", None))
        _event_log(
            "state_stock_mismatch",
            file_stock=raw.get("stock"),
            runtime_stock=getattr(A, "stock", None),
            path=path,
        )
        return
    pos = raw.get("position")
    if isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= 100:
        A.position = dict(pos)
        A.position["shares"] = int(pos["shares"])
        A.position["price"] = float(pos.get("price", 0) or 0)
        A.position["cost"] = float(pos.get("cost", 0) or 0)
        A.position["opened_at"] = str(pos.get("opened_at", "") or "")
    lots = raw.get("lots")
    cleaned = []
    if isinstance(lots, list):
        for lot in lots:
            if isinstance(lot, dict) and int(lot.get("shares", 0) or 0) >= 100:
                cleaned.append(dict(lot))
    A.lots = cleaned
    A.acted_day = str(raw.get("acted_day", "") or "")
    acted = raw.get("acted") or []
    A.acted = set([str(x) for x in acted]) if isinstance(acted, list) else set()
    pend = raw.get("pending")
    A.pending = pend if isinstance(pend, dict) else None
    extra = globals().get("_state_extra_load")
    if callable(extra):
        try:
            extra(raw)
        except Exception as e:
            print(_strategy_tag(), "state extra load fail", e)
            _event_log("state_extra_load_fail", error=str(e))
    fp = _state_content_fp(_state_build_data())
    _state_remember_saved(path, fp)
    if _state_log_once(path, "loaded|" + fp):
        print(_strategy_tag(), "state loaded", "path=", path, A.position, "pending=", bool(A.pending))
        _event_log(
            "state_loaded",
            path=path,
            position=A.position,
            pending=bool(A.pending),
            pending_order=bool(getattr(A, "pending", None)),
        )


def _save_state():
    if getattr(A, "is_backtest", False):
        return
    if "{stock}" in str(STATE_FILE or "") and (not _state_stock_tag()):
        return
    path = _state_path()
    if not path:
        return
    data = _state_build_data()
    data["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fp = _state_content_fp(data)
    if _state_already_saved(path, fp):
        return
    try:
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=True, indent=2)
        _live_state_snapshot(data)
        _state_remember_saved(path, fp)
    except Exception as e:
        print(_strategy_tag(), "state save fail", path, e)
        _event_log("state_save_fail", error=str(e), path=path)
