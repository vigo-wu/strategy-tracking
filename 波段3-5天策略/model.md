# 3-5天股票波段策略量化信号说明书 (15M 周期版)

**主题目录**：`波段3-5天策略/`｜**版本**：v1.3｜**运行**：国金 QMT 终端模型（见 §5）

## 1. 基础参数定义

| 变量名称 | 数据周期 | 计算公式与参数 | 说明 |
| :--- | :--- | :--- | :--- |
| `Price` | 15分钟线 | 当前 15M K线收盘价 `Close` | 核心执行价格与出场依据 |
| `MA5_Daily` | 日线 | `MA(Close, 5)` | 日线5日均线（跨周期导入 15M 图表） |
| `MA10_Daily` | 日线 | `MA(Close, 10)` | 日线10日均线（跨周期导入 15M 图表） |
| `K` | 15分钟线 | `KDJ(9, 3, 3)` 中的 K 值 | 极灵敏的超短线动量分子 |
| `D` | 15分钟线 | `KDJ(9, 3, 3)` 中的 D 值 | 极灵敏的超短线动量分母 |

---

## 2. 买入信号（Buy_Signal == True）

当某一根 **15分钟K线** 结束时，必须**同时满足（AND）**以下所有条件，则在当前 15M Bar 结束前 1 分钟或下一根 Bar 开盘时触发买入：

1. **趋势过滤**：`Price > MA10_Daily` *(确保日线级别大趋势安全)*
2. **超卖区间**：`K < 20` 且 `D < 20` *(15M 级别波动大，超卖阈值由 25 降低至 20 以防假信号)*
3. **动量金叉**：`K > D` 且 `前一根 15M K线的K值 <= 前一根 15M K线的D值`
4. **时间过滤**：`14:30 <= K线时间 < 15:00` *(严格限制在尾盘最后半小时，利用日内情绪尘埃落定的低点买入)*

---

## 3. 卖出信号（Sell_Signal == True）

持仓状态下，当 **15分钟K线** 满足以下**任意一个（OR）**条件时，立即执行全仓市价卖出：

1. **技术超买死叉**：`K > 85` 且 `K < D` 且 `前一根 15M K线的K值 >= 前一根 15M K线的D值` *(高位超买死叉，快速落袋)*
2. **硬性追踪止损**：`Price <= 买入成本价 * 0.96` *(15M 级别可能遭遇日内急跌，亏损达 4% 严格斩仓)*
3. **趋势破位止损**：`当前 15M 收盘价 < MA10_Daily * 0.99` *(15M 级别跌破日线10日线超过 1%，判定波段失效)*
4. **单期目标止盈**：`Price >= 买入成本价 * 1.12` *(波段利润达 12% 触发主动止盈)*
5. **时间强制出局**：`当前交易日 - 买入交易日 >= 4` *(持仓满 4 个交易日，强制腾出资金成本)*

---

## 4. Pandas 向量化信号计算逻辑

```python
import numpy as np

# 1. 衍生变量计算 (基于 15M 频率的 DataFrame)
df_15m['prev_K'] = df_15m['K'].shift(1)
df_15m['prev_D'] = df_15m['D'].shift(1)

# 提取时间用于过滤 (格式如 '14:30')
df_15m['time_str'] = df_15m.index.strftime('%H:%M')

# 2. 计算买入信号矩阵 (1为买入，0为无信号)
buy_cond = (
    (df_15m['close'] > df_15m['MA10_Daily']) & 
    (df_15m['K'] < 20) & 
    (df_15m['D'] < 20) & 
    (df_15m['K'] > df_15m['D']) & 
    (df_15m['prev_K'] <= df_15m['prev_D']) & 
    (df_15m['time_str'] >= '14:30') & 
    (df_15m['time_str'] < '15:00')
)
df_15m['Buy_Signal'] = np.where(buy_cond, 1, 0)

# 3. 计算技术面卖出信号矩阵 (1为卖出，0为无信号)
sell_cond = (
    (df_15m['K'] > 85) & 
    (df_15m['K'] < df_15m['D']) & 
    (df_15m['prev_K'] >= df_15m['prev_D'])
)
df_15m['Tech_Sell_Signal'] = np.where(sell_cond, 1, 0)
```

持仓侧止损 / 止盈 / 日线破位 / 满 4 日强平在 QMT 脚本中按持仓状态逐 bar 判断（非纯向量矩阵）。

---

## 5. QMT 运行（国金终端模型交易）

**脚本**：[`scripts/qmt/qmt_terminal_band35.py`](./scripts/qmt/qmt_terminal_band35.py)  
**部署**：[`scripts/qmt/_deploy_qmt_gbk.py`](./scripts/qmt/_deploy_qmt_gbk.py) → GBK 写入 `Band35.py` / `波段35.py`

| 配置项 | 默认 | 说明 |
| :--- | :--- | :--- |
| `DRY_RUN` | `True` | 只打印，不 `passorder`；仍模拟 T+1 |
| `TRADE_BUDGET` | `50000` | 单笔买入预算（元） |
| `PERIOD` | `15m` | 与主图 15 分钟线一致 |
| `BUY_K/D_MAX` | `20` | 超卖阈值 |
| `BUY_TIME` | `1430`–`1500`(不含) | 尾盘买入窗 |
| `SELL_K_MIN` | `85` | 超买死叉阈值 |
| `DAILY_BREAK_RATIO` | `0.99` | 15M 收盘相对 MA10 破位 |
| `STATE_FILE` | `...\python\band35_qmt_state.json` | 实盘仓位；回测只用内存 |

**下单约定（对齐 pitfalls §7.1）**

- `DRY_RUN`：不下单，日历日 T+1 模拟  
- 回测：`passorder` 后即时落状态；可卖 = `bt_held - bt_locked`；`sell skip` 不清仓  
- 实盘：`passorder` 后进 `pending`，**成交后**才改仓；可卖 = `m_nCanUseVolume`

```bash
python 波段3-5天策略/scripts/qmt/_deploy_qmt_gbk.py
```

**操作步骤**

1. 打开国金 QMT，登录交易账号  
2. 行情主图打开目标股票，周期选 **15分钟**  
3. 【模型交易】→ 选择 `Band35` / `波段35` → 选账号 → 先回测或模拟  
4. 日志确认 `Band35 v1.3 init`、`PERIOD= 15m`、`diag: ok` 后，再改 `DRY_RUN=False` 并重新部署编译  
5. 真下单：模型交易选 **实盘** + `DRY_RUN=False`  
6. 遵守 A 股 T+1；日志出现 `sell skip T+1` 属正常  

编码由部署脚本写成 **GBK**。请只编辑仓库内 `qmt_terminal_band35.py`（UTF-8）；勿直接打开国金 `python\Band35.py`。

---

*提示：本策略为单笔波段仓；改参数后务必重新部署并在 QMT 内重新编译。*
