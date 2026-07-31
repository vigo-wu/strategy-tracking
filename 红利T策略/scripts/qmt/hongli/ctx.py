# === hongli/ctx.py ===
# 作用: 全局运行时对象与手数工具
# 主要符号: A, _S, _lot
# 拼接序: 3/16 | 上一部: config.py | 下一部: period.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
class _S(object):
    pass


A = _S()


def _lot(price, budget):
    if price is None or price <= 0 or budget <= 0:
        return 0
    return int(budget // (price * 100)) * 100
