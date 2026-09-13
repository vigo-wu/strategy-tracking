# 日志模式参考（qmt-backtest-report）

面向国金终端策略日志（如 `HlBand` / `STRATEGY_NAME` 前缀）。脚本按下列模式解析；改日志格式时先改 `scripts/generate_report.py`。

## 会话切片

```
{tag} v1.2 init 561580.SH ... PERIOD= 1d BACKTEST= True DRY_RUN= False budget= 50000.0 ...
```

取 **最后一次** `{tag} v… init` 到文件末尾。其前的 `KeyboardInterrupt` / 其它 `.py` 栈忽略。

## 买入块（v1.2+）

```
{tag} BUY by signal=pullback_vol label=买点1-缩量回踩 all=... signal_day=20241031 @open=1.0531
{tag} BUY BUY 561580.SH x47400 ... @ ...
{tag} BUY filled {'shares': 47400, 'price': 1.053..., 'cost': 49915.15, 'opened_at': '20241101000000'}
```

- 开仓日：`opened_at[:8]`
- 信号日：`signal_day`

## 卖出块（v1.2+）

```
{tag} 20241111 ... px=True ...
{tag} SELL by signal=macd_death label=卖点3-MACD死叉 ... signal_day=20241108 @open=1.0922
{tag} SELL macd_death 561580.SH x47400 ... @ ...
{tag} SELL done macd_death last= 1.092... cleared {'shares': 47400, 'price': 1.053...
```

- 执行日：`SELL by signal` **上一行** bar 日期（`{tag} YYYYMMDD`）
- 无 `SELL by signal` 时回退：`{tag} YYYYMMDD` 紧挨 `{tag} SELL {reason} {stock}`

## 诊断计数

| 模式 | 用途 |
| :--- | :--- |
| `buy skip` / `sell skip` | 下单失败 |
| `hold=True` 且同行 `pe=True` | pending_entry 粘滞 |
| `hold=False` 且同行 `px=True` | pending_exit 粘滞 |

## K 线数据源

1. `ak.fund_etf_hist_em`（前复权）
2. 失败 → `ak.fund_etf_hist_sina`

个股若非 ETF，需扩展 `fetch_ohlc`（当前按 ETF 代码拉取）。
