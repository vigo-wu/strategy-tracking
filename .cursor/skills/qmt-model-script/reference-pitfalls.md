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

- 浮仓成本/股数写入 JSON；**回测开始应清空浮仓状态**，避免污染实盘 state 文件（或回测用单独 state 路径）。
- 有底仓 + Float A/B 时：高抛 **只卖浮仓股数**，禁止按「全部持仓」清仓。
- `sell=True` 且 `A=False B=False`：信号成立但无浮仓 → **不落单**，属正常。
- `ContextInfo` 盘中会被回滚；委托/浮仓状态放 **全局对象 `A`**，不要挂在 `C.xxx`。

---

## 7. DRY_RUN / 实盘 / 回测模式

| 日志 | 含义 |
| :--- | :--- |
| `start back test mode` | 回测，不是实盘委托 |
| `DRY_RUN= True` | 只打印 `[DRY] BUY/SELL`，不 `passorder` |
| 模型交易选「模拟」 | 通常也不发真单 |

真下单：`DRY_RUN=False` + 模型交易 **实盘** + 重新 GBK 部署编译。

`passorder` 实盘盘中立刻报单常用 `quickTrade=1`；定时器/回调内用 `2`。日线收盘决策在最新 bar 上用 `1` 即可。

### 7.1 回测假平仓叠仓（T+1）

**现象**：操作明细出现连续两笔买入中间无卖出；日志有 `R-Sell done, float cleared`，但系统 WARNING `可卖0股...跳过`。

**原因**：回测里 `_broker_position` 不可用，旧逻辑在 `passorder` 后立刻清浮仓；QMT 因 T+1 拒单后策略误判空仓，次日再开 R-A。

**正确（v2.15+）**：用 `opened_at` 日历日做 T+1 可卖上限；`sellable<100` 时 **保留浮仓、不假清仓**；仅对可卖数量 `passorder` + `_apply_sell_fill`。

---

## 8. 环境与语法

- 终端 Python 偏 **3.6**：避免 `list[str]`、`X | Y`、依赖 3.10+ 语法；终端版少用 `pathlib`/`__file__`。
- 第三方库白名单：优先 `numpy`；缺库会 `Forbidden: Module ... not in whitelist`。
- 改完仓库源码必须 **重新 `_deploy_qmt_gbk.py`**，并在 QMT 内 **重新编译/加载**；只改仓库文件终端不会自动更新。

---

## 9. 推荐排障顺序（清单）

```
终端回测无信号 / 报错时:
- [ ] 1. 确认跑的是终端版（有 init/handlebar），不是 xtquant 版
- [ ] 2. 文件头 #coding:gbk 且磁盘编码为 GBK（部署脚本写出）
- [ ] 3. 无 __file__；STATE 用绝对路径
- [ ] 4. account 有 UI 注入或 ACCOUNT_ID 兜底
- [ ] 5. BACKTEST 用 K 线时间；无硬编码 barpos 暖机
- [ ] 6. download_history_data + get_market_data_ex；看 diag ok/empty/short
- [ ] 7. 主图品种=策略标的、周期=日线、区间足够长
- [ ] 8. 看 DRY_RUN / back test mode，避免误判「没下单」
```

---

## 10. 仓库锚点

| 文件 | 用途 |
| :--- | :--- |
| `红利T策略/scripts/qmt_terminal_hongli_t.py` | 终端版真源（UTF-8 仓库） |
| `红利T策略/scripts/_deploy_qmt_gbk.py` | 转 GBK 写入国金 `python\` |
| `红利T策略/scripts/qmt_hongli_t.py` | 外部 xtquant 版（勿当终端模型） |
| `D:\office\国金证券QMT交易端\python\HLT策略.py` | 终端运行副本（GBK） |
