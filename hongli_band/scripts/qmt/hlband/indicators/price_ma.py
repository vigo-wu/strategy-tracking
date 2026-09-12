# === hlband/indicators/price_ma.py ===
def _ma_kind():
    """价格均线类型：优先 BOOK_STOCKS[A.stock].ma_type，否则 MA_TYPE；非法回落 EMA。"""
    raw = None
    stock = str(getattr(A, "stock", "") or "").strip().upper()
    book = globals().get("BOOK_STOCKS")
    if stock and isinstance(book, dict):
        entry = None
        if stock in book:
            entry = book.get(stock)
        else:
            for k, v in book.items():
                if str(k or "").strip().upper() == stock:
                    entry = v
                    break
        if isinstance(entry, dict):
            raw = entry.get("ma_type")
        elif isinstance(entry, (str, bytes)):
            raw = entry
    if raw is None or str(raw or "").strip() == "":
        raw = globals().get("MA_TYPE", "EMA")
    kind = str(raw or "EMA").strip().upper()
    if kind in ("SMA", "EMA"):
        return kind
    if not globals().get("_MA_TYPE_BAD"):
        globals()["_MA_TYPE_BAD"] = True
        print("%s ma_type=%s invalid, fallback EMA" % (STRATEGY_NAME, raw))
    return "EMA"


def _price_ma(closes, n):
    if _ma_kind() == "SMA":
        return _sma(closes, n)
    return _ema(closes, n)
