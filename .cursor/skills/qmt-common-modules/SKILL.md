---
name: qmt-common-modules
description: >-
  按 scripts/qmt_common 模块化模式新建或修改国金 QMT 终端策略：
  策略片段 + common 拼接部署、单仓/双浮仓选型、钩子、MODULE_ORDER、
  禁止手改 qmt_terminal_*.py。Use when creating a new strategy, splitting
  or refactoring QMT scripts, editing scripts/qmt_common, band35/hwr/ma_dual/
  hongli fragments, _deploy_qmt_gbk.py, MODULE_ORDER, or when the user mentions
  共用模块、qmt_common、新建策略、策略骨架、拼接部署.
---

# QMT 共用模块模式（终端策略）

国金终端脚本**必须**用 `scripts/qmt_common` + 策略片段拼接，**禁止**再写整文件复制粘贴基础设施。

联调踩坑仍走 [qmt-model-script](../qmt-model-script/SKILL.md) / [reference-pitfalls.md](../qmt-model-script/reference-pitfalls.md)。  
模块清单真源：[scripts/qmt_common/NAV.md](../../../scripts/qmt_common/NAV.md)。  
布局与模板：[reference-layout.md](reference-layout.md)。

---

## 硬性约束（违反即错）

1. **禁止**跨片段 `import`；只靠 `_deploy_qmt_gbk.py` 的 `MODULE_ORDER` 拼接。
2. **禁止**手改 `qmt_terminal_*.py` 与 QMT `python\` 下 GBK 产物；只改片段后 re-deploy。
3. **禁止**在策略里复制 `_process_pending` / `_bt_roll_t1` / `_series_from_ex` / `_refresh_mode` / `_broker_position` 等已进 common 的逻辑。
4. **禁止** `__file__` 定 STATE 路径；用绝对路径 `STATE_FILE`。
5. 片段内**不要**再写 `import datetime/json/os/numpy`（preamble 已有，deploy 会剥）。
6. 源码 UTF-8；部署 GBK；字符须可 GBK 编码。
7. 改完必须跑该主题 `python .../_deploy_qmt_gbk.py` 且 `compile` 成功。
8. 默认 `DRY_RUN=True`；日志用 `STRATEGY_NAME` / `_strategy_tag()`，勿写死策略名。

---

## 路径选择

| 意图 | 动作 |
| :--- | :--- |
| 新建单仓策略（一票一仓） | **A. 单仓骨架** |
| 新建双浮仓/底仓隔离（类红利T） | **B. 双浮仓骨架** |
| 改信号/阈值/周期 | 只动策略侧 `config` / `indicators` / `market` / `strategy` |
| 改下单/T+1/暖机/行情解析 | 改 `scripts/qmt_common/`，**所有**消费者 re-deploy |
| 迁旧单文件策略 | **C. 迁移** |

---

## A. 新建单仓策略

```
进度:
- [ ] 1. 建 <主题>/model.md + <主题>/scripts/qmt/<简名>/
- [ ] 2. 写策略片段: config, indicators, market, strategy, runtime
         （可选 helpers / state_extra）
- [ ] 3. 写 _deploy_qmt_gbk.py：MODULE_ORDER = 单仓模板（见 reference-layout）
- [ ] 4. config 必填: STRATEGY_NAME, STRATEGY_VER, STATE_FILE, DRY_RUN,
         ACCOUNT_*, PERIOD, TRADE_BUDGET, _ORDER_FILLED/_DEAD, _VALID_PERIODS
- [ ] 5. runtime: init 拉历史；handlebar 调 _refresh_mode(C) 再 _handle
- [ ] 6. deploy → 预览 qmt_terminal_*.py → QMT 回测见 diag: ok
```

**只写策略特有逻辑**；买卖/pending/T+1/经纪查询一律 `common:` / `common:single:`。

范本：`波段3-5天策略/scripts/qmt/band35/` + `_deploy_qmt_gbk.py`。

---

## B. 新建双浮仓策略

```
进度:
- [ ] 1. 建 hongli 式目录；common 用到 broker_base + orders_pending（不用 single/orders）
- [ ] 2. 本地实现: broker.py（_max_sell_vol / 底仓）、orders.py（_order_* + _pending_on_*）
- [ ] 3. state_io / state / bt_recover 按浮仓腿语义
- [ ] 4. MODULE_ORDER 用双浮仓模板（见 reference-layout）
- [ ] 5. 可选钩子: _reconcile_with_broker、_heartbeat_extra
```

范本：`红利T策略/scripts/qmt/hongli/`。

---

## C. 迁移旧单文件

```
进度:
- [ ] 1. 抽出 config / indicators / market / strategy / runtime
- [ ] 2. 删除与 common 重复的 ctx/period/backtest/mode/broker/orders/market_util
- [ ] 3. 单仓接 common:single/*；特殊状态用 _state_extra_load/save
- [ ] 4. deploy 改用 qmt_common._deploy_lib；预览覆盖原 qmt_terminal_*.py
- [ ] 5. DRY_RUN 回测对比迁移前信号笔数/期末仓
```

---

## 修改准则

| 改什么 | 动哪里 |
| :--- | :--- |
| 买卖点、止损、持仓天数 | 策略 `strategy.py` / `indicators.py` |
| 预算、周期、决策窗 | 策略 `config.py` |
| 拉数字段/多周期 | 策略 `market.py` |
| pending/撤单/T+1/暖机 | `scripts/qmt_common/` → **全策略 re-deploy** |
| 单仓 fill/可卖 | `qmt_common/single/` |
| 红利浮仓 fill/底仓 | 该主题 `orders.py` / `broker.py` |

---

## 完成标准

- [ ] 无手改生成的 `qmt_terminal_*.py`
- [ ] deploy 成功且 UTF-8 预览与 GBK 目标均可 `compile`
- [ ] 基础设施未在策略目录重复实现
- [ ] `DRY_RUN=True`；回测可见 `diag: ok` / 策略日志前缀正确
