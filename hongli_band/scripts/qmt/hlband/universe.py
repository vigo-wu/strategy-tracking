# === hlband/universe.py ===
# 单实例监视 BOOK_STOCKS：切票上下文、run_time 扫池、账本 eval/exec 两轮。
# 日线主图上 start="" 可能只回调一次；盘中改立即重复，盘前挂 09:30:00；handlebar 看门狗补扫。
_UNIVERSE_TIMER_INTERVAL = "1nSecond"
_UNIVERSE_TIMER_START = "09:30:00"
_HANDLEBAR_PUMP_STALE_SEC = 2.0
_UNIVERSE_UI_KEYS = (
    "ready_logged",
    "_bar_status_at",
    "_bar_sig_prev",
    "_skip_sell_eval_logged",
    "_defer_log_entry_day",
    "_defer_log_exit_day",
    "_defer_log_book_day",
    "_defer_log_wait_day",
)


def _watch_stocks():
    """BOOK_STOCKS 代码列表（保持配置键原样）。"""
    mp = _book_stock_map()
    if not mp:
        return []
    return sorted(list(mp.keys()))


def _watch_universe_codes():
    """交易池 + 时钟主图（不在池内时）。暖机 init 也是 do_back_test，不能只订主图。"""
    codes = []
    seen = set()
    for x in list(getattr(A, "watch", None) or []) or _watch_stocks():
        s = str(x or "").strip()
        if (not s) or (s in seen):
            continue
        seen.add(s)
        codes.append(s)
    chart = str(getattr(A, "chart_stock", "") or "").strip()
    if chart and chart not in seen:
        codes.append(chart)
    return codes


def _apply_watch_universe(C):
    codes = _watch_universe_codes()
    if not codes:
        return
    try:
        C.set_universe(codes)
        print(
            _strategy_tag(),
            "set_universe n=%s" % len(codes),
            ",".join(codes),
        )
        _event_log("set_universe", n=len(codes), stocks=codes)
    except Exception as e:
        print("%s set_universe fail" % STRATEGY_NAME, e)
        _event_log("set_universe_fail", error=str(e))


def _is_local_bt(C=None):
    """CSV 无头回放：必须一图一票走 _handle，不能当成指数暖机 skip。"""
    if C is not None and bool(getattr(C, "_local_bt", False)):
        return True
    return bool(globals().get("_LOCAL_BT"))


def _chart_in_watch():
    chart = _norm_code(getattr(A, "chart_stock", ""))
    watch = getattr(A, "watch", None) or []
    if (not chart) or (not watch):
        return False
    for x in watch:
        if _norm_code(x) == chart:
            return True
    return False


def _per_stock_map():
    d = getattr(A, "_per_stock", None)
    if not isinstance(d, dict):
        d = {}
        A._per_stock = d
    return d


def _stash_stock_ui(code):
    code = str(code or "").strip()
    if not code:
        return
    rec = dict(_per_stock_map().get(code) or {})
    for k in _UNIVERSE_UI_KEYS:
        rec[k] = getattr(A, k, None)
    _per_stock_map()[code] = rec


def _restore_stock_ui(code):
    code = str(code or "").strip()
    rec = _per_stock_map().get(code) if code else None
    if not isinstance(rec, dict):
        A.ready_logged = False
        A._bar_status_at = None
        A._bar_sig_prev = None
        return
    for k in _UNIVERSE_UI_KEYS:
        if k in rec:
            setattr(A, k, rec[k])


def _activate_stock(code):
    """保存当前票 → reset extra → 切 A.stock → load 该票 STATE。"""
    code = str(code or "").strip()
    if not code:
        return ""
    cur = str(getattr(A, "stock", "") or "").strip()
    if cur == code:
        return code
    if cur:
        _stash_stock_ui(cur)
        if not getattr(A, "is_backtest", False):
            _save_state()
    _reset_stock_ctx()
    A.stock = code
    _restore_stock_ui(code)
    if not getattr(A, "is_backtest", False):
        _load_state()
        _restore_stock_ui(code)
    return code


