# chinaAModel · A股日度选股模型仓库

多主题日度选股 / 跟踪 / 回测。结构对齐 [`stock_analysis_model_tracking`](../stock_analysis_model_tracking)（一主题一目录），频率为**每个交易日**。

| 主题 | 手册 | 日志 | 观察池 |
| :--- | :--- | :--- | :--- |
| 科技成长波段反转（2–4 周） | [`科技成长波段反转/model.md`](./科技成长波段反转/model.md) | [`log/`](./科技成长波段反转/log/) | [`portfolio/`](./科技成长波段反转/portfolio/) |
| 大蓝筹防御型波段（1–3 周，控回撤） | [`大蓝筹防御型波段策略/model.md`](./大蓝筹防御型波段策略/model.md) | [`log/`](./大蓝筹防御型波段策略/log/) | [`portfolio/`](./大蓝筹防御型波段策略/portfolio/) |
| 红利资产·绝对防御低回撤波段（2–4 周） | [`红利资产·绝对防御低回撤波段策略/model.md`](./红利资产·绝对防御低回撤波段策略/model.md) | [`log/`](./红利资产·绝对防御低回撤波段策略/log/) | [`portfolio/`](./红利资产·绝对防御低回撤波段策略/portfolio/) |

**共享**：日线缓存 [`data/daily/`](./data/daily/) · Skill [`.cursor/skills/a-share-daily-model/`](./.cursor/skills/a-share-daily-model/)

## 每日用法

```bash
pip install -r requirements.txt
cd <主题目录>    # 例：大蓝筹防御型波段策略
python scripts/run_screener.py
# 按 a-share-daily-model「续日」更新 portfolio + log
python scripts/run_backtest.py    # 可选
```

对 Agent 说「按 a-share-daily-model 续写今日日志 / 跑选股 / 跑回测 / 建档」。

## 新增主题

1. 新建 `<主题名>/model.md`  
2. 按 Skill **A. 建档** 补齐 log / portfolio / scripts，并登记本表  
