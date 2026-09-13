# 登记表字段与结构窗

真源：`hongli_band/scripts/qmt/hlband/factors/catalog.py`。运行时阈值是写入后的 `RECIPE.factor_params`。

`LEAVES` = 可作 AST 叶子的**因子登记表**。行在表里 ≠ 四槽已启用。

## 登记一行

| 键 | 必填 | 说明 |
| :--- | :--- | :--- |
| `label` | 是 | 日志中文名（现网买卖文案，不要为网格短名改） |
| `label_buy` | 否 | 仅买卖用词不同时（如 `weekly_bear`） |
| `group` | 是 | 只用于网格侧栏：`entry` / `exit` / `scale`。不是槽立场，不限制 AST 引用 |
| `params` | 是 | 无阈值用 `{}`；`_leaves_factor_params` 跳过空表，不写进 `factor_params` |

`LEAVES` 插入序 = `lib/` 拼包序。网格轴序另用 `params[].axis`（同 `group` 内数字越小越靠前）。

## 参数

| 键 | 说明 |
| :--- | :--- |
| `default` | 写入 `factor_params` 的字面量；`2` ≠ `2.0`；tiers 用 list 不是 tuple |
| `percent` | `True` → 网格按百分比轴 |
| `abbrev` | 格子短 id（如 `sl`、`atk1`） |
| `label` | 轴短名（侧栏），不是因子日志名 |
| `kind` | `smaller_tighten` / `smaller_loosen` / `trail_tiers`；缺省 → `kind_mode=other` |
| `off` | `le0`：`<=0` 标 `off`。`stop_loss.pct` 必须 `off: None`（0 是更紧，不是关规则） |
| `axis` | 同 `group` 内排序。`time_force.bars` 与 `arm` 不要靠插入序硬挨 |

`weekly_bear_confirm.days` 只进网格出场组、不设 `kind`（现网如此）。

`kind` 只写在网格出场轴上。写到入场/加仓会被当成出场松紧。

不要进 `LEAVES`：资金、`SCALE_*`、`RECIPE.structure`、四槽 AST。

## 现网 kind 约定

- `smaller_tighten` + `off=le0`：`atr_stop.k`、`atr_trail_stop.k1/k2`、`time_force.bars`
- `smaller_loosen` + `off=le0`：`time_force.arm`
- `smaller_tighten` + `off=None`：`stop_loss.pct`
- `trail_tiers`：`trail_stop.tiers`（档1 `peak_lo` 比松紧，逻辑在 `_trail_tiers_kind`）

## 新结构窗（指标侧，不是登记表）

要网格能扫窗，四处一起改（这是**参数契约**：窗真源 + 读窗 API + 覆盖形态）：

1. `config.RECIPE.structure` 段
2. `factors/ctx.py` `_structure_windows()`（缺省字面量与 config 一致）
3. `market._ohlcv_need_1d` / `_ohlcv_need_1w`（暖机）
4. `local_bt/grid_spec.py` 的 `STRUCTURE_KEYS` 与 `STRUCTURE_ROOTS`

因子调用：先 `_structure_windows()`，再把 `n` 传给 `_price_ma` / `_calc_macd` / `_calc_atr`。

## 加完自检

- `LEAVES` id ↔ `lib/<id>.py` ↔ `_factor_eval_<id>`
- 四槽 AST 里出现的 id ⊆ `LEAVES`（启用 ⊆ 登记）
- 无阈值因子不在 `factor_params`
- 新因子轴出现在 `catalog_ids()`；新结构轴出现在 `STRUCTURE_KEYS`
