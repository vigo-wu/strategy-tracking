# === hlband/market.py ===
_VALID_DIVIDEND = (
    "follow",
    "none",
    "front",
    "back",
    "front_ratio",
    "back_ratio",
)


def _norm_dividend(raw):
    s = str(raw or "").strip().lower()
    if s in ("", "follow", "chart", "main"):
        return "follow"
    return s


def _book_dividend_raw():
    """BOOK_STOCKS[A.stock].dividend_type；无键返回 None。"""
    stock = str(getattr(A, "stock", "") or "").strip()
    cfg_fn = globals().get("_book_cfg")
    if callable(cfg_fn):
        entry = cfg_fn(stock)
        if isinstance(entry, dict) and "dividend_type" in entry:
            return entry.get("dividend_type")
        return None
    book = globals().get("BOOK_STOCKS")
    if not stock or not isinstance(book, dict):
        return None
    key = stock.upper()
    entry = book.get(stock)
    if entry is None:
        entry = book.get(key)
    if entry is None:
        for k, v in book.items():
            if str(k or "").strip().upper() == key:
                entry = v
                break
    if isinstance(entry, dict) and "dividend_type" in entry:
        return entry.get("dividend_type")
    return None


def _dividend_type():
    """QMT 复权：优先 BOOK_STOCKS[code].dividend_type，否则 DIVIDEND_TYPE。"""
    glob_raw = globals().get("DIVIDEND_TYPE")
    book_raw = _book_dividend_raw()
    picked = book_raw
    if picked is None or str(picked).strip() == "":
        picked = glob_raw
    norm = _norm_dividend(picked)
    if norm in _VALID_DIVIDEND:
        return norm
    if not globals().get("_DIVIDEND_TYPE_BAD"):
        globals()["_DIVIDEND_TYPE_BAD"] = True
        print(
            "%s dividend_type=%s invalid, fallback"
            % (STRATEGY_NAME, picked)
        )
    glob_norm = _norm_dividend(glob_raw)
    if glob_norm in _VALID_DIVIDEND:
        return glob_norm
    return "front_ratio"


def _chart_dividend(C):
    """主图/公式当前复权（只用于日志）。"""
    try:
        return str(getattr(C, "dividend_type", "") or "")
    except Exception:
        return ""


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
    div = _dividend_type()
    try:
        md = C.get_market_data_ex(
            fields=fields,
            stock_code=[stock],
            period=getattr(A, "period", "1d"),
            end_time=end,
            count=int(count),
            dividend_type=div,
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
                dividend_type=div,
            )
        except Exception:
            md = None
    except Exception:
        md = None
    days = _days_from_ex(md, stock) if md is not None else None
    return days


def _week_monday(day):
    s = _norm_bar_day(day)
    if len(s) < 8:
        return ""
    d = datetime.datetime.strptime(s[:8], "%Y%m%d")
    monday = d - datetime.timedelta(days=int(d.weekday()))
    return monday.strftime("%Y%m%d")


def _is_weekly_period(period):
    p = str(period or "").strip().lower()
    return p in ("1w", "week", "weekly", "w")


def _drop_unclosed_week_ohlcv(open_, high, low, close, volume, days, end_day):
    """丢掉 end_day 所在自然周，对齐 QMT 回测 0000 原生 1w（周五当天也不含本周）。"""
    if not close:
        return None
    n = len(close)
    cur = _week_monday(end_day)
    keep = None
    if cur and days and len(days) == n:
        keep = [i for i in range(n) if _week_monday(days[i]) != cur]
    elif cur and (not getattr(A, "is_backtest", False)) and n >= 2:
        keep = list(range(n - 1))
        _diag_once("w1_drop_last_no_days", "end=", end_day, "n=", n)
    if keep is None:
        return open_, high, low, close, volume
    if len(keep) < 1:
        return None

    def _take(seq):
        return [seq[i] for i in keep]

    return _take(open_), _take(high), _take(low), _take(close), _take(volume)


