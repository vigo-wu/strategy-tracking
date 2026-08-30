---
name: qmt-local-bt-grid
description: >-
  用真实 local_bt（拼接脚本 + CSV 回放）对少量命名参数做隔离网格重跑，输出主样本与对照组，
  按样本外稳健性选参。Use when the user mentions 网格回测、最优参数、实跑扫参、
  STOP_LOSS/TRAIL/TIME_FORCE 确认、local_bt 网格、命名格子、对照重跑，
  或要把风控阈值从反事实改成完整回放结论。
---

# 真实 local_bt 网格确认

对出场/风控常量做**完整拼接脚本 + 日线 CSV 回放**，禁止用 MAE 反事实当选参结论。
结论格子必须改运行时覆盖，禁止为扫参改主题 `config.py`。

MAE 为何不可信、本轮数字：需要时再读 [reference-lessons.md](reference-lessons.md)。
新主题怎么接：`[reference-contract.md](reference-contract.md)`。

## 何时使用

- 用户要确认 STOP_LOSS / TRAIL_TIERS / TIME_FORCE_*（或同类出场阈值）哪个更好
- 用户说网格、扫参、最优参数、对照重跑、样本外选参
- 已有基线 `local_bt` 报告（含每年均线 winner 名单）

## 不要用错

| 需求 | 走哪个 |
| :--- | :--- |
| 终端 log 画成交/权益/K 线 | `qmt-backtest-report` |
| DSR / PBO / Haircut | `skill-backtest-overfit`（网格 JSON 可事后交给它，本 Skill 不内嵌） |
| 固定买入的反事实预筛 | `stop_loss_mae.py` 等可选用；**预筛不得写入推荐** |
| 改片段并上终端 | 用户明确说「按建议修改」后再改 `config` + `_deploy_qmt_gbk.py` |

## 硬规则

1. **只扫有经济含义的命名变体**，默认 ≤8 格（含 `base`）。禁止 12 维笛卡尔积。
2. **必须含现行 `base`**。收紧 / 放宽分开标，不要混成一个「更好」。
3. 关联常量不顺手改：动 TRAIL 起步不改 `SCALE_ARM` / `TIME_FORCE_MIN_RET`，除非格子里显式写了。
4. `TIME_FORCE_BARS<=0` 关闭整条 time_force；`MIN_RET=0` 只关掉让路，不是关闭 time_force。
5. **冻结**基线 winner 名单（stock × year × MA），其它格子用同一组。禁止每格重算 winner。
6. 每格写入主题 `report/grid/<sweep>/<cell>/`，**不得覆盖** `report/front_ratio/` 等基线 log。
7. 格子之间**串行**；格内可用现有 ProcessPool。
8. 开跑后校验 init 指纹：`stop=` / `time_force_bars=`（扫 TRAIL 时还要 `trail_arm=`）与该格一致，不一致则停。
9. **默认不改 `config.py`、不 deploy**。用户说「按建议修改」再改片段并部署。

## 选参

相对 `base`：合计、利润因子、分年回撤；**OOS 为主**（主样本 2018–2022 IS / 2023–2026 OOS）；
IS 与 OOS 同向；跟踪池 4 只同向。接近则少改结构。不追样本内尖峰。
OOS 与 4 只一正一负则维持现行。

Agent 输出：Canvas（各格 Δ / OOS / 4 只）+ **一句推荐**。不要把 MAE 数字写进推荐。

## 检查清单

```
进度:
- [ ] 1. 命名格子 JSON（含 base，≤8，收紧/放宽分开）
- [ ] 2. 基线 winner CSV 存在；冻结名单，不重算
- [ ] 3. 运行时 overrides（禁止改 config 扫参）
- [ ] 4. 隔离 report/grid/<sweep>/；格间串行
- [ ] 5. 探针 log 指纹与格子一致
- [ ] 6. summarize → summary.json；OOS + 4 只选参
- [ ] 7. Canvas + 一句推荐；默认不改 config / 不 deploy
```

## 怎么跑（hongli_band 首个实现）

仓库根目录。其它主题未接 `scripts/local_bt/` 前不要把路径写死成唯一实现。

```bash
python hongli_band/scripts/local_bt/grid_run.py --spec .cursor/skills/qmt-local-bt-grid/examples/stop_loss.json
python hongli_band/scripts/local_bt/grid_run.py --spec path/to/cells.json --book-only
python hongli_band/scripts/local_bt/grid_run.py --spec path/to/cells.json --include-sma-ema
python .cursor/skills/qmt-local-bt-grid/scripts/summarize.py --sweep-dir hongli_band/report/grid/<sweep>
```

`grid_run.py` 结束时会调 summarize，写出 `hongli_band/report/grid/<sweep>/summary.json`（`report/` 已 gitignore）。

| 参数 | 含义 |
| :--- | :--- |
| `--spec` | 命名格子 JSON/YAML（须含 `id=base`） |
| `--book-only` | 只跑跟踪池 4 只（冒烟） |
| `--include-sma-ema` | 额外全 SMA / 全 EMA 对照（不参与冻结 winner） |
| `--workers` | 格内进程数；格子之间始终串行 |
| `--summarize-only` | 不重跑，只解析已有格子 log |

## 格子 JSON

```json
{
  "theme": "hongli_band",
  "sweep": "stop_loss_confirm",
  "compare_div": "front_ratio",
  "cells": [
    {"id": "base", "label": "现行 8%", "kind": "base", "overrides": {}},
    {"id": "sl06", "label": "止损 6%", "kind": "tighten", "overrides": {"STOP_LOSS": 0.06}},
    {"id": "sl10", "label": "止损 10%", "kind": "loosen", "overrides": {"STOP_LOSS": 0.10}}
  ]
}
```

`kind`：`base` / `tighten` / `loosen` / `off` / `other`。`overrides` 的键是拼接脚本里的全局名（如 `STOP_LOSS`、`TRAIL_TIERS`、`TIME_FORCE_BARS`）。
