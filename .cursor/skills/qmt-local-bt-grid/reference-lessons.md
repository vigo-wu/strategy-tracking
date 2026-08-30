# MAE 反事实 vs 真实 local_bt

固定买入路径的反事实（`stop_loss_mae.py` / `trail_tiers_mae.py` / `time_force_mae.py`）**不能**当作选参结论。本文件记下 hongli_band 本轮对照，Agent 需要解释「为什么必须实跑」时再读。

口径：主样本 = 冻结的每年均线 winner（约 40 只 × 年）；预算 10 万/账户/年；IS=2018–2022，OOS=2023–2026。

## 收紧 vs 放宽

| 方向 | 反事实在做什么 | 可信度 |
| :--- | :--- | :--- |
| **收紧**（原持仓期内提前平） | 同一买入，更早触及新阈值 | 较可信，仍可能因路径依赖小于 MAE 幅度 |
| **放宽 / 关闭**（延长原出场） | 假设原卖点之后仍拿着同一笔仓 | 高估；路径会变（加仓、其它卖点、下一笔买入），甚至把符号估反 |

## 本轮数字（hongli_band）

### STOP_LOSS

现行 8%。MAE 偏向 10%。真实重跑 10% 仍好于 8%，但改善小于 MAE（路径依赖：提前/延后平仓会改后续开仓）。

### TRAIL_TIERS 起步

现行档 1 起步 3%。MAE 选起步 4%（`arm_later`）：winner **+14.4 万**。
真实重跑起步 4%：winner **−3.9 万**，OOS **−1.05 万**。符号与 MAE 相反。已回到 3%。

TRAIL 当时不进 init 行，只能靠反事实猜口径。网格扫 TRAIL 必须看 `trail_arm=`（档 1 的 `peak_lo`）。

### TIME_FORCE

MAE：关掉整条规则（`TIME_FORCE_BARS<=0`）约 **+3.4 万**。
真实重跑：winner 合计约 **+0.63 万**，**OOS 为负**。MAE 高估且样本外符号翻了。

`MIN_RET=0` 不是关闭 time_force，只关掉「峰值已武装则让路」。关闭整条规则只能 `TIME_FORCE_BARS<=0`。

## 均线 winner

每格若按该格自己的盈亏重选 SMA/EMA，会把「选均线」混进「选阈值」。网格必须冻结基线 `local_bt_ma_compare.csv` 的 winner 名单，其它格子同一组 stock/year/MA。

全 SMA / 全 EMA 只做对照，不参与冻结名单，也不单独当选参器。

## Agent 禁令

- 推荐句里不要引用 MAE 的 Δ。
- 不要把 `stop_loss_mae.py` 等脚本的最优格写进 `summary.json` 的 `recommend`。
- 放宽/关闭格子即使用户催「按 MAE 改 config」，也要先跑完本 Skill 的实跑网格。
