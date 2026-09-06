# coding: utf-8
"""滚动选股过拟合预警：有组合日权益才算 DSR；年频 4 点 skip。不当硬门。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
OVERFIT = HERE.parents[2] / ".cursor" / "skills" / "skill-backtest-overfit" / "scripts"
if str(OVERFIT) not in sys.path:
    sys.path.insert(0, str(OVERFIT))

from equity_yearly import build_daily_equity, simple_returns  # noqa: E402


MIN_DAILY_RETS = 60
PBO_MIN_COLS = 10


def _trade_rows_from_detail(path: str | Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    try:
        from analyze import analyze_detail

        result = analyze_detail(p, log_path=None, hold_metrics=False)
        return list(result.get("trades") or [])
    except Exception:
        return []


def daily_returns_from_wf(result: dict[str, Any] | None, budget: float = 100000.0) -> np.ndarray | None:
    """拼接各持有年日收益。没有明细则 None（年频点不够，不报 DSR）。"""
    parts: list[float] = []
    for row in (result or {}).get("year_rows") or []:
        trades = _trade_rows_from_detail(row.get("hold_detail_path"))
        if not trades:
            continue
        daily = build_daily_equity(trades, float(budget))
        if daily is None or daily.empty:
            continue
        rets = simple_returns(daily["equity"])
        parts.extend(float(x) for x in rets.tolist())
    if len(parts) < MIN_DAILY_RETS:
        return None
    return np.asarray(parts, dtype=float)


def select_overfit_report(
    gate: dict[str, Any],
    *,
    budget: float = 100000.0,
    n_trials: int | None = None,
    trials_returns: list[np.ndarray] | None = None,
) -> dict[str, Any]:
    """软预警。overfit_report.passed 不映射为选股 FAIL。"""
    wf_raw = (gate or {}).get("_wf_raw") or {}
    selected = daily_returns_from_wf(wf_raw, budget=budget)
    n_pass = int((gate or {}).get("n_passed_max") or 0)
    n_cells = int((gate or {}).get("n_filter_cells") or 1)
    trials = int(n_trials if n_trials is not None else max(n_pass, 1) + max(n_cells, 1))
    if selected is None:
        return {
            "status": "skip",
            "reason": "无足够组合日收益（年频点不报 DSR）",
            "n_trials": trials,
            "pbo": "skip",
        }
    matrix = None
    extra = [x for x in (trials_returns or []) if x is not None and len(x) == len(selected)]
    if extra:
        matrix = np.column_stack([selected] + extra)
    try:
        from overfit_report import build_report
    except Exception as e:
        return {"status": "skip", "reason": "无法导入 overfit_report: %s" % e, "n_trials": trials}
    pbo_note = "skip"
    if matrix is None or matrix.shape[1] < PBO_MIN_COLS:
        pbo_note = "skip"
        matrix_arg = None
    else:
        matrix_arg = matrix
    try:
        report = build_report(
            selected_returns=selected,
            n_trials=trials,
            trials_matrix=matrix_arg,
            periods_per_year=252,
        )
    except Exception as e:
        return {"status": "skip", "reason": "overfit_report 失败: %s" % e, "n_trials": trials}
    return {
        "status": "warn",
        "reason": "统计预警，不改经济硬门",
        "n_trials": trials,
        "pbo": pbo_note if matrix_arg is None else report.get("pbo"),
        "report": {
            "verdict": report.get("verdict"),
            "passed": report.get("passed"),
            "deflated_sharpe_ratio": report.get("deflated_sharpe_ratio"),
            "observed_sharpe_annual": report.get("observed_sharpe_annual"),
            "haircut": report.get("haircut"),
            "minimum_track_record_length": report.get("minimum_track_record_length"),
            "n_obs": report.get("n_obs"),
        },
    }
