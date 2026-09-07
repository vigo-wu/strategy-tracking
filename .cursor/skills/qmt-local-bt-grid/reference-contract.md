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
   - 扫阶梯止盈：`trail_arm=` = `TRAIL_TIERS` 档 1 的 `peak_lo`。
4. **主样本 job 列表**：默认 config `BOOK_STOCKS` × spec 回测年（均线/复权锁在跟踪池配置里）。`asset_split.mode=random_from_csv` 时改为从 `tools/csv/none` 抽取的 `tune_stocks ∪ holdout_stocks`（名单写入 `freeze.json` / `spec.json`；建 job 仍用现有 `csv_for`）。
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

- 格内：可按现有 `ProcessPool`（同 CSV 分组）。
- 格间：**串行**，避免进程数 × 格数爆炸。
- 每格写 `cell_meta.json`（`overrides`、kind、job 数）。
- 先跑该格第一份 job 做探针，指纹不对则**停止整个 sweep**。

## summarize 口径

复用主题已有的 log 解析（hongli_band：`parse_local_bt_log`，认 `BUY filled` 的 `lots=` / `@close=`，不要用终端 `generate_report.parse_trades`）。

每格、每个样本（`book` / `sma` / `ema`）输出：合计盈亏、胜率、利润因子、调参期、验收期、分年、出场结构、相对 `base` 的 Δ。年份窗口读该 sweep 的 `spec.json`。

写出 `<theme>/report/grid/<sweep>/summary.json`。选参规则见 SKILL.md，不要在 summarize 里改 `config.py`。

## 新主题最小增量

1. `run.py`：`overrides` 注入 + 任意 `out_dir`。
2. `batch_job.py`：payload `overrides` 透传。
3. 跟踪池 `BOOK_STOCKS`（主样本）。
4. 在主题 `scripts/local_bt/grid_run.py`（或共享 runner 的 `--theme`）里提供 job 列表。
5. init 日志带指纹字段。
