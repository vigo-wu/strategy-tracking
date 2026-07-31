# === hongli/strategy.py ===
# 作用: 交易决策：止损/R-Sell/MaxHold/R-A/R-B
# 主要符号: _handle
# 拼接序: 15/16 | 上一部: runtime.py | 下一部: _main_guard.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
def _handle(C):
    bt = getattr(A, "is_backtest", False)
    now = _bar_datetime(C) if bt else datetime.datetime.now()
    now_s = now.strftime("%H%M%S")
    day = now.strftime("%Y%m%d")
    intraday = getattr(A, "intraday", False)

    if not bt:
        # 先处理 pending（含 15:00 后成交/撤单）
        if getattr(A, "pending", None):
            if _process_pending(C, now):
                _live_heartbeat("pending")
                return
        # 实盘: 交易时段外不做新决策
        if now_s < "093000" or now_s > "150000":
            _live_heartbeat("outside_session")
            return
        # 日线+: 临近收盘窗；日内: 时段内每根最新 K
        if (not intraday) and (now_s < DECISION_START or now_s > DECISION_END):
            _live_heartbeat("wait_decision_window")
            return
        _live_heartbeat("in_session")
    # 回测: 每根约等于该 K 收盘决策
    if bt:
        _bt_roll_t1(day)
        _bt_recover_float(now=now)

    _reset_day(day)

    cash = _available_cash()
    if cash is None:
        _live_heartbeat("no_cash_or_login")
        return

    ohlc = _get_ohlc(C, A.stock)
    if ohlc is None:
        _live_heartbeat("ohlc_none")
        return
    high, low, close = ohlc
    ind = _calc_indicators(high, low, close)
    if ind is None:
        _live_heartbeat("ind_none")
        return
    lower, upper, j, last = ind
    if bt:
        _bt_recover_float(now=now, last=last)
    buy_cond = (last <= lower * LOWER_TOL) and (j <= 0)
    sell_cond = (last >= upper * UPPER_TOL) and (j >= 100)
    has_a = _has_leg(A.float_a)
    has_b = _has_leg(A.float_b)
    zero_float = (not has_a) and (not has_b)
    # 影子持仓拦住新 R-A（即使中途浮仓腿被清空）
    if bt and _bt_held_vol() >= 100:
        zero_float = False
    drop_vs_a = None
    if has_a:
        ap = float(A.float_a["price"])
        if ap > 0:
            drop_vs_a = (ap - last) / ap

    interesting = buy_cond or sell_cond or has_a or has_b or (bt and _bt_held_vol() >= 100)
    if (not getattr(A, "ready_logged", False)) or interesting or (C.barpos % 20 == 0):
        A.ready_logged = True
        print(
            "HongliT",
            getattr(A, "period", "?"),
            day,
            now_s,
            "n=%d close=%.4f lower=%.4f upper=%.4f J=%.2f buy=%s sell=%s A=%s B=%s dropA=%s bt_held=%s avail=%s"
            % (
                len(close),
                last,
                lower,
                upper,
                j,
                buy_cond,
                sell_cond,
                has_a,
                has_b,
                None if drop_vs_a is None else round(drop_vs_a * 100, 2),
                _bt_held_vol() if bt else "-",
                _bt_available_vol() if bt else "-",
            ),
        )

    # 实盘恢复的腿补 opened_at（避免立刻触发 MaxHold）
    if has_a and not A.float_a.get("opened_at"):
        A.float_a["opened_at"] = now.strftime("%Y%m%d%H%M%S")
        _save_state()

    hold_d = 0.0
    if has_a:
        hold_d = _hold_days(A.float_a.get("opened_at"), now)
    fret = _float_ret(last) if (has_a or has_b) else 0.0
    exit_ok = _exit_time_ok(now_s)

    # 软止损（先于 R-Sell）。可忽略 EXIT_AFTER 以抓住开盘跳空。
    stop_time_ok = exit_ok or bool(STOP_LOSS_IGNORE_EXIT_AFTER)
    if (
        _use_risk_rules()
        and float(STOP_LOSS) > 0
        and (has_a or has_b)
        and fret <= -float(STOP_LOSS)
        and stop_time_ok
        and ("SELL" not in A.acted)
        and (not getattr(A, "pending", None))
    ):
        sell_vol = _sell_float_vol()
        print(
            "HongliT StopLoss trigger ret=%.2f%% <= -%.2f%% now=%s exitGate=%s"
            % (fret * 100.0, float(STOP_LOSS) * 100.0, now_s, exit_ok)
        )
        _order_sell(C, sell_vol, "StopLoss", "StopLoss", last, now)
        return

    # 先做 R-Sell: 只清浮仓
    if sell_cond and (has_a or has_b) and ("SELL" not in A.acted) and (not getattr(A, "pending", None)):
        if not exit_ok:
            print("R-Sell defer until", EXIT_AFTER, "now=", now_s)
            return
        else:
            sell_vol = _sell_float_vol()
            _order_sell(C, sell_vol, "RSell", "R-Sell", last, now)
            return

    # 软最长持仓（仅亏损）+ 硬最长持仓防漏
    if (
        _use_risk_rules()
        and (has_a or has_b)
        and ("SELL" not in A.acted)
        and (not getattr(A, "pending", None))
    ):
        hard_n = int(MAX_HOLD_HARD_DAYS)
        soft_n = int(MAX_HOLD_DAYS)
        hard_hit = hard_n > 0 and hold_d >= float(hard_n)
        soft_hit = soft_n > 0 and hold_d >= float(soft_n)
        if soft_hit and (not hard_hit) and bool(MAX_HOLD_ONLY_LOSS) and fret >= 0:
            soft_hit = False  # 浮仓盈利: 等 R-Sell
        if hard_hit or soft_hit:
            if not exit_ok:
                print(
                    "MaxHold defer until",
                    EXIT_AFTER,
                    "now=",
                    now_s,
                    "hold=%.2f" % hold_d,
                    "ret=%.2f%%" % (fret * 100.0),
                    "hard=" + str(hard_hit),
                )
            else:
                tag = "MaxHoldHard" if hard_hit else "MaxHold"
                sell_vol = _sell_float_vol()
                print(
                    "HongliT %s trigger hold_days=%.2f soft=%s hard=%s ret=%.2f%%"
                    % (tag, hold_d, soft_n, hard_n, fret * 100.0)
                )
                _order_sell(C, sell_vol, tag, tag, last, now)
                return

    # R-A
    if (
        buy_cond
        and zero_float
        and ("RA" not in A.acted)
        and (not getattr(A, "pending", None))
    ):
        if not _entry_time_ok(now_s):
            print("R-A skip after", NO_ENTRY_AFTER, "now=", now_s)
            return
        if _in_cooldown(now):
            print(
                "R-A skip cooldown now=",
                now.strftime("%Y%m%d%H%M%S"),
                "until=",
                getattr(A, "cooldown_until", None),
            )
            return
        above_ma, d_last, d_ma = _daily_ma_ok(C, A.stock, closes_hint=close)
        if not above_ma:
            print(
                "R-A skip daily MA%d last=%s ma=%s"
                % (
                    int(DAILY_MA_N),
                    None if d_last is None else round(d_last, 4),
                    None if d_ma is None else round(d_ma, 4),
                )
            )
            return
        budget = min(FLOAT_A_BUDGET, cash)
        vol = _lot(last, budget)
        if vol < 100:
            print("R-A skip cash/lot")
            return
        opened_at = now.strftime("%Y%m%d%H%M%S")
        _order_buy(C, vol, "RA", "RA", last, opened_at, now)
        return

    # R-B（USE_RISK_RULES 且 ENABLE_FLOAT_B=False 时关闭）
    if (
        _enable_float_b()
        and buy_cond
        and has_a
        and (not has_b)
        and ("RB" not in A.acted)
        and (not getattr(A, "pending", None))
    ):
        above_ma, d_last, d_ma = _daily_ma_ok(C, A.stock, closes_hint=close)
        if not above_ma:
            print(
                "R-B skip daily MA%d last=%s ma=%s"
                % (
                    int(DAILY_MA_N),
                    None if d_last is None else round(d_last, 4),
                    None if d_ma is None else round(d_ma, 4),
                )
            )
            return
        ap = float(A.float_a["price"])
        need = ap * (1.0 - SPACE_STEP)
        if last > need + 1e-9:
            print("R-B skip space close=%.4f need<=%.4f" % (last, need))
            return
        budget = min(FLOAT_B_BUDGET, cash)
        vol = _lot(last, budget)
        if vol < 100:
            print("R-B skip cash/lot")
            return
        opened_at = now.strftime("%Y%m%d%H%M%S")
        _order_buy(C, vol, "RB", "RB", last, opened_at, now)
        return

    if (not buy_cond) and (not sell_cond) and interesting:
        extra = ""
        if _use_risk_rules() and (has_a or has_b):
            extra = " holdDays=%.2f ret=%.2f%%" % (hold_d, fret * 100.0)
        print("HongliT hold float" + extra)