def _timer_session_idle(now_s):
    s = str(now_s or "")
    if "113000" <= s < "130000":
        return True
    if s >= "160000" or s < "093000":
        return True
    return False


def _universe_timer_starts(now_s=None, now=None):
    """禁止空串起始：本终端日线上 start='' 不会重复回调。盘中再挂数秒后的墙钟。"""
    if now is None:
        now = datetime.datetime.now()
    s = str(now_s or "") or _bar_hhmmss(now)
    start0 = str(globals().get("UNIVERSE_TIMER_START") or _UNIVERSE_TIMER_START)
    starts = [start0]
    if "093000" <= s < "160000":
        soon = (now + datetime.timedelta(seconds=2)).strftime("%H:%M:%S")
        if soon not in starts:
            starts.append(soon)
    return starts


def _routine_log_sec():
    try:
        n = int(globals().get("LIVE_HEARTBEAT_SEC") or 300)
    except Exception:
        n = 300
    return n if n > 0 else 300


def _log_timer_gate(reason):
    """busy / backtest / idle / clock_gate 不再静默。"""
    now = datetime.datetime.now()
    last = getattr(A, "_timer_gate_at", None)
    last_r = str(getattr(A, "_timer_gate_reason", "") or "")
    why = str(reason or "")
    if last is not None and last_r == why:
        try:
            if (now - last).total_seconds() < _routine_log_sec():
                return
        except Exception:
            pass
    A._timer_gate_at = now
    A._timer_gate_reason = why
    print(_strategy_tag(), "timer skip", why)
    _event_log("timer_skip", reason=why)


def _mark_timer_alive():
    A._universe_timer_at = datetime.datetime.now()


def _timer_stale_sec():
    last = getattr(A, "_universe_timer_at", None)
    if last is None:
        return 1e9
    try:
        return float((datetime.datetime.now() - last).total_seconds())
    except Exception:
        return 1e9


def _register_universe_timer(C, why="init"):
    interval = str(
        globals().get("UNIVERSE_TIMER_INTERVAL") or _UNIVERSE_TIMER_INTERVAL
    )
    func = str(globals().get("UNIVERSE_TIMER_FUNC") or "universe_on_timer")
    ok = False
    for start in _universe_timer_starts():
        try:
            C.run_time(func, interval, start)
            ok = True
            print(
                _strategy_tag(),
                "run_time",
                func,
                interval,
                "start=",
                start,
                "why=",
                why,
            )
            _event_log(
                "run_time_register",
                func=func,
                interval=interval,
                start=start,
                why=str(why),
            )
        except Exception as e:
            print("%s run_time register fail" % STRATEGY_NAME, start, e)
            _event_log("run_time_fail", error=str(e), start=start, why=str(why))
    if ok:
        A._timer_reg = True
    return ok


def _subscribe_clock_quote(C):
    """日线 handlebar 盘中可能不再触发；订时钟图 1m/分笔作第二看门狗。"""
    A._clock_C = C
    chart = str(getattr(A, "chart_stock", "") or "").strip()
    if not chart:
        return False
    fn = getattr(C, "subscribe_quote", None) or getattr(C, "subscribe", None)
    if not callable(fn):
        print(_strategy_tag(), "subscribe_quote unavailable")
        _event_log("subscribe_quote_unavailable")
        return False

    def universe_on_quote(data):
        cc = getattr(A, "_clock_C", None) or C
        _pump_universe_from_handlebar(cc)

    A._quote_cb = universe_on_quote
    for period in ("1m", "tick", ""):
        try:
            if period:
                fn(chart, period=period, callback=universe_on_quote)
            else:
                fn(chart, callback=universe_on_quote)
            print(_strategy_tag(), "subscribe_quote", chart, period or "default")
            _event_log("subscribe_quote", stock=chart, period=period or "default")
            return True
        except TypeError:
            continue
        except Exception as e:
            print(_strategy_tag(), "subscribe_quote fail", period or "default", e)
            _event_log("subscribe_quote_fail", error=str(e), period=period or "")
            return False
    print(_strategy_tag(), "subscribe_quote skip no matching signature")
    _event_log("subscribe_quote_skip")
    return False


