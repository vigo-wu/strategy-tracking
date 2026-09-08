# 主题接入契约

仓库里目前只有 `hongli_band` 实现了 `scripts/local_bt/`。新主题按本节接上后再扩 runner，不要把 hlband 路径写进 SKILL 正文当唯一实现说明。

## 主题必须提供

1. **拼接回放入口**（如 `<theme>/scripts/local_bt/run.py`）
   - `_exec_bundle()` 之后注入 `overrides`（写进 exec 得到的 `ns`）。
   - `init()` 之后再注入一次（防止 `_apply_panel` 把面板键如 `STOP_LOSS` 打回默认）。
   - 建议包装 `_apply_panel`：面板应用完立即再写 `overrides`，这样 init 日志指纹才是格子值。
   - 函数体用运行时全局查找 `STOP_LOSS` / `TRAIL_TIERS` / `TIME_FORCE_*` 等，改 `ns` 即可生效。
   - `out_dir` 由调用方指定；批量 payload 带 `overrides` 透传到子进程。
2. **隔离产物目录**：`report/grid/<sweep>/<cell>/<sample>/<div>/`。禁止写回基线 `report/<div>/`。
3. **init 指纹**（写进同一份 log，供 runner 校验）
   - 必有：`stop=`、`time_force_bars=`（若策略有这两项）。
   - 扫阶梯止盈：`trail_arm=` = `TRAIL_TIERS` 档 1 的 `peak_lo`；另打 compact `trail_tiers=` JSON，探针按整表相等（起步相同、giveback 不同也要能抓到）。
4. **主样本 walk**：默认 config `BOOK_STOCKS` 一段 `run_book_backtest`（`year_start0101`–`year_end1231`）。`asset_split.mode=random_from_csv` 时调参 / 盲测 **各一段**（名单写入 `freeze.json` / `spec.json`；CSV 仍用 `csv_for`）。禁止 stock×年独立 10 万账户，禁止 `tune∪holdout` 同一钱包。
5. **可选对照**：全 SMA / 全 EMA（`include_sma_ema`），不单独当选参器。
6. **空间隔离（可选）**：`asset_split` 见 skill 示例 `stop_loss_space.json`。选参主 KPI 仅 tune 股；holdout × 验收年复用 `gate` 否决（无覆盖不得过门）。
7. **过门 `gate`**：绝对合格线（可逐项禁用）+ 可选相对 base + 可选卡玛同向；指标用 `windows.check.*`；排序用验收期卡玛 Δ。写入 spec/freeze/summary；只汇总可 `--gate-json` / 侧栏覆盖。

## 覆盖值形态

JSON 可序列化。元组在 JSON 里用数组；`null` = Python `None`。

```json
{
  "STOP_LOSS": 0.10,
  "TIME_FORCE_BARS": 0,
  "TRAIL_TIERS": [
    [0.04, 0.06, 0.015, null],
    [0.06, 0.10, 0.03, 0.03],
    [0.10, null, 0.04, null]
  ]
}
```

空 `overrides` = `base`（现行片段常量，仍跑一遍以便对照目录与指纹）。

## 格子之间

- **一层全局 walk 池**：探针在主进程串行；通过后把各格 walk 铺平进同一个 `ProcessPool`（最多 6 段/格：分篮 × SMA/EMA）。禁止格间池再套格内池。
- `--workers<=0`：`min(n_cells × n_jobs, CPU)`；`1` 全串行；`>=2` 为池大小（只夹 walk 数，不夹 16）。
- 每格写 `cell_meta.json`（`overrides`、kind、walk 数）。
- 每格先跑 **init 探针**（dummy context，不回放 K 线），指纹不对则**停止整个 sweep**。通过后该格全部 walk 再跑（第一段不再兼探针）。
- 资金：`compound_backtest=True`，`wallet_cash=TRADE_BUDGET`；`BUDGET_BASE` / `CASH_RATIO` 跟现行 config。

## summarize 口径

解析组合明细（`window_kpi_from_trades`）。每格、每个样本（`book` / `sma` / `ema`）输出窗 KPI：

- 笔数 / 胜率 / 盈亏比：平仓日落在窗内（已是抢槽后的成交）
- 回撤 / 夏普 / 卡玛 / 年化：窗内同一条权益；卡玛 = 几何年化 / `|max_dd|`
- 几何年化 \((E_{end}/E_{start})^{1/n}-1\)，\(n=\) 窗内日历年数（空年也算）
- 主表 `sum_pnl` / `is_pnl` / `oos_pnl` = 对应窗账户盈亏 \(E_{end}-E_{start}\)
- 权益 = 预算 + 已实现盈亏台阶（与 robust 相同，不承诺全日盯市）

年份窗口读该 sweep 的 `spec.json`。若目录仍是旧 `local_bt_{code}_{SZ|SH}_{year}_{MA}.txt`，直接报错要求重跑。

写出 `<theme>/report/grid/<sweep>/summary.json`。选参规则见 SKILL.md，不要在 summarize 里改 `config.py`。

## 新主题最小增量

1. `run.py`：`overrides` 注入 + 任意 `out_dir`（`init` 打出 `stop=` / `time_force_bars=` / `trail_arm=` / `trail_tiers=` JSON）。
2. `book_backtest.py`：`run_book_backtest` 接受 `overrides`，资金键 `compound_backtest` / `wallet_cash`。
3. 跟踪池 `BOOK_STOCKS`（主样本组合 walk）。
4. 在主题 `scripts/local_bt/grid_run.py` 里提供 book walk 列表（不是 stock×年）。
5. init 日志带指纹字段。
