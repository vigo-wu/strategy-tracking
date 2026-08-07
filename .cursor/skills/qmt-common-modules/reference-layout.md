# 布局与 MODULE_ORDER 模板

片段命名（`_deploy_lib.resolve_fragment`）：

| 写法 | 解析到 |
| :--- | :--- |
| `foo.py` | `<策略目录>/foo.py` |
| `common:bar.py` | `scripts/qmt_common/bar.py` |
| `common:single/x.py` | `scripts/qmt_common/single/x.py` |

目录约定：

```text
<主题>/
  model.md
  scripts/qmt/
    _deploy_qmt_gbk.py          # MODULE_ORDER + TARGETS
    qmt_terminal_<简名>.py      # AUTO 预览，勿手改
    <简名>/                     # 策略片段（UTF-8）
      config.py
      indicators.py
      market.py
      strategy.py
      runtime.py
      ...
scripts/qmt_common/             # 共用片段
  _deploy_lib.py
  NAV.md
  ...
```

---

## 单仓 MODULE_ORDER（复制后改策略目录名）

```python
MODULE_ORDER = [
    "config.py",
    "common:ctx.py",
    "common:live_log.py",  # 可选；需 config.LOG_DIR
    "common:time_util.py",
    "common:period.py",
    # 可选: "state_extra.py",   # 须在 state_io 之前定义钩子亦可；运行时查找
    "common:single/state_io.py",
    "common:backtest.py",
    "common:single/state_pos.py",
    "common:single/bt_recover.py",
    # 可选: "helpers.py",
    "indicators.py",
    "common:market_util.py",
    "market.py",
    "common:mode.py",
    "common:broker_base.py",
    "common:single/broker.py",
    "common:orders_pending.py",
    "common:single/orders.py",
    "strategy.py",
    "runtime.py",
]
```

范本：`波段3-5天策略/scripts/qmt/_deploy_qmt_gbk.py`。

扩展状态字段（如 `pending_entry`）时增加：

```python
def _state_extra_load(raw): ...
def _state_extra_save(data): ...
```

---

## 双浮仓 MODULE_ORDER

```python
MODULE_ORDER = [
    "_header.py",
    "config.py",
    "common:ctx.py",
    "common:time_util.py",
    "common:period.py",
    "state_io.py",
    "common:backtest.py",
    "state.py",
    "bt_recover.py",
    "indicators.py",
    "common:market_util.py",
    "market.py",
    "common:mode.py",
    "common:broker_base.py",
    "broker.py",                 # 本地: 底仓 / _max_sell_vol / reconcile
    "common:orders_pending.py",
    "orders.py",                 # 本地: _order_* + _pending_on_*
    "runtime.py",
    "strategy.py",
    "_main_guard.py",
]
```

范本：`红利T策略/scripts/qmt/_deploy_qmt_gbk.py`。

---

## deploy 脚本骨架

```python
# coding: utf-8
from __future__ import annotations
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STRAT = HERE / "<简名>"
PREVIEW = HERE / "qmt_terminal_<简名>.py"
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from qmt_common._deploy_lib import build_bundle, deploy_gbk, write_preview

QMT_DIR = Path(r"D:\service\GJQMT") / "python"
TARGETS = [QMT_DIR / "<入口名>.py"]
MODULE_ORDER = [ ... ]  # 上表

def main() -> None:
    text = build_bundle(MODULE_ORDER, STRAT)
    write_preview(text, PREVIEW)
    deploy_gbk(text, TARGETS, compile_name=PREVIEW.name)

if __name__ == "__main__":
    main()
```

`REPO = HERE.parents[2]`：`<主题>/scripts/qmt` → 仓库根。若目录深度不同需改。

---

## config 最小字段

```python
DRY_RUN = True
STRATEGY_NAME = "Foo"
STRATEGY_VER = "v1.0"
ACCOUNT_ID = "..."
ACCOUNT_TYPE = "STOCK"
TRADE_BUDGET = 50000.0          # 单仓；双浮仓用 FLOAT_*_BUDGET
PERIOD = "15m"                  # 或 "follow"
OHLC_COUNT = 480
# 绝对路径；多实例不同主图时用 {stock}（或基名由 single/state_io 自动加 _代码_市场 后缀）
STATE_FILE = r"D:\tradingStrategy\foo_{stock}.json"
# 实盘结构化日志根目录；空字符串关闭。落盘: LOG_DIR/<stock>/{tag}_*.jsonl
LOG_DIR = r"D:\tradingStrategy\logs"
LOG_IN_BACKTEST = False
PENDING_TIMEOUT_SEC = 180
PENDING_ORPHAN_SEC = 60
LIVE_HEARTBEAT_SEC = 60
HIST_MAX_LOOKBACK_DAYS = 360
DOWNLOAD_HIST_LIVE = False
DOWNLOAD_HIST_BACKTEST = True
_ORDER_FILLED = (56, 8)
_ORDER_DEAD = (54, 57, 53, 5, 6, 9)
_VALID_PERIODS = ("1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mon", "1q", "1hy", "1y")
```

---

## 钩子一览

| 钩子 | 何时需要 |
| :--- | :--- |
| `_pending_on_buy_fill` / `_pending_on_sell_fill` | 双浮仓必写；单仓由 `single/orders` 提供 |
| `_reconcile_with_broker` | 暖机→实盘对账（红利 T） |
| `_heartbeat_extra` | 心跳附加仓位摘要 |
| `_state_extra_load` / `_state_extra_save` | JSON 扩展字段 |
| `_buy_budget` | 单仓已有；可用 `CASH_RATIO` |

---

## runtime 要点

```python
def handlebar(C):
    try:
        _refresh_mode(C)   # 勿只用 _is_backtest(C)，否则暖机陷阱
        ...
        _handle(C)
    finally:
        A.busy = False
```

```python
A.period = _resolve_period(C, default="15m")  # 与主图默认一致
```

---

## 策略侧应写 / 不应写

**应写**：信号、指标组合、策略特有行情组装、仓位语义（单仓以外）、`config`。

**不应写**：`passorder` 封装、pending 状态机、T+1 影子仓、`get_market_data_ex` 解析、暖机模式切换、资金/可卖查询（除非双浮仓扩展 `_max_sell_vol`）。
