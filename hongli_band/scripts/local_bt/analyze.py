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

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
THEME = REPO / "hongli_band"
REPORT_PY = (
    REPO / ".cursor" / "skills" / "qmt-backtest-report" / "scripts" / "generate_report.py"
)

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from market_csv import compact_day, load_daily_csv, peek_daily_csv_meta  # noqa: E402

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


def normalize_dividend_type(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    return s if s in DIVIDEND_TYPES else ""


def dividend_label(dividend_type: Any) -> str:
    div = normalize_dividend_type(dividend_type) or DEFAULT_DIVIDEND_TYPE
    return DIVIDEND_LABELS.get(div, div)


def resolve_typed_dir(root: str | Path, dividend_type: Any = "") -> Path:
    """root/<type>；root 已是该 type 目录名则不再拼接。非法 type 回落默认。"""
    base = Path(root)
    div = normalize_dividend_type(dividend_type) or DEFAULT_DIVIDEND_TYPE
    if base.name == div:
        return base
    return base / div


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


def daily_csv_for_stock(csv_dir: str | Path, stock: str) -> Path | None:
    want = str(stock or "").strip().upper()
    if not want:
        return None
    for meta in daily_csvs_by_stock(csv_dir):
        if str(meta.get("stock") or "").strip().upper() == want:
            return Path(str(meta.get("path") or ""))
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
    """批量行按 (stock, year) 配对 SMA/EMA。"""
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
    for r in pairs:
        rec: dict[str, Any] = {"标的": r.get("stock") or ""}
        if has_year:
            rec["年份"] = str(r.get("year") or "")
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
    if has_year:
        cols = ["标的", "年份"] + [c for c in cols if c != "标的"]
    df = pd.DataFrame(recs, columns=cols)
    for col in ("轮次SMA", "轮次EMA"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("盈亏SMA", "盈亏EMA", "Δ盈亏", "胜率SMA", "胜率EMA", "平均%SMA", "平均%EMA"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def summarize_ma_compare_by_year(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_year: dict[str, list[dict[str, Any]]] = {}
    for r in pairs:
        y = str(r.get("year") or "").strip() or "?"
        by_year.setdefault(y, []).append(r)
    out: list[dict[str, Any]] = []
    for y in sorted(by_year):
        xs = by_year[y]
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
    for r in summarize_ma_compare_by_year(pairs):
        recs.append(
            {
                "年份": r.get("year") or "",
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
    for r in rows:
        walk_s = compact_day(str(r.get("walk_start") or ""))
        walk_e = compact_day(str(r.get("walk_end") or ""))
        walk = ""
        if walk_s or walk_e:
            walk = "%s–%s" % (walk_s or "?", walk_e or "?")
        rec: dict[str, Any] = {"标的": r.get("stock") or ""}
        if has_year:
            rec["年份"] = str(r.get("year") or "")
        ma = normalize_ma_type(r.get("ma_type"))
        if ma:
            rec["均线"] = ma
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
    cols = [
        "标的",
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
    if any(normalize_ma_type(r.get("ma_type")) for r in rows):
        cols = ["标的", "均线"] + [c for c in cols if c != "标的"]
    if has_year:
        rest = [c for c in cols if c != "标的"]
        cols = ["标的", "年份"] + [c for c in rest if c != "年份"]
    df = pd.DataFrame(recs, columns=cols)
    for col in ("轮次",):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    for col in ("总盈亏", "胜率", "平均收益%", "最大单笔%", "最大亏损%"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def summarize_batch_by_year(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按年汇总：胜率 / 平均收益% 按轮次加权。"""
    by_year: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        y = str(r.get("year") or "").strip()
        if not y:
            walk = compact_day(str(r.get("walk_start") or ""))
            y = walk[:4] if len(walk) >= 4 else ""
        if not y:
            y = "?"
        by_year.setdefault(y, []).append(r)
    out: list[dict[str, Any]] = []
    for y in sorted(by_year):
        xs = by_year[y]
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
    for r in summarize_batch_by_year(rows):
        recs.append(
            {
                "年份": r.get("year") or "",
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
