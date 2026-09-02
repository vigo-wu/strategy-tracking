# === hlband/universe.py ===
# 单实例监视 BOOK_STOCKS：切票上下文、run_time 扫池、账本 eval/exec 两轮。
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


def _ohlcv_prefetch_codes(live_work, stocks, day, prev_closed):
    """本轮会走 _get_ohlcv_1d/1w 的交易池子集。signal=全池；open_exec=未确认兜底或买入 pending。"""
    live_work = str(live_work or "")
    out_stocks = []
    for x in stocks or []:
        s = str(x or "").strip()
        if s:
            out_stocks.append(s)
    if live_work == "signal":
        return list(out_stocks)
    if live_work != "open_exec":
        return []
    pmap = getattr(A, "_per_stock", None)
    if not isinstance(pmap, dict) or not pmap:
        return list(out_stocks)
    prev_closed = str(prev_closed or "")
    day = str(day or "")
    need = []
    for code in out_stocks:
        rec = pmap.get(code)
        if not isinstance(rec, dict):
            rec = {}
            want = str(code).strip().upper()
            for k, v in pmap.items():
                if str(k or "").strip().upper() == want and isinstance(v, dict):
                    rec = v
                    break
        confirmed = str(rec.get("_confirmed_eval_day", "") or "")
        has_pend = bool(rec.get("_has_pend"))
        extra = rec.get("_hot_extra") if isinstance(rec.get("_hot_extra"), dict) else {}
        has_buy = bool(rec.get("_has_buy_pend")) or isinstance(
            extra.get("pending_entry"), dict
        )
        fb_done = str(
            rec.get("_fallback_done_day", "") or extra.get("fallback_done_day") or ""
        )
        need_fb = (
            (not has_pend)
            and (confirmed < prev_closed)
            and (fb_done != day)
        )
        if need_fb or has_buy:
            need.append(code)
    return need


def _per_stock_map():
    d = getattr(A, "_per_stock", None)
    if not isinstance(d, dict):
        d = {}
        A._per_stock = d
    return d


# 同票 STATE 磁盘重读间隔（秒）。未到期用内存热缓存，避免 2s 定时器刷 state loaded。
_STATE_RELOAD_SEC = 60


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


def _copy_state_dict(val):
    if isinstance(val, dict):
        return dict(val)
    return None


def _copy_state_lots(val):
    if not isinstance(val, list):
        return []
    out = []
    for lot in val:
        if isinstance(lot, dict):
            out.append(dict(lot))
    return out


def _stash_hot_state(code):
    """切票前把仓位/pending/extra 留在内存，供间隔内免读盘。"""
    code = str(code or "").strip()
    if not code:
        return
    _stash_stock_ui(code)
    rec = dict(_per_stock_map().get(code) or {})
    rec["_hot_position"] = _copy_state_dict(getattr(A, "position", None))
    rec["_hot_lots"] = _copy_state_lots(getattr(A, "lots", None))
    rec["_hot_acted_day"] = str(getattr(A, "acted_day", "") or "")
    rec["_hot_acted"] = set(getattr(A, "acted", set()) or [])
    rec["_hot_bt_held"] = int(getattr(A, "bt_held", 0) or 0)
    rec["_hot_bt_locked"] = int(getattr(A, "bt_locked", 0) or 0)
    rec["_hot_bt_lock_day"] = str(getattr(A, "bt_lock_day", "") or "")
    rec["_hot_bt_opened_at"] = str(getattr(A, "bt_opened_at", "") or "")
    pend = getattr(A, "pending", None)
    rec["_hot_pending"] = dict(pend) if isinstance(pend, dict) else None
    extra = {}
    fn = globals().get("_state_extra_save")
    if callable(fn):
        try:
            fn(extra)
        except Exception:
            extra = {}
    rec["_hot_extra"] = extra
    rec["_hot_ok"] = True
    _per_stock_map()[code] = rec


def _restore_hot_state(code):
    rec = _per_stock_map().get(code) if code else None
    if not (isinstance(rec, dict) and rec.get("_hot_ok")):
        return False
    pos = rec.get("_hot_position")
    A.position = dict(pos) if isinstance(pos, dict) else None
    A.lots = _copy_state_lots(rec.get("_hot_lots"))
    A.acted_day = str(rec.get("_hot_acted_day") or "")
    acted = rec.get("_hot_acted")
    if isinstance(acted, (set, list, tuple)):
        A.acted = set([str(x) for x in acted])
    else:
        A.acted = set()
    A.bt_held = int(rec.get("_hot_bt_held") or 0)
    A.bt_locked = int(rec.get("_hot_bt_locked") or 0)
    A.bt_lock_day = str(rec.get("_hot_bt_lock_day") or "")
    A.bt_opened_at = str(rec.get("_hot_bt_opened_at") or "")
    pend = rec.get("_hot_pending")
    A.pending = dict(pend) if isinstance(pend, dict) else None
    extra = rec.get("_hot_extra")
    fn = globals().get("_state_extra_load")
    if callable(fn) and isinstance(extra, dict):
        try:
            fn(extra)
        except Exception:
            pass
    _restore_stock_ui(code)
    return True


