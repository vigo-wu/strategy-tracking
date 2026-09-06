# coding: utf-8
"""滚动选股：打分窗早于持有年 → 组合回放 → 经济硬门。默认不写 BOOK_STOCKS。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from analyze import (
    DEFAULT_CSV_ROOT,
    DEFAULT_DIVIDEND_TYPE,
    DEFAULT_REPORT_ROOT,
    daily_csvs_by_stock,
    resolve_ohlc_csv_dir,
    typed_sibling_dirs,
)
from book_backtest import normalize_book_stocks
from select_analysis import (
    iter_rebalance_periods,
    period_baskets_from_book,
    run_walk_forward,
)
from select_config import (
    SELECT_AMOUNT_DROP_BOTTOM,
    SELECT_CONTRIB_SHARE,
    SELECT_EPS_PNL,
    SELECT_LISTING_MIN_YEARS,
    fill_select_windows,
    hold_eval_years,
    named_filter_cells,
    resolve_named_filters,
    score_years_before_hold,
    select_check_years,
    select_precheck_years,
    select_train_years,
)
from select_qualify import listing_year_from_meta, qualify_stocks
from stock_select import infer_score_years, recommend_to_basket, score_universe

WfRunner = Callable[..., dict[str, Any]]


def _sign(val: float | None, eps: float = SELECT_EPS_PNL) -> int:
    if val is None:
        return 0
    x = float(val)
    if abs(x) < eps:
        return 0
    return 1 if x > 0 else -1


def _merge_listing_meta(cur: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """同代码多份日线：资格取更早的上市日。"""
    a = listing_year_from_meta(cur)
    b = listing_year_from_meta(other)
    if a is None:
        return other
    if b is None:
        return cur
    return other if b < a else cur


def csv_meta_map(csv_root: str | Path | None) -> dict[str, dict[str, Any]]:
    """日线 meta：复权子目录（none/front_ratio/…），不是 tools/csv 根下的扁平文件。"""
    root = Path(csv_root or DEFAULT_CSV_ROOT)
    dirs: list[Path] = []
    try:
        sibs = typed_sibling_dirs(root)
    except Exception:
        sibs = []
    if sibs:
        dirs.extend(p for _div, p in sibs)
    else:
        try:
            dirs.append(resolve_ohlc_csv_dir(root, DEFAULT_DIVIDEND_TYPE))
        except Exception:
            pass
        dirs.append(root)
    seen: set[str] = set()
    out: dict[str, dict[str, Any]] = {}
    for data_dir in dirs:
        key = str(data_dir)
        if key in seen:
            continue
        seen.add(key)
        try:
            rows = daily_csvs_by_stock(data_dir)
        except Exception:
            continue
        for m in rows or []:
            stock = str(m.get("stock") or "").strip().upper()
            if not stock:
                continue
            prev = out.get(stock)
            out[stock] = m if prev is None else _merge_listing_meta(prev, m)
    return out


def _csv_meta_map(csv_root: str | Path | None) -> dict[str, dict[str, Any]]:
    return csv_meta_map(csv_root)


def _emit_select_progress(
    on_progress: Any,
    *,
    phase: str = "",
    done: int = 0,
    total: int = 0,
    year: str = "",
    label: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    if not on_progress:
        return
    try:
        on_progress(
            {
                "phase": str(phase or ""),
                "done": int(done),
                "total": max(int(total), 0),
                "year": str(year or ""),
                "action": "",
                "label": str(label or ""),
                "extra": dict(extra or {}),
            }
        )
    except Exception:
        pass


def prefix_progress(on_progress: Any, prefix: str) -> Any:
    """给 WF 回调的 label 加上路径前缀；缺失或抛错则跳过。"""
    if not on_progress:
        return None
    tag = str(prefix or "").strip()

    def wrapped(ev: dict[str, Any] | None) -> None:
        src = dict(ev or {})
        label = str(src.get("label") or "").strip()
        if tag:
            src["label"] = ("%s · %s" % (tag, label)) if label else tag
        try:
            on_progress(src)
        except Exception:
            pass

    return wrapped


def select_progress_units(
    n_years: int,
    *,
    n_paths: int = 2,
    with_meta: bool = True,
) -> int:
    """一次闸门的进度格：meta + 每年打分 + 每条路径每年一格。"""
    n = max(int(n_years or 0), 0)
    paths = max(int(n_paths or 0), 0)
    return (1 if with_meta else 0) + n * (1 + paths)


class SelectProgressClock:
    """一次点击累计 done/total，禁止换路径时回跳。"""

    def __init__(self, sink: Any, total: int):
        self.sink = sink
        self.total = max(int(total), 1)
        self.done = 0
        self._phase_base = 0
        self._phase_size = 0

    def start_phase(self, size: int) -> None:
        self._phase_base = self.done
        self._phase_size = max(int(size), 0)

    def report(
        self,
        inner_done: int,
        inner_total: int,
        label: str,
        *,
        phase: str = "",
        year: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        if self._phase_size <= 0:
            mapped = self.done
        elif inner_total <= 0:
            mapped = self._phase_base
        else:
            frac = min(1.0, max(0.0, float(inner_done) / float(inner_total)))
            mapped = self._phase_base + int(round(self._phase_size * frac))
        self.done = min(self.total, max(self.done, mapped))
        raw = str(label or "").strip()
        tagged = (
            "总进度 %s/%s · %s" % (self.done, self.total, raw)
            if raw
            else "总进度 %s/%s" % (self.done, self.total)
        )
        _emit_select_progress(
            self.sink,
            phase=phase,
            done=self.done,
            total=self.total,
            year=year,
            label=tagged,
            extra=extra,
        )

    def finish_phase(self) -> None:
        target = min(self.total, self._phase_base + self._phase_size)
        self.done = max(self.done, target)
        self._phase_base = self.done
        self._phase_size = 0

    def callback(self, prefix: str = "") -> Any:
        tag = str(prefix or "").strip()

        def on_progress(ev: dict[str, Any] | None) -> None:
            src = dict(ev or {})
            label = str(src.get("label") or "").strip()
            if tag:
                label = ("%s · %s" % (tag, label)) if label else tag
            try:
                extra = src.get("extra")
                self.report(
                    int(src.get("done") or 0),
                    int(src.get("total") or 0),
                    label,
                    phase=str(src.get("phase") or ""),
                    year=str(src.get("year") or ""),
                    extra=extra if isinstance(extra, dict) else None,
                )
            except Exception:
                pass

        return on_progress


def _with_progress_prefix(prefix: str, label: str) -> str:
    tag = str(prefix or "").strip()
    raw = str(label or "").strip()
    if tag and raw:
        return "%s · %s" % (tag, raw)
    return tag or raw


def assert_no_leak(score_years: tuple[str, ...], hold_years: tuple[str, ...]) -> str:
    """有交集则返回失败原因，否则空串。"""
    score = {int(y) for y in score_years if str(y).isdigit()}
    hold = {int(y) for y in hold_years if str(y).isdigit()}
    if not score:
        return "打分年为空（禁止回落全历史）"
    overlap = score & hold
    if overlap:
        return "打分年与持有年相交: %s" % ",".join(str(y) for y in sorted(overlap))
    if max(score) >= min(hold):
        return "打分年未严格早于持有年"
    return ""


def _pnl_by_year(result: dict[str, Any] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in (result or {}).get("year_rows") or []:
        if str(row.get("status") or "") != "ok":
            continue
        y = str(row.get("year") or "")
        pnl = row.get("portfolio_pnl")
        if not y or pnl is None:
            continue
        try:
            out[y] = float(pnl)
        except (TypeError, ValueError):
            continue
    return out


def _sum_years(by_year: dict[str, float], years: tuple[str, ...]) -> float:
    return round(sum(float(by_year.get(y) or 0.0) for y in years), 2)


def _fail_years(result: dict[str, Any] | None, years: tuple[str, ...]) -> list[str]:
    have = set()
    for row in (result or {}).get("year_rows") or []:
        y = str(row.get("year") or "")
        if y in years and str(row.get("status") or "") == "ok" and row.get("portfolio_pnl") is not None:
            have.add(y)
    return [y for y in years if y not in have]


def build_period_baskets(
    scanned: dict[str, Any],
    *,
    win: dict[str, int],
    filter_overrides: dict[str, Any] | None = None,
    csv_meta_by_stock: dict[str, dict[str, Any]] | None = None,
    amount_by_stock: dict[str, float] | None = None,
    listing_min_years: int = SELECT_LISTING_MIN_YEARS,
    amount_drop_bottom: float = SELECT_AMOUNT_DROP_BOTTOM,
    on_progress: Any = None,
) -> dict[str, Any]:
    """每段持有年用之前的 KPI 打分。泄漏或空窗 → leak 原因。"""
    available = infer_score_years((scanned or {}).get("stocks") or {})
    eval_years = hold_eval_years(win)
    stocks = list(((scanned or {}).get("stocks") or {}).keys())
    baskets: dict[str, dict[str, dict[str, str]]] = {}
    period_meta: list[dict[str, Any]] = []
    leak = ""
    n_passed_max = 0
    n_eval = len(eval_years)
    for i, hy in enumerate(eval_years, 1):
        _emit_select_progress(
            on_progress,
            phase="score",
            done=i,
            total=n_eval,
            year=hy,
            label="按年打分 · 持有 %s" % hy,
        )
        hold = (hy,)
        score_years = score_years_before_hold(hy, win, available)
        reason = assert_no_leak(score_years, hold)
        if reason:
            leak = reason
            period_meta.append(
                {
                    "select_year": hy,
                    "hold_years": list(hold),
                    "score_years": list(score_years),
                    "leak": reason,
                    "n_pick": 0,
                    "n_passed": 0,
                }
            )
            break
        qual = qualify_stocks(
            stocks,
            select_year=int(hy),
            score_years=score_years,
            csv_meta_by_stock=csv_meta_by_stock,
            listing_min_years=listing_min_years,
            amount_drop_bottom=amount_drop_bottom,
            amount_by_stock=amount_by_stock,
        )
        flt = resolve_named_filters(filter_overrides, len(score_years))
        scored = score_universe(
            scanned,
            filters=flt,
            score_years=score_years,
            qualify_ok=qual.get("eligible") or set(),
            strict_score_years=True,
        )
        if scored.get("empty_score_years"):
            leak = "打分年为空（禁止回落全历史）"
            period_meta.append(
                {
                    "select_year": hy,
                    "hold_years": list(hold),
                    "score_years": list(score_years),
                    "leak": leak,
                    "n_pick": 0,
                    "n_passed": 0,
                }
            )
            break
        rec = scored.get("recommend")
        basket = recommend_to_basket(rec)
        baskets[str(hy)] = basket
        passed_df = scored.get("passed")
        n_pass = 0 if passed_df is None or getattr(passed_df, "empty", True) else int(len(passed_df))
        n_passed_max = max(n_passed_max, n_pass)
        period_meta.append(
            {
                "select_year": hy,
                "hold_years": list(hold),
                "score_years": list(score_years),
                "n_pick": len(basket),
                "n_passed": n_pass,
                "n_eligible": int(qual.get("n_eligible") or 0),
                "n_no_listing": int(qual.get("n_no_listing") or 0),
                "n_listing_ok": int(qual.get("n_listing_ok") or 0),
                "amount_cut": qual.get("amount_cut"),
                "filters": flt,
            }
        )
    return {
        "baskets": baskets,
        "periods": period_meta,
        "leak": leak,
        "eval_years": list(eval_years),
        "n_passed_max": n_passed_max,
        "n_universe": len(stocks),
        "meta_empty": not bool(csv_meta_by_stock),
    }


def qualify_fail_reason(built: dict[str, Any] | None) -> str:
    """资格全空时给出硬失败原因（不是泄漏）。"""
    src = built or {}
    n_uni = int(src.get("n_universe") or 0)
    if n_uni <= 0:
        return "扫描宇宙为空，无法选股"
    periods = [p for p in (src.get("periods") or []) if not p.get("leak")]
    if src.get("meta_empty"):
        return "日线 meta 为空，全员无上市日，资格 0 只"
    if periods and all(int(p.get("n_eligible") or 0) == 0 for p in periods):
        n_miss = max(int(p.get("n_no_listing") or 0) for p in periods)
        if n_miss >= n_uni:
            return "资格 0 只：全员无日线上市日"
        return "资格 0 只（上市年限或打分窗成交额分位）"
    return ""


def judge_select_gate(
    *,
    leak: str,
    wf_by_year: dict[str, float],
    book_by_year: dict[str, float],
    train_years: tuple[str, ...],
    precheck_years: tuple[str, ...],
    check_years: tuple[str, ...],
    wf_fail: list[str],
    book_fail: list[str],
    qualify_fail: str = "",
) -> dict[str, Any]:
    """经济硬门。隔离破坏或回放不可用 → FAIL；未优于现行 → KEEP_CURRENT。"""
    intended = tuple(y for y in (train_years + precheck_years + check_years) if y)
    hard_fail = sorted(set(wf_fail + book_fail) & set(intended))
    pnl_train_wf = _sum_years(wf_by_year, train_years)
    pnl_train_book = _sum_years(book_by_year, train_years)
    pnl_pre_wf = _sum_years(wf_by_year, precheck_years)
    pnl_pre_book = _sum_years(book_by_year, precheck_years)
    pnl_check_wf = _sum_years(wf_by_year, check_years)
    pnl_check_book = _sum_years(book_by_year, check_years)
    d_train = round(pnl_train_wf - pnl_train_book, 2)
    d_pre = round(pnl_pre_wf - pnl_pre_book, 2)
    d_check = round(pnl_check_wf - pnl_check_book, 2)
    verdict = "PASS"
    reason = "验收期组合优于现行池且与训练窗同向"
    if leak:
        verdict = "FAIL"
        reason = leak
    elif qualify_fail:
        verdict = "FAIL"
        reason = qualify_fail
    elif [y for y in check_years if y in hard_fail]:
        verdict = "FAIL"
        reason = "验收期组合回放失败: %s" % ",".join(y for y in check_years if y in hard_fail)
    elif len(hard_fail) > 1:
        verdict = "FAIL"
        reason = "组合回放失败年过多: %s" % ",".join(hard_fail)
    elif d_check <= 0:
        verdict = "KEEP_CURRENT"
        reason = "验收期未优于现行池"
    elif _sign(d_check) * _sign(d_train) < 0:
        verdict = "KEEP_CURRENT"
        reason = "选股训练窗与验收期不同向"
    elif _sign(d_pre) * _sign(d_check) < 0:
        verdict = "KEEP_CURRENT"
        reason = "预验收相对现行池与验收期反号"
    elif d_pre < -max(500.0, 0.2 * abs(d_check)):
        verdict = "KEEP_CURRENT"
        reason = "预验收相对现行池显著更差"
    return {
        "verdict": verdict,
        "reason": reason,
        "d_train": d_train,
        "d_precheck": d_pre,
        "d_check": d_check,
        "pnl_train_wf": pnl_train_wf,
        "pnl_train_book": pnl_train_book,
        "pnl_precheck_wf": pnl_pre_wf,
        "pnl_precheck_book": pnl_pre_book,
        "pnl_check_wf": pnl_check_wf,
        "pnl_check_book": pnl_check_book,
        "fail_years": hard_fail,
    }


def _run_path(
    *,
    runner: WfRunner,
    baskets: dict[str, Any],
    eval_years: tuple[str, ...],
    book_params: dict[str, Any] | None,
    csv_root: str | Path,
    report_dir: str | Path,
    force_rerun: bool,
    on_progress: Any,
) -> dict[str, Any]:
    keyed = {str(k): normalize_book_stocks(v) for k, v in (baskets or {}).items()}
    return runner(
        data_start=eval_years[0] if eval_years else "",
        data_end=eval_years[-1] if eval_years else "",
        eval_years=eval_years,
        rebalance_years=1,
        period_baskets=keyed,
        fallback_book={},
        book_params=book_params,
        csv_root=csv_root,
        report_dir=report_dir,
        force_rerun=force_rerun,
        compound_backtest=False,
        on_progress=on_progress,
    )


def turnover_warnings(
    baskets: dict[str, dict[str, dict[str, str]]],
    eval_years: tuple[str, ...],
) -> list[str]:
    notes: list[str] = []
    prev: set[str] | None = None
    for y in eval_years:
        cur = set((baskets.get(str(y)) or {}).keys())
        if prev is not None and cur and prev:
            inter = len(prev & cur)
            union = len(prev | cur) or 1
            jacc = inter / float(union)
            replaced = len(prev - cur)
            if jacc < 0.3:
                notes.append("%s 换手偏大 Jaccard=%.2f" % (y, jacc))
            if replaced > 3:
                notes.append("%s 换票 %s 只" % (y, replaced))
        prev = cur
    return notes


def _pnl_from_per_stock(per: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    if not isinstance(per, dict):
        return out
    for k, v in per.items():
        stock = str(k or "").strip().upper()
        if not stock:
            continue
        raw = v.get("sum_pnl") if isinstance(v, dict) else v
        try:
            out[stock] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


def _row_stock_pnl(row: dict[str, Any] | None) -> dict[str, float]:
    src = row or {}
    mapped = _pnl_from_per_stock(src.get("per_stock"))
    if mapped:
        return mapped
    path = str(src.get("hold_detail_path") or "")
    if not path or not Path(path).is_file():
        return {}
    try:
        from book_backtest import attribute_portfolio_kpi

        return _pnl_from_per_stock(attribute_portfolio_kpi(path))
    except Exception:
        return {}


def contribution_warnings(
    wf_res: dict[str, Any] | None,
    check_years: tuple[str, ...],
    *,
    baskets: dict[str, dict[str, dict[str, str]]] | None = None,
    share_cut: float = SELECT_CONTRIB_SHARE,
) -> list[str]:
    """验收期单票贡献过高 → 软预警，不改硬判决。"""
    notes: list[str] = []
    names: set[str] = set()
    for y in check_years:
        names |= set(((baskets or {}).get(str(y)) or {}).keys())
    if len(names) == 1:
        notes.append("验收期篮子实质单票 %s（无法分散）" % next(iter(names)))
    by_stock: dict[str, float] = {}
    for row in (wf_res or {}).get("year_rows") or []:
        y = str(row.get("year") or "")
        if y not in check_years:
            continue
        for stock, pnl in _row_stock_pnl(row).items():
            by_stock[stock] = by_stock.get(stock, 0.0) + pnl
    if len(by_stock) < 2:
        return notes
    total = sum(by_stock.values())
    if total <= SELECT_EPS_PNL:
        return notes
    top_stock, top_pnl = max(by_stock.items(), key=lambda kv: kv[1])
    if top_pnl <= 0:
        return notes
    share = top_pnl / float(total)
    cut = min(max(float(share_cut or 0.0), 0.0), 1.0)
    if share >= cut:
        notes.append(
            "验收期 %s 贡献组合盈亏 %.0f%%（≥%.0f%%，软预警）"
            % (top_stock, share * 100.0, cut * 100.0)
        )
    return notes


def run_select_gate(
    scanned: dict[str, Any],
    *,
    spec: dict[str, Any] | None = None,
    filter_overrides: dict[str, Any] | None = None,
    book: dict[str, Any] | None = None,
    csv_root: str | Path | None = None,
    report_dir: str | Path | None = None,
    book_params: dict[str, Any] | None = None,
    force_rerun: bool = False,
    include_prev_hold: bool = False,
    wf_runner: WfRunner | None = None,
    csv_meta_by_stock: dict[str, dict[str, Any]] | None = None,
    amount_by_stock: dict[str, float] | None = None,
    on_progress: Any = None,
    progress: SelectProgressClock | None = None,
    progress_prefix: str = "",
    write_files: bool = True,
    with_overfit: bool = True,
    n_filter_cells: int = 1,
) -> dict[str, Any]:
    """硬门关闭复利；默认只跑 wf_picks vs book_frozen。"""
    from select_config import load_book_stocks_full

    win = fill_select_windows(spec)
    csv_root = csv_root or DEFAULT_CSV_ROOT
    report_dir = report_dir or DEFAULT_REPORT_ROOT
    frozen_book = normalize_book_stocks(book if book is not None else load_book_stocks_full())
    runner = wf_runner or run_walk_forward
    eval_plan = hold_eval_years(win)
    n_years = len(eval_plan)
    n_paths = 2 + (1 if include_prev_hold else 0)
    with_meta = csv_meta_by_stock is None
    clock = progress
    if clock is None and on_progress:
        clock = SelectProgressClock(
            on_progress,
            select_progress_units(n_years, n_paths=n_paths, with_meta=with_meta),
        )
    pfx = str(progress_prefix or "").strip()

    def _phase_cb(tag: str = "") -> Any:
        if clock is None:
            joined = _with_progress_prefix(pfx, tag) if tag else pfx
            return prefix_progress(on_progress, joined) if joined else on_progress
        return clock.callback(_with_progress_prefix(pfx, tag) if tag else pfx)

    if csv_meta_by_stock is not None:
        metas = csv_meta_by_stock
    else:
        if clock is not None:
            clock.start_phase(1)
        _emit_select_progress(
            _phase_cb(),
            phase="meta",
            done=0,
            total=1,
            label="读取日线上市日（复权子目录）…",
        )
        metas = _csv_meta_map(csv_root)
        _emit_select_progress(
            _phase_cb(),
            phase="meta",
            done=1,
            total=1,
            label="读取日线上市日完成",
        )
        if clock is not None:
            clock.finish_phase()
    if clock is not None:
        clock.start_phase(n_years)
    built = build_period_baskets(
        scanned,
        win=win,
        filter_overrides=filter_overrides,
        csv_meta_by_stock=metas,
        amount_by_stock=amount_by_stock,
        on_progress=_phase_cb(),
    )
    if clock is not None:
        clock.finish_phase()
    leak = str(built.get("leak") or "")
    qfail = "" if leak else qualify_fail_reason(built)
    eval_years = tuple(str(y) for y in (built.get("eval_years") or hold_eval_years(win)))
    train_years = select_train_years(win)
    pre_years = select_precheck_years(win)
    check_years = select_check_years(win)
    picks = built.get("baskets") or {}
    paths: dict[str, dict[str, Any]] = {}
    wf_res: dict[str, Any] = {}
    book_res: dict[str, Any] = {}
    if leak or qfail:
        judged = judge_select_gate(
            leak=leak,
            qualify_fail=qfail,
            wf_by_year={},
            book_by_year={},
            train_years=train_years,
            precheck_years=pre_years,
            check_years=check_years,
            wf_fail=list(eval_years),
            book_fail=list(eval_years),
        )
    else:
        periods = iter_rebalance_periods(eval_years, 1)
        book_baskets = period_baskets_from_book(periods, frozen_book)
        if clock is not None:
            clock.start_phase(n_years)
        wf_res = _run_path(
            runner=runner,
            baskets=picks,
            eval_years=eval_years,
            book_params=book_params,
            csv_root=csv_root,
            report_dir=report_dir,
            force_rerun=force_rerun,
            on_progress=_phase_cb("自动篮"),
        )
        if clock is not None:
            clock.finish_phase()
            clock.start_phase(n_years)
        book_res = _run_path(
            runner=runner,
            baskets=book_baskets,
            eval_years=eval_years,
            book_params=book_params,
            csv_root=csv_root,
            report_dir=report_dir,
            force_rerun=force_rerun,
            on_progress=_phase_cb("现行池"),
        )
        if clock is not None:
            clock.finish_phase()
        if include_prev_hold:
            prev: dict[str, dict[str, str]] | None = None
            prev_baskets: dict[str, dict[str, dict[str, str]]] = {}
            for y in eval_years:
                prev_baskets[str(y)] = dict(prev) if prev else dict(frozen_book)
                prev = dict(picks.get(str(y)) or frozen_book)
            if clock is not None:
                clock.start_phase(n_years)
            paths["prev_hold"] = _run_path(
                runner=runner,
                baskets=prev_baskets,
                eval_years=eval_years,
                book_params=book_params,
                csv_root=csv_root,
                report_dir=report_dir,
                force_rerun=force_rerun,
                on_progress=_phase_cb("上一段篮子"),
            )
            if clock is not None:
                clock.finish_phase()
        wf_by = _pnl_by_year(wf_res)
        book_by = _pnl_by_year(book_res)
        judged = judge_select_gate(
            leak="",
            wf_by_year=wf_by,
            book_by_year=book_by,
            train_years=train_years,
            precheck_years=pre_years,
            check_years=check_years,
            wf_fail=_fail_years(wf_res, eval_years),
            book_fail=_fail_years(book_res, eval_years),
        )
        paths["wf_picks"] = wf_res
        paths["book_frozen"] = book_res

    warnings = turnover_warnings(picks, eval_years)
    warnings.extend(contribution_warnings(wf_res, check_years, baskets=picks))
    last_year = eval_years[-1] if eval_years else ""
    next_basket = dict(picks.get(str(last_year)) or {})
    out = {
        "windows": {
            "year_start": win["year_start"],
            "year_end": win["year_end"],
            "lookback": win["lookback"],
            "train_hold": list(train_years),
            "precheck_year": win["precheck_year"],
            "precheck_hold": list(pre_years),
            "check_hold": list(check_years),
            "eval_years": list(eval_years),
        },
        "compound_backtest": False,
        "leak": leak,
        "qualify_fail": qfail,
        "periods": built.get("periods") or [],
        "picks": picks if judged.get("verdict") == "PASS" else {},
        "next_basket": next_basket if judged.get("verdict") == "PASS" else {},
        "next_basket_note": (
            "PASS 产物是按年 picks.json。"
            "把最后一年 Top N 写进 BOOK_STOCKS 等于放弃滚动、验收作废。"
        ),
        "gate": judged,
        "warnings": warnings,
        "n_passed_max": int(built.get("n_passed_max") or 0),
        "n_filter_cells": max(int(n_filter_cells), 1),
        "note": "扫描宇宙是已有 local_bt 报告，不是全 A 股。资格无 ST。默认不改 config / 不 deploy。",
    }
    out["paths"] = {
        k: {"summary": (v or {}).get("summary"), "year_rows": (v or {}).get("year_rows")}
        for k, v in paths.items()
    }
    out["_wf_raw"] = wf_res
    out["_book_raw"] = book_res
    if with_overfit:
        try:
            from select_overfit import select_overfit_report

            out["overfit"] = select_overfit_report(out)
        except Exception as e:
            out["overfit"] = {"status": "skip", "reason": str(e)}
    else:
        out["overfit"] = {"status": "skip", "reason": "实验室未跑统计预警"}
    if write_files:
        root = Path(report_dir)
        root.mkdir(parents=True, exist_ok=True)
        picks_path = root / "picks.json"
        gate_path = root / "select_gate.json"
        verdict = str(judged.get("verdict") or "")
        if verdict == "PASS":
            picks_path.write_text(
                json.dumps(picks, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            out["picks_path"] = str(picks_path)
        else:
            if picks_path.is_file():
                try:
                    picks_path.unlink()
                except OSError:
                    pass
            out["picks_path"] = ""
            out["picks_skipped"] = "非 PASS 不写 picks.json"
        dump = dict(out)
        dump.pop("paths", None)
        dump.pop("_wf_raw", None)
        dump.pop("_book_raw", None)
        gate_path.write_text(
            json.dumps(_json_ready(dump), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        out["gate_path"] = str(gate_path)
    return out


def _json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_ready(x) for x in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def run_filter_lab(
    scanned: dict[str, Any],
    *,
    spec: dict[str, Any] | None = None,
    book: dict[str, Any] | None = None,
    csv_root: str | Path | None = None,
    report_dir: str | Path | None = None,
    book_params: dict[str, Any] | None = None,
    force_rerun: bool = False,
    wf_runner: WfRunner | None = None,
    csv_meta_by_stock: dict[str, dict[str, Any]] | None = None,
    amount_by_stock: dict[str, float] | None = None,
    on_progress: Any = None,
    progress: SelectProgressClock | None = None,
) -> dict[str, Any]:
    """训练窗预选过滤组，预验收确认。默认不跑验收期。"""
    win = fill_select_windows(spec)
    lab_years = tuple(
        y for y in hold_eval_years(win) if int(y) <= int(win["precheck_year"])
    )
    if not lab_years:
        return {"id": "base", "reason": "无训练/预验收持有年", "cells": []}
    lab_spec = dict(spec or {})
    lab_spec["year_end"] = int(win["precheck_year"])
    notes: list[dict[str, Any]] = []
    passers: list[tuple[str, float, dict[str, Any]]] = []
    cells = named_filter_cells()
    with_meta = csv_meta_by_stock is None
    clock = progress
    if clock is None and on_progress:
        clock = SelectProgressClock(
            on_progress,
            len(cells) * select_progress_units(len(lab_years), with_meta=with_meta),
        )
    for cell in cells:
        cell_id = str(cell.get("id") or "")
        gate = run_select_gate(
            scanned,
            spec=lab_spec,
            filter_overrides=cell.get("overrides"),
            book=book,
            csv_root=csv_root,
            report_dir=report_dir,
            book_params=book_params,
            force_rerun=force_rerun,
            wf_runner=wf_runner,
            csv_meta_by_stock=csv_meta_by_stock,
            amount_by_stock=amount_by_stock,
            progress=clock,
            progress_prefix="过滤组 %s" % cell_id,
            write_files=False,
            with_overfit=False,
        )
        g = gate.get("gate") or {}
        row = {
            "id": cell["id"],
            "label": cell.get("label"),
            "kind": cell.get("kind"),
            "d_train": g.get("d_train"),
            "d_precheck": g.get("d_precheck"),
            "verdict": g.get("verdict"),
            "reason": g.get("reason"),
        }
        notes.append(row)
        if str(g.get("verdict") or "") == "FAIL":
            continue
        if _sign(g.get("d_train")) <= 0:
            continue
        if _sign(g.get("d_precheck")) * _sign(g.get("d_train")) < 0:
            continue
        passers.append((str(cell["id"]), float(g.get("d_train") or 0), cell))
    if not passers:
        base = next((c for c in named_filter_cells() if c["id"] == "base"), named_filter_cells()[0])
        return {
            "id": "base",
            "label": base.get("label"),
            "overrides": base.get("overrides") or {},
            "reason": "训练窗未优于现行或预验收反号，冻结 base",
            "cells": notes,
        }
    best = max(passers, key=lambda x: x[1])
    picked = best[2]
    return {
        "id": picked["id"],
        "label": picked.get("label"),
        "overrides": picked.get("overrides") or {},
        "reason": "以选股训练窗 Δ 为主且预验收未反号",
        "cells": notes,
    }
