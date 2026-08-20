# === hlband/runtime.py ===
def _as_bool(val):
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "y", "是")


def _apply_panel():
    """策略交易注入 bind → 写回 config 全局。须由 init() 直接调用。"""
    g = globals()
    names = dict(g)
    try:
        import sys
        fr = sys._getframe(1)
        for _ in range(3):
            if fr is None:
                break
            names.update(fr.f_globals)
            names.update(fr.f_locals)
            fr = fr.f_back
    except Exception:
        pass
    applied = []
    for bind, const, kind in (g.get("PANEL_BINDS") or ()):
        if bind not in names:
            continue
        val = names[bind]
        cur = g.get(const)
        if kind == "bool":
            new = _as_bool(val)
        elif kind == "int":
            new = int(float(val))
        elif kind == "float":
            new = float(val)
        else:
            new = str(val)
        g[const] = new
        applied.append(const)
        if new != cur:
            print(_strategy_tag(), "panel", const, cur, "->", new)
        if const == "TRADE_BUDGET":
            g["TRADE_BUDGET_BY_STOCK"] = {}
    if applied:
        g["_PANEL_APPLIED"] = set(applied)
        print(_strategy_tag(), "panel applied", ",".join(applied))


def init(C):
    A.busy = False
    A._hb_at = None
    try:
        _apply_panel()
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
            A.time_force_trend_skip = False
            A.lots = []
            A.round_scaled = False
            A._confirmed_eval_day = ""
            A._fallback_done_day = ""
            A._w_bear_streak = 0
            A._w_bear_last_day = ""
            A._skip_sell_eval_day = ""
            A._last_add_day = ""
            A._last_add_signal = ""
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
            if not hasattr(A, "time_force_trend_skip"):
                A.time_force_trend_skip = False
            if not hasattr(A, "lots") or A.lots is None:
                A.lots = []
            if not hasattr(A, "round_scaled"):
                A.round_scaled = False
            if not hasattr(A, "_confirmed_eval_day"):
                A._confirmed_eval_day = ""
            if not hasattr(A, "_fallback_done_day"):
                A._fallback_done_day = ""
            if not hasattr(A, "_w_bear_streak"):
                A._w_bear_streak = 0
            if not hasattr(A, "_w_bear_last_day"):
                A._w_bear_last_day = ""
            if not hasattr(A, "_skip_sell_eval_day"):
                A._skip_sell_eval_day = ""
            if not hasattr(A, "_last_add_day"):
                A._last_add_day = ""
            if not hasattr(A, "_last_add_signal"):
                A._last_add_signal = ""
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
        if not hasattr(A, "time_force_trend_skip"):
            A.time_force_trend_skip = False
        if not hasattr(A, "lots") or A.lots is None:
            A.lots = []
        if not hasattr(A, "round_scaled"):
            A.round_scaled = False
        if not hasattr(A, "_confirmed_eval_day"):
            A._confirmed_eval_day = ""
        if not hasattr(A, "_fallback_done_day"):
            A._fallback_done_day = ""
        if not hasattr(A, "_w_bear_streak"):
            A._w_bear_streak = 0
        if not hasattr(A, "_w_bear_last_day"):
            A._w_bear_last_day = ""
        if not hasattr(A, "_skip_sell_eval_day"):
            A._skip_sell_eval_day = ""
        if not hasattr(A, "_last_add_day"):
            A._last_add_day = ""
        if not hasattr(A, "_last_add_signal"):
            A._last_add_signal = ""

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
        "dynamic_budget=",
        DYNAMIC_BUDGET,
        "BOOK_N=",
        _cfg_book_n(),
        "book_stocks=",
        ",".join(sorted(_book_stock_set())) or "-",
        "cash_ratio=",
        CASH_RATIO,
        "min_lot=",
        MIN_LOT,
        "max_name_frac=",
        MAX_NAME_FRAC,
        "equal_split=",
        EQUAL_SPLIT,
        "book_freeze=",
        "%s/%s" % (BOOK_FREEZE_CLOSE, BOOK_FREEZE_OPEN),
        "wMA=",
        "%d/%d/%d" % (W_MA_FAST, W_MA_MID, W_MA_LIFE),
        "dMA=",
        "%d/%d" % (D_MA_MID, D_MA_SLOW),
        "stop=",
        STOP_LOSS,
        "chase<",
        CHASE_MAX_PCT,
        "scale=",
        SCALE_ENABLE,
        "scale_lots=",
        SCALE_LOTS,
        "scale_once=",
        SCALE_ONCE_PER_ROUND,
        "scale_arm=",
        SCALE_ARM,
        "scale_arm_bars=",
        SCALE_ARM_BARS,
        "scale_plat=",
        "%d/%.2f" % (SCALE_PLAT_LOOKBACK, SCALE_PLAT_MAX_RANGE),
        "scale_w_expand=",
        SCALE_W_HIST_EXPAND_RATIO,
        "time_force_bars=",
        TIME_FORCE_BARS,
        "time_force_min_ret=",
        TIME_FORCE_MIN_RET,
        "close_exec=",
        "%s-%s" % (
            globals().get("PENDING_EXEC_START", "145750"),
            globals().get("PENDING_EXEC_END", "150000"),
        ),
        "open_exec=",
        "%s-%s" % (
            globals().get("OPEN_EXEC_START", "093000"),
            globals().get("OPEN_EXEC_END", "094500"),
        ),
    )
    _event_log(
        "init",
        acct=A.acct,
        acct_type=A.acct_type,
        period=A.period,
        backtest=A.is_backtest,
        dry_run=DRY_RUN,
        scale=SCALE_ENABLE,
        scale_lots=SCALE_LOTS,
        scale_once=SCALE_ONCE_PER_ROUND,
        scale_arm=SCALE_ARM,
        scale_arm_bars=SCALE_ARM_BARS,
        scale_w_hist_min=SCALE_W_HIST_MIN,
        scale_plat_lookback=SCALE_PLAT_LOOKBACK,
        scale_plat_max_range=SCALE_PLAT_MAX_RANGE,
        scale_w_hist_expand=SCALE_W_HIST_EXPAND_RATIO,
        time_force_bars=TIME_FORCE_BARS,
        time_force_min_ret=TIME_FORCE_MIN_RET,
        close_exec="%s-%s"
        % (
            globals().get("PENDING_EXEC_START", "145750"),
            globals().get("PENDING_EXEC_END", "150000"),
        ),
        open_exec="%s-%s"
        % (
            globals().get("OPEN_EXEC_START", "093000"),
            globals().get("OPEN_EXEC_END", "094500"),
        ),
        budget=_trade_budget_cap(),
        dynamic_budget=DYNAMIC_BUDGET,
        book_n=_cfg_book_n(),
        book_stocks=len(_book_stock_set()),
        cash_ratio=CASH_RATIO,
        min_lot=MIN_LOT,
        max_name_frac=MAX_NAME_FRAC,
        equal_split=EQUAL_SPLIT,
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
