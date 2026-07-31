# coding: utf-8
"""一次性生成 qmt_terminal_trend_pb_basket.py（从单标的版改造）。"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "qmt_terminal_trend_pb.py"
DST = HERE / "qmt_terminal_trend_pb_basket.py"

BOOK_HELPERS = r'''
A = _S()


def _empty_book_item():
    return {
        "position": None,
        "acted": set(),
        "pending": None,
        "pending_entry": None,
        "bt_held": 0,
        "bt_locked": 0,
        "bt_lock_day": "",
        "bt_opened_at": "",
        "bt_swing_low": 0.0,
        "bt_half_taken": False,
        "bt_initial_shares": 0,
    }


def _ensure_book():
    if not isinstance(getattr(A, "book", None), dict):
        A.book = {}


def _book_get(stock):
    _ensure_book()
    stock = str(stock or "")
    if stock not in A.book:
        A.book[stock] = _empty_book_item()
    return A.book[stock]


def _bind(stock):
    """把 A 工作区切换到指定标的(复用单标的买卖逻辑)."""
    stock = str(stock or "")
    b = _book_get(stock)
    A.stock = stock
    A.position = b.get("position")
    acted = b.get("acted")
    A.acted = acted if isinstance(acted, set) else set(acted or [])
    A.pending = b.get("pending")
    A.pending_entry = b.get("pending_entry")
    A.bt_held = int(b.get("bt_held", 0) or 0)
    A.bt_locked = int(b.get("bt_locked", 0) or 0)
    A.bt_lock_day = str(b.get("bt_lock_day", "") or "")
    A.bt_opened_at = str(b.get("bt_opened_at", "") or "")
    A.bt_swing_low = float(b.get("bt_swing_low", 0) or 0)
    A.bt_half_taken = bool(b.get("bt_half_taken", False))
    A.bt_initial_shares = int(b.get("bt_initial_shares", 0) or 0)


def _unbind():
    stock = str(getattr(A, "stock", "") or "")
    if not stock:
        return
    b = _book_get(stock)
    b["position"] = A.position
    b["acted"] = set(getattr(A, "acted", set()) or set())
    b["pending"] = getattr(A, "pending", None)
    b["pending_entry"] = getattr(A, "pending_entry", None)
    b["bt_held"] = int(getattr(A, "bt_held", 0) or 0)
    b["bt_locked"] = int(getattr(A, "bt_locked", 0) or 0)
    b["bt_lock_day"] = str(getattr(A, "bt_lock_day", "") or "")
    b["bt_opened_at"] = str(getattr(A, "bt_opened_at", "") or "")
    b["bt_swing_low"] = float(getattr(A, "bt_swing_low", 0) or 0)
    b["bt_half_taken"] = bool(getattr(A, "bt_half_taken", False))
    b["bt_initial_shares"] = int(getattr(A, "bt_initial_shares", 0) or 0)


def _count_holdings():
    _ensure_book()
    n = 0
    bt = getattr(A, "is_backtest", False)
    for code, b in A.book.items():
        pos = b.get("position")
        if isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= 100:
            n += 1
            continue
        if bt and int(b.get("bt_held", 0) or 0) >= 100:
            n += 1
    return n


def _holding_codes():
    _ensure_book()
    out = []
    bt = getattr(A, "is_backtest", False)
    for code, b in A.book.items():
        pos = b.get("position")
        if isinstance(pos, dict) and int(pos.get("shares", 0) or 0) >= 100:
            out.append(code)
        elif bt and int(b.get("bt_held", 0) or 0) >= 100:
            out.append(code)
    return out


def _normalize_code(code):
    code = str(code or "").strip().upper()
    if not code:
        return ""
    if "." in code:
        return code
    if code.startswith(("5", "6", "9")):
        return code + ".SH"
    return code + ".SZ"


def _resolve_pool(C):
    """取中证央企红利成分股; 回测尽量带 timetag 防未来函数."""
    codes = []
    tag = None
    try:
        tag = C.get_bar_timetag(C.barpos)
    except Exception:
        tag = None

    for fn_name in ("get_sector",):
        fn = getattr(C, fn_name, None)
        if not callable(fn):
            fn = globals().get(fn_name)
        if not callable(fn):
            continue
        try:
            if tag is not None and getattr(A, "is_backtest", False):
                raw = fn(POOL_INDEX, tag)
            else:
                raw = fn(POOL_INDEX)
            if raw:
                codes = list(raw)
                _diag_once("pool_src", fn_name, POOL_INDEX, "n=", len(codes))
                break
        except TypeError:
            try:
                raw = fn(POOL_INDEX)
                if raw:
                    codes = list(raw)
                    _diag_once("pool_src", fn_name + "/notag", POOL_INDEX, "n=", len(codes))
                    break
            except Exception as e:
                _diag_once("pool_" + fn_name, e)
        except Exception as e:
            _diag_once("pool_" + fn_name, e)

    if not codes:
        for name in POOL_SECTOR_NAMES:
            fn = getattr(C, "get_stock_list_in_sector", None)
            if not callable(fn):
                fn = globals().get("get_stock_list_in_sector")
            if not callable(fn):
                break
            try:
                if tag is not None and getattr(A, "is_backtest", False):
                    try:
                        raw = fn(name, tag)
                    except TypeError:
                        raw = fn(name)
                else:
                    raw = fn(name)
                if raw:
                    codes = list(raw)
                    _diag_once("pool_src", "sector", name, "n=", len(codes))
                    break
            except Exception as e:
                _diag_once("pool_sector_" + name, e)

    if not codes and POOL_FALLBACK:
        codes = list(POOL_FALLBACK)
        _diag_once("pool_src", "fallback", "n=", len(codes))

    out = []
    seen = set()
    for c in codes:
        cc = _normalize_code(c)
        if not cc or cc in seen:
            continue
        if cc.startswith("000825."):
            continue
        seen.add(cc)
        out.append(cc)

    if not out:
        chart = str(getattr(A, "chart_stock", "") or "")
        if chart and not chart.startswith("000825."):
            out = [chart]
            _diag_once("pool_src", "chart_only", chart)
        else:
            _diag_once("pool_empty", "请下载板块/指数成分或填 POOL_FALLBACK")
    return out


'''

NEW_STATE = r'''# -------------------- 状态 IO --------------------
def _state_path():
    return STATE_FILE


def _pos_from_raw(pos):
    if not isinstance(pos, dict):
        return None
    if int(pos.get("shares", 0) or 0) < 100:
        return None
    return {
        "shares": int(pos["shares"]),
        "price": float(pos.get("price", 0) or 0),
        "cost": float(pos.get("cost", 0) or 0),
        "opened_at": str(pos.get("opened_at", "") or ""),
        "swing_low": float(pos.get("swing_low", 0) or 0),
        "half_taken": bool(pos.get("half_taken", False)),
        "initial_shares": int(pos.get("initial_shares", pos.get("shares", 0)) or 0),
    }


def _load_state():
    _ensure_book()
    A.book = {}
    A.acted_day = ""
    path = _state_path()
    if not path or not os.path.isfile(path):
        print("%s state: empty (no file)" % STRATEGY_NAME)
        return
    try:
        with open(path, "r") as f:
            raw = json.load(f)
    except Exception as e:
        print("%s state load fail" % STRATEGY_NAME, e)
        return
    if not isinstance(raw, dict):
        return
    A.acted_day = str(raw.get("acted_day", "") or "")
    books = raw.get("books")
    if isinstance(books, dict):
        for code, item in books.items():
            code = _normalize_code(code)
            if not code or not isinstance(item, dict):
                continue
            b = _empty_book_item()
            b["position"] = _pos_from_raw(item.get("position"))
            acted = item.get("acted") or []
            b["acted"] = set(acted) if isinstance(acted, list) else set()
            pe = item.get("pending_entry")
            b["pending_entry"] = pe if isinstance(pe, dict) else None
            pend = item.get("pending")
            b["pending"] = pend if isinstance(pend, dict) else None
            A.book[code] = b
    else:
        code = _normalize_code(raw.get("stock") or getattr(A, "chart_stock", ""))
        if code:
            b = _empty_book_item()
            b["position"] = _pos_from_raw(raw.get("position"))
            acted = raw.get("acted") or []
            b["acted"] = set(acted) if isinstance(acted, list) else set()
            pe = raw.get("pending_entry")
            b["pending_entry"] = pe if isinstance(pe, dict) else None
            A.book[code] = b
    print("%s state loaded holdings=" % STRATEGY_NAME, _count_holdings(), "codes=", list(A.book.keys()))


def _save_state():
    if getattr(A, "is_backtest", False):
        return
    try:
        _unbind()
    except Exception:
        pass
    path = _state_path()
    if not path:
        return
    _ensure_book()
    books = {}
    for code, b in A.book.items():
        books[code] = {
            "position": b.get("position"),
            "acted": list(b.get("acted") or []),
            "pending": b.get("pending"),
            "pending_entry": b.get("pending_entry"),
        }
    data = {
        "version": STRATEGY_VER,
        "pool_index": POOL_INDEX,
        "acted_day": getattr(A, "acted_day", ""),
        "books": books,
    }
    try:
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("%s state save fail" % STRATEGY_NAME, e)


def _reset_day(day):
    if getattr(A, "acted_day", "") != day:
        A.acted_day = day
        _ensure_book()
        for b in A.book.values():
            b["acted"] = set()
        A.acted = set()
'''

BATCH_FN = r'''
def _get_ohlcv_batch(C, stocks, count=None):
    """批量取 OHLCV, 返回 {stock: (o,h,l,c,v)}."""
    period = getattr(A, "period", "1d")
    if count is None:
        count = int(OHLC_COUNT) if OHLC_COUNT else 180
    end = _bar_end_str(C)
    need = max(int(EMA_SLOW), int(BOLL_N), int(RSI_N)) + int(EMA_SLOPE_LOOKBACK) + 5
    stocks = [str(s) for s in (stocks or []) if s]
    out = {}
    if not stocks:
        return out

    md = None
    try:
        md = C.get_market_data_ex(
            fields=["open", "high", "low", "close", "volume"],
            stock_code=stocks,
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
                ["open", "high", "low", "close", "volume"],
                stocks,
                period=period,
                start_time="",
                end_time=end,
                count=count,
                dividend_type="front_ratio",
            )
        except Exception as e:
            _diag_once("batch_ex_fail", e)
            md = None
    except Exception as e:
        _diag_once("batch_ex_fail", e)
        md = None

    for stock in stocks:
        open_ = high = low = close = volume = None
        if md is not None:
            open_ = _series_from_ex(md, stock, "open")
            high = _series_from_ex(md, stock, "high")
            low = _series_from_ex(md, stock, "low")
            close = _series_from_ex(md, stock, "close")
            volume = _series_from_ex(md, stock, "volume")
        if not close or len(close) < need:
            one = _get_ohlcv(C, stock, count=count)
            if one is not None:
                out[stock] = one
            else:
                _diag_once("ohlcv_short_" + stock, "n=", 0 if not close else len(close))
            continue
        n = min(len(open_ or []), len(high or []), len(low or []), len(close), len(volume or close))
        if n < need:
            _diag_once("ohlcv_short_" + stock, "n=", n)
            continue
        if not getattr(A, "_diag_ok", False):
            A._diag_ok = True
            print("%s diag: ok batch n_stocks=" % STRATEGY_NAME, len(stocks), "sample=", stock, "bars=", n)
        out[stock] = (open_[-n:], high[-n:], low[-n:], close[-n:], (volume or [0] * n)[-n:])
    return out


'''

NEW_HANDLE_INIT = r'''
def _process_all_pendings(C, now):
    """实盘: 处理所有标的 pending."""
    if getattr(A, "is_backtest", False) or DRY_RUN:
        return False
    _ensure_book()
    busy = False
    codes = [c for c, b in list(A.book.items()) if isinstance(b.get("pending"), dict)]
    for code in codes:
        _bind(code)
        try:
            if _process_pending(C, now):
                busy = True
        finally:
            _unbind()
    return busy


def _handle_one(C, stock, ohlcv, now, bar_dt, day, live_phase, bt):
    """单标的信号与下单."""
    _bind(stock)
    try:
        if bt:
            _bt_roll_t1(day)
            _bt_recover_position(now=now)

        opens, highs, lows, closes, volumes = ohlcv
        ema20 = _ema(closes, EMA_FAST)
        ema60 = _ema(closes, EMA_SLOW)
        rsi = _rsi_wilder(closes, RSI_N)
        _mid, boll_up, _ = _bollinger(closes, BOLL_N, BOLL_K)
        if ema20 is None or ema60 is None or rsi is None:
            return

        price = float(closes[-1])
        open_px = float(opens[-1])
        if bt:
            _bt_recover_position(now=now, last=price)

        buy, detail = _eval_buy(opens, highs, lows, closes, volumes, ema20, ema60, rsi)
        sell_reason, sell_vol, mark_half = _eval_sell(
            opens, highs, lows, closes, rsi, boll_up, now
        )
        holding = _has_position() or (bt and _bt_held_vol() >= 100)
        swing = _swing_low_at(lows)

        e20 = float(ema20[-1]) if ema20[-1] == ema20[-1] else None
        e60 = float(ema60[-1]) if ema60[-1] == ema60[-1] else None
        r0 = float(rsi[-1]) if rsi[-1] == rsi[-1] else None
        bu = float(boll_up[-1]) if boll_up is not None and boll_up[-1] == boll_up[-1] else None

        interesting = buy or bool(sell_reason) or holding
        if interesting:
            print(
                "%s" % STRATEGY_NAME,
                stock,
                day,
                _bar_hhmm(bar_dt),
                "n=%d close=%.4f ema20=%s ema60=%s rsi=%s boll_up=%s buy=%s sell=%s hold=%s "
                "trend=%s near20=%s alert=%s div=%s cross=%s pat=%s yang=%s "
                "bt_held=%s avail=%s holdings=%s/%s"
                % (
                    len(closes),
                    price,
                    None if e20 is None else round(e20, 4),
                    None if e60 is None else round(e60, 4),
                    None if r0 is None else round(r0, 2),
                    None if bu is None else round(bu, 4),
                    buy,
                    sell_reason,
                    holding,
                    detail.get("trend"),
                    detail.get("near20"),
                    detail.get("rsi_alert"),
                    detail.get("diverge"),
                    detail.get("rsi_cross"),
                    detail.get("pattern") or "-",
                    detail.get("yang"),
                    _bt_held_vol() if bt else "-",
                    _bt_available_vol() if bt else "-",
                    _count_holdings(),
                    MAX_HOLDINGS,
                ),
            )

        if sell_reason and holding:
            _order_sell(C, sell_reason, price, now, want_vol=sell_vol, mark_half=mark_half)
            return

        mode = str(ENTRY_MODE or "close").strip().lower()
        pe = getattr(A, "pending_entry", None)
        if (
            (not holding)
            and isinstance(pe, dict)
            and ("BUY" not in getattr(A, "acted", set()))
            and (bt or live_phase == "open" or mode == "next_open")
        ):
            sig_day = str(pe.get("signal_day", "") or "")
            if bt:
                if sig_day and sig_day < day:
                    _order_buy(C, open_px, now, swing_low=float(pe.get("swing_low", 0) or 0))
                    return
            else:
                if live_phase == "open" and sig_day and sig_day < day:
                    _order_buy(C, open_px, now, swing_low=float(pe.get("swing_low", 0) or 0))
                    return

        if buy and (not holding) and ("BUY" not in getattr(A, "acted", set())):
            if mode == "next_open":
                A.pending_entry = {
                    "signal_day": day,
                    "swing_low": swing,
                    "close": price,
                }
                _save_state()
                print("%s pending_entry set" % STRATEGY_NAME, stock, A.pending_entry)
                return
            _order_buy(C, price, now, swing_low=swing)
    finally:
        _unbind()


def _handle(C):
    bt = getattr(A, "is_backtest", False)
    bar_dt = _bar_datetime(C)
    now = bar_dt if bt else datetime.datetime.now()
    day = now.strftime("%Y%m%d")
    live_phase = "close"

    if not bt:
        _process_all_pendings(C, now)
        in_win, live_phase = _in_live_decision_window(now)
        if not in_win:
            _live_heartbeat("outside_session")
            return
        if LIVE_ONLY_LAST_BAR:
            try:
                if hasattr(C, "is_last_bar") and (not C.is_last_bar()):
                    return
            except Exception:
                pass
        _live_heartbeat("in_session")

    _reset_day(day)

    cash = _available_cash()
    if cash is None:
        _live_heartbeat("no_cash_or_login")
        return

    pool = _resolve_pool(C)
    for code in _holding_codes():
        if code not in pool:
            pool.append(code)

    if not pool:
        _live_heartbeat("empty_pool")
        return

    try:
        C.set_universe(pool)
    except Exception:
        pass

    batch = _get_ohlcv_batch(C, pool)
    if not batch:
        _live_heartbeat("ohlcv_none")
        return

    if not getattr(A, "ready_logged", False):
        A.ready_logged = True
        print(
            "%s ready" % STRATEGY_NAME,
            day,
            "pool=",
            len(pool),
            "md=",
            len(batch),
            "holdings=",
            _count_holdings(),
            "/",
            MAX_HOLDINGS,
            "budget=",
            TRADE_BUDGET,
        )

    sell_first = [c for c in pool if c in set(_holding_codes())]
    buy_cands = [c for c in pool if c not in set(sell_first)]

    for stock in sell_first:
        ohlcv = batch.get(stock)
        if ohlcv is None:
            continue
        _handle_one(C, stock, ohlcv, now, bar_dt, day, live_phase, bt)

    if _count_holdings() < int(MAX_HOLDINGS):
        for stock in buy_cands:
            if _count_holdings() >= int(MAX_HOLDINGS):
                break
            ohlcv = batch.get(stock)
            if ohlcv is None:
                continue
            _handle_one(C, stock, ohlcv, now, bar_dt, day, live_phase, bt)


def init(C):
    A.busy = False
    A._hb_at = None
    try:
        _init_impl(C)
    except Exception as e:
        print("%s init error" % STRATEGY_NAME, e)
        try:
            traceback.print_exc()
        except Exception:
            pass


def _init_impl(C):
    A.chart_stock = str(getattr(C, "stockcode", "") or "") + "." + str(getattr(C, "market", "") or "")
    A.stock = A.chart_stock
    A.period = _resolve_period(C)
    _ensure_book()

    if "account" in globals() and account:
        A.acct = str(account)
    elif hasattr(C, "accountid") and C.accountid:
        A.acct = str(C.accountid)
    else:
        A.acct = ACCOUNT_ID

    if "accountType" in globals() and accountType:
        A.acct_type = str(accountType)
    else:
        A.acct_type = ACCOUNT_TYPE

    try:
        C.set_account(A.acct)
    except Exception:
        pass

    A.buy_code = 23 if A.acct_type == "STOCK" else 33
    A.sell_code = 24 if A.acct_type == "STOCK" else 34
    A.busy = False
    A.do_back_test_raw = _is_backtest(C)
    A.is_backtest = A.do_back_test_raw
    A._diag_seen = set()
    A._diag_ok = False

    try:
        fn = globals().get("download_sector_data")
        if callable(fn):
            fn()
            print("%s download_sector_data ok" % STRATEGY_NAME)
    except Exception as e:
        print("%s download_sector_data skip" % STRATEGY_NAME, e)

    pool = _resolve_pool(C)
    do_dl = DOWNLOAD_HIST_BACKTEST if A.is_backtest else DOWNLOAD_HIST_LIVE
    if do_dl:
        dl_list = [POOL_INDEX] + list(pool)
        for s in dl_list:
            try:
                _download_hist(s, A.period)
            except Exception as e:
                print("%s download_hist abort-safe" % STRATEGY_NAME, s, e)
    else:
        print("%s skip download_history (live)" % STRATEGY_NAME, A.period, "pool=", len(pool))

    if A.is_backtest:
        barpos = 0
        try:
            barpos = int(getattr(C, "barpos", 0) or 0)
        except Exception:
            barpos = 0
        fresh = (not getattr(A, "_bt_alive", False)) or (barpos <= 0)
        if fresh:
            A.book = {}
            A.acted_day = ""
            A._bt_alive = True
            A.ready_logged = False
            print("%s backtest session start barpos=" % STRATEGY_NAME, barpos)
        else:
            print(
                "%s backtest re-init preserve barpos=" % STRATEGY_NAME,
                barpos,
                "holdings=",
                _count_holdings(),
            )
    else:
        _load_state()
        A.ready_logged = False

    try:
        C.set_universe(pool if pool else [A.chart_stock])
    except Exception as e:
        print("%s set_universe fail" % STRATEGY_NAME, e)

    print(
        "%s %s init" % (STRATEGY_NAME, STRATEGY_VER),
        "chart=",
        A.chart_stock,
        "pool=",
        len(pool),
        "max_hold=",
        MAX_HOLDINGS,
        A.acct,
        A.acct_type,
        "PERIOD=",
        A.period,
        "BACKTEST=",
        A.is_backtest,
        "DRY_RUN=",
        DRY_RUN,
        "budget=",
        TRADE_BUDGET,
        "index=",
        POOL_INDEX,
        "entry=",
        ENTRY_MODE,
    )


'''


def main() -> None:
    text = SRC.read_text(encoding="utf-8")

    text = text.replace(
        '"""TrendPB v1.0 - 趋势回调策略(国金 QMT 终端模型 / 日线版).\n'
        "\n"
        "主图周期: 日线. 信号见主题 model.md.\n"
        "部署: python scripts/qmt/_deploy_qmt_gbk.py -> 写入 QMT python/TrendPB.py (GBK).\n"
        "注意: 请编辑本仓库 UTF-8 源文件; 勿在 IDE 中直接打开 QMT 目录下的 TrendPB.py(其为 GBK, 会显示乱码).\n"
        "\n"
        "下单约定 (对齐 qmt-model-script / pitfalls 7.1):\n"
        "  - DRY_RUN: 只打印, 模拟 T+1, 不 passorder\n"
        "  - 回测: passorder + 即时落状态; 可卖=bt_held-bt_locked; skip 不清仓\n"
        "  - 实盘: passorder 后 pending, 成交后才改仓; 可卖=m_nCanUseVolume\n"
        '"""',
        '"""TrendPB Basket v1.0 - 趋势回调(国金终端 / 中证央企红利50池).\n'
        "\n"
        "主图: 建议挂 000825.SH 日线. 池子=中证中央企业红利成分股(~50).\n"
        "部署: python scripts/qmt/_deploy_qmt_gbk_basket.py -> TrendPBBasket.py (GBK).\n"
        "单标的版见 qmt_terminal_trend_pb.py; 请编辑本仓库 UTF-8 源, 勿直接开 QMT 目录 GBK 文件.\n"
        "\n"
        "下单约定 (对齐 qmt-model-script / pitfalls 7.1):\n"
        "  - DRY_RUN: 只打印, 模拟 T+1, 不 passorder\n"
        "  - 回测: passorder + 即时落状态; 可卖=bt_held-bt_locked; skip 不清仓\n"
        "  - 实盘: passorder 后 pending, 成交后才改仓; 可卖=m_nCanUseVolume\n"
        "  - 按标的分状态(book); 同时持仓上限 MAX_HOLDINGS\n"
        '"""',
    )

    text = text.replace("DRY_RUN = False", "DRY_RUN = True", 1)
    text = text.replace(
        "# 单笔买入预算（元）\nTRADE_BUDGET = 50000.0\n",
        "# 单笔买入预算（元）\n"
        "TRADE_BUDGET = 10000.0\n"
        "# 同时持仓上限（只）；满仓后不再开新仓，已有仓位照常卖\n"
        "MAX_HOLDINGS = 10\n"
        "\n"
        "# 股票池: 中证中央企业红利 000825.SH (~50)\n"
        'POOL_INDEX = "000825.SH"\n'
        'POOL_SECTOR_NAMES = ("中证中央企业红利", "央企红利", "中证央企红利")\n'
        "# 取池失败时的兜底列表(可手填); 空则仅用主图品种\n"
        "POOL_FALLBACK = []\n",
    )
    text = text.replace(
        'STATE_FILE = r"D:\\service\\GJQMT\\python\\trend_pb_qmt_state.json"',
        'STATE_FILE = r"D:\\service\\GJQMT\\python\\trend_pb_basket_qmt_state.json"',
    )
    text = text.replace('STRATEGY_NAME = "TrendPB"', 'STRATEGY_NAME = "TrendPBBasket"')
    text = text.replace('STRATEGY_VER = "v1.0"', 'STRATEGY_VER = "v1.0-basket"')

    old_a = "A = _S()\n\n\ndef _lot(price, budget):"
    if old_a not in text:
        raise SystemExit("A=_S block not found")
    text = text.replace(old_a, BOOK_HELPERS + "\ndef _lot(price, budget):")

    old_state_start = "# -------------------- 状态 IO --------------------\n"
    old_state_end = "\ndef _has_position():"
    i0 = text.find(old_state_start)
    i1 = text.find(old_state_end)
    if i0 < 0 or i1 < 0:
        raise SystemExit("state block markers missing")
    text = text[:i0] + NEW_STATE + text[i1:]

    old_buy = (
        "def _order_buy(C, price, now, swing_low=0.0):\n"
        '    if getattr(A, "pending", None):\n'
        '        print("%s buy skip: pending active" % STRATEGY_NAME)\n'
        "        return False\n"
        '    if _has_position() or (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100):\n'
        '        print("%s buy skip: already holding" % STRATEGY_NAME)\n'
        "        return False\n"
        '    if "BUY" in getattr(A, "acted", set()):\n'
        "        return False\n"
    )
    new_buy = (
        "def _order_buy(C, price, now, swing_low=0.0):\n"
        '    if getattr(A, "pending", None):\n'
        '        print("%s buy skip: pending active" % STRATEGY_NAME, A.stock)\n'
        "        return False\n"
        '    if _has_position() or (getattr(A, "is_backtest", False) and _bt_held_vol() >= 100):\n'
        '        print("%s buy skip: already holding" % STRATEGY_NAME, A.stock)\n'
        "        return False\n"
        '    if "BUY" in getattr(A, "acted", set()):\n'
        "        return False\n"
        "    if _count_holdings() >= int(MAX_HOLDINGS):\n"
        '        print("%s buy skip: max holdings" % STRATEGY_NAME, MAX_HOLDINGS, A.stock)\n'
        "        return False\n"
    )
    if old_buy not in text:
        raise SystemExit("order_buy head not found")
    text = text.replace(old_buy, new_buy)

    idx = text.find("def _available_cash")
    if idx < 0:
        raise SystemExit("available_cash not found")
    text = text[:idx] + BATCH_FN + text[idx:]

    start = text.find("def _handle(C):")
    end = text.find("\ndef handlebar(C):")
    if start < 0 or end < 0:
        raise SystemExit("handle/init markers missing")
    text = text[:start] + NEW_HANDLE_INIT.lstrip("\n") + text[end + 1 :]

    compile(text, str(DST), "exec")
    DST.write_text(text, encoding="utf-8")
    print("OK wrote", DST, "lines", len(text.splitlines()))


if __name__ == "__main__":
    main()
