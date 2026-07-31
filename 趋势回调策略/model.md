# 趋势回调策略量化信号说明书（日线版）

**主题目录**：`趋势回调策略/`｜**版本**：v1.0｜**运行**：国金 QMT 终端模型（见 §6）

多头环境下，等待价格回调至 20 EMA 附近，经 RSI 与 K 线形态共振确认后尾盘/次日开盘买入；以波段低点止损，布林上轨减仓 + RSI 超买清仓。

---

## 1. 基础参数定义

| 变量名称 | 数据周期 | 计算公式与参数 | 说明 |
| :--- | :--- | :--- | :--- |
| `Close` / `Open` / `High` / `Low` / `Volume` | 日线 | OHLC V | 主图日线 |
| `EMA20` | 日线 | `EMA(Close, 20)` | 回调监控均线 |
| `EMA60` | 日线 | `EMA(Close, 60)` | 大势多头过滤 |
| `EMA60_Slope` | 日线 | `EMA60[t] > EMA60[t-SLOPE_LOOKBACK]` | 默认 `SLOPE_LOOKBACK=3`，斜率朝上 |
| `RSI` | 日线 | `RSI(Close, 14)` Wilder | 超卖 / 背离 / 超买 |
| `BOLL_UP` | 日线 | `MA(Close,20) + 2 * STD(Close,20)` | 减仓参考上轨 |
| `Near_EMA20` | 日线 | `abs(Close/EMA20 - 1) <= 0.01` 或当日触及 | 允许 ±1% 误差 |
| `Swing_Low` | 日线 | 入场前 `SWING_N` 根最低价（默认 8） | 初始止损锚点 |

---

## 2. 买入信号（Buy_Signal == True）

某一根**日线**收盘时，须**同时满足（AND）**下列步骤，则在**当日尾盘（收盘前 5 分钟）**或**次日开盘**触发买入（脚本由 `ENTRY_MODE` 控制，默认尾盘按收盘价成交）。

### 2.1 第一步：筛选大势（多头环境 · 硬性）

1. `Close > EMA60`
2. `EMA60_Slope == True`（60 EMA 朝上，代表大资金流入）

### 2.2 第二步：等待回调（进入监控区）

1. **价格行为**：价格从高位回落，触及或逼近 `EMA20`（`Near_EMA20`，允许上下 1%）
2. **成交量（软条件）**：回调过程中成交量宜逐步萎缩；默认 `VOLUME_SHRINK_REQUIRED=False`，仅诊断打印；若改为 `True` 则硬过滤

### 2.3 第三步：确认转折（RSI 与 K 线共振）

**前置警惕（满足其一即可）**

1. **超卖**：近期 `RSI` 曾降至 **35 以下**（强趋势回调很少锁死 30，35 即可高度警惕）
2. **底背离（胜率更高）**：价格创近期新低，但 `RSI` 在 30 附近止跌回升，形成底背离

**确认信号（须全部满足）**

1. `RSI` 拐头向上并**突破 35**（如 `prev_RSI <= 35` 且 `RSI > 35`，或当根明确上穿）
2. 当日 K 线为下列之一：**看涨吞没**、**锤子线**、**风高浪大线**
3. 当日收盘为**阳线**（`Close > Open`）

#### K 线形态定义（脚本实现）

| 形态 | 判定要点 |
| :--- | :--- |
| 看涨吞没 | 前阴后阳；当日实体完全覆盖前一日实体 |
| 锤子线 | 下影线 ≥ 2×实体；上影线较短；实体位于 K 线上方 |
| 风高浪大线 | 上下影线均较长、实体很小（长脚十字 / 高波纺锤） |

### 2.4 第四步：精确入场

| `ENTRY_MODE` | 行为 |
| :--- | :--- |
| `close`（默认） | 信号日按收盘价买入（对应尾盘） |
| `next_open` | 信号日记标记，次日开盘价买入 |

实盘日线模型：仅在 `14:55`–`15:00` 决策窗评估尾盘信号（`close` 模式）。

---

## 3. 卖出信号（持仓中）

### 3.1 初始止损（全仓）

`Price <= Swing_Low * (1 - 0.01)`  
即近期波段最低点下方 **1%**（防假突破）。

### 3.2 动态止盈（分批）

1. **减仓 50%**：价格触及布林带上轨 `Close >= BOLL_UP`，且尚未减仓过 → 平仓约一半仓位锁定利润  
2. **清仓剩余**：`RSI >= 70`，且出现**滞涨阳线**或**首根阴线** → 清仓其余部分  

| 术语 | 定义 |
| :--- | :--- |
| 滞涨阳线 | 阳线，但涨幅很小或上影线明显、实体推进乏力（脚本：阳线且 `(Close-Open)/Open <= STALL_YANG_MAX` 或上影 ≥ 实体） |
| 首根阴线 | 超买区后第一根阴线（`Close < Open`） |

止损优先于止盈；减仓后剩余仓位仍受止损与清仓规则约束。

---

## 4. Pandas 向量化信号计算逻辑（示意）

