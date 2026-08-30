# coding: utf-8
"""无头回放 HlBand：本地日线 CSV + 真实拼接脚本。"""
from __future__ import annotations

import argparse
import importlib.util
import os
import runpy
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TextIO


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
THEME = REPO / "hongli_band"
QMT_DIR = THEME / "scripts" / "qmt"
HLBAND = QMT_DIR / "hlband"
DEPLOY_PY = QMT_DIR / "_deploy_qmt_gbk.py"
REPORT_PY = (
    REPO / ".cursor" / "skills" / "qmt-backtest-report" / "scripts" / "generate_report.py"
)

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from market_csv import (  # noqa: E402
    MarketStore,
    find_weekly_csv,
    load_daily_csv,
    load_weekly_csv,
    peek_daily_csv_meta,
    walk_days,
)
from mock_qmt import MockContext, _as_tag, inject_qmt_globals  # noqa: E402
from trades_csv import TradeLedger, trades_csv_path, wrap_fill_hooks  # noqa: E402

from qmt_common._deploy_lib import build_bundle  # noqa: E402

import numpy as np  # noqa: E402

_BUNDLE_CODE = None
_STORE_CACHE: dict[tuple, MarketStore] = {}
MA_TYPES = ("SMA", "EMA")


class _Tee:
    def __init__(self, *streams: TextIO):
        self.streams = streams

    def write(self, data):
        n = len(data) if data is not None else 0
        for s in self.streams:
            s.write(data)
        return n

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def _drop_quiet_line(line: str) -> bool:
    if "BUY" in line or "SELL" in line or "pending" in line or "diag:" in line:
        return False
    if " n1d=" in line or "w_bear streak" in line:
        return True
    return False


class _QuietFile:
    """块缓冲写 log；丢掉状态行 / w_bear streak。"""

    def __init__(self, inner: TextIO):
        self.inner = inner
        self._buf = ""

    def write(self, data):
        if not data:
            return 0
        text = data if isinstance(data, str) else str(data)
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if not _drop_quiet_line(line):
                self.inner.write(line + "\n")
        return len(text)

    def flush(self):
        if self._buf:
            if not _drop_quiet_line(self._buf):
                self.inner.write(self._buf)
            self._buf = ""
        try:
            self.inner.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    @property
    def encoding(self):
        return getattr(self.inner, "encoding", "utf-8")


def _load_module_order():
    spec = importlib.util.spec_from_file_location("hlband_deploy", DEPLOY_PY)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load %s" % DEPLOY_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.MODULE_ORDER)


def _stock_tag(stock: str) -> str:
    return str(stock).replace(".", "_")


def normalize_ma_type(raw: Any) -> str:
    s = str(raw or "").strip().upper()
    return s if s in MA_TYPES else ""


def default_log_name(stock: str, year: str = "", ma_type: str = "") -> str:
    parts = ["local_bt", _stock_tag(stock)]
    year_s = str(year or "").strip()
    if year_s:
        parts.append(year_s)
    ma = normalize_ma_type(ma_type)
    if ma:
        parts.append(ma)
    return "_".join(parts) + ".txt"


def _as_trail_tiers(raw: Any) -> tuple:
    if not raw:
        return ()
    out = []
    for row in raw:
        if row is None:
            continue
        seq = list(row)
        while len(seq) < 4:
            seq.append(None)
        lo, hi, gb, fl = seq[0], seq[1], seq[2], seq[3]
        out.append(
            (
                float(lo),
                None if hi is None else float(hi),
                float(gb),
                None if fl is None else float(fl),
            )
        )
    return tuple(out)


def apply_config_overrides(ns: dict[str, Any], overrides: Mapping[str, Any] | None) -> None:
    """把命名格子的覆盖写进拼接脚本命名空间（运行时全局）。"""
    if not overrides:
        return
    for raw_k, val in overrides.items():
        key = str(raw_k)
        if key == "TRAIL_TIERS":
            ns[key] = _as_trail_tiers(val)
        else:
            ns[key] = val


def install_config_overrides(ns: dict[str, Any], overrides: Mapping[str, Any] | None) -> None:
    """exec 之后立刻覆盖；并包一层 _apply_panel，避免面板把 STOP_LOSS 打回默认。"""
    if not overrides:
        return
    apply_config_overrides(ns, overrides)
    orig = ns.get("_apply_panel")

    def _apply_panel_then_overrides():
        if callable(orig):
            orig()
        apply_config_overrides(ns, overrides)

    ns["_apply_panel"] = _apply_panel_then_overrides