def _bar_end_str(C):
    """覆盖 period.py：实盘 end_time 跟墙钟，15:00 后仍能拉到今日 K。"""
    period = getattr(A, "period", "1d")
    if getattr(A, "is_backtest", False):
        dt = _bar_datetime(C)
        if _is_intraday(period):
            return dt.strftime("%Y%m%d%H%M%S")
        return dt.strftime("%Y%m%d")
    now = datetime.datetime.now()
    today = now.strftime("%Y%m%d")
    chart_day = ""
    try:
        tag = C.get_bar_timetag(C.barpos)
        if "timetag_to_datetime" in globals():
            s = timetag_to_datetime(tag, "%Y%m%d%H%M%S")
            chart_day = str(s)[:8]
        elif tag is not None:
            if tag > 10 ** 12:
                chart_day = datetime.datetime.fromtimestamp(tag / 1000.0).strftime(
                    "%Y%m%d"
                )
            else:
                chart_day = datetime.datetime.fromtimestamp(tag).strftime("%Y%m%d")
    except Exception:
        chart_day = ""
    end_day = today
    if chart_day and len(str(chart_day)) >= 8:
        end_day = max(str(chart_day)[:8], today)
    if _is_intraday(period):
        return now.strftime("%Y%m%d%H%M%S")
    return end_day


def _ohlcv_diag_key(base):
    st = str(getattr(A, "stock", "") or "").replace(".", "_")
    if st:
        return "%s_%s" % (base, st)
    return base


def _get_ohlcv_period(C, stock, period, count, need, diag_key):
    end = _bar_end_str(C)
    if period in ("1d", "1w", "1mon", "1q", "1hy", "1y"):
        end = end[:8] if len(end) >= 8 else end
    md = None
    md_used = None
    source = None
    open_ = high = low = close = volume = None
    fields = ["open", "high", "low", "close", "volume"]
    div = _dividend_type()

    try:
        md = C.get_market_data_ex(
            fields=fields,
            stock_code=[stock],
            period=period,
            end_time=end,
            count=count,
            dividend_type=div,
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
                dividend_type=div,
            )
            source = "get_market_data_ex/pos"
        except Exception as e:
            _diag_once(diag_key + "_ex_fail", e)
            md = None
    except Exception as e:
        _diag_once(diag_key + "_ex_fail", e)
        md = None

    if md is not None:
        md_used = md
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
                dividend_type=div,
            )
            source = "get_market_data"
            md_used = md2
            open_ = _series_from_ex(md2, stock, "open")
            high = _series_from_ex(md2, stock, "high")
            low = _series_from_ex(md2, stock, "low")
            close = _series_from_ex(md2, stock, "close")
            volume = _series_from_ex(md2, stock, "volume")
        except Exception as e:
            _diag_once(diag_key + "_gmd_fail", e)

    if not close:
        _diag_once(
            diag_key + "_empty",
            "period=",
            period,
            "end=",
            end,
            "n=",
            0,
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

    if _is_weekly_period(period):
        days = _days_from_ex(md_used, stock) if md_used is not None else None
        trimmed = _drop_unclosed_week_ohlcv(
            open_, high, low, close, volume, days, end
        )
        if trimmed is None:
            _diag_once(
                diag_key + "_empty",
                "period=",
                period,
                "end=",
                end,
                "n=0 after drop forming week",
            )
            return None
        open_, high, low, close, volume = trimmed

    if len(close) < need:
        _diag_once(
            diag_key + "_empty",
            "period=",
            period,
            "end=",
            end,
            "n=",
            len(close),
        )
        return None

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
        "div=",
        div,
        "chart=",
        _chart_dividend(C) or "-",
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
        C, stock, getattr(A, "period", "1d"), int(OHLC_COUNT), need, _ohlcv_diag_key("d1")
    )


def _get_ohlcv_1w(C, stock):
    need = max(int(W_MA_SLOW), int(MACD_SLOW) + int(MACD_SIGNAL)) + 5
    return _get_ohlcv_period(
        C, stock, "1w", int(WEEKLY_OHLC_COUNT), need, _ohlcv_diag_key("w1")
    )
