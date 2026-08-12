# === pbs/runtime.py ===
def init(C):
    A.busy = False
    A._hb_at = None
    A.drive = ""
    A.passorder_quick = 1
    try:
        _init_impl(C)
    except Exception as e:
        print("%s init error" % STRATEGY_NAME, e)
        _event_log("init_error", error=str(e))
        try:
            traceback.print_exc()
        except Exception:
            pass


def _ensure_day_flags():
    defaults = {
        "buy_done_day": "",
        "entry_mode": "",
    }
    for k, v in defaults.items():
        if not hasattr(A, k):
            setattr(A, k, v)
    if not isinstance(getattr(A, "_log_at_ms", None), dict):
        A._log_at_ms = {}


def _start_live_timer(C):
    """实盘注册 run_time：50ms 轮询 + 14:56 预热 + 14:57 准点开火。"""
    if getattr(A, "is_backtest", False):
        return False
    if not bool(globals().get("ENABLE_LIVE_TIMER", True)):
        print("%s live timer disabled" % STRATEGY_NAME)
        return False
    ms = int(globals().get("LIVE_TIMER_MS") or 100)
    if ms < 50:
        ms = 50
    period = "%dnMilliSecond" % ms
    start = "2020-01-01 09:00:00"
    mkt = "SH" if _market_tag() == "SH" else "SZ"
    prewarm_at = str(globals().get("CLOSE_PREWARM_TIMER") or "2020-01-01 14:56:00")
    close_at = str(globals().get("CLOSE_FIRE_TIMER") or "2020-01-01 14:57:00")
    ok_any = False
    try:
        try:
            C.run_time("_pbs_pulse", period, start, mkt)
        except TypeError:
            C.run_time("_pbs_pulse", period, start)
        ok_any = True
        print(
            "%s live timer ON" % STRATEGY_NAME,
            period,
            "quickTrade=",
            int(globals().get("TIMER_QUICK_TRADE") or 2),
            "mkt=",
            mkt,
        )
        _event_log(
            "live_timer_on",
            period=period,
            ms=ms,
            quick_trade=int(globals().get("TIMER_QUICK_TRADE") or 2),
            market=mkt,
        )
    except Exception as e:
        print("%s live timer FAIL" % STRATEGY_NAME, e)
        _event_log("live_timer_fail", error=str(e), period=period)

    for name, when, fn in (
        ("prewarm", prewarm_at, "_pbs_prewarm_fire"),
        ("close_fire", close_at, "_pbs_close_fire"),
    ):
        try:
            try:
                C.run_time(fn, "1nDay", when, mkt)
            except TypeError:
                C.run_time(fn, "1nDay", when)
            ok_any = True
            print("%s %s timer ON" % (STRATEGY_NAME, name), when, "mkt=", mkt)
            _event_log("live_timer_slot", name=name, when=when, market=mkt)
        except Exception as e:
            print("%s %s timer FAIL" % (STRATEGY_NAME, name), e)
            _event_log("live_timer_slot_fail", name=name, error=str(e), when=when)

    A.live_timer_on = bool(ok_any)
    return bool(ok_any)


def _run_handle(C, drive):
    """分笔/定时器共用入口；busy 防重入。"""
    try:
        _refresh_mode(C)
        if getattr(A, "busy", False):
            return
        A.busy = True
        A.drive = str(drive or "")
        if drive in ("timer", "close_fire", "prewarm"):
            A.passorder_quick = int(globals().get("TIMER_QUICK_TRADE") or 2)
        else:
            A.passorder_quick = int(globals().get("TICK_QUICK_TRADE") or 1)
        _handle(C)
    except Exception as e:
        print("%s %s error" % (STRATEGY_NAME, drive or "handle"), e)
        _event_log("handle_error", drive=str(drive or ""), error=str(e))
        try:
            traceback.print_exc()
        except Exception:
            pass
    finally:
        A.busy = False
        A.drive = ""
        A.passorder_quick = 1


def _pbs_pulse(C):
    """run_time 回调：墙钟驱动（收盘申报重试）。"""
    if getattr(A, "is_backtest", False):
        return
    _run_handle(C, "timer")


def _pbs_prewarm_fire(C):
    """14:56 准点预热。"""
    if getattr(A, "is_backtest", False):
        return
    _run_handle(C, "prewarm")


def _pbs_close_fire(C):
    """14:57 准点开火。"""
    if getattr(A, "is_backtest", False):
        return
    _run_handle(C, "close_fire")


