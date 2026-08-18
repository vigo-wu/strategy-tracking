# === hlband/market.py ===
def _norm_bar_day(x):
    """行情时间戳/索引 → yyyymmdd。"""
    if x is None:
        return ""
    try:
        if hasattr(x, "strftime"):
            return x.strftime("%Y%m%d")
    except Exception:
        pass
    s = str(x).strip()
    digits = []
    for ch in s:
        if ch.isdigit():
            digits.append(ch)
        elif digits:
            break
    if len(digits) >= 8:
        return "".join(digits[:8])
    return ""


def _days_from_ex(md, stock):
    """从 get_market_data_ex 结果解析交易日列表（与 close 序列对齐时优先 index/time）。"""
    if md is None:
        return None
    df = None
    if isinstance(md, dict) and stock in md:
        df = md[stock]
    elif isinstance(md, dict):
        for v in md.values():
            df = v
            break
    if df is None:
        return None
    raw = None
    if hasattr(df, "index"):
        try:
            raw = list(df.index)
        except Exception:
            raw = None
    if (not raw) and hasattr(df, "columns"):
        for col in ("time", "date", "datetime", "stime"):
            try:
                cols = getattr(df, "columns", [])
                if col in cols:
                    raw = list(df[col])
                    break
            except Exception:
                continue
    if not raw:
        return None
    out = []
    for x in raw:
        d = _norm_bar_day(x)
        if d:
            out.append(d)
    return out if out else None


def _get_daily_bar_days(C, stock, count=8):
    """最近若干根日线交易日（yyyymmdd），失败返回 None。"""
    end = _bar_end_str(C)
    if len(end) >= 8:
        end = end[:8]
    fields = ["close"]
    md = None
    try:
        md = C.get_market_data_ex(
            fields=fields,
            stock_code=[stock],
            period=getattr(A, "period", "1d"),
            end_time=end,
            count=int(count),
            dividend_type="front_ratio",
            fill_data=True,
            subscribe=False,
        )
    except TypeError:
        try:
            md = C.get_market_data_ex(
                fields,
                [stock],
                period=getattr(A, "period", "1d"),
                start_time="",
                end_time=end,
                count=int(count),
                dividend_type="front_ratio",
            )
        except Exception:
            md = None
    except Exception:
        md = None
    days = _days_from_ex(md, stock) if md is not None else None
    return days


def _get_ohlcv_period(C, stock, period, count, need, diag_key):
    end = _bar_end_str(C)
    if period in ("1d", "1w", "1mon", "1q", "1hy", "1y"):
        end = end[:8] if len(end) >= 8 else end
    md = None
    source = None
    open_ = high = low = close = volume = None
    fields = ["open", "high", "low", "close", "volume"]

    try:
        md = C.get_market_data_ex(
            fields=fields,
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
                fields,
                [stock],
                period=period,
                start_time="",
                end_time=end,
                count=count,
                dividend_type="front_ratio",
            )
            source = "get_market_data_ex/pos"
        except Exception as e:
            _diag_once(diag_key + "_ex_fail", e)
            md = None
    except Exception as e:
        _diag_once(diag_key + "_ex_fail", e)
        md = None

    if md is not None:
        open_ = _series_from_ex(md, stock, "open")
        high = _series_from_ex(md, stock, "high")
        low = _series_from_ex(md, stock, "low")
        close = _series_from_ex(md, stock, "close")
        volume = _series_from_ex(md, stock, "volume")

    if not close or len(close) < need:
        try:
            md2 = C.get_market_data(
                fields,
                stock_code=[stock],
                period=period,
                end_time=end,
                count=count,
                dividend_type="front_ratio",
            )
            source = "get_market_data"
            open_ = _series_from_ex(md2, stock, "open")
            high = _series_from_ex(md2, stock, "high")
            low = _series_from_ex(md2, stock, "low")
            close = _series_from_ex(md2, stock, "close")
            volume = _series_from_ex(md2, stock, "volume")
        except Exception as e:
            _diag_once(diag_key + "_gmd_fail", e)

    if not close or len(close) < need:
        _diag_once(
            diag_key + "_empty",
            "period=",
            period,
            "end=",
            end,
            "n=",
            0 if not close else len(close),
        )
        return None

    n = len(close)
    if not open_ or len(open_) != n:
        open_ = list(close)
    if not high or len(high) != n:
        high = list(close)
    if not low or len(low) != n:
        low = list(close)
    if not volume or len(volume) != n:
        volume = [0.0] * n

    if np.std(np.asarray(close[-min(20, len(close)) :], dtype=float)) < 1e-8:
        _diag_once(diag_key + "_flat", "n=", len(close), "source=", source)
        return None

    _diag_once(
        diag_key + "_ok",
        "source=",
        source,
        "period=",
        period,
        "n=",
        len(close),
        "end=",
        end,
        "last=",
        round(float(close[-1]), 4),
    )
    return open_, high, low, close, volume


def _get_ohlcv_1d(C, stock):
    plat_n = int(globals().get("SCALE_PLAT_LOOKBACK") or 20)
    need = max(
        int(D_MA_SLOW),
        int(VOL_PULLBACK_N),
        int(VOL_DRY_N),
        plat_n + 2,
    ) + 10
    return _get_ohlcv_period(
        C, stock, getattr(A, "period", "1d"), int(OHLC_COUNT), need, "d1"
    )


def _get_ohlcv_1w(C, stock):
    need = max(int(W_MA_SLOW), int(MACD_SLOW) + int(MACD_SIGNAL)) + 5
    return _get_ohlcv_period(
        C, stock, "1w", int(WEEKLY_OHLC_COUNT), need, "w1"
    )
