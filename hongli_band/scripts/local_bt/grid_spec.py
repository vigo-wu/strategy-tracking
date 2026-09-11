# coding: utf-8
"""命名格子 / 笛卡尔积生成：config 参数目录、kind/id、TRAIL_TIERS 整表轴。"""
from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

EPS = 1e-9
KIND_ENUM = ("base", "tighten", "loosen", "off", "other")
WARN_CELL_SOFT = 8
EDITOR_CELL_MAX = 30
JOB_CONFIRM_THRESHOLD = 400

_HERE = Path(__file__).resolve().parent
_HLBAND_CONFIG = _HERE.parent / "qmt" / "hlband" / "config.py"

GROUP_ORDER = ("入场", "出场", "加仓", "资金", "结构", "配方")
KIND_EXIT_IDS = frozenset(
    {"STOP_LOSS", "TRAIL_TIERS", "TIME_FORCE_BARS"}
)
ENTRY_KEYS = (
    "MA_TOUCH_TOL",
    "VOL_PULLBACK_RATIO",
    "VOL_PULLBACK_N",
    "VOL_PULLBACK_CONFIRM_DAYS",
    "VOL_DRY_RATIO",
    "VOL_DRY_N",
    "CHASE_MAX_PCT",
    "W_BIAS_HARD",
    "W_BIAS_LOW",
    "W_MA30_SLOPE_WEEKS",
)
EXIT_KEYS = (
    "STOP_LOSS",
    "TRAIL_TIERS",
    "TIME_FORCE_BARS",
    "W_BEAR_CONFIRM_DAYS",
)
MONEY_KEYS = (
    "CASH_RATIO",
    "BOOK_LOT_MAX",
    "LOT_OPEN_FRAC",
    "LOT_ADD_FRAC",
    "TRADE_BUDGET",
)
PERCENT_KEYS = frozenset(
    {
        "STOP_LOSS",
        "MA_TOUCH_TOL",
        "VOL_PULLBACK_RATIO",
        "VOL_DRY_RATIO",
        "CHASE_MAX_PCT",
        "W_BIAS_HARD",
        "W_BIAS_LOW",
        "CASH_RATIO",
        "LOT_OPEN_FRAC",
        "LOT_ADD_FRAC",
        "SCALE_ARM",
        "SCALE_PLAT_MAX_RANGE",
    }
)
SKIP_NAMES = frozenset(
    {
        "DRY_RUN",
        "ACCOUNT_ID",
        "ACCOUNT_TYPE",
        "BOOK_FILE",
        "BOOK_FREEZE_CLOSE",
        "BOOK_FREEZE_OPEN",
        "BUDGET_BASE",
        "MA_TYPE",
        "PERIOD",
        "OHLC_COUNT",
        "WEEKLY_OHLC_COUNT",
        "LIVE_ONLY_LAST_BAR",
        "LIVE_CLOSE_CONFIRM",
        "DECISION_START",
        "DECISION_END",
        "PENDING_EXEC_START",
        "PENDING_EXEC_END",
        "OPEN_EXEC_START",
        "OPEN_EXEC_END",
        "SIGNAL_CONFIRM_START",
        "SIGNAL_CONFIRM_END",
        "LIVE_HEARTBEAT_SEC",
        "LIVE_OHLCV_POLICY",
        "DIVIDEND_TYPE",
        "HIST_MAX_LOOKBACK_DAYS",
        "DOWNLOAD_HIST_LIVE",
        "DOWNLOAD_HIST_BACKTEST",
        "PENDING_TIMEOUT_SEC",
        "PENDING_ORPHAN_SEC",
        "STATE_FILE",
        "LOG_DIR",
        "LOG_IN_BACKTEST",
        "STRATEGY_NAME",
        "STRATEGY_VER",
        "SCALE_OUT_LOT",
    }
)
EXPR_KEYS = frozenset(
    {
        "RECIPE_ENTRY",
        "RECIPE_EXITS",
        "RECIPE_SCALE_IN",
        "RECIPE_SCALE_OUT",
    }
)