def _apply_ma_type(ns: dict, kind: str) -> str:
    k = normalize_ma_type(kind)
    if not k:
        return ""
    ns["MA_TYPE"] = k
    ns["_MA_TYPE_BAD"] = False

    def _forced(_k=k):
        return _k

    ns["_ma_kind"] = _forced
    return k


def _bundle_code():
    global _BUNDLE_CODE
    if _BUNDLE_CODE is None:
        order = _load_module_order()
        text = build_bundle(order, HLBAND)
        _BUNDLE_CODE = compile(text, "qmt_terminal_hlband.py", "exec")
    return _BUNDLE_CODE


def _exec_bundle() -> dict:
    ns: dict = {"__name__": "hlband_local"}
    exec(_bundle_code(), ns, ns)
    inject_qmt_globals(ns)
    return ns


def _patch_quiet_status(ns: dict) -> None:
    def _should_emit_bar_status(_c, _now, force, _status_idle):
        return bool(force)

    ns["_should_emit_bar_status"] = _should_emit_bar_status


def _patch_fast_ohlcv(ns: dict) -> None:
    """本地 Mock：按 barpos 切 numpy 列，跳过 list 往返与二次丢未收盘周。"""
    orig_series = ns.get("_series_from_ex")

    def _series_from_ex(md, stock, field):
        if md is not None and isinstance(md, dict):
            df = md.get(stock)
            if df is None and md:
                df = next(iter(md.values()))
            if df is not None:
                try:
                    obj = df[field]
                    if isinstance(obj, np.ndarray):
                        return obj
                except Exception:
                    pass
        if callable(orig_series):
            return orig_series(md, stock, field)
        return None

    def _ohlcv_from_ctx(C, period, count, need, diag_key):
        fn = getattr(C, "ohlcv", None)
        tup = fn(period, count) if callable(fn) else None
        if tup is None:
            return None
        _open, _high, _low, close, _volume = tup
        if close is None or len(close) < int(need):
            return None
        tail = close[-min(20, len(close)) :]
        if np.std(np.asarray(tail, dtype=float)) < 1e-8:
            diag = ns.get("_diag_once")
            if callable(diag):
                diag(diag_key + "_flat", "n=", len(close), "source=", "store.ohlcv")
            return None
        diag = ns.get("_diag_once")
        if callable(diag):
            end_fn = getattr(C, "walk_end_day", None)
            end = end_fn() if callable(end_fn) else ""
            chart_fn = ns.get("_chart_dividend")
            chart = "-"
            if callable(chart_fn):
                try:
                    chart = chart_fn(C) or "-"
                except Exception:
                    chart = "-"
            div_fn = ns.get("_dividend_type")
            div = div_fn() if callable(div_fn) else ""
            diag(
                diag_key + "_ok",
                "source=",
                "store.ohlcv",
                "period=",
                period,
                "n=",
                len(close),
                "end=",
                end,
                "last=",
                round(float(close[-1]), 4),
                "div=",
                div,
                "chart=",
                chart,
            )
        return tup

    def _get_ohlcv_1d(C, stock):
        plat_n = int(ns.get("SCALE_PLAT_LOOKBACK") or 20)
        need = max(
            int(ns.get("D_MA_SLOW") or 0),
            int(ns.get("VOL_PULLBACK_N") or 0),
            int(ns.get("VOL_DRY_N") or 0),
            plat_n + 2,
        ) + 10
        period = getattr(ns.get("A"), "period", "1d")
        return _ohlcv_from_ctx(C, period, int(ns.get("OHLC_COUNT") or 180), need, "d1")

    def _get_ohlcv_1w(C, stock):
        need = max(
            int(ns.get("W_MA_SLOW") or 0),
            int(ns.get("MACD_SLOW") or 0) + int(ns.get("MACD_SIGNAL") or 0),
        ) + 5
        return _ohlcv_from_ctx(C, "1w", int(ns.get("WEEKLY_OHLC_COUNT") or 120), need, "w1")

    ns["_series_from_ex"] = _series_from_ex
    ns["_get_ohlcv_1d"] = _get_ohlcv_1d
    ns["_get_ohlcv_1w"] = _get_ohlcv_1w


def _empty_row(
    csv_path: Path,
    stock: str,
    year: str = "",
    ma_type: str = "",
    dividend_type: str = "",
    out_dir: str = "",
) -> dict[str, Any]:
    return {
        "stock": stock,
        "year": str(year or ""),
        "ma_type": normalize_ma_type(ma_type),
        "dividend_type": str(dividend_type or ""),
        "csv": str(csv_path),
        "out_dir": str(out_dir or ""),
        "log": "",
        "detail": "",
        "budget": None,
        "walk_start": "",
        "walk_end": "",
        "n_bars": 0,
        "ok": False,
        "error": "",
    }


