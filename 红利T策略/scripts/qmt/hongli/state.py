# === hongli/state.py ===
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
def _reset_day(day):
    if A.acted_day != day:
        A.acted_day = day
        A.acted = set()
        _save_state()


def _has_leg(leg):
    return leg is not None and int(leg.get("shares", 0)) >= 100


def _use_risk_rules():
    """风控档（最长持仓/冷却/止损/时段门/Float-B 开关）。任意 PERIOD。"""
    return bool(USE_RISK_RULES)


def _enable_float_b():
    if _use_risk_rules():
        return bool(ENABLE_FLOAT_B)
    return True


def _parse_opened_at(s):
    if not s:
        return None
    s = str(s).strip()
    for fmt, n in (("%Y%m%d%H%M%S", 14), ("%Y-%m-%d %H:%M:%S", 19), ("%Y%m%d", 8)):
        try:
            return datetime.datetime.strptime(s[:n], fmt)
        except Exception:
            continue
    return None


def _hold_days(opened_at, now):
    ot = opened_at if isinstance(opened_at, datetime.datetime) else _parse_opened_at(opened_at)
    if ot is None or now is None:
        return 0.0
    return max(0.0, (now - ot).total_seconds() / 86400.0)


def _float_avg_cost():
    """浮仓 A/B 按股数加权均价；空则 0。"""
    cost = 0.0
    sh = 0
    for leg in (getattr(A, "float_a", None), getattr(A, "float_b", None)):
        if not _has_leg(leg):
            continue
        s = int(leg.get("shares", 0))
        px = float(leg.get("price", 0) or 0)
        if s >= 100 and px > 0:
            cost += s * px
            sh += s
    if sh <= 0:
        return 0.0
    return cost / float(sh)


def _float_ret(last):
    avg = _float_avg_cost()
    if avg <= 0 or last is None or last <= 0:
        return 0.0
    return (float(last) - avg) / avg


def _exit_time_ok(now_s):
    """延后 R-Sell/MaxHold 至 EXIT_AFTER（仅日内；止损可绕过）。"""
    if not _use_risk_rules():
        return True
    if not getattr(A, "intraday", False):
        return True
    gate = str(EXIT_AFTER or "").strip()
    if not gate:
        return True
    return str(now_s) >= gate


def _entry_time_ok(now_s):
    """NO_ENTRY_AFTER 及之后禁止新开 R-A（仅日内）。"""
    if not _use_risk_rules():
        return True
    if not getattr(A, "intraday", False):
        return True
    gate = str(NO_ENTRY_AFTER or "").strip()
    if not gate:
        return True
    return str(now_s) < gate


def _cooldown_timedelta(bars):
    p = getattr(A, "period", "1d") or "1d"
    mins = int(_PERIOD_BAR_MINUTES.get(p, 24 * 60))
    return datetime.timedelta(minutes=max(0, int(bars)) * mins)


def _set_cooldown(now, is_loss=False):
    if not _use_risk_rules():
        return
    bars = int(COOLDOWN_BARS_LOSS) if is_loss else int(COOLDOWN_BARS)
    if bars <= 0:
        return
    if now is None:
        now = datetime.datetime.now()
    until = now + _cooldown_timedelta(bars)
    A.cooldown_until = until.strftime("%Y%m%d%H%M%S")
    print(
        "HongliT cooldown until",
        A.cooldown_until,
        "bars=",
        bars,
        "period=",
        getattr(A, "period", "?"),
        "loss=",
        bool(is_loss),
    )


def _in_cooldown(now):
    if not _use_risk_rules():
        return False
    if int(COOLDOWN_BARS) <= 0 and int(COOLDOWN_BARS_LOSS) <= 0:
        return False
    until_s = str(getattr(A, "cooldown_until", "") or "").strip()
    if not until_s:
        return False
    until = _parse_opened_at(until_s)
    if until is None:
        return False
    if now is None:
        now = datetime.datetime.now()
    return now < until


def _sell_float_vol():
    vol = 0
    if _has_leg(getattr(A, "float_a", None)):
        vol += int(A.float_a["shares"])
    if _has_leg(getattr(A, "float_b", None)):
        vol += int(A.float_b["shares"])
    return vol


def _clear_float_after_sell(now, remark, last=None):
    is_loss = False
    if last is not None:
        is_loss = _float_ret(last) < 0
    A.float_a = None
    A.float_b = None
    _bt_held_set(0)
    A.acted.add("SELL")
    _set_cooldown(now, is_loss=is_loss)
    _save_state()
    print("HongliT", remark, "done, float cleared loss=", bool(is_loss))


def _shrink_float_to_vol(target_vol):
    """缩减浮仓 A/B 使总股数 <= target_vol（先减 B）。"""
    target_vol = int(target_vol)
    if target_vol < 100:
        A.float_a = None
        A.float_b = None
        return
    a = int(A.float_a["shares"]) if _has_leg(A.float_a) else 0
    b = int(A.float_b["shares"]) if _has_leg(A.float_b) else 0
    total = a + b
    if total <= target_vol:
        return
    drop = total - target_vol
    if b > 0:
        take = min(b, drop)
        b -= take
        drop -= take
        if b < 100:
            A.float_b = None
        else:
            A.float_b["shares"] = b
            A.float_b["cost"] = round(b * float(A.float_b.get("price", 0) or 0), 2)
    if drop > 0 and a > 0:
        a = max(0, a - drop)
        if a < 100:
            A.float_a = None
        else:
            A.float_a["shares"] = a
            A.float_a["cost"] = round(a * float(A.float_a.get("price", 0) or 0), 2)
