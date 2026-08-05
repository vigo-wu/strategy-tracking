# coding: utf-8
"""主题入口：委托 qmt-backtest-report 生成成交表/权益/K线/MD。"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / ".cursor" / "skills" / "qmt-backtest-report" / "scripts" / "generate_report.py"

if __name__ == "__main__":
    sys.argv = [str(SCRIPT), "--theme", str(Path(__file__).resolve().parent), *sys.argv[1:]]
    runpy.run_path(str(SCRIPT), run_name="__main__")
