# === hlband/indicators/util.py ===
def _last_valid(arr, i=-1):
    if arr is None:
        return None
    v = arr[i]
    if v != v:
        return None
    return float(v)


def _cross_down(a_prev, b_prev, a_now, b_now):
    if None in (a_prev, b_prev, a_now, b_now):
        return False
    return (a_prev >= b_prev) and (a_now < b_now)


def _cross_up(a_prev, b_prev, a_now, b_now):
    if None in (a_prev, b_prev, a_now, b_now):
        return False
    return (a_prev <= b_prev) and (a_now > b_now)
