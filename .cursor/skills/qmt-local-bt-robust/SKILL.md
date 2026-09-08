---
name: qmt-local-bt-robust
description: >-
  参数锁定后做实盘评估：从宇宙随机抽 N 组真组合连续回放，按硬/软门与嵌套盲测窗裁决 GO/NO-GO。
  Use when the user mentions 实盘评估、上实盘验收、随机组合回放、稳健门、能否上实盘、
  robust gate、post-grid portfolio validation.
---

# 实盘评估（流水线第 2 步）

网格选参之后、选股之前：锁定 `overrides`，随机组合真回放，判断策略是否达到预期。

## 不要用错

| 需求 | 走哪个 |
| :--- | :--- |
| 选 STOP_LOSS / TRAIL 等参数 | `qmt-local-bt-grid` |
| 打分选票 / walk-forward | 选股方案 / `select_wf` |
| 终端 log 画图 | `qmt-backtest-report` |
| DSR / PBO | `skill-backtest-overfit` |

## 硬规则

1. **真组合**：`run_book_backtest` / `run_one_basket`，禁止单票预算加总冒充组合。
2. **灌参**：默认空 = 现行 config；可选 `overrides_from` → `summary.recommend.id` → `cells[].overrides`。
3. **时间嵌套**：`deploy_start > check_end`；GO/NO-GO **只看盲测窗**。
4. **硬门**：卡玛 / 回撤 / 夏普 / 盈亏比。**软门**：胜率 / 笔数（默认 `veto=false` 只 warn）。
5. **整次 GO**：`pass_rate` ∧ 中位卡玛 ∧ P10 回撤。
6. **默认不改 config / 不 deploy / 不写 BOOK_STOCKS**。

## 窗内 KPI

| 指标 | 口径 |
| :--- | :--- |
| 笔数 / 胜率 / 盈亏比 | 平仓日落在窗内 |
| 回撤 / 夏普 / 卡玛 | 窗内组合权益路径；卡玛 = 窗内几何年化 / `|max_dd|` |

## 怎么跑

```bash
python hongli_band/scripts/local_bt/robust_run.py --spec .cursor/skills/qmt-local-bt-robust/examples/robust_default.json --dry-run
python hongli_band/scripts/local_bt/app.py   # 模式「实盘评估」
```

产物：`hongli_band/report/robust/<run_id>/`（`summary.json` / `freeze.json` / `basket_XXX/`）。

网格结果页可点「送入实盘评估」。

## 检查清单

```
进度:
- [ ] 1. 网格 summary 已有 recommend
- [ ] 2. spec 含 tune/check/deploy，deploy 晚于 check
- [ ] 3. N/K/seed 与硬软门确认
- [ ] 4. 探针 init 指纹与 overrides 一致（不回放 K 线）
- [ ] 5. summary verdict = GO / NO-GO
- [ ] 6. 不改 config / 不 deploy
```

## 已知限制

- walk 轴跟 chart 股交易日；合格池仅 CSV 年份交集（未做选股资格过滤）
- 篮子可重叠，有效独立样本可能 < N
