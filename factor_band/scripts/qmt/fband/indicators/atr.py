# === fband/indicators/atr.py ===
def _true_range(highs, lows, closes):
    """真实波幅。首根 H-L，其后 max(H-L, |H-C_prev|, |L-C_prev|)。"""
    if highs is None or lows is None or closes is None:
        return None
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = min(len(h), len(l), len(c))
    if n <= 0:
        return None
    h = h[:n]
    l = l[:n]
    c = c[:n]
    tr = np.full(n, np.nan, dtype=float)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    return tr


def _wilder(values, n):
    """威尔德平滑：首值=前 n 根 SMA，其后 (prev*(n-1)+x)/n。"""
    v = np.asarray(values, dtype=float)
    n = int(n)
    if n <= 0 or len(v) < n:
        return None
    out = np.full(len(v), np.nan, dtype=float)
    out[n - 1] = float(np.mean(v[:n]))
    for i in range(n, len(v)):
        out[i] = (out[i - 1] * (n - 1) + v[i]) / float(n)
    return out


def _calc_atr(highs, lows, closes, n):
    """威尔德 ATR。n 必传，不读 RECIPE；n<=0 或长度不足返回 None。"""
    n = int(n)
    if n <= 0:
        return None
    tr = _true_range(highs, lows, closes)
    if tr is None:
        return None
    return _wilder(tr, n)


def _atr_to_pct(atr, closes):
    """NATR：ATR/Close*100。非正收盘为 NaN。"""
    if atr is None or closes is None:
        return None
    a = np.asarray(atr, dtype=float)
    c = np.asarray(closes, dtype=float)
    n = min(len(a), len(c))
    if n <= 0:
        return None
    a = a[:n]
    c = c[:n]
    out = np.full(n, np.nan, dtype=float)
    ok = np.isfinite(a) & np.isfinite(c) & (c > 0.0)
    out[ok] = a[ok] / c[ok] * 100.0
    return out


def _calc_atr_pct(highs, lows, closes, n):
    """威尔德 ATR 再 /Close*100。n 必传，不读 RECIPE。"""
    atr = _calc_atr(highs, lows, closes, n)
    if atr is None:
        return None
    return _atr_to_pct(atr, closes)
