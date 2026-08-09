# === cbauct/indicators.py ===
def _bar_hhmmss(dt):
    if dt is None:
        return "000000"
    return dt.strftime("%H%M%S")


def _bar_tag(dt):
    if dt is None:
        return ""
    return dt.strftime("%Y%m%d%H%M%S")


def _issue_size_yi():
    """发行规模（亿元）；未知返回 None。"""
    stock = str(getattr(A, "stock", "") or "")
    mp = globals().get("ISSUE_SIZE_MAP") or {}
    if stock in mp:
        try:
            return float(mp[stock])
        except Exception:
            pass
    try:
        v = float(globals().get("ISSUE_SIZE_YI") or 0)
    except Exception:
        v = 0.0
    if v > 0:
        return v
    return None


def _is_small_issue():
    sz = _issue_size_yi()
    if sz is None:
        return False
    return sz <= float(globals().get("SMALL_SIZE_YI") or 5.0)


def _sell_hint_price(last_px):
    """定稿卖价：≤5亿→157.30；否则→可确认收盘价（用最新价近似）。"""
    if _is_small_issue():
        return float(globals().get("LIMIT_UP_PRICE") or 157.30)
    try:
        px = float(last_px)
    except Exception:
        px = 0.0
    if px > 0:
        return round(px, 3)
    return None
