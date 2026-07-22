# 目录与脚本路径约定

## 多主题扩展

新增模型时**复制**既有主题目录为新目录名，再改 `model.md` 与 `scripts/` 内阈值/池子逻辑；不要把第二个模型的文件堆回仓库根目录。

| 层级 | 放什么 | 不放什么 |
| :--- | :--- | :--- |
| 仓库根 | README 索引、requirements、共享 `data/`、可选共享 `list.md`、Skill | 某个模型的 log/output |
| `<主题>/` | model、可选 origin/list、log、portfolio、output、scripts | 其它主题的缓存 |
| `data/daily/` | 全市场/板块日线 CSV 缓存 | 回测报告（报告在主题 output） |

### 主题内可选文件

| 文件 | 用途 |
| :--- | :--- |
| `origin.md` | 策略优化草案 / 变更来源（E. 策略变更） |
| `list.md` | 主题股票池；回测 `--universe list` 默认读此文件 |
| `output/backtest_skipped_*.csv` | 因满仓/现金不足跳过的信号 |

## 脚本路径常量（必遵）

```python
THEME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = THEME_ROOT.parent
OUT_DIR = THEME_ROOT / "output"
DATA_DIR = REPO_ROOT / "data" / "daily"
LIST_MD = THEME_ROOT / "list.md"
```

## 运行 cwd

推荐：

```bash
cd <主题目录>
python scripts/run_screener.py
python scripts/run_backtest.py --universe list
python scripts/run_backtest.py --universe mainboard
```

从仓库根亦可：`python <主题>/scripts/run_backtest.py`（脚本用 `__file__` 定位，不依赖 cwd）。

## 与周期仓库的差异

| | stock_analysis_model_tracking | chinaAModel / strategy-tracking |
| :--- | :--- | :--- |
| 频率 | 月 | **交易日** |
| 核心产物 | 四维打分 /20 | 硬条件 AND + 观察池 |
| 活页 | 无 | `portfolio/active.md` |
| 量化脚本 | 通常无 | screener + backtest（可 list + 定额仓位） |
