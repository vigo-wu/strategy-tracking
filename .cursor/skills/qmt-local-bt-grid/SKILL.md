---
name: qmt-local-bt-grid
description: >-
  用真实 local_bt（拼接脚本 + CSV 回放）对少量命名参数做隔离网格重跑，输出主样本，
  按样本外稳健性选参。Use when the user mentions 网格回测、最优参数、实跑扫参、
  stop_loss.pct / TRAIL / TIME_FORCE 确认、local_bt 网格、命名格子、对照重跑，
  或要把风控阈值从反事实改成完整回放结论。
---

# 真实 local_bt 网格确认

对出场/风控常量做**完整拼接脚本 + 日线 CSV 回放**，禁止用 MAE 反事实当选参结论。
结论格子必须改运行时覆盖，禁止为扫参改主题 `config.py`。

MAE 为何不可信、本轮数字：需要时再读 [reference-lessons.md](reference-lessons.md)。
新主题怎么接：`[reference-contract.md](reference-contract.md)`。

## 何时使用

- 用户要确认 `stop_loss.pct` / `atr_stop.k` / `atr_trail_stop.k1` / `k2` / `trail_stop.tiers` / `time_force.bars` / `time_force.arm`（或同类出场阈值）哪个更好
- 用户说网格、扫参、最优参数、对照重跑、样本外选参
- 已有主题 `scripts/local_bt/` 与 config `BOOK_STOCKS`

## 不要用错

| 需求 | 走哪个 |
| :--- | :--- |
| 终端 log 画成交/权益/K 线 | `qmt-backtest-report` |
| DSR / PBO / Haircut | `skill-backtest-overfit`（网格 JSON 可事后交给它，本 Skill 不内嵌） |
| 固定买入的反事实预筛 | `stop_loss_mae.py` 等可选用；**预筛不得写入推荐** |
| 改片段并上终端 | 用户明确说「按建议修改」后再改 `config` + `_deploy_qmt_gbk.py` |

## 硬规则

1. **只扫有经济含义的命名变体**，默认 ≤8 格。禁止 12 维笛卡尔积。
2. 格子 = **扫描取值笛卡尔积**，不自动插入现行档。扫描值全等于 config 的格打 `is_current` / `★现行`。不强制 `id=base`。
3. 关联常量不顺手改：动 `trail_stop.tiers` 整表不改 `SCALE_ARM`。让路是 `time_force.arm`；禁止顶层 `TIME_FORCE_MIN_RET`；旧 spec 含该轴须拒绝重存。
4. `time_force.bars<=0` 关闭整条 time_force。`time_force.arm<=0` 关让路（站上慢线也日历强平）。
5. **主样本**：默认=跟踪池 `BOOK_STOCKS` 一段组合连续回放（`year_start0101`–`year_end1231`，单账户、最多 3 笔、`CASH_RATIO×`权益复利）。`asset_split.mode=random_from_csv` 时调参篮 / 盲测篮 **各跑一段**（两套钱包，禁止 `tune∪holdout` 同一 book）。均线锁 `BOOK_STOCKS[].ma_type` / 全局 `MA_TYPE`。旧 `report/grid/<sweep>/` 的 stock×年 log **须重跑**，禁止只汇总。
6. **时空双重隔离**：时间用 `tune_*` / `check_*`；空间用 `tune_stocks` / `holdout_stocks`（盲测只否决、不参与格子比大小）。`mode=off` 时无空间门。
7. 每格写入主题 `report/grid/<sweep>/<cell>/`，**不得覆盖** `report/front_ratio/` 等基线 log。
8. **一层全局 walk 池**（禁止格间×格内嵌套 ProcessPool）：`--workers` / `grid_workers` = 全局进程数。`<=0` 自动 `min(walk 数, CPU)`；`1` 全串行；`>=2` 铺平**当前组**各格 walk 进同一池（不夹 16）。一次只提交一组，禁止把全部格子塞进同一个池。格内最多 2 段（tune + holdout）。进度 = (已完成 walk + 在跑 bar 分数) / `(本组格数 × n_jobs)`，探针不占分母。
9. 每格先跑 init 探针（dummy context，不回放 K 线）校验指纹：`stop=` / `time_force_bars=`；`time_force_min_ret=` = `time_force.arm`（标签名不改）；`trail_arm=` = `trail_stop.tiers` 档1 `peak_lo`（与让路脱钩）。扫 `trail_stop.tiers` 时核 compact `trail_tiers=` JSON（整表相等）。改档1 不得改 `time_force_min_ret=`。不一致则停。通过后该格全部 walk 再跑。
10. **分组续跑**：`report/grid/<sweep>/progress.json`。已 `done` 的组跳过；未跑完的组标 `dirty`，继续时**整组清空重跑**。`--resume` 不 prune。`--cell` 与 `--resume` / `--batch-size>0` 互斥。CLI `--batch-size` 默认 0（一组=现状）；UI 默认 10。UI 暂停杀进程树，**等到 pid 退出后再 dirty**；认活用 cmdline（Win11 走 CIM，不依赖 wmic）——命令行读不到且 pid 仍在则**不**自动删目录。CLI 可用 `pause.flag`。summarize 只传已 done 的格子 id。未跑完时推荐只基于已完成组。格子数>8 只 WARN、**不阻断、不等确认**。
11. **默认不改 `config.py`、不 deploy**。用户说「按建议修改」再改片段并部署。

