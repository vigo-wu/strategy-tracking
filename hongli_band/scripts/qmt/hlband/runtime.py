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


def _trail_arm():
    """档 1 起步 peak_lo；网格扫 TRAIL 时写进 init 指纹。"""
    tiers = globals().get("TRAIL_TIERS") or ()
    try:
        return float(tiers[0][0])
    except (IndexError, TypeError, ValueError):
        return None


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
    A.chart_stock = C.stockcode + "." + C.market
    if _is_local_bt(C):
        A.watch = [A.chart_stock]
    else:
        A.watch = _watch_stocks()
        if not A.watch:
            A.watch = [A.chart_stock]
    A.stock = A.chart_stock
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
    if A.is_backtest:
        if do_dl:
            try:
                _download_hist(A.stock, A.period)
                _download_hist(A.stock, "1w")
            except Exception as e:
                print("%s download_hist abort-safe" % STRATEGY_NAME, e)
        else:
            print("%s skip download_history (live)" % STRATEGY_NAME, A.period, "+1w")
    elif do_dl:
        for code in A.watch:
            try:
                _download_hist(code, A.period)
                _download_hist(code, "1w")
            except Exception as e:
                print("%s download_hist abort-safe" % STRATEGY_NAME, code, e)
    else:
        print(
            "%s skip download_history (live) n=%s" % (STRATEGY_NAME, len(A.watch)),
            A.period,
            "+1w",
        )

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
            A._bt_hb_logged = False
            A._bt_hb_skip_logged = False
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
        # 实盘宇宙：不按主图/时钟 load；第一轮定时回调再 _activate_stock
        _reset_stock_ctx()
        A.stock = ""
        A.ready_logged = False

    _apply_watch_universe(C)

    drive = "handlebar"
    if A.is_backtest:
        # 编辑器回测必须靠 handlebar 扫历史 K。注册 1nSecond 后终端可能改走墙钟
        # 定时、不再推进 barpos；而 _universe_on_timer 在 is_backtest 下直接 return，
        # 表现为 init 之后没有任何 close=/diag。
        print("%s backtest skip run_time drive=handlebar" % STRATEGY_NAME)
    else:
        drive = "timer"
        try:
            C.run_time("_universe_on_timer", "1nSecond", "")
            print(
                "%s run_time _universe_on_timer 1nSecond start=" % STRATEGY_NAME,
                "(immediate)",
            )
        except Exception as e:
            print("%s run_time register fail" % STRATEGY_NAME, e)
            _event_log("run_time_fail", error=str(e))

    uni = list(getattr(A, "watch", None) or [])
    print(
        "%s UNIVERSE n=%s stocks=%s chart=%s drive=%s 只保留一个 HlBand 实例"
        % (
            STRATEGY_NAME,
            len(uni),
            ",".join(uni) or "-",
            getattr(A, "chart_stock", "") or "-",
            drive,
        )
    )

    print(
        "%s %s init" % (STRATEGY_NAME, STRATEGY_VER),
        "chart=",
        getattr(A, "chart_stock", "") or "-",
        "stock=",
        getattr(A, "stock", "") or "-",
        A.acct,
        A.acct_type,
        "PERIOD=",
        A.period,
        "ohlcv_policy=",
        str(globals().get("LIVE_OHLCV_POLICY") or "window"),
        "DIVIDEND=",
        _dividend_type() if getattr(A, "stock", "") else "per-stock",
        "chart_div=",
        _chart_dividend(C) or "-",
        "BACKTEST=",
        A.is_backtest,
        "DRY_RUN=",
        DRY_RUN,
        "budget=",
        _trade_budget_cap(),
        "BOOK_N=",
        _cfg_book_n(),
        "book_stocks=",
        ",".join(sorted(_book_stock_set())) or "-",
        "cash_ratio=",
        CASH_RATIO,
        "lot_open_frac=",
        LOT_OPEN_FRAC,
        "lot_add_frac=",
        LOT_ADD_FRAC,
        "book_lot_max=",
        BOOK_LOT_MAX,
        "book_freeze=",
        "%s/%s" % (BOOK_FREEZE_CLOSE, BOOK_FREEZE_OPEN),
        "wMA=",
        "%d/%d/%d" % (W_MA_FAST, W_MA_MID, W_MA_LIFE),
        "dMA=",
        "%d/%d" % (D_MA_MID, D_MA_SLOW),
        "ma_type=",
        _ma_kind(),
        "stop=",
        STOP_LOSS,
        "trail_arm=",
        _trail_arm(),
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
            globals().get("PENDING_EXEC_START", "145600"),
            globals().get("PENDING_EXEC_END", "145700"),
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
        dividend=_dividend_type(),
        chart_div=_chart_dividend(C) or "",
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
        stop=STOP_LOSS,
        trail_arm=_trail_arm(),
        time_force_bars=TIME_FORCE_BARS,
        time_force_min_ret=TIME_FORCE_MIN_RET,
        close_exec="%s-%s"
        % (
            globals().get("PENDING_EXEC_START", "145600"),
            globals().get("PENDING_EXEC_END", "145700"),
        ),
        open_exec="%s-%s"
        % (
            globals().get("OPEN_EXEC_START", "093000"),
            globals().get("OPEN_EXEC_END", "094500"),
        ),
        budget=_trade_budget_cap(),
        book_n=_cfg_book_n(),
        book_stocks=len(_book_stock_set()),
        watch=len(getattr(A, "watch", None) or []),
        chart=getattr(A, "chart_stock", "") or "",
        ohlcv_policy=str(globals().get("LIVE_OHLCV_POLICY") or ""),
        cash_ratio=CASH_RATIO,
        lot_open_frac=LOT_OPEN_FRAC,
        lot_add_frac=LOT_ADD_FRAC,
        book_lot_max=BOOK_LOT_MAX,
        ma_type=_ma_kind(),
        log_dir=str(globals().get("LOG_DIR") or ""),
    )


def handlebar(C):
    try:
        _refresh_mode(C)
        bt = getattr(A, "is_backtest", False)
        if bt and (not getattr(A, "_bt_hb_logged", False)):
            A._bt_hb_logged = True
            print(
                "%s backtest handlebar start barpos=" % STRATEGY_NAME,
                getattr(C, "barpos", None),
                "busy=",
                getattr(A, "busy", False),
                "chart_in_watch=",
                _chart_in_watch(),
            )
        if getattr(A, "busy", False):
            return
        A.busy = True
        if bt:
            if _is_local_bt(C) or (not (getattr(A, "watch", None) or [])) or _chart_in_watch():
                _handle(C)
            elif not getattr(A, "_bt_hb_skip_logged", False):
                A._bt_hb_skip_logged = True
                print(
                    "%s backtest handlebar skip chart not in watch" % STRATEGY_NAME,
                    getattr(A, "chart_stock", ""),
                    "watch=",
                    ",".join(getattr(A, "watch", None) or []) or "-",
                )
        # 实盘暖机（主图不在池）：只 _refresh_mode。live 扫池只走 run_time。
    except Exception as e:
        print("%s handlebar error" % STRATEGY_NAME, e)
        _event_log("handlebar_error", error=str(e))
        try:
            traceback.print_exc()
        except Exception:
            pass
    finally:
        A.busy = False
