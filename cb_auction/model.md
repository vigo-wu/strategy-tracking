# 可转债上市首日开盘/收盘竞价策略

**主题目录**：`cb_auction/`｜**版本**：v1.0｜**运行**：国金 QMT 终端模型（见 §4）

定稿依据：`convertible-bond-strategy/reports/2026年可转债上市首日开盘收盘竞价收入策略.md`

---

## 一、核心规则

| 环节 | 规则 | 脚本行为 |
| :--- | :--- | :--- |
| 开盘竞价买 | **9:15** 起以 **130.00** 限价挂买 | `passorder` prType=11，自动 |
| 收盘卖 ≤5 亿 | 建议挂 **157.30** | **仅日志提示，不下单** |
| 收盘卖 >5 亿 | 建议挂**可确认收盘价**（用最新价近似） | **仅日志提示，不下单** |
| 卖出 | 一律手动 | 实盘永不 `passorder` 卖出 |

回测专用：`BACKTEST_SIM_SELL=True` 时在 14:57～15:00 按提示价模拟卖出（可转债按 T+0 解锁），便于看开→收盈亏；**实盘忽略该开关**。

---

## 二、配置要点（`cbauct/config.py`）

| 配置 | 默认 | 说明 |
| :--- | :--- | :--- |
| `DRY_RUN` | `True` | 默认不下真实单 |
| `TRADE_BUDGET` | `50000` | 单笔买入资金上限 |
| `LOT_SIZE` | `10` | 可转债一手张数 |
| `OPEN_BUY_PRICE` | `130.0` | 开盘竞价买入价 |
| `LIMIT_UP_PRICE` | `157.30` | 小盘收盘顶格参考价 |
| `SMALL_SIZE_YI` | `5.0` | ≤ 此值（亿）走顶格卖提示 |
| `ISSUE_SIZE_MAP` | 2026 样本 | 键=`代码.市场`；未知时看 `ISSUE_SIZE_YI` |
| `BUY_START` / `BUY_END` | `091500` / `092500` | 开盘挂单窗 |
| `SELL_HINT_START` / `END` | `145700` / `150000` | 手动卖提示窗 |
| `PERIOD` | `1m` | 建议 1 分钟主图 |
| `STATE_FILE` | `...\cbauct_{stock}.json` | 按标的分文件 |

新券上市前：把规模写入 `ISSUE_SIZE_MAP`，或临时设 `ISSUE_SIZE_YI`。

---

## 三、执行流程

```
上市日主图挂该转债（1 分钟）
  │
  ├─ 9:15～9:25  限价 130 买入（每日一次；未成交不追）
  ├─ 临停等待
  └─ 14:57～15:00  打印 MANUAL_SELL hint → 交易者手动挂卖
```

日志关键字：

- `OPEN_AUCTION buy @130.00`
- `MANUAL_SELL hint mode=小盘顶格|可确认收盘价 price=...`
- `[BT-SIM] ... SELL`（仅回测模拟）

---

## 四、QMT 运行

**部署**：

```bash
python cb_auction/scripts/qmt/_deploy_qmt_gbk.py
```

写入：`D:\service\GJQMT\python\CbAuct.py` 与 `转债首日竞价.py`  
预览：`cb_auction/scripts/qmt/qmt_terminal_cbauct.py`（勿手改）

| 步骤 | 操作 |
| :--- | :--- |
| 1 | 模型交易 → 加载 `CbAuct` / `转债首日竞价` |
| 2 | 主图 = 当日上市可转债；周期 **1 分钟**；复权 **不复权** |
| 3 | 确认 `ACCOUNT_ID`；先 `DRY_RUN=True` 看 `diag: ok` / 开盘买日志 |
| 4 | 实盘改 `DRY_RUN=False` 后 re-deploy；收盘按提示**手动卖出** |
| 5 | 多标的并行：每个主图单独实例（STATE 含 `{stock}`） |

**只改** `cb_auction/scripts/qmt/cbauct/*.py` 后重新 deploy；禁止手改 GBK 产物。

---

## 五、风险与边界

- 开盘未成交：当日不再追买。  
- 规模未知：不按小盘顶格提示，走「可确认收盘价」。  
- 顶格卖可能排队不成交 → 手动处理残留仓。  
- 历史开→收约 +17% 为样本统计，非实盘保证。  