## 选参

过门 = **侧栏/spec `gate` 已启用的绝对合格线** ∧（可选）相对现行格不劣 ∧（可选）调参/验收卡玛同向。无 `is_current` / `id=base` 格时相对门与同向跳过。
默认关闭：卡玛绝对线、笔数、卡玛同向、相对现行。默认开启：回撤、夏普、胜率、盈亏比。
指标一律用窗内 `windows.check.*`（空间隔离时盲测用 `holdout_windows.check.*` 复用同一 gate 否决）；禁止用样本级整段 `max_dd`/`win_rate`。
口径：几何年化 \((E_{end}/E_{start})^{1/n}-1\)（空年也算）、路径回撤、卡玛 = 几何年化 / `|max_dd|`、账户盈亏 \(E_{end}-E_{start}\)。权益 = 预算 + 已实现盈亏台阶（与实盘评估相同，不承诺全日盯市）。验收窗接在调参权益之后（同一 walk 切开）。过门数字默认仍是 1.5 / 10% / 0.8，但抢槽后通过率会变，须用新跑的 ★现行格看线。
通过者按验收期**卡玛**排序（接近则少改与 config 的差异键）；盈亏仅展示。全不过则无推荐（不要写「最优」或「维持现行」）。侧栏可逐项启用/改阈值；「只汇总」传入当前侧栏 gate 重算推荐（不回写 widget 键）。

Agent 输出：过门推荐一句。不要把 MAE 数字写进推荐。

## 检查清单

```
进度:
- [ ] 1. 扫描叉乘格子 JSON（≤8；等于 config 则 ★现行）
- [ ] 2. 主样本=BOOK_STOCKS（或 asset_split 分篮）组合 walk；spec 含回测年 / 调参期 / 验收期；旧 stock×年 sweep 须重跑
- [ ] 3. 若空间隔离：freeze 含 tune/holdout；盲测只否决
- [ ] 4. 运行时 overrides（禁止改 config 扫参）
- [ ] 5. 隔离 report/grid/<sweep>/；一层全局 walk 池（禁止嵌套）
- [ ] 6. 探针 init 指纹与格子一致（只跑 init，不走 K 线）
- [ ] 7. summarize → summary.json；绝对过门 + 验收期卡玛推荐
- [ ] 8. 一句过门推荐；默认不改 config / 不 deploy
```

## 怎么跑（hongli_band 首个实现）

仓库根目录。其它主题未接 `scripts/local_bt/` 前不要把路径写死成唯一实现。

```bash
python hongli_band/scripts/local_bt/grid_run.py --spec .cursor/skills/qmt-local-bt-grid/examples/stop_loss.json
python hongli_band/scripts/local_bt/grid_run.py --spec path/to/cells.json --batch-size 10
python hongli_band/scripts/local_bt/grid_run.py --resume --sweep-dir hongli_band/report/grid/<sweep>
python hongli_band/scripts/local_bt/grid_run.py --spec .cursor/skills/qmt-local-bt-grid/examples/stop_loss_space.json --reshuffle
python .cursor/skills/qmt-local-bt-grid/scripts/summarize.py --sweep-dir hongli_band/report/grid/<sweep>
```

