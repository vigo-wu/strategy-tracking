# === hlband/indicators/macd.py ===
def _calc_macd(closes, fast, slow, signal):
    """返回 (dif, dea, hist) 或 None。hist = dif - dea。三窗必传。"""
    fast = int(fast)
    slow = int(slow)
    signal = int(signal)
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