def _kick_universe_after_init(C):
    """不依赖 QMT 调度：init 结束后立刻扫一轮。"""
    if getattr(A, "is_backtest", False):
        return
    print(_strategy_tag(), "init kick universe")
    _event_log("init_kick_universe")
    try:
        _universe_on_timer(C, drive="init_kick")
    except Exception as e:
        print("%s init kick fail" % STRATEGY_NAME, e)
        _event_log("init_kick_fail", error=str(e))
        try:
            traceback.print_exc()
        except Exception:
            pass


def _pump_universe_from_handlebar(C):
    """日线 run_time 不回调时，用最新 K 的 handlebar 补扫；不按 tick 算指标。"""
    if getattr(A, "is_backtest", False):
        return
    if getattr(A, "busy", False):
        return
    now_s = _bar_hhmmss(datetime.datetime.now())
    if _timer_session_idle(now_s):
        return
    stale = _timer_stale_sec()
    if stale < _HANDLEBAR_PUMP_STALE_SEC:
        return
    if not getattr(A, "_timer_reg", False):
        _register_universe_timer(C, why="handlebar_stale")
    elif stale >= 30 and (not getattr(A, "_timer_rereg", False)):
        A._timer_rereg = True
        _register_universe_timer(C, why="handlebar_rereg")
    last_pump = getattr(A, "_hb_pump_log_at", None)
    now = datetime.datetime.now()
    if last_pump is None:
        do_log = True
    else:
        try:
            do_log = (now - last_pump).total_seconds() >= _routine_log_sec()
        except Exception:
            do_log = True
    if do_log:
        A._hb_pump_log_at = now
        print(_strategy_tag(), "handlebar pump universe stale=%.1fs" % stale)
        _event_log("handlebar_pump_universe", stale=stale)
    _universe_on_timer(C, drive="handlebar_pump")


def _compute_live_work(now_s, day):
    policy = str(globals().get("LIVE_OHLCV_POLICY") or "window").strip().lower()
    open_s = _cfg_hhmmss("OPEN_EXEC_START", "093000")
    open_e = _cfg_hhmmss("OPEN_EXEC_END", "094500")
    conf_s = _cfg_hhmmss("SIGNAL_CONFIRM_START", "145600")
    conf_e = _cfg_hhmmss("SIGNAL_CONFIRM_END", "160000")
    dec_s = str(globals().get("DECISION_START") or "093000")
    s = str(now_s or "")
    if s < dec_s or s > conf_e:
        return ""
    if policy == "always":
        return "signal"
    if open_s <= s < open_e:
        return "open_exec"
    if conf_s <= s <= conf_e:
        if str(getattr(A, "_universe_signal_done_day", "") or "") == str(day):
            return "pending"
        return "signal"
    return "pending"


def _ensure_clock_prev_closed(C, today):
    """时钟图上一根已收盘日，全池共用，避免每票再拉 8 根日 K。"""
    today = str(today or "")
    if (
        str(getattr(A, "_clock_prev_for", "") or "") == today
        and str(getattr(A, "clock_prev_closed_day", "") or "")
    ):
        return A.clock_prev_closed_day
    chart = str(getattr(A, "chart_stock", "") or "") or str(
        getattr(A, "stock", "") or ""
    )
    days = None
    try:
        if chart:
            days = _get_daily_bar_days(C, chart, count=8)
    except Exception:
        days = None
    prev = ""
    if days:
        last = str(days[-1])
        if last >= today and len(days) >= 2:
            prev = str(days[-2])
        elif last and last < today:
            prev = last
    if not prev:
        prev = _calendar_prev_weekday(today)
    A.clock_prev_closed_day = prev
    A._clock_prev_for = today
    return prev


