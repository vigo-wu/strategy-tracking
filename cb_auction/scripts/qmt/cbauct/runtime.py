# === cbauct/runtime.py ===
def init(C):
    A.busy = False
    A._hb_at = None
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
    if not hasattr(A, "buy_done_day"):
        A.buy_done_day = ""
    if not hasattr(A, "sz_preplace_day"):
        A.sz_preplace_day = ""
    if not hasattr(A, "sz_close_buy_day"):
        A.sz_close_buy_day = ""
    if not hasattr(A, "sz_escalate_day"):
        A.sz_escalate_day = ""
    if not hasattr(A, "sz_escalate_alert_ms"):
        A.sz_escalate_alert_ms = 0.0
    if not hasattr(A, "sh_chase_day"):
        A.sh_chase_day = ""
    if not hasattr(A, "sh_last_order_px"):
        A.sh_last_order_px = 0.0
    if not hasattr(A, "sh_chase_at_ms"):
        A.sh_chase_at_ms = 0.0


def _init_impl(C):
    A.stock = C.stockcode + "." + C.market
    A.period = _resolve_period(C, default="1m")
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
    A._diag = set()

    do_dl = DOWNLOAD_HIST_BACKTEST if A.is_backtest else DOWNLOAD_HIST_LIVE
    if do_dl:
        try:
            _download_hist(A.stock, A.period)
        except Exception as e:
            print("%s download_hist abort-safe" % STRATEGY_NAME, e)
    else:
        print("%s skip download_history (live)" % STRATEGY_NAME, A.period)

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
            A.sz_preplace_day = ""
            A.sz_close_buy_day = ""
            A.sz_escalate_day = ""
            A.sz_escalate_alert_ms = 0.0
            A.sh_chase_day = ""
            A.sh_last_order_px = 0.0
            A.sh_chase_at_ms = 0.0
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

    size_yi = _issue_size_yi()
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
        "reopen_cap=",
        _reopen_cap(),
        "limit_up=",
        _limit_up(),
        "size_yi=",
        size_yi,
        "sz_pre=",
        "%s-%s" % (SZ_PREPLACE_START, SZ_PREPLACE_END),
        "sz_close=",
        "%s-%s" % (SZ_CLOSE_BUY_START, SZ_CLOSE_BUY_END),
        "sh_chase=",
        "%s-%s" % (SH_CHASE_START, SH_CHASE_END),
        "chase_ms=",
        SH_CHASE_INTERVAL_MS,
        "chase_mode=",
        SH_CHASE_MODE,
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
        size_yi=size_yi,
        reopen_cap=_reopen_cap(),
        limit_up=_limit_up(),
        log_dir=str(globals().get("LOG_DIR") or ""),
    )


def handlebar(C):
    try:
        _refresh_mode(C)
        if getattr(A, "busy", False):
            return
        A.busy = True
        _handle(C)
    except Exception as e:
        print("%s handlebar error" % STRATEGY_NAME, e)
        _event_log("handlebar_error", error=str(e))
        try:
            traceback.print_exc()
        except Exception:
            pass
    finally:
        A.busy = False
