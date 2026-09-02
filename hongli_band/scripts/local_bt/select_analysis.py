# coding: utf-8
"""walk-forward 数据分析：组合打分预计算 + TopK 持有回放。"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from analyze import DEFAULT_DIVIDEND_TYPE, DEFAULT_REPORT_ROOT, resolve_typed_dir  # noqa: E402
from book_backtest import (  # noqa: E402
    analyze_book_detail,
    attribute_portfolio_kpi,
    book_log_name,
    book_stocks_hash,
    normalize_book_stocks,
    run_book_backtest,
)
from select_config import DEFAULT_FILTERS, WEIGHTS, load_book_defaults  # noqa: E402
from stock_select import (  # noqa: E402
    _apply_year_window,
    empty_year_kpi,
    infer_score_years,
    score_universe,
    scan_reports,
)
from trades_csv import trades_csv_path  # noqa: E402

MA_TYPES = ("SMA", "EMA")


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
    flt["min_years_traded"] = max(1, int(flt.get("min_years_traded") or 1) - 1)
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


def _run_score_year_job(payload: dict[str, Any]) -> dict[str, Any]:
    year = str(payload["year"])
    pool = payload["pool"]
    start = "%s0101" % year
    end = "%s1231" % year
    out_dir = Path(payload["out_dir"])
    log_name = book_log_name(kind="score", year=year, tag=str(payload["tag"]))
    trades_path = out_dir / log_name.replace(".txt", "_操作明细.csv")
    budget = float(payload.get("budget") or 100000.0)
    if trades_path.is_file() and not payload.get("force_rerun"):
        per = attribute_portfolio_kpi(trades_path, budget=budget)
        # 空明细多半是修复前的坏缓存，不能当命中（否则 2023+ 会永久无推荐）
        if per:
            return {"year": year, "per_stock": per, "cached": True, "path": str(trades_path)}
    try:
        log_path, meta = run_book_backtest(
            pool,
            start,
            end,
            payload["csv_root"],
            out_dir,
            log_name=log_name,
            quiet=True,
            overrides=payload.get("overrides") or {},
        )
        tp = trades_csv_path(log_path)
        per = attribute_portfolio_kpi(tp, budget=budget)
        return {
            "year": year,
            "per_stock": per,
            "cached": False,
            "path": str(tp),
            "meta": meta,
        }
    except Exception as e:
        return {"year": year, "error": str(e), "per_stock": {}}


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
    w = int(workers or 0)
    if w <= 1 or len(jobs) <= 1:
        results = [_run_score_year_job(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=min(w, len(jobs))) as ex:
            futs = [ex.submit(_run_score_year_job, j) for j in jobs]
            for fu in as_completed(futs):
                results.append(fu.result())
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
    scanned: dict[str, Any],
    *,
    data_start: str = "",
    data_end: str = "",
    eval_years: tuple[str, ...] | None = None,
    lookback_n: int = 2,
    rebalance_years: int = 1,
    top_k: int = 3,
    filters: dict[str, Any] | None = None,
    weights: dict[str, float] | None = None,
    book_params: dict[str, Any] | None = None,
    csv_root: str | Path = "",
    report_dir: str | Path = "",
    score_mode: str = "portfolio",
    score_pool: str = "scanned",
    force_rerun: bool = False,
    workers: int = 0,
) -> dict[str, Any]:
    flt = dict(DEFAULT_FILTERS)
    if filters:
        flt.update(filters)
    flt["top_n"] = min(max(int(top_k or 3), 1), 9)
    available = infer_score_years(scanned.get("stocks") or {})
    ds = str(data_start or "").strip()
    de = str(data_end or "").strip()
    if not ds and available:
        ds = str(available[0])
    if not de and available:
        de = str(available[-1])
    data_years, eval_from_data = data_and_eval_years(ds, de, lookback_n, available)
    eval_years_run = tuple(eval_years) if eval_years else eval_from_data
    notes: list[str] = []
    if data_years:
        if eval_years_run:
            notes.append(
                "数据年 %s–%s → 评估 %s–%s（回看 %s）"
                % (
                    data_years[0],
                    data_years[-1],
                    eval_years_run[0],
                    eval_years_run[-1],
                    lookback_n,
                )
            )
        else:
            notes.append(
                "数据年 %s–%s 在回看 %s 下推不出首评年"
                % (
                    data_years[0] if data_years else ds,
                    data_years[-1] if data_years else de,
                    lookback_n,
                )
            )
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
                lookback_n=lookback_n,
                rebalance_years=rebalance_years,
                top_k=top_k,
                mode=str(score_mode or "portfolio").strip().lower(),
                score_pool=score_pool,
                flt=flt,
                weights=weights,
                book_params=book_params,
            ),
        }
    periods = iter_rebalance_periods(eval_years_run, rebalance_years)
    mode = str(score_mode or "portfolio").strip().lower()
    pool = build_score_pool(scanned, pool_mode=score_pool, filters=flt)
    if mode == "portfolio":
        need_score_years = collect_score_years(periods, lookback_n, data_years)
        if not pool:
            notes.append("打分池为空，无法组合预计算。")
        else:
            precompute_portfolio_kpis(
                scanned,
                need_score_years,
                pool,
                csv_root=csv_root,
                report_dir=report_dir,
                book_params=book_params,
                force_rerun=force_rerun,
                workers=workers,
            )
            notes.append(
                "组合打分年 %s · 池 %s 只"
                % ("、".join(need_score_years) if need_score_years else "-", len(pool))
            )
            for err in scanned.get("_portfolio_kpi_errors") or []:
                notes.append("打分预计算警告: %s" % err)

    overrides = _book_overrides(book_params)
    budget = float(overrides["TRADE_BUDGET"])
    out_dir = resolve_typed_dir(report_dir, DEFAULT_DIVIDEND_TYPE)
    out_dir.mkdir(parents=True, exist_ok=True)

    year_rows: list[dict[str, Any]] = []
    period_rows: list[dict[str, Any]] = []
    equity_pts: list[dict[str, Any]] = []
    cum = 0.0

    for period in periods:
        select_year = str(period["select_year"])
        hold_years = tuple(str(y) for y in period["hold_years"])
        window = score_years_for_period(select_year, lookback_n, data_years)
        period_status = "ok"
        picks: list[dict[str, Any]] = []
        if len(window) < max(1, int(lookback_n)):
            period_status = "窗口不足"
            for hy in hold_years:
                year_rows.append(
                    {
                        "year": hy,
                        "period_i": period["period_i"],
                        "select_year": select_year,
                        "is_rebalance": hy == select_year,
                        "picks": "",
                        "portfolio_pnl": None,
                        "naive_pnl": None,
                        "skipped_buys": None,
                        "status": period_status,
                    }
                )
            period_rows.append(
                {
                    "period_i": period["period_i"],
                    "select_year": select_year,
                    "hold_years": "、".join(hold_years),
                    "picks": "",
                    "period_pnl": None,
                    "status": period_status,
                }
            )
            continue

        scored = score_universe(
            scanned,
            filters=flt,
            score_years=window,
            kpi_source=mode if mode in ("portfolio", "single") else "single",
            weights=weights,
        )
        rec = scored.get("recommend")
        if rec is None or rec.empty:
            period_status = "无推荐"
        else:
            for _, r in rec.iterrows():
                picks.append(
                    {
                        "stock": str(r["stock"]),
                        "score": r.get("score"),
                        "ma_type": r.get("ma_type_suggest"),
                        "div_type": r.get("div_type_suggest"),
                    }
                )
        basket = {}
        for p in picks:
            ma = str(p.get("ma_type") or "").upper()
            div = str(p.get("div_type") or DEFAULT_DIVIDEND_TYPE).lower()
            if ma in MA_TYPES:
                basket[str(p["stock"])] = {"ma_type": ma, "dividend_type": div}
        pick_names = "、".join(sorted(basket.keys()))

        period_pnl = 0.0
        for hy in hold_years:
            is_rebalance = hy == select_year
            row_status = period_status
            port_pnl = None
            naive = _naive_year_pnl(list(basket.keys()), hy, scanned) if basket else 0.0
            if period_status != "ok" or not basket:
                year_rows.append(
                    {
                        "year": hy,
                        "period_i": period["period_i"],
                        "select_year": select_year,
                        "is_rebalance": is_rebalance,
                        "picks": pick_names,
                        "portfolio_pnl": port_pnl,
                        "naive_pnl": naive if basket else None,
                        "skipped_buys": None,
                        "status": row_status,
                    }
                )
                continue
            htag = book_stocks_hash(basket)
            log_name = "local_bt_book_hold_%s_p%s_k%s.txt" % (hy, period["period_i"], htag)
            trades_path = out_dir / log_name.replace(".txt", "_操作明细.csv")
            try:
                if trades_path.is_file() and not force_rerun:
                    combo = analyze_book_detail(trades_path, budget=budget)
                else:
                    run_book_backtest(
                        basket,
                        "%s0101" % hy,
                        "%s1231" % hy,
                        csv_root,
                        out_dir,
                        log_name=log_name,
                        quiet=True,
                        overrides=overrides,
                    )
                    combo = analyze_book_detail(trades_path, budget=budget)
                port_pnl = float(combo.get("sum_pnl") or 0.0)
                row_status = "ok"
            except Exception as e:
                row_status = "回放失败: %s" % e
                port_pnl = None
            if port_pnl is not None:
                period_pnl += port_pnl
                cum += port_pnl
                equity_pts.append({"year": hy, "cum_pnl": cum, "pnl": port_pnl})
            year_rows.append(
                {
                    "year": hy,
                    "period_i": period["period_i"],
                    "select_year": select_year,
                    "is_rebalance": is_rebalance,
                    "picks": pick_names,
                    "portfolio_pnl": port_pnl,
                    "naive_pnl": naive,
                    "skipped_buys": None,
                    "status": row_status,
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
    summary = {
        "n_eval_years": len([r for r in year_rows if r.get("portfolio_pnl") is not None]),
        "n_ok_years": len(ok_rows),
        "total_pnl": sum(pnls) if pnls else 0.0,
        "mean_pnl": (sum(pnls) / len(pnls)) if pnls else None,
        "pos_years": sum(1 for p in pnls if p > 0),
        "pos_ratio": (sum(1 for p in pnls if p > 0) / len(pnls)) if pnls else None,
    }
    return {
        "summary": summary,
        "year_rows": year_rows,
        "period_rows": period_rows,
        "equity_pts": equity_pts,
        "notes": notes,
        "params": _walk_forward_params(
            data_start=ds,
            data_end=de,
            data_years=data_years,
            eval_years=eval_years_run,
            lookback_n=lookback_n,
            rebalance_years=rebalance_years,
            top_k=top_k,
            mode=mode,
            score_pool=score_pool,
            flt=flt,
            weights=weights,
            book_params=book_params,
        ),
    }


def _walk_forward_params(
    *,
    data_start: str,
    data_end: str,
    data_years: tuple[str, ...],
    eval_years: tuple[str, ...],
    lookback_n: int,
    rebalance_years: int,
    top_k: int,
    mode: str,
    score_pool: str,
    flt: dict[str, Any],
    weights: dict[str, float] | None,
    book_params: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "data_start": data_start,
        "data_end": data_end,
        "data_years": list(data_years),
        "eval_years": list(eval_years),
        "lookback_n": lookback_n,
        "rebalance_years": rebalance_years,
        "top_k": top_k,
        "score_mode": mode,
        "score_pool": score_pool,
        "filters": flt,
        "weights": dict(weights or WEIGHTS),
        "book_params": dict(book_params or load_book_defaults()),
    }


def write_analysis_csv(result: dict[str, Any], out_path: str | Path) -> Path:
    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(result.get("year_rows") or [])
    if not df.empty:
        df["params_json"] = json.dumps(result.get("params") or {}, ensure_ascii=False)
    df.to_csv(dest, index=False, encoding="utf-8-sig")
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HlBand walk-forward 数据分析（组合回放）")
    ap.add_argument("--report-dir", default=str(DEFAULT_REPORT_ROOT))
    ap.add_argument("--csv-dir", default="")
    ap.add_argument(
        "--data-start",
        "--eval-start",
        default="",
        dest="data_start",
        help="数据/KPI 起始自然年（首评年=区间内最早可回看年）",
    )
    ap.add_argument(
        "--data-end",
        "--eval-end",
        default="",
        dest="data_end",
        help="数据/KPI 结束自然年（评估持有年至多到此年）",
    )
    ap.add_argument("--lookback-n", type=int, default=2)
    ap.add_argument("--rebalance-years", type=int, default=1)
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--score-mode", choices=("portfolio", "single"), default="portfolio")
    ap.add_argument("--score-pool", choices=("scanned", "passed_prefilter"), default="scanned")
    ap.add_argument("--force-rerun", action="store_true")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)
    csv_dir = args.csv_dir or str(Path(args.report_dir).parent.parent / "tools" / "csv")
    scanned = scan_reports(args.report_dir, csv_dir)
    avail = infer_score_years(scanned.get("stocks") or {})
    if not avail:
        print("无分年扫描数据", file=sys.stderr)
        return 1
    data_start = str(args.data_start or (avail[0] if avail else ""))
    data_end = str(args.data_end or (avail[-1] if avail else ""))
    _, eval_years = data_and_eval_years(data_start, data_end, args.lookback_n, avail)
    result = run_walk_forward(
        scanned,
        data_start=data_start,
        data_end=data_end,
        lookback_n=args.lookback_n,
        rebalance_years=args.rebalance_years,
        top_k=args.top_k,
        score_mode=args.score_mode,
        score_pool=args.score_pool,
        force_rerun=args.force_rerun,
        workers=args.workers,
        csv_root=csv_dir,
        report_dir=args.report_dir,
    )
    s = result.get("summary") or {}
    print(
        "data %s–%s eval %s–%s total_pnl=%s mean=%s pos_ratio=%s"
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
