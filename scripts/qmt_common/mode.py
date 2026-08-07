# === qmt_common/mode.py ===
# 作用: 回测/实盘模式、暖机切换、K 线时间
# 主要符号: _refresh_mode, _is_backtest, _bar_datetime
# 钩子: _load_state；可选 _reconcile_with_broker
def _is_backtest(C):
    return bool(getattr(C, "do_back_test", False))


def _on_mode_switch_to_live(C):
    """暖机结束: 切到实盘语义（STATE / pending / 墙钟）。"""
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
    try:
        _load_state()
    except Exception as e:
        print(_strategy_tag(), "live switch load_state fail", e)
        _event_log("live_switch_load_state_fail", error=str(e))
    if not hasattr(A, "pending"):
        A.pending = None
    recon = globals().get("_reconcile_with_broker")
    if callable(recon):
        try:
            recon()
        except Exception as e:
            print(_strategy_tag(), "live switch reconcile fail", e)
            _event_log("live_switch_reconcile_fail", error=str(e))


def _refresh_mode(C):
    """每根 K 刷新 A.is_backtest。

    国金模型交易常先以 do_back_test=True 暖机历史，
    再进入同一根最新 K 做实时，而标志可能仍为 True。
    追赶规则: 今日最新 K 上 barpos 不变的第 2 次及以后调用 => 实盘。
    """
    prev = getattr(A, "is_backtest", None)
    raw = bool(getattr(C, "do_back_test", False))
    A.do_back_test_raw = raw
    use_bt = raw
    if raw:
        try:
            if C.is_last_bar():
                bp = int(getattr(C, "barpos", 0) or 0)
                last_bp = int(getattr(A, "_mode_last_bp", -1))
                hits = int(getattr(A, "_mode_same_bp_hits", 0) or 0)
                if bp == last_bp and bp >= 0:
                    hits += 1
                else:
                    hits = 0
                A._mode_last_bp = bp
                A._mode_same_bp_hits = hits
                bar_day = _bar_datetime(C).strftime("%Y%m%d")
                today = datetime.datetime.now().strftime("%Y%m%d")
                if bar_day == today and hits >= 1:
                    use_bt = False
        except Exception:
            pass
    else:
        A._mode_same_bp_hits = 0

    A.is_backtest = use_bt
    if prev is True and (not use_bt):
        _on_mode_switch_to_live(C)
    elif prev is False and use_bt:
        print(_strategy_tag(), "mode switch live -> backtest raw=", raw)
        _event_log("mode_switch", direction="live_to_backtest", raw=raw)
    return use_bt


def _bar_datetime(C):
    """回测用 K 线时间；实盘用墙钟。

    注意: 若调用方已判定实盘，可直接用 datetime.now()；
    本函数在无法解析 timetag 时回退墙钟。
    """
    try:
        tag = C.get_bar_timetag(C.barpos)
        if "timetag_to_datetime" in globals():
            s = timetag_to_datetime(tag, "%Y%m%d%H%M%S")
            return datetime.datetime.strptime(str(s), "%Y%m%d%H%M%S")
        if tag > 10**12:
            return datetime.datetime.fromtimestamp(tag / 1000.0)
        return datetime.datetime.fromtimestamp(tag)
    except Exception:
        return datetime.datetime.now()
