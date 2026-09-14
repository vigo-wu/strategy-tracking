# coding: utf-8
"""ProcessPool 子进程入口。必须是独立模块，Windows spawn 才能 pickle。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))


def init_worker(local_bt_dir: str = "") -> None:
    d = str(local_bt_dir or HERE)
    if d not in sys.path:
        sys.path.insert(0, d)
    scripts = str(Path(d).resolve().parents[2] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from run import _bundle_code

    _bundle_code()


def run_one(payload: dict[str, Any]) -> dict[str, Any]:
    rows = run_group([payload])
    return rows[0] if rows else {}


def run_group(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from run import backtest_one_result, get_market_store

    if not payloads:
        return []
    store = None
    csv_path = payloads[0].get("csv")
    try:
        store = get_market_store(csv_path, stock=str(payloads[0].get("stock") or ""))
    except Exception:
        store = None
    rows = []
    for payload in payloads:
        rows.append(
            backtest_one_result(
                payload["csv"],
                start=str(payload.get("start") or ""),
                end=str(payload.get("end") or ""),
                out_dir=payload.get("out_dir"),
                quiet=bool(payload.get("quiet", True)),
                log_name=str(payload.get("log_name") or ""),
                year=str(payload.get("year") or ""),
                ma_type=str(payload.get("ma_type") or ""),
                dividend_type=str(payload.get("dividend_type") or ""),
                store=store,
                overrides=payload.get("overrides") or None,
            )
        )
    return rows


def run_score_year(payload: dict[str, Any]) -> dict[str, Any]:
    """Walk-forward Phase A：单年全池组合回测 → 按票归因 KPI。

    Streamlit 下勿用 ProcessPool submit 本函数；请走 ``--score-year`` 子进程入口。
    """
    from book_backtest import (
        attribute_portfolio_kpi,
        book_log_name,
        run_book_backtest,
    )
    from trades_csv import trades_csv_path

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
        # 空明细多半是修复前的坏缓存，不能当命中
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


def _cli_score_year(in_path: str, out_path: str) -> int:
    import pickle

    payload = pickle.loads(Path(in_path).read_bytes())
    row = run_score_year(payload)
    Path(out_path).write_bytes(pickle.dumps(row, protocol=pickle.HIGHEST_PROTOCOL))
    return 0 if not row.get("error") else 1


if __name__ == "__main__":
    # python batch_job.py --score-year <in.pkl> <out.pkl>
    if len(sys.argv) >= 4 and sys.argv[1] == "--score-year":
        raise SystemExit(_cli_score_year(sys.argv[2], sys.argv[3]))
    raise SystemExit("usage: batch_job.py --score-year <in.pkl> <out.pkl>")
