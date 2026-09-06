# coding: utf-8
"""本机 Streamlit 表单草稿：JSON 读写、hydrate、按键 merge。

不缓存 editor 内部态、不缓存回测/分析结果。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping, MutableMapping

from select_config import FILTER_WIDGETS, SELECT_SIDEBAR

CACHE_PATH = Path(__file__).with_name(".ui_form_cache.json")
UI_MODE_KEY = "ui_mode"

BT_KEYS: tuple[str, ...] = (
    "bt_scope",
    "bt_dividend_types",
    "bt_verbose",
    "bt_compound",
    "bt_workers",
)
SELECT_YEAR_KEYS: tuple[str, ...] = (
    str(SELECT_SIDEBAR["year_start_key"]),
    str(SELECT_SIDEBAR["year_end_key"]),
)
ANALYSIS_KEYS: tuple[str, ...] = (
    "analysis_type_radio",
    "analysis_form_data_start",
    "analysis_form_data_end",
    "analysis_form_rebalance",
    "analysis_force_rerun",
    "analysis_compound_backtest",
    "analysis_trade_budget",
    "analysis_book_lot_max",
    "analysis_lot_open_frac",
    "analysis_lot_add_frac",
    "analysis_book_rows",
    "analysis_wf_rows",
)


def select_filter_keys() -> tuple[str, ...]:
    return tuple("select_flt_%s" % w["key"] for w in FILTER_WIDGETS)


def form_cache_keys() -> tuple[str, ...]:
    return (UI_MODE_KEY,) + BT_KEYS + SELECT_YEAR_KEYS + select_filter_keys() + ANALYSIS_KEYS


def is_editor_key(key: Any) -> bool:
    k = str(key or "")
    return k == "analysis_book_editor" or k.startswith("analysis_wf_editor_")


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def clamp_choice(value: Any, options: list[Any] | tuple[Any, ...], fallback: Any = None) -> Any:
    opts = list(options)
    if not opts:
        return fallback
    if value in opts:
        return value
    needle = str(value) if value is not None else ""
    for item in opts:
        if str(item) == needle:
            return item
    return fallback if fallback is not None else opts[0]


def load_form_cache(path: Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else CACHE_PATH
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    allowed = set(form_cache_keys())
    for key, value in data.items():
        k = str(key)
        if is_editor_key(k) or k not in allowed:
            continue
        out[k] = value
    return out


def save_form_cache(payload: Mapping[str, Any], path: Path | None = None) -> None:
    target = Path(path) if path is not None else CACHE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(json_ready(dict(payload)), ensure_ascii=False, indent=2)
    target.write_text(text + "\n", encoding="utf-8")


def snapshot_form_state(state: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in form_cache_keys():
        if key not in state or is_editor_key(key):
            continue
        out[key] = json_ready(state[key])
    return out


def merge_form_cache(updates: Mapping[str, Any], path: Path | None = None) -> dict[str, Any]:
    """只写入 updates 里出现的白名单键，其它切片保持文件原值。"""
    existing = load_form_cache(path)
    allowed = set(form_cache_keys())
    for key, value in dict(updates or {}).items():
        k = str(key)
        if is_editor_key(k) or k not in allowed:
            continue
        existing[k] = json_ready(value)
    save_form_cache(existing, path)
    return existing


def hydrate_session(state: MutableMapping[str, Any], payload: Mapping[str, Any] | None) -> list[str]:
    """仅当 key 不在 state 时写入。返回实际写入的键。"""
    applied: list[str] = []
    allowed = set(form_cache_keys())
    for key, value in dict(payload or {}).items():
        k = str(key)
        if is_editor_key(k) or k not in allowed:
            continue
        if k in state:
            continue
        state[k] = copy.deepcopy(value)
        applied.append(k)
    if "analysis_book_rows" in applied:
        state.pop("analysis_book_editor", None)
    if "analysis_wf_rows" in applied:
        for key in list(state.keys()):
            if str(key).startswith("analysis_wf_editor_"):
                del state[key]
    return applied
