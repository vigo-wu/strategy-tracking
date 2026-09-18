# 主题接入契约

仓库里目前只有 `factor_band` 实现了 `scripts/local_bt/`。新主题按本节接上后再扩 runner，不要把 fband 路径写进 SKILL 正文当唯一实现说明。

## 主题必须提供

1. **拼接回放入口**（如 `<theme>/scripts/local_bt/run.py`）
   - `_exec_bundle()` 之后注入 `overrides`（写进 exec 得到的 `ns`）。
   - `init()` 之后再注入一次（防止 `_apply_panel` 把资金/开关打回默认）。
   - 建议包装 `_apply_panel`：面板应用完立即再写 `overrides`，这样 init 日志指纹才是格子值。
   - 因子阈值写 `overrides.factor_params`（如 `stop_loss.pct`）；`RECIPE.structure` 指标周期窗写 `overrides.structure`（如 `ma.1d.mid`）；资金仍写顶层 `CASH_RATIO`。顶层旧键 / 顶层点路径直接报错。fband 因子轴元数据来自 `factors/catalog.py` 的 `LEAVES`，再按买入 `entry`、加仓 `scale_in`、卖出 `exit`、减仓 `scale_out` 四个槽位已启用叶子过滤；未启用叶子不上侧栏。overrides 形态不改。`RECIPE.factor_params` 仍是全表（`recipe=` 指纹 / 参数指纹预检 defaults 不跟目录变窄）。
   - `out_dir` 由调用方指定；批量 payload 带 `overrides` 透传到子进程。
2. **隔离产物目录**：`report/grid/<sweep>/<cell>/<sample>/<div>/`。禁止写回基线 `report/<div>/`。
3. **init 指纹**（写进同一份 log，供 runner 校验）
   - 必有：`recipe=`（表达式 + 折进表的全表 `factor_params` + `structure`）。
   - 人读字段是启用叶子的点路径（如 `atr_stop.k=`、`keltner_vol.vol_n=`、`above_ma.n=`），由 `_recipe_log_kv` 展开；卸下叶子不打。
   - 该格 `overrides.factor_params` 且叶子已启用时，参数指纹预检再核对应路径；`trail_stop.tiers` 用 compact JSON。未启用叶子的覆盖只走 `recipe=`。启用集合读不到则字段级跳过，只核 `recipe=`。
4. **主样本 walk**：默认 config `BOOK_STOCKS` 一段 `run_book_backtest`（`year_start0101`–`year_end1231`）。`asset_split.mode=random_from_csv` 时调参 / 盲测 **各一段**（名单写入 `freeze.json` / `spec.json`；CSV 仍用 `csv_for`）。禁止 stock×年独立 10 万账户，禁止 `tune∪holdout` 同一钱包。
5. **空间隔离（可选）**：`asset_split` 见 skill 示例 `stop_loss_space.json`。主列盈亏仍展示 tune 股；空间分用全区间夏普比进入排名（盲测不再只否决）。某格缺盲测窗则空间维 0 分，不摊权。
6. **`score`**：写入 spec/freeze/summary。侧栏是评分维配置；只汇总按 `score` 重算推荐。`--score-json` 覆盖只汇总。续跑读磁盘 freeze/spec.`score`。旧 spec `gate` 残留可忽略（`--gate-json` WARN 后丢弃）。

## 覆盖值形态

JSON 可序列化。元组在 JSON 里用数组；`null` = Python `None`。

```json
{
  "factor_params": {
    "stop_loss": {"pct": 0.10},
    "time_force": {"bars": 0, "arm": 0.03},
    "scale_arm": {"arm": 0.03, "bars": 8},
    "atr_trail_stop": {"k1": 2.0, "k2": 1.5},
    "trail_stop": {
      "tiers": [
        [0.04, 0.06, 0.015, null],
        [0.06, 0.10, 0.03, 0.03],
        [0.10, null, 0.04, null]
      ]
    }
  },
  "structure": {
    "ema": {"1d": {"mid": 15, "trend": 120}},
    "atr": {"n": 14},
    "keltner": {"ema_n": 20, "atr_n": 20}
  }
}
```

结构轴 id：`ma.1d.mid` `ma.1d.slow` `ma.1d.trend` `ma.1w.mid` `ma.1w.trend` `atr.n` `keltner.ma_n` `keltner.atr_n`。`ma.1d.trend` 是显式写入的价格均线窗，不是 `above_ma` 的周期；`above_ma` 周期是 `above_ma.n`。短 id 如 `m1dm15` / `m1dt` / `atr` / `kmm` / `kat`。出场另有 `atr_stop.k`（短 id `ask`）、`atr_trail_stop.k1` / `k2`（`atk1` / `atk2`，浮点倍数轴，**不是**百分比轴）、`time_force.arm`（`tfa`，百分比）。不要写顶层 `D_MA_MID`、顶层 `d_ma.mid` / `ma.1d.mid`，或袋内旧段 `d_ma`/`w_ma`/`macd`/`ema`/`sma`。

