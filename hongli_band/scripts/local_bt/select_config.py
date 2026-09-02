# coding: utf-8
"""选股方案侧栏参数：默认值、控件范围、文案。改这里即可，不必改 app.py。

打分权重不在侧栏，但与硬过滤同属选股可调项，也放本文件。
"""
from __future__ import annotations

from pathlib import Path
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


ANALYSIS_SIDEBAR: dict[str, Any] = {
    "title": "数据分析",
    "scan_caption": "扫描 `report/` 全部复权子目录；打分/持有均走组合 local_bt 回放。",
    "year_section": "数据区间（打分/KPI）",
    "year_start_label": "数据起始年",
    "year_end_label": "数据结束年",
    "year_caption": "数据 %s–%s · 回看 %s 后首评 %s · 评估至 %s",
    "year_start_key": "analysis_year_start",
    "year_end_key": "analysis_year_end",
    "walk_section": "Walk-forward",
    "filter_section": "硬过滤",
    "book_section": "组合仓位",
    "advanced_section": "高级",
    "submit_label": "开始分析",
    "reset_label": "重新配置",
    "refresh_label": "刷新缓存",
    "form_key": "analysis_cfg",
    "result_key": "analysis_result",
    "params_key": "analysis_params",
}

ANALYSIS_WIDGETS: list[dict[str, Any]] = [
    {
        "key": "lookback_n",
        "label": "打分回看年数",
        "widget": "number_input",
        "dtype": "int",
        "min_value": 1,
        "max_value": 10,
        "step": 1,
        "default": 2,
    },
    {
        "key": "rebalance_years",
        "label": "换仓周期（年）",
        "widget": "number_input",
        "dtype": "int",
        "min_value": 1,
        "max_value": 10,
        "step": 1,
        "default": 1,
    },
    {
        "key": "top_k",
        "label": "每段持仓只数",
        "widget": "number_input",
        "dtype": "int",
        "min_value": 1,
        "max_value": 9,
        "step": 1,
        "default": 3,
    },
    {
        "key": "score_mode",
        "label": "打分 KPI",
        "widget": "select",
        "options": [("portfolio", "组合回放（推荐）"), ("single", "单票 KPI（回退）")],
        "default": "portfolio",
    },
    {
        "key": "score_pool",
        "label": "打分池",
        "widget": "select",
        "options": [("scanned", "扫描全池"), ("passed_prefilter", "宽松预过滤")],
        "default": "scanned",
    },
    {
        "key": "force_rerun",
        "label": "强制重跑回放",
        "widget": "checkbox",
        "default": False,
    },
    {
        "key": "compound_backtest",
        "label": "复利回测（持有期跨年传递权益）",
        "widget": "checkbox",
        "default": True,
    },
    {
        "key": "workers",
        "label": "打分并行进程（0=顺序）",
        "widget": "number_input",
        "dtype": "int",
        "min_value": 0,
        "max_value": 8,
        "step": 1,
        "default": 0,
    },
    {
        "key": "trade_budget",
        "label": "组合资金帽（元）",
        "widget": "number_input",
        "dtype": "float",
        "min_value": 10000.0,
        "max_value": 5000000.0,
        "step": 10000.0,
        "default": 100000.0,
    },
    {
        "key": "book_lot_max",
        "label": "BOOK_LOT_MAX",
        "widget": "number_input",
        "dtype": "int",
        "min_value": 1,
        "max_value": 9,
        "step": 1,
        "default": 3,
    },
    {
        "key": "lot_open_frac",
        "label": "大仓档比例",
        "widget": "slider",
        "dtype": "float",
        "min_value": 0.1,
        "max_value": 0.9,
        "step": 0.05,
        "default": 0.50,
    },
    {
        "key": "lot_add_frac",
        "label": "加仓档比例",
        "widget": "slider",
        "dtype": "float",
        "min_value": 0.05,
        "max_value": 0.5,
        "step": 0.05,
        "default": 0.30,
    },
]

WEIGHT_WIDGETS: list[dict[str, Any]] = [
    {"key": "pnl", "label": "权重·盈亏", "default": WEIGHTS["pnl"]},
    {"key": "win_rate", "label": "权重·胜率", "default": WEIGHTS["win_rate"]},
    {"key": "stability", "label": "权重·稳定性", "default": WEIGHTS["stability"]},
    {"key": "profit_factor", "label": "权重·利润因子", "default": WEIGHTS["profit_factor"]},
    {"key": "quality", "label": "权重·质量", "default": WEIGHTS["quality"]},
]


