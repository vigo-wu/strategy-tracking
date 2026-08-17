# === ma15/indicators.py ===
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


def _last_valid(arr, i=-1):
    if arr is None:
        return None
    v = arr[i]
    if v != v:
        return None
    return float(v)


def _is_hammer(o, h, l, c):
    rng = float(h) - float(l)
    if rng <= 0:
        return False
    body = abs(float(c) - float(o))
    lower = min(float(o), float(c)) - float(l)
    lower_mult = float(globals().get("HAMMER_LOWER_MULT") or 1.5)
    body_max = float(globals().get("HAMMER_BODY_MAX") or 0.50)
    if lower < lower_mult * body:
        return False
    if body / rng > body_max:
        return False
    if float(c) < float(o):
        return False
    return float(c) >= (float(h) + float(l)) / 2.0


def _is_bounce(o, h, l, c):
    """弱于锤子：收阳、有下影、收在区间上半（回踩确认，不要求 2 倍下影）。"""
    rng = float(h) - float(l)
    if rng <= 0:
        return False
    if float(c) < float(o):
        return False
    body = abs(float(c) - float(o))
    lower = min(float(o), float(c)) - float(l)
    if lower < max(body, rng * 0.20):
        return False
    if body / rng > 0.70:
        return False
    return float(c) >= (float(h) + float(l)) / 2.0


def _is_engulf(o0, c0, o1, c1, v0, v1):
    if float(c0) >= float(o0):
        return False
    if float(c1) <= float(o1):
        return False
    if float(c1) < float(o0):
        return False
    if float(o1) > float(c0):
        return False
    return float(v1) > float(v0)