def _store_cache_key(
    csv_path: Path,
    weekly_path: Path | None,
) -> tuple:
    p = csv_path.resolve()
    st = p.stat()
    wk: tuple = ("", 0, 0)
    if weekly_path is not None:
        w = Path(weekly_path)
        if w.is_file():
            ws = w.stat()
            wk = (str(w.resolve()), int(ws.st_mtime_ns), int(ws.st_size))
    return (str(p), int(st.st_mtime_ns), int(st.st_size), wk)


def clear_market_store_cache() -> None:
    _STORE_CACHE.clear()


def get_market_store(
    csv_path: str | Path,
    stock: str = "",
    weekly_csv: str | Path | None = None,
) -> MarketStore:
    path = Path(csv_path)
    weekly_path = Path(weekly_csv) if weekly_csv else find_weekly_csv(path, stock)
    if weekly_path and not Path(weekly_path).is_file():
        weekly_path = None
    key = _store_cache_key(path, Path(weekly_path) if weekly_path else None)
    cached = _STORE_CACHE.get(key)
    if cached is not None:
        return cached
    code, bars = load_daily_csv(path, stock=stock)
    weekly_bars = None
    weekly_src = "aggregate drop_forming"
    if weekly_path and Path(weekly_path).is_file():
        _, weekly_bars = load_weekly_csv(weekly_path, stock=code)
        weekly_src = "native %s n=%s" % (weekly_path, len(weekly_bars))
    store = MarketStore(bars, code, weekly=weekly_bars)
    store.weekly_src = weekly_src
    _STORE_CACHE[key] = store
    return store


