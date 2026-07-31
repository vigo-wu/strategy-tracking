# QMT 终端调试踩坑录（国金等券商端）

来源：红利 T `HLT策略.py` / `qmt_terminal_hongli_t.py` 实装与回测联调。  
报错日志常见前缀：`...\python\某策略.py_SH561580...`

---

## 0. 先分清两种脚本（混用必挂）

| 形态 | 入口 | 下单 | 编码 | 适用 |
| :--- | :--- | :--- | :--- | :--- |
| **终端模型交易** | `init` + `handlebar` | `passorder` | `#coding:gbk` + 文件 GBK | 国金 QMT「模型交易 / 回测」 |
| **外部 xtquant** | `XtQuantTrader` + `run_forever` | `order_stock_async` | UTF-8 | 独立 Python 连 userdata |

把 xtquant 脚本拷进 `QMT\python\` 当模型跑 → 编码/无 init/环境全错。  
终端版示例：`红利T策略/scripts/qmt_terminal_hongli_t.py`  
部署：`python scripts/_deploy_qmt_gbk.py` → 写入 `...\python\HLT策略.py` 等。

---

## 1. 编码：`0xb9` / utf-8 decode

**现象**

```text
SyntaxError: (unicode error) 'utf-8' codec can't decode byte 0xb9 in position N
```

**原因**：文件实际是 **GBK**，首行却写 `# coding: utf-8`。`国` 的 GBK 首字节为 `0xb9`（常见于 `D:\office\国金证券QMT...` 路径字符串）。

**正确**

- 券商终端策略：`#coding:gbk`，用部署脚本 **按 GBK 字节写出**，勿用记事本 ANSI/UTF-8 来回另存。
- 国金自带示例多为 `#coding:gbk`（如 `PY简单示例.py`）。
- 仓库源码可 UTF-8；**拷进 QMT 前必须转 GBK**。

---

## 2. `NameError: __file__ is not defined`

**原因**：模型运行时是 `<string>` 执行，没有 `__file__`。

**正确**：状态文件用**绝对路径**常量，例如：

```python
STATE_FILE = r"D:\office\国金证券QMT交易端\python\hongli_t_qmt_state.json"
```

禁止 `os.path.dirname(__file__)`。

---

## 3. `NameError: account is not defined`

**原因**：`account` / `accountType` **仅**在「模型交易」界面启动时注入。主图/副图/部分回测入口没有这两个全局名。

**正确**

```python
if "account" in globals() and account:
    A.acct = str(account)
elif hasattr(C, "accountid") and C.accountid:
    A.acct = str(C.accountid)
else:
    A.acct = ACCOUNT_ID  # 脚本顶部兜底
```

同理处理 `accountType` → 默认 `"STOCK"`。可尝试 `C.set_account(A.acct)`。

---

## 4. 回测只有 init、没有信号日志

### 4.1 用了墙上时钟

**现象**：晚上跑回测，init 成功后无后续；或 `BACKTEST=True` 仍按 `datetime.now()` 卡 14:30–14:57。

**正确**

- `A.is_backtest = bool(getattr(C, "do_back_test", False))`
- 回测：用 `C.get_bar_timetag(C.barpos)` +（若有）`timetag_to_datetime`；**不要**用决策窗墙钟
- 实盘：`is_last_bar()` + 决策窗墙钟

### 4.2 硬编码 `barpos < 34` 暖机

**现象**：只有一行 `warmup skip until barpos>= 34`，之后全无。

**原因**：回测区间 K 线不足 34 根时，每根都 return，永远不算指标。

**正确**：不要用固定 barpos 门槛；以 **OHLC 长度 / 波动率** 判断是否就绪。可打 `progress barpos=` 便于确认 handlebar 在跑。

### 4.3 取数失败被静默 `return`

**现象**：init + 偶发 progress，无 `close=/J=`。

**正确**：对「空数据 / 过短 / 异常」做 **`_diag_once`** 只打一次，避免刷屏又便于定位。

---

## 5. 行情：`get_history_data` 过时与假指标

**现象**

```text
get_history_data接口版本较老，推荐使用get_market_data_ex...
close=0.91 lower=0.91 upper=0.91 J=55...
```

上下轨等于收盘 → 窗口被填充或长度不足，`std≈0`。

**正确**

1. `init` 里 `download_history_data(stock, '1d', '20220101', '')`（或 `down_history_data`）
2. 优先 `C.get_market_data_ex(..., period='1d', end_time=当日yyyymmdd, count=120, dividend_type='front_ratio')`
3. 回退：`get_market_data` → 最后才 `get_history_data`
4. 解析兼容两种返回：`{code: DataFrame}` 与 `{field: DataFrame}`
5. `std(close[-20:]) < 1e-8` 则视为未就绪，跳过
6. 日志带上 `n=`（K 线根数）与 `source=`

健康示例：

```text
HongliT diag: ok source= get_market_data_ex n= 120 end= 20240930 last= 1.08 std20= 0.01
```

---

## 6. 状态与仓位语义

- 浮仓成本/股数写入 JSON；**回测只用内存状态，禁止读写实盘 STATE_FILE**。
- 回测 `init`：仅在新会话（`barpos<=0` / 首次）清空；**中途再 init 必须保留** `float` / `bt_held`（否则孤儿双开）。
- 有底仓 + Float A/B 时：高抛 **只卖浮仓股数**，禁止按「全部持仓」清仓；`BASE_SHARES` 永不 adopt/卖出。
- `sell=True` 且 `A=False B=False`：信号成立但无浮仓 → **不落单**，属正常。
- `ContextInfo` 盘中会被回滚；委托/浮仓状态放 **全局对象 `A`**，不要挂在 `C.xxx`。
- 回测影子仓：`bt_held`（总持仓）、`bt_locked`（当日买入、T+1 不可卖）、`avail=held-locked`。

