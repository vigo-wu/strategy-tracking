# hlband/indicators · 技术指标

只做序列变换，算一次。无立场、无持仓、不读现金 / pending。是否调用由 `factors/ctx.py` 按启用叶子决定。

**契约的唯一可信数据源**：[docs/架构说明/架构.md](../../../../docs/架构说明/架构.md) §2.3。  
**下游**：组装进 [../factors/NAV.md](../factors/NAV.md) 的 `ctx.market`。  
**拼接**：[`../_deploy_qmt_gbk.py`](../../_deploy_qmt_gbk.py) `MODULE_ORDER`（片段禁止互 `import`）。

---

## 文件

| 文件 | 符号 | 算指标 | 说明 |
| :--- | :--- | :--- | :--- |
| [util.py](util.py) | `_last_valid` `_cross_up` `_cross_down` | 否 | 取末值、金叉死叉；给因子用 |
| [sma.py](sma.py) | `_sma` | 是 | 简单均线；**成交量均量固定走这里** |
| [ema.py](ema.py) | `_ema` | 是 | 指数均线；由 `_ma` 分发调用 |
| [ma.py](ma.py) | `_ma` | 是 | 价格均线入口；`kind`（`"sma"`\|`"ema"`）必传，不读 `RECIPE`；非法 kind → `None` |
| [norm_slope.py](norm_slope.py) | `_calc_norm_slope` `_norm_slope_from_ma` | 是 | 均线 OLS 斜率归一化；经 `_ma`；`ma_n` / `slope_m` / `ma_kind` 必传/显式，不读 `RECIPE` |
| [atr.py](atr.py) | `_true_range` `_wilder` `_calc_atr` | 是 | 威尔德 ATR；`n` **必传**，不读 `RECIPE` / `atr.n`；`n<=0` 或长度不足 → `None` |
| [keltner.py](keltner.py) | `_calc_keltner` | 是 | 中轨 `_ma` ± k×威尔德 ATR；须在 ma / atr 之后；`ma_n` / `atr_n` / `k` / `kind` **必传**，不读 `RECIPE` |

不要把因子放进来（如 `keltner_vol` / `trail_stop`）。

---

## 拼接顺序

```text
indicators/util.py → sma.py → ema.py → ma.py → norm_slope.py → atr.py → keltner.py
```

`ma.py` 分发 `_sma` / `_ema`。`norm_slope.py` / `keltner.py` 经 `_ma`（及 ATR）。纯算法以后可迁 `qmt_common/indicators/`。价格均线算法唯一可信数据源是 `structure.ma.kind`，调用方传入 `_ma`；量均固定 `_sma`，窗在 `factor_params`。

---

## 加指标

1. 本目录一指标一文件，仅接受行情序列作为输入、产出序列（或纯工具）。
2. 在 `_deploy_qmt_gbk.py` 的 `MODULE_ORDER` 插入（有依赖的放后面）。
3. `python factor_band/scripts/qmt/_deploy_qmt_gbk.py`，`compile` 成功。
4. 不要新建根上的 `indicators.py`（会和本目录重名）。
