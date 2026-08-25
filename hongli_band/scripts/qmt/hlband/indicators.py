# === hlband/indicators.py ===
def _sma(closes, n):
    """简单均线；成交量均量固定走此函数。"""
    c = np.asarray(closes, dtype=float)
    n = int(n)
    if n <= 0 or len(c) < n:
        return None
    out = np.full(len(c), np.nan, dtype=float)
    cs = np.cumsum(c)
    out[n - 1] = cs[n - 1] / float(n)
    if len(c) > n:
        out[n:] = (cs[n:] - cs[:-n]) / float(n)
    return out


def _ema(closes, n):
    c = np.asarray(closes, dtype=float)
    n = int(n)
    if n <= 0 or len(c) < n:
        return None
    out = np.full(len(c), np.nan, dtype=float)
    alpha = 2.0 / (n + 1.0)
    out[n - 1] = float(np.mean(c[:n]))
    for i in range(n, len(c)):
        out[i] = alpha * c[i] + (1.0 - alpha) * out[i - 1]
    return out


def _book_entry_for(stock=None):
    """BOOK_STOCKS 中当前标的的配置 dict；无则 None。"""
    stock = str(stock or getattr(A, "stock", "") or "").strip().upper()
    book = globals().get("BOOK_STOCKS")
    if not stock or not isinstance(book, dict):
        return None
    if stock in book:
        entry = book.get(stock)
    else:
        entry = None
        for k, v in book.items():
            if str(k or "").strip().upper() == stock:
                entry = v
                break
    if isinstance(entry, dict):
        return entry
    if isinstance(entry, (str, bytes)):
        return {"ma_type": entry}
    return None


def _norm_ma_kind(raw, fallback="EMA"):
    kind = str(raw or "").strip().upper()
    if kind in ("SMA", "EMA"):
        return kind
    return str(fallback or "EMA").strip().upper() or "EMA"


