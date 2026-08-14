"""ONR 离线回测脚手架（非 QMT 终端模型）。"""

from onr_strategy.backtest.config import OnrConfig
from onr_strategy.backtest.engine import BacktestResult, run_backtest
from onr_strategy.backtest.synthetic import build_demo_store

__all__ = ["OnrConfig", "BacktestResult", "run_backtest", "build_demo_store"]
