# === fband/indicators/ema.py ===
def _ema(closes, n):
    """指数均线；前 n 根 SMA 播种，其后 alpha=2/(n+1) 递推。"""
    c = np.asarray(closes, dtype=float)
    n = int(n)
    if n <= 0 or len(c) < n:
        return None
    out = np.full(len(c), np.nan, dtype=float)
    seed = float(np.mean(c[:n]))
    out[n - 1] = seed
    rest = c[n:]
    if rest.size == 0:
        return out
    if n == 1:
        out[:] = c
        return out
    alpha = 2.0 / (n + 1.0)
    beta = 1.0 - alpha
    ks = np.arange(rest.size, dtype=float)
    scaled = rest * (beta ** -ks)
    cs = np.cumsum(scaled)
    out[n:] = alpha * (beta ** ks) * cs + (beta ** (ks + 1.0)) * seed
    return out