def _log_book_checkin_missing(now_s):
    window = _book_window_id(now_s)
    if not window:
        return
    now = datetime.datetime.now()
    last = getattr(A, "_checkin_missing_at", None)
    if last is not None:
        try:
            if (now - last).total_seconds() < 30:
                return
        except Exception:
            pass
    data = _book_load()
    if str(data.get("window") or "") != window:
        names = {}
    else:
        names = data.get("names") if isinstance(data.get("names"), dict) else {}
    missing = []
    for code in getattr(A, "watch", None) or _watch_stocks():
        rec = names.get(code)
        if rec is None:
            rec = names.get(str(code).upper())
        if not (isinstance(rec, dict) and rec.get("checkin")):
            missing.append(code)
    if not missing:
        return
    A._checkin_missing_at = now
    print(
        "%s checkin missing=%s window=%s"
        % (STRATEGY_NAME, ",".join(missing), window)
    )
    _event_log("checkin_missing", missing=missing, window=window)


def _on_mode_switch_to_live(C):
    """覆盖 common:mode。宇宙模式禁止按时钟品种 load_state。"""
    print(
        _strategy_tag(),
        "mode switch backtest -> live",
        "raw_do_back_test=",
        getattr(A, "do_back_test_raw", None),
        "barpos=",
        getattr(C, "barpos", None),
    )
    _event_log(
        "mode_switch",
        direction="backtest_to_live",
        raw_do_back_test=getattr(A, "do_back_test_raw", None),
        barpos=getattr(C, "barpos", None),
    )
    A.ready_logged = False
    A._hb_at = None
    watch = list(getattr(A, "watch", None) or [])
    chart = str(getattr(A, "chart_stock", "") or "").strip()
    if watch and chart and (not _chart_in_watch()):
        print(
            _strategy_tag(),
            "live switch skip clock load chart=",
            chart,
        )
        _event_log("live_switch_skip_clock_load", chart=chart)
        _reset_stock_ctx()
        A.stock = ""
        A.pending = None
        _apply_watch_universe(C)
        A._timer_reg = False
        A._timer_rereg = False
        _register_universe_timer(C, why="mode_switch")
        return
    try:
        if str(getattr(A, "stock", "") or "").strip():
            _load_state()
        else:
            _reset_stock_ctx()
    except Exception as e:
        print(_strategy_tag(), "live switch load_state fail", e)
        _event_log("live_switch_load_state_fail", error=str(e))
    if not hasattr(A, "pending"):
        A.pending = None
    recon = globals().get("_reconcile_with_broker")
    if callable(recon) and str(getattr(A, "stock", "") or "").strip():
        try:
            recon()
        except Exception as e:
            print(_strategy_tag(), "live switch reconcile fail", e)
            _event_log("live_switch_reconcile_fail", error=str(e))
    _apply_watch_universe(C)
    A._timer_reg = False
    A._timer_rereg = False
    _register_universe_timer(C, why="mode_switch")