```python
import numpy as np

df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
df["ema60"] = df["close"].ewm(span=60, adjust=False).mean()
df["rsi"] = wilder_rsi(df["close"], 14)
df["boll_mid"] = df["close"].rolling(20).mean()
df["boll_up"] = df["boll_mid"] + 2 * df["close"].rolling(20).std()

bull = (df["close"] > df["ema60"]) & (df["ema60"] > df["ema60"].shift(3))
near20 = (df["close"] / df["ema20"] - 1).abs() <= 0.01
rsi_alert = (df["rsi"].rolling(5).min() <= 35) | bullish_rsi_divergence(df)
rsi_cross = (df["rsi"].shift(1) <= 35) & (df["rsi"] > 35)
yang = df["close"] > df["open"]
pattern = is_bullish_engulfing(df) | is_hammer(df) | is_high_wave(df)

df["Buy_Signal"] = np.where(bull & near20 & rsi_alert & rsi_cross & pattern & yang, 1, 0)
```

持仓侧止损 / 布林减仓 / RSI 清仓在 QMT 脚本中按持仓状态逐 bar 判断。

---

## 5. 参数一览（与脚本对齐）

| 配置项 | 默认 | 说明 |
| :--- | :--- | :--- |
| `EMA_FAST` / `EMA_SLOW` | `20` / `60` | 回调线 / 大势线 |
| `EMA_SLOPE_LOOKBACK` | `3` | 60 EMA 斜率回看 |
| `EMA20_TOL` | `0.01` | 逼近 20 EMA 容差 |
| `RSI_N` | `14` | RSI 周期 |
| `RSI_ALERT` | `35` | 超卖警惕 / 上穿确认 |
| `RSI_DIVERGE_FLOOR` | `30` | 背离关注区参考 |
| `RSI_OVERBUY` | `70` | 清仓超买线 |
| `BOLL_N` / `BOLL_K` | `20` / `2.0` | 布林参数 |
| `SWING_N` | `8` | 止损波段低点回看 |
| `STOP_BELOW` | `0.01` | 低点下方 1% |
| `ENTRY_MODE` | `close` | `close` / `next_open` |
| `VOLUME_SHRINK_REQUIRED` | `False` | 缩量是否硬过滤 |
| `TRADE_BUDGET` | 单标的 `50000` / 池版 `10000` | 单笔买入预算（元） |
| `MAX_HOLDINGS` | 池版 `10` | 同时持仓上限（仅 basket） |
| `DRY_RUN` | `True`（池版默认） | 只打印不报单 |

---

## 6. QMT 运行（国金终端模型交易）

### 6.1 单标的

**脚本**：[`scripts/qmt/qmt_terminal_trend_pb.py`](./scripts/qmt/qmt_terminal_trend_pb.py)  
**部署**：[`scripts/qmt/_deploy_qmt_gbk.py`](./scripts/qmt/_deploy_qmt_gbk.py) → `TrendPB.py` / `趋势回调.py`

主图打开**目标股票**日线 → 加载 `TrendPB`。

### 6.2 中证央企红利池（~50 只）

**脚本**：[`scripts/qmt/qmt_terminal_trend_pb_basket.py`](./scripts/qmt/qmt_terminal_trend_pb_basket.py)  
**部署**：[`scripts/qmt/_deploy_qmt_gbk_basket.py`](./scripts/qmt/_deploy_qmt_gbk_basket.py) → `TrendPBBasket.py` / `趋势回调池.py`

| 配置项 | 默认 | 说明 |
| :--- | :--- | :--- |
| `POOL_INDEX` | `000825.SH` | 中证中央企业红利；`get_sector` 取成分 |
| `TRADE_BUDGET` | `10000` | 单笔预算 |
| `MAX_HOLDINGS` | `10` | 同时最多持仓只数 |
| `STATE_FILE` | `...\python\trend_pb_basket_qmt_state.json` | 按标的分 books |

```bash
python 趋势回调策略/scripts/qmt/_deploy_qmt_gbk_basket.py
```

**操作步骤（池版）**

1. 打开国金 QMT，登录交易账号  
2. 主图打开 **`000825.SH`**，周期 **日线**（数据管理中确保指数成分/板块已下载）  
3. 【模型交易】→ `TrendPBBasket` / `趋势回调池` → 选账号 → 先回测/`DRY_RUN`  
4. 日志确认：`TrendPBBasket v1.0-basket init`、`pool= ~50`、`diag: ok batch`  
5. 确认后再改 `DRY_RUN=False` 并重新部署编译  
6. 遵守 T+1；满仓后日志 `buy skip: max holdings` 属正常  

取池失败时可在脚本填 `POOL_FALLBACK = ["600028.SH", ...]`。回测 50 只会明显变慢，属预期。

### 6.3 下单约定（两版相同，对齐 pitfalls §7.1）

- `DRY_RUN`：不下单，日历日 T+1 模拟  
- 回测：`passorder` 后即时落状态；可卖 = `bt_held - bt_locked`；`sell skip` 不清仓  
- 实盘：`passorder` 后进 `pending`，**成交后**才改仓；可卖 = `m_nCanUseVolume`  
- 减仓 50% 按整手向下取整；剩余不足 100 股则一次清仓  

编码由部署脚本写成 **GBK**。请只编辑仓库内 UTF-8 源文件；勿直接打开国金 `python\` 下 GBK 文件。

---

*提示：改参数后务必重新部署并在 QMT 内重新编译。*
