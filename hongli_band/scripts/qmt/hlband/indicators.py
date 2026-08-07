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
    """TR[i] = max(H-L, |H-C_prev|, |L-C_prev|)；首根用 H-L。"""
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = len(c)
    if n == 0 or len(h) != n or len(l) != n:
        return None
    tr = np.empty(n, dtype=float)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        hl = h[i] - l[i]
        hc = abs(h[i] - c[i - 1])
        lc = abs(l[i] - c[i - 1])
        tr[i] = hl if hl >= hc and hl >= lc else (hc if hc >= lc else lc)
    return tr


def _atr(highs, lows, closes, n=None):
    """Wilder ATR；返回与 closes 等长数组，不足暖机为 nan。"""
    n = int(n if n is not None else TRAIL_ATR_PERIOD)
    tr = _true_range(highs, lows, closes)
    if tr is None or n <= 0 or len(tr) < n:
        return None
    out = np.full(len(tr), np.nan, dtype=float)
    out[n - 1] = float(np.mean(tr[:n]))
    for i in range(n, len(tr)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / float(n)
    return out
