# 目录与脚本路径约定

## 多主题扩展

新增模型时**复制** `科技成长波段反转/` 为新目录名，再改 `model.md` 与 `scripts/` 内阈值/池子逻辑；不要把第二个模型的文件堆回仓库根目录。

| 层级 | 放什么 | 不放什么 |
| :--- | :--- | :--- |
| 仓库根 | README 索引、requirements、共享 `data/`、Skill | 某个模型的 log/output |
| `<主题>/` | model、log、portfolio、output、scripts | 其它主题的缓存 |
| `data/daily/` | 全市场/板块日线 CSV 缓存 | 回测报告（报告在主题 output） |

## 脚本路径常量（必遵）

```python
THEME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = THEME_ROOT.parent
OUT_DIR = THEME_ROOT / "output"
DATA_DIR = REPO_ROOT / "data" / "daily"
```

## 运行 cwd

推荐：

```bash
cd <主题目录>
python scripts/run_screener.py
python scripts/run_backtest.py
```

从仓库根亦可：`python <主题>/scripts/run_screener.py`（脚本用 `__file__` 定位，不依赖 cwd）。

## 与周期仓库的差异

| | stock_analysis_model_tracking | chinaAModel |
| :--- | :--- | :--- |
| 频率 | 月 | **交易日** |
| 核心产物 | 四维打分 /20 | 硬条件 AND + 观察池 |
| 活页 | 无 | `portfolio/active.md` |
| 量化脚本 | 通常无 | screener + backtest |
