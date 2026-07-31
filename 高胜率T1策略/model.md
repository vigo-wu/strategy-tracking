# 高胜率 T+1 尾盘潜伏策略（1分钟版）

**主题目录**：`高胜率T1策略/`｜**版本**：v1.1｜**运行**：国金 QMT 终端模型（见 §5）

v1.1 针对低波标的「±1.2% 无效震荡」：收紧买入（放量拉升）+ 次日分时 VWAP 动态追踪出场。

## 1. 基础参数

| 变量 | 默认 | 说明 |
| :--- | :--- | :--- |
| `LOOKBACK_N` | `240` | 约 1 日 1m K，用于 VWAP / 日内高点 |
| `NEAR_HIGH_RATIO` | `0.996` | `Close >= max(High) * 0.996` |
| `MOM_BARS` / `MOM_MIN_RET` | `10` / `0.005` | 近 10 分钟涨幅 > 0.5% |
| `VOL_RATIO_MIN` | `1.3` | 近 10 分钟均量 > 更早均量 × 1.3 |
| `stop_loss` | `0.015` | 硬止损 -1.5% |
| `target_profit` | `0.04` | 硬止盈 +4% |
| `TRAIL_ARM_RET` | `0.005` | 盈利 > 0.5% 后启用 VWAP 追踪 |
| `TRAIL_START` | `09:35` | 开始动态追踪 |
| `FORCE_EXIT` | `14:30` | 尾盘保底清仓 |
| `cash_ratio` | `0.15` | 单笔约可用资金 15% |

> VWAP = `sum(close*volume)/sum(volume)`（真实成交量加权，非 WMA）。

## 2. 买入信号（Buy_Signal）

无持仓，时间 `14:48 <= t <= 14:55`，且同时满足：

1. `Close > VWAP(近240根)`
2. `Close >= max(High) * 0.996`
3. 近 10 分钟涨幅 `> 0.5%`
4. 近 10 分钟均量 `> 更早段均量 * 1.3`（拒绝阴跌尾盘）

单标的终端模型只管主图一只；多标的池需篮子版另扩。

## 3. 卖出信号（Sell_Signal，T+1）

持仓且 **当前交易日 > 买入日**：

1. **硬止损**：收益 `<= -1.5%` → 立刻平仓  
2. **动态追踪 / 硬止盈**（`t >= 09:35`）：  
   - 收益 `>= +4%`，或  
   - 收益 `> +0.5%` 且 `Close < 今日分时 VWAP`（多头衰竭）  
3. **尾盘保底**：`t >= 14:30` 仍持仓 → 强制平仓  

买入当日不可卖；`sell skip T+1` 属正常。

## 4. 伪代码

```text
每根 1m bar:
  if 无仓 and 14:48<=t<=14:55:
    if close>VWAP and near_high and mom10>0.5% and vol_ratio>1.3:
      buy(lot(cash*0.15))
  elif 有仓 and 交易日 > 买入日:
    r = (close-cost)/cost
    if r <= -1.5%: sell(stop)
    elif t >= 09:35:
      if r >= 4% or (r > 0.5% and close < today_vwap): sell(trail/tp)
    if t >= 14:30: sell(force)
```

## 5. QMT 运行（国金终端模型交易）

**脚本**：[`scripts/qmt/qmt_terminal_hwr_t1.py`](./scripts/qmt/qmt_terminal_hwr_t1.py)  
**部署**：[`scripts/qmt/_deploy_qmt_gbk.py`](./scripts/qmt/_deploy_qmt_gbk.py) → GBK 写入 `HwrT1.py` / `高胜率T1.py`

| 配置项 | 默认 | 说明 |
| :--- | :--- | :--- |
| `DRY_RUN` | `True` | 只打印，不 `passorder`；仍模拟 T+1 |
| `PERIOD` | `1m` | 与主图 1 分钟一致 |
| `BUY_TIME` | `1448`–`1455` | 尾盘买入窗 |
| `STATE_FILE` | `...\python\hwr_t1_qmt_state.json` | 实盘仓位；回测只用内存 |

```bash
python 高胜率T1策略/scripts/qmt/_deploy_qmt_gbk.py
```

**操作步骤**

1. 打开国金 QMT，登录交易账号  
2. 主图打开目标股票，周期选 **1分钟**（建议波动更大的个股/ETF，而非极低波红利）  
3. 【模型交易】→ `HwrT1` / `高胜率T1` → 先回测，日志确认 `HwrT1 v1.1 init`、`diag: ok`  
4. 再改 `DRY_RUN=False` 并重新部署编译后实盘  

编码由部署脚本写成 **GBK**。请只编辑仓库内 UTF-8 源文件。

---

*改参数后务必重新部署并在 QMT 内重新编译。*
