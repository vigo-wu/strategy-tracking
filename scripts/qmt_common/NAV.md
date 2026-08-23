# qmt_common · 国金终端模型共用片段

各策略通过 `_deploy_qmt_gbk.py` 拼接：`common:*` → 本目录，其余 → 策略目录。

**约定**：片段之间不要 `import`；运行时靠拼接顺序定义符号。

**Agent**：新建/修改策略必须遵循 [`.cursor/skills/qmt-common-modules/`](../../.cursor/skills/qmt-common-modules/)；编辑本目录或 `**/scripts/qmt/**` 时 Rule [`.cursor/rules/qmt-common-modules.mdc`](../../.cursor/rules/qmt-common-modules.mdc) 生效。终端参数面板见 [`.cursor/skills/qmt-param-panel/`](../../.cursor/skills/qmt-param-panel/)。

---

## 模块一览（P0 + P1）

| 文件 | 层级 | 作用 |
| :--- | :--- | :--- |
| `ctx.py` | 核心 | 全局 `A`、`_vol_step` / `_lot`、`_strategy_tag`；落盘钩子空实现。`VOL_STEP` 默认 100，转债可设 10 |
| `live_log.py` | P0 | 实盘落盘：`_event_log` / `_bar_log` / `_heartbeat_persist` / `_live_state_snapshot` |
| `time_util.py` | 核心 | `_parse_opened_at`、日历日差 |
| `period.py` | 核心 | 周期解析、OHLC 根数、`end_time` |
| `backtest.py` | P0 | 回测影子仓 T+1（`bt_held` / `bt_locked`）；策略可设 `ALLOW_T0=True` 不锁当日仓 |
| `mode.py` | P0 | 暖机→实盘、`_bar_datetime` |
| `broker_base.py` | P0 | 查资金 / 持仓 / `can_use` |
| `orders_pending.py` | P0 | pending、成交查询、撤单；钩子 `_pending_on_*` |
| `market_util.py` | P1 | `_series_from_ex`、补历史、诊断、心跳 |
| `single/state_io.py` | 单仓 | JSON 仓位读写（按 `A.stock` 分文件） |
| `single/state_pos.py` | 单仓 | `A.position` 辅助 |
| `single/bt_recover.py` | 单仓 | 回测仓恢复 |
| `single/broker.py` | 单仓 | `_max_sell_vol` |
| `single/lots.py` | 单仓 | 同标的多笔 `A.lots`；`SCALE_LOTS` 默认关，开则 `add` 记独立笔、`_order_sell(lot_ids=)` 按笔平 |
| `single/orders.py` | 单仓 | `_order_buy` / `_order_sell` / fill；`add=True` 加仓（默认均价合并，一票一仓） |

红利 T（双浮仓）用 `broker_base` + `orders_pending`，自带 `hongli/broker.py` / `orders.py`。

---

## 策略侧钩子

| 钩子 | 谁实现 | 用途 |
| :--- | :--- | :--- |
| `_pending_on_buy_fill(pend, vol, px)` | 策略 / `single/orders` | pending 买成交落地 |
| `_pending_on_sell_fill(pend, now, vol, px)` | 同上 | pending 卖成交落地 |
| `_reconcile_with_broker()` | 可选（红利 T） | 暖机切实盘对账 |
| `_heartbeat_extra()` | 可选 | 心跳附加信息 |
| `_state_extra_load` / `_state_extra_save` | 可选（均线双周期） | 扩展状态字段 |

实盘日志：`config` 设 `LOG_DIR`（绝对路径，范例 `D:\tradingStrategy\logs`）并拼接 `common:live_log.py`。目录：

```
LOG_DIR/<stock_tag>/
  {STRATEGY_NAME}_events.jsonl
  {STRATEGY_NAME}_bars.jsonl
  {STRATEGY_NAME}_heartbeat.log
  state_snapshots/YYYYMMDD_HHMM.json
```

状态文件范例：`STATE_FILE = r"D:\tradingStrategy\<策略简名>_{stock}.json"`。
`LOG_DIR=""` 关闭落盘；`LOG_IN_BACKTEST=False`（默认）时回测不写盘。

---

## 典型拼接顺序（单仓）

```
config → ctx → live_log → time_util → period → state_io → backtest → state_pos → lots → bt_recover
→ indicators → market_util → market → mode → broker_base → single/broker
→ orders_pending → single/orders → strategy → runtime
```

部署示例：

```bash
python 红利T策略/scripts/qmt/_deploy_qmt_gbk.py
python 波段3-5天策略/scripts/qmt/_deploy_qmt_gbk.py
python 高胜率T1策略/scripts/qmt/_deploy_qmt_gbk.py
python 均线双周期策略/scripts/qmt/_deploy_qmt_gbk.py
```

同标的多仓（不是双浮仓）：单仓模板已含 `single/lots.py`。config `SCALE_LOTS=True` 后，`A.position` 仍是合计，`A.lots` 为各笔；策略只评信号并传 `lot_ids`，不要在策略里再写 fill/T+1。未设该开关时行为与一票一仓相同。

下单数量步长：`VOL_STEP`（默认 100 股）。沪市转债在策略 config 设 `VOL_STEP=10`。