PARAM_LABELS = {
    "STOP_LOSS": "止损",
    "TRAIL_TIERS": "阶梯止盈",
    "TIME_FORCE_BARS": "时间成本 BARS",
    "W_BEAR_CONFIRM_DAYS": "周线空确认日",
    "MA_TOUCH_TOL": "回踩容差",
    "VOL_PULLBACK_RATIO": "缩量回踩比例",
    "VOL_PULLBACK_N": "缩量窗口",
    "VOL_PULLBACK_CONFIRM_DAYS": "缩量确认日",
    "VOL_DRY_RATIO": "无量阴跌比例",
    "VOL_DRY_N": "无量窗口",
    "CHASE_MAX_PCT": "追高禁开",
    "W_BIAS_HARD": "周线高位禁开",
    "W_BIAS_LOW": "低位乖离",
    "W_MA30_SLOPE_WEEKS": "低位斜率周数",
    "SCALE_ENABLE": "加仓开关",
    "SCALE_ONCE_PER_ROUND": "每轮只加一次",
    "SCALE_ARM": "加仓门槛",
    "SCALE_ARM_BARS": "加仓持仓日",
    "SCALE_W_HIST_MIN": "加仓周柱下限",
    "SCALE_LOTS": "分笔独立",
    "SCALE_PLAT_LOOKBACK": "平台回看",
    "SCALE_PLAT_MAX_RANGE": "平台振幅",
    "SCALE_W_HIST_EXPAND_RATIO": "金叉柱放大",
    "CASH_RATIO": "可部署比例",
    "BOOK_LOT_MAX": "全池最多笔",
    "LOT_OPEN_FRAC": "开仓仓位",
    "LOT_ADD_FRAC": "第二笔仓位",
    "TRADE_BUDGET": "固定预算",
    "D_MA_MID": "日线中均线",
    "D_MA_SLOW": "日线慢均线",
    "W_MA_FAST": "周线快均线",
    "W_MA_LIFE": "周线生命线",
    "MACD_FAST": "MACD 快线",
    "MACD_SLOW": "MACD 慢线",
    "MACD_SIGNAL": "MACD 信号",
    "RECIPE_ENTRY": "入场配方",
    "RECIPE_EXITS": "出场配方",
    "RECIPE_SCALE_IN": "加仓配方",
    "RECIPE_SCALE_OUT": "减仓配方",
    "RECIPE_EXIT_WEEKLY_BEAR": "周空全平",
}
ABBREV_FIXED = {
    "STOP_LOSS": "sl",
    "TRAIL_TIERS": "tt",
    "TIME_FORCE_BARS": "tfb",
    "W_BEAR_CONFIRM_DAYS": "wbc",
    "CHASE_MAX_PCT": "ch",
    "W_BIAS_HARD": "wb",
    "W_BIAS_LOW": "wl",
    "MA_TOUCH_TOL": "mt",
    "VOL_PULLBACK_RATIO": "vpr",
    "VOL_PULLBACK_N": "vpn",
    "VOL_PULLBACK_CONFIRM_DAYS": "vpc",
    "VOL_DRY_RATIO": "vdr",
    "VOL_DRY_N": "vdn",
    "W_MA30_SLOPE_WEEKS": "ws",
    "SCALE_ENABLE": "se",
    "SCALE_ONCE_PER_ROUND": "sor",
    "SCALE_ARM": "sa",
    "SCALE_ARM_BARS": "sab",
    "SCALE_W_HIST_MIN": "swh",
    "SCALE_LOTS": "slt",
    "SCALE_PLAT_LOOKBACK": "spl",
    "SCALE_PLAT_MAX_RANGE": "spr",
    "SCALE_W_HIST_EXPAND_RATIO": "she",
    "CASH_RATIO": "cr",
    "BOOK_LOT_MAX": "blm",
    "LOT_OPEN_FRAC": "lof",
    "LOT_ADD_FRAC": "laf",
    "TRADE_BUDGET": "tb",
    "D_MA_MID": "dmm",
    "D_MA_SLOW": "dms",
    "W_MA_FAST": "wmf",
    "W_MA_LIFE": "wml",
    "MACD_FAST": "mcf",
    "MACD_SLOW": "mcs",
    "MACD_SIGNAL": "mcg",
    "RECIPE_ENTRY": "ren",
    "RECIPE_EXITS": "rex",
    "RECIPE_SCALE_IN": "rsi",
    "RECIPE_SCALE_OUT": "rso",
    "RECIPE_EXIT_WEEKLY_BEAR": "rew",
}
DEFAULT_SCAN = {
    "STOP_LOSS": "6,10",
    "TIME_FORCE_BARS": "0",
}
DEFAULT_SELECTED = ()
DEFAULT_EXTRAS = {
    "STOP_LOSS": (0.06, 0.10),
    "TIME_FORCE_BARS": (0,),
}


@dataclass(frozen=True)
class ParamSpec:
    id: str
    key: str
    label: str
    group: str
    dtype: str
    abbrev: str
    kind_mode: str
    preselect: bool
    default_scan: str


class GridSpecError(ValueError):
    """可视化加格 / spec 生成错误。"""


RETIRED_MIN_RET_MSG = (
    "TIME_FORCE_MIN_RET 已删除：让路阈值跟 TRAIL 档1 peak_lo。"
    "请去掉该轴后重存 spec；关时间成本请扫 TIME_FORCE_BARS=0。"
)
RETIRED_GRACE_MSG = (
    "TIME_FORCE_GRACE_BARS 已删除：死钱仓满 BARS 后立即强平，不再宽限。"
    "请去掉该轴后重存 spec。"
)


def _spec_has_retired_key(spec: Mapping[str, Any] | None, key: str) -> bool:
    data = dict(spec or {})
    if key in dict(data.get("axes") or {}):
        return True
    sel = data.get("param_selection") or {}
    if isinstance(sel, dict) and key in sel:
        return True
    for cell in data.get("cells") or []:
        if not isinstance(cell, dict):
            continue
        ov = cell.get("overrides") or {}
        if isinstance(ov, dict) and key in ov:
            return True
    return False


def spec_has_retired_min_ret(spec: Mapping[str, Any] | None) -> bool:
    return _spec_has_retired_key(spec, "TIME_FORCE_MIN_RET")


def spec_has_retired_grace(spec: Mapping[str, Any] | None) -> bool:
    return _spec_has_retired_key(spec, "TIME_FORCE_GRACE_BARS")


def reject_retired_min_ret(spec: Mapping[str, Any] | None) -> None:
    if spec_has_retired_min_ret(spec):
        raise GridSpecError(RETIRED_MIN_RET_MSG)
    if spec_has_retired_grace(spec):
        raise GridSpecError(RETIRED_GRACE_MSG)


def num_eq(a: Any, b: Any, eps: float = EPS) -> bool:
    if a is None and b is None:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) is bool(b) if isinstance(a, bool) and isinstance(b, bool) else False
    try:
        return abs(float(a) - float(b)) <= eps
    except (TypeError, ValueError):
        return a == b


def struct_eq(a: Any, b: Any, eps: float = EPS) -> bool:
    """json_ready 后递归比较；元组与列表视为同一结构。"""
    left = json_ready(a)
    right = json_ready(b)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            struct_eq(x, y, eps) for x, y in zip(left, right)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            return False
        return all(struct_eq(left[k], right[k], eps) for k in left)
    return num_eq(left, right, eps)


def json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_ready(x) for x in obj]
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def trail_arm(tiers: Any) -> float | None:
    try:
        return float(tiers[0][0])
    except (IndexError, TypeError, ValueError, KeyError):
        return None


def copy_trail_tiers(tiers: Any) -> list[list[Any]]:
    out: list[list[Any]] = []
    for row in tiers or ():
        seq = list(row)
        while len(seq) < 4:
            seq.append(None)
        lo, hi, gb, fl = seq[0], seq[1], seq[2], seq[3]
        out.append(
            [
                float(lo),
                None if hi is None else float(hi),
                float(gb),
                None if fl is None else float(fl),
            ]
        )
    return out


