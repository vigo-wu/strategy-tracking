# hlband/factors · 因子引擎

根目录是**引擎**（组 ctx、求值、四槽、仲裁）。叶子在 [lib/](lib/NAV.md)，一 id 一文件。

因子不决定买/卖/加/减；立场由 Recipe 所在槽赋予。同一原子可进多槽（如 `pullback_vol` 开仓+加仓）。

**契约**：[架构.md](../../../../docs/架构重构/架构.md) §2.4–2.7、[Recipe分类.md](../../../../docs/架构重构/Recipe分类.md)。  
**默认表达式**：[config.py](../config.py) 的 `RECIPE`（AST 无数字；阈值仍读全局常量）。  
**上游指标**：[../indicators/NAV.md](../indicators/NAV.md)。  
**消费**：`strategy.py` 组 ctx → 评槽 → Intent → 挂 pending；`budget.py` / `qmt_common` 订单不进本目录。

片段禁止互 `import`。改完 deploy：`python hongli_band/scripts/qmt/_deploy_qmt_gbk.py`。

---

## 引擎文件

| 文件 | 符号（主） | 做什么 |
| :--- | :--- | :--- |
| [ctx.py](ctx.py) | `_weekly_market_features` `_build_factor_ctx` `_factor_ctx_bind_state` | 组 `ctx = {market, state, clock}`；周线 MA/MACD；日线量均预计算。`weekly_bull` 只在这里算，仅日志 |
| [registry.py](registry.py) | `_factor_registry` `_factor_eval` `_factor_hit` | `id → eval` |
| [expr.py](expr.py) | `_recipe_hit` | `and` / `or` / `not`；`False`/`None` = 恒假 |
| [slots.py](slots.py) | `_eval_*_slot` `_eval_recipe_slots` `_recipe_fingerprint` | 四槽 → `{hit, reasons, detail}`；日志码映射（`chase` → `chase_skip`） |
| [intent.py](intent.py) | `_arbitrate_intent` | `{side, target: open\|add\|flat\|reduce, lot_ids?, frac?, reasons[]}`。优先级写死：`flat > reduce > add > open` |

`intent.py` 是仓位层胶水，不是因子叶子。账本 / 50·30·剩余 / `_scale_gate` 仍在 `budget.py` / `strategy.py`。

---

## 拼接顺序

```text
market.py
→ factors/ctx.py
→ factors/lib/<id>.py（见 lib/NAV.md）
→ registry.py → expr.py → slots.py → intent.py
→ mode → … → budget → strategy
```

`registry` 必须在全部叶子之后，才能看到 `_factor_eval_*`。

---

## 默认四槽（现网）

真源是 `config.RECIPE`，不是 `Recipe分类.md` 里偏旧的加仓草图。

| 槽 | 形态 | 备注 |
| :--- | :--- | :--- |
| `entry` | `¬chase ∧ ¬vol_dry ∧ ¬w_bias ∧ ¬w_slope ∧ ¬weekly_bear ∧ pullback_vol` | 日志码由 slots 映射 |
| `scale_in` | `¬vol_dry ∧ ¬w_bias ∧ ¬w_slope ∧ ¬weekly_bear ∧ ((pullback_vol ∧ ¬chase) ∨ plat_break ∨ w_macd_golden)` | 破平台/金叉**不受** chase；回踩加仓受。`SCALE_ARM` / `scale_once` / 满槽在 `_scale_gate`，不进表达式 |
| `exit` | 有序列表：`weekly_bear_confirm > stop_loss > trail_stop > time_force` | 确认清仓 reason 仍打 `weekly_bear` |
| `scale_out` | `false` | **减仓未启用**。Intent 预留 `reduce`，strategy 忽略 |

`weekly_bear` = 当天空头（禁开/撤买）。确认清仓用独立叶子 `weekly_bear_confirm`（读 streak）。`_update_w_bear_streak` 不进 `eval`。

网格/探针打 `recipe=` 指纹（表达式 + 被覆盖的阈值键）。不要做全因子 `2^n` 开关。AST 不上 `panel.xml`。

---

## 加因子 / 改 Recipe

1. `lib/<id>.py` 写 `_factor_eval_<id>(ctx) → (bool, detail)`，阈值读 `globals()`（`CHASE_MAX_PCT` 等），**不写死数字**。
2. `MODULE_ORDER` 在 `registry.py` 之前插入该文件。
3. [registry.py](registry.py) 登记 `id → eval`。
4. 默认盘要启用：改 `config.RECIPE` 引用该 id。
5. 不要改 `_handle` 才能加叶子；仓位门槛不要写进布尔式。

不要进 `lib/`：`BOOK_LOT_MAX`、现金、`scale_once`、`SCALE_ARM`、pending 超时、T+1。  
不要把因子塞进 `indicators/`。

叶子以后仍留策略侧。引擎（ctx/registry/expr/slots）以后可迁 `qmt_common/factors/`。
