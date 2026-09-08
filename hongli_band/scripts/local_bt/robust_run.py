# coding: utf-8
"""实盘评估 runner：随机组合连续回放 + 指纹探针 + 汇总。

用法（仓库根目录）::

  python hongli_band/scripts/local_bt/robust_run.py --spec path/to/robust.json
  python hongli_band/scripts/local_bt/robust_run.py --spec path/to/robust.json --summarize-only
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Callable, Mapping

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from analyze import DEFAULT_CSV_ROOT, resolve_typed_dir  # noqa: E402
from book_backtest import book_log_name, book_stocks_hash, run_book_backtest  # noqa: E402
from grid_run import (  # noqa: E402
    assert_fingerprint_text,
    expected_fingerprint,
    load_config_defaults,
)
from run import run_init_probe  # noqa: E402
from robust_sample import load_freeze, sample_baskets_for_spec, write_freeze  # noqa: E402
from robust_spec import (  # noqa: E402
    ROBUST_ROOT,
    RobustSpecError,
    WARN_BASKETS_SOFT,
    json_ready,
    load_spec,
    run_dir,
)
from robust_summarize import summarize_run  # noqa: E402
from select_analysis import _book_overrides  # noqa: E402
from select_config import load_book_defaults  # noqa: E402
from trades_csv import trades_csv_path  # noqa: E402

ProgressCb = Callable[[dict[str, Any]], None] | None


class RobustError(Exception):
    """运行期错误。"""


def _emit(on_progress: ProgressCb, **kwargs: Any) -> None:
    if not on_progress:
        return
    try:
        on_progress(dict(kwargs))
    except Exception:
        pass


def _basket_book(
    stocks: list[str],
    *,
    ma_type: str,
    dividend_type: str,
) -> dict[str, dict[str, str]]:
    return {
        str(s).upper(): {"ma_type": ma_type, "dividend_type": dividend_type}
        for s in stocks
        if str(s).strip()
    }


def _merged_overrides(
    strategy_ov: Mapping[str, Any],
    *,
    compound: bool,
) -> dict[str, Any]:
    base = _book_overrides(load_book_defaults())
    out = dict(base)
    out.update(dict(strategy_ov or {}))
    if compound:
        out["compound_backtest"] = True
        out["wallet_cash"] = float(out.get("TRADE_BUDGET") or 100000.0)
    return out


def run_one_basket(payload: dict[str, Any]) -> dict[str, Any]:
    """子进程入口：跑一组固定标的连续回放。"""
    basket_id = str(payload["basket_id"])
    stocks = list(payload["stocks"])
    out_dir = Path(payload["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    book = _basket_book(
        stocks,
        ma_type=str(payload.get("ma_type") or "EMA"),
        dividend_type=str(payload.get("compare_div") or "front_ratio"),
    )
    overrides = _merged_overrides(
        payload.get("overrides") or {},
        compound=bool(payload.get("compound_backtest", True)),
    )
    start = str(payload["start"])
    end = str(payload["end"])
    csv_root = payload.get("csv_root") or DEFAULT_CSV_ROOT
    htag = book_stocks_hash(book)
    log_name = book_log_name(kind="fixed", year=start, tag=htag, end=end)
    # isolate per basket folder; avoid name collision across baskets
    log_name = "%s_%s" % (basket_id, log_name)
    force = bool(payload.get("force_rerun"))
    log_path = out_dir / log_name
    tp = trades_csv_path(log_path)
    try:
        if tp.is_file() and not force:
            return {
                "basket_id": basket_id,
                "ok": True,
                "cached": True,
                "log_path": str(log_path),
                "trades_path": str(tp),
                "stocks": stocks,
            }
        _lp, meta = run_book_backtest(
            book,
            start,
            end,
            csv_root,
            out_dir,
            log_name=log_name,
            quiet=True,
            overrides=overrides,
        )
        return {
            "basket_id": basket_id,
            "ok": True,
            "cached": False,
            "log_path": str(_lp),
            "trades_path": str(trades_csv_path(_lp)),
            "stocks": stocks,
            "meta": meta,
        }
    except Exception as e:
        return {
            "basket_id": basket_id,
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "stocks": stocks,
        }


def _year_span(spec: Mapping[str, Any]) -> tuple[str, str]:
    return "%s0101" % int(spec["year_start"]), "%s1231" % int(spec["year_end"])


def run_robust(
    spec_raw: str | Path | Mapping[str, Any],
    *,
    reshuffle: bool = False,
    workers: int = 0,
    force_rerun: bool = False,
    summarize_only: bool = False,
    dry_run: bool = False,
    gate_override: Mapping[str, Any] | None = None,
    on_progress: ProgressCb = None,
    csv_root: str | Path | None = None,
) -> dict[str, Any]:
    spec = load_spec(spec_raw)
    if gate_override is not None:
        from robust_gate import validate_gate

        spec["gate"] = validate_gate(gate_override)

    root = run_dir(spec)
    root.mkdir(parents=True, exist_ok=True)
    freeze_path = root / "freeze.json"
    spec_path = root / "spec.json"

    if summarize_only:
        out = summarize_run(root, gate=spec.get("gate"), spec=spec)
        _emit(on_progress, phase="done", done=1, total=1, label="只汇总完成")
        return out

    freeze_old = None if reshuffle else load_freeze(freeze_path)
    sampled = sample_baskets_for_spec(spec, reshuffle=reshuffle, freeze=freeze_old)
    n = int(sampled["n_baskets"])
    if n >= WARN_BASKETS_SOFT:
        print("WARN: n_baskets=%s ≥ %s，组合连续回放较重" % (n, WARN_BASKETS_SOFT))

    start, end = _year_span(spec)
    csv = str(csv_root or DEFAULT_CSV_ROOT)
    # typed root for dividends
    try:
        csv = str(resolve_typed_dir(csv, spec["compare_div"]).parent)
    except Exception:
        pass

    payload_common = {
        "start": start,
        "end": end,
        "csv_root": csv,
        "ma_type": spec["ma_type"],
        "compare_div": spec["compare_div"],
        "overrides": dict(spec.get("overrides") or {}),
        "compound_backtest": bool(spec.get("compound_backtest", True)),
        "force_rerun": force_rerun,
    }

    freeze_body = {
        **json_ready(spec),
        "baskets": sampled["baskets"],
        "eligible_n": sampled["eligible_n"],
        "mean_jaccard": sampled["mean_jaccard"],
        "universe_dir": sampled["universe_dir"],
        "_overrides_meta": spec.get("_overrides_meta"),
    }
    write_freeze(freeze_path, freeze_body)
    spec_path.write_text(
        json.dumps(
            json_ready({**spec, "_overrides_meta": spec.get("_overrides_meta")}),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    jobs = []
    for row in sampled["baskets"]:
        bid = str(row["id"])
        jobs.append(
            {
                **payload_common,
                "basket_id": bid,
                "stocks": list(row["stocks"]),
                "out_dir": str(root / bid),
            }
        )

    if dry_run:
        print(
            "dry-run run_id=%s baskets=%s size=%s years=%s-%s overrides=%s"
            % (
                spec["run_id"],
                n,
                spec["basket_size"],
                spec["year_start"],
                spec["year_end"],
                list((spec.get("overrides") or {}).keys()) or "(base)",
            )
        )
        return {"dry_run": True, "n_baskets": n, "root": str(root), "spec": json_ready(spec)}

    # init 探针：不回放 K 线；通过后全部篮子（含第一组）再跑
    defaults = load_config_defaults()
    need_trail = "TRAIL_TIERS" in (spec.get("overrides") or {})
    expected = expected_fingerprint(defaults, spec.get("overrides") or {})
    _emit(on_progress, phase="probe", done=0, total=n, label="探针 init")
    probe_log = root / "probe_init.txt"
    try:
        text = run_init_probe(spec.get("overrides") or {}, log_path=probe_log)
        assert_fingerprint_text(text, expected, need_trail=need_trail, source=str(probe_log))
    except Exception as e:
        raise RobustError("探针失败: %s" % e) from e

    results: list[dict[str, Any]] = []
    rest = jobs
    w = int(workers or 0)
    if w <= 0:
        w = min(4, max(1, (len(rest) or 1)))
    done = 0
    if rest:
        _emit(
            on_progress,
            phase="run",
            done=0,
            total=n,
            label="回放 %s" % str(rest[0]["basket_id"]),
        )
        if w == 1:
            for job in rest:
                _emit(
                    on_progress,
                    phase="run",
                    done=done,
                    total=n,
                    label="回放 %s" % str(job["basket_id"]),
                )
                row = run_one_basket(job)
                results.append(row)
                done += 1
                _emit(
                    on_progress,
                    phase="run",
                    done=done,
                    total=n,
                    label=str(job["basket_id"]),
                    extra={"ok": row.get("ok")},
                )
        else:
            ctx = get_context("spawn")
            with ProcessPoolExecutor(max_workers=w, mp_context=ctx) as ex:
                futs = {ex.submit(run_one_basket, job): job for job in rest}
                for fut in as_completed(futs):
                    job = futs[fut]
                    try:
                        row = fut.result()
                    except Exception as e:
                        row = {
                            "basket_id": job["basket_id"],
                            "ok": False,
                            "error": str(e),
                            "stocks": job.get("stocks"),
                        }
                    results.append(row)
                    done += 1
                    _emit(
                        on_progress,
                        phase="run",
                        done=done,
                        total=n,
                        label=str(job["basket_id"]),
                        extra={"ok": row.get("ok")},
                    )

    n_fail = sum(1 for r in results if not r.get("ok"))
    if n_fail:
        print("WARN: %s / %s 组回放失败" % (n_fail, len(results)))

    _emit(on_progress, phase="summarize", done=n, total=n, label="汇总中")
    # ensure _overrides_meta on disk spec for summarize
    summary = summarize_run(root, gate=spec.get("gate"), spec=spec)
    _emit(
        on_progress,
        phase="done",
        done=n,
        total=n,
        label="完成 %s" % (summary.get("verdict") or {}).get("verdict"),
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="实盘评估：随机组合稳健门")
    ap.add_argument("--spec", required=True, help="robust JSON / 或已有 run 目录的 spec")
    ap.add_argument("--reshuffle", action="store_true")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--force-rerun", action="store_true")
    ap.add_argument("--summarize-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--gate-json", default="", help="覆盖 gate 的 JSON 文件或内联对象")
    ap.add_argument("--csv-root", default="")
    args = ap.parse_args(argv)

    gate_ov = None
    if str(args.gate_json or "").strip():
        raw = str(args.gate_json).strip()
        p = Path(raw)
        if p.is_file():
            gate_ov = json.loads(p.read_text(encoding="utf-8"))
        else:
            gate_ov = json.loads(raw)

    try:
        out = run_robust(
            args.spec,
            reshuffle=bool(args.reshuffle),
            workers=int(args.workers or 0),
            force_rerun=bool(args.force_rerun),
            summarize_only=bool(args.summarize_only),
            dry_run=bool(args.dry_run),
            gate_override=gate_ov,
            csv_root=args.csv_root or None,
        )
    except (RobustSpecError, RobustError) as e:
        print("ERROR:", e, file=sys.stderr)
        return 2
    verdict = (out.get("verdict") or {}) if isinstance(out, dict) else {}
    if isinstance(verdict, dict) and verdict.get("verdict"):
        print("verdict", verdict.get("verdict"), verdict.get("reason"))
        print("summary", out.get("summary_path") or (ROBUST_ROOT / str(out.get("run_id") or "")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
