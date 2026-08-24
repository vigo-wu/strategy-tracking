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


def _ma_kind():
    """价格均线类型：EMA 或 SMA。非法值回落 EMA。"""
    raw = globals().get("MA_TYPE", "EMA")
    kind = str(raw or "EMA").strip().upper()
    if kind in ("SMA", "EMA"):
        return kind
    if not globals().get("_MA_TYPE_BAD"):
        globals()["_MA_TYPE_BAD"] = True
        print("%s MA_TYPE=%s invalid, fallback EMA" % (STRATEGY_NAME, raw))
    return "EMA"


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
