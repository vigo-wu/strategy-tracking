# coding: utf-8
"""HlBand 批量回测 → 选股打分。只读 report 明细/日志 + 日线 CSV，不改策略、不重跑。

CLI（模块名避开标准库 select）::

  python hongli_band/scripts/local_bt/stock_select.py
"""
from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
THEME = REPO / "hongli_band"
CONFIG_PY = THEME / "scripts" / "qmt" / "hlband" / "config.py"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from analyze import (  # noqa: E402
    DEFAULT_CSV_ROOT,
    DEFAULT_DIVIDEND_TYPE,
    DEFAULT_REPORT_ROOT,
    DIVIDEND_TYPES,
    agg_kpi_pnl,
    analyze_detail,
    daily_csvs_by_stock,
    normalize_dividend_type,
    parse_budget_from_log,
    pick_div_winner,
    pick_ma_winner,
    resolve_typed_dir,
    typed_dir_root,
    typed_sibling_dirs,
)
from market_csv import load_daily_csv  # noqa: E402
from select_config import DEFAULT_FILTERS, WEIGHTS, clamp_top_n  # noqa: E402

DEFAULT_REPORT = DEFAULT_REPORT_ROOT
DEFAULT_CSV_DIR = DEFAULT_CSV_ROOT

DETAIL_RE = re.compile(
    r"^local_bt_(\d{6})_(SZ|SH)(?:_(\d{4}))?(?:_(SMA|EMA))?_操作明细\.csv$",
    re.IGNORECASE,
)
RE_SELL_SIG = re.compile(r"SELL by signal=(\w+)")
RE_BUY_SIG = re.compile(r"BUY(?: add)? by signal=(\w+)")
RE_BANNER_N = re.compile(r"\bn=\s*(\d+)")
SKIP_CODES = (
    "w_bias_skip",
    "w_slope_skip",
    "vol_dry_skip",
    "chase_skip",
    "weekly_bear",
)
# 默认回落；实际打分年由扫描结果推断（含尚未走完的最大年）
SCORE_YEARS = ("2021", "2022", "2023", "2024", "2025", "2026")
RECENT_KEY = "recent"

PF_CAP = 10.0
VOL_MIN_BARS = 40
TOUCH_TOL = 0.025


def glob_fingerprint(root: Path, pattern: str) -> tuple[int, int, int]:
    """目录聚合指纹：(匹配文件数, 最大 mtime_ns, 总 size)。scandir，不作逐文件键。"""
    n = 0
    mx = 0
    sz = 0
    root = Path(root)
    if not root.is_dir():
        return (0, 0, 0)
    try:
        entries = os.scandir(root)
    except OSError:
        return (0, 0, 0)
    with entries:
        for e in entries:
            try:
                if not e.is_file():
                    continue
            except OSError:
                continue
            if not fnmatch.fnmatch(e.name, pattern):
                continue
            n += 1
            try:
                st = e.stat()
            except OSError:
                continue
            mx = max(mx, int(st.st_mtime_ns))
            sz += int(st.st_size)
    return (n, mx, sz)


def _glob_fingerprint(root: Path, pattern: str) -> tuple[int, int, int]:
    return glob_fingerprint(root, pattern)