def validate_trail_row(row: list[Any], tier_idx: int) -> None:
    n = tier_idx + 1
    lo, hi, gb, fl = row[0], row[1], row[2], row[3]
    if lo is None or float(lo) <= 0:
        raise GridSpecError("档%s 起步必须 > 0" % n)
    if hi is not None and float(lo) >= float(hi) - EPS:
        raise GridSpecError("档%s 起步必须小于上限" % n)
    if gb is None or float(gb) <= 0:
        raise GridSpecError("档%s 回撤必须 > 0" % n)
    if fl is not None:
        float(fl)


def validate_trail_tiers(tiers: Any) -> list[list[Any]]:
    try:
        copied = copy_trail_tiers(tiers)
    except (TypeError, ValueError, IndexError, KeyError) as exc:
        raise GridSpecError("TRAIL_TIERS 格式无效") from exc
    if not copied:
        raise GridSpecError("TRAIL_TIERS 为空")
    for i, row in enumerate(copied):
        validate_trail_row(row, i)
    return copied


def _skip_name(name: str) -> bool:
    if not name or not str(name).isupper():
        return True
    if name.startswith("_"):
        return True
    if name in SKIP_NAMES:
        return True
    if name.startswith(("LIVE_", "PENDING_", "OPEN_", "SIGNAL_", "DECISION_", "DOWNLOAD_", "LOG_", "STRATEGY_", "HIST_")):
        return True
    if name.startswith("BOOK_FREEZE"):
        return True
    if name in ("BOOK_STOCKS", "TRADE_BUDGET_BY_STOCK", "PANEL_BINDS"):
        return True
    return False


def _load_config_ns() -> dict[str, Any]:
    if not _HLBAND_CONFIG.is_file():
        raise GridSpecError("找不到 %s" % _HLBAND_CONFIG)
    ns: dict[str, Any] = {}
    code = _HLBAND_CONFIG.read_text(encoding="utf-8")
    exec(compile(code, str(_HLBAND_CONFIG), "exec"), ns, ns)
    return ns


