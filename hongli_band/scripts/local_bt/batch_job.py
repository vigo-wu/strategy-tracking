# coding: utf-8
"""ProcessPool 子进程入口。必须是独立模块，Windows spawn 才能 pickle。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))


def init_worker(local_bt_dir: str = "") -> None:
    d = str(local_bt_dir or HERE)
    if d not in sys.path:
        sys.path.insert(0, d)
    scripts = str(Path(d).resolve().parents[2] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def run_one(payload: dict[str, Any]) -> dict[str, Any]:
    from run import backtest_one_result

    return backtest_one_result(
        payload["csv"],
        start=str(payload.get("start") or ""),
        end=str(payload.get("end") or ""),
        out_dir=payload.get("out_dir"),
        quiet=bool(payload.get("quiet", True)),
        log_name=str(payload.get("log_name") or ""),
        year=str(payload.get("year") or ""),
    )
