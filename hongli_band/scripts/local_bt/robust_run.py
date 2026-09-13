# coding: utf-8
"""实盘评估 runner：随机组合连续回放 + 指纹探针 + 汇总。

用法（仓库根目录）::

  python hongli_band/scripts/local_bt/robust_run.py --spec path/to/robust.json
  python hongli_band/scripts/local_bt/robust_run.py --spec path/to/robust.json --summarize-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Callable, Mapping

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from analyze import DEFAULT_CSV_ROOT, resolve_typed_dir  # noqa: E402
from book_backtest import book_log_name, book_stocks_hash, run_book_backtest  # noqa: E402
from grid_progress import (  # noqa: E402
    STATUS_DONE,
    STATUS_RUNNING,
    WAIT_DEAD_SETTLE_SEC,
    WAIT_DEAD_TIMEOUT_SEC,
    build_progress,
    pid_exists,
    python_executable,
    save_progress,
    set_batch_status,
    terminate_process_tree,
    wait_until_dead,
)
from grid_run import (  # noqa: E402
    WALK_PROGRESS_QUEUE_MAX,
    WalkProgress,
    _drain_walk_queue,
    _emit_walk_progress,
    _queue_put,
    assert_fingerprint_text,
    expected_fingerprint,
    init_walk_pool,
    load_config_defaults,
    resolve_pool_workers,
)
from grid_spec import overrides_has_trail_tiers  # noqa: E402
from run import run_init_probe  # noqa: E402
from robust_sample import load_freeze, sample_baskets_for_spec, write_freeze  # noqa: E402
from robust_spec import (  # noqa: E402
    ROBUST_ROOT,
    RobustSpecError,
    WARN_BASKETS_SOFT,
    json_ready,
    load_spec,
    run_dir,
    sampling_fingerprint,
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


def apply_walk_progress(prog: dict[str, Any], state: WalkProgress) -> dict[str, Any]:
    """把 WalkProgress 写进 progress.json 字段。探针不改 n_walks。"""
    prog["batch_walk_total"] = int(state.n_walks)
    prog["batch_walk_done"] = float(state.completed) + float(state.inflight_frac)
    tot = int(state.n_walks)
    prog["batch_cell_total"] = tot
    prog["batch_cell_done"] = min(tot, max(int(state.cells_done), int(state.completed)))
    return prog


def robust_progress_caption(progress: Mapping[str, Any] | None) -> str:
    if not progress:
        return ""
    try:
        tot = int(progress.get("batch_walk_total") or progress.get("batch_cell_total") or 0)
        done_cells = int(progress.get("batch_cell_done") or 0)
        walk_done = float(progress.get("batch_walk_done") or 0)
    except (TypeError, ValueError):
        return ""
    batches = progress.get("batches") or []
    status = ""
    if batches and isinstance(batches[0], dict):
        status = str(batches[0].get("status") or "")
    if tot <= 0:
        return status or ""
    return "已完成 %s/%s 组 · walk %.1f/%s · %s" % (
        done_cells,
        tot,
        walk_done,
        tot,
        status or "—",
    )


def robust_worker_argv(
    *,
    spec_path: str,
    workers: int = 0,
    reshuffle: bool = False,
    force_rerun: bool = False,
    script: str | Path | None = None,
) -> list[str]:
    py = python_executable()
    path = str(script or (HERE / "robust_run.py"))
    cmd = [py, path, "--spec", str(spec_path), "--workers", str(int(workers or 0))]
    if reshuffle:
        cmd.append("--reshuffle")
    if force_rerun:
        cmd.append("--force-rerun")
    return cmd


def stop_robust_worker(
    pid: int,
    *,
    timeout: float = WAIT_DEAD_TIMEOUT_SEC,
) -> dict[str, Any]:
    """杀进程树并等到退出。不标 dirty、不删 basket 目录。"""
    pid = int(pid or 0)
    terminate_process_tree(pid)
    dead = wait_until_dead(pid, timeout=timeout)
    if dead and WAIT_DEAD_SETTLE_SEC > 0:
        time.sleep(WAIT_DEAD_SETTLE_SEC)
        dead = not pid_exists(pid)
    return {"ok": bool(dead)}


def run_one_basket(
    payload: dict[str, Any],
    on_bar_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """子进程入口：跑一组固定标的连续回放。payload 禁止带 callback。"""
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
            on_progress=on_bar_progress,
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


def run_basket_job(payload: dict[str, Any]) -> dict[str, Any]:
    """模块级篮子入口（Windows spawn 可 pickle）。payload 禁止带 progress_queue。"""
    bid = str(payload.get("basket_id") or "")
    job_key = bid
    _queue_put("start", bid, job_key, 0, 0, bid)

    def _on_bar(done_bars: int, tot_bars: int, day: str) -> None:
        year = str(day or "")[:4]
        lab = "回放 %s · %s %s/%s" % (bid, year, done_bars, tot_bars)
        _queue_put("bar", bid, job_key, done_bars, tot_bars, lab)

    row = run_one_basket(payload, on_bar_progress=_on_bar)
    row["job_key"] = job_key
    return row


def _year_span(spec: Mapping[str, Any]) -> tuple[str, str]:
    return "%s0101" % int(spec["year_start"]), "%s1231" % int(spec["year_end"])


def _freeze_from_spec(spec: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = spec.get("baskets")
    if not isinstance(raw, list) or not raw:
        return None
    return {
        "baskets": raw,
        "sampling_fingerprint": spec.get("sampling_fingerprint") or sampling_fingerprint(spec),
        "year_start": spec.get("year_start"),
        "year_end": spec.get("year_end"),
        "n_baskets": spec.get("n_baskets"),
        "basket_size": spec.get("basket_size"),
        "seed": spec.get("seed"),
        "full_span": spec.get("full_span"),
    }


def _run_baskets_serial(
    jobs: list[dict[str, Any]],
    state: WalkProgress,
    on_walk: Callable[..., None] | None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for job in jobs:
        jk = str(job["basket_id"])
        state.start(jk)
        _emit_walk_progress(on_walk, state, jk, "回放 %s" % jk, phase="walk", job_key=jk)

        def _on_bar(
            done_bars: int,
            tot_bars: int,
            day: str,
            _jk: str = jk,
        ) -> None:
            state.bar(_jk, done_bars, tot_bars)
            year = str(day or "")[:4]
            _emit_walk_progress(
                on_walk,
                state,
                _jk,
                "回放 %s · %s %s/%s" % (_jk, year, done_bars, tot_bars),
                phase="walk",
                job_key=_jk,
            )

        row = run_one_basket(job, on_bar_progress=_on_bar)
        results.append(row)
        state.finish(jk)
        state.cells_done += 1
        _emit_walk_progress(on_walk, state, jk, jk, phase="walk", job_key=jk)
    return results


def _run_baskets_in_pool(
    jobs: list[dict[str, Any]],
    pool_workers: int,
    state: WalkProgress,
    on_walk: Callable[..., None] | None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not jobs:
        return results
    ctx = get_context("spawn")
    q = ctx.Queue(maxsize=WALK_PROGRESS_QUEUE_MAX)
    last_cid, last_jk, last_label = "", "", ""
    with ProcessPoolExecutor(
        max_workers=int(pool_workers),
        mp_context=ctx,
        initializer=init_walk_pool,
        initargs=(str(HERE), q),
    ) as ex:
        futs = {ex.submit(run_basket_job, job): job for job in jobs}
        pending = set(futs)
        while pending:
            cid, jk, lab = _drain_walk_queue(q, state)
            if cid:
                last_cid, last_jk, last_label = cid, jk, lab
            done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            cid2, jk2, lab2 = _drain_walk_queue(q, state)
            if cid2:
                last_cid, last_jk, last_label = cid2, jk2, lab2
            for fut in done:
                job = futs[fut]
                jk = str(job.get("basket_id") or "")
                try:
                    row = fut.result()
                except Exception as e:
                    row = {
                        "basket_id": jk,
                        "ok": False,
                        "error": str(e),
                        "stocks": job.get("stocks"),
                    }
                state.finish(jk)
                state.cells_done += 1
                results.append(row)
                last_cid, last_jk, last_label = jk, jk, jk
            _emit_walk_progress(
                on_walk, state, last_cid, last_label, phase="walk", job_key=last_jk
            )
        cid3, jk3, lab3 = _drain_walk_queue(q, state)
        if cid3:
            last_cid, last_jk, last_label = cid3, jk3, lab3
        _emit_walk_progress(
            on_walk, state, last_cid, last_label, phase="walk", job_key=last_jk
        )
    return results


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

    freeze_old = None if reshuffle else (_freeze_from_spec(spec) or load_freeze(freeze_path))
    sampled = sample_baskets_for_spec(spec, reshuffle=reshuffle, freeze=freeze_old)
    n = int(sampled["n_baskets"])
    if n >= WARN_BASKETS_SOFT:
        print("WARN: n_baskets=%s ≥ %s，组合连续回放较重" % (n, WARN_BASKETS_SOFT))

    start, end = _year_span(spec)
    csv = str(csv_root or DEFAULT_CSV_ROOT)
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
        "full_span": sampled.get("full_span"),
        "sampling_fingerprint": sampled.get("sampling_fingerprint") or sampling_fingerprint(spec),
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

    defaults = load_config_defaults()
    need_trail = overrides_has_trail_tiers(spec.get("overrides") or {})
    expected = expected_fingerprint(defaults, spec.get("overrides") or {})
    _emit(on_progress, phase="probe", done=0, total=n, label="探针 init")
    probe_log = root / "probe_init.txt"
    try:
        text = run_init_probe(spec.get("overrides") or {}, log_path=probe_log)
        assert_fingerprint_text(text, expected, need_trail=need_trail, source=str(probe_log))
    except Exception as e:
        raise RobustError("探针失败: %s" % e) from e

    ids = [str(j["basket_id"]) for j in jobs]
    prog = build_progress(ids, 0, worker_pid=os.getpid())
    set_batch_status(prog, 0, STATUS_RUNNING)
    prog["batch_walk_total"] = n
    prog["batch_walk_done"] = 0
    prog["batch_cell_total"] = n
    prog["batch_cell_done"] = 0
    save_progress(root, prog)

    state = WalkProgress(n)
    last_hb = 0.0

    def _heartbeat(force: bool = False) -> None:
        nonlocal last_hb, prog
        now = time.time()
        if not force and now - last_hb < 2.0:
            return
        last_hb = now
        apply_walk_progress(prog, state)
        prog["worker_pid"] = os.getpid()
        prog = save_progress(root, prog)

    def on_walk(cid: str, done: int, tot: int, label: str, **extra: Any) -> None:
        _heartbeat(force=False)
        _emit(
            on_progress,
            phase=str(extra.get("phase") or "run"),
            done=int(done),
            total=int(tot),
            label=label,
            **extra,
        )

    w = resolve_pool_workers(int(workers or 0), n)
    print("pool_workers=%s n_walks=%s" % (w, n), flush=True)
    if w <= 1:
        results = _run_baskets_serial(jobs, state, on_walk)
    else:
        results = _run_baskets_in_pool(jobs, w, state, on_walk)

    apply_walk_progress(prog, state)
    set_batch_status(prog, 0, STATUS_DONE)
    prog["worker_pid"] = os.getpid()
    save_progress(root, prog)

    n_fail = sum(1 for r in results if not r.get("ok"))
    if n_fail:
        print("WARN: %s / %s 组回放失败" % (n_fail, len(results)))

    _emit(on_progress, phase="summarize", done=n, total=n, label="汇总中")
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
