# 均线双周期共振策略（日线定方向 + 1小时找买点）

**主题目录**：`均线双周期策略/`｜**版本**：v1.0｜**运行**：国金 QMT 终端模型（见 §5）

大周期（日线）过滤多头方向，小周期（1小时）MA5/MA10 金叉确认买点；卖出以日线破 MA20 与 1小时硬止损为主。

---

## 1. 基础参数

| 变量 | 周期 | 默认 | 说明 |
| :--- | :--- | :--- | :--- |
| `MA20` / `MA60` | 日线 | 20 / 60 | 多头排列过滤 |
| `MA5` / `MA10` / `MA120` | 1小时 | 5 / 10 / 120 | 金叉买点 + 大支撑 |
| `MA120_TOL` | 1小时 | `0.02` | 收盘价不低于 MA120 下方 2% |
| `STOP_LOSS` | 1小时 | `0.03` | 相对成本价硬止损 -3% |
| `SWING_N` | 1小时 | `20` | 近期波段低点窗口；`USE_SWING_STOP=True` 时启用 |
| `TRADE_BUDGET` | - | `50000` | 单笔买入预算（元） |

均线均为简单移动平均（SMA）。

---

## 2. 买入信号（双周期共振）

须**同时**满足日线方向 + 1小时买点；金叉在**当前 1小时K线收盘确认**后，于**下一根 1小时K线开盘**买入。

### 2.1 日线（方向过滤）

1. `Close_1d > MA20`
2. `MA20 > MA60`

不满足则不进入待买池。

### 2.2 1小时（精准买点）

1. **支撑**：`Close_1h >= MA120 * (1 - MA120_TOL)`（默认不低于 MA120 下方 2%）
2. **金叉**：上一根 `MA5 <= MA10`，当前根 `MA5 > MA10`
3. **执行**：信号确认后，下一根小时线开盘买入

---

## 3. 卖出信号（任一触发即清仓）

### 3.1 日线破位

- 触发：日线收盘价跌破 `MA20`（`Close_1d < MA20`）
- 执行：**次日开盘**清仓

### 3.2 1小时硬止损

- 触发（满足其一）：
  1. 1小时收盘相对买入成本下跌超过 `STOP_LOSS`（默认 3%）
  2. （可选）跌破近期 `SWING_N` 根小时线最低价
- 执行：信号触发后的**下一根小时线开盘**清仓

遵守 A 股 **T+1**：当日买入不可卖；`sell skip T+1` 属正常。

---

## 4. 伪代码

```text
每根 1h bar:
  先执行挂起的 pending_entry / pending_exit（用本根开盘价）
  取日线: daily_ok = Close>MA20 and MA20>MA60
  取1h: ma5/ma10/ma120

  if 持仓:
    if 日线 Close < MA20: pending_exit(next_day_open, daily_break)
    elif 1h Close <= cost*(1-0.03) [or < swing_low]:
      pending_exit(next_hour_open, stop_1h)
  elif 无仓 and daily_ok and Close>=MA120*0.98 and ma5金叉ma10:
    pending_entry(next_hour_open)
```

---

## 5. QMT 运行（国金终端模型交易）

**脚本**：[`scripts/qmt/qmt_terminal_ma_dual.py`](./scripts/qmt/qmt_terminal_ma_dual.py)  
**部署**：[`scripts/qmt/_deploy_qmt_gbk.py`](./scripts/qmt/_deploy_qmt_gbk.py) → GBK 写入 `MaDual.py` / `均线双周期.py`

| 配置项 | 默认 | 说明 |
| :--- | :--- | :--- |
| `DRY_RUN` | `True` | 只打印，不 `passorder`；仍模拟 T+1 |
| `PERIOD` | `1h` | **主图必须为 1小时** |
| `STATE_FILE` | `...\python\ma_dual_qmt_state.json` | 实盘仓位；回测只用内存 |

```bash
python 均线双周期策略/scripts/qmt/_deploy_qmt_gbk.py
```

**操作步骤**

1. 打开国金 QMT，登录交易账号  
2. 模型交易 → 加载 `MaDual` / `均线双周期`，主图选标的，**周期=1小时**  
3. 先回测：日志应出现 `diag: ok`，确认买卖笔数对称后再改 `DRY_RUN=False` 并重新部署  
4. 必改：`ACCOUNT_ID`；改完必须重新 deploy + QMT 编译  