def _merge_fingerprints(parts: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    n = 0
    mx = 0
    sz = 0
    for a, b, c in parts:
        n += a
        mx = max(mx, b)
        sz += c
    return (n, mx, sz)


def report_fingerprint(report_dir: str | Path) -> tuple[int, int, int]:
    """报告目录指纹：含全部复权兄弟目录。"""
    parts = []
    sibs = typed_sibling_dirs(report_dir)
    if not sibs:
        return _glob_fingerprint(Path(report_dir), "local_bt_*操作明细.csv")
    for _div, d in sibs:
        parts.append(_glob_fingerprint(d, "local_bt_*操作明细.csv"))
    return _merge_fingerprints(parts)


def csv_dir_fingerprint(csv_dir: str | Path) -> tuple[int, int, int]:
    parts = []
    sibs = typed_sibling_dirs(csv_dir)
    if not sibs:
        return _glob_fingerprint(Path(csv_dir), "*_1d_*.csv")
    for _div, d in sibs:
        parts.append(_glob_fingerprint(d, "*_1d_*.csv"))
    return _merge_fingerprints(parts)


def load_book_stocks(config_path: str | Path | None = None) -> dict[str, str]:
    """config.BOOK_STOCKS → {code: ma_type}。读失败则空字典。"""
    path = Path(config_path) if config_path else CONFIG_PY
    if not path.is_file():
        return {}
    spec = importlib.util.spec_from_file_location("hlband_config_select", path)
    if spec is None or spec.loader is None:
        return {}
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return {}
    raw = getattr(mod, "BOOK_STOCKS", None)
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        items = raw.items()
    elif isinstance(raw, (list, tuple)):
        items = [(str(x), {}) for x in raw]
    else:
        return {}
    for k, v in items:
        code = str(k or "").strip().upper()
        if not code:
            continue
        if isinstance(v, dict):
            kind = str(v.get("ma_type") or "EMA").strip().upper()
        elif isinstance(v, str):
            kind = v.strip().upper()
        else:
            kind = "EMA"
        if kind not in ("EMA", "SMA"):
            kind = "EMA"
        out[code] = kind
    return out


def _log_path_for_detail(detail: Path) -> Path:
    name = detail.name
    if name.endswith("_操作明细.csv"):
        return detail.with_name(name[: -len("_操作明细.csv")] + ".txt")
    return detail.with_suffix(".txt")


def list_detail_files(report_dir: str | Path) -> list[dict[str, Any]]:
    root = Path(report_dir)
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for p in sorted(root.glob("local_bt_*操作明细.csv")):
        m = DETAIL_RE.match(p.name)
        if not m:
            continue
        code, ex, year, ma = m.group(1), m.group(2).upper(), m.group(3), m.group(4)
        stock = "%s.%s" % (code, ex)
        rows.append(
            {
                "stock": stock,
                "year": year or RECENT_KEY,
                "ma_type": (ma or "").upper(),
                "detail": p,
                "log": _log_path_for_detail(p),
            }
        )
    return rows


def parse_log_signals(log_path: str | Path | None) -> dict[str, Any]:
    sell: Counter[str] = Counter()
    buy: Counter[str] = Counter()
    skip: Counter[str] = Counter()
    n_bars = 0
    if not log_path:
        return {"sell": dict(sell), "buy": dict(buy), "skip": dict(skip), "n_bars": n_bars}
    p = Path(log_path)
    if not p.is_file():
        return {"sell": dict(sell), "buy": dict(buy), "skip": dict(skip), "n_bars": n_bars}
    text = p.read_text(encoding="utf-8", errors="replace")
    first = text.splitlines()[0] if text else ""
    bm = RE_BANNER_N.search(first)
    if bm:
        try:
            n_bars = int(bm.group(1))
        except ValueError:
            n_bars = 0
    for m in RE_SELL_SIG.finditer(text):
        sell[m.group(1)] += 1
    for m in RE_BUY_SIG.finditer(text):
        buy[m.group(1)] += 1
    for code in SKIP_CODES:
        skip[code] = text.count(code)
    return {"sell": dict(sell), "buy": dict(buy), "skip": dict(skip), "n_bars": n_bars}


def _max_dd(equity: pd.DataFrame, budget: float) -> float | None:
    if equity is None or equity.empty or "equity" not in equity.columns:
        return None
    eq = pd.to_numeric(equity["equity"], errors="coerce").dropna()
    if eq.empty:
        return None
    peak = eq.cummax()
    base = peak.replace(0, np.nan)
    if float(budget or 0) > 0:
        base = base.fillna(float(budget))
    dd = (eq - peak) / base
    val = float(dd.min()) if len(dd) else None
    if val is None or not np.isfinite(val):
        return None
    return round(val, 6)


def _profit_factor(gross_profit: float, gross_loss: float) -> float | None:
    gp = float(gross_profit or 0.0)
    gl = abs(float(gross_loss or 0.0))
    if gl <= 1e-12:
        if gp > 0:
            return PF_CAP
        return None
    return min(PF_CAP, gp / gl)


def kpi_from_detail(detail: Path, log: Path | None, stock: str) -> dict[str, Any]:
    budget = parse_budget_from_log(log, default=50000.0) if log else 50000.0
    result = analyze_detail(
        detail,
        budget=budget,
        meta={"tag": "HlBand", "ver": "local", "stock": stock, "period": "1d", "budget": budget},
        log_path=log,
        hold_metrics=False,
    )
    stats = result.get("stats") or {}
    trades = result.get("trades") or []
    holds = []
    win_pnls = []
    buy_ctr: Counter[str] = Counter()
    sell_ctr: Counter[str] = Counter()
    for t in trades:
        h = t.get("hold_calendar_days")
        if h is not None and h != "":
            try:
                holds.append(float(h))
            except (TypeError, ValueError):
                pass
        try:
            pnl = float(t.get("pnl") or 0.0)
        except (TypeError, ValueError):
            pnl = 0.0
        if pnl > 0:
            win_pnls.append(pnl)
        # 信号计数只看本明细轮次，避免组合 log 污染按票归因
        bs = str(t.get("buy_signal") or "").strip()
        if bs and bs not in ("-",):
            buy_ctr[bs] += 1
        ss = str(t.get("sell_signal") or "").strip()
        if ss and ss not in ("-",):
            sell_ctr[ss] += 1
    gp = float(stats.get("gross_profit") or 0.0)
    gl = float(stats.get("gross_loss") or 0.0)
    sig = parse_log_signals(log)
    return {
        "n_buy": int(stats.get("n_buy") or 0),
        "sum_pnl": float(stats.get("sum_pnl") or 0.0),
        "win_rate": float(stats.get("win_rate") or 0.0),
        "avg_ret": float(stats.get("avg_ret") or 0.0),
        "max_win": float(stats.get("max_win") or 0.0),
        "max_loss": float(stats.get("max_loss") or 0.0),
        "gross_profit": gp,
        "gross_loss": gl,
        "profit_factor": _profit_factor(gp, gl),
        "max_dd": _max_dd(result.get("equity"), budget),
        "avg_hold_days": (sum(holds) / len(holds)) if holds else None,
        "max_win_pnl": max(win_pnls) if win_pnls else 0.0,
        "budget": float(budget),
        "sell": dict(sell_ctr) if sell_ctr else sig["sell"],
        "buy": dict(buy_ctr) if buy_ctr else sig["buy"],
        "skip": sig["skip"],
        "n_bars": int(sig["n_bars"] or 0),
        "detail": str(detail),
        "log": str(log) if log else "",
    }


def style_from_closes(closes: list[float], *, tol: float = TOUCH_TOL) -> dict[str, Any]:
    arr = np.asarray(closes, dtype=float)
    arr = arr[np.isfinite(arr) & (arr > 0)]
    if len(arr) < 20:
        return {"vol_ann": None, "touch_ma20": None, "n_close": int(len(arr))}
    window = arr[-252:] if len(arr) > 252 else arr
    vol = None
    if len(window) >= VOL_MIN_BARS + 1:
        rets = np.diff(np.log(window[-(VOL_MIN_BARS + 1) :]))
        if len(rets) >= VOL_MIN_BARS:
            vol = float(np.std(rets, ddof=1) * np.sqrt(252.0))
    s = pd.Series(window, dtype=float)
    ma = s.rolling(20, min_periods=20).mean()
    valid = ma.notna() & (ma > 0)
    touch = None
    if int(valid.sum()) >= 20:
        ratio = (s[valid] - ma[valid]).abs() / ma[valid]
        touch = float((ratio <= float(tol)).mean())
    return {"vol_ann": vol, "touch_ma20": touch, "n_close": int(len(arr))}


def _add_counter(dst: Counter[str], src: dict | None) -> None:
    if not src:
        return
    for k, v in src.items():
        try:
            dst[str(k)] += int(v)
        except (TypeError, ValueError):
            continue


def _ma_bucket(rec: dict[str, Any], ma: str) -> dict[str, Any]:
    rec.setdefault("by_ma", {})
    rec["by_ma"].setdefault(ma, {"years": {}, "recent": None})
    return rec["by_ma"][ma]


def _clip_year_map(
    years: dict[str, Any] | None,
    years_keep: tuple[str, ...] | list[str] | set[str] | None,
) -> dict[str, Any]:
    src = dict(years or {})
    if years_keep is None:
        return src
    keep = {str(y) for y in years_keep}
    return {str(y): v for y, v in src.items() if str(y) in keep}


def _empty_style() -> dict[str, Any]:
    return {"vol_ann": None, "touch_ma20": None, "n_close": 0}


def _style_from_csv_meta(meta: dict[str, Any] | None, stock: str) -> tuple[dict[str, Any], str, str]:
    if not meta or not meta.get("path"):
        return _empty_style(), "", ""
    try:
        _code, bars = load_daily_csv(meta["path"], stock=stock)
        closes = [float(b.close) for b in bars if float(b.close) > 0]
        return style_from_closes(closes), str(meta["path"]), ""
    except Exception as e:
        return _empty_style(), "", "ohlc: %s; " % e


def _resolve_stock_ma(
    rec: dict[str, Any],
    years_keep: tuple[str, ...] | list[str] | set[str] | None = None,
) -> None:
    """按成对分年对照选定建议均线，并把 years/recent 换成胜出一侧。

    years_keep 非空时只在这些年内择优，不回写 by_ma 原始分年 KPI。
    """
    by_ma = rec.get("by_ma") or {}
    sma_years = _clip_year_map((by_ma.get("SMA") or {}).get("years"), years_keep)
    ema_years = _clip_year_map((by_ma.get("EMA") or {}).get("years"), years_keep)
    plain_years = _clip_year_map((by_ma.get("") or {}).get("years"), years_keep)
    paired = sorted(set(sma_years) & set(ema_years), key=str)

    rec["ma_type_suggest"] = ""
    rec["ma_type_why"] = "no_compare"
    rec["ma_pnl_sma"] = None
    rec["ma_pnl_ema"] = None
    rec["ma_pnl_delta"] = None
    rec["ma_label"] = ""

    if paired:
        pick = pick_ma_winner(agg_kpi_pnl([sma_years[y] for y in paired]), agg_kpi_pnl([ema_years[y] for y in paired]))
        winner = str(pick.get("winner") or "")
        src = by_ma.get(winner) or {}
        rec["years"] = _clip_year_map(src.get("years"), years_keep)
        rec["recent"] = src.get("recent") or (by_ma.get("") or {}).get("recent")
        rec["ma_type_suggest"] = winner
        rec["ma_type_why"] = pick.get("why") or "compare"
        rec["ma_pnl_sma"] = pick.get("pnl_sma")
        rec["ma_pnl_ema"] = pick.get("pnl_ema")
        rec["ma_pnl_delta"] = pick.get("pnl_delta")
        rec["ma_label"] = pick.get("label") or ""
        return

    has_sma = bool(sma_years)
    has_ema = bool(ema_years)
    if has_sma and not has_ema:
        rec["years"] = sma_years
        rec["recent"] = (by_ma.get("SMA") or {}).get("recent") or (by_ma.get("") or {}).get("recent")
        rec["ma_type_suggest"] = "SMA"
        rec["ma_type_why"] = "single_ma"
        rec["ma_pnl_sma"] = float(agg_kpi_pnl(list(sma_years.values())).get("sum_pnl") or 0)
        rec["ma_label"] = "SMA"
        return
    if has_ema and not has_sma:
        rec["years"] = ema_years
        rec["recent"] = (by_ma.get("EMA") or {}).get("recent") or (by_ma.get("") or {}).get("recent")
        rec["ma_type_suggest"] = "EMA"
        rec["ma_type_why"] = "single_ma"
        rec["ma_pnl_ema"] = float(agg_kpi_pnl(list(ema_years.values())).get("sum_pnl") or 0)
        rec["ma_label"] = "EMA"
        return

    rec["years"] = plain_years
    rec["recent"] = (by_ma.get("") or {}).get("recent")
    rec["ma_type_why"] = "no_compare"


def _copy_div_to_rec(
    rec: dict[str, Any],
    drec: dict[str, Any],
    div: str,
    *,
    why: str,
    pick: dict[str, Any] | None = None,
    years_keep: tuple[str, ...] | list[str] | set[str] | None = None,
) -> None:
    rec["years"] = _clip_year_map(drec.get("years"), years_keep)
    rec["recent"] = drec.get("recent")
    rec["ma_type_suggest"] = drec.get("ma_type_suggest") or ""
    rec["ma_type_why"] = drec.get("ma_type_why") or ""
    rec["ma_pnl_sma"] = drec.get("ma_pnl_sma")
    rec["ma_pnl_ema"] = drec.get("ma_pnl_ema")
    rec["ma_pnl_delta"] = drec.get("ma_pnl_delta")
    rec["ma_label"] = drec.get("ma_label") or ""
    rec["div_type_suggest"] = div
    rec["div_type_why"] = why
    rec["div_pnl"] = dict((pick or {}).get("pnl_by_type") or {})


def _resolve_stock_div(
    rec: dict[str, Any],
    years_keep: tuple[str, ...] | list[str] | set[str] | None = None,
) -> None:
    """各复权先完成 MA 择优后，在分年交集上选定建议复权。"""
    by_div = rec.get("by_div") or {}
    rec["div_type_suggest"] = ""
    rec["div_type_why"] = "no_compare"
    rec["div_pnl"] = {}
    year_maps: dict[str, dict[str, Any]] = {}
    for div, drec in by_div.items():
        years = _clip_year_map(drec.get("years"), years_keep)
        if years:
            year_maps[str(div)] = years
    if not year_maps:
        return
    if len(year_maps) == 1:
        div = next(iter(year_maps))
        _copy_div_to_rec(rec, by_div[div], div, why="single_div", years_keep=years_keep)
        return
    common = set(year_maps[next(iter(year_maps))])
    for years in year_maps.values():
        common &= set(years)
    if not common:
        return
    kpis_by_type: dict[str, dict[str, Any] | None] = {}
    for div, years in year_maps.items():
        kpis_by_type[div] = agg_kpi_pnl([years[y] for y in sorted(common)])
    pick = pick_div_winner(kpis_by_type)
    winner = str(pick.get("winner") or "")
    if not winner or winner not in by_div:
        rec["div_type_why"] = str(pick.get("why") or "no_compare")
        rec["div_pnl"] = dict(pick.get("pnl_by_type") or {})
        return
    _copy_div_to_rec(
        rec, by_div[winner], winner, why=str(pick.get("why") or "compare"), pick=pick, years_keep=years_keep,
    )


def _apply_year_window(rec: dict[str, Any], score_years: tuple[str, ...]) -> dict[str, Any]:
    """拷贝后按选定年重跑均线/复权择优，不改扫描缓存。"""
    keep = tuple(str(y) for y in score_years)
    by_div = rec.get("by_div") or {}
    by_ma = rec.get("by_ma") or {}
    if not by_div and not by_ma:
        work = dict(rec)
        years = rec.get("years") or {}
        work["years"] = {str(y): years[y] for y in keep if y in years}
        return work
    work: dict[str, Any] = {
        "stock": rec.get("stock"),
        "style": dict(rec.get("style") or {}),
        "error": rec.get("error") or "",
        "csv": rec.get("csv"),
        "by_ma": by_ma,
        "by_div": {},
        "years": {},
        "recent": rec.get("recent"),
    }
    if by_div:
        by_div_work: dict[str, Any] = {}
        for div, drec in by_div.items():
            dcopy = {
                "by_ma": drec.get("by_ma") or {},
                "years": {},
                "recent": drec.get("recent"),
                "style": dict(drec.get("style") or {}),
                "csv": drec.get("csv"),
            }
            _resolve_stock_ma(dcopy, years_keep=keep)
            by_div_work[str(div)] = dcopy
        work["by_div"] = by_div_work
        _resolve_stock_div(work, years_keep=keep)
        winner = str(work.get("div_type_suggest") or "")
        if winner and winner in by_div_work:
            stl = by_div_work[winner].get("style")
            if stl:
                work["style"] = dict(stl)
            if by_div_work[winner].get("csv"):
                work["csv"] = by_div_work[winner].get("csv")
        return work
    _resolve_stock_ma(work, years_keep=keep)
    work["div_type_suggest"] = rec.get("div_type_suggest") or ""
    work["div_type_why"] = rec.get("div_type_why") or "no_compare"
    return work


def scan_reports(
    report_dir: str | Path | None = None,
    csv_dir: str | Path | None = None,
    *,
    progress: bool = False,
) -> dict[str, Any]:
    """扫描 local_bt 明细/日志 + 日线股性。结果可供 score_universe 反复打分。"""
    report = Path(report_dir) if report_dir else resolve_typed_dir(
        DEFAULT_REPORT, DEFAULT_DIVIDEND_TYPE
    )
    data_dir = Path(csv_dir) if csv_dir else resolve_typed_dir(
        DEFAULT_CSV_DIR, DEFAULT_DIVIDEND_TYPE
    )
    report_dirs = typed_sibling_dirs(report)
    csv_root = typed_dir_root(data_dir)
    stocks: dict[str, dict[str, Any]] = {}
    packed: list[dict[str, Any]] = []
    for div, rdir in report_dirs:
        for item in list_detail_files(rdir):
            row = dict(item)
            row["dividend_type"] = div or normalize_dividend_type(rdir.name)
            packed.append(row)
    n_files = len(packed)
    for i, item in enumerate(packed):
        stock = item["stock"]
        year = item["year"]
        ma = str(item.get("ma_type") or "")
        div = str(item.get("dividend_type") or "")
        if progress and (i == 0 or (i + 1) % 100 == 0 or (i + 1) == n_files):
            print(
                "scan detail %s/%s %s %s %s %s"
                % (i + 1, n_files, stock, year, div or "-", ma or "-"),
                flush=True,
            )
        rec = stocks.setdefault(
            stock,
            {
                "stock": stock,
                "years": {},
                "recent": None,
                "style": {},
                "error": "",
                "by_ma": {},
                "by_div": {},
            },
        )
        log = item["log"] if item["log"].is_file() else None
        try:
            kpi = kpi_from_detail(item["detail"], log, stock)
        except Exception as e:
            rec["error"] = (rec.get("error") or "") + ("%s: %s; " % (year, e))
            continue
        if div:
            drec = rec["by_div"].setdefault(div, {"by_ma": {}, "years": {}, "recent": None})
            bucket = _ma_bucket(drec, ma)
        else:
            bucket = _ma_bucket(rec, ma)
        if year == RECENT_KEY:
            bucket["recent"] = kpi
        else:
            bucket["years"][year] = kpi

    ohlc_by_div: dict[str, dict[str, dict[str, Any]]] = {}
    csv_sibs = typed_sibling_dirs(data_dir)
    if not csv_sibs:
        csv_sibs = [("", data_dir)]
    for div, cdir in csv_sibs:
        try:
            ohlc_by_div[div] = {
                str(m.get("stock") or "").strip().upper(): m for m in daily_csvs_by_stock(cdir)
            }
        except Exception:
            ohlc_by_div[div] = {}

    def _pool_for(div: str) -> dict[str, dict[str, Any]]:
        pool = ohlc_by_div.get(div) if div else None
        if pool:
            return pool
        if div and csv_root.is_dir():
            try:
                return {
                    str(m.get("stock") or "").strip().upper(): m
                    for m in daily_csvs_by_stock(resolve_typed_dir(csv_root, div))
                }
            except Exception:
                pass
        if csv_root.is_dir() and not div:
            try:
                return {
                    str(m.get("stock") or "").strip().upper(): m
                    for m in daily_csvs_by_stock(resolve_typed_dir(csv_root, DEFAULT_DIVIDEND_TYPE))
                }
            except Exception:
                pass
        return ohlc_by_div.get("") or {}

    for stock, rec in stocks.items():
        if rec.get("by_div"):
            rec["style"] = _empty_style()
            for div, drec in rec["by_div"].items():
                pool = _pool_for(str(div))
                style, path, err = _style_from_csv_meta((pool or {}).get(stock), stock)
                drec["style"] = style
                if path:
                    drec["csv"] = path
                if err:
                    rec["error"] = (rec.get("error") or "") + err
                if (style.get("n_close") or 0) and not (rec.get("style") or {}).get("n_close"):
                    rec["style"] = style
                    rec["csv"] = path
            continue
        pool = _pool_for("")
        if not pool:
            for extra in ohlc_by_div.values():
                if extra:
                    pool = extra
                    break
        style, path, err = _style_from_csv_meta((pool or {}).get(stock), stock)
        rec["style"] = style
        if path:
            rec["csv"] = path
        if err:
            rec["error"] = (rec.get("error") or "") + err

    book = load_book_stocks()
    score_years = infer_score_years(stocks)
    return {
        "stocks": stocks,
        "files": packed,
        "coverage": {
            "n_stock": len(stocks),
            "n_detail": n_files,
            "score_years": list(score_years),
        },
        "book": book,
        "score_years": score_years,
        "report_dir": str(report.resolve()),
        "csv_dir": str(data_dir.resolve()),
        "portfolio_kpi": {},
    }


def infer_score_years(stocks: dict[str, Any]) -> tuple[str, ...]:
    """打分用自然年：扫描到的分年文件全部纳入（含尚未走完的最大年）。"""
    found: set[str] = set()

    def add_years(years: dict | None) -> None:
        for y in years or {}:
            if str(y).isdigit():
                found.add(str(y))

    for rec in stocks.values():
        add_years(rec.get("years"))
        for mrec in (rec.get("by_ma") or {}).values():
            add_years(mrec.get("years"))
        for drec in (rec.get("by_div") or {}).values():
            add_years(drec.get("years"))
            for mrec in (drec.get("by_ma") or {}).values():
                add_years(mrec.get("years"))
    return tuple(sorted(found))


def list_score_years(report_dir: str | Path | None = None) -> tuple[str, ...]:
    """轻量年份发现：只 glob 文件名，不读 CSV、不算 KPI。"""
    report = Path(report_dir) if report_dir else resolve_typed_dir(
        DEFAULT_REPORT, DEFAULT_DIVIDEND_TYPE
    )
    found: set[str] = set()
    dirs = typed_sibling_dirs(report)
    if not dirs:
        dirs = [("", report)] if report.is_dir() else []
    for _div, rdir in dirs:
        if not rdir.is_dir():
            continue
        for item in list_detail_files(rdir):
            y = item.get("year")
            if y and str(y).isdigit():
                found.add(str(y))
        for p in rdir.glob("local_bt_book_score_*_操作明细.csv"):
            parts = p.stem.split("_")
            if len(parts) >= 5 and str(parts[4]).isdigit():
                found.add(str(parts[4]))
        for p in rdir.glob("local_bt_book_hold_*_操作明细.csv"):
            parts = p.stem.split("_")
            # local_bt_book_hold_{YYYY}_p{N}_k{hash}_操作明细
            if len(parts) >= 5 and str(parts[4]).isdigit():
                found.add(str(parts[4]))
    return tuple(sorted(found))


def years_in_range(
    available: tuple[str, ...],
    year_start: str = "",
    year_end: str = "",
) -> tuple[str, ...]:
    years = tuple(str(y) for y in available if str(y).isdigit())
    start = str(year_start or "").strip()
    end = str(year_end or "").strip()
    if start:
        years = tuple(y for y in years if y >= start)
    if end:
        years = tuple(y for y in years if y <= end)
    return years


def _coverage_from_stocks(
    stocks: dict[str, Any],
    *,
    n_detail: int | None = None,
    score_years: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    cov: dict[str, Any] = {}
    n_compare = 0
    n_no_compare = 0
    n_single = 0
    n_div_compare = 0
    n_div_single = 0
    n_div_miss = 0
    for rec in stocks.values():
        why = str(rec.get("ma_type_why") or "")
        if why in ("compare", "compare_close"):
            n_compare += 1
        elif why == "single_ma":
            n_single += 1
        else:
            n_no_compare += 1
        dwhy = str(rec.get("div_type_why") or "")
        if dwhy in ("compare", "compare_close"):
            n_div_compare += 1
        elif dwhy == "single_div":
            n_div_single += 1
        else:
            n_div_miss += 1
        for y in rec.get("years") or {}:
            if str(y).isdigit():
                key = str(y)
                cov[key] = int(cov.get(key) or 0) + 1
        if rec.get("recent"):
            cov[RECENT_KEY] = int(cov.get(RECENT_KEY) or 0) + 1
    years = score_years if score_years is not None else infer_score_years(stocks)
    cov.update(
        {
            "n_stock": len(stocks),
            "n_compare": n_compare,
            "n_no_compare": n_no_compare,
            "n_single_ma": n_single,
            "n_div_compare": n_div_compare,
            "n_div_single": n_div_single,
            "n_div_no_compare": n_div_miss,
            "score_years": list(years),
        }
    )
    if n_detail is not None:
        cov["n_detail"] = int(n_detail)
    return cov


def _year_kpis(rec: dict[str, Any], score_years: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    years = rec.get("years") or {}
    for y in score_years:
        k = years.get(y)
        if k:
            out.append(k)
    return out


def _agg_from_years(rec: dict[str, Any], score_years: tuple[str, ...]) -> dict[str, Any]:
    kpis = _year_kpis(rec, score_years)
    n_buy = sum(int(k.get("n_buy") or 0) for k in kpis)
    years_traded = [k for k in kpis if int(k.get("n_buy") or 0) > 0]
    n_years_traded = len(years_traded)
    n_years_pos = sum(1 for k in years_traded if float(k.get("sum_pnl") or 0) > 0)
    pnls = [float(k.get("sum_pnl") or 0.0) for k in kpis]
    pnl_mean = (sum(pnls) / len(pnls)) if pnls else None
    win_n = 0.0
    ret_w = 0.0
    gp = 0.0
    gl = 0.0
    holds = []
    dds = []
    max_win_pnl = 0.0
    sell: Counter[str] = Counter()
    buy: Counter[str] = Counter()
    skip: Counter[str] = Counter()
    n_bars = 0
    for k in kpis:
        nb = float(k.get("n_buy") or 0)
        win_n += float(k.get("win_rate") or 0) / 100.0 * nb
        ret_w += float(k.get("avg_ret") or 0) * nb
        gp += float(k.get("gross_profit") or 0)
        gl += float(k.get("gross_loss") or 0)
        if k.get("avg_hold_days") is not None and nb > 0:
            holds.append((float(k["avg_hold_days"]), nb))
        if k.get("max_dd") is not None:
            dds.append(float(k["max_dd"]))
        max_win_pnl = max(max_win_pnl, float(k.get("max_win_pnl") or 0))
        _add_counter(sell, k.get("sell"))
        _add_counter(buy, k.get("buy"))
        _add_counter(skip, k.get("skip"))
        n_bars += int(k.get("n_bars") or 0)
    win_rate = (100.0 * win_n / n_buy) if n_buy else None
    avg_ret = (ret_w / n_buy) if n_buy else None
    hold = (sum(h * w for h, w in holds) / sum(w for _h, w in holds)) if holds else None
    n_sell = sum(sell.values())
    trail = float(sell.get("trail_stop") or 0)
    stop = float(sell.get("stop_loss") or 0)
    bear = float(sell.get("weekly_bear") or 0)
    trail_share = (trail / n_sell) if n_sell else None
    stop_share = (stop / n_sell) if n_sell else None
    bear_share = (bear / n_sell) if n_sell else None
    quality = None
    if n_sell:
        quality = trail_share - stop_share - bear_share
    bias_n = int(skip.get("w_bias_skip") or 0)
    bias_density = (bias_n / n_bars) if n_bars else None
    win_share = (max_win_pnl / gp) if gp > 1e-9 else None
    recent = rec.get("recent") or {}
    year_pnl = {y: None for y in score_years}
    year_n = {y: None for y in score_years}
    for y in score_years:
        k = (rec.get("years") or {}).get(y)
        if k:
            year_pnl[y] = float(k.get("sum_pnl") or 0.0)
            year_n[y] = int(k.get("n_buy") or 0)
    return {
        "n_buy": n_buy,
        "n_years_files": len(kpis),
        "n_years_traded": n_years_traded,
        "n_years_pos": n_years_pos,
        "stability": (n_years_pos / n_years_traded) if n_years_traded else None,
        "pnl_year_mean": pnl_mean,
        "win_rate": win_rate,
        "avg_ret": avg_ret,
        "profit_factor": _profit_factor(gp, gl),
        "gross_profit": gp,
        "gross_loss": gl,
        "max_dd": min(dds) if dds else None,
        "avg_hold_days": hold,
        "max_win_pnl_share": win_share,
        "trail_share": trail_share,
        "stop_share": stop_share,
        "bear_share": bear_share,
        "quality": quality,
        "sell": dict(sell),
        "buy": dict(buy),
        "skip": dict(skip),
        "w_bias_skip_n": bias_n,
        "w_bias_density": bias_density,
        "n_bars": n_bars,
        "year_pnl": year_pnl,
        "year_n": year_n,
        "recent_pnl": float(recent.get("sum_pnl") or 0.0) if recent else None,
        "recent_n_buy": int(recent.get("n_buy") or 0) if recent else None,
        "recent_win_rate": float(recent.get("win_rate") or 0.0) if recent else None,
        "recent_sell": dict(recent.get("sell") or {}) if recent else {},
    }


def _pct_rank(s: pd.Series) -> pd.Series:
    return s.rank(method="average", pct=True)


def empty_year_kpi() -> dict[str, Any]:
    return {
        "n_buy": 0,
        "sum_pnl": 0.0,
        "win_rate": 0.0,
        "avg_ret": 0.0,
        "max_win": 0.0,
        "max_loss": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "profit_factor": None,
        "max_dd": None,
        "avg_hold_days": None,
        "max_win_pnl": 0.0,
        "budget": 0.0,
        "sell": {},
        "buy": {},
        "skip": {},
        "n_bars": 0,
    }


def _portfolio_score_filters(
    flt: dict[str, Any],
    score_years: tuple[str, ...],
) -> dict[str, Any]:
    """组合归因轮次少于单票独立回测，硬过滤按窗口年数放宽。"""
    out = dict(flt)
    ny = max(1, len(score_years))
    per = int(out.get("min_n_buy_per_year") or 0)
    if per > 0:
        out["min_n_buy"] = max(1, per * ny)
    else:
        base = int(out.get("min_n_buy") or 0)
        out["min_n_buy"] = max(1, ny if base <= 0 else min(base, ny * 2))
    out["max_win_pnl_share"] = 1.0
    return out


def _overlay_portfolio_kpi(
    resolved: dict[str, Any],
    portfolio_kpi: dict[str, Any],
    score_years: tuple[str, ...],
) -> None:
    for stock, rec in resolved.items():
        pk = portfolio_kpi.get(stock) or {}
        years: dict[str, Any] = {}
        for y in score_years:
            k = pk.get(str(y))
            years[str(y)] = dict(k) if k else empty_year_kpi()
        rec["years"] = years


def score_universe(
    scanned: dict[str, Any],
    filters: dict[str, Any] | None = None,
    score_years: tuple[str, ...] | None = None,
    *,
    kpi_source: str = "single",
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """硬过滤 + 百分位加权打分。score_years 内重跑建议均线/复权，不改扫描缓存。"""
    flt = dict(DEFAULT_FILTERS)
    if filters:
        flt.update(filters)
    wt = dict(WEIGHTS)
    if weights:
        wt.update(weights)
    book: dict[str, str] = dict(scanned.get("book") or {})
    raw_stocks: dict[str, Any] = dict(scanned.get("stocks") or {})
    portfolio_kpi: dict[str, Any] = dict(scanned.get("portfolio_kpi") or {})
    kpi_src = str(kpi_source or "single").strip().lower()
    available = infer_score_years(raw_stocks)
    requested = score_years
    if requested is None:
        requested = tuple(scanned.get("score_years") or available)
    requested = tuple(str(y) for y in requested)
    if available:
        keep = set(available)
        requested = tuple(y for y in requested if y in keep)
    score_years = requested if requested else (available or SCORE_YEARS)
    if kpi_src == "portfolio" and score_years:
        flt = _portfolio_score_filters(flt, score_years)

    resolved: dict[str, Any] = {}
    for stock, rec in raw_stocks.items():
        resolved[stock] = _apply_year_window(rec, score_years)
    if kpi_src == "portfolio" and portfolio_kpi:
        _overlay_portfolio_kpi(resolved, portfolio_kpi, score_years)
    n_detail = (scanned.get("coverage") or {}).get("n_detail")
    cov = _coverage_from_stocks(resolved, n_detail=n_detail, score_years=score_years)

    rows: list[dict[str, Any]] = []
    details: dict[str, Any] = {}
    vols: list[float] = []
    touches: list[float] = []
    aggs: dict[str, dict[str, Any]] = {}
    for stock, rec in resolved.items():
        agg = _agg_from_years(rec, score_years)
        aggs[stock] = agg
        style = rec.get("style") or {}
        v = style.get("vol_ann")
        t = style.get("touch_ma20")
        if v is not None and np.isfinite(v):
            vols.append(float(v))
        if t is not None and np.isfinite(t):
            touches.append(float(t))

    vol_cut = None
    if vols:
        drop = float(flt.get("vol_drop_top") or 0.0)
        drop = min(max(drop, 0.0), 0.5)
        vol_cut = float(np.quantile(vols, 1.0 - drop)) if drop > 0 else None
    touch_med = float(np.median(touches)) if touches else None
    vol_med = float(np.median(vols)) if vols else None

    min_n_buy = int(flt.get("min_n_buy") or 0)
    min_per_year = int(flt.get("min_n_buy_per_year") or 0)
    min_years = int(flt.get("min_years_traded") or 0)
    min_pos = int(flt.get("min_pos_years") or 0)
    min_ratio = float(flt.get("min_pos_ratio") or 0.0)
    max_win_share = float(flt.get("max_win_pnl_share") or 1.0)

    for stock, rec in resolved.items():
        agg = aggs[stock]
        style = rec.get("style") or {}
        vol = style.get("vol_ann")
        touch = style.get("touch_ma20")
        reasons: list[str] = []
        year_n = agg.get("year_n") or {}
        n_buy_year_min = min(int(year_n.get(y) or 0) for y in score_years) if score_years else 0
        if int(agg["n_buy"] or 0) < min_n_buy:
            reasons.append("轮次不足")
        if min_per_year > 0 and n_buy_year_min < min_per_year:
            reasons.append("每年轮次不足")
        if int(agg["n_years_traded"] or 0) < min_years:
            reasons.append("成交年数不足")
        n_pos = int(agg["n_years_pos"] or 0)
        n_tr = int(agg["n_years_traded"] or 0)
        ratio = (n_pos / n_tr) if n_tr else 0.0
        if n_pos < min_pos and ratio < min_ratio:
            reasons.append("盈利年不稳定")
        share = agg.get("max_win_pnl_share")
        if share is not None and share > max_win_share and float(agg.get("gross_profit") or 0) > 0:
            reasons.append("单笔盈利占比过高")
        if vol_cut is not None and vol is not None and float(vol) > vol_cut:
            reasons.append("波动过高")
        ma_type = str(rec.get("ma_type_suggest") or "")
        ma_why = str(rec.get("ma_type_why") or "no_compare")
        recent_n = agg.get("recent_n_buy")
        recent_pnl = agg.get("recent_pnl")
        recent_flag = "无近期"
        if recent_n is not None:
            if int(recent_n) <= 0:
                recent_flag = "近期无成交"
            elif recent_pnl is not None and float(recent_pnl) > 0:
                recent_flag = "近期盈利"
            else:
                recent_flag = "近期亏损"
        row = {
            "stock": stock,
            "passed": not reasons,
            "fail_reason": "；".join(reasons),
            "in_book": stock in book,
            "ma_type_suggest": ma_type,
            "ma_type_why": ma_why,
            "ma_pnl_sma": rec.get("ma_pnl_sma"),
            "ma_pnl_ema": rec.get("ma_pnl_ema"),
            "ma_pnl_delta": rec.get("ma_pnl_delta"),
            "div_type_suggest": rec.get("div_type_suggest") or "",
            "div_type_why": rec.get("div_type_why") or "no_compare",
            "n_buy": agg["n_buy"],
            "n_buy_year_min": n_buy_year_min,
            "n_years_traded": agg["n_years_traded"],
            "n_years_pos": agg["n_years_pos"],
            "n_years_files": agg["n_years_files"],
            "stability": agg["stability"],
            "pnl_year_mean": agg["pnl_year_mean"],
            "win_rate": agg["win_rate"],
            "avg_ret": agg["avg_ret"],
            "profit_factor": agg["profit_factor"],
            "quality": agg["quality"],
            "trail_share": agg["trail_share"],
            "stop_share": agg["stop_share"],
            "bear_share": agg["bear_share"],
            "max_dd": agg["max_dd"],
            "avg_hold_days": agg["avg_hold_days"],
            "w_bias_skip_n": agg["w_bias_skip_n"],
            "w_bias_density": agg["w_bias_density"],
            "vol_ann": vol,
            "touch_ma20": touch,
            "recent_flag": recent_flag,
            "recent_n_buy": recent_n,
            "recent_pnl": recent_pnl,
            "error": rec.get("error") or "",
        }
        for y in score_years:
            row["pnl_%s" % y] = agg["year_pnl"].get(y)
            row["n_buy_%s" % y] = agg["year_n"].get(y)
        rows.append(row)
        details[stock] = {
            "years": rec.get("years") or {},
            "recent": rec.get("recent"),
            "sell": agg["sell"],
            "buy": agg["buy"],
            "skip": agg["skip"],
            "style": style,
        }

    df = pd.DataFrame(rows)
    if df.empty:
        return {
            "df": df,
            "passed": df,
            "heatmap": pd.DataFrame(),
            "details": details,
            "coverage": cov,
            "filters": flt,
            "book": book,
            "book_rank": pd.DataFrame(),
            "recommend": pd.DataFrame(),
            "snippet": "BOOK_STOCKS = {}",
            "vol_cut": vol_cut,
            "score_years": score_years,
        }

    passed_mask = df["passed"].astype(bool)
    score = pd.Series(0.0, index=df.index)
    if passed_mask.any():
        sub = df.loc[passed_mask]
        pnl_r = _pct_rank(sub["pnl_year_mean"])
        wr_r = _pct_rank(sub["win_rate"])
        st_r = _pct_rank(sub["stability"])
        pf_r = _pct_rank(sub["profit_factor"])
        q_r = _pct_rank(sub["quality"])
        part = (
            wt["pnl"] * pnl_r.fillna(0.5)
            + wt["win_rate"] * wr_r.fillna(0.5)
            + wt["stability"] * st_r.fillna(0.5)
            + wt["profit_factor"] * pf_r.fillna(0.5)
            + wt["quality"] * q_r.fillna(0.5)
        )
        score.loc[passed_mask] = part
        df.loc[passed_mask, "score_pnl"] = pnl_r
        df.loc[passed_mask, "score_win"] = wr_r
        df.loc[passed_mask, "score_stab"] = st_r
        df.loc[passed_mask, "score_pf"] = pf_r
        df.loc[passed_mask, "score_qual"] = q_r
    df["score"] = score
    df.loc[~passed_mask, "score"] = np.nan
    df["rank"] = np.nan
    if passed_mask.any():
        df.loc[passed_mask, "rank"] = (
            df.loc[passed_mask, "score"].rank(ascending=False, method="min").astype(int)
        )
    df = df.sort_values(["passed", "score", "pnl_year_mean"], ascending=[False, False, False], na_position="last")
    df = df.reset_index(drop=True)

    passed = df[df["passed"]].copy()
    heat_cols = ["stock"] + ["pnl_%s" % y for y in score_years] + ["recent_pnl"]
    heat_cols = [c for c in heat_cols if c in (passed.columns if not passed.empty else heat_cols)]
    heatmap = passed[heat_cols].copy() if not passed.empty else pd.DataFrame(columns=heat_cols)

    book_rank = df[df["in_book"]].copy()
    top_n = clamp_top_n(flt.get("top_n"))
    flt = dict(flt)
    flt["top_n"] = top_n
    recommend = passed.head(top_n).copy()
    snippet = format_book_snippet(recommend)

    return {
        "df": df,
        "passed": passed,
        "heatmap": heatmap,
        "details": details,
        "coverage": cov,
        "filters": flt,
        "book": book,
        "book_rank": book_rank,
        "recommend": recommend,
        "snippet": snippet,
        "vol_cut": vol_cut,
        "score_years": score_years,
    }


def format_book_snippet(recommend: pd.DataFrame) -> str:
    if recommend is None or recommend.empty:
        return "BOOK_STOCKS = {}"
    lines = ["BOOK_STOCKS = {"]
    n = 0
    for _, r in recommend.iterrows():
        kind = str(r.get("ma_type_suggest") or "").strip().upper()
        if kind not in ("SMA", "EMA"):
            continue
        fields = ['"ma_type": "%s"' % kind]
        div = str(r.get("div_type_suggest") or "").strip().lower()
        if div in DIVIDEND_TYPES:
            fields.append('"dividend_type": "%s"' % div)
        lines.append('    "%s": {%s},' % (r["stock"], ", ".join(fields)))
        n += 1
    lines.append("}")
    if n == 0:
        return "BOOK_STOCKS = {}"
    return "\n".join(lines)


def coverage_notes(coverage: dict[str, Any], scanned: dict[str, Any] | None = None) -> list[str]:
    notes = []
    n = int(coverage.get("n_stock") or 0)
    notes.append("扫描到 **%s** 只标的的本地回测产物。" % n)
    years = [k for k in sorted(coverage) if str(k).isdigit()]
    ycounts = ["%s 年 %s 只" % (y, int(coverage.get(y) or 0)) for y in years]
    if ycounts:
        notes.append("分年覆盖：%s；无年份（近期）%s 只。" % (" / ".join(ycounts), int(coverage.get(RECENT_KEY) or 0)))
    score_years = coverage.get("score_years") or ((scanned or {}).get("score_years") or SCORE_YEARS)
    notes.append(
        "主排序使用分年回测 **%s**（含尚未走完的最大年，年等权盈亏把该年当作一整年）；无年份整段文件只作近期确认。"
        % "、".join(str(y) for y in score_years)
    )
    if years and len(years) >= 2:
        last, prev = years[-1], years[-2]
        if int(coverage.get(prev) or 0) and int(coverage.get(last) or 0) < int(0.9 * int(coverage.get(prev) or 0)):
            notes.append("%s 年批明显少于 %s，覆盖不齐。" % (last, prev))
    notes.append(
        "建议均线/复权按选定年 **%s** 重算（成对年份总盈亏择优）；白名单不覆盖建议。"
        % "、".join(str(y) for y in score_years)
    )
    n_cmp = int(coverage.get("n_compare") or 0)
    n_miss = int(coverage.get("n_no_compare") or 0)
    n_single = int(coverage.get("n_single_ma") or 0)
    notes.append(
        "均线对照：成对 **%s** 只 · 单边 %s 只 · 缺对照 %s 只。"
        % (n_cmp, n_single, n_miss)
    )
    if n_cmp == 0:
        notes.append("没有成对均线对照文件。请先跑「批量 + 按自然年分段 + SMA/EMA 对照」。")
    n_dc = int(coverage.get("n_div_compare") or 0)
    n_ds = int(coverage.get("n_div_single") or 0)
    n_dm = int(coverage.get("n_div_no_compare") or 0)
    notes.append(
        "复权对照：成对 **%s** 只 · 单边 %s 只 · 缺对照 %s 只。"
        % (n_dc, n_ds, n_dm)
    )
    if n_dc == 0:
        notes.append(
            "没有多种复权的分年对照。请先多选复权跑「批量 + 按自然年分段」（建议同时勾 SMA/EMA 对照）。"
        )
    notes.append("选股扫描 `report/` 下全部复权子目录，不限于侧栏勾选。")
    notes.append("在全池里取 Top N 有多重选择偏差，不要把得分当分真实夏普。")
    book = (scanned or {}).get("book") or {}
    if book:
        notes.append("现白名单：%s" % "、".join(sorted(book)))
    return notes


def select_csv_columns(score_years: tuple[str, ...] | None = None) -> list[str]:
    years = score_years or SCORE_YEARS
    cols = [
        "rank",
        "stock",
        "passed",
        "score",
        "fail_reason",
        "in_book",
        "ma_type_suggest",
        "ma_type_why",
        "ma_pnl_sma",
        "ma_pnl_ema",
        "ma_pnl_delta",
        "div_type_suggest",
        "div_type_why",
        "n_buy",
        "n_buy_year_min",
        "n_years_traded",
        "n_years_pos",
        "stability",
        "pnl_year_mean",
        "win_rate",
        "avg_ret",
        "profit_factor",
        "quality",
        "trail_share",
        "stop_share",
        "bear_share",
        "max_dd",
        "avg_hold_days",
        "w_bias_skip_n",
        "w_bias_density",
        "vol_ann",
        "touch_ma20",
        "recent_flag",
        "recent_n_buy",
        "recent_pnl",
    ]
    for y in years:
        cols.append("pnl_%s" % y)
        cols.append("n_buy_%s" % y)
    cols.append("error")
    return cols


def write_select_csv(df: pd.DataFrame, path: str | Path) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    years = []
    if df is not None and not df.empty:
        for c in df.columns:
            if str(c).startswith("pnl_") and str(c) != "pnl_year_mean":
                years.append(str(c).replace("pnl_", "", 1))
    years = tuple(years) if years else SCORE_YEARS
    preferred = select_csv_columns(years)
    cols = [c for c in preferred if df is not None and c in df.columns]
    extra = [c for c in (df.columns if df is not None else []) if c not in cols]
    out = df[cols + extra].copy() if df is not None and not df.empty else pd.DataFrame(columns=preferred)
    out.to_csv(dest, index=False, encoding="utf-8-sig")
    return dest


def run_select(
    report_dir: str | Path | None = None,
    csv_dir: str | Path | None = None,
    out: str | Path | None = None,
    filters: dict[str, Any] | None = None,
    scanned: dict[str, Any] | None = None,
    progress: bool = False,
    score_years: tuple[str, ...] | None = None,
    year_start: str = "",
    year_end: str = "",
) -> dict[str, Any]:
    packed = scanned if scanned is not None else scan_reports(report_dir, csv_dir, progress=progress)
    years = score_years
    if years is None and (year_start or year_end):
        years = years_in_range(
            infer_score_years(packed.get("stocks") or {}),
            year_start,
            year_end,
        )
    scored = score_universe(packed, filters=filters, score_years=years)
    dest = Path(out) if out else (
        Path(report_dir)
        if report_dir
        else resolve_typed_dir(DEFAULT_REPORT, DEFAULT_DIVIDEND_TYPE)
    ) / "local_bt_stock_select.csv"
    scored["out_csv"] = str(write_select_csv(scored["df"], dest))
    scored["scanned"] = packed
    return scored


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="HlBand 批量回测选股打分")
    ap.add_argument(
        "--dividend-type",
        default=DEFAULT_DIVIDEND_TYPE,
        metavar="TYPE",
        help="复权类型 none|front|back|front_ratio|back_ratio（默认 front_ratio）",
    )
    ap.add_argument("--report-dir", default="", help="local_bt 报告根目录或已解析的 <type> 子目录")
    ap.add_argument("--csv-dir", default="", help="日线 CSV 根目录或已解析的 <type> 子目录")
    ap.add_argument(
        "--out",
        default="",
        help="输出 CSV（默认 report 根目录 local_bt_stock_select.csv）",
    )
    ap.add_argument("--min-n-buy", type=int, default=DEFAULT_FILTERS["min_n_buy"])
    ap.add_argument(
        "--min-n-buy-year",
        type=int,
        default=DEFAULT_FILTERS["min_n_buy_per_year"],
        help="窗口内每一年最少买入轮次（缺文件按 0；0 表示不启用）",
    )
    ap.add_argument("--min-years", type=int, default=DEFAULT_FILTERS["min_years_traded"])
    ap.add_argument("--min-pos-years", type=int, default=DEFAULT_FILTERS["min_pos_years"])
    ap.add_argument("--min-pos-ratio", type=float, default=DEFAULT_FILTERS["min_pos_ratio"])
    ap.add_argument("--max-win-share", type=float, default=DEFAULT_FILTERS["max_win_pnl_share"])
    ap.add_argument("--vol-drop-top", type=float, default=DEFAULT_FILTERS["vol_drop_top"])
    ap.add_argument("--top-n", type=int, default=DEFAULT_FILTERS["top_n"])
    ap.add_argument("--year-start", default="", help="打分起始年（含），默认扫描到的最早年")
    ap.add_argument("--year-end", default="", help="打分结束年（含），默认扫描到的最晚年")
    args = ap.parse_args(argv)
    div_raw = str(args.dividend_type or "").strip()
    div = normalize_dividend_type(div_raw) if div_raw else DEFAULT_DIVIDEND_TYPE
    if div_raw and not normalize_dividend_type(div_raw):
        raise SystemExit("--dividend-type must be none|front|back|front_ratio|back_ratio")
    csv_dir = str(resolve_typed_dir(args.csv_dir or DEFAULT_CSV_DIR, div))
    report_dir = str(resolve_typed_dir(args.report_dir or DEFAULT_REPORT, div))
    filters = {
        "min_n_buy": args.min_n_buy,
        "min_n_buy_per_year": args.min_n_buy_year,
        "min_years_traded": args.min_years,
        "min_pos_years": args.min_pos_years,
        "min_pos_ratio": args.min_pos_ratio,
        "max_win_pnl_share": args.max_win_share,
        "vol_drop_top": args.vol_drop_top,
        "top_n": args.top_n,
    }
    out = args.out or str(typed_dir_root(report_dir) / "local_bt_stock_select.csv")
    print("scanning", report_dir, csv_dir, flush=True)
    scored = run_select(
        report_dir=report_dir,
        csv_dir=csv_dir,
        out=out,
        filters=filters,
        progress=True,
        year_start=str(args.year_start or ""),
        year_end=str(args.year_end or ""),
    )
    cov = scored.get("coverage") or {}
    for line in coverage_notes(cov, scored.get("scanned")):
        print(re.sub(r"\*\*", "", line))
    passed = scored.get("passed")
    n_pass = 0 if passed is None or passed.empty else len(passed)
    print("passed", n_pass, "/", cov.get("n_stock"), "wrote", scored.get("out_csv"))
    rec = scored.get("recommend")
    if rec is not None and not rec.empty:
        print("recommend")
        cols = ["rank", "stock", "score", "pnl_year_mean", "win_rate", "stability", "ma_type_suggest"]
        if "div_type_suggest" in rec.columns:
            cols.append("div_type_suggest")
        show = rec[cols]
        print(show.to_string(index=False))
        print(scored.get("snippet") or "")


if __name__ == "__main__":
    main()
