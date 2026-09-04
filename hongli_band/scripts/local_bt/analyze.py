# coding: utf-8
"""本地回测操作明细 → 轮次 / 权益 / KPI；日线 CSV → OHLC。"""
from __future__ import annotations

import importlib.util
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
THEME = REPO / "hongli_band"
REPORT_PY = (
    REPO / ".cursor" / "skills" / "qmt-backtest-report" / "scripts" / "generate_report.py"
)

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from display_df import TRADES_DISPLAY_COLUMNS, insert_name_column, rename_columns  # noqa: E402
from market_csv import (  # noqa: E402
    aggregate_weekly,
    compact_day,
    find_weekly_csv,
    load_daily_csv,
    load_weekly_csv,
    peek_daily_csv_meta,
    week_monday,
)

MA_TYPES = ("SMA", "EMA")
MA_PNL_CLOSE = 1.0

DIVIDEND_TYPES = ("none", "front", "back", "front_ratio", "back_ratio")
DIVIDEND_LABELS = {
    "none": "不复权",
    "front": "前复权",
    "back": "后复权",
    "front_ratio": "等比前复权",
    "back_ratio": "等比后复权",
}
DEFAULT_DIVIDEND_TYPE = "front_ratio"
DEFAULT_CSV_ROOT = REPO / "tools" / "csv"
DEFAULT_REPORT_ROOT = THEME / "report"
HLBAND_CONFIG = THEME / "scripts" / "qmt" / "hlband" / "config.py"
# front/front_ratio 回测改读 none CSV + divid_factors 做 PIT；报告目录名仍为逻辑复权
PIT_LOGICAL_DIVS = frozenset({"front", "front_ratio"})


def uses_pit_front(dividend_type: Any) -> bool:
    return normalize_dividend_type(dividend_type) in PIT_LOGICAL_DIVS


def csv_source_dividend_type(dividend_type: Any = "") -> str:
    """逻辑复权 → 实际读取的 CSV 子目录（front* → none）。"""
    div = normalize_dividend_type(dividend_type) or DEFAULT_DIVIDEND_TYPE
    if div in PIT_LOGICAL_DIVS:
        return "none"
    return div


def divid_factors_json_path(csv_root: str | Path, stock: str) -> Path:
    root = Path(csv_root)
    if root.name in DIVIDEND_TYPES:
        root = root.parent
    tag = str(stock or "").strip().upper().replace(".", "_")
    return root / "divid_factors" / ("%s.json" % tag)


def load_divid_factors_json(csv_root: str | Path, stock: str) -> dict[str, Any]:
    import json

    path = divid_factors_json_path(csv_root, stock)
    if not path.is_file():
        raise FileNotFoundError(
            "缺 divid_factors: %s（请跑 KlineDump，DUMP_STOCKS 须含该票且 DUMP_DIVID_FACTORS=True）"
            % path
        )
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("divid_factors 非 dict: %s" % path)
    return raw


