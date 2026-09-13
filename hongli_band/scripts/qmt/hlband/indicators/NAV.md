# hlband/indicators · 技术指标

只做序列变换，算一次。无立场、无持仓、不读现金 / pending。

**契约真源**：[docs/架构重构/架构.md](../../../../docs/架构重构/架构.md) §2.3。  
**下游**：组装进 [../factors/NAV.md](../factors/NAV.md) 的 `ctx.market`。  
**拼接**：[`../_deploy_qmt_gbk.py`](../../_deploy_qmt_gbk.py) `MODULE_ORDER`（片段禁止互 `import`）。

---

## 文件

| 文件 | 符号 | 算指标 | 说明 |
| :--- | :--- | :--- | :--- |
| [util.py](util.py) | `_last_valid` `_cross_up` `_cross_down` | 否 | 取末值、金叉死叉；给 MACD / 因子用 |
| [sma.py](sma.py) | `_sma` | 是 | 简单均线；**成交量均量固定走这里** |
| [ema.py](ema.py) | `_ema` | 是 | 指数均线 |
| [macd.py](macd.py) | `_calc_macd` | 是 | 只用已拼入的 `_ema`（必须在 ema 之后）；`fast/slow/signal` **必传**，不读 `RECIPE` / `MACD_*` |
| [atr.py](atr.py) | `_true_range` `_wilder` `_calc_atr` | 是 | 威尔德 ATR；`n` **必传**，不读 `RECIPE` / `atr.n`；`n<=0` 或长度不足 → `None` |
| [price_ma.py](price_ma.py) | `_ma_kind` `_price_ma` | 否 | `_price_ma(closes, n, kind=None)`；`n` 由调用方从 `RECIPE.structure` 传入；`kind` 缺省走 `_ma_kind()`（算法，不是窗） |

不要放进来：`chase` / `pullback_vol` / `trail_stop`（因子）以及 `_near_ma` / `_plat_window`（在 [../factors/lib/NAV.md](../factors/lib/NAV.md)）。

---

## 拼接顺序

```text
indicators/util.py → sma.py → ema.py → macd.py → atr.py → price_ma.py
```

`macd.py` 直接调用 `_ema`，靠顺序看到符号。纯算法（util/sma/ema/macd/atr）以后可迁 `qmt_common/indicators/`；`price_ma` 读池配置，留策略侧。

---

## 加指标

1. 本目录一指标一文件，只吃序列、产出序列（或纯工具）。
2. 在 `_deploy_qmt_gbk.py` 的 `MODULE_ORDER` 插入（有依赖的放后面）。
3. `python hongli_band/scripts/qmt/_deploy_qmt_gbk.py`，`compile` 成功。
4. 不要新建根上的 `indicators.py`（会和本目录重名）。