空 `overrides` = `base`（现行片段常量，仍跑一遍以便对照目录与指纹）。

## 格子之间

- **全局单层多进程池**：参数指纹预检在主进程串行；通过后把**当前组**各格 walk 铺平进同一个 `ProcessPool`（最多 2 段/格：tune + holdout）。禁止格间池再套格内池；禁止一次把全部格子丢进同一池。
- `--workers<=0`：`min(本组 n_cells × n_jobs, CPU)`；`1` 全串行；`>=2` 为池大小（只夹 walk 数，不夹 16）。
- `--batch-size` / `--resume` / `progress.json`：组级检查点。`done` 跳过；`dirty` 或杀进程留下的 `running` 整组删目录后重跑。UI 暂停须杀进程树后用操作系统命令行双重核对 pid，确认退出再标 dirty / 删目录，避免残留进程导致误删。cmdline 证明已死或 pid 不存在才自动 dirty。`--resume` 不 prune。summarize 只收已 done 的 cell id。
- 每格写 `cell_meta.json`（`overrides`、kind、walk 数）。
- 每格先跑 **参数指纹预检**（Dummy Context Check，不回放 K 线），指纹不对则**停止整个 sweep**。通过后该格全部 walk 再跑（第一段不再兼预检）。
- 资金：`compound_backtest=True`，`wallet_cash=TRADE_BUDGET`；`BUDGET_BASE` / `CASH_RATIO` 跟现行 config。

## summarize 口径

解析组合明细（`window_kpi_from_trades`）。每格主样本 `book` 输出窗 KPI（旧目录残留的 `sma/`/`ema/` 不进 summary）：

- 笔数 / 胜率 / 盈亏比：平仓日落在窗内（已是抢槽后的成交）
- 回撤 / 夏普 / 卡玛 / 年化：窗内同一条权益；卡玛 = 几何年化 / `|max_dd|`
- 几何年化 \((E_{end}/E_{start})^{1/n}-1\)，\(n=\) 窗内日历年数（空年也算）
- 主表 `sum_pnl` / `is_pnl` / `oos_pnl` = 对应窗账户盈亏 \(E_{end}-E_{start}\)
- 权益 = 预算 + 已实现盈亏台阶（与 robust 相同，不承诺全日盯市）
- 推荐：`pick_recommend` 按四维综合分排序（`grid_score.score_cell`，读取 `score` 配置）；`candidates[]` 带 `s_def` / `s_str` / `s_res` / `s_gen` / `total`。无空间隔离时 `s_gen` 为 null 且权重摊到另三维。`summary.score` 写本次评分配置。

年份窗口读该 sweep 的 `spec.json`。若目录仍是旧 `local_bt_{code}_{SZ|SH}_{year}_{MA}.txt`，直接报错要求重跑。

写出 `<theme>/report/grid/<sweep>/summary.json`。选参规则见 SKILL.md，不要在 summarize 里改 `config.py`。

## 新策略接入网格 5 项 Checklist

1. **`overrides` 注入**：`run.py` 在 `_exec_bundle()` 之后与 `init()` 之后各写一次（防止 `_apply_panel` 把资金/开关打回默认）；`book_backtest.py` 的 `run_book_backtest` 接受 `overrides`，资金键 `compound_backtest` / `wallet_cash`。
2. **隔离产物目录**：`report/grid/<sweep>/<cell>/<sample>/<div>/`。禁止写回基线 `report/<div>/`。`out_dir` 由调用方指定。
3. **init 指纹字段**：同一份 log 打出 `recipe=`。人读字段是启用叶子的点路径。参数指纹预检必核 `recipe=`；格子 overrides 且已启用的路径可选核对。启用集合读不到则字段级跳过。
4. **主样本 walk 限制**：默认 `BOOK_STOCKS` 一段 `run_book_backtest`。`asset_split.mode=random_from_csv` 时调参 / 盲测各一段。禁止 stock×年独立账户，禁止 `tune∪holdout` 同一钱包。主题 `grid_run.py` 提供 book walk 列表（不是 stock×年）。
5. **全局单层多进程池 / 禁止嵌套**：格间池不得再套格内池；一次只提交一组。参数指纹预检在主进程串行通过后再铺 walk。
