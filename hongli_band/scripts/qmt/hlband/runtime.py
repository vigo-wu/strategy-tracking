# === hlband/runtime.py ===
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


def _init_impl(C):
    A.stock = C.stockcode + "." + C.market
    A.period = _resolve_period(C, default="1d")
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
            _download_hist(A.stock, "1w")
        except Exception as e:
            print("%s download_hist abort-safe" % STRATEGY_NAME, e)
    else:
        print("%s skip download_history (live)" % STRATEGY_NAME, A.period, "+1w")

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
            A.pending_entry = None
            A.pending_exit = None
            A.hold_peak = None
            A.hold_bars = 0
            A._hold_count_day = ""
            A.time_force_grace_until = None
            A._confirmed_eval_day = ""
            A._fallback_done_day = ""
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
            if not hasattr(A, "pending_entry"):
                A.pending_entry = None
            if not hasattr(A, "pending_exit"):
                A.pending_exit = None
            if not hasattr(A, "hold_peak"):
                A.hold_peak = None
            if not hasattr(A, "hold_bars"):
                A.hold_bars = 0
            if not hasattr(A, "_hold_count_day"):
                A._hold_count_day = ""
            if not hasattr(A, "time_force_grace_until"):
                A.time_force_grace_until = None
            if not hasattr(A, "_confirmed_eval_day"):
                A._confirmed_eval_day = ""
            if not hasattr(A, "_fallback_done_day"):
                A._fallback_done_day = ""
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
        if not hasattr(A, "pending_entry"):
            A.pending_entry = None
        if not hasattr(A, "pending_exit"):
            A.pending_exit = None
        if not hasattr(A, "hold_peak"):
            A.hold_peak = None
        if not hasattr(A, "hold_bars"):
            A.hold_bars = 0
        if not hasattr(A, "_hold_count_day"):
            A._hold_count_day = ""
        if not hasattr(A, "time_force_grace_until"):
            A.time_force_grace_until = None
        if not hasattr(A, "_confirmed_eval_day"):
            A._confirmed_eval_day = ""
        if not hasattr(A, "_fallback_done_day"):
            A._fallback_done_day = ""

    try:
        C.set_universe([A.stock])
    except Exception as e:
        print("%s set_universe fail" % STRATEGY_NAME, e)

    print(
        "%s %s init" % (STRATEGY_NAME, STRATEGY_VER),
        A.stock,
        A.acct,
        A.acct_type,
        "PERIOD=",
        A.period,
        "BACKTEST=",
        A.is_backtest,
        "DRY_RUN=",
        DRY_RUN,
        "budget=",
        _trade_budget_cap(),
        "wMA=",
        "%d/%d/%d" % (W_MA_FAST, W_MA_MID, W_MA_LIFE),
        "dMA=",
        "%d/%d" % (D_MA_MID, D_MA_SLOW),
        "stop=",
        STOP_LOSS,
        "chase<",
        CHASE_MAX_PCT,
    )
    _event_log(
        "init",
        acct=A.acct,
        acct_type=A.acct_type,
        period=A.period,
        backtest=A.is_backtest,
        dry_run=DRY_RUN,
        budget=_trade_budget_cap(),
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
