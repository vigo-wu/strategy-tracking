# === qmt_common/ctx.py ===
# 作用: 全局运行时对象与手数工具
# 主要符号: A, _S, _vol_step, _lot
# 前置: 策略 config（可选 STRATEGY_NAME, VOL_STEP）
# VOL_STEP: 下单数量步长。股票/ETF 默认 100 股；沪市转债设 10（10 张=1000 元面值）
class _S(object):
    pass


A = _S()


def _vol_step():
    try:
        s = int(globals().get("VOL_STEP") or 100)
    except Exception:
        s = 100
    if s <= 0:
        s = 100
    return s


def _lot(price, budget):
    step = _vol_step()
    if price is None or price <= 0 or budget <= 0:
        return 0
    return int(budget // (price * step)) * step


def _strategy_tag():
    return str(globals().get("STRATEGY_NAME") or "QMT")


# 实盘落盘钩子空实现；引入 common:live_log.py 后覆盖
def _event_log(event, **fields):
    pass


def _bar_log(**fields):
    pass


def _heartbeat_persist(text):
    pass


def _live_state_snapshot(data):
    pass
