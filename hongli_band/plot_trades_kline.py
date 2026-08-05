# coding: utf-8
"""兼容旧入口：转发到 gen_report.py（含 K 线）。"""
from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "gen_report.py"), run_name="__main__")