`grid_run.py` 结束时会调 summarize，写出 `hongli_band/report/grid/<sweep>/summary.json`（`report/` 已 gitignore）。

| 参数 | 含义 |
| :--- | :--- |
| `--spec` | 命名格子 JSON/YAML |
| `--workers` | 全局并行进程数（0=自动=min(walk数, CPU)；1=串行；格间与格内 walk 共用一层池） |
| `--batch-size` | 每组格子数；0=一组跑完全部（CLI 默认）。未完成组整组重来 |
| `--resume` | 同一 sweep 续跑：跳过 done，dirty 整组重跑；读磁盘 spec/freeze，忽略侧栏年份 |
| `--summarize-only` | 不重跑，只 summarize |
| `--year-start` 等 | 覆盖 spec 回测年 / 调参期 / 验收期 |
| `--asset-mode` | `off` / `random_from_csv` |
| `--n` | 空间抽取：调参与盲测各抽此数（互不重叠） |
| `--n-tune` / `--n-holdout` / `--seed` | 旧覆盖；与 `--n` 同时出现时 `--n` 优先。缺 seed 则系统随机 |
| `--reshuffle` | 忽略 freeze 旧名单重新抽取 |
| `--gate-json` | 过门配置 JSON 文件或内联对象（覆盖 spec.gate；只汇总同样生效） |
| `--dry-run` | 只打印每格 walk 数 |

## 格子 JSON

```json
{
  "theme": "hongli_band",
  "sweep": "stop_loss_confirm",
  "compare_div": "front_ratio",
  "year_start": 2018,
  "year_end": 2026,
  "tune_start": 2018,
  "tune_end": 2022,
  "check_start": 2023,
  "check_end": 2026,
  "cells": [
    {"id": "base", "label": "现行 8%", "kind": "base", "overrides": {}},
    {"id": "sl06", "label": "止损 6%", "kind": "tighten", "overrides": {"factor_params": {"stop_loss": {"pct": 0.06}}}},
    {"id": "sl10", "label": "止损 10%", "kind": "loosen", "overrides": {"factor_params": {"stop_loss": {"pct": 0.10}}}}
  ]
}
```

空间隔离示例见 `examples/stop_loss_space.json`（`asset_split.mode=random_from_csv`，宇宙默认 `tools/csv/none`）。

`kind`：`base` / `tighten` / `loosen` / `off` / `other`（`id=base` 仅兼容旧 spec）。扫描生成的格子用 token id；等于 config 时 `is_current=true`。因子/结构轴 id 是点路径（如 `stop_loss.pct`、`atr_stop.k`、`atr_trail_stop.k1` / `k2`、`time_force.arm`、`d_ma.mid`、`atr.n`）；格子 `overrides` 写成 `{"factor_params": {"stop_loss": {"pct": 0.06}}}`、`{"factor_params": {"atr_stop": {"k": 2}}}`、`{"factor_params": {"atr_trail_stop": {"k1": 2}}}`、`{"factor_params": {"time_force": {"arm": 0.03}}}` 或 `{"structure": {"d_ma": {"mid": 15}}}` / `{"structure": {"atr": {"n": 14}}}`。`atr_trail_stop.k1` / `k2` 不是百分比轴。资金仍是顶层全局名（`CASH_RATIO`）。顶层旧键（`STOP_LOSS` / `D_MA_MID`）和顶层点路径（`stop_loss.pct` / `d_ma.mid`）都直接报错。

## 已知限制（继承 `run_book_backtest`）

- walk 日历跟排序第一只票的交易日。
- 回测无集合竞价冻结 / `_allocate_equal`。
- `_buy_budget_fixed` 按 cap×档位，不走实盘 `min(现金, 房间)`。
- 这些与固定标的 / 实盘评估一致；本轮不改 `budget.py`、不改主题 `config.py`、不 deploy。
