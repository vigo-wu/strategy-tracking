# QMT 脚本骨架

## 国金终端模型（现行必遵）

终端策略**不要**再落单文件基础设施。按 [qmt-common-modules](../qmt-common-modules/SKILL.md) + [reference-layout.md](../qmt-common-modules/reference-layout.md)：

- 策略片段：`<主题>/scripts/qmt/<简名>/{config,indicators,market,strategy,runtime}.py`
- 共用：`scripts/qmt_common/`（`common:` 拼接）
- 部署：`_deploy_qmt_gbk.py` → 预览 `qmt_terminal_<简名>.py` + QMT `python\` GBK
- 范本：单仓 `波段3-5天策略/scripts/qmt/`；双浮仓 `红利T策略/scripts/qmt/hongli/`

以下各节主要服务 **外部 xtquant** 脚本（`qmt_<简名>.py`，UTF-8）。

---

# xtquant / 历史骨架说明

输出路径：`<主题>/scripts/qmt/qmt_<简名>.py`。

## 顶部配置（必须集中、可改）

```python
QMT_USERDATA = r"D:\qmt\userdata_mini"  # 投研则 ...\userdata
ACCOUNT_ID = "填入资金账号"
ACCOUNT_TYPE = "STOCK"
STOCK_CODE = "561580.SH"
STRATEGY_NAME = "Theme_vX"

# 定额 / 阈值 —— 从 model.md 抄，勿自创
BASE_BUDGET = ...
FLOAT_A_BUDGET = ...
SPACE_STEP = ...
BOLL_N, BOLL_K, KDJ_N = 20, 2.0, 9
DECISION_START, DECISION_END = (14, 30), (14, 57)
DRY_RUN = True
AUTO_BUY_BASE = False
# 状态落盘（终端模型无 __file__，必须用绝对路径）
STATE_FILE = r"D:\office\国金证券QMT交易端\python\hongli_t_qmt_state.json"
# 外部 xtquant 版才可用 Path(__file__)...
```

## 模块顺序

1. **状态容器** `A`：trader、acc、float 腿、acted_today、busy  
2. **load_state / save_state**：JSON 持久化浮仓成本与股数  
3. **calc_* 指标**：与主题 `model.md` / 既有 QMT 指标模块同公式（rolling / ewm 参数一致）  
4. **fetch_daily_df**：download → get_market_data_ex → tick 修正当日 bar  
5. **Callback 类**：日志级实现即可  
6. **place_buy / place_sell**：尊重 DRY_RUN；整手；**卖出量 ≤ 可卖**（实盘 `m_nCanUseVolume` / 回测 `bt_held-bt_locked`）；skip 不清浮仓；成交后再改状态  
7. **evaluate_and_trade**：决策窗内；优先级一般 **先卖后买**；空间不足不记死 acted（允许同日跌透再开）  
8. **main**：load_state → connect → 快照 → subscribe_quote(1m) → 窗内则立即 evaluate → run_forever  

终端模型额外硬约束（见 [reference-pitfalls.md](reference-pitfalls.md) §7.1）：回测禁读写实盘 STATE；中途 `init` 不擦浮仓；T+1 未可卖则 `sell skip` 并保留状态。

## 信号分支伪代码

```text
if not in_decision_window: return
reset acted if new day
ind = boll + kdj on daily(with tick close)
if sell_cond and has_float and SELL not acted:
    sell all float legs; clear state; mark SELL
elif buy_A_cond and zero_float and RA not acted:
    lot buy A budget; save float_a; mark RA
elif buy_B_cond and has_A and not has_B:
    if close > A_price * (1 - SPACE_STEP): log skip; return  # 不 mark RB
    lot buy B budget; save float_b; mark RB
else: log 观望
```

## 状态 JSON 示例

```json
{
  "stock": "561580.SH",
  "version": "v2.5",
  "base_done": true,
  "float_a": {"shares": 41000, "price": 1.20, "cost": 49200.0},
  "float_b": null,
  "last_signal_date": "20260728"
}
```

## 用户交付话术（转写结束时）

1. 先问清：终端模型交易，还是外部 xtquant  
2. 终端：GBK 部署 + 主图日线回测见 `diag: ok` 后再实盘  
3. 踩坑速查：[reference-pitfalls.md](reference-pitfalls.md)  
4. 必改：`ACCOUNT_ID` / `DRY_RUN`；改完必须重新 deploy + QMT 编译