def _handle_universe(C):
    """实盘定时扫池。不依赖 is_last_bar。"""
    A._universe_loop = True
    if not str(getattr(A, "_drive", "") or ""):
        A._drive = "timer"
    ctx = _handle_clock_gate(C, from_timer=True)
    if ctx is None:
        _log_timer_gate("clock_gate")
        A._universe_loop = False
        A._live_work = ""
        return
    live_work = str(ctx.get("live_work") or "")
    A._live_work = live_work
    day = ctx.get("day")
    now = datetime.datetime.now()
    last_b = getattr(A, "_universe_begin_at", None)
    last_w = str(getattr(A, "_universe_begin_work", "") or "")
    if last_b is None or last_w != live_work:
        do_begin = True
    else:
        try:
            do_begin = (now - last_b).total_seconds() >= _routine_log_sec()
        except Exception:
            do_begin = True
    if do_begin:
        A._universe_begin_at = now
        A._universe_begin_work = live_work
        print(
            _strategy_tag(),
            "universe begin work=",
            live_work,
            "day=",
            day,
            "drive=",
            getattr(A, "_drive", "") or "-",
        )
        _event_log(
            "universe_begin",
            work=live_work,
            day=day,
            drive=getattr(A, "_drive", "") or "",
        )
    _ensure_clock_prev_closed(C, day)
    ctx["prev_closed"] = getattr(A, "clock_prev_closed_day", "")
    stocks = list(getattr(A, "watch", None) or _watch_stocks())
    if not stocks:
        _live_heartbeat("no_watch")
        A._universe_loop = False
        return
    _live_heartbeat(live_work)

    def _run_one(code, upass):
        try:
            _activate_stock(code)
            A._universe_pass = upass
            A._live_work = live_work
            _handle_stock(C, ctx)
            rec = _per_stock_map().get(code) or {}
            rec["_confirmed_eval_day"] = str(
                getattr(A, "_confirmed_eval_day", "") or ""
            )
            rec["_has_pend"] = bool(
                getattr(A, "pending_entry", None)
                or getattr(A, "pending_exit", None)
                or getattr(A, "pending", None)
            )
            _per_stock_map()[code] = rec
            _stash_stock_ui(code)
        except Exception as e:
            print("%s universe stock error" % STRATEGY_NAME, code, e)
            _event_log("universe_stock_error", stock=code, error=str(e))
            try:
                traceback.print_exc()
            except Exception:
                pass
        finally:
            A._universe_pass = ""

    if live_work == "pending":
        for code in stocks:
            _run_one(code, "")
    else:
        for code in stocks:
            _run_one(code, "eval")
        _log_book_checkin_missing(ctx.get("now_s"))
        for code in stocks:
            _run_one(code, "exec")
        if live_work == "signal":
            all_ok = True
            any_pend = False
            for code in stocks:
                rec = _per_stock_map().get(code) or {}
                if str(rec.get("_confirmed_eval_day", "") or "") != str(day):
                    all_ok = False
                if rec.get("_has_pend"):
                    any_pend = True
            if all_ok and (not any_pend):
                A._universe_signal_done_day = str(day)

    cur = str(getattr(A, "stock", "") or "").strip()
    if cur and (not getattr(A, "is_backtest", False)):
        _stash_stock_ui(cur)
        _save_state()
    A._universe_loop = False
    A._live_work = ""
    A._universe_pass = ""


def _universe_on_timer(C, drive="timer"):
    """C.run_time 回调。墙钟过滤时段；一进函数就打点，供 handlebar 看门狗判断死活。"""
    _mark_timer_alive()
    A._drive = str(drive or "timer")
    if getattr(A, "busy", False):
        _log_timer_gate("busy")
        return
    if not _chart_in_watch():
        try:
            _refresh_mode(C)
        except Exception:
            pass
    if getattr(A, "is_backtest", False):
        _log_timer_gate("is_backtest")
        return
    now = datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    if _timer_session_idle(now_s):
        _log_timer_gate("session_idle")
        return
    A.busy = True
    A._force_quicktrade = 2
    try:
        _handle_universe(C)
    except Exception as e:
        print("%s universe timer error" % STRATEGY_NAME, e)
        _event_log("universe_timer_error", error=str(e))
        try:
            traceback.print_exc()
        except Exception:
            pass
    finally:
        A._force_quicktrade = None
        A.busy = False
        A._drive = ""


def universe_on_timer(C):
    """QMT run_time 按全局函数名查找；下划线前缀进不了回调。"""
    _universe_on_timer(C, drive="timer")
