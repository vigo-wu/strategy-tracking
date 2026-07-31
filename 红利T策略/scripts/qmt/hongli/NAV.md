# HongliT 片段快速导航

编辑本目录后部署：

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
| 下单 / pending / 成交回填 | [`orders.py`](./orders.py) |
| 可卖 / 底仓 / 对账 | [`broker.py`](./broker.py) |
| OHLC / 日线 MA | [`market.py`](./market.py) |
| BOLL + KDJ | [`indicators.py`](./indicators.py) |
| 回测 T+1 影子仓 | [`backtest.py`](./backtest.py) |
| 浮仓腿 / 冷却 / 时段门 | [`state.py`](./state.py) |
| 状态 JSON 读写 | [`state_io.py`](./state_io.py) |
| 暖机→实盘 / K 线时间 | [`mode.py`](./mode.py) |
| 周期解析 | [`period.py`](./period.py) |
| 心跳 / 下载历史 / 行情解析 | [`market_util.py`](./market_util.py) |
| 全局 `A` 对象 | [`ctx.py`](./ctx.py) |
| 策略总说明 | [`_header.py`](./_header.py) |
| simpleRun 秒退提示 | [`_main_guard.py`](./_main_guard.py) |

---

## 拼接顺序（MODULE_ORDER）

| # | 文件 | 作用 |
| ---: | :--- | :--- |
| 1 | [`_header.py`](./_header.py) | 策略总览注释（规则 / 风控 / 实盘与回测约定） |
| 2 | [`config.py`](./config.py) | 用户参数与周期/委托常量 |
| 3 | [`ctx.py`](./ctx.py) | 全局运行时对象 `A`、手数 `_lot` |
| 4 | [`period.py`](./period.py) | 周期归一化、OHLC 根数、end_time |
| 5 | [`state_io.py`](./state_io.py) | 浮仓状态 JSON 加载/保存 |
| 6 | [`backtest.py`](./backtest.py) | 回测影子持仓与 T+1 锁定 |
| 7 | [`state.py`](./state.py) | 浮仓腿、风控门闩、冷却、缩仓 |
| 8 | [`indicators.py`](./indicators.py) | 布林带 + KDJ(J) |
| 9 | [`market_util.py`](./market_util.py) | 诊断、序列解析、补历史、心跳 |
| 10 | [`market.py`](./market.py) | 拉收盘/OHLC、日线均线过滤 |
| 11 | [`mode.py`](./mode.py) | 回测/实盘判定、暖机切换、K 线时间 |
| 12 | [`broker.py`](./broker.py) | 资金、持仓可卖、底仓、对账 |
| 13 | [`orders.py`](./orders.py) | pending、买卖委托、成交落地 |
| 14 | [`runtime.py`](./runtime.py) | `init` / `handlebar` |
| 15 | [`strategy.py`](./strategy.py) | `_handle`：信号与下单决策 |
| 16 | [`_main_guard.py`](./_main_guard.py) | 阻止 simpleRun/doRun 独立启动 |

---

## 调用链（读代码时可顺着走）

```
init / handlebar          (runtime.py)
  └─ _refresh_mode        (mode.py)
  └─ _handle              (strategy.py)
       ├─ _process_pending / _order_*   (orders.py)
       ├─ _get_ohlc / _daily_ma_ok      (market.py)
       ├─ _calc_indicators              (indicators.py)
       ├─ 风控门闩 / 浮仓                 (state.py)
       └─ _max_sell_vol / 对账           (broker.py)
```
