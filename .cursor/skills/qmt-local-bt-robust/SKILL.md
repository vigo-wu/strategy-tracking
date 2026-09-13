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
| 打分选票 / walk-forward | 选股方案打分 / 数据分析 walk-forward |
| 终端 log 画图 | `qmt-backtest-report` |
| DSR / PBO | `skill-backtest-overfit` |

## 硬规则

1. **真组合**：`run_book_backtest` / `run_one_basket`，禁止单票预算加总冒充组合。
2. **灌参**：默认空 = 现行 config；可选 `overrides_from` → `overrides_cell_id` 或 `summary.recommend.id` → `cells[].overrides`。网格页可选手动格子 id 送入。
3. **时间嵌套**：`deploy_start > check_end`；GO/NO-GO **只看盲测窗**。
4. **硬门**：卡玛 / 回撤 / 夏普 / 盈亏比。**软门**：胜率 / 笔数（默认 `veto=false` 只 warn）。
5. **整次 GO**：`pass_rate` ∧ 中位卡玛 ∧ P10 回撤。
6. **默认不改 config / 不 deploy / 不写 BOOK_STOCKS**。
7. **一层组池**：`--workers` / 侧栏进程数 = 全局进程数。`0` → `min(N, CPU)`；`1` 串行；`≥2` 铺开全部未完成组。禁止嵌套进程池。进度 = `(已完成组 + 在跑 bar 分数) / N`，探针不占分母。
8. **UI 后台进程**：`Popen` `robust_run.py`，读 `progress.json`。caption 含路数/阶段；探针与启池先写盘。暂停杀进程树，**已完成组留盘**，禁止套用网格 dirty 删目录。继续靠成交表缓存跳过已完成组。
9. **抽标与网格同资格**：宇宙 `tools/csv/none`，`list_eligible_stocks`（回测年起止，可选 `full_span`）。语义仍是 N 组 × K 只、组可重叠，不是 tune/holdout。改 N/K/seed/年份/`full_span` 须再抽；名单空或指纹变了则开跑自动抽。

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

产物：`hongli_band/report/robust/<run_id>/`（`summary.json` / `freeze.json` / `progress.json` / `basket_XXX/`）。

网格结果页可点「送入实盘评估」。

## 检查清单

```
进度:
- [ ] 1. 网格 summary 已有 recommend
- [ ] 2. spec 含 tune/check/deploy，deploy 晚于 check
- [ ] 3. N/K/seed/full_span 与硬软门确认；已抽取或开跑自动抽
- [ ] 4. 探针 init 指纹与 overrides 一致（不回放 K 线）
- [ ] 5. 组间一层池；progress 分母 = N
- [ ] 6. summary verdict = GO / NO-GO
- [ ] 7. 不改 config / 不 deploy
```

## 已知限制

- walk 轴跟 chart 股交易日；合格池仅 CSV 年份交集（未做选股资格过滤）
- 篮子可重叠，有效独立样本可能 < N
