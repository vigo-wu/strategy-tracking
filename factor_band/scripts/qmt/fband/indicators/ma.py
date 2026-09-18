# === fband/indicators/ma.py ===
def _ma(closes, n, kind):
    """价格均线分发。kind 必传 "sma"|"ema"，不读 RECIPE；非法 kind → None。"""
    k = str(kind or "").strip().lower()
    if k == "sma":
        return _sma(closes, n)
    if k == "ema":
        return _ema(closes, n)
    return None
