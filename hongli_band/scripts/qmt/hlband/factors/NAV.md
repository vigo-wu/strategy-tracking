# hlband/factors · 因子引擎

根目录是**引擎**（组 ctx、求值、四槽、仲裁）。叶子在 [lib/](lib/NAV.md)，一 id 一文件。

因子不决定买/卖/加/减；立场由 Recipe 所在槽赋予。同一原子可进多槽（如 `pullback_vol` 开仓+加仓）。

**契约**：[架构.md](../../../../docs/架构重构/架构.md) §2.4–2.7、[Recipe分类.md](../../../../docs/架构重构/Recipe分类.md)。  
**默认表达式**：[config.py](../config.py) 的 `RECIPE` 四槽 AST（无数字）。作者改 [catalog.py](catalog.py) 的 `LEAVES`；运行时阈值只读已写入的 `RECIPE.factor_params`。均线/MACD/ATR 窗只读 `structure`。  
**上游指标**：[../indicators/NAV.md](../indicators/NAV.md)。  
**消费**：`strategy.py` 组 ctx → 评槽 → Intent → 挂 pending；`budget.py` / `qmt_common` 订单不进本目录。

片段禁止互 `import`。改完 deploy：`python hongli_band/scripts/qmt/_deploy_qmt_gbk.py`。

---

## 引擎文件

| 文件 | 符号（主） | 做什么 |
| :--- | :--- | :--- |
| [ctx.py](ctx.py) | `_factor_param` `_factor_params_apply_global` `_structure_windows` `_structure_apply_global` `_weekly_market_features` `_build_factor_ctx` `_factor_ctx_bind_state` | 组 `ctx = {market, state, clock}`；读 `RECIPE.factor_params` / `RECIPE.structure`；周线 MA/MACD；日线量均与威尔德 ATR 预计算。`weekly_bull` 只在这里算，仅日志 |
| [catalog.py](catalog.py) | `LEAVES` `_leaves_factor_params` | 叶子登记 / 默认阈值 / 网格轴元数据；整表写入 `RECIPE.factor_params`（`weekly_bear` 无键） |
| [registry.py](registry.py) | `_factor_registry` `_factor_eval` `_factor_hit` | 按 `LEAVES` 取 `_factor_eval_<id>`；缺函数启动时报错 |
| [expr.py](expr.py) | `_recipe_hit` | `and` / `or` / `not`；`False`/`None` = 恒假 |
| [slots.py](slots.py) | `_eval_*_slot` `_eval_recipe_slots` `_recipe_fingerprint` | 四槽 → `{hit, reasons, detail}`；reasons 用叶子 id |
| [intent.py](intent.py) | `_arbitrate_intent` | `{side, target: open\|add\|flat\|reduce, lot_ids?, frac?, reasons[]}`。优先级写死：`flat > reduce > add > open` |

`intent.py` 是仓位层胶水，不是因子叶子。账本 / 50·30·剩余 / `_scale_gate` 仍在 `budget.py` / `strategy.py`。

---

## 拼接顺序

```text
config.py
→ factors/catalog.py
→ …
→ factors/ctx.py
→ factors/lib/<id>.py（顺序 = LEAVES 插入序；缺文件/孤儿启动时报错）
→ registry.py → expr.py → slots.py → intent.py
→ mode → … → budget → strategy
```

`registry` 必须在全部叶子之后，才能看到 `_factor_eval_*`。lib 段由 deploy 从表生成，不要手改 `MODULE_ORDER`。

---

## 默认四槽（现网）

真源是 `config.RECIPE`。四槽草图与阈值约定见 [Recipe分类.md](../../../../docs/架构重构/Recipe分类.md)。

| 槽 | 形态 | 备注 |
| :--- | :--- | :--- |
| `entry` | `¬chase ∧ ¬vol_dry ∧ ¬w_bias ∧ ¬w_slope ∧ ¬weekly_bear ∧ pullback_vol` | 未命中 reasons 为第一个挡住的叶子 |
| `scale_in` | `¬vol_dry ∧ ¬w_bias ∧ ¬w_slope ∧ ¬weekly_bear ∧ ((pullback_vol ∧ ¬chase) ∨ plat_break ∨ w_macd_golden)` | 破平台/金叉**不受** chase；回踩加仓受。`SCALE_ARM` / `scale_once` / 满槽在 `_scale_gate`，不进表达式 |
| `exit` | `weekly_bear_confirm ∨ atr_stop ∨ atr_trail_stop ∨ time_force` | or 短路；主因=第一个命中叶子。`stop_loss` / `trail_stop` 叶子仍在，默认 AST 不引用 |
| `scale_out` | `false` | **减仓未启用**。Intent 预留 `reduce`，strategy 忽略 |

`weekly_bear` = 当天空头（禁开/撤买）。确认清仓用独立叶子 `weekly_bear_confirm`（读 streak）。`_update_w_bear_streak` 不进 `eval`。

网格/探针打 `recipe=` 指纹（表达式 + 折进表的 `factor_params` + `structure`）。apply 进表后再算，`overrides` 袋为空。默认哈希会变；探针重算，不对历史档案旧哈希。算法与 `local_bt/grid_spec.recipe_fingerprint` 同一套。不要做全因子 `2^n` 开关。AST / 结构窗不上 `panel.xml`。

---

## 加因子 / 改 Recipe

1. [catalog.py](catalog.py) 的 `LEAVES` 加一行：`label` / `group` / `params`（`default` 类型与现网一致；无阈值叶子不要写空 `{}` 进表）。网格轴序用 `params[].axis`。
2. `lib/<id>.py` 写 `_factor_eval_<id>(ctx) → (bool, detail)`，阈值读 `_factor_param(ctx, id, key)`（运行时 `RECIPE.factor_params`），**不写死数字、不做成配置表达式**。均线/MACD/ATR 窗读 `_structure_windows()`（`RECIPE.structure`）。
3. 默认盘要启用：改 `config.RECIPE` 四槽 AST 引用该 id。不要手改 `registry` / `MODULE_ORDER` / `grid_spec` 白名单。
4. 网格覆盖仍是 `overrides.factor_params` / `overrides.structure`，由 `_factor_params_apply_global` / `_structure_apply_global` 按段再按 key 合并。新序列仍改 `indicators/` + `ctx.py`。
5. 不要改 `_handle` 才能加叶子；仓位门槛不要写进布尔式。

不要进 `lib/`：`BOOK_LOT_MAX`、现金、`scale_once`、`SCALE_ARM`、pending 超时、T+1。  
不要把因子塞进 `indicators/`。

叶子以后仍留策略侧。引擎（ctx/registry/expr/slots）以后可迁 `qmt_common/factors/`。
