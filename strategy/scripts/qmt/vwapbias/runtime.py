# === vwapbias/runtime.py ===
def _as_bool(val):
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    return s in ("1", "true", "yes", "y", "是")


def _apply_panel():
    """策略交易注入 bind -> 写回 config 全局。须由 init() 直接调用。"""
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


def _reset_runtime_fields():
    A.position = None
    A.acted_day = ""
    A.acted = set()
    A.pending = None
    A.lots = []
    A.acted_closed = ""
    A.risk_skip_day = ""
    A.bt_held = 0
    A.bt_locked = 0
    A.bt_lock_day = ""
    A.bt_opened_at = ""
    A.ready_logged = False
    A._adv_cache_day = ""
    A._adv_cache_val = None
    A._preclose_day = ""
    A._preclose_val = None
    A._md_pandas_broken = False
    A._chart_bp = -2
    A._chart_pack = None
    A._ori_tail_bp = -9
    A._ori_tail_pack = None
    A._bt_prog = 0


def _ensure_runtime_fields():
    if not hasattr(A, "acted") or A.acted is None:
        A.acted = set()
    if not hasattr(A, "pending"):
        A.pending = None
    if not hasattr(A, "lots") or A.lots is None:
        A.lots = []
    if not hasattr(A, "acted_closed"):
        A.acted_closed = ""
    if not hasattr(A, "risk_skip_day"):
        A.risk_skip_day = ""
    if not hasattr(A, "bt_held"):
        A.bt_held = _pos_shares()
    if not hasattr(A, "ready_logged"):
        A.ready_logged = False
    if not hasattr(A, "_md_pandas_broken"):
        A._md_pandas_broken = False
    if not hasattr(A, "_chart_bp"):
        A._chart_bp = -2
    if not hasattr(A, "_chart_pack"):
        A._chart_pack = None
    if not hasattr(A, "_ori_tail_bp"):
        A._ori_tail_bp = -9
    if not hasattr(A, "_ori_tail_pack"):
        A._ori_tail_pack = None
    if not hasattr(A, "_bt_prog"):
        A._bt_prog = 0


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
            _download_hist(A.stock, "1m")
            _download_hist(A.stock, "1d")
        except Exception as e:
            print("%s download_hist abort-safe" % STRATEGY_NAME, e)
    else:
        print("%s skip download_history (live)" % STRATEGY_NAME, "1m+1d")

    if A.is_backtest:
        barpos = 0
        try:
            barpos = int(getattr(C, "barpos", 0) or 0)
        except Exception:
            barpos = 0
        fresh = (not getattr(A, "_bt_alive", False)) or (barpos <= 0)
        if fresh:
            _reset_runtime_fields()
            A._bt_alive = True
            print("%s backtest session start barpos=" % STRATEGY_NAME, barpos)
        else:
            _ensure_runtime_fields()
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
        _ensure_runtime_fields()
        A.ready_logged = False

    try:
        C.set_universe([A.stock])
    except Exception as e:
        print("%s set_universe fail" % STRATEGY_NAME, e)

    if str(A.period) != "1m":
        print(_strategy_tag(), "warn chart period=", A.period, "signals still use 1m")

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
        "VOL_STEP=",
        VOL_STEP,
        "ALLOW_T0=",
        ALLOW_T0,
        "SCALE_LOTS=",
        SCALE_LOTS,
        "BIAS_L1=",
        BIAS_L1,
        "BIAS_L2=",
        BIAS_L2,
        "BIAS_FADE=",
        BIAS_FADE,
        "TAKE_PROFIT=",
        TAKE_PROFIT,
        "TRAIL_ARM=",
        TRAIL_ARM,
        "TRAIL_GIVE=",
        TRAIL_GIVE,
        "LAST_DROP=",
        LAST_DROP,
        "IMPULSE_SUM=",
        IMPULSE_SUM,
        "DOWN_BARS=",
        DOWN_BARS,
        "STOP=",
        STOP_LOSS,
        "expect=",
        EXPECT_STOCK,
    )
    _event_log(
        "init",
        acct=A.acct,
        acct_type=A.acct_type,
        period=A.period,
        backtest=A.is_backtest,
        dry_run=DRY_RUN,
        budget=_trade_budget_cap(),
        vol_step=VOL_STEP,
        allow_t0=ALLOW_T0,
        scale_lots=SCALE_LOTS,
        bias_l1=BIAS_L1,
        bias_l2=BIAS_L2,
        bias_fade=BIAS_FADE,
        take_profit=TAKE_PROFIT,
        trail_arm=TRAIL_ARM,
        trail_give=TRAIL_GIVE,
        stop_loss=STOP_LOSS,
        expect=EXPECT_STOCK,
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
