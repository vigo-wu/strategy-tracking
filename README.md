# chinaAModel · A股日度选股模型仓库

多主题日度选股 / 跟踪 / 回测。结构对齐 [`stock_analysis_model_tracking`](../stock_analysis_model_tracking)（一主题一目录），频率为**每个交易日**。

| 主题 | 手册 | 日志 | 观察池 |
| :--- | :--- | :--- | :--- |
| 周日双周期趋势波段（v3.1 · list20 · 20万） | [`A股周日双周期趋势波段交易策略系统/model.md`](./A股周日双周期趋势波段交易策略系统/model.md) | [`log/`](./A股周日双周期趋势波段交易策略系统/log/) | [`portfolio/`](./A股周日双周期趋势波段交易策略系统/portfolio/) |

**共享**：日线缓存 [`data/daily/`](./data/daily/) · Skill [`.cursor/skills/a-share-daily-model/`](./.cursor/skills/a-share-daily-model/)

## 每日用法

```bash
pip install -r requirements.txt
cd <主题目录>    # 例：大蓝筹防御型波段策略
python scripts/run_screener.py
# 按 a-share-daily-model「续日」更新 portfolio + log
python scripts/run_backtest.py    # 可选
```

对 Agent 说「按 a-share-daily-model 续写今日日志 / 跑选股 / 跑回测 / 建档 / 策略变更」。

## 新增主题

1. 新建 `<主题名>/model.md`  
2. 按 Skill **A. 建档** 补齐 log / portfolio / scripts，并登记本表  

## 策略变更 / 名单回测

- 有 `origin.md` 或口述优化：按 Skill **E. 策略变更**  
- 用 `list.md` + 定额仓位回测：按 Skill **D. 回测**（详见 skill 内 `reference-backtest.md`）  
