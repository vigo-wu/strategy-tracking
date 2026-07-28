# xtquant / MiniQMT 要点（转写时必遵）

来源：[完整实例](https://dict.thinktrader.net/nativeApi/code_examples.html)。细节以官网为准；此处只留转写时易错点。

## 行情（xtdata）

- 历史数据先 `download_history_data(code, period=..., incrementally=True)`，再 `get_market_data_ex`。  
- 盘中实时：先 `subscribe_quote`，再取数；回调里也可再 `get_market_data_ex`。  
- 用回调时需阻塞：`xtdata.run()` **或** 交易侧 `xt_trader.run_forever()`（二选一主循环即可）。  
- 日线做决策时：订阅 `1m` 触发评估，用日线算指标，并用 `get_full_tick` 的 `lastPrice` 修正当日 close/high/low。

## 交易（XtQuantTrader）

```text
path + session_id → XtQuantTrader
register_callback → start → connect(0=成功)
StockAccount(账号, 'STOCK'|'CREDIT'|'FUTURE')
subscribe(acc)
order_stock_async(...)
run_forever()
```

| 项 | 约定 |
| :--- | :--- |
| path | 券商：`userdata_mini`；投研：`userdata` |
| session_id | `int(time.time())`；同机并行策略勿重复 |
| 买入量 | 100 股整数倍；金额定额 → 整手下取整 |
| 卖出量 | `min(目标, m_nCanUseVolume)` |
| 报价 | 买可用 `FIX_PRICE`+最新价；卖可用 `LATEST_PRICE, -1` |
| 备注 | `strategy_name` + `order_remark`（如 `RA`/`RB`/`R高抛`）便于回调排查 |

## 回调类最少实现

`on_disconnected` / `on_stock_order` / `on_stock_trade` / `on_order_error` /  
`on_order_stock_async_response` / `on_cancel_error` / `on_account_status`

## 查询

- 资金：`query_stock_asset(acc)` → `m_dCash`  
- 持仓：`query_stock_positions(acc)` → `stock_code`, `m_nVolume`, `m_nCanUseVolume`

## 禁忌

- 连接失败时不要 `while True` 狂重连（每次 session 占对接文件，易撑满磁盘）。  
- 未确认逻辑前不要注册全推并自动下单。  
- 脚本内写死真实资金账号提交到公开仓库前，应保持占位符。  
- 官方声明：示例仅供写法参考，实盘自负风险——脚本头注释保留 `DRY_RUN` 警告。
