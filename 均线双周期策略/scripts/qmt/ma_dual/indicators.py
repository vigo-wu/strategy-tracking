# === ma_dual/indicators.py ===
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


def _swing_low(lows, n=None):
    n = int(n if n is not None else SWING_N)
    if lows is None or len(lows) < 2:
        return 0.0
    window = lows[-n:] if len(lows) >= n else lows
    return float(np.min(np.asarray(window, dtype=float)))


# -------------------- 行情 --------------------
