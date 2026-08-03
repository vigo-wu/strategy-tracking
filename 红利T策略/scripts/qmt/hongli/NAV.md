# HongliT 片段快速导航

编辑本目录或 `scripts/qmt_common/` 后部署：

```bash
python scripts/qmt/_deploy_qmt_gbk.py
```

拼接产物预览：[`../qmt_terminal_hongli_t.py`](../qmt_terminal_hongli_t.py)（AUTO-GENERATED，勿手改）

约定：片段之间**不要互相 import**；部署按下方顺序拼成单个 GBK 文件。

---

## 按改什么找哪里

| 我想改… | 打开 |
| :--- | :--- |
| `DRY_RUN` / 预算 / 风控开关 / 决策窗 | [`config.py`](./config.py) |
| R-A / R-B / R-Sell / 止损 / MaxHold 逻辑 | [`strategy.py`](./strategy.py) |
| `init` / `handlebar` 入口 | [`runtime.py`](./runtime.py) |
| 双浮仓买卖 / fill | [`orders.py`](./orders.py) |
| 底仓隔离 / 对账 | [`broker.py`](./broker.py) |
| OHLC / 日线 MA | [`market.py`](./market.py) |
| BOLL + KDJ | [`indicators.py`](./indicators.py) |
| 浮仓腿 / 冷却 / 时段门 | [`state.py`](./state.py) |
| 状态 JSON 读写 | [`state_io.py`](./state_io.py) |
| 回测浮仓恢复 | [`bt_recover.py`](./bt_recover.py) |
| **共用** ctx/period/mode/T+1/pending/行情工具 | [`scripts/qmt_common/`](../../../../scripts/qmt_common/) |

---

## 拼接顺序（MODULE_ORDER）

| # | 片段 | 作用 |
| ---: | :--- | :--- |
| 1 | `_header.py` | 策略总览注释 |
| 2 | `config.py` | 用户参数 |
| 3–5 | `common:ctx/time_util/period` | 运行时骨架 |
| 6 | `state_io.py` | 浮仓 JSON |
| 7 | `common:backtest` | T+1 影子仓 |
| 8–9 | `state.py` + `bt_recover.py` | 浮仓语义 / 恢复 |
| 10 | `indicators.py` | BOLL+KDJ |
| 11–12 | `common:market_util` + `market.py` | 行情 |
| 13 | `common:mode` | 暖机/实盘 |
| 14–15 | `common:broker_base` + `broker.py` | 经纪 |
| 16–17 | `common:orders_pending` + `orders.py` | 下单 |
| 18–19 | `runtime.py` + `strategy.py` | 入口与信号 |
| 20 | `_main_guard.py` | 阻止 simpleRun |

详见 [`scripts/qmt_common/NAV.md`](../../../../scripts/qmt_common/NAV.md)。
