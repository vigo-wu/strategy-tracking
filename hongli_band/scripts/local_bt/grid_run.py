# coding: utf-8
"""真实 local_bt 命名网格：跟踪池 BOOK_STOCKS、隔离目录、一层全局 walk 池。

用法（仓库根目录）::

  python hongli_band/scripts/local_bt/grid_run.py --spec .cursor/skills/qmt-local-bt-grid/examples/stop_loss.json
  python hongli_band/scripts/local_bt/grid_run.py --spec path/to/cells.json --include-sma-ema
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, as_completed, wait
from multiprocessing import get_context
from pathlib import Path
from queue import Empty, Full
from typing import Any, Callable, Iterable, Mapping

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
THEME = REPO / "hongli_band"
HLBAND_CONFIG = THEME / "scripts" / "qmt" / "hlband" / "config.py"
GRID_ROOT = THEME / "report" / "grid"
SKILL_SCRIPTS = REPO / ".cursor" / "skills" / "qmt-local-bt-grid" / "scripts"
SKILL_SUMMARIZE = SKILL_SCRIPTS / "summarize.py"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

from analyze import (  # noqa: E402
    DEFAULT_CSV_ROOT,
    DEFAULT_DIVIDEND_TYPE,
    csv_source_dividend_type,
    daily_csvs_by_stock,
    normalize_dividend_type,
    normalize_ma_type,
    resolve_typed_dir,
)
from grid_spec import (  # noqa: E402
    YEAR_WINDOW_KEYS,
    GridSpecError,
    apply_year_windows,
    deep_merge_factor_params,
    fill_year_windows,
    flatten_factor_params,
    json_ready,
    nest_factor_path,
    overrides_has_trail_tiers,
    recipe_fingerprint,
    reject_retired_min_ret,
    struct_eq,
)
from grid_progress import (  # noqa: E402
    STATUS_DIRTY,
    STATUS_DONE,
    STATUS_RUNNING,
    GridPaused,
    build_progress,
    cell_ids_of,
    check_pause,
    chunk_ids,
    clear_pause,
    delete_cell_dirs,
    done_cell_ids,
    infer_existing_batch_status,
    iter_batches,
    load_progress,
    mark_running_dead_as_dirty,
    order_cells_current_first,
    pause_requested,
    save_progress,
    set_batch_status,
    worker_is_alive,
)
from grid_gate import fill_gate, gate_for_json, validate_gate  # noqa: E402
from asset_split import (  # noqa: E402
    AssetSplitError,
    draw_asset_split,
    fill_asset_split,
    stock_lock_rows,
    validate_asset_split,
)
from market_csv import compact_day, peek_daily_csv_meta  # noqa: E402
from book_backtest import book_log_name, book_stocks_hash, run_book_backtest  # noqa: E402
from run import clear_market_store_cache, run_init_probe  # noqa: E402
from trades_csv import trades_csv_path  # noqa: E402

WARN_CELL_SOFT = 8
WARN_JOBS_SOFT = 12
WALK_PROGRESS_QUEUE_MAX = 256
RE_STOP = re.compile(r"\bstop=\s*([0-9.eE+-]+)")
RE_TFB = re.compile(r"\btime_force_bars=\s*(-?\d+)")
RE_TFM = re.compile(r"\btime_force_min_ret=\s*([0-9.eE+-]+)")
RE_ARM = re.compile(r"\btrail_arm=\s*([0-9.eE+-]+|None)")
RE_RECIPE = re.compile(r"recipe=\s*([0-9a-fA-F]+)")

_CSV_INDEX: dict[tuple[str, str], Path] = {}
_CSV_SPAN: dict[str, tuple[str, str] | None] = {}
_WALK_PROGRESS_Q: Any = None


class GridError(Exception):
    """网格 spec / 运行错误（CLI 转成 exit）。"""


def resolve_pool_workers(requested: int, n_walks: int) -> int:
    """全局 walk 池大小。自动 min(walk 数, CPU)；手动只夹 walk 数，不夹 16。"""
    n_walks = max(0, int(n_walks))
    if n_walks <= 1:
        return 1
    cpu = os.cpu_count() or 2
    req = int(requested or 0)
    if req <= 0:
        return max(1, min(n_walks, int(cpu)))
    if req == 1:
        return 1
    return max(1, min(req, n_walks))


def _emit_progress(
    on_progress: Callable[..., None] | None,
    cid: str,
    done: int,
    tot: int,
    label: str,
    **extra: Any,
) -> None:
    if on_progress is not None:
        on_progress(str(cid), int(done), int(tot), str(label), **extra)
        return
    n_walks = extra.get("n_walks")
    if n_walks:
        completed = extra.get("completed", done)
        inflight = extra.get("inflight_frac") or 0.0
        n_running = extra.get("n_running") or 0
        jk = extra.get("job_key") or cid
        phase = extra.get("phase") or "walk"
        if phase == "probe":
            print(
                "[%s] 探针 %s/%s %s"
                % (cid, extra.get("probe_done", done), extra.get("probe_total", tot), label),
                flush=True,
            )
            return
        print(
            "[%s] %.1f/%s walk · %s 路 %s"
            % (jk, float(completed) + float(inflight), n_walks, n_running, label),
            flush=True,
        )
        return
    print("[%s] %s/%s %s" % (cid, done, tot, label), flush=True)


def walk_job_key(payload: dict[str, Any] | None, *, cid: str = "", sample: str = "", basket: str = "") -> str:
    p = payload or {}
    return "%s|%s|%s" % (
        str(p.get("cell_id") or cid or ""),
        str(p.get("sample") or sample or "book"),
        str(p.get("basket_id") or p.get("basket") or basket or "book"),
    )


class WalkProgress:
    """全局 walk 进度：completed + sum(inflight bar 分数)。"""

    def __init__(self, n_walks: int):
        self.n_walks = max(int(n_walks or 0), 0)
        self.completed = 0
        self.inflight: dict[str, float] = {}
        self._finished: set[str] = set()
        self.probe_done = 0
        self.probe_total = 0
        self.cells_done = 0

    @property
    def inflight_frac(self) -> float:
        return float(sum(self.inflight.values()))

    @property
    def n_running(self) -> int:
        return len(self.inflight)

    def frac(self) -> float:
        denom = max(self.n_walks, 1)
        return min(1.0, (float(self.completed) + self.inflight_frac) / float(denom))

    def start(self, job_key: str) -> None:
        jk = str(job_key or "")
        if not jk or jk in self._finished:
            return
        self.inflight.setdefault(jk, 0.0)

    def bar(self, job_key: str, done: int, total: int) -> None:
        jk = str(job_key or "")
        if not jk or jk in self._finished:
            return
        tot = float(total or 0)
        if tot <= 0:
            self.inflight.setdefault(jk, 0.0)
            return
        self.inflight[jk] = min(1.0, float(done or 0) / tot)

    def finish(self, job_key: str) -> None:
        jk = str(job_key or "")
        self.inflight.pop(jk, None)
        if jk:
            if jk in self._finished:
                return
            self._finished.add(jk)
        self.completed += 1

    def drop(self, job_key: str) -> None:
        jk = str(job_key or "")
        self.inflight.pop(jk, None)
        if jk:
            self._finished.add(jk)

    def extras(self, *, phase: str = "walk", job_key: str = "") -> dict[str, Any]:
        out: dict[str, Any] = {
            "completed": int(self.completed),
            "n_walks": int(self.n_walks),
            "inflight_frac": float(self.inflight_frac),
            "n_running": int(self.n_running),
            "cells_done": int(self.cells_done),
            "phase": str(phase or "walk"),
            "job_key": str(job_key or ""),
        }
        if phase == "probe":
            out["probe_done"] = int(self.probe_done)
            out["probe_total"] = int(self.probe_total)
        return out


def _emit_walk_progress(
    on_progress: Callable[..., None] | None,
    state: WalkProgress,
    cid: str,
    label: str,
    *,
    phase: str = "walk",
    job_key: str = "",
) -> None:
    extra = state.extras(phase=phase, job_key=job_key)
    if phase == "probe":
        done, tot = state.probe_done, max(state.probe_total, 1)
    else:
        done, tot = state.completed, max(state.n_walks, 1)
    _emit_progress(on_progress, cid, done, tot, label, **extra)


def _json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_ready(x) for x in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def pickle_safe(overrides: dict[str, Any] | None) -> dict[str, Any]:
    if not overrides:
        return {}
    return json.loads(json.dumps(_json_ready(overrides)))


def load_spec(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    suf = p.suffix.lower()
    if suf in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise GridError("YAML spec 需要 PyYAML，请改用 JSON") from e
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise GridError("spec 必须是对象")
    try:
        reject_retired_min_ret(data)
    except GridSpecError as e:
        raise GridError(str(e)) from e
    return data


def validate_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        reject_retired_min_ret(spec)
    except GridSpecError as e:
        raise GridError(str(e)) from e
    cells = list(spec.get("cells") or [])
    if not cells:
        raise GridError("spec.cells 为空")
    if len(cells) > WARN_CELL_SOFT:
        print(
            "WARN 格子数 %s > %s；叉乘交互项多，仅提示仍继续跑（技能建议选参 ≤8 格）"
            % (len(cells), WARN_CELL_SOFT),
            flush=True,
        )
    ids: list[str] = []
    out: list[dict[str, Any]] = []
    for raw in cells:
        if not isinstance(raw, dict):
            raise GridError("每个 cell 必须是对象")
        cid = str(raw.get("id") or "").strip()
        if not cid:
            raise GridError("cell 缺少 id")
        if cid in ids:
            raise GridError("重复 cell id: %s" % cid)
        ids.append(cid)
        kind = str(raw.get("kind") or ("base" if cid == "base" else "other")).strip().lower()
        if cid == "base":
            kind = "base"
        overrides = raw.get("overrides") or {}
        if not isinstance(overrides, dict):
            raise GridError("%s.overrides 必须是对象" % cid)
        rec = {
            "id": cid,
            "label": str(raw.get("label") or cid),
            "kind": kind,
            "overrides": pickle_safe(overrides),
            "is_current": bool(raw.get("is_current")) or cid == "base",
        }
        if raw.get("n_diffs") is not None:
            try:
                rec["n_diffs"] = int(raw.get("n_diffs"))
            except (TypeError, ValueError):
                pass
        out.append(rec)
    try:
        apply_year_windows(spec)
    except GridSpecError as e:
        raise GridError(str(e)) from e
    try:
        split = fill_asset_split(spec)
        if split["mode"] != "off":
            validate_asset_split(split)
        spec["asset_split"] = split
    except AssetSplitError as e:
        raise GridError(str(e)) from e
    return out


def _load_hlband_config():
    spec = importlib.util.spec_from_file_location("hlband_config_grid", HLBAND_CONFIG)
    if spec is None or spec.loader is None:
        raise GridError("无法读取 %s" % HLBAND_CONFIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_config_defaults() -> dict[str, Any]:
    from grid_spec import param_catalog

    mod = _load_hlband_config()
    rec = getattr(mod, "RECIPE", None) or {}
    flat = flatten_factor_params(rec.get("factor_params") or {})
    out: dict[str, Any] = {}
    seen: set[str] = set()
    for spec in param_catalog():
        if spec.key in seen:
            continue
        seen.add(spec.key)
        if spec.key in flat:
            out[spec.key] = flat[spec.key]
        elif hasattr(mod, spec.key):
            out[spec.key] = getattr(mod, spec.key)
    return out


def load_exit_defaults() -> dict[str, Any]:
    return load_config_defaults()


def book_stock_entries(raw: Any) -> list[tuple[Any, Any]]:
    """BOOK_STOCKS → [(key, value), ...]。兼容 dict / set / frozenset / list / tuple。"""
    if isinstance(raw, dict):
        return list(raw.items())
    if raw is None or isinstance(raw, (str, bytes)):
        return []
    try:
        seq = list(raw)
    except TypeError:
        return []
    out: list[tuple[Any, Any]] = []
    for x in seq:
        if isinstance(x, (list, tuple)) and len(x) >= 1:
            out.append((x[0], x[1] if len(x) >= 2 else {}))
        else:
            out.append((x, {}))
    return out


def load_book_lock() -> list[tuple[str, str, str]]:
    """config.BOOK_STOCKS → [(stock, ma_type, dividend_type), ...]。"""
    mod = _load_hlband_config()
    raw = getattr(mod, "BOOK_STOCKS", None)
    default_ma = normalize_ma_type(getattr(mod, "MA_TYPE", "EMA")) or "EMA"
    default_div = (
        normalize_dividend_type(getattr(mod, "DIVIDEND_TYPE", "")) or DEFAULT_DIVIDEND_TYPE
    )
    items = book_stock_entries(raw)
    if raw is None or (
        not items and not isinstance(raw, (dict, list, tuple, set, frozenset))
    ):
        raise GridError("config.BOOK_STOCKS 为空或无法解析")
    out: list[tuple[str, str, str]] = []
    for k, v in items:
        stock = str(k or "").strip().upper()
        if not stock:
            continue
        if isinstance(v, dict):
            ma = normalize_ma_type(v.get("ma_type")) or default_ma
            div = normalize_dividend_type(v.get("dividend_type")) or default_div
        elif isinstance(v, str):
            ma = normalize_ma_type(v) or default_ma
            div = default_div
        else:
            ma, div = default_ma, default_div
        out.append((stock, ma, div))
    if not out:
        raise GridError("config.BOOK_STOCKS 没有有效标的")
    return out


def _fp_table_from_defaults(defaults: Mapping[str, Any] | None) -> dict[str, Any]:
    table: dict[str, Any] = {}
    for key, val in dict(defaults or {}).items():
        ks = str(key)
        if "." not in ks:
            continue
        table = deep_merge_factor_params(table, nest_factor_path(ks, val))
    return table


def expected_fingerprint(
    defaults: dict[str, Any],
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    ov = overrides or {}
    incoming = ov.get("factor_params") if isinstance(ov.get("factor_params"), dict) else {}
    fp = deep_merge_factor_params(_fp_table_from_defaults(defaults), incoming)
    stop = float((fp.get("stop_loss") or {}).get("pct"))
    time_force_bars = int((fp.get("time_force") or {}).get("bars"))
    arm = None
    try:
        arm = float(fp["trail_stop"]["tiers"][0][0])
    except (IndexError, TypeError, ValueError, KeyError):
        arm = None
    out = {
        "stop": stop,
        "time_force_bars": time_force_bars,
        "time_force_min_ret": float(arm) if arm is not None else 0.0,
        "trail_arm": arm,
    }
    if overrides_has_trail_tiers(ov):
        out["trail_tiers"] = json_ready((fp.get("trail_stop") or {}).get("tiers"))
    out["recipe"] = recipe_fingerprint(overrides=ov)
    return out


def _extract_tagged_json(text: str, tag: str) -> tuple[Any, bool]:
    marker = tag if str(tag).endswith("=") else "%s=" % tag
    i = text.find(marker)
    if i < 0:
        return None, False
    rest = text[i + len(marker) :].lstrip()
    if not rest:
        return None, True
    try:
        obj, _end = json.JSONDecoder().raw_decode(rest)
    except json.JSONDecodeError:
        return None, True
    return obj, True


def parse_fingerprint(text: str) -> dict[str, Any]:
    stop_m = RE_STOP.search(text)
    tfb_m = RE_TFB.search(text)
    tfm_m = RE_TFM.search(text)
    arm_m = RE_ARM.search(text)
    arm: float | None
    if arm_m is None:
        arm = None
    elif arm_m.group(1) in ("None", "none"):
        arm = None
    else:
        arm = float(arm_m.group(1))
    tiers, has_tiers = _extract_tagged_json(text, "trail_tiers=")
    rec_hits = RE_RECIPE.findall(text)
    recipe = rec_hits[-1] if rec_hits else None
    return {
        "stop": None if stop_m is None else float(stop_m.group(1)),
        "time_force_bars": None if tfb_m is None else int(tfb_m.group(1)),
        "time_force_min_ret": None if tfm_m is None else float(tfm_m.group(1)),
        "trail_arm": arm,
        "trail_tiers": tiers,
        "recipe": recipe,
        "has_recipe": bool(rec_hits),
        "has_trail_arm": arm_m is not None,
        "has_trail_tiers": has_tiers,
        "has_stop": stop_m is not None,
        "has_tfb": tfb_m is not None,
    }


def _num_eq(a: Any, b: Any, eps: float = 1e-9) -> bool:
    if a is None and b is None:
        return True
    try:
        return abs(float(a) - float(b)) <= eps
    except (TypeError, ValueError):
        return False


def assert_fingerprint_text(
    text: str,
    expected: dict[str, Any],
    *,
    need_trail: bool,
    source: str = "",
) -> None:
    label = source or "probe"
    got = parse_fingerprint(text)
    if not got["has_stop"] or not _num_eq(got["stop"], expected["stop"]):
        raise GridError(
            "指纹 stop 不符 log=%s got=%s expected=%s" % (label, got["stop"], expected["stop"])
        )
    if not got["has_tfb"] or got["time_force_bars"] != expected["time_force_bars"]:
        raise GridError(
            "指纹 time_force_bars 不符 log=%s got=%s expected=%s"
            % (label, got["time_force_bars"], expected["time_force_bars"])
        )
    if got["time_force_min_ret"] is not None and not _num_eq(
        got["time_force_min_ret"], expected["time_force_min_ret"]
    ):
        raise GridError(
            "指纹 time_force_min_ret 不符 log=%s got=%s expected=%s"
            % (label, got["time_force_min_ret"], expected["time_force_min_ret"])
        )
    if need_trail:
        if not got["has_trail_arm"] or not _num_eq(got["trail_arm"], expected["trail_arm"]):
            raise GridError(
                "指纹 trail_arm 不符 log=%s got=%s expected=%s"
                % (label, got.get("trail_arm"), expected["trail_arm"])
            )
        if not got.get("has_trail_tiers") or not struct_eq(
            got.get("trail_tiers"), expected.get("trail_tiers")
        ):
            raise GridError(
                "指纹 trail_tiers 不符 log=%s got=%s expected=%s"
                % (label, got.get("trail_tiers"), expected.get("trail_tiers"))
            )
    if expected.get("recipe") and got.get("has_recipe"):
        if got.get("recipe") != expected.get("recipe"):
            raise GridError(
                "指纹 recipe 不符 log=%s got=%s expected=%s"
                % (label, got.get("recipe"), expected.get("recipe"))
            )


def assert_fingerprint(
    log_path: Path,
    expected: dict[str, Any],
    *,
    need_trail: bool,
) -> None:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    assert_fingerprint_text(text, expected, need_trail=need_trail, source=str(log_path))


def csv_for(stock: str, div: str) -> Path | None:
    key = (str(div), str(stock).upper())
    if key in _CSV_INDEX:
        p = _CSV_INDEX[key]
        return p if p.is_file() else None
    root = resolve_typed_dir(DEFAULT_CSV_ROOT, csv_source_dividend_type(div))
    for meta in daily_csvs_by_stock(root):
        code = str(meta.get("stock") or "").strip().upper()
        path = Path(str(meta.get("path") or ""))
        if code and path.is_file():
            _CSV_INDEX[(str(div), code)] = path
            ms = compact_day(str(meta.get("start") or ""))
            me = compact_day(str(meta.get("end") or ""))
            if len(ms) == 8 and len(me) == 8:
                _CSV_SPAN[str(path)] = (ms, me)
    hit = _CSV_INDEX.get(key)
    return hit if hit is not None and hit.is_file() else None


def _csv_span(path: Path) -> tuple[str, str] | None:
    key = str(path)
    if key in _CSV_SPAN:
        return _CSV_SPAN[key]
    try:
        meta = peek_daily_csv_meta(path)
        ms = compact_day(str(meta.get("start") or ""))
        me = compact_day(str(meta.get("end") or ""))
        span = (ms, me) if len(ms) == 8 and len(me) == 8 else None
    except Exception:
        span = None
    _CSV_SPAN[key] = span
    return span


def _year_overlaps_csv(csv_p: Path, start: str, end: str) -> bool:
    span = _csv_span(csv_p)
    if span is None:
        return False
    return max(str(start), span[0]) <= min(str(end), span[1])


def _walk_span(spec: dict[str, Any] | None = None) -> tuple[str, str]:
    win = fill_year_windows(spec)
    return "%s0101" % int(win["year_start"]), "%s1231" % int(win["year_end"])


def _locks_to_book(
    locks: list[tuple[str, str, str]],
    start: str,
    end: str,
    *,
    ma_force: str | None = None,
) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for stock, ma, div in locks:
        csv_p = csv_for(stock, div)
        if csv_p is None:
            print("skip book 无 CSV", stock, div, flush=True)
            continue
        if not _year_overlaps_csv(csv_p, start, end):
            print("skip book 无行情", stock, start, end, flush=True)
            continue
        out[stock] = {
            "ma_type": str(ma_force or ma),
            "dividend_type": str(div),
        }
    return out


def _walk_job(
    *,
    sample: str,
    basket: str,
    book_stocks: dict[str, dict[str, str]],
    start: str,
    end: str,
    div: str,
    ma: str,
) -> dict[str, Any]:
    return {
        "sample": sample,
        "basket": basket,
        "book_stocks": book_stocks,
        "start": start,
        "end": end,
        "div": div,
        "ma": ma,
        "n_stocks": len(book_stocks),
        "stocks": sorted(book_stocks.keys()),
    }


def book_jobs(spec: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    start, end = _walk_span(spec)
    split = fill_asset_split(spec)
    compare_div = str((spec or {}).get("compare_div") or "front_ratio")
    if split["mode"] == "random_from_csv":
        locks = stock_lock_rows(split)
        if not locks:
            raise GridError("asset_split 名单为空，请先抽取 tune/holdout")
        tune_set = {str(s).strip().upper() for s in (split.get("tune_stocks") or [])}
        hold_set = {str(s).strip().upper() for s in (split.get("holdout_stocks") or [])}
        tune_locks = [row for row in locks if row[0] in tune_set]
        hold_locks = [row for row in locks if row[0] in hold_set]
        out: list[dict[str, Any]] = []
        tune_book = _locks_to_book(tune_locks, start, end)
        if not tune_book:
            raise GridError("调参篮子无可用 CSV")
        ma0 = str((split.get("ma_type") or "EMA")).upper()
        out.append(
            _walk_job(
                sample="book",
                basket="tune",
                book_stocks=tune_book,
                start=start,
                end=end,
                div=compare_div,
                ma=ma0,
            )
        )
        hold_book = _locks_to_book(hold_locks, start, end)
        if not hold_book:
            raise GridError("盲测篮子无可用 CSV")
        out.append(
            _walk_job(
                sample="book",
                basket="holdout",
                book_stocks=hold_book,
                start=start,
                end=end,
                div=compare_div,
                ma=ma0,
            )
        )
        return out
    locks = load_book_lock()
    book = _locks_to_book(locks, start, end)
    if not book:
        raise GridError("跟踪池无可用 CSV")
    mas = {str(cfg.get("ma_type") or "EMA").upper() for cfg in book.values()}
    ma = mas.pop() if len(mas) == 1 else "MIX"
    return [
        _walk_job(
            sample="book",
            basket="book",
            book_stocks=book,
            start=start,
            end=end,
            div=compare_div,
            ma=ma,
        )
    ]


def ma_control_jobs(src_jobs: list[dict[str, Any]], ma: str) -> list[dict[str, Any]]:
    kind = str(ma).upper()
    out: list[dict[str, Any]] = []
    for j in src_jobs:
        q = dict(j)
        q["sample"] = kind.lower()
        q["ma"] = kind
        forced: dict[str, dict[str, str]] = {}
        for stock, cfg in (j.get("book_stocks") or {}).items():
            row = dict(cfg)
            row["ma_type"] = kind
            forced[str(stock)] = row
        q["book_stocks"] = forced
        q["n_stocks"] = len(forced)
        q["stocks"] = sorted(forced.keys())
        out.append(q)
    return out


def _assert_grid_dir(path: Path) -> None:
    parts = [str(x).lower() for x in path.parts]
    if "grid" not in parts:
        raise GridError("禁止把网格 log 写到非 report/grid 目录: %s" % path)
    if "front_ratio" in parts and "grid" in parts:
        idx_g = parts.index("grid")
        # report/grid/.../front_ratio 作为 sample 下的复权子目录允许
        if idx_g > parts.index("front_ratio"):
            raise GridError("禁止覆盖基线 report/front_ratio: %s" % path)


_CELL_SAMPLE_DIRS = ("book", "sma", "ema")


def is_cell_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    if (path / "cell_meta.json").is_file():
        return True
    return any((path / name).is_dir() for name in _CELL_SAMPLE_DIRS)


def prune_stale_cell_dirs(dest: Path, keep_ids: Iterable[str]) -> list[str]:
    """全量重跑时删掉不在当前 spec 里的旧格子目录，避免 summarize 扫进残留 id。"""
    keep = {str(x).strip() for x in keep_ids if str(x).strip()}
    removed: list[str] = []
    if not dest.is_dir():
        return removed
    for child in dest.iterdir():
        if not is_cell_dir(child) or child.name in keep:
            continue
        shutil.rmtree(child)
        removed.append(child.name)
    return removed


def reset_cell_sample_dirs(cell_dir: str | Path) -> None:
    """全量重跑一格时清掉 book/sma/ema，避免旧 stock×年 log 混进组合汇总。"""
    root = Path(cell_dir)
    for name in _CELL_SAMPLE_DIRS:
        dest = root / name
        if dest.is_dir():
            shutil.rmtree(dest)


def grid_book_overrides(
    cell_overrides: dict[str, Any] | None,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = pickle_safe(cell_overrides)
    tb = out.get("TRADE_BUDGET")
    if tb is None and defaults:
        tb = defaults.get("TRADE_BUDGET")
    try:
        tb_f = float(tb or 100000.0)
    except (TypeError, ValueError):
        tb_f = 100000.0
    if tb_f <= 0:
        tb_f = 100000.0
    out["TRADE_BUDGET"] = tb_f
    out["compound_backtest"] = True
    out["wallet_cash"] = tb_f
    return out


def job_payload(
    job: dict[str, Any],
    cell_dir: Path,
    overrides: dict[str, Any],
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sample = str(job.get("sample") or "book")
    div = str(job.get("div") or "front_ratio")
    basket = str(job.get("basket") or "book")
    dest = cell_dir / sample / div
    if basket in ("tune", "holdout"):
        dest = dest / basket
    dest.mkdir(parents=True, exist_ok=True)
    _assert_grid_dir(dest)
    book = job.get("book_stocks") or {}
    htag = book_stocks_hash(book)
    start = str(job["start"])
    end = str(job["end"])
    log_name = book_log_name(kind="fixed", year=start, tag=htag, end=end)
    if basket in ("tune", "holdout"):
        log_name = "%s_%s" % (basket, log_name)
    return {
        "basket_id": basket,
        "book_stocks": pickle_safe(book),
        "start": start,
        "end": end,
        "out_dir": str(dest),
        "csv_root": str(DEFAULT_CSV_ROOT),
        "log_name": log_name,
        "overrides": grid_book_overrides(overrides, defaults),
        "sample": sample,
        "div": div,
    }


def run_one_book_walk(
    payload: dict[str, Any],
    on_bar_progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """子进程入口：一段组合连续回放。"""
    basket_id = str(payload.get("basket_id") or "book")
    out_dir = Path(payload["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    log_name = str(payload.get("log_name") or "")
    try:
        try:
            lp, meta = run_book_backtest(
                payload.get("book_stocks") or {},
                str(payload["start"]),
                str(payload["end"]),
                payload.get("csv_root") or DEFAULT_CSV_ROOT,
                out_dir,
                log_name=log_name,
                quiet=True,
                overrides=payload.get("overrides") or {},
                on_progress=on_bar_progress,
            )
            return {
                "ok": True,
                "basket_id": basket_id,
                "log_path": str(lp),
                "trades_path": str(trades_csv_path(lp)),
                "meta": meta,
                "sample": payload.get("sample"),
            }
        except Exception as e:
            return {
                "ok": False,
                "basket_id": basket_id,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "sample": payload.get("sample"),
            }
    finally:
        clear_market_store_cache()


def init_walk_pool(local_bt_dir: str = "", progress_queue: Any = None) -> None:
    """spawn 子进程：补 sys.path，Queue 只能走 initializer 继承。"""
    from batch_job import init_worker

    init_worker(str(local_bt_dir or HERE))
    global _WALK_PROGRESS_Q
    _WALK_PROGRESS_Q = progress_queue


def _queue_put(
    kind: str,
    cid: str,
    job_key: str,
    walk_done: int,
    walk_total: int,
    label: str,
) -> None:
    q = _WALK_PROGRESS_Q
    if q is None:
        return
    try:
        q.put_nowait(
            (str(kind), str(cid), str(job_key), int(walk_done or 0), int(walk_total or 0), str(label))
        )
    except Full:
        pass
    except Exception:
        pass


def run_walk_job(payload: dict[str, Any]) -> dict[str, Any]:
    """模块级 walk 入口（Windows spawn 可 pickle）。payload 禁止带 progress_queue。"""
    cid = str(payload.get("cell_id") or "")
    job_key = walk_job_key(payload)
    label = str(payload.get("basket_id") or payload.get("sample") or "book")
    _queue_put("start", cid, job_key, 0, 0, label)
    if not payload.get("out_dir"):
        return {"ok": False, "cell_id": cid, "error": "无 job", "basket_id": label, "job_key": job_key}

    def _on_bar(done_bars: int, tot_bars: int, day: str) -> None:
        year = str(day or "")[:4]
        lab = "回放 %s · %s %s/%s" % (label, year, done_bars, tot_bars)
        _queue_put("bar", cid, job_key, done_bars, tot_bars, lab)

    walk = {k: v for k, v in payload.items() if k != "cell_id"}
    row = run_one_book_walk(walk, on_bar_progress=_on_bar)
    row["cell_id"] = cid
    row["job_key"] = job_key
    return row


def _drain_walk_queue(q: Any, state: WalkProgress) -> tuple[str, str, str]:
    """把 Queue 事件打进 WalkProgress，不回调 UI。返回最后一条 cid/job_key/label。"""
    last = ("", "", "")
    if q is None:
        return last
    while True:
        try:
            item = q.get_nowait()
        except Empty:
            break
        except Exception:
            break
        if not item:
            continue
        if len(item) >= 6:
            kind = str(item[0] or "")
            cid = str(item[1] or "")
            job_key = str(item[2] or "")
            walk_done = int(item[3] or 0)
            walk_total = int(item[4] or 0)
            label = str(item[5] or "")
        elif len(item) >= 2:
            kind = "start"
            cid = str(item[0] or "")
            job_key = str(item[0] or "")
            walk_done, walk_total = 0, 0
            label = str(item[1] or "")
        else:
            continue
        last = (cid, job_key, label)
        if kind == "bar":
            state.bar(job_key, walk_done, walk_total)
        else:
            state.start(job_key)
    return last


def write_cell_meta(cell: dict[str, Any], jobs: list[dict[str, Any]], cell_dir: Path) -> None:
    cell_dir.mkdir(parents=True, exist_ok=True)
    reset_cell_sample_dirs(cell_dir)
    meta = {
        "id": cell["id"],
        "label": cell["label"],
        "kind": cell["kind"],
        "overrides": cell["overrides"],
        "is_current": bool(cell.get("is_current")) or str(cell.get("id") or "") == "base",
        "n_jobs": len(jobs),
    }
    if cell.get("n_diffs") is not None:
        meta["n_diffs"] = cell.get("n_diffs")
    (cell_dir / "cell_meta.json").write_text(
        json.dumps(_json_ready(meta), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def probe_cell(
    cell: dict[str, Any],
    cell_dir: Path,
    defaults: dict[str, Any],
    n_jobs: int,
    on_progress: Callable[..., None] | None = None,
) -> None:
    _emit_progress(on_progress, str(cell["id"]), 0, n_jobs, "探针 init", phase="probe")
    probe_log = cell_dir / "probe_init.txt"
    try:
        text = run_init_probe(cell.get("overrides") or {}, log_path=probe_log)
    except Exception as e:
        raise GridError("格子 %s 探针失败: %s" % (cell["id"], e)) from e
    expected = expected_fingerprint(defaults, cell["overrides"])
    need_trail = overrides_has_trail_tiers(cell.get("overrides") or {})
    assert_fingerprint_text(text, expected, need_trail=need_trail, source=str(probe_log))


def _load_summarize():
    spec = importlib.util.spec_from_file_location("qmt_local_bt_grid_summarize", SKILL_SUMMARIZE)
    if spec is None or spec.loader is None:
        raise GridError("无法加载 %s" % SKILL_SUMMARIZE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_cell(
    cell: dict[str, Any],
    jobs: list[dict[str, Any]],
    cell_dir: Path,
    defaults: dict[str, Any],
    workers: int,
    on_progress: Callable[[str, int, int, str], None] | None = None,
) -> None:
    write_cell_meta(cell, jobs, cell_dir)
    if not jobs:
        raise GridError("格子 %s 无 job" % cell["id"])
    payloads = [job_payload(j, cell_dir, cell["overrides"], defaults) for j in jobs]
    n = len(payloads)
    probe_cell(cell, cell_dir, defaults, n, on_progress=on_progress)

    def _progress(done: int, total: int, label: str, **extra: Any) -> None:
        _emit_progress(on_progress, str(cell["id"]), done, total, label, **extra)

    done = 0
    w = int(workers or 0)

    def _basket(payload: dict[str, Any]) -> str:
        return str(payload.get("basket_id") or "book")

    if w <= 1 or n <= 1:
        for payload in payloads:
            basket = _basket(payload)
            sample = str(payload.get("sample") or "book")
            jk = walk_job_key(payload, cid=str(cell["id"]))

            def _on_bar(
                done_bars: int,
                tot_bars: int,
                day: str,
                _b=basket,
                _s=sample,
                _jk=jk,
            ) -> None:
                year = str(day or "")[:4]
                label = "回放 %s · %s %s/%s" % (_b, year, done_bars, tot_bars)
                _progress(
                    done,
                    n,
                    label,
                    walk_done=done_bars,
                    walk_total=tot_bars,
                    basket=_b,
                    sample=_s,
                    job_key=_jk,
                )

            _progress(done, n, "回放 %s" % basket, basket=basket, sample=sample, job_key=jk)
            row = run_one_book_walk(payload, on_bar_progress=_on_bar)
            done += 1
            if not row.get("ok"):
                raise GridError(
                    "格子 %s walk 失败: %s" % (cell["id"], row.get("error") or payload.get("basket_id"))
                )
            _progress(done, n, basket, basket=basket, sample=sample, job_key=jk)
        return
    _progress(0, n, "回放 %s" % "+".join(_basket(p) for p in payloads))
    ctx = get_context("spawn")
    with ProcessPoolExecutor(max_workers=w, mp_context=ctx) as ex:
        futs = {ex.submit(run_one_book_walk, p): p for p in payloads}
        for fut in as_completed(futs):
            payload = futs[fut]
            try:
                row = fut.result()
            except Exception as e:
                raise GridError("格子 %s walk 失败: %s" % (cell["id"], e)) from e
            done += 1
            if not row.get("ok"):
                raise GridError(
                    "格子 %s walk 失败: %s"
                    % (cell["id"], row.get("error") or payload.get("basket_id"))
                )
            _progress(done, n, _basket(payload))


def assemble_jobs(
    spec: dict[str, Any],
    *,
    include_sma_ema: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    book = book_jobs(spec)
    jobs: list[dict[str, Any]] = list(book)
    if include_sma_ema and book:
        jobs.extend(ma_control_jobs(book, "SMA"))
        jobs.extend(ma_control_jobs(book, "EMA"))
    return book, jobs


def _run_walks_in_pool(
    payloads: list[dict[str, Any]],
    pool_workers: int,
    n_jobs: int,
    state: WalkProgress,
    on_progress: Callable[..., None] | None = None,
    succeeded: set[str] | None = None,
    pause_dest: Path | None = None,
) -> set[str]:
    """一层全局 walk 池。返回已全部 walk 成功的 cell_id。逻辑失败升 GridError。"""
    if succeeded is None:
        succeeded = set()
    else:
        succeeded.clear()
    if not payloads:
        return succeeded
    remaining: dict[str, int] = {}
    for p in payloads:
        cid = str(p.get("cell_id") or "")
        remaining[cid] = remaining.get(cid, 0) + 1
    ctx = get_context("spawn")
    q = ctx.Queue(maxsize=WALK_PROGRESS_QUEUE_MAX)
    last_cid, last_jk, last_label = "", "", ""
    with ProcessPoolExecutor(
        max_workers=int(pool_workers),
        mp_context=ctx,
        initializer=init_walk_pool,
        initargs=(str(HERE), q),
    ) as ex:
        futs = {ex.submit(run_walk_job, p): p for p in payloads}
        pending = set(futs)
        while pending:
            if pause_dest is not None and pause_requested(pause_dest):
                for rest in pending:
                    rest.cancel()
                raise GridPaused()
            cid, jk, lab = _drain_walk_queue(q, state)
            if cid:
                last_cid, last_jk, last_label = cid, jk, lab
            done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            cid2, jk2, lab2 = _drain_walk_queue(q, state)
            if cid2:
                last_cid, last_jk, last_label = cid2, jk2, lab2
            for fut in done:
                payload = futs[fut]
                cid = str(payload.get("cell_id") or "")
                jk = walk_job_key(payload)
                try:
                    row = fut.result()
                except Exception:
                    state.drop(jk)
                    for rest in pending:
                        rest.cancel()
                    _emit_walk_progress(
                        on_progress, state, cid, last_label, phase="walk", job_key=jk
                    )
                    raise
                if not row.get("ok"):
                    state.drop(jk)
                    for rest in pending:
                        rest.cancel()
                    _emit_walk_progress(
                        on_progress, state, cid, last_label, phase="walk", job_key=jk
                    )
                    raise GridError(
                        "格子 %s walk 失败: %s"
                        % (cid, row.get("error") or payload.get("basket_id"))
                    )
                state.finish(jk)
                remaining[cid] = int(remaining.get(cid) or 1) - 1
                if remaining.get(cid, 1) <= 0:
                    succeeded.add(cid)
                    state.cells_done = len(succeeded)
                last_cid, last_jk, last_label = cid, jk, str(payload.get("basket_id") or "book")
            _emit_walk_progress(
                on_progress, state, last_cid, last_label, phase="walk", job_key=last_jk
            )
        cid3, jk3, lab3 = _drain_walk_queue(q, state)
        if cid3:
            last_cid, last_jk, last_label = cid3, jk3, lab3
        _emit_walk_progress(
            on_progress, state, last_cid, last_label, phase="walk", job_key=last_jk
        )
    return succeeded


def _wrap_serial_progress(
    state: WalkProgress,
    n_cells: int,
    on_progress: Callable[..., None] | None,
) -> Callable[..., None]:
    last_done: dict[str, int] = {}
    current_job: dict[str, str] = {}
    probed: set[str] = set()
    state.probe_total = max(int(n_cells), 0)

    def wrapped(cid: str, done: int, tot: int, label: str, **extra: Any) -> None:
        cid = str(cid or "")
        lab = str(label or "")
        if extra.get("phase") == "probe" or "探针" in lab:
            if cid not in probed:
                probed.add(cid)
                state.probe_done = len(probed)
            _emit_walk_progress(on_progress, state, cid, lab, phase="probe")
            return
        basket = str(extra.get("basket") or extra.get("basket_id") or "")
        if not basket and lab.startswith("回放 "):
            parts = lab.split()
            if len(parts) >= 2:
                basket = parts[1]
        sample = str(extra.get("sample") or "book")
        job_key = str(extra.get("job_key") or walk_job_key(None, cid=cid, sample=sample, basket=basket))
        wt = extra.get("walk_total")
        try:
            wt_f = float(wt or 0)
        except (TypeError, ValueError):
            wt_f = 0.0
        if wt_f > 0:
            state.bar(job_key, int(extra.get("walk_done") or 0), int(wt_f))
            current_job[cid] = job_key
            _emit_walk_progress(on_progress, state, cid, lab, phase="walk", job_key=job_key)
            return
        prev = int(last_done.get(cid) or 0)
        cur = int(done or 0)
        if cur > prev:
            delta = cur - prev
            last_done[cid] = cur
            jk = current_job.pop(cid, None)
            if jk:
                state.finish(jk)
                delta -= 1
            if delta > 0:
                state.completed = min(state.n_walks, int(state.completed) + delta)
            _emit_walk_progress(on_progress, state, cid, lab, phase="walk", job_key=jk or job_key)
            return
        current_job[cid] = job_key
        state.start(job_key)
        _emit_walk_progress(on_progress, state, cid, lab, phase="walk", job_key=job_key)

    return wrapped


def run_cells(
    cells: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    dest: Path,
    defaults: dict[str, Any],
    workers: int,
    on_progress: Callable[..., None] | None = None,
    pause_dest: Path | None = None,
) -> None:
    n_cells = len(cells)
    n_jobs = len(jobs)
    n_walks = n_cells * n_jobs
    cw = resolve_pool_workers(workers, n_walks)
    print("pool_workers=%s n_walks=%s" % (cw, n_walks), flush=True)
    state = WalkProgress(n_walks)
    state.probe_total = n_cells
    wrapped = _wrap_serial_progress(state, n_cells, on_progress)
    if cw <= 1:
        for cell in cells:
            if pause_dest is not None:
                check_pause(pause_dest)
            print("== cell", cell["id"], cell["kind"], cell["overrides"], flush=True)
            run_cell(
                cell,
                jobs,
                dest / cell["id"],
                defaults,
                1,
                on_progress=wrapped,
            )
            state.cells_done += 1
            _emit_walk_progress(
                on_progress, state, str(cell["id"]), "格子完成", phase="walk"
            )
        return
    succeeded: set[str] = set()
    try:
        payloads: list[dict[str, Any]] = []
        for cell in cells:
            if pause_dest is not None:
                check_pause(pause_dest)
            print("== cell", cell["id"], cell["kind"], cell["overrides"], flush=True)
            cell_dir = dest / cell["id"]
            write_cell_meta(cell, jobs, cell_dir)
            if not jobs:
                raise GridError("格子 %s 无 job" % cell["id"])
            probe_cell(cell, cell_dir, defaults, n_jobs, on_progress=wrapped)
            for j in jobs:
                p = job_payload(j, cell_dir, cell["overrides"], defaults)
                p["cell_id"] = str(cell["id"])
                payloads.append(p)
        succeeded = _run_walks_in_pool(
            payloads,
            cw,
            n_jobs,
            state,
            on_progress=on_progress,
            succeeded=succeeded,
            pause_dest=pause_dest,
        )
    except GridPaused:
        raise
    except GridError:
        raise
    except Exception as e:
        print("WARN 格间池失败，回退串行: %s" % e, flush=True)
        for cell in cells:
            if str(cell["id"]) in succeeded:
                continue
            if pause_dest is not None:
                check_pause(pause_dest)
            print("== cell fallback", cell["id"], flush=True)
            run_cell(
                cell,
                jobs,
                dest / cell["id"],
                defaults,
                1,
                on_progress=wrapped,
            )
            state.cells_done += 1
            _emit_walk_progress(
                on_progress, state, str(cell["id"]), "格子完成", phase="walk"
            )


def run_sweep(
    spec: dict[str, Any],
    *,
    include_sma_ema: bool = False,
    workers: int = 0,
    sweep_dir: str | Path | None = None,
    progress: Callable[[str, int, int, str], None] | None = None,
    dry_run: bool = False,
    cell_id: str = "",
    spec_path: str = "",
    reshuffle: bool = False,
    batch_size: int = 0,
    resume: bool = False,
) -> dict[str, Any]:
    if resume:
        reshuffle = False
    cells = validate_spec(spec)
    if cell_id:
        want = str(cell_id).strip()
        cells = [c for c in cells if c["id"] == want]
        if not cells:
            raise GridError("没有格子 id=%s" % want)
    elif not resume:
        cells = order_cells_current_first(cells)
    sweep = str(spec.get("sweep") or Path(spec_path).stem or "grid")
    dest = Path(sweep_dir) if sweep_dir else GRID_ROOT / sweep
    _assert_grid_dir(dest)
    dest.mkdir(parents=True, exist_ok=True)

    prev_freeze: dict[str, Any] | None = None
    freeze_p = dest / "freeze.json"
    if freeze_p.is_file() and not reshuffle:
        try:
            prev_freeze = json.loads(freeze_p.read_text(encoding="utf-8"))
        except Exception:
            prev_freeze = None
    if resume and prev_freeze:
        include_sma_ema = bool(prev_freeze.get("include_sma_ema"))
        for key in YEAR_WINDOW_KEYS:
            if prev_freeze.get(key) is not None:
                spec[key] = int(prev_freeze[key])
        if prev_freeze.get("compare_div"):
            spec["compare_div"] = str(prev_freeze.get("compare_div"))
        split_prev = prev_freeze.get("asset_split")
        if isinstance(split_prev, dict):
            spec["asset_split"] = split_prev
    try:
        split = draw_asset_split(spec, reshuffle=bool(reshuffle), freeze=prev_freeze)
    except AssetSplitError as e:
        raise GridError(str(e)) from e
    spec["asset_split"] = split
    try:
        gate = validate_gate(spec.get("gate"))
    except ValueError as e:
        raise GridError(str(e)) from e
    spec["gate"] = gate_for_json(gate)

    book, jobs = assemble_jobs(spec, include_sma_ema=include_sma_ema)
    if resume and prev_freeze and prev_freeze.get("n_jobs") is not None:
        if int(prev_freeze.get("n_jobs") or 0) != len(jobs):
            raise GridError(
                "resume freeze n_jobs=%s 与当前 jobs=%s 不一致"
                % (prev_freeze.get("n_jobs"), len(jobs))
            )
    if len(jobs) > WARN_JOBS_SOFT:
        print(
            "WARN jobs/cell=%s > %s（空间隔离×SMA/EMA 最多 6 段组合 walk）"
            % (len(jobs), WARN_JOBS_SOFT),
            flush=True,
        )
    (dest / "spec.json").write_text(
        json.dumps(_json_ready(spec), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    win = fill_year_windows(spec)
    freeze_meta = {
        "compare_div": str(spec.get("compare_div") or "front_ratio"),
        "n_book": len(book),
        "n_jobs": len(jobs),
        "include_sma_ema": bool(include_sma_ema),
        "book": [
            {
                "sample": j.get("sample"),
                "basket": j.get("basket"),
                "n_stocks": j.get("n_stocks"),
                "start": j.get("start"),
                "end": j.get("end"),
                "stocks": list(j.get("stocks") or []),
                "ma": j.get("ma"),
                "div": j.get("div"),
            }
            for j in book
        ],
        "asset_split": _json_ready(split),
        "tune_stocks": list(split.get("tune_stocks") or []),
        "holdout_stocks": list(split.get("holdout_stocks") or []),
        "gate": gate_for_json(gate),
        "batch_size": int(
            (prev_freeze or {}).get("batch_size")
            if resume and prev_freeze and prev_freeze.get("batch_size") is not None
            else (batch_size or 0)
        ),
    }
    freeze_meta.update(win)
    (dest / "freeze.json").write_text(
        json.dumps(freeze_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "sweep=%s cells=%s jobs/cell=%s book=%s mode=%s tune=%s holdout=%s eligible=%s"
        % (
            sweep,
            len(cells),
            len(jobs),
            len(book),
            split.get("mode"),
            len(split.get("tune_stocks") or []),
            len(split.get("holdout_stocks") or []),
            split.get("eligible_n"),
        ),
        flush=True,
    )
    info = {
        "sweep": sweep,
        "sweep_dir": str(dest),
        "n_cells": len(cells),
        "n_jobs": len(jobs),
        "n_book": len(book),
        "cells": cells,
        "dry_run": bool(dry_run),
        "asset_split": split,
        "resume": bool(resume),
        "paused": False,
    }
    info.update(win)
    if dry_run:
        info["n_batches"] = len(chunk_ids(cell_ids_of(cells), int(batch_size or 0)))
        return info
    if not cell_id and not resume:
        prune_stale_cell_dirs(dest, [c["id"] for c in cells])
    defaults = load_exit_defaults()
    if cell_id:
        run_cells(
            cells,
            jobs,
            dest,
            defaults,
            int(workers or 0),
            on_progress=progress,
            pause_dest=dest,
        )
        out = _summarize_sweep_cells(
            dest,
            spec.get("gate"),
            cell_ids=[str(c["id"]) for c in cells],
        )
        rec = out.get("recommend") or {}
        info["summary"] = out
        info["recommend"] = rec
        return info

    by_id = {str(c["id"]): c for c in cells}
    freeze_bs = int(freeze_meta.get("batch_size") or batch_size or 0)
    prog = load_progress(dest) if resume else None
    if resume:
        if worker_is_alive(prog):
            raise GridError(
                "sweep 仍有 worker pid=%s 在跑，请先暂停或等其退出"
                % (prog or {}).get("worker_pid")
            )
        prog = mark_running_dead_as_dirty(dest, prog, is_cell_dir, force=True)
        frozen_ids = [str(x).strip() for x in ((prog or {}).get("cell_ids") or []) if str(x).strip()]
        if frozen_ids:
            cells = [by_id[i] for i in frozen_ids if i in by_id]
            by_id = {str(c["id"]): c for c in cells}
        elif prog is None:
            cells = order_cells_current_first(list(by_id.values()))
            by_id = {str(c["id"]): c for c in cells}
            prog = build_progress(cell_ids_of(cells), freeze_bs, worker_pid=os.getpid())
            infer_existing_batch_status(dest, prog, is_cell_dir)
    if prog is None:
        prog = build_progress(cell_ids_of(cells), int(batch_size or 0), worker_pid=os.getpid())
    prog["worker_pid"] = os.getpid()
    save_progress(dest, prog)
    info["n_batches"] = len(iter_batches(prog))
    info["cells"] = cells

    last_hb = 0.0
    last_sum_ids: list[str] | None = None

    def _heartbeat(force: bool = False, **extra: Any) -> None:
        nonlocal last_hb, prog
        now = time.time()
        if not force and now - last_hb < 2.0:
            return
        last_hb = now
        n_walks = extra.get("n_walks")
        completed = extra.get("completed")
        inflight = extra.get("inflight_frac")
        if n_walks is not None:
            try:
                prog["batch_walk_total"] = int(n_walks)
                prog["batch_walk_done"] = float(completed or 0) + float(inflight or 0)
            except (TypeError, ValueError):
                pass
        cells_done = extra.get("cells_done")
        if cells_done is not None:
            try:
                prog["batch_cell_done"] = min(
                    int(prog.get("batch_cell_total") or 0),
                    int(cells_done),
                )
            except (TypeError, ValueError):
                pass
        prog["worker_pid"] = os.getpid()
        prog = save_progress(dest, prog)

    def on_progress_wrap(cid: str, done: int, tot: int, label: str, **extra: Any) -> None:
        if progress is not None:
            progress(cid, done, tot, label, **extra)
        _heartbeat(
            cid=cid,
            completed=extra.get("completed"),
            n_walks=extra.get("n_walks"),
            inflight_frac=extra.get("inflight_frac"),
            cells_done=extra.get("cells_done"),
            force=False,
        )

    def _maybe_summarize() -> None:
        nonlocal last_sum_ids
        want = done_cell_ids(prog)
        if not want or want == last_sum_ids:
            return
        out = _summarize_sweep_cells(dest, spec.get("gate"), cell_ids=want)
        last_sum_ids = list(want)
        info["summary"] = out
        info["recommend"] = out.get("recommend") or {}

    paused = False
    try:
        for batch in iter_batches(prog):
            status = str(batch.get("status") or "")
            if status == STATUS_DONE:
                continue
            ids = list(batch.get("cell_ids") or [])
            chunk = [by_id[i] for i in ids if i in by_id]
            if status == STATUS_DIRTY:
                delete_cell_dirs(dest, ids, is_cell_dir)
            set_batch_status(prog, int(batch["index"]), STATUS_RUNNING)
            prog["batch_cell_done"] = 0
            prog["batch_cell_total"] = len(chunk)
            prog["batch_walk_done"] = 0
            prog["batch_walk_total"] = len(chunk) * max(len(jobs), 0)
            prog["worker_pid"] = os.getpid()
            save_progress(dest, prog)
            print(
                "== batch %s/%s cells=%s"
                % (int(batch["index"]) + 1, info["n_batches"], ",".join(ids)),
                flush=True,
            )
            try:
                run_cells(
                    chunk,
                    jobs,
                    dest,
                    defaults,
                    int(workers or 0),
                    on_progress=on_progress_wrap,
                    pause_dest=dest,
                )
            except GridPaused:
                paused = True
                set_batch_status(prog, int(batch["index"]), STATUS_DIRTY)
                delete_cell_dirs(dest, ids, is_cell_dir)
                prog["worker_pid"] = 0
                save_progress(dest, prog)
                clear_pause(dest)
                print("paused batch", batch["index"], flush=True)
                break
            except GridError:
                set_batch_status(prog, int(batch["index"]), STATUS_DIRTY)
                delete_cell_dirs(dest, ids, is_cell_dir)
                prog["worker_pid"] = 0
                save_progress(dest, prog)
                raise
            set_batch_status(prog, int(batch["index"]), STATUS_DONE)
            prog["batch_cell_done"] = len(chunk)
            prog["worker_pid"] = os.getpid()
            save_progress(dest, prog)
            _maybe_summarize()
        if not paused:
            prog["worker_pid"] = 0
            save_progress(dest, prog)
            _maybe_summarize()
    except KeyboardInterrupt:
        paused = True
        mark_running_dead_as_dirty(dest, prog, is_cell_dir, force=True)
        clear_pause(dest)
        print("interrupted; running batch marked dirty", flush=True)
        _maybe_summarize()
    except GridPaused:
        paused = True
        prog["worker_pid"] = 0
        save_progress(dest, prog)
        clear_pause(dest)
        _maybe_summarize()
    info["paused"] = bool(paused)
    info["progress"] = load_progress(dest)
    rec = info.get("recommend") or {}
    if rec:
        print("recommend", rec.get("id"), rec.get("reason"))
    print("默认不改 config.py、不 deploy；用户说按建议修改后再改片段")
    return info


def _summarize_sweep_cells(
    dest: Path,
    gate: dict[str, Any] | None,
    cell_ids: Iterable[str] | None,
) -> dict[str, Any]:
    mod = _load_summarize()
    try:
        out = mod.summarize_sweep(dest, gate=gate, cell_ids=cell_ids)
    except Exception as e:
        raise GridError(str(e)) from e
    rec = out.get("recommend") or {}
    print("wrote", out.get("summary_path"))
    print("recommend", rec.get("id"), rec.get("reason"))
    return out


def summarize_only(
    sweep_dir: str | Path,
    gate: dict[str, Any] | None = None,
    cell_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    dest = Path(sweep_dir)
    _assert_grid_dir(dest)
    mod = _load_summarize()
    try:
        out = mod.summarize_sweep(dest, gate=gate, cell_ids=cell_ids)
    except Exception as e:
        raise GridError(str(e)) from e
    rec = out.get("recommend") or {}
    print("wrote", out.get("summary_path"))
    print("recommend", rec.get("id"), rec.get("reason"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="真实 local_bt 命名网格")
    ap.add_argument("--spec", default="", help="命名格子 JSON/YAML")
    ap.add_argument("--include-sma-ema", action="store_true", help="额外全 SMA / 全 EMA 对照")
    ap.add_argument(
        "--workers",
        type=int,
        default=0,
        help="全局并行进程数（0=自动=min(walk数, CPU)；1=串行；不夹 16）",
    )
    ap.add_argument("--sweep-dir", default="", help="覆盖输出目录")
    ap.add_argument("--cell", default="", help="只跑指定格子 id")
    ap.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="每组格子数（0=一组全量；UI 默认 10）",
    )
    ap.add_argument(
        "--resume",
        action="store_true",
        help="同一 sweep 续跑：跳过 done 组，dirty 组整组重来",
    )
    ap.add_argument("--summarize-only", action="store_true", help="不重跑，只 summarize")
    ap.add_argument("--dry-run", action="store_true", help="只打印每格 walk 数")
    ap.add_argument("--year-start", type=int, default=None)
    ap.add_argument("--year-end", type=int, default=None)
    ap.add_argument("--tune-start", type=int, default=None)
    ap.add_argument("--tune-end", type=int, default=None)
    ap.add_argument("--check-start", type=int, default=None)
    ap.add_argument("--check-end", type=int, default=None)
    ap.add_argument(
        "--asset-mode",
        default="",
        help="空间隔离: off | random_from_csv（覆盖 spec.asset_split.mode）",
    )
    ap.add_argument("--n", type=int, default=None, dest="n_draw", help="调参与盲测各抽此数")
    ap.add_argument("--n-tune", type=int, default=None, help="调参抽取数")
    ap.add_argument("--n-holdout", type=int, default=None, help="盲测抽取数")
    ap.add_argument("--seed", type=int, default=None, help="抽取 seed（可选；缺省系统随机）")
    ap.add_argument(
        "--reshuffle",
        action="store_true",
        help="忽略 freeze/spec 旧名单，重新抽取（缺 seed 则系统随机）",
    )
    ap.add_argument(
        "--gate-json",
        default="",
        help="过门配置 JSON 文件或内联对象（覆盖 spec.gate）",
    )
    args = ap.parse_args()
    try:
        gate_override = None
        raw_gate = str(args.gate_json or "").strip()
        if raw_gate:
            gp = Path(raw_gate)
            if gp.is_file():
                gate_override = json.loads(gp.read_text(encoding="utf-8"))
            else:
                gate_override = json.loads(raw_gate)
            gate_override = validate_gate(gate_override)
        if args.summarize_only:
            if not args.sweep_dir and not args.spec:
                raise GridError("--summarize-only 需要 --sweep-dir 或 --spec")
            if args.sweep_dir:
                sweep_dir = Path(args.sweep_dir)
            else:
                spec = load_spec(args.spec)
                sweep = str(spec.get("sweep") or Path(args.spec).stem)
                sweep_dir = GRID_ROOT / sweep
            summarize_only(sweep_dir, gate=gate_override)
            return
        if args.cell and args.resume:
            raise GridError("--cell 不能与 --resume 同时使用")
        if args.cell and int(args.batch_size or 0) > 0:
            raise GridError("--cell 不能与 --batch-size>0 同时使用")
        resume = bool(args.resume)
        spec_path = str(args.spec or "")
        sweep_dir_arg = str(args.sweep_dir or "").strip()
        if resume:
            if spec_path:
                spec = load_spec(spec_path)
                dest = Path(sweep_dir_arg) if sweep_dir_arg else GRID_ROOT / str(
                    spec.get("sweep") or Path(spec_path).stem
                )
            elif sweep_dir_arg:
                dest = Path(sweep_dir_arg)
                spec_file = dest / "spec.json"
                if not spec_file.is_file():
                    raise GridError("--resume 需要 %s" % spec_file)
                spec = load_spec(spec_file)
                spec_path = str(spec_file)
            else:
                raise GridError("--resume 需要 --sweep-dir 或 --spec")
        else:
            if not spec_path:
                raise GridError("需要 --spec")
            spec = load_spec(spec_path)
        if not resume:
            cli_years = {
                "year_start": args.year_start,
                "year_end": args.year_end,
                "tune_start": args.tune_start,
                "tune_end": args.tune_end,
                "check_start": args.check_start,
                "check_end": args.check_end,
            }
            for key, val in cli_years.items():
                if val is not None:
                    spec[key] = int(val)
        if gate_override is not None:
            spec["gate"] = gate_for_json(gate_override)
        elif spec.get("gate") is not None:
            spec["gate"] = gate_for_json(validate_gate(spec.get("gate")))
        else:
            spec["gate"] = gate_for_json(fill_gate(None))
        if not resume:
            split = fill_asset_split(spec)
            if args.asset_mode:
                split["mode"] = str(args.asset_mode).strip().lower()
            if args.n_draw is not None:
                split["n"] = int(args.n_draw)
                split["n_tune"] = int(args.n_draw)
                split["n_holdout"] = int(args.n_draw)
            else:
                if args.n_tune is not None:
                    split["n_tune"] = int(args.n_tune)
                if args.n_holdout is not None:
                    split["n_holdout"] = int(args.n_holdout)
            if args.seed is not None:
                split["seed"] = int(args.seed)
            spec["asset_split"] = split
        dest_arg = sweep_dir_arg or None
        if resume and not dest_arg:
            dest_arg = str(dest)
        try:
            run_sweep(
                spec,
                include_sma_ema=bool(args.include_sma_ema) if not resume else False,
                workers=int(args.workers or 0),
                sweep_dir=dest_arg,
                dry_run=bool(args.dry_run),
                cell_id=str(args.cell or ""),
                spec_path=spec_path,
                reshuffle=bool(args.reshuffle) if not resume else False,
                batch_size=0 if resume else int(args.batch_size or 0),
                resume=resume,
            )
        except GridPaused:
            return
    except GridError as e:
        raise SystemExit(str(e)) from e


if __name__ == "__main__":
    main()