# hlband/factors/lib · 因子叶子

一 id 一文件。接口：`_factor_eval_<id>(ctx) → (bool, detail)`。  
中性：只回答「条件是否成立」，买/卖/加/减由 [../NAV.md](../NAV.md) 的 Recipe / Intent 赋予。

登记表：[../registry.py](../registry.py)。阈值：[../../config.py](../../config.py) 全局，不写死在叶子里。

---

## 清单

| id | 文件 | 现逻辑 | 主要读 | 阈值（全局） |
| :--- | :--- | :--- | :--- | :--- |
| `pullback_vol` | [pullback_vol.py](pullback_vol.py) | 贴中/慢均线 + 连续缩量 | 日线价量 | `MA_TOUCH_TOL` `VOL_PULLBACK_*` `D_MA_MID` `D_MA_SLOW` |
| `chase` | [chase.py](chase.py) | 当日涨幅过大 | 日线收盘 | `CHASE_MAX_PCT` |
| `vol_dry` | [vol_dry.py](vol_dry.py) | 跌破中线且无量 | 日线价量 | `VOL_DRY_*` `D_MA_MID` |
| `w_bias` | [w_bias.py](w_bias.py) | 周线高位乖离 | `w_detail` | `W_BIAS_HARD` |
| `w_slope` | [w_slope.py](w_slope.py) | 低位生命线未连升 | `w_detail` | `W_BIAS_LOW` `W_MA30_SLOPE_WEEKS` |
| `weekly_bear` | [weekly_bear.py](weekly_bear.py) | **当天空头**（破生命线 / 零轴下死叉） | `w_detail` | `W_MA_LIFE` 等已在周线特征里 |
| `weekly_bear_confirm` | [weekly_bear_confirm.py](weekly_bear_confirm.py) | **确认清仓**：streak ≥ N | `state.w_bear_streak` | `W_BEAR_CONFIRM_DAYS` |
| `plat_break` | [plat_break.py](plat_break.py) | 日线收盘破窄幅平台 | 高低收 | `SCALE_PLAT_*` |
| `w_macd_golden` | [w_macd_golden.py](w_macd_golden.py) | 近两周金叉且红柱放大 | `w_detail` | `SCALE_W_HIST_EXPAND_RATIO` |
| `stop_loss` | [stop_loss.py](stop_loss.py) | 收盘相对成本 | `state.lot` / `cost` | `STOP_LOSS` |
| `trail_stop` | [trail_stop.py](trail_stop.py) | 阶梯回撤 / 利润底 | `hold_peak` | `TRAIL_TIERS` |
| `time_force` | [time_force.py](time_force.py) | 持仓日 + 慢线地板 + 武装让路 | `hold_bars` / peak | `TIME_FORCE_BARS` `D_MA_SLOW` |

叶子 id 用 `chase`；日志码 `chase_skip` 由 `slots` / strategy 映射（`vol_dry`→`vol_dry_skip`，`w_bias`→`w_bias_skip`，`w_slope`→`w_slope_skip`）。确认清仓对外 reason 仍是 `weekly_bear`。

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
| `_trail_arm` `_time_force_*` | `time_force.py` | 时间成本；runtime init 指纹也读 `_trail_arm` |

`_update_w_bear_streak` 在 `strategy.py`，不进 `eval`。

---

## 读 / 不读

| 给叶子 | 不给叶子 |
| :--- | :--- |
| 复权 OHLCV、已算均线/MACD、成本、峰值、持仓日、当前 lot、`w_bear_streak` | 现金、全池账本、pending、T+1、`passorder` |

`eval` 约定只读。例外：`time_force` 为对齐现网，命中「武装让路」时仍会写 `time_force_trend_skip`（与旧 `_time_force_hit` 相同）。不要把新的写盘塞进其它叶子。

---

## 加叶子

`lib/<id>.py` → `_deploy_qmt_gbk.py` 插在 `registry.py` 前 → `registry` 登记 → 需要则改 `RECIPE`。步骤见 [../NAV.md](../NAV.md)。