def _state_reload_due(code):
    rec = _per_stock_map().get(code) or {}
    last = rec.get("_state_loaded_at")
    if last is None or (not rec.get("_hot_ok")):
        return True
    try:
        sec = float(globals().get("_STATE_RELOAD_SEC") or 60)
        return (datetime.datetime.now() - last).total_seconds() >= sec
    except Exception:
        return True


def _live_load_state(code):
    """读盘。每票只在首次打印路径；之后静默（含 60s 重读）。"""
    rec = _per_stock_map().get(code) or {}
    log = not bool(rec.get("_state_path_logged"))
    _load_state(log=log)
    _restore_stock_ui(code)
    rec = dict(_per_stock_map().get(code) or {})
    rec["_state_path_logged"] = True
    rec["_state_loaded_at"] = datetime.datetime.now()
    _per_stock_map()[code] = rec
    _stash_hot_state(code)


def _activate_stock(code):
    """保存当前票 → reset extra → 切 A.stock → load 该票 STATE。"""
    code = str(code or "").strip()
    if not code:
        return ""
    cur = str(getattr(A, "stock", "") or "").strip()
    if cur == code:
        return code
    if cur:
        _stash_hot_state(cur)
        if not getattr(A, "is_backtest", False):
            _save_state()
    _reset_stock_ctx()
    A.stock = code
    _restore_stock_ui(code)
    if getattr(A, "is_backtest", False):
        # eval/exec 两轮：eval 写入的 pending_entry 在 _hot_extra，exec 前须恢复
        _restore_hot_state(code)
        return code
    if _state_reload_due(code):
        _live_load_state(code)
    elif not _restore_hot_state(code):
        _live_load_state(code)
    return code


def _timer_session_idle(now_s):
    """午休、开盘前、确认窗结束后空闲。晚盘截止跟 SIGNAL_CONFIRM_END，等于截止时刻仍工作。"""
    s = str(now_s or "")
    if "113000" <= s < "130000":
        return True
    conf_e = _cfg_hhmmss("SIGNAL_CONFIRM_END", "150000")
    dec_s = _cfg_hhmmss("DECISION_START", "093000")
    if s > conf_e or s < dec_s:
        return True
    return False


def _compute_live_work(now_s, day):
    policy = str(globals().get("LIVE_OHLCV_POLICY") or "window").strip().lower()
    open_s = _cfg_hhmmss("OPEN_EXEC_START", "093000")
    open_e = _cfg_hhmmss("OPEN_EXEC_END", "094500")
    conf_s = _cfg_hhmmss("SIGNAL_CONFIRM_START", "145600")
    conf_e = _cfg_hhmmss("SIGNAL_CONFIRM_END", "150000")
    dec_s = _cfg_hhmmss("DECISION_START", "093000")
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


def _handle_universe(C):
    """实盘定时扫池。不依赖 is_last_bar。"""
    A._universe_loop = True
    A._drive = "timer"
    ctx = _handle_clock_gate(C, from_timer=True)
    if ctx is None:
        A._universe_loop = False
        A._live_work = ""
        return
    live_work = str(ctx.get("live_work") or "")
    A._live_work = live_work
    day = ctx.get("day")
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
            rec["_fallback_done_day"] = str(
                getattr(A, "_fallback_done_day", "") or ""
            )
            rec["_has_pend"] = bool(
                getattr(A, "pending_entry", None)
                or getattr(A, "pending_exit", None)
                or getattr(A, "pending", None)
            )
            rec["_has_buy_pend"] = isinstance(
                getattr(A, "pending_entry", None), dict
            )
            _per_stock_map()[code] = rec
            _stash_hot_state(code)
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
        need_codes = _ohlcv_prefetch_codes(
            live_work, stocks, day, ctx.get("prev_closed")
        )
        try:
            if need_codes:
                _prefetch_watch_ohlcv(C, need_codes)
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
        finally:
            cache = getattr(A, "_ohlcv_cache", None)
            if isinstance(cache, dict):
                cache.clear()

    cur = str(getattr(A, "stock", "") or "").strip()
    if cur and (not getattr(A, "is_backtest", False)):
        _stash_hot_state(cur)
        _save_state()
    A._universe_loop = False
    A._live_work = ""
    A._universe_pass = ""


def _universe_on_timer(C):
    """定时扫池。时段过滤在此，不依赖 startTime。"""
    if getattr(A, "busy", False):
        return
    if not _chart_in_watch():
        try:
            _refresh_mode(C)
        except Exception:
            pass
    if getattr(A, "is_backtest", False):
        return
    now = datetime.datetime.now()
    now_s = _bar_hhmmss(now)
    if _timer_session_idle(now_s):
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


def check_market(C):
    """C.run_time 回调。必须是顶层公开函数名，与 init 注册字符串一致。"""
    n = int(getattr(A, "_timer_hits", 0) or 0) + 1
    A._timer_hits = n
    if n <= 5 or (n % 30) == 0:
        now_s = ""
        try:
            now_s = _bar_hhmmss(datetime.datetime.now())
        except Exception:
            pass
        print(
            "%s check_market hit=%s t=%s busy=%s bt=%s"
            % (
                STRATEGY_NAME,
                n,
                now_s,
                getattr(A, "busy", False),
                getattr(A, "is_backtest", None),
            )
        )
    _universe_on_timer(C)
