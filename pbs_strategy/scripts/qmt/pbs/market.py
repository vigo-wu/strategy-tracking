# === pbs/market.py ===
def _synth_ohlcv_from_px(px, open_px=None, high_px=None, low_px=None, vol=0.0):
    """用最新价合成单根 OHLCV，供 tick 主图决策。"""
    px = float(px or 0)
    if px <= 0:
        return None
    o = float(open_px or 0)
    h = float(high_px or 0)
    l = float(low_px or 0)
    if o <= 0:
        o = px
    if h <= 0:
        h = max(o, px)
    if l <= 0:
        l = min(o, px) if o > 0 else px
    return [o], [h], [l], [px], [float(vol or 0)]


def _tick_field_series(md, stock, field):
    """解析 period=tick 的 get_market_data_ex 结果为 float 列表。"""
    if md is None:
        return None
    # 常见：{stock: DataFrame/ndarray/list[dict]}
    if isinstance(md, dict) and stock in md:
        obj = md[stock]
        if hasattr(obj, "columns") and field in getattr(obj, "columns", []):
            return _series_from_ex(md, stock, field)
        if isinstance(obj, dict) and field in obj:
            try:
                return [float(x) for x in list(obj[field]) if x is not None]
            except Exception:
                pass
        # list/tuple of dict-like ticks
        try:
            rows = list(obj)
            out = []
            for row in rows:
                v = None
                if isinstance(row, dict):
                    v = row.get(field)
                elif hasattr(row, field):
                    v = getattr(row, field)
                elif hasattr(row, "__getitem__"):
                    try:
                        v = row[field]
                    except Exception:
                        v = None
                if v is None:
                    continue
                try:
                    fv = float(v)
                    if fv == fv and fv > 0:
                        out.append(fv)
                except Exception:
                    continue
            if out:
                return out
        except Exception:
            pass
    # 也试标准 K 线字段解析（部分终端 tick 仍给 DataFrame）
    return _series_from_ex(md, stock, field)


def _get_ohlcv_tick(C, stock):
    """分笔主图：实盘优先全推；回测/实盘均用 tick 序列；可选回退 1m。"""
    count = int(globals().get("OHLC_COUNT") or 200)
    end = _bar_end_str(C)
    bt = getattr(A, "is_backtest", False)

    # 1) 实盘全推（回测禁用，避免串入实盘脏价）
    if not bt:
        last, _a, _b = _tick_quote(C)
        open_px = high_px = low_px = 0.0
        try:
            fn = getattr(C, "get_full_tick", None)
            if callable(fn):
                ticks = fn([stock])
                t = ticks.get(stock) if isinstance(ticks, dict) else None
                if t is not None:
                    def _g(*keys):
                        for k in keys:
                            if isinstance(t, dict) and t.get(k) is not None:
                                try:
                                    v = float(t[k])
                                    if v > 0:
                                        return v
                                except Exception:
                                    pass
                            if hasattr(t, k):
                                try:
                                    v = float(getattr(t, k))
                                    if v > 0:
                                        return v
                                except Exception:
                                    pass
                        return 0.0

                    if last <= 0:
                        last = _g("lastPrice", "price", "last", "match")
                    open_px = _g("open", "openPrice")
                    high_px = _g("high", "highPrice")
                    low_px = _g("low", "lowPrice")
        except Exception as e:
            _diag_once("tick_full_fail", e)
        syn = _synth_ohlcv_from_px(last, open_px, high_px, low_px)
        if syn is not None:
            _diag_once("md_ok", "source=", "full_tick", "period=", "tick", "last=", round(last, 4))
            return syn

    # 2) get_market_data_ex(period=tick) — 回测主路径
    md = None
    source = None
    fields = ["lastPrice", "open", "high", "low", "volume"]
    try:
        md = C.get_market_data_ex(
            fields=fields,
            stock_code=[stock],
            period="tick",
            end_time=end,
            count=count,
            dividend_type="none",
            fill_data=False,
            subscribe=False,
        )
        source = "get_market_data_ex/tick"
    except TypeError:
        try:
            md = C.get_market_data_ex(
                fields,
                [stock],
                period="tick",
                start_time="",
                end_time=end,
                count=count,
                dividend_type="none",
            )
            source = "get_market_data_ex/tick/pos"
        except Exception as e:
            _diag_once("md_tick_fail", e)
            md = None
    except Exception as e:
        _diag_once("md_tick_fail", e)
        md = None

    lasts = _tick_field_series(md, stock, "lastPrice")
    if not lasts:
        lasts = _tick_field_series(md, stock, "close")
    opens = _tick_field_series(md, stock, "open")
    highs = _tick_field_series(md, stock, "high")
    lows = _tick_field_series(md, stock, "low")
    vols = _tick_field_series(md, stock, "volume")
    if lasts and len(lasts) >= 1:
        n = len(lasts)
        if not opens or len(opens) != n:
            opens = list(lasts)
        if not highs or len(highs) != n:
            highs = list(lasts)
        if not lows or len(lows) != n:
            lows = list(lasts)
        if not vols or len(vols) != n:
            vols = [0.0] * n
        _diag_once(
            "md_ok",
            "source=",
            source,
            "period=",
            "tick",
            "n=",
            n,
            "last=",
            round(float(lasts[-1]), 4),
            "bt=",
            bt,
        )
        return opens, highs, lows, lasts, vols

    # 3) 可选回退 1m（默认关闭，保持回测/实盘一致）
    if bool(globals().get("TICK_ALLOW_1M_FALLBACK", False)):
        _diag_once("md_tick_fallback_1m", "stock=", stock)
        saved = getattr(A, "period", "tick")
        try:
            A.period = "1m"
            return _get_ohlcv_bars(C, stock, period="1m")
        finally:
            A.period = saved

    _diag_once("md_tick_empty", "stock=", stock, "end=", end, "bt=", bt)
    return None


def _get_ohlcv_bars(C, stock, period=None):
    """拉 K 线 OHLCV。"""
    period = period or getattr(A, "period", "1m")
    count = int(globals().get("OHLC_COUNT") or 120)
    need = 1
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
            dividend_type="none",
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
                dividend_type="none",
            )
            source = "get_market_data_ex/pos"
        except Exception as e:
            _diag_once("md_ex_fail", e)
            md = None
    except Exception as e:
        _diag_once("md_ex_fail", e)
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
                dividend_type="none",
            )
            source = "get_market_data"
            open_ = _series_from_ex(md2, stock, "open")
            high = _series_from_ex(md2, stock, "high")
            low = _series_from_ex(md2, stock, "low")
            close = _series_from_ex(md2, stock, "close")
            volume = _series_from_ex(md2, stock, "volume")
        except Exception as e:
            _diag_once("md_gmd_fail", e)

    if not close or len(close) < need:
        _diag_once(
            "md_empty",
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

    _diag_once(
        "md_ok",
        "source=",
        source,
        "period=",
        period,
        "n=",
        n,
        "end=",
        end,
        "last=",
        round(float(close[-1]), 4),
    )
    return open_, high, low, close, volume


def _get_ohlcv(C, stock):
    """拉主图周期行情；tick 走分笔路径，其余走 K 线。"""
    period = getattr(A, "period", "1m")
    if str(period) == "tick":
        return _get_ohlcv_tick(C, stock)
    return _get_ohlcv_bars(C, stock, period=period)
