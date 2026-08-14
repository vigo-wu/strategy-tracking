# coding: utf-8
"""把完整 1 分钟线压成 14:45 因子行，并裁出早盘/尾盘稀疏分钟。"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from onr_strategy.backtest.config import OnrConfig
from onr_strategy.backtest.data import add_hhmm, last_at_or_before, slice_hhmm
from onr_strategy.backtest.signals import tail_pullback, vol_ratio


def compact_from_minutes(mins: pd.DataFrame, cfg: Optional[OnrConfig] = None) -> Dict[str, Any]:
    """用全日分钟线计算无前视压缩字段。决策截止 14:45，复查用 14:50。"""
    cfg = cfg or OnrConfig()
    work = add_hhmm(mins) if mins is not None and not mins.empty and "hhmm" not in mins.columns else mins
    empty = {
        "px_1430": None,
        "px_1445": None,
        "px_1450": None,
        "high_1445": None,
        "high_1450": None,
        "vol_body_mean": None,
        "vol_tail_mean": None,
        "vol_ratio": None,
        "pullback_1445": None,
    }
    if work is None or work.empty:
        return empty
    cut_1445 = slice_hhmm(work, cfg.t_open, cfg.t_decision, end_inclusive=True)
    cut_1450 = slice_hhmm(work, cfg.t_open, cfg.t_recheck, end_inclusive=True)
    body = slice_hhmm(work, cfg.t_open, cfg.t_tail_start, end_inclusive=False)
    tail = slice_hhmm(work, cfg.t_tail_start, cfg.t_decision, end_inclusive=True)
    empty["px_1430"] = last_at_or_before(cut_1445, cfg.t_tail_start)
    empty["px_1445"] = last_at_or_before(cut_1445, cfg.t_decision)
    empty["px_1450"] = last_at_or_before(cut_1450, cfg.t_recheck)
    if not cut_1445.empty:
        empty["high_1445"] = float(cut_1445["high"].max())
    if not cut_1450.empty:
        empty["high_1450"] = float(cut_1450["high"].max())
    if not body.empty:
        empty["vol_body_mean"] = float(body["volume"].mean())
    if not tail.empty:
        empty["vol_tail_mean"] = float(tail["volume"].mean())
    empty["vol_ratio"] = vol_ratio(work, cfg)
    empty["pullback_1445"] = tail_pullback(tail)
    return empty


def sparse_minutes(mins: pd.DataFrame) -> pd.DataFrame:
    """只留 09:30–10:00（出场）和 14:30–14:50（抽查）。量比已写入 compact。"""
    if mins is None or mins.empty:
        return pd.DataFrame()
    work = add_hhmm(mins) if "hhmm" not in mins.columns else mins
    mask = ((work["hhmm"] >= 930) & (work["hhmm"] <= 1000)) | (
        (work["hhmm"] >= 1430) & (work["hhmm"] <= 1450)
    )
    return work.loc[mask].copy()


def in_keep_window(hhmm: int) -> bool:
    return (930 <= hhmm <= 1000) or (1430 <= hhmm <= 1450)
