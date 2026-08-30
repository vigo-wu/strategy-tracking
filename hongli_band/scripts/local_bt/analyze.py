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
    """root/<type>；root 已是该 type 目录名则不再拼接。非法 type 回落默认。"""
    base = Path(root)
    div = normalize_dividend_type(dividend_type) or DEFAULT_DIVIDEND_TYPE
    if base.name == div:
        return base
    return base / div


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
    for meta in daily_csvs_by_stock(csv_dir):
        got = str(meta.get("stock") or "").strip().upper()
        if got == want or _stock_token_match(got, want):
            path = Path(str(meta.get("path") or ""))
            if str(path):
                return path
    return None


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
            rec["标的"] = stock
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
        cols = ["标的"] + cols
    df = pd.DataFrame(recs, columns=cols)
    if "轮次" in df.columns:
        df["轮次"] = pd.to_numeric(df["轮次"], errors="coerce").astype("Int64")
    for col in ("总盈亏", "胜率", "平均收益%"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


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
        rec: dict[str, Any] = {"标的": r.get("stock") or ""}
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
        "标的",
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
        cols = ["标的", "复权"] + [c for c in cols if c != "标的"]
    if has_year:
        rest = [c for c in cols if c != "标的"]
        cols = ["标的", "年份"] + [c for c in rest if c != "年份"]
    df = pd.DataFrame(recs, columns=cols)
    for col in ("轮次SMA", "轮次EMA"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("盈亏SMA", "盈亏EMA", "Δ盈亏", "胜率SMA", "胜率EMA", "平均%SMA", "平均%EMA"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


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


def report_mod():
    global _REPORT
    if _REPORT is None:
        _REPORT = _load_report_mod()
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
        if "hold_calendar_days" not in t:
            try:
                b = datetime.strptime(str(t["buy_open_day"])[:8], "%Y%m%d")
                s = datetime.strptime(str(t["sell_exec_day"])[:8], "%Y%m%d")
                t["hold_calendar_days"] = (s - b).days
            except Exception:
                t["hold_calendar_days"] = None
        trades.append(t)
    return trades


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


def analyze_detail(
    detail_path: str | Path,
    budget: float = 50000.0,
    meta: dict | None = None,
) -> dict[str, Any]:
    """操作明细 → trades / equity / stats。"""
    mod = report_mod()
    path = Path(detail_path)
    rounds = mod.parse_terminal_rounds(path)
    trades = _normalize_trades(rounds)
    meta_d = meta or {
        "tag": "HlBand",
        "ver": "local",
        "stock": "?",
        "period": "1d",
        "budget": float(budget),
    }
    if "budget" not in meta_d:
        meta_d["budget"] = float(budget)
    stats = mod.compute_stats(meta_d, trades, diag={}, price_info={"source": "terminal", "terminal_csv": str(path)})
    eq = mod.equity_curve(trades, float(budget))
    return {
        "path": str(path.resolve()),
        "trades": trades,
        "stats": stats,
        "equity": eq,
        "budget": float(budget),
        "sum_pnl_detail": float(stats.get("sum_pnl") or 0.0),
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
    if not trades:
        return pd.DataFrame(
            columns=[
                "i",
                "buy_open_day",
                "sell_exec_day",
                "buy_price",
                "sell_price",
                "shares",
                "pnl",
                "ret_pct",
                "hold_calendar_days",
            ]
        )
    cols = [
        "i",
        "buy_open_day",
        "sell_exec_day",
        "buy_price",
        "sell_price",
        "shares",
        "cost",
        "pnl",
        "ret_pct",
        "hold_calendar_days",
        "buy_signal",
        "sell_signal",
    ]
    rows = [{c: t.get(c) for c in cols} for t in trades]
    return pd.DataFrame(rows)


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
    )
    stats = result["stats"] or {}
    return {
        "n_buy": int(stats.get("n_buy") or 0),
        "sum_pnl": float(stats.get("sum_pnl") or 0.0),
        "win_rate": float(stats.get("win_rate") or 0.0),
        "avg_ret": float(stats.get("avg_ret") or 0.0),
        "max_win": float(stats.get("max_win") or 0.0),
        "max_loss": float(stats.get("max_loss") or 0.0),
    }


def summarize_batch_row(row: dict[str, Any]) -> dict[str, Any]:
    """把 run_batch 一行补上 KPI / 中文状态。"""
    out = dict(row)
    if not out.get("ok"):
        out["status"] = "失败"
        out.setdefault("n_buy", None)
        out.setdefault("sum_pnl", None)
        out.setdefault("win_rate", None)
        out.setdefault("avg_ret", None)
        out.setdefault("max_win", None)
        out.setdefault("max_loss", None)
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
        out.setdefault("n_buy", None)
        out.setdefault("sum_pnl", None)
        out.setdefault("win_rate", None)
        out.setdefault("avg_ret", None)
        out.setdefault("max_win", None)
        out.setdefault("max_loss", None)
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
        rec: dict[str, Any] = {"标的": r.get("stock") or ""}
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
                "说明": r.get("error") or "",
            }
        )
        recs.append(rec)
    cols = ["标的"]
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
        "说明",
    ]
    df = pd.DataFrame(recs, columns=cols)
    for col in ("轮次",):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("总盈亏", "胜率", "平均收益%", "最大单笔%", "最大亏损%"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def summarize_batch_by_year(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按年汇总：胜率 / 平均收益% 按轮次加权。多种复权时按 年×复权 拆开。"""
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
        max_win: float | None = None
        max_loss: float | None = None
        for r in xs:
            if not r.get("ok"):
                continue
            nb = float(r.get("n_buy") or 0)
            n_buy += nb
            sum_pnl += float(r.get("sum_pnl") or 0)
            win_n += float(r.get("win_rate") or 0) / 100.0 * nb
            ret_w += float(r.get("avg_ret") or 0) * nb
            mw = r.get("max_win")
            ml = r.get("max_loss")
            if mw is not None and mw != "":
                fv = float(mw)
                max_win = fv if max_win is None else max(max_win, fv)
            if ml is not None and ml != "":
                fv = float(ml)
                max_loss = fv if max_loss is None else min(max_loss, fv)
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
    ]
    if has_div:
        cols = ["年份", "复权"] + [c for c in cols if c != "年份"]
    df = pd.DataFrame(recs, columns=cols)
    for col in ("标的数", "成功数", "轮次"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("总盈亏", "胜率", "平均收益%", "最大单笔%", "最大亏损%"):
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
    ]
    recs = [{k: r.get(k) for k in fields} for r in summarize_batch_by_year(rows)]
    pd.DataFrame(recs, columns=fields).to_csv(dest, index=False, encoding="utf-8-sig")
    return dest
