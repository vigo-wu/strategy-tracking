# === hongli/indicators.py ===
# 作用: 布林带 + KDJ(J)，与 model.md 对齐
# 主要符号: _calc_indicators
# 拼接序: 8/16 | 上一部: state.py | 下一部: market_util.py
# 导航: hongli/NAV.md（按改什么找哪里 / 调用链）
# 国金 QMT 拼接片段。运行时勿跨模块 import；
# 由 _deploy_qmt_gbk.py 按 MODULE_ORDER 拼成单个 GBK 文件。
def _calc_indicators(high, low, close):
    """返回 (下轨, 上轨, J, 最新收盘) 或 None。"""
    n = len(close)
    need = max(BOLL_N, KDJ_N) + 2
    if n < need:
        return None
    c = np.asarray(close, dtype=float)
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    # 拒绝填充/平坦窗口（历史未就绪）
    if np.std(c[-BOLL_N:]) < 1e-8:
        return None
    mid = np.mean(c[-BOLL_N:])
    std = np.std(c[-BOLL_N:])
    lower = mid - BOLL_K * std
    upper = mid + BOLL_K * std

    # KDJ 与 model.md 一致: RSV ewm(com=2)
    rsv = np.zeros(n, dtype=float)
    for i in range(n):
        i0 = max(0, i - KDJ_N + 1)
        hn = np.max(h[i0 : i + 1])
        ln = np.min(l[i0 : i + 1])
        if hn <= ln:
            rsv[i] = 0.0
        else:
            rsv[i] = (c[i] - ln) / (hn - ln) * 100.0
    k = np.zeros(n, dtype=float)
    d = np.zeros(n, dtype=float)
    alpha = 1.0 / 3.0  # ewm com=2 -> alpha=1/(com+1)
    k[0] = rsv[0]
    d[0] = k[0]
    for i in range(1, n):
        k[i] = (1 - alpha) * k[i - 1] + alpha * rsv[i]
        d[i] = (1 - alpha) * d[i - 1] + alpha * k[i]
    j = 3.0 * k[-1] - 2.0 * d[-1]
    return lower, upper, float(j), float(c[-1])
