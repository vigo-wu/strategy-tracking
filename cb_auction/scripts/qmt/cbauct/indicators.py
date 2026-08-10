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
    """发行规模（亿元）；未知返回 None。仅日志参考。"""
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


def _cb_code_num():
    stock = str(getattr(A, "stock", "") or "")
    code = stock.split(".")[0] if stock else ""
    try:
        return int(code)
    except Exception:
        return 0


def _is_sz_cb():
    """深市新债：12 / 123 开头（含 127/128 等 12x）。"""
    stock = str(getattr(A, "stock", "") or "").upper()
    if stock.endswith(".SZ"):
        return True
    n = _cb_code_num()
    return 120000 <= n <= 129999


def _is_sh_cb():
    """沪市新债：11 开头。"""
    stock = str(getattr(A, "stock", "") or "").upper()
    if stock.endswith(".SH"):
        return True
    n = _cb_code_num()
    return 110000 <= n <= 119999


def _market_tag():
    if _is_sz_cb():
        return "SZ"
    if _is_sh_cb():
        return "SH"
    return "UNK"


def _px_round(price):
    dec = int(globals().get("PRICE_DECIMALS") or 3)
    try:
        return round(float(price), dec)
    except Exception:
        return 0.0


def _reopen_cap():
    """临停基准 * 笼子；默认 143.00。"""
    cfg = globals().get("REOPEN_CAP_PRICE")
    if cfg is not None:
        try:
            v = float(cfg)
            if v > 0:
                return _px_round(v)
        except Exception:
            pass
    base = float(globals().get("HALT_BASE_PRICE") or 130.0)
    ratio = float(globals().get("CAGE_RATIO") or 1.1)
    return _px_round(base * ratio)


def _limit_up():
    return _px_round(globals().get("LIMIT_UP_PRICE") or 157.30)


def _cage_cap(last_px):
    """有效申报上限 = min(last * CAGE_RATIO, 全天涨停)。"""
    try:
        last = float(last_px)
    except Exception:
        last = 0.0
    if last <= 0:
        return _reopen_cap()
    ratio = float(globals().get("CAGE_RATIO") or 1.1)
    return _px_round(min(last * ratio, _limit_up()))


def _tick_last(C, fallback=None):
    """优先全推 tick 最新价；失败回退 K 线收盘。"""
    stock = str(getattr(A, "stock", "") or "")
    try:
        fn = getattr(C, "get_full_tick", None)
        if callable(fn):
            ticks = fn([stock])
            if isinstance(ticks, dict) and stock in ticks:
                t = ticks[stock]
                # 勿用 lastClose（昨收/面值），会算错笼子
                for k in ("lastPrice", "price", "last", "match"):
                    if isinstance(t, dict) and t.get(k) is not None:
                        px = float(t[k])
                        if px > 0:
                            return _px_round(px)
                    if hasattr(t, k):
                        px = float(getattr(t, k))
                        if px > 0:
                            return _px_round(px)
    except Exception as e:
        _diag_once("tick_fail", e)
    try:
        if fallback is not None and float(fallback) > 0:
            return _px_round(fallback)
    except Exception:
        pass
    return 0.0


