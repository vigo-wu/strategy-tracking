# coding: utf-8
"""Streamlit 展示用：中文表头 + 代码旁名称列。"""
from __future__ import annotations

from typing import Any

import pandas as pd

from trades_csv import stock_meta

ANALYSIS_YEAR_COLUMNS: dict[str, str] = {
    "year": "年份",
    "period_i": "换仓段",
    "select_year": "选股年",
    "is_rebalance": "是否换仓年",
    "picks": "标的",
    "portfolio_pnl": "组合盈亏",
    "naive_pnl": "单票合计盈亏",
    "status": "状态",
}

ANALYSIS_PERIOD_COLUMNS: dict[str, str] = {
    "period_i": "换仓段",
    "select_year": "选股年",
    "hold_years": "持有年",
    "picks": "标的",
    "period_pnl": "段盈亏",
    "status": "状态",
}

TRADES_DISPLAY_COLUMNS: dict[str, str] = {
    "i": "轮次",
    "stock": "代码",
    "buy_open_day": "买入日",
    "sell_exec_day": "卖出日",
    "buy_price": "买价",
    "sell_price": "卖价",
    "shares": "股数",
    "cost": "成本",
    "pnl": "盈亏",
    "ret_pct": "收益%",
    "hold_calendar_days": "持有天数",
    "hold_max_dd": "持有回撤%",
    "hold_max_up": "持有浮盈%",
    "buy_signal": "买入信号",
    "sell_signal": "卖出信号",
}


def normalize_display_code(stock: object) -> str:
    """展示用代码：补前导零，保留 .SH/.SZ；不把 600350.SH 收成裸码。"""
    raw = str(stock).strip() if stock is not None else ""
    if not raw or raw.lower() in ("nan", "none", "nat"):
        return ""
    upper = raw.upper()
    if "." in upper:
        num, mkt = upper.rsplit(".", 1)
        if num.isdigit():
            num = num.zfill(6)
        return "%s.%s" % (num, mkt)
    return stock_meta(upper)[0]


def stock_display_name(stock: str) -> str:
    """STOCK_META 中文名；未知则回退裸代码（stock_meta 已如此）。"""
    return stock_meta(stock)[1]


def stock_axis_label(stock: str) -> str:
    """热力图等轴标签：代码 + 名称（名称与代码相同时只显示代码）。"""
    raw = str(stock or "").strip().upper()
    if not raw:
        return ""
    name = stock_display_name(raw)
    code = stock_meta(raw)[0]
    if name and name != code and name != raw.split(".", 1)[0]:
        return "%s\n%s" % (raw, name)
    return raw


def rename_columns(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """只 rename 存在的列，保持列序（含空表，仅改列名）。"""
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    use = {k: v for k, v in mapping.items() if k in out.columns}
    if use:
        out = out.rename(columns=use)
    return out


def insert_name_column(df: pd.DataFrame, code_col: str = "代码") -> pd.DataFrame:
    """在 code_col 后插入「名称」；缺列或已有「名称」则原样返回（已有则刷新值）。"""
    if df is None:
        return pd.DataFrame()
    if df.empty or code_col not in df.columns:
        return df.copy() if df is not None else pd.DataFrame()
    out = df.copy()
    # 补前导零（2001→002001），保留市场后缀
    codes = out[code_col].map(normalize_display_code)
    out[code_col] = codes
    names = codes.map(lambda x: stock_display_name(str(x) if x is not None else ""))
    if "名称" in out.columns:
        out["名称"] = names
        cols = list(out.columns)
        cols.remove("名称")
        idx = cols.index(code_col) + 1
        cols.insert(idx, "名称")
        return out[cols]
    cols = list(out.columns)
    idx = cols.index(code_col) + 1
    out.insert(idx, "名称", names)
    return out


def with_code_and_name(
    df: pd.DataFrame,
    *,
    from_col: str = "标的",
    code_col: str = "代码",
) -> pd.DataFrame:
    """把 from_col（如「标的」）改名为「代码」并插入「名称」。"""
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    if from_col in out.columns and from_col != code_col:
        out = out.rename(columns={from_col: code_col})
    return insert_name_column(out, code_col=code_col)
