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


def _calc_kdj(high, low, close, n=None, m1=None, m2=None):
    """返回 (K, D, J) 或 None。"""
    n = int(n if n is not None else KDJ_N)
    m1 = int(m1 if m1 is not None else KDJ_M1)
    m2 = int(m2 if m2 is not None else KDJ_M2)
    c = np.asarray(close, dtype=float)
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    length = len(c)
    if length < n + 2:
        return None
    rsv = np.zeros(length, dtype=float)
    for i in range(length):
        i0 = max(0, i - n + 1)
        hn = np.max(h[i0 : i + 1])
        ln = np.min(l[i0 : i + 1])
        if hn <= ln:
            rsv[i] = 50.0
        else:
            rsv[i] = (c[i] - ln) / (hn - ln) * 100.0
    k = np.zeros(length, dtype=float)
    d = np.zeros(length, dtype=float)
    alpha_k = 1.0 / float(m1)
    alpha_d = 1.0 / float(m2)
    k[0] = rsv[0]
    d[0] = k[0]
    for i in range(1, length):
        k[i] = (1.0 - alpha_k) * k[i - 1] + alpha_k * rsv[i]
        d[i] = (1.0 - alpha_d) * d[i - 1] + alpha_d * k[i]
    j = 3.0 * k - 2.0 * d
    return k, d, j


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


def _bias_pct(price, ma):
    if price is None or ma is None or ma <= 0:
        return None
    return (float(price) - float(ma)) / float(ma) * 100.0


def _candle_metrics(o, h, l, c):
    """返回 (body_ratio, upper_shadow_ratio, is_yang)。"""
    o, h, l, c = float(o), float(h), float(l), float(c)
    rng = max(h - l, 1e-8)
    body = abs(c - o)
    upper = h - max(o, c)
    return body / rng, upper / rng, c > o
