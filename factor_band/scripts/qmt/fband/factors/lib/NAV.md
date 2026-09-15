# hlband/factors/lib · 因子叶子

一 id 一文件。接口：`_factor_eval_<id>(ctx) → (bool, detail)`。  
中性：只回答「条件是否成立」，买/卖/加/减由 [../NAV.md](../NAV.md) 的 Recipe / Intent 赋予。

登记表：[../catalog.py](../catalog.py) 的 `LEAVES`（`registry` 按表取 `_factor_eval_<id>`）。作者改 `LEAVES` 的 `default`；运行时阈值是已写入的 `RECIPE.factor_params`，不写死在叶子里。不存在 `STOP_LOSS` 这类模块全局别名。`above_ema` 无阈值，不要给它写出空 `{}`。

---

## 清单

| id | 文件 | 现逻辑 | 主要读 | 阈值（`factor_params`） |
| :--- | :--- | :--- | :--- | :--- |
| `keltner_vol` | [keltner_vol.py](keltner_vol.py) | 收盘在肯特纳通道内 + 连续缩量 | `kc_mid` / `kc_atr` / 量 | `keltner_vol.k` / `ratio` / `min_ratio` / `vol_n` / `confirm_days`；窗是 `structure.keltner.*`（`k<=0` 或窗 `<=0` 关；`min_ratio<=0` 关下限） |
| `above_ema` | [above_ema.py](above_ema.py) | 收盘 > 日线趋势 EMA | `d_trend` | 无叶子阈值；窗是 `structure.ema.1d.trend`（`<=0` 关闸门） |
| `scale_arm` | [scale_arm.py](scale_arm.py) | 峰值浮盈 + 该笔持仓日 | `state.lots` / peak | `scale_arm.arm` / `bars`；`arm<=0` 回落 `0.03`；`bars<=0` 不查持仓日 |
| `stop_loss` | [stop_loss.py](stop_loss.py) | 收盘相对成本 | `state.lot` / `cost` | `stop_loss.pct` |
| `atr_stop` | [atr_stop.py](atr_stop.py) | 收盘 <= 成本 − k×ATR | `state.lot` / `market.atr` | `atr_stop.k`；窗是 `structure.atr.n`（`<=0` 关） |
| `atr_trail_stop` | [atr_trail_stop.py](atr_trail_stop.py) | 峰值相对成本 > k1×ATR 武装；收盘<=成本或峰值回撤>=k2×ATR | `state.lot` / `hold_peak` / `market.atr` | `atr_trail_stop.k1` / `k2`；`k1<=0` 整条关；`k2<=0` 只保本 |
| `trail_stop` | [trail_stop.py](trail_stop.py) | 阶梯回撤 / 利润底 | `hold_peak` | `trail_stop.tiers`（默认 exit 不引用） |
| `time_force` | [time_force.py](time_force.py) | 持仓日 + 慢线地板 + 武装让路 | `hold_bars` / peak | `time_force.bars` / `time_force.arm`；`arm<=0` 关让路；慢线是 `structure.ema.1d.slow`，调用点直调 `_ema` |

日志 / 成交主因直接用叶子 id（`keltner_vol`、`above_ema`、`atr_stop`、`atr_trail_stop`）。历史 log 里的旧 reason 码由选股/summarize 兼容读取。

不要拆 `keltner_vol` 为 `keltner_inside & vol_shrink`。`above_ema` 无阈值，不要给它写出空 `{}`。

---

## 辅助（不是独立 id）

| 符号 | 写在 | 用途 |
| :--- | :--- | :--- |
| `_trail_tier_params` `_trail_stop_hit` | `trail_stop.py` | 阶梯止盈 |
| `_trail_arm` `_time_force_*` | `time_force.py` | 时间成本让路读 `time_force.arm`；`_trail_arm` 读档 1 `peak_lo`，init 不再调用。启用 `trail_stop` 时 init 由 `_recipe_log_kv` 打 `trail_stop.tiers=` JSON |

---

## 读 / 不读

| 给叶子 | 不给叶子 |
| :--- | :--- |
| 复权 OHLCV、已算均线/ATR/肯特纳、成本、峰值、持仓日、当前 lot | 现金、全池账本、pending、T+1、`passorder` |

`eval` 约定只读。例外：`time_force` 为对齐现行默认配置，命中「武装让路」时仍会写 `time_force_trend_skip`（与旧 `_time_force_hit` 相同）。不要把新的写盘塞进其它叶子。

---

## 加叶子

`catalog.LEAVES` + `lib/<id>.py` + 默认盘要启用时改四个槽位的条件抽象语法树。lib 拼包顺序跟 `LEAVES`；不要手改 `registry` / `MODULE_ORDER` / `grid_spec` 白名单。步骤见 [../NAV.md](../NAV.md)。
