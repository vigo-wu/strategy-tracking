# coding: utf-8
"""walk-forward 数据分析：每换仓段手工篮子 + 持有回放。"""
from __future__ import annotations

import argparse
import json
import pickle
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ProgressCb = Callable[[dict[str, Any]], None] | None

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from analyze import DEFAULT_DIVIDEND_TYPE, DEFAULT_REPORT_ROOT, resolve_typed_dir  # noqa: E402
from batch_job import run_score_year  # noqa: E402
from book_backtest import (  # noqa: E402
    analyze_book_detail,
    book_log_name,
    book_stocks_hash,
    normalize_book_stocks,
    run_book_backtest,
)
from compound_wallet import parse_wallet_from_log  # noqa: E402
from select_config import (  # noqa: E402
    DEFAULT_FILTERS,
    clamp_top_n,
    coerce_book_stocks_dict,
    is_year_keyed_baskets,
    load_book_defaults,
    load_book_stocks_full,
    parse_book_stocks_text,
)
from stock_select import (  # noqa: E402
    _apply_year_window,
    infer_score_years,
    list_score_years,
    score_universe,
)
from trades_csv import trades_csv_path  # noqa: E402

MA_TYPES = ("SMA", "EMA")


def pick_details_from_basket(
    basket: dict[str, Any] | None,
    scores: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """从组合 basket 生成 year_rows.pick_details（含均线/复权；score 可选）。"""
    out: list[dict[str, Any]] = []
    score_map = {str(k).upper(): v for k, v in (scores or {}).items()}
    for code in sorted((basket or {}).keys()):
        cfg = (basket or {}).get(code) or {}
        if not isinstance(cfg, dict):
            cfg = {"ma_type": str(cfg), "dividend_type": DEFAULT_DIVIDEND_TYPE}
        key = str(code).upper()
        row: dict[str, Any] = {
            "stock": key,
            "ma_type": str(cfg.get("ma_type") or "").upper(),
            "dividend_type": str(cfg.get("dividend_type") or DEFAULT_DIVIDEND_TYPE).lower(),
        }
        if key in score_map:
            row["score"] = score_map[key]
        out.append(row)
    return out


def picks_from_scored(
    scored: dict[str, Any] | None,
    top_k: int,
) -> tuple[list[dict[str, Any]], str]:
    """Walk-forward 选股：硬过滤通过者优先，不足 top_k 时按总分从其余补足。

    返回 (picks, note)。note 非空表示发生了补足或仍不足。
    """
    k = clamp_top_n(top_k, fallback=3)
    df = None
    if scored:
        rec = scored.get("recommend")
        df = scored.get("df")
        if df is None or (hasattr(df, "empty") and df.empty):
            df = rec
    if df is None or (hasattr(df, "empty") and df.empty):
        return [], ""
    picks: list[dict[str, Any]] = []
    seen: set[str] = set()
    n_passed = 0
    for _, r in df.iterrows():
        if len(picks) >= k:
            break
        stock = str(r.get("stock") or "").strip().upper()
        if not stock or stock in seen:
            continue
        ma = str(r.get("ma_type_suggest") or r.get("ma_type") or "").upper()
        if ma not in MA_TYPES:
            ma = "EMA"
        div = str(r.get("div_type_suggest") or r.get("div_type") or DEFAULT_DIVIDEND_TYPE).lower()
        if not div:
            div = DEFAULT_DIVIDEND_TYPE
        seen.add(stock)
        if bool(r.get("passed")):
            n_passed += 1
        picks.append(
            {
                "stock": stock,
                "score": r.get("score"),
                "ma_type": ma,
                "div_type": div,
            }
        )
    note = ""
    if len(picks) < k:
        note = "硬过滤后可交易不足 %s 只，仅选出 %s 只" % (k, len(picks))
    elif n_passed < k:
        note = "硬过滤仅 %s 只过线，已按分数补足至 %s 只" % (n_passed, k)
    return picks, note


def iter_rebalance_periods(
    eval_years: tuple[str, ...],
    rebalance_years: int,
) -> list[dict[str, Any]]:
    years = tuple(str(y) for y in eval_years if str(y).isdigit())
    r = max(1, int(rebalance_years or 1))
    out: list[dict[str, Any]] = []
    i = 0
    period_i = 0
    while i < len(years):
        chunk = years[i : i + r]
        if not chunk:
            break
        period_i += 1
        out.append(
            {
                "period_i": period_i,
                "select_year": chunk[0],
                "hold_years": chunk,
            }
        )
        i += r
    return out


def _copy_book(book: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    return {str(k): dict(v) for k, v in (book or {}).items()}


def hold_years_for_range(
    data_start: str,
    data_end: str,
    available: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """评估/持有年：有扫描年则与区间求交；否则用日历年 data_start–data_end。"""
    ds, de = str(data_start or "").strip(), str(data_end or "").strip()
    if ds and de and de < ds:
        ds, de = de, ds
    scanned_years = tuple(str(y) for y in (available or ()) if str(y).isdigit())
    if scanned_years:
        if ds and de:
            return tuple(y for y in scanned_years if ds <= y <= de)
        return scanned_years
    if ds.isdigit() and de.isdigit() and len(ds) == 4 and len(de) == 4:
        return tuple(str(y) for y in range(int(ds), int(de) + 1))
    return ()


def resolve_period_basket(
    raw: Any,
    fallback: dict[str, Any] | None = None,
) -> dict[str, dict[str, str]]:
    """段内篮子：None 回落 fallback；空 dict/list 表示未配置。"""
    fb = normalize_book_stocks(fallback or {})
    if raw is None:
        return _copy_book(fb)
    if raw == {} or raw == []:
        return {}
    out: dict[str, Any] = {}
    if isinstance(raw, (list, tuple)):
        for item in raw:
            stock = str(item or "").strip().upper()
            if not stock:
                continue
            if stock in fb:
                out[stock] = dict(fb[stock])
            else:
                out[stock] = {"ma_type": "EMA", "dividend_type": DEFAULT_DIVIDEND_TYPE}
        return normalize_book_stocks(out)
    if isinstance(raw, dict):
        for k, v in raw.items():
            stock = str(k or "").strip().upper()
            if not stock:
                continue
            base = dict(fb.get(stock) or {"ma_type": "EMA", "dividend_type": DEFAULT_DIVIDEND_TYPE})
            if isinstance(v, dict):
                ma = v.get("ma_type") or base.get("ma_type") or "EMA"
                div = v.get("dividend_type") or base.get("dividend_type") or DEFAULT_DIVIDEND_TYPE
                out[stock] = {"ma_type": ma, "dividend_type": div}
            elif isinstance(v, str) and v.strip():
                out[stock] = {"ma_type": v, "dividend_type": base.get("dividend_type") or DEFAULT_DIVIDEND_TYPE}
            else:
                out[stock] = base
        return normalize_book_stocks(out)
    return _copy_book(fb)


def period_baskets_from_book(
    periods: list[dict[str, Any]],
    book: dict[str, Any] | None = None,
) -> dict[str, dict[str, dict[str, str]]]:
    basket = normalize_book_stocks(book if book is not None else load_book_stocks_full())
    out: dict[str, dict[str, dict[str, str]]] = {}
    for p in periods:
        out[str(p.get("select_year") or "")] = _copy_book(basket)
    return out


def load_picks_file(path: str | Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """读 picks 文件：按年 dict → (period_baskets, None)；单篮子 → (None, book)。"""
    data = parse_book_stocks_text(Path(path).read_text(encoding="utf-8"))
    if is_year_keyed_baskets(data):
        return {str(k): v for k, v in data.items()}, None
    return None, coerce_book_stocks_dict(data)


def load_period_baskets_json(path: str | Path) -> dict[str, Any]:
    periods, _book = load_picks_file(path)
    if periods is None:
        raise ValueError("picks 须为 {换仓年: 篮子}；单篮子请用 CLI 同一文件（会应用到全部段）")
    return periods


def score_years_for_period(
    select_year: str,
    lookback_n: int,
    year_pool: tuple[str, ...],
) -> tuple[str, ...]:
    """select_year 之前、且在 year_pool 内的最近 lookback_n 个自然年。"""
    y0 = str(select_year)
    n = max(1, int(lookback_n or 1))
    prior = tuple(str(y) for y in year_pool if str(y).isdigit() and str(y) < y0)
    if len(prior) < n:
        return ()
    return prior[-n:]


def data_and_eval_years(
    data_start: str,
    data_end: str,
    lookback_n: int,
    available: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """起止年为数据/KPI 年；首评年 = 数据区间内已有 lookback_n 个 prior 的最早年。"""
    ds, de = str(data_start or "").strip(), str(data_end or "").strip()
    if ds and de and de < ds:
        ds, de = de, ds
    data_years = tuple(str(y) for y in available if str(y).isdigit() and ds <= str(y) <= de)
    n = max(1, int(lookback_n or 1))
    eval_years = tuple(
        y
        for y in data_years
        if sum(1 for d in data_years if d < y) >= n
    )
    return data_years, eval_years


def collect_score_years(
    periods: list[dict[str, Any]],
    lookback_n: int,
    year_pool: tuple[str, ...],
) -> tuple[str, ...]:
    found: set[str] = set()
    for p in periods:
        sy = score_years_for_period(str(p["select_year"]), lookback_n, year_pool)
        found.update(sy)
    return tuple(sorted(found))


def build_score_pool(
    scanned: dict[str, Any],
    *,
    pool_mode: str = "scanned",
    filters: dict[str, Any] | None = None,
) -> dict[str, dict[str, str]]:
    stocks: dict[str, Any] = dict(scanned.get("stocks") or {})
    avail = infer_score_years(stocks)
    if not avail:
        return {}
    resolved: dict[str, dict[str, str]] = {}
    for stock, rec in stocks.items():
        w = _apply_year_window(rec, avail)
        ma = str(w.get("ma_type_suggest") or "").upper()
        div = str(w.get("div_type_suggest") or DEFAULT_DIVIDEND_TYPE).lower()
        if ma not in MA_TYPES:
            continue
        resolved[str(stock).upper()] = {"ma_type": ma, "dividend_type": div}

    mode = str(pool_mode or "scanned").strip().lower()
    if mode != "passed_prefilter" or not resolved:
        return resolved

    flt = dict(DEFAULT_FILTERS)
    if filters:
        flt.update(filters)
    flt["min_n_buy"] = max(0, int(flt.get("min_n_buy") or 0) // 2)
    flt["min_years_traded_ratio"] = max(
        0.0, float(flt.get("min_years_traded_ratio") or 0.0) - 0.10
    )
    sub = {k: v for k, v in stocks.items() if k in resolved}
    if not sub:
        return resolved
    scored = score_universe(
        {**scanned, "stocks": sub},
        filters=flt,
        score_years=avail,
        kpi_source="single",
    )
    passed = scored.get("passed")
    if passed is None or passed.empty:
        return resolved
    keep = set(passed["stock"].astype(str).tolist())
    return {k: v for k, v in resolved.items() if k in keep}


def _book_overrides(book_params: dict[str, Any]) -> dict[str, Any]:
    bp = dict(book_params or load_book_defaults())
    return {
        "TRADE_BUDGET": float(bp.get("trade_budget") or bp.get("TRADE_BUDGET") or 100000.0),
        "BOOK_LOT_MAX": int(bp.get("book_lot_max") or bp.get("BOOK_LOT_MAX") or 3),
        "LOT_OPEN_FRAC": float(bp.get("lot_open_frac") or bp.get("LOT_OPEN_FRAC") or 0.5),
        "LOT_ADD_FRAC": float(bp.get("lot_add_frac") or bp.get("LOT_ADD_FRAC") or 0.3),
    }


def _emit_wf_progress(
    on_progress: ProgressCb,
    *,
    phase: str,
    done: int,
    total: int,
    year: str = "",
    action: str = "",
    label: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    if not on_progress:
        return
    on_progress(
        {
            "phase": str(phase or ""),
            "done": int(done),
            "total": max(int(total), 0),
            "year": str(year or ""),
            "action": str(action or ""),
            "label": str(label or ""),
            "extra": dict(extra or {}),
        }
    )


def _score_trades_path(payload: dict[str, Any]) -> Path:
    out_dir = Path(payload["out_dir"])
    log_name = book_log_name(kind="score", year=str(payload["year"]), tag=str(payload["tag"]))
    return out_dir / log_name.replace(".txt", "_操作明细.csv")


def _score_cache_likely(payload: dict[str, Any]) -> bool:
    return _score_trades_path(payload).is_file() and not bool(payload.get("force_rerun"))


def _run_score_year_job(payload: dict[str, Any]) -> dict[str, Any]:
    """串行路径 / 单测入口；并行必须走 batch_job.run_score_year。"""
    return run_score_year(payload)


def _score_parallel_workers(requested: int, n_jobs: int, n_pool: int = 0) -> int:
    """按用户填写的进程数并行；0/1=顺序。n_pool 仅兼容旧调用。"""
    del n_pool
    w = max(0, int(requested or 0))
    if w <= 1 or int(n_jobs or 0) <= 1:
        return 1
    return max(1, min(w, int(n_jobs)))


def _run_score_jobs_subprocess(
    jobs: list[dict[str, Any]],
    *,
    n_workers: int,
    n_pool: int,
    get_done: Callable[[], int],
    total: int,
    on_progress: ProgressCb,
    finish_row: Callable[[dict[str, Any]], None],
) -> list[dict[str, Any]]:
    """独立 python 子进程跑打分年，避开 Streamlit + ProcessPool 的 ScriptRunContext 卡死。"""
    results: list[dict[str, Any]] = []
    queue = list(jobs)
    active: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    work = Path(tempfile.mkdtemp(prefix="hlband_score_"))
    script = str((HERE / "batch_job.py").resolve())

    def _spawn(job: dict[str, Any]) -> dict[str, Any]:
        tok = uuid.uuid4().hex
        inp = work / ("in_%s.pkl" % tok)
        outp = work / ("out_%s.pkl" % tok)
        inp.write_bytes(pickle.dumps(job, protocol=pickle.HIGHEST_PROTOCOL))
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            [sys.executable, script, "--score-year", str(inp), str(outp)],
            cwd=str(HERE),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
        return {
            "year": str(job["year"]),
            "proc": proc,
            "inp": inp,
            "outp": outp,
        }

    def _collect(slot: dict[str, Any]) -> dict[str, Any]:
        proc: subprocess.Popen = slot["proc"]
        outp: Path = slot["outp"]
        year = str(slot["year"])
        stdout_b, stderr_b = proc.communicate()
        try:
            if outp.is_file():
                row = pickle.loads(outp.read_bytes())
                if isinstance(row, dict):
                    return row
        except Exception as e:
            return {"year": year, "error": "读结果失败: %s" % e, "per_stock": {}}
        err = (stderr_b or b"").decode("utf-8", errors="replace").strip()
        out = (stdout_b or b"").decode("utf-8", errors="replace").strip()
        tip = err or out or ("exit=%s" % proc.returncode)
        return {"year": year, "error": tip[:500], "per_stock": {}}

    _emit_wf_progress(
        on_progress,
        phase="score",
        done=get_done(),
        total=total,
        year="",
        action="run",
        label="打分预计算 %s/%s · 子进程×%s · 池 %s 只 · 首年约数分钟"
        % (get_done(), total, n_workers, n_pool),
        extra={"pool_n": n_pool, "parallel": n_workers},
    )
    try:
        while queue or active:
            while queue and len(active) < n_workers:
                job = queue.pop(0)
                active.append(_spawn(job))
                _emit_wf_progress(
                    on_progress,
                    phase="score",
                    done=get_done(),
                    total=total,
                    year=str(job["year"]),
                    action="run",
                    label="打分预计算 %s/%s · 启动 %s · 在跑 %s · 池 %s 只"
                    % (
                        get_done(),
                        total,
                        job["year"],
                        "、".join(str(s["year"]) for s in active),
                        n_pool,
                    ),
                    extra={"pool_n": n_pool, "running": [str(s["year"]) for s in active]},
                )
            alive: list[dict[str, Any]] = []
            finished_any = False
            for slot in active:
                rc = slot["proc"].poll()
                if rc is None:
                    alive.append(slot)
                    continue
                finished_any = True
                row = _collect(slot)
                try:
                    slot["inp"].unlink(missing_ok=True)
                    slot["outp"].unlink(missing_ok=True)
                except Exception:
                    pass
                results.append(row)
                finish_row(row)
            active = alive
            if not finished_any:
                elapsed = int(time.perf_counter() - t0)
                running = "、".join(str(s["year"]) for s in active) or "-"
                _emit_wf_progress(
                    on_progress,
                    phase="score",
                    done=get_done(),
                    total=total,
                    year="",
                    action="run",
                    label="打分预计算 %s/%s · 子进程×%s 仍在跑 %s · 已等待 %ss · 池 %s 只"
                    % (get_done(), total, n_workers, running, elapsed, n_pool),
                    extra={
                        "pool_n": n_pool,
                        "parallel": n_workers,
                        "elapsed_s": elapsed,
                        "running": [str(s["year"]) for s in active],
                    },
                )
                time.sleep(2.0)
    finally:
        for slot in active:
            try:
                slot["proc"].kill()
            except Exception:
                pass
        try:
            for p in work.glob("*"):
                p.unlink(missing_ok=True)
            work.rmdir()
        except Exception:
            pass
    return results


def precompute_portfolio_kpis(
    scanned: dict[str, Any],
    score_years: tuple[str, ...],
    pool: dict[str, dict[str, str]],
    *,
    csv_root: str | Path,
    report_dir: str | Path,
    book_params: dict[str, Any] | None = None,
    force_rerun: bool = False,
    workers: int = 0,
    on_progress: ProgressCb = None,
    progress_done: int = 0,
    progress_total: int | None = None,
) -> dict[str, dict[str, Any]]:
    if not pool or not score_years:
        return dict(scanned.get("portfolio_kpi") or {})
    portfolio_kpi: dict[str, dict[str, Any]] = {}
    for stock in pool:
        portfolio_kpi[str(stock).upper()] = dict((scanned.get("portfolio_kpi") or {}).get(stock) or {})
    tag = book_stocks_hash(pool)
    overrides = _book_overrides(book_params)
    budget = float(overrides["TRADE_BUDGET"])
    out_dir = resolve_typed_dir(report_dir, DEFAULT_DIVIDEND_TYPE)
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = [
        {
            "year": y,
            "pool": pool,
            "tag": tag,
            "csv_root": str(csv_root),
            "out_dir": str(out_dir),
            "budget": budget,
            "overrides": overrides,
            "force_rerun": bool(force_rerun),
        }
        for y in score_years
    ]
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    score_paths: dict[str, str] = dict(scanned.get("score_detail_paths") or {})
    n_pool = len(pool)
    n_workers = _score_parallel_workers(int(workers or 0), len(jobs), n_pool)
    done = int(progress_done)
    total = int(progress_total) if progress_total is not None else (done + len(jobs))

    def _finish_score_row(row: dict[str, Any]) -> None:
        nonlocal done
        year = str(row.get("year") or "")
        if row.get("error"):
            action = "error"
            tip = "失败: %s" % row.get("error")
        elif row.get("cached"):
            action = "cache"
            tip = "缓存命中"
        else:
            action = "run"
            tip = "回测完成"
        done += 1
        _emit_wf_progress(
            on_progress,
            phase="score",
            done=done,
            total=total,
            year=year,
            action=action,
            label="打分预计算 %s/%s · %s · %s · 池 %s 只"
            % (done, total, year or "-", tip, n_pool),
            extra={"pool_n": n_pool, "cached": bool(row.get("cached")), "error": row.get("error")},
        )

    if n_workers <= 1:
        for j in jobs:
            year = str(j["year"])
            likely = _score_cache_likely(j)
            _emit_wf_progress(
                on_progress,
                phase="score",
                done=done,
                total=total,
                year=year,
                action="cache" if likely else "run",
                label="打分预计算 %s/%s · %s · %s · 池 %s 只"
                % (
                    min(done + 1, total),
                    total,
                    year,
                    "读缓存…" if likely else "正在组合回测…",
                    n_pool,
                ),
                extra={"pool_n": n_pool, "cached": likely},
            )
            row = _run_score_year_job(j)
            results.append(row)
            _finish_score_row(row)
    else:
        results.extend(
            _run_score_jobs_subprocess(
                jobs,
                n_workers=n_workers,
                n_pool=n_pool,
                get_done=lambda: done,
                total=total,
                on_progress=on_progress,
                finish_row=_finish_score_row,
            )
        )
    for row in results:
        sy = str(row.get("year") or "")
        sp = str(row.get("path") or "").strip()
        if sy and sp:
            score_paths[sy] = sp
    scanned["score_detail_paths"] = score_paths
    for row in results:
        year = str(row.get("year") or "")
        if row.get("error"):
            errors.append("%s: %s" % (year, row.get("error")))
            continue
        per = row.get("per_stock") or {}
        if not per:
            errors.append("%s: 组合明细无成交归因" % year)
        per = row.get("per_stock") or {}
        for stock, kpi in per.items():
            portfolio_kpi.setdefault(str(stock).upper(), {})[year] = dict(kpi)
    scanned["portfolio_kpi"] = portfolio_kpi
    scanned["_portfolio_kpi_errors"] = errors
    return portfolio_kpi


def _naive_year_pnl(
    stocks: list[str],
    year: str,
    scanned: dict[str, Any],
) -> float:
    total = 0.0
    raw = scanned.get("stocks") or {}
    avail = infer_score_years(raw)
    for stock in stocks:
        rec = raw.get(stock)
        if not rec:
            continue
        w = _apply_year_window(rec, avail)
        k = (w.get("years") or {}).get(str(year))
        if k:
            total += float(k.get("sum_pnl") or 0.0)
    return total


def run_walk_forward(
    scanned: dict[str, Any] | None = None,
    *,
    data_start: str = "",
    data_end: str = "",
    eval_years: tuple[str, ...] | None = None,
    rebalance_years: int = 1,
    period_baskets: dict[str, Any] | None = None,
    fallback_book: dict[str, Any] | None = None,
    book_params: dict[str, Any] | None = None,
    csv_root: str | Path = "",
    report_dir: str | Path = "",
    force_rerun: bool = False,
    compound_backtest: bool = True,
    on_progress: ProgressCb = None,
    lookback_n: int = 2,
    top_k: int = 3,
    filters: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
    score_mode: str = "portfolio",
    score_pool: str = "scanned",
    workers: int = 0,
) -> dict[str, Any]:
    del lookback_n, top_k, filters, weights, score_mode, score_pool, workers
    scanned = scanned if isinstance(scanned, dict) else {}
    fallback = normalize_book_stocks(
        fallback_book if fallback_book is not None else load_book_stocks_full()
    )
    baskets_in = (
        {str(k): v for k, v in period_baskets.items()} if period_baskets is not None else None
    )
    available = infer_score_years(scanned.get("stocks") or {})
    ds = str(data_start or "").strip()
    de = str(data_end or "").strip()
    if not ds and available:
        ds = str(available[0])
    if not de and available:
        de = str(available[-1])
    data_years = hold_years_for_range(ds, de, available)
    eval_years_run = tuple(str(y) for y in eval_years) if eval_years else data_years
    notes: list[str] = []
    has_scan_kpi = bool(scanned.get("stocks"))
    if data_years:
        notes.append(
            "评估持有 %s–%s · 换仓 %s 年 · 手工篮子"
            % (data_years[0], data_years[-1], max(1, int(rebalance_years or 1)))
        )
    elif ds or de:
        notes.append("数据年 %s–%s 推不出持有年" % (ds or "-", de or "-"))
    if not has_scan_kpi:
        notes.append("未扫描分年明细，不计算单票合计对照（naive_pnl）")
    if not eval_years_run:
        return {
            "summary": {
                "n_eval_years": 0,
                "n_ok_years": 0,
                "total_pnl": 0.0,
                "mean_pnl": None,
                "pos_years": 0,
                "pos_ratio": None,
            },
            "year_rows": [],
            "period_rows": [],
            "equity_pts": [],
            "notes": notes,
            "params": _walk_forward_params(
                data_start=ds,
                data_end=de,
                data_years=data_years,
                eval_years=(),
                rebalance_years=rebalance_years,
                period_baskets={},
                book_params=book_params,
                compound_backtest=compound_backtest,
            ),
        }
    periods = iter_rebalance_periods(eval_years_run, rebalance_years)
    progress_total = sum(len(tuple(p.get("hold_years") or ())) for p in periods)
    progress_done = 0

    overrides = _book_overrides(book_params)
    budget = float(overrides["TRADE_BUDGET"])
    out_dir = resolve_typed_dir(report_dir, DEFAULT_DIVIDEND_TYPE)
    out_dir.mkdir(parents=True, exist_ok=True)

    running_wallet = budget
    initial_wallet = budget

    year_rows: list[dict[str, Any]] = []
    period_rows: list[dict[str, Any]] = []
    equity_pts: list[dict[str, Any]] = []
    resolved_baskets: dict[str, dict[str, dict[str, str]]] = {}
    cum = 0.0
    if compound_backtest:
        notes.append("持有期复利回测：跨年传递期末权益")

    def _hold_step(
        *,
        hy: str,
        period_i: int,
        select_year: str,
        action: str,
        tip: str,
        picks: str = "",
        extra: dict[str, Any] | None = None,
        bump: bool = False,
    ) -> None:
        nonlocal progress_done
        if bump:
            progress_done += 1
            done_show = progress_done
        else:
            done_show = min(progress_done + 1, progress_total) if progress_total else progress_done
        pick_part = (" · %s" % picks) if picks else ""
        _emit_wf_progress(
            on_progress,
            phase="hold",
            done=done_show,
            total=progress_total,
            year=hy,
            action=action,
            label="持有回放 %s/%s · %s · 段p%s · 换仓年%s%s · %s"
            % (done_show, progress_total, hy, period_i, select_year, pick_part, tip),
            extra={
                "period_i": period_i,
                "select_year": select_year,
                "picks": picks,
                **(extra or {}),
            },
        )

    for period in periods:
        select_year = str(period["select_year"])
        hold_years = tuple(str(y) for y in period["hold_years"])
        raw = None if baskets_in is None else baskets_in.get(select_year)
        basket = resolve_period_basket(raw, fallback)
        resolved_baskets[select_year] = _copy_book(basket)
        period_status = "ok"
        if not basket:
            period_status = "无推荐"
            notes.append("段 p%s %s：未配置标的" % (period["period_i"], select_year))
        pick_names = "、".join(sorted(basket.keys()))
        details = pick_details_from_basket(basket)

        period_pnl = 0.0
        for hy in hold_years:
            is_rebalance = hy == select_year
            row_status = period_status
            port_pnl = None
            if has_scan_kpi:
                naive = _naive_year_pnl(list(basket.keys()), hy, scanned) if basket else None
            else:
                naive = None
            if period_status != "ok" or not basket:
                _hold_step(
                    hy=hy,
                    period_i=int(period["period_i"]),
                    select_year=select_year,
                    action="skip",
                    tip="跳过（%s）" % (period_status or "无篮子"),
                    picks=pick_names,
                    bump=True,
                )
                year_rows.append(
                    {
                        "year": hy,
                        "period_i": period["period_i"],
                        "select_year": select_year,
                        "is_rebalance": is_rebalance,
                        "picks": pick_names,
                        "pick_details": details,
                        "portfolio_pnl": port_pnl,
                        "naive_pnl": naive if basket else None,
                        "status": row_status,
                        "hold_detail_path": None,
                    }
                )
                continue
            htag = book_stocks_hash(basket)
            log_name = "local_bt_book_hold_%s_p%s_k%s.txt" % (hy, period["period_i"], htag)
            log_path = out_dir / log_name
            trades_path = trades_csv_path(log_path)
            wallet_start = running_wallet if compound_backtest else None
            wallet_end = None
            use_cache = trades_path.is_file() and not force_rerun
            _hold_step(
                hy=hy,
                period_i=int(period["period_i"]),
                select_year=select_year,
                action="cache" if use_cache else "run",
                tip="读缓存…" if use_cache else "正在回测…",
                picks=pick_names,
                bump=False,
                extra={"cached": use_cache},
            )
            try:
                if use_cache:
                    combo = analyze_book_detail(trades_path, budget=budget, log_path=log_path)
                    if compound_backtest:
                        parsed = parse_wallet_from_log(log_path.read_text(encoding="utf-8", errors="replace"))
                        wallet_end = parsed.get("wallet_cash_end")
                        if wallet_end is None and wallet_start is not None:
                            wallet_end = float(wallet_start) + float(combo.get("sum_pnl") or 0.0)
                        if wallet_start is not None and wallet_end is not None:
                            port_pnl = float(wallet_end) - float(wallet_start)
                        else:
                            port_pnl = float(combo.get("sum_pnl") or 0.0)
                    else:
                        port_pnl = float(combo.get("sum_pnl") or 0.0)
                else:
                    hold_overrides = dict(overrides)
                    if compound_backtest:
                        hold_overrides["compound_backtest"] = True
                        hold_overrides["wallet_cash"] = running_wallet
                    _log_path, meta = run_book_backtest(
                        basket,
                        "%s0101" % hy,
                        "%s1231" % hy,
                        csv_root,
                        out_dir,
                        log_name=log_name,
                        quiet=True,
                        overrides=hold_overrides,
                    )
                    combo = analyze_book_detail(trades_path, budget=budget, log_path=_log_path)
                    if compound_backtest:
                        wallet_end = meta.get("wallet_cash_end")
                        if wallet_end is None:
                            wallet_end = float(wallet_start or budget) + float(combo.get("sum_pnl") or 0.0)
                        port_pnl = float(wallet_end) - float(wallet_start or budget)
                    else:
                        port_pnl = float(combo.get("sum_pnl") or 0.0)
                row_status = "ok"
                finish_action = "cache" if use_cache else "run"
                finish_tip = "缓存命中" if use_cache else "回测完成"
            except Exception as e:
                row_status = "回放失败: %s" % e
                port_pnl = None
                finish_action = "error"
                finish_tip = "失败: %s" % e
            _hold_step(
                hy=hy,
                period_i=int(period["period_i"]),
                select_year=select_year,
                action=finish_action,
                tip=finish_tip,
                picks=pick_names,
                bump=True,
                extra={"cached": use_cache, "status": row_status},
            )
            if port_pnl is not None:
                period_pnl += port_pnl
                if compound_backtest and wallet_end is not None:
                    running_wallet = float(wallet_end)
                    cum = float(wallet_end) - float(initial_wallet)
                    equity_pts.append(
                        {
                            "year": hy,
                            "cum_pnl": cum,
                            "pnl": port_pnl,
                            "wallet_end": running_wallet,
                        }
                    )
                else:
                    cum += port_pnl
                    equity_pts.append({"year": hy, "cum_pnl": cum, "pnl": port_pnl})
            year_rows.append(
                {
                    "year": hy,
                    "period_i": period["period_i"],
                    "select_year": select_year,
                    "is_rebalance": is_rebalance,
                    "picks": pick_names,
                    "pick_details": details,
                    "portfolio_pnl": port_pnl,
                    "naive_pnl": naive,
                    "status": row_status,
                    "hold_detail_path": str(trades_path) if trades_path.is_file() else None,
                    "wallet_start": wallet_start,
                    "wallet_end": wallet_end if compound_backtest else None,
                }
            )
        period_rows.append(
            {
                "period_i": period["period_i"],
                "select_year": select_year,
                "hold_years": "、".join(hold_years),
                "picks": pick_names,
                "period_pnl": period_pnl if period_status == "ok" and basket else None,
                "status": period_status,
            }
        )

    ok_rows = [r for r in year_rows if r.get("status") == "ok" and r.get("portfolio_pnl") is not None]
    pnls = [float(r["portfolio_pnl"]) for r in ok_rows]
    if compound_backtest and ok_rows:
        summary_total = float(running_wallet) - float(initial_wallet)
    else:
        summary_total = sum(pnls) if pnls else 0.0
    summary = {
        "n_eval_years": len([r for r in year_rows if r.get("portfolio_pnl") is not None]),
        "n_ok_years": len(ok_rows),
        "total_pnl": summary_total,
        "mean_pnl": (sum(pnls) / len(pnls)) if pnls else None,
        "pos_years": sum(1 for p in pnls if p > 0),
        "pos_ratio": (sum(1 for p in pnls if p > 0) / len(pnls)) if pnls else None,
        "compound_backtest": bool(compound_backtest),
        "initial_wallet": float(initial_wallet),
        "final_wallet": float(running_wallet) if compound_backtest else None,
    }
    if progress_total > 0:
        _emit_wf_progress(
            on_progress,
            phase="hold",
            done=progress_total,
            total=progress_total,
            year="",
            action="run",
            label="Walk-forward 完成 %s/%s" % (progress_total, progress_total),
        )
    return {
        "summary": summary,
        "year_rows": year_rows,
        "period_rows": period_rows,
        "equity_pts": equity_pts,
        "score_detail_paths": dict(scanned.get("score_detail_paths") or {}),
        "report_dir": str(out_dir),
        "notes": notes,
        "params": _walk_forward_params(
            data_start=ds,
            data_end=de,
            data_years=data_years,
            eval_years=eval_years_run,
            rebalance_years=rebalance_years,
            period_baskets=resolved_baskets,
            book_params=book_params,
            compound_backtest=compound_backtest,
        ),
    }


def _walk_forward_params(
    *,
    data_start: str,
    data_end: str,
    data_years: tuple[str, ...],
    eval_years: tuple[str, ...],
    rebalance_years: int,
    period_baskets: dict[str, Any] | None,
    book_params: dict[str, Any] | None,
    compound_backtest: bool = True,
) -> dict[str, Any]:
    return {
        "data_start": data_start,
        "data_end": data_end,
        "data_years": list(data_years),
        "eval_years": list(eval_years),
        "rebalance_years": rebalance_years,
        "period_baskets": dict(period_baskets or {}),
        "book_params": dict(book_params or load_book_defaults()),
        "compound_backtest": bool(compound_backtest),
    }


def write_analysis_csv(result: dict[str, Any], out_path: str | Path) -> Path:
    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(result.get("year_rows") or [])
    if not df.empty:
        if "pick_details" in df.columns:
            df["pick_details"] = df["pick_details"].map(
                lambda v: json.dumps(v if isinstance(v, list) else [], ensure_ascii=False)
            )
        df["params_json"] = json.dumps(result.get("params") or {}, ensure_ascii=False)
    df.to_csv(dest, index=False, encoding="utf-8-sig")
    return dest


def run_fixed_book(
    book_stocks: dict[str, Any] | None = None,
    *,
    data_start: str = "",
    data_end: str = "",
    book_params: dict[str, Any] | None = None,
    csv_root: str | Path = "",
    report_dir: str | Path = "",
    compound_backtest: bool = True,
    force_rerun: bool = False,
) -> dict[str, Any]:
    """固定标的：一段连续组合回放（无 walk-forward 打分）。"""
    notes: list[str] = []
    basket = normalize_book_stocks(book_stocks if book_stocks is not None else load_book_stocks_full())
    if not basket:
        notes.append("BOOK_STOCKS 为空，无法回放。")
        return {
            "mode": "fixed",
            "summary": {
                "total_pnl": None,
                "wallet_start": None,
                "wallet_end": None,
                "n_stocks": 0,
                "compound_backtest": bool(compound_backtest),
            },
            "hold_detail_path": None,
            "notes": notes,
            "params": {
                "mode": "fixed",
                "data_start": data_start,
                "data_end": data_end,
                "book_stocks": {},
                "book_params": dict(book_params or load_book_defaults()),
                "compound_backtest": bool(compound_backtest),
            },
        }
    ds = str(data_start or "").strip()
    de = str(data_end or "").strip()
    if ds and de and de < ds:
        ds, de = de, ds
    start = "%s0101" % ds if len(ds) == 4 else ds
    end = "%s1231" % de if len(de) == 4 else de
    if len(start) != 8 or len(end) != 8:
        notes.append("起止年无效：%s–%s" % (data_start, data_end))
        return {
            "mode": "fixed",
            "summary": {
                "total_pnl": None,
                "wallet_start": None,
                "wallet_end": None,
                "n_stocks": len(basket),
                "compound_backtest": bool(compound_backtest),
            },
            "hold_detail_path": None,
            "notes": notes,
            "params": {
                "mode": "fixed",
                "data_start": ds,
                "data_end": de,
                "book_stocks": basket,
                "book_params": dict(book_params or load_book_defaults()),
                "compound_backtest": bool(compound_backtest),
            },
        }

    overrides = _book_overrides(book_params)
    budget = float(overrides["TRADE_BUDGET"])
    if compound_backtest:
        overrides["compound_backtest"] = True
        overrides["wallet_cash"] = budget
    out_dir = resolve_typed_dir(report_dir, DEFAULT_DIVIDEND_TYPE)
    out_dir.mkdir(parents=True, exist_ok=True)
    htag = book_stocks_hash(basket)
    log_name = book_log_name(kind="fixed", year=start, tag=htag, end=end)
    log_path = out_dir / log_name
    trades_path = trades_csv_path(log_path)
    notes.append(
        "固定标的 %s 只 · %s–%s · %s"
        % (len(basket), start, end, "复利" if compound_backtest else "固定预算")
    )
    wallet_start = budget if compound_backtest else None
    wallet_end = None
    port_pnl = None
    status = "ok"
    try:
        if trades_path.is_file() and not force_rerun:
            combo = analyze_book_detail(trades_path, budget=budget, log_path=log_path)
            if compound_backtest and log_path.is_file():
                parsed = parse_wallet_from_log(log_path.read_text(encoding="utf-8", errors="replace"))
                wallet_start = parsed.get("wallet_cash_start") or budget
                wallet_end = parsed.get("wallet_cash_end")
                if wallet_end is None:
                    wallet_end = float(wallet_start) + float(combo.get("sum_pnl") or 0.0)
                port_pnl = float(wallet_end) - float(wallet_start)
            else:
                port_pnl = float(combo.get("sum_pnl") or 0.0)
            notes.append("命中缓存：%s" % trades_path.name)
        else:
            _lp, meta = run_book_backtest(
                basket,
                start,
                end,
                csv_root,
                out_dir,
                log_name=log_name,
                quiet=True,
                overrides=overrides,
            )
            combo = analyze_book_detail(trades_path, budget=budget, log_path=_lp)
            if compound_backtest:
                wallet_start = meta.get("wallet_cash_start") or budget
                wallet_end = meta.get("wallet_cash_end")
                if wallet_end is None:
                    wallet_end = float(wallet_start) + float(combo.get("sum_pnl") or 0.0)
                port_pnl = float(wallet_end) - float(wallet_start)
            else:
                port_pnl = float(combo.get("sum_pnl") or 0.0)
            if meta.get("skipped"):
                notes.append("缺 CSV 跳过：%s" % "; ".join(meta["skipped"]))
    except Exception as e:
        status = "回放失败: %s" % e
        notes.append(status)
        combo = {}

    n_trades = int((combo.get("stats") or {}).get("n_buy") or 0) if combo else 0
    return {
        "mode": "fixed",
        "summary": {
            "total_pnl": port_pnl,
            "wallet_start": wallet_start,
            "wallet_end": wallet_end,
            "n_stocks": len(basket),
            "n_buy": n_trades,
            "compound_backtest": bool(compound_backtest),
            "status": status,
            "picks": "、".join(sorted(basket.keys())),
        },
        "hold_detail_path": str(trades_path) if trades_path.is_file() else None,
        "report_dir": str(out_dir),
        "notes": notes,
        "params": {
            "mode": "fixed",
            "data_start": ds,
            "data_end": de,
            "start": start,
            "end": end,
            "book_stocks": basket,
            "book_params": dict(book_params or load_book_defaults()),
            "compound_backtest": bool(compound_backtest),
        },
    }


def write_fixed_book_csv(result: dict[str, Any], out_path: str | Path) -> Path:
    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    s = result.get("summary") or {}
    row = {
        "mode": "fixed",
        "start": (result.get("params") or {}).get("start"),
        "end": (result.get("params") or {}).get("end"),
        "picks": s.get("picks"),
        "n_stocks": s.get("n_stocks"),
        "n_buy": s.get("n_buy"),
        "portfolio_pnl": s.get("total_pnl"),
        "wallet_start": s.get("wallet_start"),
        "wallet_end": s.get("wallet_end"),
        "status": s.get("status"),
        "hold_detail_path": result.get("hold_detail_path"),
        "params_json": json.dumps(result.get("params") or {}, ensure_ascii=False),
    }
    pd.DataFrame([row]).to_csv(dest, index=False, encoding="utf-8-sig")
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HlBand walk-forward / 固定标的 数据分析（组合回放）")
    ap.add_argument("--mode", choices=("walk-forward", "fixed"), default="walk-forward")
    ap.add_argument("--report-dir", default=str(DEFAULT_REPORT_ROOT))
    ap.add_argument("--csv-dir", default="")
    ap.add_argument(
        "--data-start",
        "--eval-start",
        default="",
        dest="data_start",
        help="持有起始自然年（含）",
    )
    ap.add_argument(
        "--data-end",
        "--eval-end",
        default="",
        dest="data_end",
        help="持有结束自然年（含）",
    )
    ap.add_argument("--rebalance-years", type=int, default=1)
    ap.add_argument(
        "--picks-json",
        default="",
        help="手工篮子：按年 {换仓年: 篮子}，或 BOOK_STOCKS 风格单篮子（应用到全部段，可行尾注释）",
    )
    ap.add_argument("--force-rerun", action="store_true")
    ap.add_argument("--no-compound", action="store_true", help="关闭持有期复利（固定 TRADE_BUDGET）")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    csv_dir = args.csv_dir or str(Path(args.report_dir).parent.parent / "tools" / "csv")
    if args.mode == "fixed":
        result = run_fixed_book(
            load_book_stocks_full(),
            data_start=str(args.data_start or ""),
            data_end=str(args.data_end or ""),
            compound_backtest=not args.no_compound,
            force_rerun=args.force_rerun,
            csv_root=csv_dir,
            report_dir=args.report_dir,
        )
        s = result.get("summary") or {}
        print(
            "fixed %s–%s pnl=%s wallet=%s→%s status=%s"
            % (
                (result.get("params") or {}).get("start"),
                (result.get("params") or {}).get("end"),
                s.get("total_pnl"),
                s.get("wallet_start"),
                s.get("wallet_end"),
                s.get("status"),
            )
        )
        out = args.out or str(Path(args.report_dir) / "local_bt_fixed_book.csv")
        write_fixed_book_csv(result, out)
        print("wrote", out)
        return 0 if str(s.get("status") or "") == "ok" else 1

    avail = list_score_years(args.report_dir)
    data_start = str(args.data_start or (avail[0] if avail else ""))
    data_end = str(args.data_end or (avail[-1] if avail else ""))
    if not data_start or not data_end:
        print("请指定 --data-start / --data-end", file=sys.stderr)
        return 1
    fallback = load_book_stocks_full()
    period_baskets = None
    if args.picks_json:
        period_baskets, book_override = load_picks_file(args.picks_json)
        if book_override is not None:
            fallback = book_override
    result = run_walk_forward(
        {"stocks": {}},
        data_start=data_start,
        data_end=data_end,
        rebalance_years=args.rebalance_years,
        period_baskets=period_baskets,
        fallback_book=fallback,
        force_rerun=args.force_rerun,
        compound_backtest=not args.no_compound,
        csv_root=csv_dir,
        report_dir=args.report_dir,
    )
    s = result.get("summary") or {}
    eval_years = (result.get("params") or {}).get("eval_years") or []
    print(
        "hold %s–%s eval %s–%s total_pnl=%s mean=%s pos_ratio=%s"
        % (
            data_start,
            data_end,
            eval_years[0] if eval_years else "-",
            eval_years[-1] if eval_years else "-",
            s.get("total_pnl"),
            s.get("mean_pnl"),
            s.get("pos_ratio"),
        )
    )
    out = args.out or str(Path(args.report_dir) / "local_bt_select_analysis.csv")
    write_analysis_csv(result, out)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