def _stick_std(closes, lookback=None, ma_n=None):
    """近 lookback 日收盘相对 SMA(ma_n) 的偏离标准差；样本不足返回 None。"""
    lookback = int(lookback if lookback is not None else globals().get("STICK_LOOKBACK", 120) or 120)
    ma_n = int(ma_n if ma_n is not None else globals().get("STICK_MA_N", 20) or 20)
    if lookback < 20 or ma_n < 2:
        return None
    c = np.asarray(closes, dtype=float)
    if len(c) < ma_n + lookback:
        return None
    ma = _sma(c, ma_n)
    if ma is None:
        return None
    tail_c = c[-lookback:]
    tail_m = ma[-lookback:]
    dev = []
    for i in range(lookback):
        m = float(tail_m[i])
        if m != m or m <= 0:
            continue
        v = float(tail_c[i])
        if v != v:
            continue
        dev.append((v - m) / m)
    if len(dev) < max(20, lookback // 2):
        return None
    return float(np.std(np.asarray(dev, dtype=float), ddof=0))


def _ma_kind_from_stick(stick_std):
    """高粘性(std小)→EMA；低粘性(std大)→SMA。"""
    thr = float(globals().get("STICK_STD_THR", 0.025) or 0.025)
    if stick_std is None:
        return None
    return "EMA" if float(stick_std) <= thr else "SMA"


def _ma_lock_kind():
    """BOOK_STOCKS 强制锁线：ma_lock=True 且 ma_type 合法时返回线型，否则 None。"""
    entry = _book_entry_for()
    if not isinstance(entry, dict):
        return None
    if not bool(entry.get("ma_lock")):
        return None
    raw = entry.get("ma_type")
    kind = _norm_ma_kind(raw, "")
    if kind in ("SMA", "EMA"):
        return kind
    return None


def _ma_kind_static():
    """关自适应时：BOOK_STOCKS.ma_type → MA_TYPE；非法回落 EMA。"""
    entry = _book_entry_for()
    raw = None
    if isinstance(entry, dict):
        raw = entry.get("ma_type")
    if raw is None or str(raw or "").strip() == "":
        raw = globals().get("MA_TYPE", "EMA")
    kind = _norm_ma_kind(raw, "EMA")
    if kind in ("SMA", "EMA"):
        return kind
    if not globals().get("_MA_TYPE_BAD"):
        globals()["_MA_TYPE_BAD"] = True
        print("%s ma_type=%s invalid, fallback EMA" % (STRATEGY_NAME, raw))
    return "EMA"


def _holding_now():
    try:
        if callable(globals().get("_has_position")) and _has_position():
            return True
    except Exception:
        pass
    lots = getattr(A, "lots", None) or []
    if lots:
        return True
    try:
        if callable(globals().get("_bt_held_vol")) and int(_bt_held_vol() or 0) >= 100:
            return True
    except Exception:
        pass
    try:
        vol = float(getattr(A, "volume", 0) or 0)
        if vol > 0:
            return True
    except Exception:
        pass
    return False


def _refresh_ma_kind(closes, day=""):
    """按趋势粘性刷新 A.ma_kind。持仓中保持上次线型；失败回落静态配置。
    返回 (kind, stick_std, source)：source=lock|stick|hold|static|fallback。
    """
    locked = _ma_lock_kind()
    if locked:
        A.ma_kind = locked
        A.stick_std = getattr(A, "stick_std", None)
        A.stick_src = "lock"
        return locked, getattr(A, "stick_std", None), "lock"

    adapt = bool(globals().get("MA_STICK_ADAPT", True))
    if not adapt:
        kind = _ma_kind_static()
        A.ma_kind = kind
        A.stick_std = None
        A.stick_src = "static"
        return kind, None, "static"

    prev = str(getattr(A, "ma_kind", "") or "").strip().upper()
    if prev not in ("SMA", "EMA"):
        prev = ""

    if _holding_now() and prev:
        A.stick_src = "hold"
        return prev, getattr(A, "stick_std", None), "hold"

    stick = _stick_std(closes)
    A.stick_std = stick
    kind = _ma_kind_from_stick(stick)
    if kind is None:
        kind = prev or _ma_kind_static()
        A.ma_kind = kind
        A.stick_src = "fallback"
        return kind, stick, "fallback"

    A.ma_kind = kind
    A.stick_day = day
    A.stick_src = "stick"
    if prev and kind != prev:
        print(
            "%s stick ma_type %s -> %s stick_std=%.4f thr=%.4f"
            % (
                STRATEGY_NAME,
                prev,
                kind,
                float(stick),
                float(globals().get("STICK_STD_THR", 0.025) or 0.025),
            )
        )
        try:
            if callable(globals().get("_save_state")):
                _save_state()
        except Exception:
            pass
    return kind, stick, "stick"


def _ma_kind():
    """当前价格均线类型。优先 A.ma_kind（粘性刷新后），否则静态配置。"""
    cur = str(getattr(A, "ma_kind", "") or "").strip().upper()
    if cur in ("SMA", "EMA"):
        return cur
    locked = _ma_lock_kind()
    if locked:
        A.ma_kind = locked
        return locked
    if bool(globals().get("MA_STICK_ADAPT", True)):
        # 尚未 refresh 时先用静态，等 _handle 用日线收盘刷新
        kind = _ma_kind_static()
        A.ma_kind = kind
        return kind
    kind = _ma_kind_static()
    A.ma_kind = kind
    return kind


def _price_ma(closes, n):
    if _ma_kind() == "SMA":
        return _sma(closes, n)
    return _ema(closes, n)


def _calc_macd(closes, fast=None, slow=None, signal=None):
    """返回 (dif, dea, hist) 或 None。hist = dif - dea。"""
    fast = int(fast if fast is not None else MACD_FAST)
    slow = int(slow if slow is not None else MACD_SLOW)
    signal = int(signal if signal is not None else MACD_SIGNAL)
    c = np.asarray(closes, dtype=float)
    if len(c) < slow + signal:
        return None
    ema_f = _ema(c, fast)
    ema_s = _ema(c, slow)
    if ema_f is None or ema_s is None:
        return None
    dif = ema_f - ema_s
    start = slow - 1
    dif_valid = dif[start:]
    if len(dif_valid) < signal:
        return None
    dea_tail = _ema(dif_valid, signal)
    if dea_tail is None:
        return None
    dea = np.full(len(c), np.nan, dtype=float)
    dea[start:] = dea_tail
    hist = dif - dea
    return dif, dea, hist


def _last_valid(arr, i=-1):
    if arr is None:
        return None
    v = arr[i]
    if v != v:
        return None
    return float(v)


def _near_ma(price, ma, tol=None):
    tol = float(tol if tol is not None else MA_TOUCH_TOL)
    if price is None or ma is None or ma <= 0:
        return False
    return abs(float(price) - float(ma)) / float(ma) <= tol


def _plat_window(highs, lows, lookback, end_i=None):
    """不含 end_i 的回看窗口平台高低点；(plat_high, plat_low) 或 None。"""
    if highs is None or lows is None:
        return None
    n = min(len(highs), len(lows))
    lookback = int(lookback)
    if lookback < 2 or n < lookback + 1:
        return None
    i = n - 1 if end_i is None else int(end_i)
    if i < lookback:
        return None
    win_h = [float(x) for x in highs[i - lookback:i]]
    win_l = [float(x) for x in lows[i - lookback:i]]
    if not win_h or not win_l:
        return None
    plat_high = max(win_h)
    plat_low = min(win_l)
    if plat_high <= 0 or plat_low <= 0:
        return None
    return plat_high, plat_low