def run_backtest(
    csv_path: str | Path,
    start: str = "",
    end: str = "",
    stock: str = "",
    out_dir: str | Path | None = None,
    log_name: str = "",
    weekly_csv: str | Path | None = None,
    quiet: bool = True,
    ma_type: str = "",
    store: MarketStore | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Path:
    path = Path(csv_path)
    if store is None:
        store = get_market_store(path, stock=stock, weekly_csv=weekly_csv)
    code = store.stock
    bars = store.bars
    walk = walk_days(bars, start=start, end=end)
    if not walk:
        raise SystemExit("no bars in walk range start=%s end=%s" % (start, end))
    weekly_src = str(getattr(store, "weekly_src", "") or "aggregate drop_forming")

    tags = [_as_tag(b.dt) for b in walk]
    ctx = MockContext(store, tags, code)
    ctx.start = start or walk[0].day
    ctx.end = end or walk[-1].day
    ctx.barpos = 0

    dest = Path(out_dir) if out_dir else THEME / "report"
    dest.mkdir(parents=True, exist_ok=True)
    ma = normalize_ma_type(ma_type)
    fname = log_name.strip() if log_name else ""
    if not fname:
        fname = default_log_name(code, ma_type=ma)
    elif ma:
        stem = Path(fname).stem
        suf = "_" + ma
        if not stem.upper().endswith(suf):
            fname = stem + suf + (Path(fname).suffix or ".txt")
    log_path = dest / fname

    n_w0 = 0
    w0 = store.ohlcv("1w", walk[0].day, count=120)
    if w0 is not None:
        n_w0 = len(w0[3])
    banner = (
        "local_bt %s csv= %s walk= %s %s n= %s hist_n= %s weekly= %s n_w_start= %s ma_type= %s"
        % (
            code,
            csv_path,
            walk[0].day,
            walk[-1].day,
            len(walk),
            len(bars),
            weekly_src,
            n_w0,
            ma or "config",
        )
    )
    print(banner)
    if n_w0 < 60:
        print(
            "WARN weekly bars at start < 60 (need ~60 for w1, QMT uses 120); "
            "extend daily CSV or dump native 1w with HIST_START well before walk start"
        )

    ns = _exec_bundle()
    _patch_fast_ohlcv(ns)
    if ma:
        _apply_ma_type(ns, ma)
    install_config_overrides(ns, overrides)
    if quiet:
        _patch_quiet_status(ns)
    ledger = TradeLedger(code)
    wrap_fill_hooks(ns, ledger)
    log_f = open(log_path, "w", encoding="utf-8", newline="\n", buffering=1024 * 1024)
    log_f.write(banner + "\n")
    if n_w0 < 60:
        log_f.write(
            "WARN weekly bars at start < 60 (need ~60 for w1, QMT uses 120); "
            "extend daily CSV or dump native 1w with HIST_START well before walk start\n"
        )
    sink: TextIO = _QuietFile(log_f) if quiet else log_f
    old_out, old_err = sys.stdout, sys.stderr
    if quiet:
        sys.stdout = sink
        sys.stderr = sink
    else:
        sys.stdout = _Tee(old_out, sink)
        sys.stderr = _Tee(old_err, sink)
    try:
        ns["init"](ctx)
        apply_config_overrides(ns, overrides)
        for i, _bar in enumerate(walk):
            ctx.barpos = i
            ns["handlebar"](ctx)
    finally:
        try:
            sink.flush()
        except Exception:
            pass
        sys.stdout, sys.stderr = old_out, old_err
        log_f.close()
    trades_path = trades_csv_path(log_path)
    ledger.write(trades_path)
    print("wrote log", log_path, "bars", len(walk))
    print("wrote trades", trades_path, "n=", len(ledger.rows))
    return log_path


def backtest_one_result(
    csv_path: str | Path,
    start: str = "",
    end: str = "",
    out_dir: str | Path | None = None,
    quiet: bool = True,
    log_name: str = "",
    year: str = "",
    ma_type: str = "",
    dividend_type: str = "",
    store: MarketStore | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """单只回测 → 批量行（失败不抛给调用方）。"""
    from analyze import parse_budget_from_log  # noqa: WPS433

    path = Path(csv_path)
    dest = Path(out_dir) if out_dir else THEME / "report"
    dest.mkdir(parents=True, exist_ok=True)
    stock = path.stem
    year_s = str(year or "").strip()
    ma = normalize_ma_type(ma_type)
    div = str(dividend_type or "")
    row = _empty_row(path, stock, year=year_s, ma_type=ma, dividend_type=div, out_dir=str(dest))
    try:
        if store is None:
            store = get_market_store(path)
        code = store.stock
        stock = code
        row["stock"] = code
        walk = walk_days(store.bars, start=start, end=end)
        if not walk:
            row["error"] = "无行情交集 start=%s end=%s" % (start, end)
            return row
        row["walk_start"] = walk[0].day
        row["walk_end"] = walk[-1].day
        row["n_bars"] = len(walk)
        fname = str(log_name or "").strip()
        if not fname:
            fname = default_log_name(code, year=year_s, ma_type=ma)
        log_path = run_backtest(
            path,
            start=start,
            end=end,
            stock=code,
            out_dir=dest,
            log_name=fname,
            quiet=quiet,
            ma_type=ma,
            store=store,
            overrides=overrides,
        )
        detail = trades_csv_path(log_path)
        row["log"] = str(log_path)
        row["detail"] = str(detail)
        row["budget"] = parse_budget_from_log(log_path)
        row["ok"] = True
        row["ma_type"] = ma
        row["dividend_type"] = div
        row["out_dir"] = str(dest)
    except SystemExit as e:
        msg = str(e).strip()
        row["error"] = msg or ("exit %s" % e.code)
        row["stock"] = stock
        row["ma_type"] = ma
        row["dividend_type"] = div
    except Exception as e:
        row["error"] = "%s: %s" % (type(e).__name__, e)
        row["stock"] = stock
        row["ma_type"] = ma
        row["dividend_type"] = div
    return row


def resolve_workers(requested: int, n_tasks: int) -> int:
    n_tasks = max(0, int(n_tasks))
    if n_tasks <= 1:
        return 1
    cpu = os.cpu_count() or 2
    if requested is None or int(requested) <= 0:
        return max(1, min(n_tasks, int(cpu), 8))
    return max(1, min(int(requested), n_tasks))


def _job_label(payload: dict[str, Any], row: dict[str, Any] | None = None) -> str:
    stock = ""
    if row:
        stock = str(row.get("stock") or "")
    if not stock:
        stock = str(payload.get("stock") or "") or Path(str(payload.get("csv") or "")).stem
    year = str((row or {}).get("year") or payload.get("year") or "").strip()
    ma = normalize_ma_type((row or {}).get("ma_type") or payload.get("ma_type"))
    div = str((row or {}).get("dividend_type") or payload.get("dividend_type") or "").strip()
    bits = [stock]
    if div:
        bits.append(div)
    if year:
        bits.append(year)
    if ma:
        bits.append(ma)
    return " ".join(str(x) for x in bits if x)


def group_payloads_by_csv(payloads: list[dict[str, Any]]) -> list[list[int]]:
    """同一 csv 的任务下标分到一组（保序）。"""
    groups: dict[str, list[int]] = {}
    order: list[str] = []
    for i, p in enumerate(payloads):
        raw = str(p.get("csv") or "")
        if raw:
            try:
                key = str(Path(raw).resolve())
            except Exception:
                key = raw
        else:
            key = "__empty_%s" % i
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(i)
    return [groups[k] for k in order]


def _payload_out_dir(payload: dict[str, Any], dest: Path) -> Path:
    raw = payload.get("out_dir")
    if raw:
        return Path(str(raw))
    return dest


def _result_from_payload(
    payload: dict[str, Any],
    dest: Path,
    store: MarketStore | None = None,
) -> dict[str, Any]:
    return backtest_one_result(
        payload["csv"],
        start=str(payload.get("start") or ""),
        end=str(payload.get("end") or ""),
        out_dir=_payload_out_dir(payload, dest),
        quiet=bool(payload.get("quiet", True)),
        log_name=str(payload.get("log_name") or ""),
        year=str(payload.get("year") or ""),
        ma_type=str(payload.get("ma_type") or ""),
        dividend_type=str(payload.get("dividend_type") or ""),
        store=store,
        overrides=payload.get("overrides") or None,
    )


def _run_payloads(
    payloads: list[dict[str, Any]],
    dest: Path,
    on_progress: Callable[[int, int, str], None] | None,
    workers: int,
) -> list[dict[str, Any]]:
    n = len(payloads)
    if n == 0:
        return []
    groups = group_payloads_by_csv(payloads)
    n_workers = resolve_workers(workers, len(groups))

    def _blank(i: int) -> dict[str, Any]:
        p = payloads[i]
        return _empty_row(
            Path(str(p.get("csv") or "")),
            str(p.get("stock") or Path(str(p.get("csv") or "")).stem),
            year=str(p.get("year") or ""),
            ma_type=str(p.get("ma_type") or ""),
            dividend_type=str(p.get("dividend_type") or ""),
            out_dir=str(_payload_out_dir(p, dest)),
        )

    if n_workers <= 1:
        rows: list[dict[str, Any]] = [_blank(i) for i in range(n)]
        done = 0
        for idxs in groups:
            store = None
            csv0 = payloads[idxs[0]].get("csv")
            try:
                store = get_market_store(csv0, stock=str(payloads[idxs[0]].get("stock") or ""))
            except Exception:
                store = None
            for i in idxs:
                if on_progress:
                    on_progress(done, n, _job_label(payloads[i]))
                rows[i] = _result_from_payload(payloads[i], dest, store=store)
                done += 1
        if on_progress and payloads:
            last_i = groups[-1][-1] if groups else n - 1
            on_progress(n, n, _job_label(payloads[last_i], rows[last_i]))
        return rows

    from batch_job import init_worker, run_group

    rows = [_blank(i) for i in range(n)]
    if on_progress:
        on_progress(0, n, _job_label(payloads[0]))
    ctx = get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=n_workers,
        mp_context=ctx,
        initializer=init_worker,
        initargs=(str(HERE),),
    ) as pool:
        futs = {}
        for idxs in groups:
            chunk = [payloads[i] for i in idxs]
            futs[pool.submit(run_group, chunk)] = idxs
        done = 0
        for fut in as_completed(futs):
            idxs = futs[fut]
            try:
                got = fut.result()
            except Exception as e:
                got = []
                for i in idxs:
                    rows[i] = _blank(i)
                    rows[i]["error"] = "%s: %s" % (type(e).__name__, e)
                done += len(idxs)
                if on_progress:
                    on_progress(done, n, _job_label(payloads[idxs[-1]], rows[idxs[-1]]))
                continue
            for j, i in enumerate(idxs):
                if j < len(got) and isinstance(got[j], dict):
                    rows[i] = got[j]
                else:
                    rows[i] = _blank(i)
                    rows[i]["error"] = "empty group result"
            done += len(idxs)
            if on_progress:
                on_progress(done, n, _job_label(payloads[idxs[-1]], rows[idxs[-1]]))
    return rows


def _expand_ma_payloads(
    payloads: list[dict[str, Any]],
    *,
    ma_type: str = "",
    compare_ma: bool = False,
) -> list[dict[str, Any]]:
    kinds: list[str]
    if compare_ma:
        kinds = list(MA_TYPES)
    else:
        ma = normalize_ma_type(ma_type)
        kinds = [ma] if ma else [""]
    out: list[dict[str, Any]] = []
    for p in payloads:
        for k in kinds:
            q = dict(p)
            q["ma_type"] = k
            out.append(q)
    return out


def run_batch(
    csv_paths: Sequence[str | Path],
    start: str = "",
    end: str = "",
    out_dir: str | Path | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
    workers: int = 0,
    quiet: bool = True,
    split: str = "range",
    metas: Sequence[dict[str, Any]] | None = None,
    ma_type: str = "",
    compare_ma: bool = False,
    dividend_type: str = "",
) -> list[dict[str, Any]]:
    """独立回测多标的；单只失败不中断。workers<=0 为自动。split=year 时按自然年分段。"""
    dest = Path(out_dir) if out_dir else THEME / "report"
    dest.mkdir(parents=True, exist_ok=True)
    payloads = build_batch_payloads(
        csv_paths,
        start=start,
        end=end,
        out_dir=dest,
        quiet=quiet,
        split=split,
        metas=metas,
        ma_type=ma_type,
        compare_ma=compare_ma,
        dividend_type=dividend_type,
    )
    return _run_payloads(payloads, dest, on_progress, workers)


def build_batch_payloads(
    csv_paths: Sequence[str | Path],
    start: str = "",
    end: str = "",
    out_dir: str | Path | None = None,
    quiet: bool = True,
    split: str = "range",
    metas: Sequence[dict[str, Any]] | None = None,
    ma_type: str = "",
    compare_ma: bool = False,
    dividend_type: str = "",
) -> list[dict[str, Any]]:
    dest = Path(out_dir) if out_dir else THEME / "report"
    dest.mkdir(parents=True, exist_ok=True)
    paths = [Path(p) for p in csv_paths]
    mode = str(split or "range").strip().lower()
    if mode not in ("range", "year"):
        mode = "range"
    div = str(dividend_type or "")

    if mode == "year":
        from analyze import (  # noqa: WPS433
            build_year_jobs,
            compact_day,
            peek_daily_csv_meta,
            union_date_range,
        )

        meta_list: list[dict[str, Any]]
        if metas:
            meta_list = [dict(m) for m in metas]
        else:
            meta_list = []
            for p in paths:
                try:
                    meta_list.append(peek_daily_csv_meta(p))
                except Exception:
                    continue
        if not meta_list:
            return []
        start_s = compact_day(start)
        end_s = compact_day(end)
        if len(start_s) != 8 or len(end_s) != 8:
            start_s, end_s = union_date_range(meta_list)
        jobs = build_year_jobs(meta_list, start_s, end_s)
        payloads = [
            {
                "csv": j["csv"],
                "stock": j.get("stock") or "",
                "start": j["start"],
                "end": j["end"],
                "year": j["year"],
                "out_dir": str(dest),
                "quiet": bool(quiet),
                "log_name": "",
                "ma_type": "",
                "dividend_type": div,
            }
            for j in jobs
        ]
        return _expand_ma_payloads(payloads, ma_type=ma_type, compare_ma=compare_ma)

    payloads = [
        {
            "csv": str(p),
            "stock": p.stem,
            "start": start,
            "end": end,
            "year": "",
            "out_dir": str(dest),
            "quiet": bool(quiet),
            "log_name": "",
            "ma_type": "",
            "dividend_type": div,
        }
        for p in paths
    ]
    return _expand_ma_payloads(payloads, ma_type=ma_type, compare_ma=compare_ma)


def write_typed_summaries(
    rows: list[dict[str, Any]],
    *,
    split: str = "range",
    compare_ma: bool = False,
) -> list[Path]:
    """按 out_dir / 复权拆开写 batch summary 与对照 CSV。"""
    from analyze import (  # noqa: WPS433
        pair_ma_batch_rows,
        write_batch_summary_csv,
        write_batch_year_summary_csv,
        write_ma_compare_csv,
        write_ma_compare_year_csv,
    )

    by_dest: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for r in rows:
        dest = str(r.get("out_dir") or "")
        if not dest:
            log = str(r.get("log") or r.get("detail") or "")
            dest = str(Path(log).parent) if log else ""
        if dest not in by_dest:
            by_dest[dest] = []
            order.append(dest)
        by_dest[dest].append(r)
    written: list[Path] = []
    mode = str(split or "range").strip().lower()
    for dest in order:
        if not dest:
            continue
        chunk = by_dest[dest]
        out_dir = Path(dest)
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = write_batch_summary_csv(chunk, out_dir / "local_bt_batch_summary.csv")
        written.append(summary)
        if compare_ma:
            pairs = pair_ma_batch_rows(chunk)
            written.append(write_ma_compare_csv(pairs, out_dir / "local_bt_ma_compare.csv"))
            if mode == "year":
                written.append(
                    write_ma_compare_year_csv(pairs, out_dir / "local_bt_ma_compare_year.csv")
                )
        elif mode == "year":
            written.append(
                write_batch_year_summary_csv(chunk, out_dir / "local_bt_batch_year_summary.csv")
            )
    return written


def _run_report(log_path: Path, out_dir: Path) -> None:
    if not REPORT_PY.is_file():
        raise SystemExit("missing report script: %s" % REPORT_PY)
    report_dir = out_dir / "local_bt_report"
    terminal = trades_csv_path(log_path)
    argv = [
        str(REPORT_PY),
        "--theme",
        str(THEME),
        "--log",
        str(log_path),
        "--out-dir",
        str(report_dir),
        "--no-kline",
        "--title",
        "HlBand 本地回测",
    ]
    if terminal.is_file():
        argv.extend(["--terminal-csv", str(terminal)])
    else:
        argv.append("--no-terminal")
    sys.argv = argv
    runpy.run_path(str(REPORT_PY), run_name="__main__")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="HlBand local backtest from KlineDump daily CSV")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--csv", default="", help="KlineDump 日线 CSV（单标的）")
    src.add_argument(
        "--csv-dir",
        default="",
        help="批量：行情根目录或已解析的 <type> 子目录（*_1d_*.csv）",
    )
    ap.add_argument("--start", default="", help="回测起点 yyyymmdd（CSV 须含更早暖机）")
    ap.add_argument("--end", default="", help="回测终点 yyyymmdd")
    ap.add_argument("--stock", default="", help="覆盖 CSV 中的代码，如 600350.SH")
    ap.add_argument(
        "--out",
        default="",
        help="日志输出根目录（默认 hongli_band/report/<dividend-type>）",
    )
    ap.add_argument(
        "--dividend-type",
        default="front_ratio",
        metavar="TYPE",
        help="复权类型，逗号分隔 none|front|back|front_ratio|back_ratio（默认 front_ratio）",
    )
    ap.add_argument("--log-name", default="", help="日志文件名，默认 local_bt_{stock}.txt")
    ap.add_argument(
        "--weekly-csv",
        default="",
        help="QMT 原生 1w CSV；缺省则同目录 {code}_1w_*.csv，再缺省则日线合成并丢掉未收盘周",
    )
    ap.add_argument("--report", action="store_true", help="事后用 gen_report；成交真源为本回测操作明细")
    ap.add_argument("--verbose", action="store_true", help="刷屏写 log（默认安静：过滤状态行，不 tee 控制台）")
    ap.add_argument(
        "--workers",
        type=int,
        default=0,
        help="批量进程数；0=min(任务数, CPU, 8)；1=串行",
    )
    ap.add_argument(
        "--split",
        choices=("range", "year"),
        default="range",
        help="批量切分：range=整段区间；year=按自然年分段独立回测",
    )
    ap.add_argument(
        "--ma-type",
        default="",
        metavar="SMA|EMA",
        help="强制价格均线 SMA/EMA（盖过 BOOK_STOCKS）；缺省用 config",
    )
    ap.add_argument(
        "--compare-ma",
        action="store_true",
        help="同一任务各跑 SMA 与 EMA，写 local_bt_ma_compare.csv",
    )
    args = ap.parse_args(argv)
    from analyze import (  # noqa: WPS433
        DEFAULT_CSV_ROOT,
        DEFAULT_DIVIDEND_TYPE,
        DEFAULT_REPORT_ROOT,
        daily_csv_for_stock,
        daily_csvs_by_stock,
        pair_ma_batch_rows,
        parse_budget_from_log,
        parse_dividend_types,
        resolve_typed_dir,
        summarize_batch_row,
        typed_dir_root,
        write_ma_compare_csv,
    )

    quiet = not bool(args.verbose)
    raw_ma = str(args.ma_type or "").strip()
    ma_type = normalize_ma_type(raw_ma)
    if raw_ma and not ma_type:
        raise SystemExit("--ma-type must be SMA or EMA")
    compare_ma = bool(args.compare_ma)
    div_raw = str(args.dividend_type or "").strip()
    divs = parse_dividend_types(div_raw)
    if div_raw:
        tokens = [t for t in div_raw.replace(",", " ").split() if t]
        if tokens and not divs:
            raise SystemExit("--dividend-type must be none|front|back|front_ratio|back_ratio")
    if not divs:
        divs = [DEFAULT_DIVIDEND_TYPE]
    csv_root = args.csv_dir or DEFAULT_CSV_ROOT
    out_root = args.out or DEFAULT_REPORT_ROOT

    if args.csv_dir:
        all_payloads: list[dict[str, Any]] = []
        for div in divs:
            csv_dir = str(resolve_typed_dir(csv_root, div))
            out_dir = str(resolve_typed_dir(out_root, div))
            metas = daily_csvs_by_stock(csv_dir)
            paths = [Path(m["path"]) for m in metas]
            if not paths:
                print("skip empty *_1d_*.csv in %s" % csv_dir, flush=True)
                continue
            all_payloads.extend(
                build_batch_payloads(
                    paths,
                    start=args.start,
                    end=args.end,
                    out_dir=out_dir,
                    quiet=quiet,
                    split=args.split,
                    metas=metas,
                    ma_type=ma_type,
                    compare_ma=compare_ma,
                    dividend_type=div,
                )
            )
        if not all_payloads:
            raise SystemExit("no *_1d_*.csv for dividend types %s" % ",".join(divs))

        def _prog(i: int, n: int, stock: str) -> None:
            print("batch [%s/%s] %s" % (min(i + 1, n), n, stock), flush=True)

        raw = _run_payloads(all_payloads, Path(out_root), _prog, args.workers)
        rows = [summarize_batch_row(r) for r in raw]
        for p in write_typed_summaries(rows, split=args.split, compare_ma=compare_ma):
            print("wrote", p)
        for r in rows:
            print(
                r.get("dividend_type") or "",
                r.get("stock"),
                r.get("year") or "",
                r.get("ma_type") or "",
                r.get("status"),
                "pnl=",
                r.get("sum_pnl"),
                r.get("error") or "",
            )
        return

    stock = str(args.stock or "").strip().upper()
    csv_file = Path(args.csv)
    if not stock and csv_file.is_file():
        try:
            stock = str(peek_daily_csv_meta(csv_file).get("stock") or "").strip().upper()
        except Exception:
            stock = ""
    src_root = typed_dir_root(csv_file.parent) if csv_file.parent else DEFAULT_CSV_ROOT

    def _single_csv_for(div: str) -> Path | None:
        if len(divs) == 1:
            return csv_file if csv_file.is_file() else None
        found = daily_csv_for_stock(resolve_typed_dir(src_root, div), stock)
        return found if found and found.is_file() else None

    last_log = None
    last_out = None
    for div in divs:
        csv_one = _single_csv_for(div)
        if csv_one is None:
            print("skip missing csv div=", div, "stock=", stock, flush=True)
            continue
        out_dir = str(resolve_typed_dir(out_root, div))
        if compare_ma:
            rows = []
            store = get_market_store(csv_one, stock=stock or args.stock, weekly_csv=args.weekly_csv or None)
            for kind in MA_TYPES:
                log_path = run_backtest(
                    csv_one,
                    start=args.start,
                    end=args.end,
                    stock=stock or args.stock,
                    out_dir=out_dir,
                    log_name="",
                    weekly_csv=args.weekly_csv or None,
                    quiet=quiet,
                    ma_type=kind,
                    store=store,
                )
                last_log = log_path
                last_out = out_dir
                row = {
                    "stock": stock or Path(csv_one).stem,
                    "year": "",
                    "ma_type": kind,
                    "ok": True,
                    "log": str(log_path),
                    "detail": str(trades_csv_path(log_path)),
                    "csv": str(csv_one),
                    "dividend_type": div,
                    "out_dir": out_dir,
                }
                row["budget"] = parse_budget_from_log(log_path)
                rows.append(summarize_batch_row(row))
            pairs = pair_ma_batch_rows(rows)
            cmp_path = write_ma_compare_csv(pairs, Path(out_dir) / "local_bt_ma_compare.csv")
            print("wrote ma compare", cmp_path)
        else:
            last_log = run_backtest(
                csv_one,
                start=args.start,
                end=args.end,
                stock=stock or args.stock,
                out_dir=out_dir,
                log_name=args.log_name if len(divs) == 1 else "",
                weekly_csv=args.weekly_csv or None,
                quiet=quiet,
                ma_type=ma_type,
            )
            last_out = out_dir
    if args.report and last_log and last_out:
        _run_report(Path(last_log), Path(last_out))


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()
    main()
