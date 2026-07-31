# === hongli/runtime.py ===
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
def init(C):
    # 尽早设 busy，避免 init 半截时 handlebar 因 A.busy 崩溃
    A.busy = False
    A._hb_at = None
    try:
        _init_impl(C)
    except Exception as e:
        print("HongliT init error", e)
        try:
            traceback.print_exc()
        except Exception:
            pass


def _init_impl(C):
    # 标的来自主图；账号优先模型交易界面，否则用配置
    A.stock = C.stockcode + "." + C.market
    A.period = _resolve_period(C)
    A.intraday = _is_intraday(A.period)
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
    A._mode_last_bp = -1
    A._mode_same_bp_hits = 0
    A.do_back_test_raw = _is_backtest(C)
    A.is_backtest = A.do_back_test_raw

    do_dl = DOWNLOAD_HIST_BACKTEST if A.is_backtest else DOWNLOAD_HIST_LIVE
    if do_dl:
        try:
            _download_hist(A.stock, A.period)
            if bool(REQUIRE_ABOVE_DAILY_MA):
                _download_hist(A.stock, "1d")
        except Exception as e:
            print("HongliT download_hist abort-safe", e)
    else:
        print(
            "HongliT skip download_history (live); use local cache PERIOD=",
            A.period,
        )

    if A.is_backtest:
        # QMT 可能中途再调 init；若清空浮仓会导致 passorder 成交变孤儿。
        # 全新开始: 首次回测会话 或 barpos 接近 0（新回放）。
        barpos = 0
        try:
            barpos = int(getattr(C, "barpos", 0) or 0)
        except Exception:
            barpos = 0
        fresh = (not getattr(A, "_bt_alive", False)) or (barpos <= 0)
        if fresh:
            A.float_a = None
            A.float_b = None
            A.acted_day = ""
            A.acted = set()
            A.cooldown_until = ""
            A.pending = None
            A.bt_held = 0
            A.bt_locked = 0
            A.bt_lock_day = ""
            A.bt_opened_at = ""
            A._bt_alive = True
            A.ready_logged = False
            print("HongliT backtest session start barpos=", barpos)
        else:
            if not hasattr(A, "bt_held"):
                A.bt_held = _sell_float_vol()
            if not hasattr(A, "acted") or A.acted is None:
                A.acted = set()
            if not hasattr(A, "cooldown_until"):
                A.cooldown_until = ""
            if not hasattr(A, "pending"):
                A.pending = None
            _bt_recover_float()
            print(
                "HongliT backtest re-init preserve barpos=",
                barpos,
                "float_a=",
                A.float_a,
                "bt_held=",
                _bt_held_vol(),
            )
    else:
        _load_state()
        # False -> 实盘首根决策 K 必打印 close=/J=
        A.ready_logged = False
        if not hasattr(A, "cooldown_until"):
            A.cooldown_until = ""
        if not hasattr(A, "pending"):
            A.pending = None
        try:
            _reconcile_float_with_broker()
        except Exception as e:
            print("HongliT reconcile fail", e)

    try:
        C.set_universe([A.stock])
    except Exception as e:
        print("HongliT set_universe fail", e)

    print(
        "HongliT v2.19 init",
        A.stock,
        A.acct,
        A.acct_type,
        "PERIOD=",
        A.period,
        "cfg=",
        PERIOD,
        "chart=",
        getattr(C, "period", None),
        "riskRules=",
        _use_risk_rules(),
        "B=",
        _enable_float_b(),
        "baseShares=",
        _base_shares(),
        "exitAfter=",
        (EXIT_AFTER if getattr(A, "intraday", False) else "-") if _use_risk_rules() else "-",
        "stopIgnoreExit=",
        STOP_LOSS_IGNORE_EXIT_AFTER if _use_risk_rules() else False,
        "maxHoldDays=",
        MAX_HOLD_DAYS if _use_risk_rules() else 0,
        "maxHoldHard=",
        MAX_HOLD_HARD_DAYS if _use_risk_rules() else 0,
        "cdWin/Loss=",
        ("%s/%s" % (COOLDOWN_BARS, COOLDOWN_BARS_LOSS)) if _use_risk_rules() else "-",
        "cdUntil=",
        getattr(A, "cooldown_until", "") or "-",
        "noEntryAfter=",
        (NO_ENTRY_AFTER if getattr(A, "intraday", False) else "-") if _use_risk_rules() else "-",
        "stopLoss=",
        STOP_LOSS if _use_risk_rules() else 0,
        "dailyMA=",
        ("on/MA%d" % int(DAILY_MA_N)) if REQUIRE_ABOVE_DAILY_MA else "off",
        "DRY_RUN=",
        DRY_RUN,
        "BACKTEST=",
        A.is_backtest,
        "rawBT=",
        getattr(A, "do_back_test_raw", A.is_backtest),
        "bt_held=",
        _bt_held_vol() if A.is_backtest else "-",
        "hbSec=",
        LIVE_HEARTBEAT_SEC,
        "dlLive=",
        DOWNLOAD_HIST_LIVE,
        "STATE=",
        STATE_FILE,
    )


def handlebar(C):
    # 实盘: 仅最新 K；回测: 每根（OHLC 未就绪则内部跳过）
    try:
        # 须在 is_last_bar 门控前刷新（国金暖机 -> 实盘）
        is_bt = _refresh_mode(C)
        if (not is_bt) and (not C.is_last_bar()):
            return
        if getattr(A, "busy", False):
            return
        A.busy = True
        try:
            if is_bt and (C.barpos % 100 == 0):
                print("HongliT progress barpos=", C.barpos, "time=", _bar_end_yyyymmdd(C))
            _handle(C)
        except Exception as e:
            print("HongliT handlebar error", e)
            try:
                traceback.print_exc()
            except Exception:
                pass
        finally:
            A.busy = False
    except Exception as e:
        print("HongliT handlebar outer error", e)
        try:
            A.busy = False
        except Exception:
            pass
