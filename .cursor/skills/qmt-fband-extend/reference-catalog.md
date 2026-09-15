# 登记表字段与指标周期窗

唯一可信数据源：`factor_band/scripts/qmt/fband/factors/catalog.py`。运行时阈值是写入后的 `RECIPE.factor_params`。

`LEAVES` = 可作 AST 叶子的**因子登记表**。行在表里 ≠ 四个槽位已启用。

## 登记一行

| 键 | 必填 | 说明 |
| :--- | :--- | :--- |
| `label` | 是 | 日志中文名（现行默认配置的买卖文案，不要为网格短名改） |
| `label_buy` | 否 | 仅买卖用词不同时（可选） |
| `group` | 是 | 只用于网格侧栏：`entry` / `exit` / `scale`。不是槽立场，不限制 AST 引用 |
| `params` | 是 | 无阈值用 `{}`；`_leaves_factor_params` 跳过空表，不写进 `factor_params` |

`LEAVES` 插入序 = `lib/` 拼包序。网格轴序另用 `params[].axis`（同 `group` 内数字越小越靠前）。

## 参数

| 键 | 说明 |
| :--- | :--- |
| `default` | 写入 `factor_params` 的字面量 |
| `percent` | `True` → 网格按百分比轴 |
| `abbrev` | 格子短 id（如 `sl`、`atk1`） |
| `label` | 轴短名（侧栏），不是因子日志名 |
| `kind` | `smaller_tighten` / `smaller_loosen` / `trail_tiers`；缺省 → `kind_mode=other` |
| `off` | `le0`：`<=0` 标 `off`。`stop_loss.pct` 必须 `off: None`（0 是更紧，不是关规则） |
| `axis` | 同 `group` 内排序。`time_force.bars` 与 `arm` 不要靠插入序硬挨 |

`time_force.bars` / `arm` 启用后才进网格出场组；出场轴写 `kind`。

`kind` 只写在网格出场轴上。写到入场/加仓会被当成出场松紧。

不要进 `LEAVES`：资金、`SCALE_ENABLE` / `SCALE_ONCE_PER_ROUND` / `SCALE_LOTS`、`RECIPE.structure`、四个槽位的条件抽象语法树。`SCALE_ARM` / `SCALE_ARM_BARS` / `SCALE_W_HIST_MIN` 已删，顶层写入即报错。

## 类型安全防错警告

登记 `params[].default` 时类型必须与运行时读取一致，否则网格覆盖或指纹会对不上：

- **`2` ≠ `2.0`**：整型与浮点错位。周期窗 / `time_force.bars` 写 `2`；`atr_stop.k` / `atr_trail_stop.k1` / `k2` 写 `2.0`，网格才按浮点轴扫 `1.5`。
- **`trail_stop.tiers` 必须用 `list`，严禁 `tuple`**：JSON / `overrides` 只能表达数组；写成 tuple 会在序列化或相等比较时失败。

## 现行默认配置 kind 约定

- `smaller_tighten` + `off=le0`：`atr_stop.k`、`atr_trail_stop.k1/k2`、`time_force.bars`
- `smaller_loosen` + `off=le0`：`time_force.arm`
- `smaller_tighten` + `off=None`：`stop_loss.pct`
- `trail_tiers`：`trail_stop.tiers`（档1 `peak_lo` 比松紧，逻辑在 `_trail_tiers_kind`）

## 新的 RECIPE.structure 指标周期窗（指标侧，不是登记表）

要网格能扫窗，四处一起改（这是**参数契约**：指标周期窗的唯一可信数据源 + `_structure_windows()` + 覆盖形态）：

1. `config.RECIPE.structure` 段
2. `factors/ctx.py` `_structure_windows()`（缺省字面量与 config 一致）
3. `market._ohlcv_need_1d` / `_ohlcv_need_1w`（暖机）
4. `local_bt/grid_spec.py` 的 `STRUCTURE_KEYS` 与 `STRUCTURE_ROOTS`

因子调用：先 `_structure_windows()`，再把 `n` 传给 `_ema` / `_sma` / `_calc_atr` / `_calc_keltner`。价格均线算法由调用点选定，不上 `structure`。`_calc_keltner` 的倍数 `k` 由调用方传入，不上 `structure`。

## 加完自检

- `LEAVES` id ↔ `lib/<id>.py` ↔ `_factor_eval_<id>` ↔ `_LEAF_MARKET_NEED`
- 四个槽位 AST 里出现的 id ⊆ `LEAVES`（启用 ⊆ 登记）
- 无阈值因子不在 `factor_params`
- 新因子轴在**登记且 AST 启用后**出现在 `catalog_ids()`；新结构轴出现在 `STRUCTURE_KEYS`
