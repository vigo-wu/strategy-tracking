# hlband/factors · 因子引擎

根目录是**引擎**（组 ctx、求值、四个槽位、仲裁）。叶子在 [lib/](lib/NAV.md)，一 id 一文件。

因子不决定买/卖/加/减；立场由 Recipe 所在槽赋予。同一原子可进多槽（如 `keltner_vol` 开仓+加仓）。

**契约**：[架构.md](../../../../docs/架构说明/架构.md) §2.4–2.7、[Recipe分类.md](../../../../docs/架构说明/Recipe分类.md)。  
**默认表达式**：[config.py](../config.py) 的 `RECIPE` 四个槽位条件抽象语法树（买入 `entry`、加仓 `scale_in`、卖出 `exit`、减仓 `scale_out`，无数字）。作者改 [catalog.py](catalog.py) 的 `LEAVES`；运行时阈值只读已写入的 `RECIPE.factor_params`。均线/ATR/肯特纳窗只读 `structure`。  
**上游指标**：[../indicators/NAV.md](../indicators/NAV.md)。  
**消费**：`strategy.py` 组 ctx → 评槽 → Intent → 挂 pending；`budget.py` / `qmt_common` 订单不进本目录。

片段禁止互 `import`。改完 deploy：`python factor_band/scripts/qmt/_deploy_qmt_gbk.py`。

---

## 引擎文件

| 文件 | 符号（主） | 做什么 |
| :--- | :--- | :--- |
| [ctx.py](ctx.py) | `_factor_param` `_factor_params_apply_global` `_structure_windows` `_structure_apply_global` `_market_need` `_weekly_market_features` `_build_factor_ctx` `_factor_ctx_bind_state` | 组 `ctx = {market, state, clock}`；`need` 读 `LEAVES`；行情键 `d_mid` / `d_slow` / `d_trend`、周线 `w_mid` / `w_trend`。`daily_ready` = 日线 `closes` 且 `i>=2` |
| [catalog.py](catalog.py) | `LEAVES` `_leaves_factor_params` | 叶子登记 / `need` / 默认阈值 / 网格轴元数据；整表写入 `RECIPE.factor_params`（`above_ema` 无键） |
| [registry.py](registry.py) | `_factor_registry` `_factor_eval` `_factor_hit` | 按 `LEAVES` 取 `_factor_eval_<id>`；缺函数启动时报错 |
| [expr.py](expr.py) | `_recipe_hit` `_recipe_leaf_ids` `_recipe_compute_leaves` | `and` / `or` / `not`；`False`/`None` = 恒假；启用叶子 + `scale_in` 特例 |
| [slots.py](slots.py) | `_eval_*_slot` `_eval_recipe_slots` `_recipe_fingerprint` `_recipe_log_kv` | 四个槽位 → `{hit, reasons, detail}`；reasons 用叶子 id；init 点路径只打启用叶子 + `_market_need` 窗 |
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

## 默认四个槽位（现行默认配置）

唯一可信数据源是 `config.RECIPE`。四个槽位草图与阈值约定见 [Recipe分类.md](../../../../docs/架构说明/Recipe分类.md)。

| 槽 | 形态 | 备注 |
| :--- | :--- | :--- |
| `entry` | `above_ema ∧ keltner_vol` | 未命中 reasons 为第一个挡住的叶子 |
| `scale_in` | `false` | **加仓未启用**。`scale_arm` 仍登记；启用时由 `_recipe_compute_leaves` 特例拉入。`scale_once` / 满槽在 `_scale_gate` |
| `exit` | `atr_stop ∨ atr_trail_stop` | or 短路；主因=第一个命中叶子。`stop_loss` / `trail_stop` / `time_force` 叶子仍在，默认 AST 不引用 |
| `scale_out` | `false` | **减仓未启用**。Intent 预留 `reduce`，strategy 忽略 |

网格 / 参数指纹预检打 `recipe=` 指纹（表达式 + 折进表的 `factor_params` + `structure`）。apply 进表后再算，`overrides` 袋为空。默认哈希会变；参数指纹预检重算，不对历史档案旧哈希。算法与 `local_bt/grid_spec.recipe_fingerprint` 同一套。不要做全因子 `2^n` 开关。AST / 指标周期窗不上 `panel.xml`。

---

## 加因子 / 改 Recipe

1. [catalog.py](catalog.py) 的 `LEAVES` 加一行：`label` / `group` / `need` / `params`（`default` 类型与现行默认配置一致；无阈值叶子不要写空 `{}` 进表）。网格轴序用 `params[].axis`。
2. `lib/<id>.py` 写 `_factor_eval_<id>(ctx) → (bool, detail)`，阈值读 `_factor_param(ctx, id, key)`（运行时 `RECIPE.factor_params`），**不写死数字、不做成配置表达式**。均线/ATR/肯特纳窗读 `_structure_windows()`（`RECIPE.structure`）。`LEAVES.need` 登记预计算标签（缺键或非法标签在 ctx 组表时报错；未知 AST id 运行时按全标签算）。
3. 默认盘要启用：改 `config.RECIPE` 四个槽位的条件抽象语法树引用该 id。不要手改 `registry` / `MODULE_ORDER` / `grid_spec` 白名单。
4. 网格覆盖仍是 `overrides.factor_params` / `overrides.structure`，由 `_factor_params_apply_global` / `_structure_apply_global` 按段再按 key 合并。新序列仍改 `indicators/` + `ctx.py`。
5. 不要改 `_handle` 才能加叶子；仓位门槛不要写进布尔式。

不要进 `lib/`：`BOOK_LOT_MAX`、现金、`scale_once`、pending 超时、T+1。  
不要把因子塞进 `indicators/`。

叶子以后仍留策略侧。引擎（ctx/registry/expr/slots）以后可迁 `qmt_common/factors/`。
