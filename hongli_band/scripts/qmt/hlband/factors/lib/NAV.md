# hlband/factors/lib · 因子叶子

一 id 一文件。接口：`_factor_eval_<id>(ctx) → (bool, detail)`。  
中性：只回答「条件是否成立」，买/卖/加/减由 [../NAV.md](../NAV.md) 的 Recipe / Intent 赋予。

登记表：[../catalog.py](../catalog.py) 的 `LEAVES`（`registry` 按表取 `_factor_eval_<id>`）。作者改 `LEAVES` 的 `default`；运行时阈值是已写入的 `RECIPE.factor_params`，不写死在叶子里。不存在 `STOP_LOSS` 这类模块全局别名。`weekly_bear` 无阈值，不要给它写出空 `{}`。

---

## 清单

| id | 文件 | 现逻辑 | 主要读 | 阈值（`factor_params`） |
| :--- | :--- | :--- | :--- | :--- |
| `pullback_vol` | [pullback_vol.py](pullback_vol.py) | 贴中/慢均线 + 连续缩量 | 日线价量 | `pullback_vol.*`；中/慢线周期是 `structure.d_ma.*` |
| `chase` | [chase.py](chase.py) | 当日涨幅过大 | 日线收盘 | `chase.max_pct` |
| `vol_dry` | [vol_dry.py](vol_dry.py) | 跌破中线且无量 | 日线价量 | `vol_dry.ratio` / `n`；中线周期是 `structure.d_ma.mid` |
| `w_bias` | [w_bias.py](w_bias.py) | 周线高位乖离 | `w_detail` | `w_bias.hard` |
| `w_slope` | [w_slope.py](w_slope.py) | 低位生命线未连升 | `w_detail` | `w_slope.low` / `slope_weeks` |
| `weekly_bear` | [weekly_bear.py](weekly_bear.py) | **当天空头**（破生命线 / 零轴下死叉） | `w_detail` | 无叶子阈值；周期在 `RECIPE.structure` |
| `weekly_bear_confirm` | [weekly_bear_confirm.py](weekly_bear_confirm.py) | **确认清仓**：streak ≥ N | `state.w_bear_streak` | `weekly_bear_confirm.days` |
| `plat_break` | [plat_break.py](plat_break.py) | 日线收盘破窄幅平台 | 高低收 | `plat_break.lookback` / `max_range` / `break_buf` |
| `w_macd_golden` | [w_macd_golden.py](w_macd_golden.py) | 近两周金叉且红柱放大 | `w_detail` | `w_macd_golden.hist_expand` |
| `stop_loss` | [stop_loss.py](stop_loss.py) | 收盘相对成本 | `state.lot` / `cost` | `stop_loss.pct` |
| `atr_stop` | [atr_stop.py](atr_stop.py) | 收盘 <= 成本 − k×ATR | `state.lot` / `market.atr` | `atr_stop.k`；窗是 `structure.atr.n`（`<=0` 关） |
| `atr_trail_stop` | [atr_trail_stop.py](atr_trail_stop.py) | 峰值相对成本 > k1×ATR 武装；收盘<=成本或峰值回撤>=k2×ATR | `state.lot` / `hold_peak` / `market.atr` | `atr_trail_stop.k1` / `k2`；`k1<=0` 整条关；`k2<=0` 只保本 |
| `trail_stop` | [trail_stop.py](trail_stop.py) | 阶梯回撤 / 利润底 | `hold_peak` | `trail_stop.tiers`（默认 exit 不引用） |
| `time_force` | [time_force.py](time_force.py) | 持仓日 + 慢线地板 + 武装让路 | `hold_bars` / peak | `time_force.bars` / `time_force.arm`；`arm<=0` 关让路；慢线是 `structure.d_ma.slow` |

日志 / 成交主因直接用叶子 id（`chase`、`vol_dry`、`w_bias`、`w_slope`、`weekly_bear_confirm`）。当天空头禁开仍是 `weekly_bear`。历史 log 里的 `*_skip` / 清仓 `weekly_bear` 由选股/summarize 兼容读取。

不要拆 `pullback_vol` 为 `near_ma & vol_shrink`（现网复合原子）。`weekly_bull` 不是因子。

---

## 辅助（不是独立 id）

| 符号 | 写在 | 用途 |
| :--- | :--- | :--- |
| `_near_ma` | `pullback_vol.py` | 价距均线容差 |
| `_plat_window` | `plat_break.py` | 回看窗口高低点 |
| `_vol_pullback_confirm_need` | [../ctx.py](../ctx.py) | 缩量确认日（ctx 预计算要用，故不放本目录） |
| `_w_bear_confirm_need` | `weekly_bear_confirm.py` | 空头确认日数；strategy 的 streak 更新也用它 |
| `_trail_tier_params` `_trail_stop_hit` | `trail_stop.py` | 阶梯止盈 |
| `_trail_arm` `_time_force_*` | `time_force.py` | 时间成本让路读 `time_force.arm`；`_trail_arm` 只给 init `trail_arm=` |

`_update_w_bear_streak` 在 `strategy.py`，不进 `eval`。

---

## 读 / 不读

| 给叶子 | 不给叶子 |
| :--- | :--- |
| 复权 OHLCV、已算均线/MACD/ATR、成本、峰值、持仓日、当前 lot、`w_bear_streak` | 现金、全池账本、pending、T+1、`passorder` |

`eval` 约定只读。例外：`time_force` 为对齐现网，命中「武装让路」时仍会写 `time_force_trend_skip`（与旧 `_time_force_hit` 相同）。不要把新的写盘塞进其它叶子。

---

## 加叶子

`catalog.LEAVES` + `lib/<id>.py` + 默认盘要启用时改四槽 AST。lib 拼包顺序跟 `LEAVES`；不要手改 `registry` / `MODULE_ORDER` / `grid_spec` 白名单。步骤见 [../NAV.md](../NAV.md)。