def _listing_day_uncached(C, day):
    """无缓存推断是否上市首日。空日K时若今日分钟线有行情则放行。"""
    stock = str(getattr(A, "stock", "") or "")
    mp = globals().get("LISTING_DATE_MAP") or {}
    if stock in mp:
        return str(mp.get(stock) or "") == str(day), "map"

    def _from_close(close):
        if close is None:
            return None, "daily_none"
        try:
            n = len(close)
        except Exception:
            return None, "daily_bad"
        if n <= 0:
            return None, "daily_empty"
        if n >= 2:
            return False, "daily_ge2"
        return True, "daily_eq1"

    def _index_yyyymmdd(ix):
        s = str(ix).strip()
        digits = "".join([c for c in s if c.isdigit()])
        if len(digits) >= 8:
            return digits[:8]
        try:
            if hasattr(ix, "strftime"):
                return ix.strftime("%Y%m%d")
        except Exception:
            pass
        return ""

    def _minute_has_today():
        """日K空洞时：仅当 1m 有数据且时间戳均属 day 才放行。"""
        day8 = str(day)[:8]
        start = day8 + "091500"
        end = day8 + "150000"
        md = None
        try:
            md = C.get_market_data_ex(
                fields=["close"],
                stock_code=[stock],
                period="1m",
                start_time=start,
                end_time=end,
                count=300,
                dividend_type="none",
                fill_data=False,
                subscribe=False,
            )
        except TypeError:
            try:
                md = C.get_market_data_ex(
                    ["close"],
                    [stock],
                    period="1m",
                    start_time=start,
                    end_time=end,
                    count=300,
                    dividend_type="none",
                )
            except Exception as e:
                _diag_once("listing_minute_fail", e)
                return False
        except Exception as e:
            _diag_once("listing_minute_fail", e)
            return False
        close = _series_from_ex(md, stock, "close")
        if close is None or len(close) <= 0:
            return False
        # 尽量校验 index 日期；拿不到 index 则依赖 start/end 窗口
        try:
            df = None
            if isinstance(md, dict) and stock in md:
                df = md[stock]
            if df is not None and hasattr(df, "index"):
                days = set()
                for ix in list(df.index)[:300]:
                    d8 = _index_yyyymmdd(ix)
                    if d8:
                        days.add(d8)
                if days and (day8 not in days or any(d != day8 for d in days)):
                    return False
        except Exception as e:
            _diag_once("listing_minute_index", e)
        return True

    # 日K >=2 根 => 已非首日；fill_data=False 避免空洞填充假K
    try:
        md = C.get_market_data_ex(
            fields=["close"],
            stock_code=[stock],
            period="1d",
            end_time=str(day),
            count=5,
            dividend_type="none",
            fill_data=False,
            subscribe=False,
        )
        ok, reason = _from_close(_series_from_ex(md, stock, "close"))
    except TypeError:
        try:
            md = C.get_market_data_ex(
                ["close"],
                [stock],
                period="1d",
                start_time="",
                end_time=str(day),
                count=5,
                dividend_type="none",
            )
            ok, reason = _from_close(_series_from_ex(md, stock, "close"))
        except Exception as e:
            _diag_once("listing_day_fail", e)
            ok, reason = None, "query_fail"
    except Exception as e:
        _diag_once("listing_day_fail", e)
        ok, reason = None, "query_fail"

    # 仅日K空洞兜底；query_fail/daily_bad 不兜底，避免老债误放行
    if ok is None and reason in ("daily_none", "daily_empty"):
        if _minute_has_today():
            return True, "minute_today_fallback"
    return ok, reason


def _verify_any_day():
    """联调：跳过上市首日门闩，开盘+尾盘竞价流程均可在任意交易日验证。"""
    if bool(globals().get("VERIFY_AUCTION_ANY_DAY", False)):
        return True
    if bool(globals().get("FORCE_RUN", False)):
        return True
    if not bool(globals().get("LISTING_DAY_ONLY", True)):
        return True
    return False


def _is_listing_day(C, day):
    """上市首日门闩（按 day+stock 缓存）。

    VERIFY_AUCTION_ANY_DAY / FORCE_RUN / LISTING_DAY_ONLY=False 均可放行任意交易日。
    推断失败看 LISTING_DAY_FAIL_OPEN。
    """
    if _verify_any_day():
        return True
    stock = str(getattr(A, "stock", "") or "")
    cache_key = "%s|%s" % (stock, day)
    cache = getattr(A, "_listing_day_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        A._listing_day_cache = cache
    if cache_key in cache:
        return bool(cache[cache_key])

    ok, reason = _listing_day_uncached(C, day)
    if ok is None:
        fail_open = bool(globals().get("LISTING_DAY_FAIL_OPEN", False))
        ok = fail_open
        print(
            "%s listing_day unknown -> %s" % (STRATEGY_NAME, "ALLOW" if ok else "DENY"),
            reason,
            stock,
            day,
        )
        _event_log(
            "listing_day_unknown",
            stock=stock,
            day=day,
            allow=ok,
            reason=reason,
        )
    else:
        _event_log("listing_day", stock=stock, day=day, ok=ok, reason=reason)
    cache[cache_key] = bool(ok)
    A._listing_day_cache = cache
    return bool(ok)