---

## 7. DRY_RUN / 实盘 / 回测模式

| 日志 | 含义 |
| :--- | :--- |
| `start back test mode` | 回测，不是实盘委托 |
| `DRY_RUN= True` | 只打印 `[DRY] BUY/SELL`，不 `passorder`（仍应模拟 T+1） |
| 模型交易选「模拟」 | 通常也不发真单 |

真下单：`DRY_RUN=False` + 模型交易 **实盘** + 重新 GBK 部署编译。

`passorder` 实盘盘中立刻报单常用 `quickTrade=1`；定时器/回调内用 `2`。日线收盘决策在最新 bar 上用 `1` 即可。

### 7.1 T+1：假平仓 → 孤儿仓 → 回测盈利虚高（必守）

**现象**

```text
[系统]WARNING:当前股票xxx可卖0股,小于需卖量N股,跳过
HongliT R-Sell done, float cleared   # 错误：拒单后仍清状态
# 随后操作明细：连续两笔买入中间无卖出；买82/卖80；期末残留仓
# CSV「盈利」虚高（残留仓吃到波段涨幅），FIFO/闭合交易对数不上
```

**根因链**

1. A 股/ETF **当日买入不可卖**（T+1）；QMT 回测用 `可卖` 校验，`需卖>可卖` 则**整单跳过**。
2. 旧逻辑：`passorder` 后立刻 `_clear_float_after_sell`（回测）/ 或按 want 下单超过 `can_use`。
3. 状态已空、账户仍持仓 → 次日再 R-A → 孤儿叠仓。
4. 导出「盈利」被残留仓污染；修复后数字下降是**虚高被修正**，不是策略突然变差。

**正确（回测 + 实盘，v2.16+）**

| 模式 | 可卖来源 | 下单量 | 清浮仓时机 |
| :--- | :--- | :--- | :--- |
| 回测 | `bt_available = bt_held - bt_locked`（当日买入进 locked，换日 unlock） | `min(want, avail)`；`avail<100` 则 skip | 仅对实际可卖量 apply；**skip 不清仓** |
| 实盘 | `m_nCanUseVolume`（经 `_max_sell_vol`） | 同上 | **仅成交/pending fill 后**；skip 打 `sell skip T+1/live` |
| DRY_RUN | 按 `opened_at` 日历日估算同日锁定 | 同上 | 只清「模拟卖掉」的部分 |

硬性禁令：

- 禁止 `passorder` 后无条件清浮仓。
- 禁止下单量 `> can_use` / `> bt_available`（会触发 QMT 整单跳过）。
- 禁止用未校验的回测 CSV「盈利」合计当绩效（先查买卖笔数是否相等、期末是否空仓）。

**回测验收清单**

```
- [ ] 日志有 v2.16+ init；出现 sell skip T+1 属正常（同日信号延后）
- [ ] 操作明细：买入笔数 == 卖出笔数；无连续同向买入
- [ ] 期末持仓 0（或仅 BASE_SHARES）
- [ ] 单笔盈利 ≈ (卖价-买价)×数量（允许费用差）；合计与 FIFO 接近
- [ ] 终端跑的是已部署的 HLCL/红利T_v25，不是旧副本；CSV mtime 晚于部署
```

---

## 8. 环境与语法

- 终端 Python 偏 **3.6**：避免 `list[str]`、`X | Y`、依赖 3.10+ 语法；终端版少用 `pathlib`/`__file__`。
- 第三方库白名单：优先 `numpy`；缺库会 `Forbidden: Module ... not in whitelist`。
- 改完仓库源码必须 **重新 `_deploy_qmt_gbk.py`**，并在 QMT 内 **重新编译/加载**；只改仓库文件终端不会自动更新。
- 部署目标以实际运行文件为准（如 `D:\service\GJQMT\python\HLCL.py`）；`红利T_v25.py` / `HLT策略.py` 一并覆盖，避免加载错文件。

---

## 9. 推荐排障顺序（清单）

```
终端回测无信号 / 报错 / 盈亏异常时:
- [ ] 1. 确认跑的是终端版（有 init/handlebar），不是 xtquant 版
- [ ] 2. 文件头 #coding:gbk 且磁盘编码为 GBK（部署脚本写出）
- [ ] 3. 无 __file__；STATE 用绝对路径；回测不写实盘 JSON
- [ ] 4. account 有 UI 注入或 ACCOUNT_ID 兜底
- [ ] 5. BACKTEST 用 K 线时间；无硬编码 barpos 暖机
- [ ] 6. download_history_data + get_market_data_ex；看 diag ok/empty/short
- [ ] 7. 主图品种=策略标的、周期匹配、区间足够长
- [ ] 8. 看 DRY_RUN / back test mode，避免误判「没下单」
- [ ] 9. T+1：无「可卖0仍 float cleared」；明细买卖闭合、无期末残留
- [ ] 10. 部署文件 mtime / 日志版本号与仓库一致后再信 CSV 盈利
```

---

## 10. 仓库锚点

| 文件 | 用途 |
| :--- | :--- |
| `红利T策略/scripts/qmt_terminal_hongli_t.py` | 终端版真源（UTF-8 仓库） |
| `红利T策略/QMT/qmt_terminal_hongli_t.py` | 同策略副本（保持与 scripts 同步） |
| `红利T策略/scripts/_deploy_qmt_gbk.py` | 转 GBK 写入国金 `python\` |
| `红利T策略/scripts/qmt_hongli_t.py` | 外部 xtquant 版（勿当终端模型） |
| `D:\service\GJQMT\python\HLCL.py` 等 | 终端运行副本（GBK） |