def normalize_dividend_type(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    return s if s in DIVIDEND_TYPES else ""


def dividend_label(dividend_type: Any) -> str:
    div = normalize_dividend_type(dividend_type) or DEFAULT_DIVIDEND_TYPE
    return DIVIDEND_LABELS.get(div, div)


def unique_dividend_types(rows: list[dict[str, Any]]) -> list[str]:
    """出现过的合法复权，按 DIVIDEND_TYPES 保序。"""
    seen: set[str] = set()
    for r in rows:
        d = normalize_dividend_type(r.get("dividend_type"))
        if d:
            seen.add(d)
    return [d for d in DIVIDEND_TYPES if d in seen]


def resolve_typed_dir(root: str | Path, dividend_type: Any = "") -> Path:
    """root/<type>；root 已是该 type 目录名则不再拼接。非法 type 回落默认。

    若 root/<type> 不存在，再找 root/<快照>/<type>（如 ``20070104_20260828/front_ratio``），
    多个快照时取目录名最大者（通常对应最新结束日）。
    """
    base = Path(root)
    div = normalize_dividend_type(dividend_type) or DEFAULT_DIVIDEND_TYPE
    if base.name == div:
        return base
    direct = base / div
    if direct.is_dir():
        return direct
    if base.is_dir():
        found: list[Path] = []
        try:
            children = list(base.iterdir())
        except OSError:
            children = []
        for child in children:
            if not child.is_dir() or child.name in DIVIDEND_TYPES:
                continue
            typed = child / div
            if typed.is_dir():
                found.append(typed)
        if found:
            return max(found, key=lambda p: p.parent.name)
    return direct


def parse_stock_filter_tokens(raw: Any) -> list[str]:
    """代码过滤：逗号（含中文逗号）或空白拆多个 token；连续分隔符当一次。"""
    s = str(raw or "").strip().upper()
    if not s:
        return []
    s = s.replace("，", ",").replace("；", " ").replace(";", " ")
    out: list[str] = []
    seen: set[str] = set()
    for chunk in s.replace(",", " ").split():
        t = chunk.strip().upper()
        if (not t) or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def stock_matches_filter(stock: str, tokens: list[str] | None) -> bool:
    """空 token 不过滤；任一 token 命中代码（含子串、600350_SH / 600350.SH）。"""
    if not tokens:
        return True
    s = str(stock or "").strip().upper()
    if not s:
        return False
    compact = s.replace("_", ".")
    for raw in tokens:
        t = str(raw or "").strip().upper()
        if not t:
            continue
        t_norm = t.replace("_", ".")
        if t in s or t_norm in compact:
            return True
    return False


def parse_dividend_types(raw: Any) -> list[str]:
    """逗号/空白分隔的复权列表，按 DIVIDEND_TYPES 去重保序。空输入 → 默认一种。"""
    parts: list[str] = []
    if raw is None or raw is False:
        parts = []
    elif isinstance(raw, (list, tuple, set)):
        parts = [str(x) for x in raw]
    else:
        s = str(raw or "").strip()
        if s:
            for chunk in s.replace(",", " ").split():
                if chunk:
                    parts.append(chunk)
    seen: set[str] = set()
    for p in parts:
        d = normalize_dividend_type(p)
        if d:
            seen.add(d)
    if not parts:
        return [DEFAULT_DIVIDEND_TYPE]
    return [d for d in DIVIDEND_TYPES if d in seen]


def typed_dir_root(path: str | Path) -> Path:
    p = Path(path)
    if p.name in DIVIDEND_TYPES:
        return p.parent
    return p


def typed_sibling_dirs(path: str | Path) -> list[tuple[str, Path]]:
    """path 所属根下已存在的复权子目录；没有则只返回 path 自身（旧扁平目录）。"""
    p = Path(path)
    root = typed_dir_root(p)
    found: list[tuple[str, Path]] = []
    for div in DIVIDEND_TYPES:
        d = root / div
        if d.is_dir():
            found.append((div, d))
    if found:
        return found
    if p.is_dir():
        return [("", p)]
    if root.is_dir():
        return [("", root)]
    return []


typed_report_dirs = typed_sibling_dirs


_DETAIL_NAME_RE = re.compile(
    r"^local_bt_(\d{6})_(SZ|SH)(?:_(\d{4}))?(?:_(SMA|EMA))?_操作明细\.csv$",
    re.IGNORECASE,
)
_CODE_EX_IN_NAME = re.compile(r"(\d{6})[._](SZ|SH)", re.IGNORECASE)


def _norm_listed_stock(raw: Any) -> str:
    s = str(raw or "").strip().upper().replace("_", ".")
    if not s:
        return ""
    m = re.match(r"^(\d{6})\.(SH|SZ)$", s)
    if m:
        return "%s.%s" % (m.group(1), m.group(2))
    m = re.match(r"^(\d{6})$", s)
    if m:
        return m.group(1)
    return ""


def _stock_token_match(meta_stock: str, want: str) -> bool:
    a = _norm_listed_stock(meta_stock) or str(meta_stock or "").strip().upper().replace("_", ".")
    b = _norm_listed_stock(want) or str(want or "").strip().upper().replace("_", ".")
    if not a or not b:
        return False
    if a == b:
        return True
    ac = a.split(".", 1)[0]
    bc = b.split(".", 1)[0]
    if ac != bc:
        return False
    am = a.split(".", 1)[1] if "." in a else ""
    bm = b.split(".", 1)[1] if "." in b else ""
    if am and bm and am != bm:
        return False
    return True


def daily_csv_for_stock(csv_dir: str | Path, stock: str) -> Path | None:
    want = str(stock or "").strip().upper()
    if not want:
        return None
    index = _daily_csv_path_index(Path(csv_dir))
    hit = index.get(want)
    if hit is not None:
        return hit
    for got, path in index.items():
        if _stock_token_match(got, want):
            return path
    return None


_DAILY_PATH_INDEX: dict[str, tuple[tuple[int, int], dict[str, Path]]] = {}


def _daily_csv_path_index(csv_dir: Path) -> dict[str, Path]:
    """按文件名建 代码→日线路径；避免 daily_csv_for_stock 每次 peek 整目录。"""
    root = Path(csv_dir)
    key = str(root)
    files = list_daily_csvs(root)
    try:
        fp = (len(files), max((p.stat().st_mtime_ns for p in files), default=0))
    except OSError:
        fp = (len(files), 0)
    cached = _DAILY_PATH_INDEX.get(key)
    if cached and cached[0] == fp:
        return cached[1]
    index: dict[str, Path] = {}
    for path in files:
        m = _CODE_EX_IN_NAME.search(path.stem)
        if not m:
            continue
        code = "%s.%s" % (m.group(1), m.group(2).upper())
        prev = index.get(code)
        if prev is None or path.name > prev.name:
            index[code] = path
    _DAILY_PATH_INDEX[key] = (fp, index)
    return index


def stock_from_detail_path(path: str | Path, *, read_csv: bool = True) -> str:
    """从操作明细文件名（或代码列）推断 600350.SH。"""
    p = Path(path)
    m = _DETAIL_NAME_RE.match(p.name)
    if m:
        return "%s.%s" % (m.group(1), m.group(2).upper())
    m2 = _CODE_EX_IN_NAME.search(p.stem)
    if m2:
        return "%s.%s" % (m2.group(1), m2.group(2).upper())
    if not read_csv:
        return ""
    return _stock_from_detail_csv(p)


def _stock_from_detail_csv(path: Path) -> str:
    try:
        import csv as _csv

        with path.open("r", encoding="utf-8-sig", errors="replace") as f:
            reader = _csv.reader(f)
            header = next(reader, None)
            if not header:
                return ""
            idx = None
            for i, c in enumerate(header):
                if str(c).strip() in ("代码", "证券代码"):
                    idx = i
                    break
            if idx is None:
                return ""
            for row in reader:
                if idx >= len(row):
                    continue
                tok = _norm_listed_stock(row[idx])
                if tok:
                    return tok
    except Exception:
        return ""
    return ""


def dividend_from_detail_path(path: str | Path) -> str:
    """明细父目录名是复权类型则返回；回测记录等返回空串。"""
    return normalize_dividend_type(Path(path).parent.name)


def match_daily_csv_for_detail(
    detail: str | Path,
    csv_root: str | Path,
    fallback_divs: list[str] | tuple[str, ...] | None = None,
) -> Path | None:
    """按明细标的 + 所在复权目录匹配 csv/<type>/ 日线；目录无文件再试 fallback_divs。"""
    stock = stock_from_detail_path(detail)
    if not stock:
        return None
    order: list[str] = []
    preferred = dividend_from_detail_path(detail)
    if preferred:
        order.append(preferred)
    for raw in fallback_divs or ():
        d = normalize_dividend_type(raw)
        if d and d not in order:
            order.append(d)
    if not order:
        order.append(DEFAULT_DIVIDEND_TYPE)
    root = Path(csv_root)
    for div in order:
        found = daily_csv_for_stock(resolve_typed_dir(root, div), stock)
        if found is not None and found.is_file():
            return found
    return None


_DIV_TIE_ORDER = (DEFAULT_DIVIDEND_TYPE,) + tuple(
    d for d in DIVIDEND_TYPES if d != DEFAULT_DIVIDEND_TYPE
)


def pick_div_winner(
    kpis_by_type: dict[str, dict[str, Any] | None],
    *,
    close_eps: float = MA_PNL_CLOSE,
) -> dict[str, Any]:
    """多种复权：总盈亏高者胜；与最高者 |Δ|≤close_eps 再比胜率；仍平按 front_ratio 优先。"""
    scored: list[tuple[str, float, float]] = []
    pnl_by: dict[str, float] = {}
    wr_by: dict[str, float] = {}
    for div in DIVIDEND_TYPES:
        if div not in kpis_by_type:
            continue
        kpi = kpis_by_type.get(div)
        pnl = _usable_pnl(kpi)
        if pnl is None:
            continue
        wr = _usable_win_rate(kpi)
        scored.append((div, pnl, wr))
        pnl_by[div] = pnl
        wr_by[div] = wr
    out: dict[str, Any] = {
        "winner": "",
        "label": "",
        "why": "",
        "pnl_by_type": pnl_by,
        "win_rate_by_type": wr_by,
    }
    if not scored:
        return out
    if len(scored) == 1:
        div = scored[0][0]
        out.update(
            {
                "winner": div,
                "label": DIVIDEND_LABELS.get(div, div),
                "why": "single_div",
            }
        )
        return out
    best_pnl = max(p for _d, p, _w in scored)
    close = [(d, p, w) for d, p, w in scored if abs(p - best_pnl) <= float(close_eps)]
    if len(close) == 1:
        div = close[0][0]
        out.update(
            {
                "winner": div,
                "label": DIVIDEND_LABELS.get(div, div),
                "why": "compare",
            }
        )
        return out
    best_wr = max(w for _d, _p, w in close)
    wr_winners = [d for d, _p, w in close if w == best_wr]
    winner = ""
    for d in _DIV_TIE_ORDER:
        if d in wr_winners:
            winner = d
            break
    if not winner:
        winner = wr_winners[0]
    out.update(
        {
            "winner": winner,
            "label": "接近",
            "why": "compare_close",
        }
    )
    return out


def div_compare_dataframe(
    kpis_by_type: dict[str, dict[str, Any] | None],
    *,
    stock: str = "",
    year: str = "",
) -> pd.DataFrame:
    """每种复权一行：轮次 / 盈亏 / 胜率 / 平均收益%；胜出者「更优」为「是」。"""
    pick = pick_div_winner(kpis_by_type)
    winner = str(pick.get("winner") or "")
    recs: list[dict[str, Any]] = []
    for div in DIVIDEND_TYPES:
        if div not in kpis_by_type:
            continue
        kpi = kpis_by_type.get(div) or {}
        rec: dict[str, Any] = {}
        if stock:
            rec["代码"] = stock
        if year:
            rec["年份"] = year
        rec["复权"] = DIVIDEND_LABELS.get(div, div)
        rec["轮次"] = kpi.get("n_buy")
        rec["总盈亏"] = kpi.get("sum_pnl")
        rec["胜率"] = kpi.get("win_rate")
        rec["平均收益%"] = kpi.get("avg_ret")
        rec["更优"] = "是" if div == winner else ""
        recs.append(rec)
    cols = ["复权", "轮次", "总盈亏", "胜率", "平均收益%", "更优"]
    if year:
        cols = ["年份"] + cols
    if stock:
        cols = ["代码"] + cols
    df = pd.DataFrame(recs, columns=cols)
    if "轮次" in df.columns:
        df["轮次"] = pd.to_numeric(df["轮次"], errors="coerce").astype("Int64")
    for col in ("总盈亏", "胜率", "平均收益%"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return insert_name_column(df, code_col="代码") if stock else df


def normalize_ma_type(raw: Any) -> str:
    s = str(raw or "").strip().upper()
    return s if s in MA_TYPES else ""


def _usable_pnl(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    if row.get("ok") is False:
        return None
    v = row.get("sum_pnl")
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _usable_win_rate(row: dict[str, Any] | None) -> float:
    if not row:
        return 0.0
    v = row.get("win_rate")
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def agg_kpi_pnl(kpis: list[dict[str, Any]]) -> dict[str, Any]:
    """多段 KPI → 对照用的盈亏/胜率（胜率按轮次加权）。"""
    n_buy = 0.0
    sum_pnl = 0.0
    win_n = 0.0
    for k in kpis:
        nb = float(k.get("n_buy") or 0)
        n_buy += nb
        sum_pnl += float(k.get("sum_pnl") or 0)
        win_n += float(k.get("win_rate") or 0) / 100.0 * nb
    return {
        "ok": True,
        "n_buy": int(n_buy) if n_buy == int(n_buy) else n_buy,
        "sum_pnl": sum_pnl,
        "win_rate": (100.0 * win_n / n_buy) if n_buy else 0.0,
    }


def pick_ma_winner(
    sma: dict[str, Any] | None,
    ema: dict[str, Any] | None,
    *,
    close_eps: float = MA_PNL_CLOSE,
) -> dict[str, Any]:
    """SMA vs EMA：盈亏高者胜出；|Δ|≤close_eps 为接近，落地时胜率高者、再平 EMA。"""
    sp = _usable_pnl(sma)
    ep = _usable_pnl(ema)
    out = {
        "winner": "",
        "label": "",
        "why": "",
        "pnl_sma": sp,
        "pnl_ema": ep,
        "pnl_delta": None,
    }
    if sp is None and ep is None:
        return out
    if sp is None:
        out.update({"winner": "EMA", "label": "EMA", "why": "single_ma"})
        return out
    if ep is None:
        out.update({"winner": "SMA", "label": "SMA", "why": "single_ma"})
        return out
    delta = ep - sp
    out["pnl_delta"] = delta
    if abs(sp - ep) <= float(close_eps):
        sw = _usable_win_rate(sma)
        ew = _usable_win_rate(ema)
        if ew > sw:
            winner = "EMA"
        elif sw > ew:
            winner = "SMA"
        else:
            winner = "EMA"
        out.update({"winner": winner, "label": "接近", "why": "compare_close"})
        return out
    winner = "EMA" if ep > sp else "SMA"
    out.update({"winner": winner, "label": winner, "why": "compare"})
    return out


def pair_ma_batch_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """批量行按 (stock, year, dividend_type) 配对 SMA/EMA。"""
    groups: dict[tuple[str, str, str], dict[str, dict[str, Any]]] = {}
    for r in rows:
        ma = normalize_ma_type(r.get("ma_type"))
        if not ma:
            continue
        key = (
            str(r.get("stock") or ""),
            str(r.get("year") or ""),
            str(r.get("dividend_type") or ""),
        )
        groups.setdefault(key, {})[ma] = r
    out: list[dict[str, Any]] = []
    for stock, year, _div in sorted(groups):
        mas = groups[(stock, year, _div)]
        sma = mas.get("SMA")
        ema = mas.get("EMA")
        pick = pick_ma_winner(sma, ema)

        def _g(row: dict[str, Any] | None, field: str) -> Any:
            return None if not row else row.get(field)

        out.append(
            {
                "stock": stock,
                "year": year,
                "dividend_type": _div,
                "ok_sma": bool(sma and sma.get("ok")),
                "ok_ema": bool(ema and ema.get("ok")),
                "n_buy_sma": _g(sma, "n_buy"),
                "n_buy_ema": _g(ema, "n_buy"),
                "sum_pnl_sma": _g(sma, "sum_pnl"),
                "sum_pnl_ema": _g(ema, "sum_pnl"),
                "win_rate_sma": _g(sma, "win_rate"),
                "win_rate_ema": _g(ema, "win_rate"),
                "avg_ret_sma": _g(sma, "avg_ret"),
                "avg_ret_ema": _g(ema, "avg_ret"),
                "max_win_sma": _g(sma, "max_win"),
                "max_win_ema": _g(ema, "max_win"),
                "max_loss_sma": _g(sma, "max_loss"),
                "max_loss_ema": _g(ema, "max_loss"),
                "pnl_delta": pick["pnl_delta"],
                "winner": pick["winner"],
                "label": pick["label"],
                "why": pick["why"],
                "sma_log": _g(sma, "log"),
                "ema_log": _g(ema, "log"),
                "sma_detail": _g(sma, "detail"),
                "ema_detail": _g(ema, "detail"),
                "sma_csv": _g(sma, "csv"),
                "ema_csv": _g(ema, "csv"),
                "budget": _g(sma, "budget") or _g(ema, "budget"),
                "walk_start": _g(sma, "walk_start") or _g(ema, "walk_start"),
                "walk_end": _g(sma, "walk_end") or _g(ema, "walk_end"),
                "error_sma": _g(sma, "error"),
                "error_ema": _g(ema, "error"),
            }
        )
    return out


def ma_compare_dataframe(pairs: list[dict[str, Any]]) -> pd.DataFrame:
    recs = []
    has_year = any(str(r.get("year") or "").strip() for r in pairs)
    has_div = len(unique_dividend_types(pairs)) >= 2
    for r in pairs:
        rec: dict[str, Any] = {"代码": r.get("stock") or ""}
        if has_year:
            rec["年份"] = str(r.get("year") or "")
        if has_div:
            rec["复权"] = dividend_label(r.get("dividend_type")) if r.get("dividend_type") else ""
        rec.update(
            {
                "轮次SMA": r.get("n_buy_sma"),
                "轮次EMA": r.get("n_buy_ema"),
                "盈亏SMA": r.get("sum_pnl_sma"),
                "盈亏EMA": r.get("sum_pnl_ema"),
                "Δ盈亏": r.get("pnl_delta"),
                "胜率SMA": r.get("win_rate_sma"),
                "胜率EMA": r.get("win_rate_ema"),
                "平均%SMA": r.get("avg_ret_sma"),
                "平均%EMA": r.get("avg_ret_ema"),
                "更优": r.get("label") or "",
                "建议": r.get("winner") or "",
            }
        )
        recs.append(rec)
    cols = [
        "代码",
        "轮次SMA",
        "轮次EMA",
        "盈亏SMA",
        "盈亏EMA",
        "Δ盈亏",
        "胜率SMA",
        "胜率EMA",
        "平均%SMA",
        "平均%EMA",
        "更优",
        "建议",
    ]
    if has_div:
        cols = ["代码", "复权"] + [c for c in cols if c != "代码"]
    if has_year:
        rest = [c for c in cols if c != "代码"]
        cols = ["代码", "年份"] + [c for c in rest if c != "年份"]
    df = pd.DataFrame(recs, columns=cols)
    for col in ("轮次SMA", "轮次EMA"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("盈亏SMA", "盈亏EMA", "Δ盈亏", "胜率SMA", "胜率EMA", "平均%SMA", "平均%EMA"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return insert_name_column(df, code_col="代码")


def summarize_ma_compare_by_year(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in pairs:
        y = str(r.get("year") or "").strip() or "?"
        div = normalize_dividend_type(r.get("dividend_type"))
        by_key.setdefault((y, div), []).append(r)
    out: list[dict[str, Any]] = []
    for y, div in sorted(by_key):
        xs = by_key[(y, div)]
        sma_pnl = 0.0
        ema_pnl = 0.0
        n_sma_ok = 0
        n_ema_ok = 0
        for r in xs:
            if r.get("ok_sma") and r.get("sum_pnl_sma") is not None:
                sma_pnl += float(r["sum_pnl_sma"] or 0)
                n_sma_ok += 1
            if r.get("ok_ema") and r.get("sum_pnl_ema") is not None:
                ema_pnl += float(r["sum_pnl_ema"] or 0)
                n_ema_ok += 1
        out.append(
            {
                "year": y,
                "dividend_type": div,
                "n_stock": len(xs),
                "n_ok_sma": n_sma_ok,
                "n_ok_ema": n_ema_ok,
                "sum_pnl_sma": sma_pnl,
                "sum_pnl_ema": ema_pnl,
                "pnl_delta": ema_pnl - sma_pnl,
                "n_sma_win": sum(1 for r in xs if r.get("label") == "SMA"),
                "n_ema_win": sum(1 for r in xs if r.get("label") == "EMA"),
                "n_close": sum(1 for r in xs if r.get("label") == "接近"),
            }
        )
    return out


def ma_compare_year_dataframe(pairs: list[dict[str, Any]]) -> pd.DataFrame:
    recs = []
    agg = summarize_ma_compare_by_year(pairs)
    has_div = len(unique_dividend_types(agg)) >= 2
    for r in agg:
        rec: dict[str, Any] = {"年份": r.get("year") or ""}
        if has_div:
            rec["复权"] = dividend_label(r.get("dividend_type")) if r.get("dividend_type") else ""
        rec.update(
            {
                "标的数": r.get("n_stock"),
                "SMA成功": r.get("n_ok_sma"),
                "EMA成功": r.get("n_ok_ema"),
                "盈亏SMA": r.get("sum_pnl_sma"),
                "盈亏EMA": r.get("sum_pnl_ema"),
                "Δ盈亏": r.get("pnl_delta"),
                "SMA更优": r.get("n_sma_win"),
                "EMA更优": r.get("n_ema_win"),
                "接近": r.get("n_close"),
            }
        )
        recs.append(rec)
    cols = [
        "年份",
        "标的数",
        "SMA成功",
        "EMA成功",
        "盈亏SMA",
        "盈亏EMA",
        "Δ盈亏",
        "SMA更优",
        "EMA更优",
        "接近",
    ]
    if has_div:
        cols = ["年份", "复权"] + [c for c in cols if c != "年份"]
    df = pd.DataFrame(recs, columns=cols)
    for col in ("标的数", "SMA成功", "EMA成功", "SMA更优", "EMA更优", "接近"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("盈亏SMA", "盈亏EMA", "Δ盈亏"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def write_ma_compare_csv(pairs: list[dict[str, Any]], path: str | Path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "stock",
        "year",
        "dividend_type",
        "ok_sma",
        "ok_ema",
        "n_buy_sma",
        "n_buy_ema",
        "sum_pnl_sma",
        "sum_pnl_ema",
        "pnl_delta",
        "win_rate_sma",
        "win_rate_ema",
        "avg_ret_sma",
        "avg_ret_ema",
        "max_win_sma",
        "max_win_ema",
        "max_loss_sma",
        "max_loss_ema",
        "winner",
        "label",
        "why",
        "walk_start",
        "walk_end",
        "budget",
        "error_sma",
        "error_ema",
        "sma_log",
        "ema_log",
        "sma_detail",
        "ema_detail",
        "sma_csv",
        "ema_csv",
    ]
    recs = [{k: r.get(k) for k in fields} for r in pairs]
    pd.DataFrame(recs, columns=fields).to_csv(dest, index=False, encoding="utf-8-sig")
    return dest


def write_ma_compare_year_csv(pairs: list[dict[str, Any]], path: str | Path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "year",
        "dividend_type",
        "n_stock",
        "n_ok_sma",
        "n_ok_ema",
        "sum_pnl_sma",
        "sum_pnl_ema",
        "pnl_delta",
        "n_sma_win",
        "n_ema_win",
        "n_close",
    ]
    recs = [{k: r.get(k) for k in fields} for r in summarize_ma_compare_by_year(pairs)]
    pd.DataFrame(recs, columns=fields).to_csv(dest, index=False, encoding="utf-8-sig")
    return dest


def _load_report_mod():
    spec = importlib.util.spec_from_file_location("qmt_generate_report", REPORT_PY)
    if spec is None or spec.loader is None:
        raise ImportError("cannot load %s" % REPORT_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_REPORT = None
_REPORT_MTIME: float | None = None


def report_mod():
    """加载 generate_report；磁盘 mtime 变化时重载（Streamlit 长会话也能吃到修复）。"""
    global _REPORT, _REPORT_MTIME
    try:
        mtime = float(REPORT_PY.stat().st_mtime)
    except OSError:
        mtime = None
    if _REPORT is None or (mtime is not None and mtime != _REPORT_MTIME):
        if _REPORT is not None and "qmt_generate_report" in sys.modules:
            del sys.modules["qmt_generate_report"]
        _REPORT = _load_report_mod()
        _REPORT_MTIME = mtime
    return _REPORT


def ymd_to_date(s: str) -> date:
    d = compact_day(s)
    if len(d) != 8:
        raise ValueError("bad day: %s" % s)
    return datetime.strptime(d, "%Y%m%d").date()


def date_to_ymd(d: date | datetime | str) -> str:
    if isinstance(d, str):
        return compact_day(d)
    if isinstance(d, datetime):
        return d.strftime("%Y%m%d")
    return d.strftime("%Y%m%d")


def list_daily_csvs(data_dir: str | Path | None = None) -> list[Path]:
    root = Path(data_dir) if data_dir else (REPO / "tools" / "csv")
    if not root.is_dir():
        return []
    return sorted(root.glob("*_1d_*.csv"))


def _prefer_daily_meta(cur: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """同代码多份日线：结束日更新、根数更多、路径名字典序更大者优先。"""
    if other["end"] != cur["end"]:
        return other if other["end"] > cur["end"] else cur
    n_o, n_c = int(other.get("n") or 0), int(cur.get("n") or 0)
    if n_o != n_c:
        return other if n_o > n_c else cur
    p_o, p_c = str(other.get("path") or ""), str(cur.get("path") or "")
    return other if p_o > p_c else cur


def daily_csvs_by_stock(data_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """行情目录按标的去重，每只保留一份最新日线。"""
    by_stock: dict[str, dict[str, Any]] = {}
    for path in list_daily_csvs(data_dir):
        try:
            meta = peek_daily_csv_meta(path)
        except Exception:
            continue
        stock = str(meta.get("stock") or "").strip().upper()
        if not stock:
            continue
        prev = by_stock.get(stock)
        by_stock[stock] = meta if prev is None else _prefer_daily_meta(prev, meta)
    return [by_stock[k] for k in sorted(by_stock)]


def union_date_range(metas: list[dict[str, Any]]) -> tuple[str, str]:
    starts = [compact_day(str(m.get("start") or "")) for m in metas]
    ends = [compact_day(str(m.get("end") or "")) for m in metas]
    starts = [s for s in starts if len(s) == 8]
    ends = [e for e in ends if len(e) == 8]
    if not starts or not ends:
        raise ValueError("empty date range")
    return min(starts), max(ends)


def iter_year_windows(start: str, end: str) -> list[tuple[str, str, str]]:
    """闭区间 [start, end] 按自然年切开。返回 [(year, y_start, y_end), ...]。"""
    s = compact_day(start)
    e = compact_day(end)
    if len(s) != 8 or len(e) != 8:
        raise ValueError("bad range: %s %s" % (start, end))
    if s > e:
        raise ValueError("start after end: %s %s" % (s, e))
    y0 = int(s[:4])
    y1 = int(e[:4])
    out: list[tuple[str, str, str]] = []
    for y in range(y0, y1 + 1):
        ys = s if y == y0 else "%04d0101" % y
        ye = e if y == y1 else "%04d1231" % y
        if ys > ye:
            continue
        out.append((str(y), ys, ye))
    return out


def _overlap_yyyymmdd(a0: str, a1: str, b0: str, b1: str) -> tuple[str, str] | None:
    lo = max(a0, b0)
    hi = min(a1, b1)
    if lo <= hi:
        return lo, hi
    return None


def build_year_jobs(
    metas: list[dict[str, Any]],
    start: str,
    end: str,
) -> list[dict[str, Any]]:
    """标的 × 年；与行情无交集的年跳过。"""
    jobs: list[dict[str, Any]] = []
    for year, ys, ye in iter_year_windows(start, end):
        for meta in metas:
            ms = compact_day(str(meta.get("start") or ""))
            me = compact_day(str(meta.get("end") or ""))
            if len(ms) != 8 or len(me) != 8:
                continue
            ov = _overlap_yyyymmdd(ys, ye, ms, me)
            if ov is None:
                continue
            path = str(meta.get("path") or "")
            if not path:
                continue
            jobs.append(
                {
                    "csv": path,
                    "stock": str(meta.get("stock") or "").strip().upper(),
                    "year": year,
                    "start": ov[0],
                    "end": ov[1],
                }
            )
    return jobs


def list_detail_csvs(
    report_dir: str | Path | list[str | Path] | tuple[str | Path, ...] | None = None,
    *,
    include_hist: bool = True,
) -> list[Path]:
    """已有操作明细：可选回测记录 + 一个或多个 report_dir 下 *_操作明细.csv。"""
    out: list[Path] = []
    if include_hist:
        hist = THEME / "回测记录"
        if hist.is_dir():
            out.extend(sorted(hist.glob("*.csv")))
    if report_dir is None:
        reports = [resolve_typed_dir(DEFAULT_REPORT_ROOT, DEFAULT_DIVIDEND_TYPE)]
    elif isinstance(report_dir, (list, tuple)):
        reports = [Path(x) for x in report_dir]
    else:
        reports = [Path(report_dir)]
    for report in reports:
        if report.is_dir():
            out.extend(sorted(report.glob("*操作明细*.csv")))
            out.extend(sorted(report.glob("*_trades.csv")))
    # 去重保序
    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in out:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        uniq.append(p)
    return uniq


def csv_date_range(csv_path: str | Path, stock: str = "") -> dict[str, Any]:
    """头尾 peek，不物化 OHLCV。stock 参数保留兼容，peek 以文件内代码为准。"""
    _ = stock
    return peek_daily_csv_meta(csv_path)


def ohlc_from_csv(
    csv_path: str | Path,
    start: str = "",
    end: str = "",
    stock: str = "",
) -> pd.DataFrame:
    code, bars = load_daily_csv(csv_path, stock=stock)
    start_d = compact_day(start)
    end_d = compact_day(end)
    rows = []
    for b in bars:
        if start_d and b.day < start_d:
            continue
        if end_d and b.day > end_d:
            continue
        rows.append(
            {
                "Date": pd.Timestamp(b.day),
                "Open": b.open,
                "High": b.high,
                "Low": b.low,
                "Close": b.close,
                "Volume": b.volume,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.set_index("Date").sort_index()


_CHART_MA_CFG: dict[str, Any] | None = None


def load_chart_ma_config(
    config_path: str | Path | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """读 hlband config 的均线周期 / 缺省 MA_TYPE / BOOK_STOCKS。不 import 拼接脚本。"""
    global _CHART_MA_CFG
    if _CHART_MA_CFG is not None and config_path is None and (not force):
        return _CHART_MA_CFG
    out: dict[str, Any] = {
        "ma_type": "EMA",
        "book": {},
        "d_mid": 20,
        "d_slow": 60,
        "w_fast": 5,
        "w_mid": 13,
        "w_life": 34,
    }
    path = Path(config_path) if config_path else HLBAND_CONFIG
    if path.is_file():
        spec = importlib.util.spec_from_file_location("hlband_config_chart", path)
        if spec is not None and spec.loader is not None:
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
                raw_ma = normalize_ma_type(getattr(mod, "MA_TYPE", "EMA"))
                if raw_ma:
                    out["ma_type"] = raw_ma
                for key, attr, default in (
                    ("d_mid", "D_MA_MID", 20),
                    ("d_slow", "D_MA_SLOW", 60),
                    ("w_fast", "W_MA_FAST", 5),
                    ("w_mid", "W_MA_MID", 13),
                    ("w_life", "W_MA_LIFE", 34),
                ):
                    try:
                        out[key] = int(getattr(mod, attr, default) or default)
                    except (TypeError, ValueError):
                        out[key] = default
                book: dict[str, str] = {}
                raw = getattr(mod, "BOOK_STOCKS", None)
                items = []
                if isinstance(raw, dict):
                    items = list(raw.items())
                elif isinstance(raw, (list, tuple)):
                    items = [(str(x), {}) for x in raw]
                for k, v in items:
                    code = str(k or "").strip().upper()
                    if not code:
                        continue
                    if isinstance(v, dict):
                        kind = normalize_ma_type(v.get("ma_type")) or "EMA"
                    elif isinstance(v, str):
                        kind = normalize_ma_type(v) or "EMA"
                    else:
                        kind = "EMA"
                    book[code] = kind
                out["book"] = book
            except Exception:
                pass
    if config_path is None:
        _CHART_MA_CFG = out
    return out


def chart_ma_periods(period: str = "1d") -> list[int]:
    cfg = load_chart_ma_config()
    p = str(period or "1d").strip().lower()
    if p in ("1w", "week", "weekly", "w"):
        return [int(cfg["w_fast"]), int(cfg["w_mid"]), int(cfg["w_life"])]
    return [int(cfg["d_mid"]), int(cfg["d_slow"])]


def ma_kind_from_detail_path(path: str | Path) -> str:
    m = _DETAIL_NAME_RE.match(Path(path).name)
    if m and m.group(4):
        return str(m.group(4)).upper()
    return ""


def resolve_chart_ma_kind(
    stock: str = "",
    detail_path: str | Path | None = None,
    ma_kind: str = "",
) -> str:
    """明细文件名 _(SMA|EMA) → BOOK_STOCKS → 全局 MA_TYPE。"""
    forced = normalize_ma_type(ma_kind)
    if forced:
        return forced
    if detail_path is not None:
        from_name = ma_kind_from_detail_path(detail_path)
        if from_name:
            return from_name
    cfg = load_chart_ma_config()
    code = str(stock or "").strip().upper()
    book = cfg.get("book") or {}
    if code:
        if code in book:
            return str(book[code])
        compact = code.replace("_", ".")
        for k, v in book.items():
            if str(k).strip().upper().replace("_", ".") == compact:
                return str(v)
    return str(cfg.get("ma_type") or "EMA")


def price_ma(closes, n, kind: str = "EMA"):
    """与 hlband/indicators._sma/_ema 相同：EMA 前 n 根用 SMA 播种。"""
    c = np.asarray(closes, dtype=float)
    n = int(n)
    if n <= 0 or len(c) < n:
        return None
    algo = normalize_ma_type(kind) or "EMA"
    out = np.full(len(c), np.nan, dtype=float)
    if algo == "SMA":
        cs = np.cumsum(c)
        out[n - 1] = cs[n - 1] / float(n)
        if len(c) > n:
            out[n:] = (cs[n:] - cs[:-n]) / float(n)
        return out
    alpha = 2.0 / (n + 1.0)
    out[n - 1] = float(np.mean(c[:n]))
    for i in range(n, len(c)):
        out[i] = alpha * c[i] + (1.0 - alpha) * out[i - 1]
    return out


def _bars_to_ohlc(bars) -> pd.DataFrame:
    rows = []
    for b in bars:
        rows.append(
            {
                "Date": pd.Timestamp(b.day),
                "Open": b.open,
                "High": b.high,
                "Low": b.low,
                "Close": b.close,
                "Volume": b.volume,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.set_index("Date").sort_index()


def _is_weekly_period(period: str) -> bool:
    return str(period or "1d").strip().lower() in ("1w", "week", "weekly", "w")


def map_day_to_bar(
    ohlc: pd.DataFrame,
    day_raw: Any,
    period: str = "1d",
):
    """日线：最近一根；周线：同一自然周（周一为一周）的那根周 K。区间外 None。"""
    digits = "".join(ch for ch in str(day_raw or "") if ch.isdigit())
    if len(digits) < 8 or ohlc is None or ohlc.empty:
        return None
    d = pd.Timestamp(digits[:8])
    idx = pd.DatetimeIndex(pd.to_datetime(ohlc.index).normalize())
    if _is_weekly_period(period):
        want = week_monday(digits[:8])
        for ts in ohlc.index:
            bar_d = pd.Timestamp(ts).strftime("%Y%m%d")
            if week_monday(bar_d) == want:
                return ts
        return None
    if d < idx[0] or d > idx[-1]:
        return None
    if d in idx:
        loc = idx.get_loc(d)
        return ohlc.index[int(loc) if not isinstance(loc, slice) else loc.start]
    pos = int(idx.searchsorted(d))
    if pos >= len(idx):
        return None
    if pos == 0:
        return ohlc.index[0]
    a, b = idx[pos - 1], idx[pos]
    pick = a if abs((a - d).days) <= abs((b - d).days) else b
    loc = idx.get_loc(pick)
    return ohlc.index[int(loc) if not isinstance(loc, slice) else loc.start]


def ohlc_frame_for_chart(
    csv_path: str | Path,
    start: str = "",
    end: str = "",
    stock: str = "",
    period: str = "1d",
    ma_kind: str = "",
    detail_path: str | Path | None = None,
) -> pd.DataFrame:
    """日/周 OHLC + MA 列。均线在切可见区间前用历史暖机。"""
    code, dailies = load_daily_csv(csv_path, stock=stock)
    kind = resolve_chart_ma_kind(stock=code or stock, detail_path=detail_path, ma_kind=ma_kind)
    start_d = compact_day(start)
    end_d = compact_day(end)
    weekly = _is_weekly_period(period)
    if weekly:
        wpath = find_weekly_csv(csv_path, stock=code or stock)
        if wpath is not None:
            _c, bars = load_weekly_csv(wpath, stock=code or stock)
        else:
            bars = aggregate_weekly(dailies, drop_forming=False)
    else:
        bars = dailies
    if end_d:
        bars = [b for b in bars if b.day <= end_d]
    df = _bars_to_ohlc(bars)
    if df.empty:
        return df
    closes = df["Close"].to_numpy(dtype=float)
    for n in chart_ma_periods("1w" if weekly else "1d"):
        arr = price_ma(closes, n, kind)
        col = "MA%d" % int(n)
        if arr is None:
            df[col] = np.nan
        else:
            df[col] = arr
    if start_d:
        df = df[df.index >= pd.Timestamp(start_d)].copy()
    df.attrs["ma_kind"] = kind
    df.attrs["period"] = "1w" if weekly else "1d"
    return df


def _normalize_trades(rounds: list[dict]) -> list[dict]:
    trades = []
    for i, r in enumerate(rounds, 1):
        t = dict(r)
        t.setdefault("i", i)
        t.setdefault("buy_signal", "-")
        t.setdefault("sell_signal", "-")
        t.setdefault("buy_label", t.get("buy_signal", "-"))
        t.setdefault("sell_label", t.get("sell_signal", "-"))
        t.setdefault("buy_signal_day", t.get("buy_open_day"))
        t.setdefault("sell_signal_day", t.get("sell_exec_day"))
        if "is_add" not in t:
            t["is_add"] = False
        if "hold_calendar_days" not in t:
            try:
                b = datetime.strptime(str(t["buy_open_day"])[:8], "%Y%m%d")
                s = datetime.strptime(str(t["sell_exec_day"])[:8], "%Y%m%d")
                t["hold_calendar_days"] = (s - b).days
            except Exception:
                t["hold_calendar_days"] = None
        trades.append(t)
    return trades


def _label_is_add(label: Any) -> bool:
    return "加仓" in str(label or "")


def add_stats_from_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """从轮次统计加仓次数 / 胜率 / 盈亏 / 收益% 极值。"""
    adds = [t for t in trades if t.get("is_add")]
    n_add = len(adds)
    win_n = sum(1 for t in adds if float(t.get("pnl") or 0) > 0)
    pnls = [float(t.get("pnl") or 0) for t in adds]
    rets = [float(t.get("ret_pct") or 0) for t in adds]
    return {
        "n_add": n_add,
        "add_win_n": win_n,
        "add_win_rate": round(win_n / n_add * 100, 1) if n_add else 0.0,
        "add_sum_pnl": round(sum(pnls), 2) if pnls else 0.0,
        "add_avg_ret": round(sum(rets) / len(rets), 2) if rets else 0.0,
        "add_max_win": round(max(rets), 2) if rets else 0.0,
        "add_max_loss": round(min(rets), 2) if rets else 0.0,
    }


def mark_add_lots(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """补全 is_add：label 含「加仓」；其余用同标的重叠持仓兜底。"""
    if not trades:
        return trades
    out: list[dict[str, Any]] = [dict(t) for t in trades]
    for t in out:
        if t.get("is_add"):
            continue
        if _label_is_add(t.get("buy_label")):
            t["is_add"] = True
    # 重叠持仓兜底：B 买入日严格落在 A 持仓区间内（bj < bi < sj）→ B 为加仓
    by_stock: dict[str, list[int]] = {}
    for i, t in enumerate(out):
        code = _norm_signal_stock(str(t.get("stock") or ""))
        by_stock.setdefault(code, []).append(i)
    for idxs in by_stock.values():
        for i in idxs:
            ti = out[i]
            if ti.get("is_add"):
                continue
            bi = compact_day(str(ti.get("buy_open_day") or ""))
            if not bi:
                continue
            for j in idxs:
                if i == j:
                    continue
                tj = out[j]
                bj = compact_day(str(tj.get("buy_open_day") or ""))
                sj = compact_day(str(tj.get("sell_exec_day") or ""))
                if not bj or not sj:
                    continue
                if bj < bi < sj:
                    ti["is_add"] = True
                    break
    return out


def parse_budget_from_log(log_path: str | Path | None, default: float = 50000.0) -> float:
    if not log_path:
        return float(default)
    p = Path(log_path)
    if not p.is_file():
        return float(default)
    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"budget=\s*([0-9.]+)", text)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return float(default)


def load_detail_raw(path: str | Path) -> pd.DataFrame:
    mod = report_mod()
    return mod._read_csv_auto(Path(path))


def sibling_log_path(detail_path: str | Path) -> Path | None:
    """操作明细旁的同名 .txt log（local_bt_*_操作明细.csv → local_bt_*.txt）。"""
    path = Path(detail_path)
    name = path.name
    if name.endswith("_操作明细.csv"):
        cand = path.with_name(name[: -len("_操作明细.csv")] + ".txt")
        if cand.is_file():
            return cand
    return None


def _norm_signal_stock(raw: str) -> str:
    s = str(raw or "").strip().upper()
    if not s:
        return ""
    s = s.split(".", 1)[0]
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".", 1)[0]
    if s.isdigit():
        s = s.zfill(6)
    return s


def parse_fill_signals_from_log(log_text: str) -> list[dict[str, Any]]:
    """从 local_bt log 提取买卖信号。

    买：BUY filled / BUY add filled
    卖：SELL <reason> <code> xN（含部分卖出）；SELL done 补 open_day
    """
    pending_buy: dict[str, Any] | None = None
    pending_sell: dict[str, Any] | None = None
    pending_stock = ""
    events: list[dict[str, Any]] = []
    for line in str(log_text or "").splitlines():
        m = re.search(
            r"BUY(?: add)? by signal=(\S+)\s+label=(\S+).*?(?:signal_day=(\d+)|@close=)",
            line,
        )
        if m:
            pending_buy = {
                "signal": m.group(1),
                "label": m.group(2),
                "day": str(m.group(3) or "")[:8],
            }
            pending_stock = ""
            continue
        m = re.search(r"(?:BUY(?: add)?|ADD) BUY (\S+)\s+x(\d+)", line)
        if m:
            pending_stock = _norm_signal_stock(m.group(1))
            continue
        # 首开：BUY filled {..., 'opened_at': '...'}
        m = re.search(
            r"BUY filled \{'shares': (\d+),[^}]*'opened_at': '(\d+)'",
            line,
        )
        if m and pending_buy:
            label = pending_buy.get("label") or pending_buy.get("signal") or "-"
            events.append(
                {
                    "kind": "buy",
                    "shares": int(m.group(1)),
                    "day": str(m.group(2))[:8],
                    "stock": pending_stock,
                    "signal": pending_buy.get("signal") or "-",
                    "label": label,
                    "is_add": False,
                }
            )
            pending_buy = None
            pending_stock = ""
            continue
        # 加仓：BUY add filled {'add_shares': N, ...}（无 opened_at，用 signal_day）
        m = re.search(r"BUY add filled \{'add_shares': (\d+)", line)
        if m and pending_buy:
            day = str(pending_buy.get("day") or "")[:8]
            label = pending_buy.get("label") or pending_buy.get("signal") or "-"
            events.append(
                {
                    "kind": "buy",
                    "shares": int(m.group(1)),
                    "day": day,
                    "stock": pending_stock,
                    "signal": pending_buy.get("signal") or "-",
                    "label": label,
                    "is_add": True,
                }
            )
            pending_buy = None
            pending_stock = ""
            continue
        m = re.search(
            r"SELL by signal=(\S+)\s+label=(\S+).*?(?:signal_day=(\d+)|@close=)",
            line,
        )
        if m:
            day = str(m.group(3) or "")[:8]
            pending_sell = {
                "signal": m.group(1),
                "label": m.group(2),
                "day": day,
            }
            continue
        # 实际卖出成交（含 partial）：SELL trail_stop 600350.SH x9400
        m = re.search(r"SELL (\S+) (\S+)\s+x(\d+)", line)
        if m and m.group(1) not in ("by", "done", "lot-can_use"):
            reason = m.group(1)
            stock = _norm_signal_stock(m.group(2))
            shares = int(m.group(3))
            sig = (pending_sell or {}).get("signal") or reason
            label = (pending_sell or {}).get("label") or reason
            day = str((pending_sell or {}).get("day") or "")[:8]
            events.append(
                {
                    "kind": "sell",
                    "shares": shares,
                    "day": day,
                    "open_day": "",
                    "stock": stock,
                    "signal": sig,
                    "label": label,
                }
            )
            continue
        m = re.search(
            r"SELL done (\S+)\s+last=\s*[0-9.]+\s+cleared \{'shares': (\d+),[^}]*'opened_at': '(\d+)'",
            line,
        )
        if m:
            sig = m.group(1)
            shares = int(m.group(2))
            open_day = str(m.group(3))[:8]
            label = (pending_sell or {}).get("label") or sig
            if pending_sell and pending_sell.get("signal"):
                sig = str(pending_sell.get("signal") or sig)
            stock = pending_stock
            filled = False
            for e in reversed(events):
                if e.get("kind") != "sell":
                    continue
                if int(e.get("shares") or 0) != shares:
                    continue
                if e.get("stock") and stock and e.get("stock") != stock:
                    continue
                if not e.get("open_day"):
                    e["open_day"] = open_day
                    if not e.get("stock") and stock:
                        e["stock"] = stock
                    filled = True
                    break
            if not filled:
                events.append(
                    {
                        "kind": "sell",
                        "shares": shares,
                        "day": str((pending_sell or {}).get("day") or "")[:8],
                        "open_day": open_day,
                        "stock": stock,
                        "signal": sig,
                        "label": label,
                    }
                )
            pending_sell = None
            pending_stock = ""
            continue
    return events


def enrich_trades_signals_from_log(
    trades: list[dict[str, Any]],
    log_path: str | Path | None,
) -> list[dict[str, Any]]:
    """把 log 信号填回成交轮次。

    两遍匹配：先精确股数，再宽松回退，避免同日小仓轮次抢走大仓信号。
    买：代码+日+股数 → 代码+日（可共享）→ 日+股数
    卖：卖出日+股数 → open_day+股数 → 卖出日+代码（可共享）
    """
    if not trades or not log_path:
        return trades
    path = Path(log_path)
    if not path.is_file():
        return trades
    events = parse_fill_signals_from_log(path.read_text(encoding="utf-8", errors="replace"))
    if not events:
        return trades
    buys = [e for e in events if e.get("kind") == "buy"]
    sells = [e for e in events if e.get("kind") == "sell"]
    used_b = [False] * len(buys)
    used_s = [False] * len(sells)
    out: list[dict[str, Any]] = [dict(t) for t in trades]

    def _keys(t: dict[str, Any]) -> tuple[str, str, int, str]:
        return (
            compact_day(str(t.get("buy_open_day") or "")),
            compact_day(str(t.get("sell_exec_day") or "")),
            int(t.get("shares") or 0),
            str(t.get("stock") or ""),
        )

    def _buy_exact(day: str, shares: int, stock: str) -> dict[str, Any] | None:
        code = _norm_signal_stock(stock)
        if not code or not day:
            return None
        for i, e in enumerate(buys):
            if used_b[i]:
                continue
            if e.get("day") == day and int(e.get("shares") or 0) == shares and e.get("stock") == code:
                used_b[i] = True
                return e
        return None

    def _buy_loose(day: str, shares: int, stock: str) -> dict[str, Any] | None:
        """同日同代码可共享买入信号（FIFO 拆仓无独立 BUY filled）。"""
        code = _norm_signal_stock(stock)
        if code and day:
            for e in buys:
                if e.get("day") == day and e.get("stock") == code:
                    return e
            # 已精确占用过的同日事件也允许回读
            for nt0 in out:
                if _norm_signal_stock(str(nt0.get("stock") or "")) != code:
                    continue
                if compact_day(str(nt0.get("buy_open_day") or "")) != day:
                    continue
                sig = nt0.get("buy_signal")
                if sig and sig not in ("-", ""):
                    return {
                        "signal": sig,
                        "label": nt0.get("buy_label") or sig,
                        "is_add": bool(nt0.get("is_add")),
                    }
        if day:
            for i, e in enumerate(buys):
                if used_b[i]:
                    continue
                if e.get("day") == day and int(e.get("shares") or 0) == shares:
                    used_b[i] = True
                    return e
        return None

    def _sell_exact(sell_day: str, buy_day: str, shares: int, stock: str) -> dict[str, Any] | None:
        code = _norm_signal_stock(stock)
        if sell_day:
            for i, e in enumerate(sells):
                if used_s[i]:
                    continue
                if e.get("day") == sell_day and int(e.get("shares") or 0) == shares:
                    if not code or not e.get("stock") or e.get("stock") == code:
                        used_s[i] = True
                        return e
        if buy_day:
            for i, e in enumerate(sells):
                if used_s[i]:
                    continue
                if str(e.get("open_day") or "") == buy_day and int(e.get("shares") or 0) == shares:
                    if not code or not e.get("stock") or e.get("stock") == code:
                        used_s[i] = True
                        return e
        return None

    def _sell_loose(sell_day: str, stock: str) -> dict[str, Any] | None:
        """同日同代码可共享卖出信号（一笔卖拆多 lot 时股数对不上 SELL xN）。"""
        code = _norm_signal_stock(stock)
        if not (sell_day and code):
            return None
        for e in sells:
            if e.get("day") == sell_day and e.get("stock") == code:
                return e
        for nt0 in out:
            if _norm_signal_stock(str(nt0.get("stock") or "")) != code:
                continue
            if compact_day(str(nt0.get("sell_exec_day") or "")) != sell_day:
                continue
            sig = nt0.get("sell_signal")
            if sig and sig not in ("-", ""):
                return {
                    "signal": sig,
                    "label": nt0.get("sell_label") or sig,
                }
        return None

    # pass1: 精确股数
    for nt in out:
        buy_day, sell_day, sh, stock = _keys(nt)
        b = _buy_exact(buy_day, sh, stock)
        if b:
            nt["buy_signal"] = b.get("signal") or nt.get("buy_signal") or "-"
            nt["buy_label"] = b.get("label") or nt.get("buy_label") or nt["buy_signal"]
            if "is_add" in b:
                nt["is_add"] = bool(b.get("is_add"))
            elif _label_is_add(nt["buy_label"]):
                nt["is_add"] = True
        s = _sell_exact(sell_day, buy_day, sh, stock)
        if s:
            nt["sell_signal"] = s.get("signal") or nt.get("sell_signal") or "-"
            nt["sell_label"] = s.get("label") or nt.get("sell_label") or nt["sell_signal"]

    # pass2: 宽松回退（仅仍缺信号的轮次）
    for nt in out:
        buy_day, sell_day, sh, stock = _keys(nt)
        if not nt.get("buy_signal") or nt.get("buy_signal") in ("-", ""):
            b = _buy_loose(buy_day, sh, stock)
            if b:
                nt["buy_signal"] = b.get("signal") or "-"
                nt["buy_label"] = b.get("label") or nt["buy_signal"]
                if "is_add" in b:
                    nt["is_add"] = bool(b.get("is_add"))
                elif _label_is_add(nt["buy_label"]):
                    nt["is_add"] = True
        elif not nt.get("is_add") and _label_is_add(nt.get("buy_label")):
            nt["is_add"] = True
        if not nt.get("sell_signal") or nt.get("sell_signal") in ("-", ""):
            s = _sell_loose(sell_day, stock)
            if s:
                nt["sell_signal"] = s.get("signal") or "-"
                nt["sell_label"] = s.get("label") or nt["sell_signal"]
    return out


def infer_dividend_type_from_path(path: str | Path | None) -> str:
    """从路径段推断复权类型（如 report/front_ratio/...）；找不到则默认。"""
    if not path:
        return DEFAULT_DIVIDEND_TYPE
    p = Path(path)
    d = dividend_from_detail_path(p)
    if d:
        return d
    for part in p.parts:
        x = normalize_dividend_type(part)
        if x:
            return x
    return DEFAULT_DIVIDEND_TYPE


def hold_max_dd_from_closes(closes: list[float] | tuple[float, ...]) -> float | None:
    """持仓区间收盘价峰值回撤，返回百分比（≤0）；不足 2 根有效 K 则 None。"""
    vals: list[float] = []
    for c in closes or []:
        try:
            v = float(c)
        except (TypeError, ValueError):
            continue
        if v > 0 and np.isfinite(v):
            vals.append(v)
    if len(vals) < 2:
        return None
    peak = vals[0]
    worst = 0.0
    for c in vals:
        peak = max(peak, c)
        worst = min(worst, c / peak - 1.0)
    return round(worst * 100.0, 4)


def hold_max_up_from_highs(
    highs: list[float] | tuple[float, ...],
    buy_price: float,
) -> float | None:
    """持仓区间最高价相对买价的最大浮盈（MFE），返回百分比（≥0）。"""
    try:
        bp = float(buy_price)
    except (TypeError, ValueError):
        return None
    if bp <= 0 or not np.isfinite(bp):
        return None
    vals: list[float] = []
    for h in highs or []:
        try:
            v = float(h)
        except (TypeError, ValueError):
            continue
        if v > 0 and np.isfinite(v):
            vals.append(v)
    if not vals:
        return None
    return round((max(vals) / bp - 1.0) * 100.0, 4)


def enrich_trades_hold_metrics(
    trades: list[dict[str, Any]],
    csv_root: str | Path | None = None,
    dividend_type: str = "",
    *,
    detail_path: str | Path | None = None,
    default_stock: str = "",
) -> list[dict[str, Any]]:
    """为每笔轮次填 hold_max_dd / hold_max_up；缺行情则 None。"""
    if not trades:
        return trades
    root = Path(csv_root) if csv_root else DEFAULT_CSV_ROOT
    div = normalize_dividend_type(dividend_type)
    if not div:
        div = infer_dividend_type_from_path(detail_path)
    csv_dir = resolve_typed_dir(root, div)
    fallback = str(default_stock or "").strip().upper()
    if not fallback and detail_path:
        fallback = stock_from_detail_path(detail_path, read_csv=True)

    groups: dict[str, list[tuple[int, str, str]]] = {}
    out: list[dict[str, Any]] = [dict(t) for t in trades]
    for i, t in enumerate(out):
        t.setdefault("hold_max_dd", None)
        t.setdefault("hold_max_up", None)
        stock = str(t.get("stock") or "").strip().upper() or fallback
        buy_d = compact_day(str(t.get("buy_open_day") or ""))
        sell_d = compact_day(str(t.get("sell_exec_day") or ""))
        if not stock or not buy_d or not sell_d:
            continue
        groups.setdefault(stock, []).append((i, buy_d, sell_d))

    # stock -> day -> (close, high)
    ohlc_by_stock: dict[str, dict[str, tuple[float, float]]] = {}
    for stock, items in groups.items():
        start = min(b for _i, b, _s in items)
        end = max(s for _i, _b, s in items)
        path = daily_csv_for_stock(csv_dir, stock)
        if path is None or not path.is_file():
            continue
        try:
            df = ohlc_from_csv(path, start=start, end=end, stock="")
        except Exception:
            continue
        if df is None or df.empty or "Close" not in df.columns:
            continue
        m: dict[str, tuple[float, float]] = {}
        for ts, row in df.iterrows():
            if hasattr(ts, "strftime"):
                day = ts.strftime("%Y%m%d")
            else:
                day = compact_day(str(ts))
            try:
                c = float(row["Close"])
            except (TypeError, ValueError, KeyError):
                continue
            if not (day and c > 0 and np.isfinite(c)):
                continue
            high = c
            if "High" in df.columns:
                try:
                    hv = float(row["High"])
                    if hv > 0 and np.isfinite(hv):
                        high = hv
                except (TypeError, ValueError, KeyError):
                    pass
            m[day] = (c, high)
        if m:
            ohlc_by_stock[stock] = m

    for stock, items in groups.items():
        cmap = ohlc_by_stock.get(stock) or {}
        if not cmap:
            continue
        days_sorted = sorted(cmap.keys())
        for i, buy_d, sell_d in items:
            closes = [cmap[d][0] for d in days_sorted if buy_d <= d <= sell_d]
            highs = [cmap[d][1] for d in days_sorted if buy_d <= d <= sell_d]
            out[i]["hold_max_dd"] = hold_max_dd_from_closes(closes)
            try:
                bp = float(out[i].get("buy_price") or 0)
            except (TypeError, ValueError):
                bp = 0.0
            out[i]["hold_max_up"] = hold_max_up_from_highs(highs, bp)
    return out


def enrich_trades_hold_mdd(
    trades: list[dict[str, Any]],
    csv_root: str | Path | None = None,
    dividend_type: str = "",
    *,
    detail_path: str | Path | None = None,
    default_stock: str = "",
) -> list[dict[str, Any]]:
    """兼容旧名 → enrich_trades_hold_metrics。"""
    return enrich_trades_hold_metrics(
        trades,
        csv_root=csv_root,
        dividend_type=dividend_type,
        detail_path=detail_path,
        default_stock=default_stock,
    )


def enrich_detail_raw_hold_metrics(
    raw_df: pd.DataFrame,
    trades: list[dict[str, Any]],
) -> pd.DataFrame:
    """把轮次持有回撤/浮盈填到原始操作明细的卖出行；买入行标是否加仓。"""
    if raw_df is None:
        return pd.DataFrame()
    out = raw_df.copy()
    out["持有回撤%"] = None
    out["持有浮盈%"] = None
    out["是否加仓"] = None
    if out.empty:
        return out

    c_time = None
    c_side = None
    c_shares = None
    c_code = None
    for col in out.columns:
        s = str(col).strip()
        if s in ("操作时间", "成交时间", "时间") and c_time is None:
            c_time = col
        elif s in ("操作类型", "买卖方向", "方向") and c_side is None:
            c_side = col
        elif s in ("数量", "成交数量", "股数") and c_shares is None:
            c_shares = col
        elif s in ("代码", "证券代码", "股票代码", "标的") and c_code is None:
            c_code = col
    if c_time is None or c_side is None:
        return out

    # pool of unused trades for matching sells / add buys
    pool = [dict(t) for t in (trades or [])]
    used = [False] * len(pool)
    add_pool = [dict(t) for t in (trades or []) if t.get("is_add")]
    used_add = [False] * len(add_pool)

    def _pick(code: str, sell_day: str, shares: int) -> dict[str, Any] | None:
        code_n = _norm_signal_stock(code)
        # 1) code + day + shares
        for i, t in enumerate(pool):
            if used[i]:
                continue
            if compact_day(str(t.get("sell_exec_day") or "")) != sell_day:
                continue
            if int(t.get("shares") or 0) != shares:
                continue
            ts = _norm_signal_stock(str(t.get("stock") or ""))
            if code_n and ts and ts != code_n:
                continue
            used[i] = True
            return t
        # 2) code + day
        for i, t in enumerate(pool):
            if used[i]:
                continue
            if compact_day(str(t.get("sell_exec_day") or "")) != sell_day:
                continue
            ts = _norm_signal_stock(str(t.get("stock") or ""))
            if code_n and ts and ts != code_n:
                continue
            if code_n and not ts:
                continue
            if code_n and ts == code_n:
                used[i] = True
                return t
            if not code_n:
                used[i] = True
                return t
        return None

    def _pick_add_buy(code: str, buy_day: str, shares: int) -> bool:
        code_n = _norm_signal_stock(code)
        for i, t in enumerate(add_pool):
            if used_add[i]:
                continue
            if compact_day(str(t.get("buy_open_day") or "")) != buy_day:
                continue
            if shares and int(t.get("shares") or 0) != shares:
                continue
            ts = _norm_signal_stock(str(t.get("stock") or ""))
            if code_n and ts and ts != code_n:
                continue
            used_add[i] = True
            return True
        # 宽松：同日同代码加仓
        for t in add_pool:
            if compact_day(str(t.get("buy_open_day") or "")) != buy_day:
                continue
            ts = _norm_signal_stock(str(t.get("stock") or ""))
            if code_n and ts and ts != code_n:
                continue
            return True
        return False

    for idx, row in out.iterrows():
        side_raw = str(row[c_side]).strip() if c_side is not None else ""
        day = compact_day(str(row[c_time]))
        if not day:
            continue
        code = ""
        if c_code is not None and pd.notna(row[c_code]):
            code = str(row[c_code]).strip()
        shares = 0
        if c_shares is not None and pd.notna(row[c_shares]):
            try:
                shares = int(float(row[c_shares]))
            except (TypeError, ValueError):
                shares = 0
        if "买" in side_raw:
            out.at[idx, "是否加仓"] = "是" if _pick_add_buy(code, day, shares) else "否"
            continue
        if "卖" not in side_raw:
            continue
        t = _pick(code, day, shares)
        if not t:
            continue
        out.at[idx, "持有回撤%"] = t.get("hold_max_dd")
        out.at[idx, "持有浮盈%"] = t.get("hold_max_up")
    return out


def analyze_detail(
    detail_path: str | Path,
    budget: float = 50000.0,
    meta: dict | None = None,
    log_path: str | Path | None = None,
    csv_root: str | Path | None = None,
    dividend_type: str = "",
    *,
    hold_metrics: bool = True,
) -> dict[str, Any]:
    """操作明细 → trades / equity / stats；旁路 log 可补买卖信号；行情可补持有回撤/浮盈。

    hold_metrics=False 时跳过日线 enrich，并 quiet 解析警告（扫描/打分 KPI 用，显著加速）。
    """
    mod = report_mod()
    path = Path(detail_path)
    # 批量扫数千明细时，每条 open-buy warn 刷 Streamlit 终端会拖慢数量级
    rounds = mod.parse_terminal_rounds(path, quiet=(not hold_metrics))
    trades = _normalize_trades(rounds)
    log = Path(log_path) if log_path else sibling_log_path(path)
    trades = enrich_trades_signals_from_log(trades, log)
    trades = mark_add_lots(trades)
    meta_d = meta or {
        "tag": "HlBand",
        "ver": "local",
        "stock": "?",
        "period": "1d",
        "budget": float(budget),
    }
    if "budget" not in meta_d:
        meta_d["budget"] = float(budget)
    if hold_metrics:
        default_stock = str(meta_d.get("stock") or "")
        if default_stock in ("?", ""):
            default_stock = stock_from_detail_path(path, read_csv=True)
        trades = enrich_trades_hold_metrics(
            trades,
            csv_root=csv_root,
            dividend_type=dividend_type,
            detail_path=path,
            default_stock=default_stock,
        )
    stats = mod.compute_stats(meta_d, trades, diag={}, price_info={"source": "terminal", "terminal_csv": str(path)})
    stats.update(add_stats_from_trades(trades))
    eq = mod.equity_curve(trades, float(budget))
    return {
        "path": str(path.resolve()),
        "trades": trades,
        "stats": stats,
        "equity": eq,
        "budget": float(budget),
        "sum_pnl_detail": float(stats.get("sum_pnl") or 0.0),
        "log_path": str(log) if log and Path(log).is_file() else "",
    }


def filter_trades_by_range(
    trades: list[dict],
    start: str = "",
    end: str = "",
) -> list[dict]:
    start_d = compact_day(start)
    end_d = compact_day(end)
    out = []
    for t in trades:
        d = compact_day(str(t.get("sell_exec_day") or t.get("buy_open_day") or ""))
        if not d:
            continue
        if start_d and d < start_d:
            continue
        if end_d and d > end_d:
            continue
        out.append(t)
    return _normalize_trades(out)


def trades_to_dataframe(trades: list[dict]) -> pd.DataFrame:
    eng_cols = [
        "i",
        "stock",
        "buy_open_day",
        "sell_exec_day",
        "buy_price",
        "sell_price",
        "shares",
        "cost",
        "pnl",
        "ret_pct",
        "hold_calendar_days",
        "hold_max_dd",
        "hold_max_up",
        "is_add",
        "buy_signal",
        "sell_signal",
    ]
    if not trades:
        empty = pd.DataFrame(columns=eng_cols)
        return insert_name_column(rename_columns(empty, TRADES_DISPLAY_COLUMNS), code_col="代码")
    rows = []
    for t in trades:
        row = {c: t.get(c) for c in eng_cols}
        row["is_add"] = "是" if t.get("is_add") else "否"
        rows.append(row)
    out = rename_columns(pd.DataFrame(rows), TRADES_DISPLAY_COLUMNS)
    if "代码" in out.columns and out["代码"].notna().any():
        return insert_name_column(out, code_col="代码")
    # 单票明细无 stock 字段时去掉空代码列
    if "代码" in out.columns and out["代码"].isna().all():
        out = out.drop(columns=["代码"])
    return out


def summarize_detail(
    detail_path: str | Path,
    budget: float = 50000.0,
    stock: str = "",
) -> dict[str, Any]:
    """操作明细 → 汇总表一行用的 KPI。"""
    result = analyze_detail(
        detail_path,
        budget=budget,
        meta={
            "tag": "HlBand",
            "ver": "local",
            "stock": stock or "?",
            "period": "1d",
            "budget": float(budget),
        },
        hold_metrics=False,
    )
    stats = result["stats"] or {}
    return {
        "n_buy": int(stats.get("n_buy") or 0),
        "sum_pnl": float(stats.get("sum_pnl") or 0.0),
        "win_rate": float(stats.get("win_rate") or 0.0),
        "avg_ret": float(stats.get("avg_ret") or 0.0),
        "max_win": float(stats.get("max_win") or 0.0),
        "max_loss": float(stats.get("max_loss") or 0.0),
        "n_add": int(stats.get("n_add") or 0),
        "add_win_rate": float(stats.get("add_win_rate") or 0.0),
        "add_sum_pnl": float(stats.get("add_sum_pnl") or 0.0),
        "add_avg_ret": float(stats.get("add_avg_ret") or 0.0),
        "add_max_win": float(stats.get("add_max_win") or 0.0),
        "add_max_loss": float(stats.get("add_max_loss") or 0.0),
    }


def summarize_batch_row(row: dict[str, Any]) -> dict[str, Any]:
    """把 run_batch 一行补上 KPI / 中文状态。"""
    out = dict(row)
    _kpi_none = (
        "n_buy",
        "sum_pnl",
        "win_rate",
        "avg_ret",
        "max_win",
        "max_loss",
        "n_add",
        "add_win_rate",
        "add_sum_pnl",
        "add_avg_ret",
        "add_max_win",
        "add_max_loss",
    )
    if not out.get("ok"):
        out["status"] = "失败"
        for k in _kpi_none:
            out.setdefault(k, None)
        return out
    detail = out.get("detail") or ""
    try:
        kpi = summarize_detail(
            detail,
            budget=float(out.get("budget") or 50000.0),
            stock=str(out.get("stock") or ""),
        )
        out.update(kpi)
        out["status"] = "成功"
    except Exception as e:
        out["ok"] = False
        out["status"] = "失败"
        out["error"] = "analyze: %s" % e
        for k in _kpi_none:
            out.setdefault(k, None)
    return out


def batch_summary_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    recs = []
    has_year = any(str(r.get("year") or "").strip() for r in rows)
    has_div = len(unique_dividend_types(rows)) >= 2
    has_ma = any(normalize_ma_type(r.get("ma_type")) for r in rows)
    for r in rows:
        walk_s = compact_day(str(r.get("walk_start") or ""))
        walk_e = compact_day(str(r.get("walk_end") or ""))
        walk = ""
        if walk_s or walk_e:
            walk = "%s–%s" % (walk_s or "?", walk_e or "?")
        rec: dict[str, Any] = {"代码": r.get("stock") or ""}
        if has_year:
            rec["年份"] = str(r.get("year") or "")
        if has_div:
            rec["复权"] = dividend_label(r.get("dividend_type")) if r.get("dividend_type") else ""
        ma = normalize_ma_type(r.get("ma_type"))
        if has_ma:
            rec["均线"] = ma or ""
        rec.update(
            {
                "状态": r.get("status") or ("成功" if r.get("ok") else "失败"),
                "walk 区间": walk,
                "轮次": r.get("n_buy"),
                "总盈亏": r.get("sum_pnl"),
                "胜率": r.get("win_rate"),
                "平均收益%": r.get("avg_ret"),
                "最大单笔%": r.get("max_win"),
                "最大亏损%": r.get("max_loss"),
                "加仓次数": r.get("n_add"),
                "加仓总盈亏": r.get("add_sum_pnl"),
                "加仓胜率": r.get("add_win_rate"),
                "加仓平均收益%": r.get("add_avg_ret"),
                "加仓最大单笔%": r.get("add_max_win"),
                "加仓最大亏损%": r.get("add_max_loss"),
                "说明": r.get("error") or "",
            }
        )
        recs.append(rec)
    cols = ["代码"]
    if has_year:
        cols.append("年份")
    if has_div:
        cols.append("复权")
    if has_ma:
        cols.append("均线")
    cols += [
        "状态",
        "walk 区间",
        "轮次",
        "总盈亏",
        "胜率",
        "平均收益%",
        "最大单笔%",
        "最大亏损%",
        "加仓次数",
        "加仓总盈亏",
        "加仓胜率",
        "加仓平均收益%",
        "加仓最大单笔%",
        "加仓最大亏损%",
        "说明",
    ]
    df = pd.DataFrame(recs, columns=cols)
    for col in ("轮次", "加仓次数"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in (
        "总盈亏",
        "胜率",
        "平均收益%",
        "最大单笔%",
        "最大亏损%",
        "加仓胜率",
        "加仓总盈亏",
        "加仓平均收益%",
        "加仓最大单笔%",
        "加仓最大亏损%",
    ):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return insert_name_column(df, code_col="代码")


def summarize_batch_by_year(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按年汇总：胜率 / 平均收益% 按轮次加权；加仓胜率/平均收益% 按加仓次数加权。多种复权时按 年×复权 拆开。"""
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        y = str(r.get("year") or "").strip()
        if not y:
            walk = compact_day(str(r.get("walk_start") or ""))
            y = walk[:4] if len(walk) >= 4 else ""
        if not y:
            y = "?"
        div = normalize_dividend_type(r.get("dividend_type"))
        by_key.setdefault((y, div), []).append(r)
    out: list[dict[str, Any]] = []
    for y, div in sorted(by_key):
        xs = by_key[(y, div)]
        n_ok = sum(1 for r in xs if r.get("ok"))
        n_buy = 0.0
        sum_pnl = 0.0
        win_n = 0.0
        ret_w = 0.0
        n_add = 0.0
        add_win_n = 0.0
        add_sum_pnl = 0.0
        add_ret_w = 0.0
        max_win: float | None = None
        max_loss: float | None = None
        add_max_win: float | None = None
        add_max_loss: float | None = None
        for r in xs:
            if not r.get("ok"):
                continue
            nb = float(r.get("n_buy") or 0)
            n_buy += nb
            sum_pnl += float(r.get("sum_pnl") or 0)
            win_n += float(r.get("win_rate") or 0) / 100.0 * nb
            ret_w += float(r.get("avg_ret") or 0) * nb
            na = float(r.get("n_add") or 0)
            n_add += na
            add_win_n += float(r.get("add_win_rate") or 0) / 100.0 * na
            add_sum_pnl += float(r.get("add_sum_pnl") or 0)
            add_ret_w += float(r.get("add_avg_ret") or 0) * na
            mw = r.get("max_win")
            ml = r.get("max_loss")
            if mw is not None and mw != "":
                fv = float(mw)
                max_win = fv if max_win is None else max(max_win, fv)
            if ml is not None and ml != "":
                fv = float(ml)
                max_loss = fv if max_loss is None else min(max_loss, fv)
            amw = r.get("add_max_win")
            aml = r.get("add_max_loss")
            if na and amw is not None and amw != "":
                fv = float(amw)
                add_max_win = fv if add_max_win is None else max(add_max_win, fv)
            if na and aml is not None and aml != "":
                fv = float(aml)
                add_max_loss = fv if add_max_loss is None else min(add_max_loss, fv)
        out.append(
            {
                "year": y,
                "dividend_type": div,
                "n_stock": len(xs),
                "n_ok": n_ok,
                "n_buy": int(n_buy) if n_buy == int(n_buy) else n_buy,
                "sum_pnl": sum_pnl if n_ok else None,
                "win_rate": (100.0 * win_n / n_buy) if n_buy else None,
                "avg_ret": (ret_w / n_buy) if n_buy else None,
                "max_win": max_win,
                "max_loss": max_loss,
                "n_add": int(n_add) if n_add == int(n_add) else n_add,
                "add_win_rate": (100.0 * add_win_n / n_add) if n_add else None,
                "add_sum_pnl": add_sum_pnl if n_add else None,
                "add_avg_ret": (add_ret_w / n_add) if n_add else None,
                "add_max_win": add_max_win,
                "add_max_loss": add_max_loss,
            }
        )
    return out


def batch_year_summary_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    recs = []
    yearly = summarize_batch_by_year(rows)
    has_div = len(unique_dividend_types(yearly)) >= 2
    for r in yearly:
        rec: dict[str, Any] = {"年份": r.get("year") or ""}
        if has_div:
            rec["复权"] = dividend_label(r.get("dividend_type")) if r.get("dividend_type") else ""
        rec.update(
            {
                "标的数": r.get("n_stock"),
                "成功数": r.get("n_ok"),
                "轮次": r.get("n_buy"),
                "总盈亏": r.get("sum_pnl"),
                "胜率": r.get("win_rate"),
                "平均收益%": r.get("avg_ret"),
                "最大单笔%": r.get("max_win"),
                "最大亏损%": r.get("max_loss"),
                "加仓次数": r.get("n_add"),
                "加仓总盈亏": r.get("add_sum_pnl"),
                "加仓胜率": r.get("add_win_rate"),
                "加仓平均收益%": r.get("add_avg_ret"),
                "加仓最大单笔%": r.get("add_max_win"),
                "加仓最大亏损%": r.get("add_max_loss"),
            }
        )
        recs.append(rec)
    cols = [
        "年份",
        "标的数",
        "成功数",
        "轮次",
        "总盈亏",
        "胜率",
        "平均收益%",
        "最大单笔%",
        "最大亏损%",
        "加仓次数",
        "加仓总盈亏",
        "加仓胜率",
        "加仓平均收益%",
        "加仓最大单笔%",
        "加仓最大亏损%",
    ]
    if has_div:
        cols = ["年份", "复权"] + [c for c in cols if c != "年份"]
    df = pd.DataFrame(recs, columns=cols)
    for col in ("标的数", "成功数", "轮次", "加仓次数"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in (
        "总盈亏",
        "胜率",
        "平均收益%",
        "最大单笔%",
        "最大亏损%",
        "加仓胜率",
        "加仓总盈亏",
        "加仓平均收益%",
        "加仓最大单笔%",
        "加仓最大亏损%",
    ):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def write_batch_summary_csv(rows: list[dict[str, Any]], path: str | Path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "stock",
        "year",
        "ma_type",
        "dividend_type",
        "ok",
        "status",
        "walk_start",
        "walk_end",
        "n_bars",
        "n_buy",
        "sum_pnl",
        "win_rate",
        "avg_ret",
        "max_win",
        "max_loss",
        "n_add",
        "add_win_rate",
        "add_sum_pnl",
        "add_avg_ret",
        "add_max_win",
        "add_max_loss",
        "budget",
        "error",
        "csv",
        "log",
        "detail",
    ]
    recs = [{k: r.get(k) for k in fields} for r in rows]
    pd.DataFrame(recs, columns=fields).to_csv(dest, index=False, encoding="utf-8-sig")
    return dest


def write_batch_year_summary_csv(rows: list[dict[str, Any]], path: str | Path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "year",
        "dividend_type",
        "n_stock",
        "n_ok",
        "n_buy",
        "sum_pnl",
        "win_rate",
        "avg_ret",
        "max_win",
        "max_loss",
        "n_add",
        "add_win_rate",
        "add_sum_pnl",
        "add_avg_ret",
        "add_max_win",
        "add_max_loss",
    ]
    recs = [{k: r.get(k) for k in fields} for r in summarize_batch_by_year(rows)]
    pd.DataFrame(recs, columns=fields).to_csv(dest, index=False, encoding="utf-8-sig")
    return dest
