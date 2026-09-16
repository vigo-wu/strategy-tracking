---
name: qmt-local-bt-robust
description: >-
  参数锁定后做实盘评估：从宇宙随机抽 N 组真组合连续回放，按四维综合分中位值裁决 GO/NO-GO。
  Use when the user mentions 实盘评估、上实盘验收、随机组合回放、稳健门、能否上实盘、
  robust gate、post-grid portfolio validation.
---

# 实盘评估（流水线第 2 步）

网格选参之后、选股之前：锁定 `overrides`，随机组合真回放，判断策略是否达到预期。

## 一票否决 / 禁止行为

| 需求 | 走哪个 |
| :--- | :--- |
| 选 STOP_LOSS / TRAIL 等参数 | `qmt-local-bt-grid` |
| 打分选票 / walk-forward | 选股方案打分 / 数据分析 walk-forward |
| 终端 log 画图 | `qmt-backtest-report` |
| DSR / PBO | `skill-backtest-overfit` |

**禁止**把本技能当成网格选参。 **禁止**用单票预算加总冒充组合。

## 硬规则

1. **真组合**：`run_book_backtest` / `run_one_basket`，禁止单票预算加总冒充组合。
2. **灌参**：默认空 = 现行 config；可选 `overrides_from` → `overrides_cell_id` 或 `summary.recommend.id` → `cells[].overrides`。网格页可选手动格子 id 送入。
3. **时间嵌套**：`deploy_start > check_end`。GO **不再**只看盲测窗：盲测进泛化与盈亏盾；结构 / 复原仍用调参 vs 验收（盲测不进 `S_Str`）。
4. **四维综合分**：复用网格 `score_cell(..., space_on=True)`。笔数门槛是验收窗绝对笔数（默认 `n_trades_floor=30`），**不再** `per_stock_year_min`。公式形状仍走 `qmt-local-bt-grid/scripts/grid_score.py`。
5. **整次 GO**：已打分组的中位总分 ≥ `go_floor`（默认 50，单位是分不是 0.50）。`n_scored=0` → NO-GO。不把通过率 / 中位卡玛 / P10 回撤当否决。
6. **默认不改 config / 不 deploy / 不写 BOOK_STOCKS**。
7. **全局单层多进程池（组级）**：`--workers` / 侧栏进程数 = 全局进程数。`0` → `min(N, CPU)`；`1` 串行；`≥2` 铺开全部未完成组。禁止嵌套进程池。进度 = `(已完成组 + 在跑 bar 分数) / N`，参数指纹预检不占分母。
8. **UI 后台进程**：`Popen` `robust_run.py`，读 `progress.json`。caption 含路数/阶段；参数指纹预检与启池先写盘。暂停须杀进程树，再用操作系统命令行双重核对 pid，确认退出后再处理目录；**已完成组留盘**，禁止套用网格 dirty 删目录（残留进程未退出时删目录会误删正在写入的产物）。继续靠成交表缓存跳过已完成组。
9. **抽标与网格同资格**：宇宙 `tools/csv/none`，`list_eligible_stocks`（回测年起止，可选 `full_span`）。语义仍是 N 组 × K 只、组可重叠，不是 tune/holdout。改 N/K/seed/年份/`full_span` 须再抽；名单空或指纹变了则开跑自动抽。

## 窗口映射（打分）

每组 `tune` / `check` / `deploy` 组装成与网格同构的 book 后再 `score_cell`：

- `windows.tune` / `windows.check`：照旧
- `windows.all`：年份集合 = 调参年份 ∪ 验收年份（**不要**写成 `year_start`–`check_end`，空年会进几何年化分母）
- `holdout_windows.all` 与 `holdout_windows.check`：都填盲测 `deploy` KPI

防御仍用同账户 all/tune/check（盲测回撤不混入）；盈亏盾第三节点 = 盲测；结构/复原只用调参 vs 验收；泛化 = 盲测夏普 / 调参∪验收夏普。`space_on` 恒为 True。缺盲测窗或盲测夏普 ≤0 则 `S_Gen=0`。

侧栏改旋钮后主表现算；点「只汇总」或 CLI `--score-json` 把 `summary.score` 与裁决落盘，不必重跑 walk。旧 summary 无 `windows.all` 时须先「只汇总」从成交表重算。`--gate-json` WARN 后忽略。旧 spec `gate` 残留可忽略。

## 窗内 KPI

| 指标 | 口径 |
| :--- | :--- |
| 笔数 / 胜率 / 盈亏比 | 平仓日落在窗内 |
| 回撤 / 夏普 / 卡玛 | 窗内组合权益路径；卡玛 = 窗内几何年化 / `|max_dd|` |

## 怎么跑

```bash
python factor_band/scripts/local_bt/robust_run.py --spec .cursor/skills/qmt-local-bt-robust/examples/robust_default.json --dry-run
python factor_band/scripts/local_bt/robust_run.py --spec factor_band/report/robust/<run_id>/freeze.json --summarize-only --score-json '{"go_floor":50}'
python factor_band/scripts/local_bt/app.py   # 模式「实盘评估」
```

产物：`factor_band/report/robust/<run_id>/`（`summary.json` / `freeze.json` / `progress.json` / `basket_XXX/`）。

网格结果页可点「送入实盘评估」。

## 检查清单

```
进度:
- [ ] 1. 网格 summary 已有 recommend
- [ ] 2. spec 含 tune/check/deploy，deploy 晚于 check
- [ ] 3. N/K/seed/full_span 与评分维 / go_floor 确认；已抽取或开跑自动抽
- [ ] 4. 参数指纹预检与 overrides 一致（不回放 K 线）
- [ ] 5. 组间全局单层多进程池；progress 分母 = N
- [ ] 6. summary 按中位综合分裁决 GO / NO-GO
- [ ] 7. 不改 config / 不 deploy
```

## 已知限制

- walk 轴跟 chart 股交易日；合格池仅 CSV 年份交集（未做选股资格过滤）
- 篮子可重叠，有效独立样本可能 < N
