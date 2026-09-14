# === fband/indicators/keltner.py ===
def _calc_keltner(highs, lows, closes, ema_n, atr_n, k):
    """返回 (mid, upper, lower) 或 None。中轨 EMA，带宽 k×威尔德 ATR。窗与 k 必传，不读 RECIPE。"""
    ema_n = int(ema_n)
    atr_n = int(atr_n)
    try:
        k = float(k)
    except (TypeError, ValueError):
        return None
    if ema_n <= 0 or atr_n <= 0 or k <= 0:
        return None
    mid = _ema(closes, ema_n)
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
