# === hongli/market.py ===
# 作用: 拉取 OHLC/收盘价与日线均线过滤
# 主要符号: _fetch_closes, _daily_ma_ok, _get_ohlc
# 拼接序: 10/16 | 上一部: market_util.py | 下一部: mode.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
def _fetch_closes(C, stock, period, count, end):
    """按指定周期拉取收盘价序列（供日线均线过滤）。"""
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
    try:
        c_map = C.get_history_data(count, period, "close", dividend_type="front_ratio")
        if c_map and stock in c_map:
            return [float(x) for x in c_map[stock] if x == x]
    except Exception as e:
        _diag_once("daily_hist_fail", e)
    return None


def _daily_ma_ok(C, stock, closes_hint=None):
    """最新日线收盘 > MA(DAILY_MA_N) 则为 True。按小时+均线周期缓存。"""
    if not bool(REQUIRE_ABOVE_DAILY_MA):
        return True, None, None
    n = int(DAILY_MA_N)
    if n <= 1:
        return True, None, None
    day = _bar_datetime(C).strftime("%Y%m%d")
    # 日内策略一天刷新数次，使今日滚动收盘价更新
    bucket = "%s|ma%d" % (_bar_datetime(C).strftime("%Y%m%d%H"), n)
    cache = getattr(A, "_daily_ma_cache", None)
    if isinstance(cache, dict) and cache.get("bucket") == bucket and cache.get("ok") is not None:
        return bool(cache.get("above")), cache.get("last"), cache.get("ma")

    closes = None
    # 策略周期已是日线时，复用传入序列
    if closes_hint is not None and getattr(A, "period", "") == "1d":
        closes = list(closes_hint)
    if not closes:
        end = day  # 日线 API 要 yyyymmdd
        closes = _fetch_closes(C, stock, "1d", max(int(DAILY_MA_COUNT), n + 5), end)
    if not closes or len(closes) < n:
        _diag_once("daily_ma_short", "bars=", 0 if not closes else len(closes), "need=", n)
        # 失败关闭: 无趋势确认则不开仓
        A._daily_ma_cache = {"bucket": bucket, "above": False, "ok": False, "last": None, "ma": None}
        return False, None, None

    last = float(closes[-1])
    ma = float(np.mean(closes[-n:]))
    above = last > ma
    A._daily_ma_cache = {
        "bucket": bucket,
        "above": above,
        "ok": True,
        "last": last,
        "ma": ma,
    }
    _diag_once(
        "daily_ma_ok",
        "last=",
        round(last, 4),
        "ma%d=" % n,
        round(ma, 4),
        "above=",
        above,
    )
    return above, last, ma


def _get_ohlc(C, stock, count=None):
    """按 A.period 拉取 OHLC；先 get_market_data_ex，再回退。"""
    period = getattr(A, "period", "1d")
    if count is None:
        count = _ohlc_count(period)
    end = _bar_end_str(C)
    need = max(BOLL_N, KDJ_N) + 2
    md = None
    source = None
    high = None
    low = None

    # 1) get_market_data_ex
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

    close = _series_from_ex(md, stock, "close") if md is not None else None

    # 2) get_market_data
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
            md = md2
        except Exception as e:
            _diag_once("gmd_fail", e)

    # 3) get_history_data（旧接口，部分版本仍可用）
    if not close or len(close) < need:
        try:
            c_map = C.get_history_data(count, period, "close", dividend_type="front_ratio")
            h_map = C.get_history_data(count, period, "high", dividend_type="front_ratio")
            l_map = C.get_history_data(count, period, "low", dividend_type="front_ratio")
            if c_map and stock in c_map:
                close = [float(x) for x in c_map[stock] if x == x]
                high = [float(x) for x in h_map[stock]] if h_map and stock in h_map else list(close)
                low = [float(x) for x in l_map[stock]] if l_map and stock in l_map else list(close)
                source = "get_history_data"
                md = {"close": close}
        except Exception as e:
            _diag_once("hist_fail", e)

    if not close:
        _diag_once(
            "empty",
            "period=",
            period,
            "end=",
            end,
            "barpos=",
            getattr(C, "barpos", None),
            "md_type=",
            type(md),
            "md_keys=",
            list(md.keys())[:8] if isinstance(md, dict) else None,
        )
        return None

    if md is not None and source != "get_history_data":
        high = _series_from_ex(md, stock, "high")
        low = _series_from_ex(md, stock, "low")
    if not high or len(high) != len(close):
        high = list(close)
    if not low or len(low) != len(close):
        low = list(close)

    if len(close) < need:
        _diag_once(
            "short",
            "period=",
            period,
            "n=",
            len(close),
            "need=",
            need,
            "source=",
            source,
            "end=",
            end,
        )
        return None

    _diag_once(
        "ok",
        "period=",
        period,
        "source=",
        source,
        "n=",
        len(close),
        "end=",
        end,
        "last=",
        close[-1],
        "std20=",
        round(float(np.std(close[-BOLL_N:])), 6),
    )
    return high, low, close

