# === band35/indicators.py ===
def _calc_kdj(high, low, close, n=None, m1=None, m2=None):
    """返回 (K序列, D序列) 或 None。KDJ(n,m1,m2)，RSV ewm com=m1-1。"""
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
    return k, d


def _sma(closes, n):
    if closes is None or len(closes) < n:
        return None
    return float(np.mean(np.asarray(closes, dtype=float)[-n:]))
