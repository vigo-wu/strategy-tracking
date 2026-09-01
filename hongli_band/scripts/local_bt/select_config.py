# coding: utf-8
"""选股方案侧栏参数：默认值、控件范围、文案。改这里即可，不必改 app.py。

打分权重不在侧栏，但与硬过滤同属选股可调项，也放本文件。
"""
from __future__ import annotations

from typing import Any

# 侧栏分区与年份控件（选项来自扫描结果，此处只放文案 / session key）
SELECT_SIDEBAR: dict[str, Any] = {
    "scan_caption": "选股扫描 `report/` 下全部已有复权子目录，不受此处勾选限制。",
    "year_section": "打分年份",
    "year_start_label": "起始年",
    "year_end_label": "结束年",
    "year_start_key": "select_year_start",
    "year_end_key": "select_year_end",
    "year_caption": "建议均线/复权与硬过滤都在 %s–%s 内重算；改年不重新扫描。",
    # 成交年 / 盈利年控件上限 = max(year_max_floor, 窗口年数)
    "year_max_floor": 5,
    "filter_section": "硬过滤",
    "refresh_label": "刷新缓存",
}

# 侧栏硬过滤：顺序即展示顺序。key 与 score_universe / CLI 过滤器字段一致。
# widget: number_input | slider
# max_from=year_max 时 max_value 由窗口年数决定；clamp_default 把默认值压进 [min, max]
FILTER_WIDGETS: list[dict[str, Any]] = [
    {
        "key": "min_n_buy",
        "label": "最少跨年轮次",
        "widget": "number_input",
        "dtype": "int",
        "min_value": 0,
        "max_value": 50,
        "step": 1,
        "default": 6,
    },
    {
        "key": "min_n_buy_per_year",
        "label": "每年最少轮次",
        "widget": "number_input",
        "dtype": "int",
        "min_value": 0,
        "max_value": 20,
        "step": 1,
        "default": 0,
        "caption": "窗口内每一年都要达标，缺文件按 0；0 表示不启用。",
    },
    {
        "key": "min_years_traded",
        "label": "最少成交年数",
        "widget": "number_input",
        "dtype": "int",
        "min_value": 1,
        "max_value": 5,
        "step": 1,
        "default": 2,
        "max_from": "year_max",
        "clamp_default": True,
    },
    {
        "key": "min_pos_years",
        "label": "最少盈利年数",
        "widget": "number_input",
        "dtype": "int",
        "min_value": 0,
        "max_value": 5,
        "step": 1,
        "default": 2,
        "max_from": "year_max",
        "clamp_default": True,
    },
    {
        "key": "min_pos_ratio",
        "label": "或盈利年占比 ≥",
        "widget": "slider",
        "dtype": "float",
        "min_value": 0.0,
        "max_value": 1.0,
        "step": 0.05,
        "default": 0.50,
    },
    {
        "key": "max_win_pnl_share",
        "label": "单笔盈利占毛利上限",
        "widget": "slider",
        "dtype": "float",
        "min_value": 0.3,
        "max_value": 1.0,
        "step": 0.05,
        "default": 0.60,
    },
    {
        "key": "vol_drop_top",
        "label": "剔除最高波动分位",
        "widget": "slider",
        "dtype": "float",
        "min_value": 0.0,
        "max_value": 0.3,
        "step": 0.05,
        "default": 0.10,
    },
    {
        "key": "top_n",
        "label": "推荐池 N",
        "widget": "slider",
        "dtype": "int",
        "min_value": 4,
        "max_value": 9,
        "step": 1,
        "default": 10,
    },
]

WEIGHTS = {
    "pnl": 0.30,
    "win_rate": 0.20,
    "stability": 0.20,
    "profit_factor": 0.15,
    "quality": 0.15,
}

DEFAULT_FILTERS: dict[str, Any] = {w["key"]: w["default"] for w in FILTER_WIDGETS}
FILTER_BY_KEY: dict[str, dict[str, Any]] = {w["key"]: w for w in FILTER_WIDGETS}


def year_max_for_window(n_years: int) -> int:
    floor = int(SELECT_SIDEBAR.get("year_max_floor") or 5)
    return max(floor, max(int(n_years), 1))


def widget_kwargs(spec: dict[str, Any], *, year_max: int) -> dict[str, Any]:
    """Streamlit number_input / slider 的 min/max/value/step。"""
    min_v = spec["min_value"]
    max_v = spec["max_value"]
    if spec.get("max_from") == "year_max":
        max_v = int(year_max)
    value = spec["default"]
    if spec.get("clamp_default"):
        value = min(max(value, min_v), max_v)
    step = spec["step"]
    if str(spec.get("dtype") or "float") == "int":
        min_v, max_v, value, step = int(min_v), int(max_v), int(value), int(step)
    else:
        min_v, max_v, value, step = float(min_v), float(max_v), float(value), float(step)
    return {
        "min_value": min_v,
        "max_value": max_v,
        "value": value,
        "step": step,
    }


def cast_filter_value(spec: dict[str, Any], raw: Any) -> Any:
    if str(spec.get("dtype") or "float") == "int":
        return int(raw)
    return float(raw)
