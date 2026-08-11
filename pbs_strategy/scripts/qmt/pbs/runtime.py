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
        "am_buy_day": "",
        "sz_preplace_day": "",
        "sz_close_buy_day": "",
        "sz_escalate_day": "",
        "sz_escalate_alert_ms": 0.0,
        "sh_chase_day": "",
        "sh_last_order_px": 0.0,
        "sh_chase_at_ms": 0.0,
        "entry_mode": "",
    }
    for k, v in defaults.items():
        if not hasattr(A, k):
            setattr(A, k, v)


def _start_live_timer(C):
    """实盘注册 run_time：竞价/临停准点驱动；回测无效。"""
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
    try:
        try:
            C.run_time("_pbs_pulse", period, start, mkt)
        except TypeError:
            C.run_time("_pbs_pulse", period, start)
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
        A.live_timer_on = True
        return True
    except Exception as e:
        print("%s live timer FAIL" % STRATEGY_NAME, e)
        _event_log("live_timer_fail", error=str(e), period=period)
        A.live_timer_on = False
        return False


def _run_handle(C, drive):
    """分笔/定时器共用入口；busy 防重入。"""
    try:
        _refresh_mode(C)
        if getattr(A, "busy", False):
            return
        A.busy = True
        A.drive = str(drive or "")
        if drive == "timer":
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
    """run_time 回调：墙钟驱动（竞价/临停/追单准点）。"""
    if getattr(A, "is_backtest", False):
        return
    _run_handle(C, "timer")


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
            A.am_buy_day = ""
            A.sz_preplace_day = ""
            A.sz_close_buy_day = ""
            A.sz_escalate_day = ""
            A.sz_escalate_alert_ms = 0.0
            A.sh_chase_day = ""
            A.sh_last_order_px = 0.0
            A.sh_chase_at_ms = 0.0
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
        "modeA=",
        bool(globals().get("ENABLE_MODE_A", True)),
        "modeB=",
        bool(globals().get("ENABLE_MODE_B", True)),
        "buy_only=1",
        "timer=",
        timer_on,
        "timer_ms=",
        int(globals().get("LIVE_TIMER_MS") or 0),
        "am_px=",
        _morning_buy_price(),
        "reopen_cap=",
        _reopen_cap(),
        "limit_up=",
        _limit_up(),
        "sz_pre=",
        "%s-%s" % (SZ_PREPLACE_START, SZ_PREPLACE_END),
        "sz_esc=",
        "%s-%s" % (SZ_ESCALATE_CANCEL_START, SZ_ESCALATE_CANCEL_END),
        "sz_close=",
        "%s-%s" % (SZ_CLOSE_BUY_START, SZ_CLOSE_BUY_END),
        "sz_ready=",
        float(globals().get("SZ_CLOSE_READY_LAST") or 0),
        "sz_force=",
        str(globals().get("SZ_CLOSE_FORCE_AT") or ""),
        "sh_chase=",
        "%s-%s" % (SH_CHASE_START, SH_CHASE_END),
        "chase_ms=",
        SH_CHASE_INTERVAL_MS,
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
        mode_a=bool(globals().get("ENABLE_MODE_A", True)),
        mode_b=bool(globals().get("ENABLE_MODE_B", True)),
        buy_only=True,
        timer=timer_on,
        timer_ms=int(globals().get("LIVE_TIMER_MS") or 0),
        reopen_cap=_reopen_cap(),
        limit_up=_limit_up(),
        listing_day_only=bool(globals().get("LISTING_DAY_ONLY", True)),
        log_dir=str(globals().get("LOG_DIR") or ""),
    )


def handlebar(C):
    """分笔驱动：有行情时补跑；与定时器共用 _handle。"""
    _run_handle(C, "tick")