def _init_impl(C):
    A.stock = C.stockcode + "." + C.market
    A.period = _resolve_period(C, default="tick")
    chart_p = _norm_period(getattr(C, "period", None))
    if chart_p == "tick":
        A.period = "tick"
    if str(A.period) == "tick":
        if bool(globals().get("LIVE_ONLY_LAST_BAR", False)):
            print("%s tick period: prefer LIVE_ONLY_LAST_BAR=False" % STRATEGY_NAME)
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
    A.drive = ""
    A.passorder_quick = 1
    A.live_timer_on = False
    A.do_back_test_raw = _is_backtest(C)
    A.is_backtest = A.do_back_test_raw
    A._diag = set()

    do_dl = DOWNLOAD_HIST_BACKTEST if A.is_backtest else DOWNLOAD_HIST_LIVE
    if do_dl:
        try:
            _download_hist(A.stock, A.period)
        except Exception as e:
            print("%s download_hist abort-safe" % STRATEGY_NAME, e)
    else:
        print("%s skip download_history" % STRATEGY_NAME, A.period)

    if A.is_backtest:
        barpos = 0
        try:
            barpos = int(getattr(C, "barpos", 0) or 0)
        except Exception:
            barpos = 0
        fresh = (not getattr(A, "_bt_alive", False)) or (barpos <= 0)
        if fresh:
            A.position = None
            A.acted_day = ""
            A.acted = set()
            A.pending = None
            A.buy_done_day = ""
            A.entry_mode = ""
            A.bt_held = 0
            A.bt_locked = 0
            A.bt_lock_day = ""
            A.bt_opened_at = ""
            A._bt_alive = True
            A.ready_logged = False
            print("%s backtest session start barpos=" % STRATEGY_NAME, barpos)
        else:
            if not hasattr(A, "bt_held"):
                A.bt_held = _pos_shares()
            if not hasattr(A, "acted") or A.acted is None:
                A.acted = set()
            if not hasattr(A, "pending"):
                A.pending = None
            _ensure_day_flags()
            _bt_recover_position()
            print(
                "%s backtest re-init preserve barpos=" % STRATEGY_NAME,
                barpos,
                "pos=",
                A.position,
                "bt_held=",
                _bt_held_vol(),
            )
    else:
        _load_state()
        A.ready_logged = False
        if not hasattr(A, "pending"):
            A.pending = None
        _ensure_day_flags()
        try:
            _reconcile_with_broker()
        except Exception as e:
            print("%s reconcile fail" % STRATEGY_NAME, e)
            _event_log("reconcile_fail", error=str(e))

    try:
        C.set_universe([A.stock])
    except Exception as e:
        print("%s set_universe fail" % STRATEGY_NAME, e)

    timer_on = False
    if not A.is_backtest:
        timer_on = bool(_start_live_timer(C))

    mkt = _market_tag()
    print(
        "%s %s init" % (STRATEGY_NAME, STRATEGY_VER),
        A.stock,
        "mkt=",
        mkt,
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
        "lot=",
        LOT_SIZE,
        "modeB=",
        bool(globals().get("ENABLE_MODE_B", True)),
        "buy_only=1",
        "timer=",
        timer_on,
        "timer_ms=",
        int(globals().get("LIVE_TIMER_MS") or 0),
        "close=",
        "%s-%s" % (CLOSE_BUY_START, CLOSE_BUY_END),
        "close_px=",
        _close_buy_price(),
        "limit_up=",
        _limit_up(),
        "listing_only=",
        bool(globals().get("LISTING_DAY_ONLY", True)),
    )
    _event_log(
        "init",
        acct=A.acct,
        acct_type=A.acct_type,
        period=A.period,
        backtest=A.is_backtest,
        dry_run=DRY_RUN,
        budget=TRADE_BUDGET,
        mkt=mkt,
        mode_b=bool(globals().get("ENABLE_MODE_B", True)),
        buy_only=True,
        timer=timer_on,
        timer_ms=int(globals().get("LIVE_TIMER_MS") or 0),
        close_start=str(globals().get("CLOSE_BUY_START") or ""),
        close_end=str(globals().get("CLOSE_BUY_END") or ""),
        close_px=_close_buy_price(),
        limit_up=_limit_up(),
        listing_day_only=bool(globals().get("LISTING_DAY_ONLY", True)),
        log_dir=str(globals().get("LOG_DIR") or ""),
    )


def handlebar(C):
    """分笔驱动：有行情时补跑；与定时器共用 _handle。"""
    _run_handle(C, "tick")