def _hlband_config_path(config_path: str | None = None) -> Path:
    if config_path:
        return Path(config_path)
    return Path(__file__).resolve().parent.parent / "qmt" / "hlband" / "config.py"


def _load_hlband_config_mod(config_path: str | None = None):
    path = _hlband_config_path(config_path)
    if not path.is_file():
        return None
    import importlib.util

    spec = importlib.util.spec_from_file_location("hlband_cfg_analysis", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_book_defaults(config_path: str | None = None) -> dict[str, Any]:
    """读 hlband config 组合仓位默认值。"""
    out = {
        "trade_budget": 100000.0,
        "book_lot_max": 3,
        "lot_open_frac": 0.50,
        "lot_add_frac": 0.30,
    }
    try:
        mod = _load_hlband_config_mod(config_path)
        if mod is None:
            return out
        out["trade_budget"] = float(getattr(mod, "TRADE_BUDGET", out["trade_budget"]))
        out["book_lot_max"] = int(getattr(mod, "BOOK_LOT_MAX", out["book_lot_max"]))
        out["lot_open_frac"] = float(getattr(mod, "LOT_OPEN_FRAC", out["lot_open_frac"]))
        out["lot_add_frac"] = float(getattr(mod, "LOT_ADD_FRAC", out["lot_add_frac"]))
    except Exception:
        pass
    return out


def load_book_stocks_full(config_path: str | None = None) -> dict[str, dict[str, str]]:
    """config.BOOK_STOCKS → {code: {ma_type, dividend_type}}。读失败则空字典。"""
    from analyze import DEFAULT_DIVIDEND_TYPE, normalize_dividend_type, normalize_ma_type  # noqa: WPS433

    try:
        mod = _load_hlband_config_mod(config_path)
    except Exception:
        return {}
    if mod is None:
        return {}
    raw = getattr(mod, "BOOK_STOCKS", None)
    default_ma = normalize_ma_type(getattr(mod, "MA_TYPE", "EMA")) or "EMA"
    default_div = (
        normalize_dividend_type(getattr(mod, "DIVIDEND_TYPE", "")) or DEFAULT_DIVIDEND_TYPE
    )
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, (list, tuple)):
        items = [(str(x), {}) for x in raw]
    else:
        return {}
    out: dict[str, dict[str, str]] = {}
    for k, v in items:
        stock = str(k or "").strip().upper()
        if not stock:
            continue
        if isinstance(v, dict):
            ma = normalize_ma_type(v.get("ma_type")) or default_ma
            div = normalize_dividend_type(v.get("dividend_type")) or default_div
        elif isinstance(v, str):
            ma = normalize_ma_type(v) or default_ma
            div = default_div
        else:
            ma, div = default_ma, default_div
        out[stock] = {"ma_type": ma, "dividend_type": div}
    return out


def book_stocks_to_editor_rows(book: dict[str, dict[str, str]] | None) -> list[dict[str, str]]:
    from display_df import stock_display_name  # noqa: WPS433

    rows: list[dict[str, str]] = []
    for code in sorted((book or {}).keys()):
        cfg = book[code] or {}
        rows.append(
            {
                "代码": str(code),
                "名称": stock_display_name(str(code)),
                "均线类型": str(cfg.get("ma_type") or "EMA"),
                "复权方式": str(cfg.get("dividend_type") or "front_ratio"),
            }
        )
    return rows


def editor_rows_to_book_stocks(rows: Any) -> dict[str, dict[str, str]]:
    """data_editor 行 → normalize 前的 BOOK_STOCKS dict。忽略「名称」列。"""
    from analyze import DEFAULT_DIVIDEND_TYPE, normalize_dividend_type, normalize_ma_type  # noqa: WPS433

    out: dict[str, dict[str, str]] = {}
    if rows is None:
        return out
    if hasattr(rows, "to_dict"):
        records = rows.to_dict(orient="records")
    else:
        records = list(rows or [])
    for rec in records:
        if not isinstance(rec, dict):
            continue
        code = str(rec.get("代码") or rec.get("stock") or "").strip().upper()
        if not code:
            continue
        ma_raw = rec.get("均线类型", rec.get("ma_type"))
        div_raw = rec.get("复权方式", rec.get("dividend_type"))
        ma = normalize_ma_type(ma_raw) or "EMA"
        div = normalize_dividend_type(div_raw) or DEFAULT_DIVIDEND_TYPE
        out[code] = {"ma_type": ma, "dividend_type": div}
    return out
