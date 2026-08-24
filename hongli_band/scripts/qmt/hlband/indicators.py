# === hlband/indicators.py ===
def _sma(closes, n):
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


def _true_range(highs, lows, closes):
    """真实波幅；序列从末根对齐。"""
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = min(len(h), len(l), len(c))
    if n < 2:
        return None
    h = h[-n:]
    l = l[-n:]
    c = c[-n:]
    tr = np.empty(n, dtype=float)
    tr[0] = h[0] - l[0]
    prev = c[:-1]
    hl = h[1:] - l[1:]
    hc = np.abs(h[1:] - prev)
    lc = np.abs(l[1:] - prev)
    tr[1:] = np.maximum(hl, np.maximum(hc, lc))
    return tr


def _atr(highs, lows, closes, n=None):
    """ATR_n = 近 n 根 TR 的简单均值（与「平均真实波幅」一致）。"""
    n = int(n if n is not None else globals().get("ATR_N", 20) or 20)
    tr = _true_range(highs, lows, closes)
    if tr is None:
        return None
    return _sma(tr, n)


def _clamp_p_atr(raw):
    if raw is None:
        return None
    try:
        p = float(raw)
    except Exception:
        return None
    if p <= 0:
        return None
    try:
        floor = float(globals().get("ATR_P_FLOOR") or 0.015)
    except Exception:
        floor = 0.015
    try:
        cap = float(globals().get("ATR_P_CAP") or 0.045)
    except Exception:
        cap = 0.045
    if cap < floor:
        cap = floor
    return max(floor, min(p, cap))


def _p_atr_ratio(highs, lows, closes, n=None):
    """P_atr = ATR_n / 最新收盘，再夹到 [ATR_P_FLOOR, ATR_P_CAP]。"""
    atr_arr = _atr(highs, lows, closes, n)
    if atr_arr is None or closes is None:
        return None
    atr = _last_valid(atr_arr, -1)
    c = np.asarray(closes, dtype=float)
    if atr is None or len(c) < 1:
        return None
    close = float(c[-1])
    if close <= 0:
        return None
    return _clamp_p_atr(float(atr) / close)


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
