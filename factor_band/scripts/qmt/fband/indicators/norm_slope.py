# === fband/indicators/norm_slope.py ===
def _norm_slope_from_ma(ma, m):
    """对已算好的均线序列做 OLS 斜率并 /MA*100。m 必传，不读 RECIPE。"""
    y = np.asarray(ma, dtype=float)
    m = int(m)
    n = len(y)
    if m <= 1 or n < m:
        return None
    out = np.full(n, np.nan, dtype=float)
    x = np.arange(1, m + 1, dtype=float)
    sum_x = float(np.sum(x))
    sum_x2 = float(np.sum(x * x))
    den = m * sum_x2 - sum_x * sum_x
    if den == 0.0:
        return None
    for i in range(m - 1, n):
        yy = y[i - m + 1 : i + 1]
        if np.any(~np.isfinite(yy)):
            continue
        ma_i = float(yy[-1])
        if ma_i <= 0.0:
            continue
        sum_y = float(np.sum(yy))
        sum_xy = float(np.sum(x * yy))
        slope = (m * sum_xy - sum_x * sum_y) / den
        out[i] = (slope / ma_i) * 100.0
    return out


def _calc_norm_slope(closes, ma_n, slope_m, ma_kind="sma"):
    """MA 线性回归斜率归一化。窗与 ma_kind 必传/显式，不读 RECIPE。
    ma_kind: "sma" | "ema"；经 _ma 分发。
    返回 Norm_Slope 全序列，或 None。
    """
    ma_n = int(ma_n)
    slope_m = int(slope_m)
    if ma_n <= 0 or slope_m <= 1:
        return None
    ma = _ma(closes, ma_n, ma_kind)
    if ma is None:
        return None
    return _norm_slope_from_ma(ma, slope_m)