def _scan_config_names(ns: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for name, val in ns.items():
        if _skip_name(str(name)):
            continue
        if isinstance(val, bool) or isinstance(val, int) or isinstance(val, float):
            names.append(str(name))
        elif str(name) in EXPR_KEYS or (
            str(name).startswith("RECIPE_") and isinstance(val, (list, tuple))
        ):
            names.append(str(name))
        elif _is_numeric_tuple(val):
            names.append(str(name))
    return names


def _is_numeric_tuple(val: Any) -> bool:
    if not isinstance(val, (list, tuple)) or not val:
        return False
    return all(_numeric_tuple_leaf_ok(x) for x in val)


def _numeric_tuple_leaf_ok(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, bool):
        return False
    if isinstance(val, (int, float)):
        return True
    if isinstance(val, (list, tuple)):
        return bool(val) and all(_numeric_tuple_leaf_ok(x) for x in val)
    return False


def _is_percent_dtype(dtype: str) -> bool:
    return dtype in ("percent", "opt_percent")


def _is_none_raw(raw: Any) -> bool:
    if raw is None:
        return True
    text = str(raw).strip().lower()
    return text in NONE_TOKENS


def _group_for(name: str) -> str:
    if name.startswith("RECIPE_"):
        return "配方"
    if name in ENTRY_KEYS:
        return "入场"
    if name in EXIT_KEYS:
        return "出场"
    if name.startswith("SCALE_"):
        return "加仓"
    if name in MONEY_KEYS:
        return "资金"
    if name.startswith(("D_MA_", "MACD_")):
        return "结构"
    if name.startswith("W_MA_") and name != "W_MA30_SLOPE_WEEKS":
        return "结构"
    return "资金"


def _dtype_for(name: str, sample: Any) -> str:
    if name in EXPR_KEYS:
        return "expr"
    if name in PERCENT_KEYS:
        return "percent"
    if _is_numeric_tuple(sample):
        return "tuple"
    if isinstance(sample, bool):
        return "bool"
    if isinstance(sample, int) and not isinstance(sample, bool):
        return "int"
    return "float"


def _auto_abbrev(name: str) -> str:
    parts = [p for p in str(name).split("_") if p]
    if not parts:
        return "p"
    letters = "".join(p[0].lower() for p in parts)
    if len(letters) < 2:
        letters = (parts[0][:2] or "p").lower()
    return letters[:4]


def _unique_abbrev(name: str, used: set[str]) -> str:
    stem = ABBREV_FIXED.get(name) or _auto_abbrev(name)
    cand = stem
    n = 2
    while cand in used:
        cand = "%s_%s" % (stem, n)
        n += 1
    used.add(cand)
    return cand


def _ordered_ids(found: Iterable[str]) -> list[str]:
    have = set(found)
    out: list[str] = []
    for key in ENTRY_KEYS:
        if key in have:
            out.append(key)
    for key in EXIT_KEYS:
        if key in have and key not in out:
            out.append(key)
    rest = [n for n in found if n not in out]
    rest.sort(
        key=lambda n: (
            GROUP_ORDER.index(_group_for(n)) if _group_for(n) in GROUP_ORDER else 99,
            n,
        )
    )
    out.extend(rest)
    return out


def _build_catalog() -> tuple[ParamSpec, ...]:
    ns = _load_config_ns()
    found = _scan_config_names(ns)
    ids = _ordered_ids(found)
    used_abbrev: set[str] = set()
    specs: list[ParamSpec] = []
    for name in ids:
        sample: Any = ns.get(name)
        dtype = _dtype_for(name, sample)
        specs.append(
            ParamSpec(
                id=name,
                key=name,
                label=PARAM_LABELS.get(name, name),
                group=_group_for(name),
                dtype=dtype,
                abbrev=_unique_abbrev(name, used_abbrev),
                kind_mode="exit" if name in KIND_EXIT_IDS else "other",
                preselect=name in DEFAULT_SELECTED,
                default_scan=DEFAULT_SCAN.get(name, ""),
            )
        )
    return tuple(specs)


def _product_order(specs: tuple[ParamSpec, ...]) -> tuple[str, ...]:
    have = {p.id for p in specs}
    head = [k for k in list(EXIT_KEYS) + list(ENTRY_KEYS) if k in have]
    rest = [p.id for p in specs if p.id not in head]
    return tuple(head + rest)


_CATALOG = _build_catalog()
_CATALOG_BY_ID = {p.id: p for p in _CATALOG}
FAMILY_ORDER = _product_order(_CATALOG)
FAMILY_LABELS = {p.id: p.label for p in _CATALOG}
OVERRIDE_KEY = {p.id: p.key for p in _CATALOG}
KNOWN_OVERRIDE_KEYS = frozenset(p.key for p in _CATALOG)
_FAMILY_BY_OVERRIDE = {p.key: p.id for p in _CATALOG}


def param_catalog() -> tuple[ParamSpec, ...]:
    return _CATALOG


def get_param(family: str) -> ParamSpec | None:
    return _CATALOG_BY_ID.get(str(family))


def require_param(family: str) -> ParamSpec:
    spec = get_param(family)
    if spec is None:
        raise GridSpecError("未知参数族 %s" % family)
    return spec


def catalog_ids() -> tuple[str, ...]:
    return FAMILY_ORDER


def catalog_override_keys() -> frozenset[str]:
    return KNOWN_OVERRIDE_KEYS


def current_value(family: str, defaults: Mapping[str, Any]) -> Any:
    spec = require_param(family)
    key = spec.key
    if key not in defaults:
        raise GridSpecError("defaults 缺少 %s" % key)
    val = defaults[key]
    if spec.dtype == "expr":
        return json_ready(val)
    if spec.dtype == "tuple":
        if family == "TRAIL_TIERS":
            return validate_trail_tiers(val)
        return json_ready(val)
    if spec.dtype == "bool":
        return bool(val)
    if spec.dtype == "int":
        return int(val)
    return float(val)


def coerce_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in ("1", "true", "yes", "y", "on", "是", "真"):
        return True
    if text in ("0", "false", "no", "n", "off", "否", "假"):
        return False
    raise GridSpecError("无法解析布尔值 %r" % raw)


def coerce_level(family: str, raw: Any) -> Any:
    spec = require_param(family)
    if spec.dtype == "expr":
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return []
            try:
                raw = json.loads(text)
            except json.JSONDecodeError as exc:
                raise GridSpecError("无法解析 %s JSON" % spec.label) from exc
        if raw is None or raw is False:
            return []
        return json_ready(raw)
    if spec.dtype == "tuple":
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise GridSpecError("无法解析 %s JSON" % spec.label) from exc
        if family == "TRAIL_TIERS":
            return validate_trail_tiers(raw)
        return json_ready(raw)
    if spec.dtype == "opt_percent" and _is_none_raw(raw):
        return None
    if spec.dtype == "bool":
        return coerce_bool(raw)
    if spec.dtype == "int":
        return int(raw)
    return float(raw)


def _strip_percent_suffix(text: str) -> tuple[str, bool]:
    raw = str(text or "").strip()
    lower = raw.lower()
    if lower.endswith("pct"):
        return raw[:-3].strip(), True
    if raw.endswith("%") or raw.endswith("％"):
        return raw[:-1].strip(), True
    return raw, False


def parse_scan_token(family: str, token: str) -> Any:
    spec = require_param(family)
    text = str(token).strip()
    if not text:
        raise GridSpecError("空取值")
    if spec.dtype == "tuple":
        return coerce_level(family, text)
    if spec.dtype == "opt_percent" and _is_none_raw(text):
        return None
    if spec.dtype == "bool":
        return coerce_bool(text)
    text, had_pct = _strip_percent_suffix(text)
    if not text:
        raise GridSpecError("空取值")
    try:
        if spec.dtype == "int":
            return int(float(text))
        val = float(text)
    except ValueError as exc:
        raise GridSpecError("无法解析取值 %r" % token) from exc
    if _is_percent_dtype(spec.dtype) and (had_pct or abs(val) > 1.0 + EPS):
        val = val / 100.0
    return val


def _tables_from_json_obj(obj: Any) -> list[Any]:
    if not isinstance(obj, (list, tuple)) or not obj:
        raise GridSpecError("TRAIL_TIERS 扫描须为 JSON 表")
    first = obj[0]
    if isinstance(first, (list, tuple)) and first and isinstance(first[0], (list, tuple)):
        return list(obj)
    if isinstance(first, (list, tuple)):
        return [list(obj)]
    raise GridSpecError("TRAIL_TIERS 扫描须为二维或三维 JSON 表")


def _parse_tuple_scan(family: str, text: str) -> list[Any]:
    raw = str(text or "").strip()
    if not raw:
        return []
    tables: list[Any] = []
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        obj = None
    if obj is not None:
        tables = _tables_from_json_obj(obj)
    else:
        chunks: list[str] = []
        for part in raw.replace("；", ";").split(";"):
            for line in part.splitlines():
                line = line.strip()
                if line:
                    chunks.append(line)
        if not chunks:
            return []
        for chunk in chunks:
            try:
                piece = json.loads(chunk)
            except json.JSONDecodeError as exc:
                raise GridSpecError("无法解析 %s 扫描 JSON" % family) from exc
            tables.extend(_tables_from_json_obj(piece))
    out: list[Any] = []
    for table in tables:
        val = coerce_level(family, table)
        if any(struct_eq(val, x) for x in out):
            continue
        out.append(val)
    return out


def _parse_expr_scan(family: str, text: str) -> list[Any]:
    raw = str(text or "").strip()
    if not raw:
        return []
    pieces: list[Any] = []
    try:
        pieces.append(json.loads(raw))
    except json.JSONDecodeError:
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                pieces.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise GridSpecError("无法解析 %s JSON" % family) from exc
    out: list[Any] = []
    for piece in pieces:
        val = coerce_level(family, piece)
        if any(struct_eq(val, x) for x in out):
            continue
        out.append(val)
    return out


def parse_scan_values(family: str, text: str) -> list[Any]:
    spec = require_param(family)
    if spec.dtype == "expr":
        return _parse_expr_scan(family, text)
    if spec.dtype == "tuple":
        return _parse_tuple_scan(family, text)
    raw = (
        str(text or "")
        .replace("，", ",")
        .replace("、", ",")
        .replace(";", " ")
        .replace("；", " ")
    )
    parts = []
    for chunk in raw.split(","):
        parts.extend(chunk.split())
    out: list[Any] = []
    for tok in parts:
        if not str(tok).strip():
            continue
        val = parse_scan_token(family, tok)
        if any(num_eq(val, x) for x in out):
            continue
        out.append(val)
    return out


def unique_levels(family: str, extras: Iterable[Any], defaults: Mapping[str, Any]) -> list[Any]:
    spec = require_param(family)
    out: list[Any] = []
    for raw in extras or ():
        val = coerce_level(family, raw)
        if (
            spec.dtype != "tuple"
            and val is not None
            and _is_percent_dtype(spec.dtype)
            and abs(float(val)) > 1.0 + EPS
        ):
            val = float(val) / 100.0
        if any(struct_eq(val, x) for x in out):
            continue
        out.append(val)
    if not out:
        raise GridSpecError("%s 已选用但扫描取值为空" % spec.label)
    return out


def product_count(axes: Mapping[str, Iterable[Any]], defaults: Mapping[str, Any]) -> int:
    fams = [f for f in FAMILY_ORDER if f in axes]
    if not fams:
        return 0
    n = 1
    for fam in fams:
        n *= len(unique_levels(fam, axes[fam], defaults))
    return n


def _pct_token(value: float) -> str:
    pct = float(value) * 100.0
    if abs(pct) <= 1e-9:
        return "0"
    n = int(round(pct))
    if abs(pct - n) <= 1e-6:
        return str(n).zfill(2) if n < 10 else str(n)
    text = ("%g" % pct).replace(".", "")
    return text


def family_token(family: str, value: Any) -> str:
    spec = require_param(family)
    if spec.dtype in ("tuple", "expr"):
        blob = json.dumps(json_ready(value), ensure_ascii=True, separators=(",", ":"))
        token = hashlib.sha1(blob.encode("ascii")).hexdigest()[:6]
    elif value is None:
        token = "n"
    elif _is_percent_dtype(spec.dtype):
        token = _pct_token(float(value))
    elif spec.dtype == "int":
        token = str(int(value))
    elif spec.dtype == "bool":
        token = "1" if bool(value) else "0"
    else:
        token = ("%g" % float(value)).replace(".", "p").replace("-", "m")
    return spec.abbrev + token


def _unique_id(stem: str, used: set[str]) -> str:
    cid = stem or "cell"
    if cid not in used:
        used.add(cid)
        return cid
    i = 2
    while True:
        cand = "%s_%s" % (cid, i)
        if cand not in used:
            used.add(cand)
            return cand
        i += 1


def infer_kind(family: str, value: Any, defaults: Mapping[str, Any]) -> str:
    spec = require_param(family)
    if spec.kind_mode != "exit":
        return "other"
    if spec.dtype == "tuple":
        return _trail_tiers_kind(value, current_value(family, defaults))
    cur = current_value(family, defaults)
    if family == "TIME_FORCE_BARS":
        iv = int(value)
        if iv <= 0:
            return "off"
        if iv < int(cur):
            return "tighten"
        if iv > int(cur):
            return "loosen"
        return "other"
    fv = float(value)
    if num_eq(fv, cur):
        return "other"
    if fv < float(cur):
        return "tighten"
    return "loosen"


def _family_for_override(key: str) -> str | None:
    return _FAMILY_BY_OVERRIDE.get(str(key))


def _trail_tiers_kind(ov_tiers: Any, def_tiers: Any) -> str:
    try:
        ov = copy_trail_tiers(ov_tiers)
        de = copy_trail_tiers(def_tiers)
    except (TypeError, ValueError, IndexError, KeyError):
        return "other"
    if not ov or not de or len(ov) != len(de):
        return "other"
    rest_same = True
    for i, (a, b) in enumerate(zip(ov, de)):
        for j in range(4):
            if i == 0 and j == 0:
                continue
            if not num_eq(a[j], b[j]):
                rest_same = False
                break
        if not rest_same:
            break
    if not rest_same:
        return "other"
    if num_eq(ov[0][0], de[0][0]):
        return "other"
    if float(ov[0][0]) < float(de[0][0]):
        return "tighten"
    return "loosen"


def infer_kind_from_overrides(
    overrides: Mapping[str, Any] | None,
    defaults: Mapping[str, Any],
) -> str:
    ov = dict(overrides or {})
    keys = [k for k in ov if k in KNOWN_OVERRIDE_KEYS]
    if not keys:
        return "other"
    if len(keys) >= 2:
        return "other"
    key = keys[0]
    if key == "TRAIL_TIERS":
        return _trail_tiers_kind(ov[key], defaults.get("TRAIL_TIERS"))
    fam = _family_for_override(key)
    if fam is None:
        return "other"
    spec = get_param(fam)
    if spec is None or spec.kind_mode != "exit":
        return "other"
    if key == "STOP_LOSS":
        return infer_kind("STOP_LOSS", ov[key], defaults)
    if key == "TIME_FORCE_BARS":
        return infer_kind("TIME_FORCE_BARS", ov[key], defaults)
    return "other"


def _format_pct(value: float) -> str:
    pct = float(value) * 100.0
    if abs(pct - round(pct)) <= 1e-6:
        return "%s%%" % int(round(pct))
    return ("%g" % pct) + "%"


def _trail_row_summary(row: list[Any]) -> str:
    lo, _hi, gb, fl = row[0], row[1], row[2], row[3]
    if fl is None:
        return "%s/%s" % (_format_pct(float(lo)), _format_pct(float(gb)))
    return "%s/%s/底%s" % (
        _format_pct(float(lo)),
        _format_pct(float(gb)),
        _format_pct(float(fl)),
    )


def trail_table_summary(tiers: Any) -> str:
    try:
        copied = copy_trail_tiers(tiers)
    except (TypeError, ValueError, IndexError, KeyError):
        return "?"
    if not copied:
        return "?"
    return " · ".join(_trail_row_summary(row) for row in copied)


def format_current(family: str, defaults: Mapping[str, Any]) -> str:
    spec = require_param(family)
    val = current_value(family, defaults)
    if val is None:
        return "无"
    if spec.dtype == "tuple":
        return trail_table_summary(val)
    if spec.dtype == "expr":
        return json.dumps(json_ready(val), ensure_ascii=False, separators=(",", ":"))
    if _is_percent_dtype(spec.dtype):
        return _format_pct(float(val))
    if spec.dtype == "bool":
        return "是" if bool(val) else "否"
    if spec.dtype == "int":
        return str(int(val))
    return "%g" % float(val)


def _format_scan_token(family: str, value: Any) -> str:
    spec = require_param(family)
    if spec.dtype in ("tuple", "expr"):
        return json.dumps(json_ready(value), ensure_ascii=False, separators=(",", ":"))
    if value is None:
        return "none"
    if _is_percent_dtype(spec.dtype):
        pct = float(value) * 100.0
        if abs(pct - round(pct)) <= 1e-6:
            return str(int(round(pct)))
        return "%g" % pct
    if spec.dtype == "bool":
        return "true" if bool(value) else "false"
    if spec.dtype == "int":
        return str(int(value))
    return "%g" % float(value)


def format_scan_values(family: str, values: Iterable[Any]) -> str:
    spec = require_param(family)
    if spec.dtype in ("tuple", "expr"):
        return "\n".join(_format_scan_token(family, v) for v in values)
    return ",".join(_format_scan_token(family, v) for v in values)


def family_value_label(family: str, value: Any) -> str:
    if family == "STOP_LOSS":
        return "止损 %s" % _format_pct(float(value))
    if family == "TRAIL_TIERS":
        return "阶梯止盈 %s" % trail_table_summary(value)
    spec = get_param(family)
    if spec and spec.dtype == "expr":
        blob = json.dumps(json_ready(value), ensure_ascii=False, separators=(",", ":"))
        if family == "RECIPE_SCALE_OUT" and (not value):
            return "减仓配方关闭"
        label = spec.label if spec else family
        if len(blob) > 48:
            blob = blob[:45] + "..."
        return "%s %s" % (label, blob)
    if family == "TIME_FORCE_BARS":
        iv = int(value)
        if iv <= 0:
            return "时间成本关闭"
        return "时间成本 %s 根" % iv
    if family in ("D_MA_MID", "D_MA_SLOW"):
        try:
            iv = int(value)
        except (TypeError, ValueError):
            iv = 0
        spec = get_param(family)
        label = spec.label if spec else family
        if iv <= 0:
            return "%s关闭" % label
        return "%s %s" % (label, iv)
    spec = get_param(family)
    label = spec.label if spec else family
    if spec and spec.dtype == "opt_percent" and value is None:
        return "%s关闭" % label
    if spec and _is_percent_dtype(spec.dtype):
        return "%s %s" % (label, _format_pct(float(value)))
    if spec and spec.dtype == "bool":
        return "%s %s" % (label, "开" if bool(value) else "关")
    return "%s %s" % (label, value)


def base_label(defaults: Mapping[str, Any], families: Iterable[str]) -> str:
    fams = [f for f in FAMILY_ORDER if f in set(families)]
    if fams == ["STOP_LOSS"]:
        return "现行 %s" % _format_pct(float(current_value("STOP_LOSS", defaults)))
    if fams == ["TRAIL_TIERS"]:
        return "现行阶梯止盈 %s" % trail_table_summary(current_value("TRAIL_TIERS", defaults))
    if fams == ["TIME_FORCE_BARS"]:
        return "现行时间成本 %s 根" % int(current_value("TIME_FORCE_BARS", defaults))
    return "现行"


CURRENT_MARK = "★现行"


def combo_matches_current(combo: Mapping[str, Any], defaults: Mapping[str, Any]) -> bool:
    if not combo:
        return False
    return all(struct_eq(combo[fam], current_value(fam, defaults)) for fam in combo)


def combo_n_diffs(combo: Mapping[str, Any], defaults: Mapping[str, Any]) -> int:
    return sum(
        0 if struct_eq(combo[fam], current_value(fam, defaults)) else 1 for fam in combo
    )


def cell_is_current(cell: Mapping[str, Any] | None) -> bool:
    if not cell:
        return False
    if cell.get("is_current"):
        return True
    return str(cell.get("id") or "") == "base"


def overrides_for_combo(
    combo: Mapping[str, Any],
    defaults: Mapping[str, Any],
) -> dict[str, Any]:
    ov: dict[str, Any] = {}
    for fam, val in combo.items():
        spec = require_param(fam)
        if spec.dtype in ("tuple", "expr"):
            ov[spec.key] = json_ready(val)
        elif spec.dtype == "int":
            ov[spec.key] = int(val)
        elif spec.dtype == "bool":
            ov[spec.key] = bool(val)
        elif spec.dtype == "opt_percent" and val is None:
            ov[spec.key] = None
        else:
            ov[spec.key] = float(val)
    return ov


def combo_id(combo: Mapping[str, Any], defaults: Mapping[str, Any], used: set[str]) -> str:
    parts: list[str] = []
    for fam in FAMILY_ORDER:
        if fam not in combo:
            continue
        parts.append(family_token(fam, combo[fam]))
    return _unique_id("_".join(parts) or "cell", used)


def combo_label(combo: Mapping[str, Any], defaults: Mapping[str, Any]) -> str:
    bits: list[str] = []
    for fam in FAMILY_ORDER:
        if fam not in combo:
            continue
        bits.append(family_value_label(fam, combo[fam]))
    return " · ".join(bits)


def overrides_summary(overrides: Mapping[str, Any] | None, defaults: Mapping[str, Any] | None = None) -> str:
    ov = dict(overrides or {})
    if not ov:
        return "（无覆盖）"
    bits: list[str] = []
    if "STOP_LOSS" in ov:
        bits.append("STOP_LOSS=%s" % ov["STOP_LOSS"])
    if "TRAIL_TIERS" in ov:
        bits.append("TRAIL_TIERS=%s" % trail_table_summary(ov["TRAIL_TIERS"]))
    if "TIME_FORCE_BARS" in ov:
        bits.append("TIME_FORCE_BARS=%s" % ov["TIME_FORCE_BARS"])
    extra = [k for k in ov if k not in ("STOP_LOSS", "TRAIL_TIERS", "TIME_FORCE_BARS")]
    for k in extra:
        bits.append("%s=%s" % (k, ov[k]))
    return " · ".join(bits) if bits else "（无覆盖）"


def build_cells(
    axes: Mapping[str, Iterable[Any]],
    defaults: Mapping[str, Any],
    *,
    keep: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    fams = [f for f in FAMILY_ORDER if f in axes]
    unknown = [k for k in axes if k not in _CATALOG_BY_ID]
    if unknown:
        raise GridSpecError("未知参数轴 %s" % ", ".join(sorted(unknown)))
    if not fams:
        return []
    levels = [unique_levels(fam, axes[fam], defaults) for fam in fams]
    used_ids: set[str] = set()
    cells: list[dict[str, Any]] = []
    for prod in itertools.product(*levels):
        combo = {fam: prod[i] for i, fam in enumerate(fams)}
        ov = overrides_for_combo(combo, defaults)
        cid = combo_id(combo, defaults, used_ids)
        is_cur = combo_matches_current(combo, defaults)
        kind = infer_kind_from_overrides(ov, defaults)
        if kind not in KIND_ENUM or kind == "base":
            kind = "other"
        label = combo_label(combo, defaults)
        if is_cur:
            label = "%s · %s" % (CURRENT_MARK, label) if label else CURRENT_MARK
        cell = {
            "id": cid,
            "label": label,
            "kind": kind,
            "overrides": json_ready(ov),
            "is_current": is_cur,
            "n_diffs": combo_n_diffs(combo, defaults),
        }
        cells.append(_apply_keep(cell, keep))
    cells.sort(key=lambda c: 0 if cell_is_current(c) else 1)
    return cells


def _apply_keep(
    cell: dict[str, Any],
    keep: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if not keep:
        return cell
    prev = keep.get(str(cell["id"]))
    if not prev:
        return cell
    label = str(prev.get("label") or "").strip()
    kind = str(prev.get("kind") or "").strip().lower()
    if label:
        cell["label"] = label
    if kind in KIND_ENUM and kind != "base":
        cell["kind"] = kind
    return cell


def keep_from_cells(cells: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for raw in cells or ():
        cid = str(raw.get("id") or "").strip()
        if not cid:
            continue
        out[cid] = {
            "label": str(raw.get("label") or cid),
            "kind": str(raw.get("kind") or "other"),
        }
    return out


def unknown_override_keys(overrides: Mapping[str, Any] | None) -> list[str]:
    return sorted(k for k in dict(overrides or {}) if k not in KNOWN_OVERRIDE_KEYS)


def generator_locked(cells: Iterable[Mapping[str, Any]]) -> bool:
    for raw in cells or ():
        if unknown_override_keys(raw.get("overrides") or {}):
            return True
    return False


def axes_from_cells(
    cells: Iterable[Mapping[str, Any]],
    defaults: Mapping[str, Any],
) -> dict[str, list[Any]]:
    extras: dict[str, list[Any]] = {f: [] for f in FAMILY_ORDER}
    seen: dict[str, list[Any]] = {f: [] for f in FAMILY_ORDER}
    for raw in cells or ():
        ov = dict(raw.get("overrides") or {})
        for key, val in ov.items():
            fam = _family_for_override(key)
            if fam is None:
                continue
            try:
                level = coerce_level(fam, val)
            except (GridSpecError, TypeError, ValueError):
                continue
            if any(struct_eq(level, x) for x in seen[fam]):
                continue
            seen[fam].append(level)
            extras[fam].append(level)
    return {f: extras[f] for f in FAMILY_ORDER if extras[f]}


def merge_param_selection(
    selection: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """目录新增键补进草稿；未知键丢掉。勾选与扫描文本保留。"""
    out = default_param_selection()
    cur = dict(selection or {})
    for fam in out:
        old = cur.get(fam)
        if not isinstance(old, Mapping):
            continue
        out[fam] = {
            "selected": bool(old.get("selected")),
            "scan": str(old.get("scan") or ""),
        }
    return out


def apply_axes_to_selection(
    selection: Mapping[str, Mapping[str, Any]] | None,
    axes: Mapping[str, Iterable[Any]],
) -> dict[str, dict[str, Any]]:
    out = default_param_selection()
    if selection:
        for fam, rec in selection.items():
            if fam in out and isinstance(rec, Mapping):
                out[fam] = {
                    "selected": bool(rec.get("selected")),
                    "scan": str(rec.get("scan") or ""),
                }
    selected = set(axes or {})
    for fam in FAMILY_ORDER:
        if fam in selected:
            out[fam] = {
                "selected": True,
                "scan": format_scan_values(fam, list(axes.get(fam) or ())),
            }
        elif fam in out and fam not in (axes or {}):
            # keep existing scan text; uncheck axes not present in imported spec
            out[fam] = {
                "selected": False,
                "scan": str(out[fam].get("scan") or ""),
            }
    return out


def default_param_selection() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for spec in _CATALOG:
        out[spec.id] = {
            "selected": bool(spec.preselect),
            "scan": spec.default_scan if spec.preselect else spec.default_scan,
        }
    return out


def axes_from_selection(
    selection: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, list[Any]]:
    axes: dict[str, list[Any]] = {}
    for spec in _CATALOG:
        rec = dict((selection or {}).get(spec.id) or {})
        if not rec.get("selected"):
            continue
        axes[spec.id] = parse_scan_values(spec.id, str(rec.get("scan") or ""))
    return axes


def correct_cell_kinds(
    cells: Iterable[Mapping[str, Any]],
    defaults: Mapping[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in cells or ():
        raw_kind = str(raw.get("kind") or "").strip().lower()
        cid = str(raw.get("id") or "").strip()
        cell: dict[str, Any] = {
            "id": cid,
            "label": str(raw.get("label") or raw.get("id") or ""),
            "kind": raw_kind,
            "overrides": json_ready(raw.get("overrides") or {}),
            "is_current": bool(raw.get("is_current")) or cid == "base",
        }
        if raw.get("n_diffs") is not None:
            try:
                cell["n_diffs"] = int(raw.get("n_diffs"))
            except (TypeError, ValueError):
                pass
        if cid == "base":
            cell["kind"] = "base"
            cell["is_current"] = True
        elif raw_kind not in KIND_ENUM or raw_kind == "base":
            inferred = infer_kind_from_overrides(cell["overrides"], defaults)
            cell["kind"] = inferred if inferred in KIND_ENUM and inferred != "base" else "other"
        out.append(cell)
    return out


def chip_presets(family: str, defaults: Mapping[str, Any]) -> list[Any]:
    cur = current_value(family, defaults)
    if family == "STOP_LOSS":
        return [0.06, 0.07, 0.08, 0.09, 0.10, 0.12]
    if family == "TIME_FORCE_BARS":
        c = int(cur)
        vals = [0, max(0, c - 10), c, c + 10, 60]
        out: list[Any] = []
        for v in vals:
            if v not in out:
                out.append(int(v))
        return out
    return []


def default_extras_for(family: str) -> list[Any]:
    return list(DEFAULT_EXTRAS.get(family) or ())


YEAR_WINDOW_DEFAULTS: dict[str, int] = {
    "year_start": 2018,
    "year_end": 2026,
    "tune_start": 2018,
    "tune_end": 2022,
    "check_start": 2023,
    "check_end": 2026,
}
YEAR_WINDOW_KEYS = tuple(YEAR_WINDOW_DEFAULTS.keys())


def _as_year(raw: Any, default: int) -> int:
    try:
        y = int(raw)
    except (TypeError, ValueError):
        return int(default)
    if y < 1990 or y > 2100:
        return int(default)
    return y


def year_range_set(start: int, end: int) -> set[int]:
    lo, hi = int(start), int(end)
    if hi < lo:
        return set()
    return set(range(lo, hi + 1))


def fill_year_windows(spec: Mapping[str, Any] | None) -> dict[str, int]:
    """缺字段回落默认年，不校验重叠。"""
    src = spec if isinstance(spec, Mapping) else {}
    out: dict[str, int] = {}
    for key, default in YEAR_WINDOW_DEFAULTS.items():
        out[key] = _as_year(src.get(key), default)
    return out


def validate_year_windows(win: Mapping[str, Any]) -> dict[str, int]:
    filled = fill_year_windows(win)
    ys, ye = filled["year_start"], filled["year_end"]
    ts, te = filled["tune_start"], filled["tune_end"]
    cs, ce = filled["check_start"], filled["check_end"]
    if ys > ye:
        raise GridSpecError("回测年起必须 ≤ 止")
    run = year_range_set(ys, ye)
    tune = year_range_set(ts, te)
    check = year_range_set(cs, ce)
    if not tune:
        raise GridSpecError("调参期为空")
    if not check:
        raise GridSpecError("验收期为空")
    if not tune <= run:
        raise GridSpecError("调参期必须落在回测年内")
    if not check <= run:
        raise GridSpecError("验收期必须落在回测年内")
    if tune & check:
        raise GridSpecError("调参期与验收期不能重叠")
    return filled


def apply_year_windows(spec: dict[str, Any]) -> dict[str, int]:
    """写入 spec 六个年份字段；非法则 GridSpecError。"""
    win = validate_year_windows(spec)
    spec.update(win)
    return win


def make_spec(
    cells: list[dict[str, Any]],
    *,
    sweep: str,
    compare_div: str = "front_ratio",
    theme: str = "hongli_band",
    year_start: int | None = None,
    year_end: int | None = None,
    tune_start: int | None = None,
    tune_end: int | None = None,
    check_start: int | None = None,
    check_end: int | None = None,
    asset_split: Mapping[str, Any] | None = None,
    gate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "theme": theme,
        "sweep": str(sweep or "grid"),
        "compare_div": str(compare_div or "front_ratio"),
        "cells": cells,
    }
    raw = {
        "year_start": year_start,
        "year_end": year_end,
        "tune_start": tune_start,
        "tune_end": tune_end,
        "check_start": check_start,
        "check_end": check_end,
    }
    for key, val in raw.items():
        if val is not None:
            spec[key] = val
    spec.update(fill_year_windows(spec))
    if asset_split is not None:
        spec["asset_split"] = dict(asset_split)
    if gate is not None:
        spec["gate"] = dict(gate)
    return spec


def spec_json(spec: Mapping[str, Any]) -> str:
    return json.dumps(json_ready(spec), ensure_ascii=False, indent=2) + "\n"


def sweep_name_ok(name: str) -> bool:
    s = str(name or "").strip()
    if not s:
        return False
    if any(ch in s for ch in ("/", "\\", ":", "*", "?", "\"", "<", ">", "|")):
        return False
    return True


def sweep_stem_from_axes(axes: Mapping[str, Any] | None) -> str:
    fams = [f for f in FAMILY_ORDER if f in dict(axes or {})]
    if not fams:
        return "grid"
    parts: list[str] = []
    for fam in fams:
        spec = get_param(fam)
        parts.append(spec.abbrev if spec else str(fam).lower()[:4])
    stem = "_".join(parts) or "grid"
    return stem if sweep_name_ok(stem) else "grid"


def auto_sweep_name(
    axes: Mapping[str, Any] | None,
    *,
    when: datetime | None = None,
    existing: Iterable[str] | None = None,
) -> str:
    """开跑用：轴缩写 + 时戳；与 existing 冲突时加 _2。"""
    stem = sweep_stem_from_axes(axes)
    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    used = {str(x).strip() for x in (existing or ()) if str(x).strip()}
    return _unique_id("%s_%s" % (stem, stamp), used)
