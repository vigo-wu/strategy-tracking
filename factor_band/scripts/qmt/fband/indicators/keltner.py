# === fband/indicators/keltner.py ===
def _calc_keltner(highs, lows, closes, ma_n, atr_n, k, kind):
    """返回 (mid, upper, lower) 或 None。中轨 _ma，带宽 k×威尔德 ATR。
    ma_n / atr_n / k / kind 必传，不读 RECIPE。"""
    ma_n = int(ma_n)
    atr_n = int(atr_n)
    try:
        k = float(k)
    except (TypeError, ValueError):
        return None
    if ma_n <= 0 or atr_n <= 0 or k <= 0:
        return None
    mid = _ma(closes, ma_n, kind)
    atr = _calc_atr(highs, lows, closes, atr_n)
    if mid is None or atr is None:
        return None
    n = min(len(mid), len(atr))
    if n <= 0:
        return None
    mid = mid[:n]
    atr = atr[:n]
    upper = mid + k * atr
    lower = mid - k * atr
    return mid, upper, lower
