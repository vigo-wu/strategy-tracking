# === hlband/indicators/macd.py ===
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
