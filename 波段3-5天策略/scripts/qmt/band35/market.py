# === band35/market.py ===
# 作用: 15m OHLC + 日线 MA
def _fetch_closes(C, stock, period, count, end):
    md = None
    try:
        md = C.get_market_data_ex(
            fields=["close"],
            stock_code=[stock],
            period=period,
            end_time=end,
            count=count,
            dividend_type="front_ratio",
            fill_data=True,
            subscribe=False,
        )
    except TypeError:
        try:
            md = C.get_market_data_ex(
                ["close"],
                [stock],
                period=period,
                start_time="",
                end_time=end,
                count=count,
                dividend_type="front_ratio",
            )
        except Exception as e:
            _diag_once("daily_ex_fail", e)
            md = None
    except Exception as e:
        _diag_once("daily_ex_fail", e)
        md = None
    closes = _series_from_ex(md, stock, "close") if md is not None else None
    if closes and len(closes) >= 2:
        return closes
    try:
        md2 = C.get_market_data(
            ["close"],
            stock_code=[stock],
            period=period,
            end_time=end,
            count=count,
            dividend_type="front_ratio",
        )
        closes = _series_from_ex(md2, stock, "close")
        if closes and len(closes) >= 2:
            return closes
    except Exception as e:
        _diag_once("daily_gmd_fail", e)
    return None


def _get_daily_ma(C, stock):
    """返回 (日线收盘, MA10) 或 (None, None)。"""
    n = int(DAILY_MA_N)
    day = _bar_datetime(C).strftime("%Y%m%d")
    bucket = "%s|ma%d" % (_bar_datetime(C).strftime("%Y%m%d%H"), n)
    cache = getattr(A, "_daily_ma_cache", None)
    if isinstance(cache, dict) and cache.get("bucket") == bucket and cache.get("ok"):
        return cache.get("last"), cache.get("ma")

    closes = _fetch_closes(C, stock, "1d", max(int(DAILY_MA_COUNT), n + 5), day)
    if not closes or len(closes) < n:
        _diag_once("daily_ma_short", "bars=", 0 if not closes else len(closes), "need=", n)
        A._daily_ma_cache = {"bucket": bucket, "ok": False, "last": None, "ma": None}
        return None, None
    last = float(closes[-1])
    ma = _sma(closes, n)
    A._daily_ma_cache = {"bucket": bucket, "ok": True, "last": last, "ma": ma}
    _diag_once(
        "ok_daily",
        "last=",
        round(last, 4),
        "ma%d=" % n,
        round(ma, 4) if ma is not None else None,
    )
    return last, ma


def _get_ohlc(C, stock, count=None):
    period = getattr(A, "period", "15m")
    if count is None:
        count = int(OHLC_COUNT) if OHLC_COUNT else 480
    end = _bar_end_str(C)
    need = KDJ_N + 5
    md = None
    source = None
    high = low = close = None

    try:
        md = C.get_market_data_ex(
            fields=["high", "low", "close"],
            stock_code=[stock],
            period=period,
            end_time=end,
            count=count,
            dividend_type="front_ratio",
            fill_data=True,
            subscribe=False,
        )
        source = "get_market_data_ex"
    except TypeError:
        try:
            md = C.get_market_data_ex(
                ["high", "low", "close"],
                [stock],
                period=period,
                start_time="",
                end_time=end,
                count=count,
                dividend_type="front_ratio",
            )
            source = "get_market_data_ex/pos"
        except Exception as e:
            _diag_once("ex_fail", e)
            md = None
    except Exception as e:
        _diag_once("ex_fail", e)
        md = None

    if md is not None:
        close = _series_from_ex(md, stock, "close")
        high = _series_from_ex(md, stock, "high")
        low = _series_from_ex(md, stock, "low")

    if not close or len(close) < need:
        try:
            md2 = C.get_market_data(
                ["high", "low", "close"],
                stock_code=[stock],
                period=period,
                end_time=end,
                count=count,
                dividend_type="front_ratio",
            )
            source = "get_market_data"
            close = _series_from_ex(md2, stock, "close")
            high = _series_from_ex(md2, stock, "high")
            low = _series_from_ex(md2, stock, "low")
        except Exception as e:
            _diag_once("gmd_fail", e)

    if not close or len(close) < need:
        _diag_once("empty", "period=", period, "end=", end, "n=", 0 if not close else len(close))
        return None

    if not high or len(high) != len(close):
        high = list(close)
    if not low or len(low) != len(close):
        low = list(close)

    if np.std(np.asarray(close[-min(20, len(close)) :], dtype=float)) < 1e-8:
        _diag_once("flat", "n=", len(close), "source=", source)
        return None

    _diag_once(
        "ok",
        "source=",
        source,
        "n=",
        len(close),
        "end=",
        end,
        "last=",
        round(float(close[-1]), 4),
    )
    return high, low, close
