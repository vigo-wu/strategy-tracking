# === pbs/indicators.py ===
def _bar_hhmmss(dt):
    if dt is None:
        return "000000"
    return dt.strftime("%H%M%S")


def _bar_tag(dt):
    if dt is None:
        return ""
    return dt.strftime("%Y%m%d%H%M%S")


def _cb_code_num():
    stock = str(getattr(A, "stock", "") or "")
    code = stock.split(".")[0] if stock else ""
    try:
        return int(code)
    except Exception:
        return 0


def _is_sz_cb():
    stock = str(getattr(A, "stock", "") or "").upper()
    if stock.endswith(".SZ"):
        return True
    n = _cb_code_num()
    return 120000 <= n <= 129999


def _is_sh_cb():
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


def _cage_cap_from_last(last_px):
    """深市：最近成交价 * CAGE_RATIO，封顶全日涨停。"""
    try:
        last = float(last_px)
    except Exception:
        last = 0.0
    if last <= 0:
        return _reopen_cap()
    ratio = float(globals().get("CAGE_RATIO") or 1.1)
    return _px_round(min(last * ratio, _limit_up()))


def _tick_quote(C):
    """实盘全推：返回 (last, ask1, bid1)；回测禁用 tick。"""
    if getattr(A, "is_backtest", False):
        return 0.0, 0.0, 0.0
    stock = str(getattr(A, "stock", "") or "")
    try:
        fn = getattr(C, "get_full_tick", None)
        if not callable(fn):
            return 0.0, 0.0, 0.0
        ticks = fn([stock])
        if not (isinstance(ticks, dict) and stock in ticks):
            return 0.0, 0.0, 0.0
        t = ticks[stock]

        def _get(obj, *keys):
            for k in keys:
                if isinstance(obj, dict) and obj.get(k) is not None:
                    try:
                        v = float(obj[k])
                        if v > 0:
                            return v
                    except Exception:
                        pass
                if hasattr(obj, k):
                    try:
                        v = float(getattr(obj, k))
                        if v > 0:
                            return v
                    except Exception:
                        pass
            return 0.0

        last = _get(t, "lastPrice", "price", "last", "match")
        ask1 = _get(t, "askPrice1", "ask1", "offerPrice1")
        if ask1 <= 0:
            # 部分终端 askPrice 为列表
            ap = None
            if isinstance(t, dict):
                ap = t.get("askPrice") or t.get("askPrices")
            else:
                ap = getattr(t, "askPrice", None) or getattr(t, "askPrices", None)
            if isinstance(ap, (list, tuple)) and len(ap) > 0:
                try:
                    ask1 = float(ap[0])
                except Exception:
                    ask1 = 0.0
        bid1 = _get(t, "bidPrice1", "bid1", "buyPrice1")
        if bid1 <= 0:
            bp = None
            if isinstance(t, dict):
                bp = t.get("bidPrice") or t.get("bidPrices")
            else:
                bp = getattr(t, "bidPrice", None) or getattr(t, "bidPrices", None)
            if isinstance(bp, (list, tuple)) and len(bp) > 0:
                try:
                    bid1 = float(bp[0])
                except Exception:
                    bid1 = 0.0
        return _px_round(last), _px_round(ask1), _px_round(bid1)
    except Exception as e:
        _diag_once("tick_fail", e)
        return 0.0, 0.0, 0.0


def _tick_last(C, fallback=None):
    last, _a, _b = _tick_quote(C)
    if last > 0:
        return last
    try:
        if fallback is not None and float(fallback) > 0:
            return _px_round(fallback)
    except Exception:
        pass
    return 0.0


def _cage_cap(C, last_px):
    """有效买入上限（不强制抬到 143，避免低于笼子时废单）。

    深市：最近价 * CAGE_RATIO，封顶全日涨停。
    沪市：优先卖一 * CAGE_RATIO；无盘口回退最近价 * CAGE_RATIO。
    无有效基准时回退 REOPEN_CAP 参考价。
    """
    mkt = _market_tag()
    limit_up = _limit_up()
    ratio = float(globals().get("CAGE_RATIO") or 1.1)

    if mkt == "SH" and (not getattr(A, "is_backtest", False)):
        last, ask1, _bid1 = _tick_quote(C)
        base = ask1 if ask1 > 0 else (last if last > 0 else float(last_px or 0))
        if base > 0:
            return _px_round(min(base * ratio, limit_up))

    try:
        last = float(last_px or 0)
    except Exception:
        last = 0.0
    if last > 0:
        return _px_round(min(last * ratio, limit_up))
    return _reopen_cap()


def _listing_day_uncached(C, day):
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

    if ok is None and reason in ("daily_none", "daily_empty"):
        if _minute_has_today():
            return True, "minute_today_fallback"
    return ok, reason


def _is_listing_day(C, day):
    if not bool(globals().get("LISTING_DAY_ONLY", True)):
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
