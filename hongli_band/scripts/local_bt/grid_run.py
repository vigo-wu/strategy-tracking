# coding: utf-8
"""真实 local_bt 命名网格：跟踪池 BOOK_STOCKS、隔离目录、格间串行。

用法（仓库根目录）::

  python hongli_band/scripts/local_bt/grid_run.py --spec .cursor/skills/qmt-local-bt-grid/examples/stop_loss.json
  python hongli_band/scripts/local_bt/grid_run.py --spec path/to/cells.json --include-sma-ema
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

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
    GridSpecError,
    apply_year_windows,
    fill_year_windows,
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
from run import (  # noqa: E402
    _as_trail_tiers,
    _run_payloads,
    default_log_name,
)

WARN_CELL_SOFT = 8
WARN_JOBS_SOFT = 200
RE_STOP = re.compile(r"\bstop=\s*([0-9.eE+-]+)")
RE_TFB = re.compile(r"\btime_force_bars=\s*(-?\d+)")
RE_TFM = re.compile(r"\btime_force_min_ret=\s*([0-9.eE+-]+)")
RE_ARM = re.compile(r"\btrail_arm=\s*([0-9.eE+-]+|None)")

_CSV_INDEX: dict[tuple[str, str], Path] = {}
_CSV_SPAN: dict[str, tuple[str, str] | None] = {}


class GridError(Exception):
    """网格 spec / 运行错误（CLI 转成 exit）。"""


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
    return data


def validate_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    cells = list(spec.get("cells") or [])
    if not cells:
        raise GridError("spec.cells 为空")
    if len(cells) > WARN_CELL_SOFT:
        print(
            "WARN 格子数 %s > %s（含 base）；叉乘交互项多，确认后再跑"
            % (len(cells), WARN_CELL_SOFT),
            flush=True,
        )
    ids: list[str] = []
    n_base = 0
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
            n_base += 1
            kind = "base"
        overrides = raw.get("overrides") or {}
        if not isinstance(overrides, dict):
            raise GridError("%s.overrides 必须是对象" % cid)
        if cid == "base" and overrides:
            print("WARN base 格 overrides 非空，仍按覆盖跑", flush=True)
        out.append(
            {
                "id": cid,
                "label": str(raw.get("label") or cid),
                "kind": kind,
                "overrides": pickle_safe(overrides),
            }
        )
    if n_base != 1:
        raise GridError("必须恰好一个 id=base 的格子，当前 %s" % n_base)
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
    out: dict[str, Any] = {"TRAIL_TIERS": getattr(mod, "TRAIL_TIERS")}
    for spec in param_catalog():
        if spec.key == "TRAIL_TIERS":
            continue
        if hasattr(mod, spec.key):
            out[spec.key] = getattr(mod, spec.key)
    return out


def load_exit_defaults() -> dict[str, Any]:
    return load_config_defaults()


def load_book_lock() -> list[tuple[str, str, str]]:
    """config.BOOK_STOCKS → [(stock, ma_type, dividend_type), ...]。"""
    mod = _load_hlband_config()
    raw = getattr(mod, "BOOK_STOCKS", None)
    default_ma = normalize_ma_type(getattr(mod, "MA_TYPE", "EMA")) or "EMA"
    default_div = (
        normalize_dividend_type(getattr(mod, "DIVIDEND_TYPE", "")) or DEFAULT_DIVIDEND_TYPE
    )
    items: list[tuple[Any, Any]]
    if isinstance(raw, dict):
        items = list(raw.items())
    elif isinstance(raw, (list, tuple)):
        items = [(str(x), {}) for x in raw]
    else:
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


def expected_fingerprint(
    defaults: dict[str, Any],
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = dict(defaults)
    ov = overrides or {}
    if "TRAIL_TIERS" in ov:
        merged["TRAIL_TIERS"] = _as_trail_tiers(ov["TRAIL_TIERS"])
    for k, v in ov.items():
        if k == "TRAIL_TIERS":
            continue
        merged[k] = v
    arm = None
    try:
        arm = float(merged["TRAIL_TIERS"][0][0])
    except (IndexError, TypeError, ValueError, KeyError):
        arm = None
    return {
        "stop": float(merged["STOP_LOSS"]),
        "time_force_bars": int(merged["TIME_FORCE_BARS"]),
        "time_force_min_ret": float(merged["TIME_FORCE_MIN_RET"]),
        "trail_arm": arm,
    }


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
    return {
        "stop": None if stop_m is None else float(stop_m.group(1)),
        "time_force_bars": None if tfb_m is None else int(tfb_m.group(1)),
        "time_force_min_ret": None if tfm_m is None else float(tfm_m.group(1)),
        "trail_arm": arm,
        "has_trail_arm": arm_m is not None,
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


def assert_fingerprint(
    log_path: Path,
    expected: dict[str, Any],
    *,
    need_trail: bool,
) -> None:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    got = parse_fingerprint(text)
    if not got["has_stop"] or not _num_eq(got["stop"], expected["stop"]):
        raise GridError(
            "指纹 stop 不符 log=%s got=%s expected=%s" % (log_path, got["stop"], expected["stop"])
        )
    if not got["has_tfb"] or got["time_force_bars"] != expected["time_force_bars"]:
        raise GridError(
            "指纹 time_force_bars 不符 log=%s got=%s expected=%s"
            % (log_path, got["time_force_bars"], expected["time_force_bars"])
        )
    if got["time_force_min_ret"] is not None and not _num_eq(
        got["time_force_min_ret"], expected["time_force_min_ret"]
    ):
        raise GridError(
            "指纹 time_force_min_ret 不符 log=%s got=%s expected=%s"
            % (log_path, got["time_force_min_ret"], expected["time_force_min_ret"])
        )
    if need_trail:
        if not got["has_trail_arm"] or not _num_eq(got["trail_arm"], expected["trail_arm"]):
            raise GridError(
                "指纹 trail_arm 不符 log=%s got=%s expected=%s"
                % (log_path, got.get("trail_arm"), expected["trail_arm"])
            )


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


def _year_window(year: str) -> tuple[str, str]:
    y = str(int(year))
    return "%s0101" % y, "%s1231" % y


def book_jobs(spec: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    win = fill_year_windows(spec)
    y0, y1 = int(win["year_start"]), int(win["year_end"])
    split = fill_asset_split(spec)
    if split["mode"] == "random_from_csv":
        locks = stock_lock_rows(split)
        if not locks:
            raise GridError("asset_split 名单为空，请先抽取 tune/holdout")
    else:
        locks = load_book_lock()
    out: list[dict[str, Any]] = []
    for stock, ma, div in locks:
        csv_p = csv_for(stock, div)
        if csv_p is None:
            print("skip book 无 CSV", stock, div, flush=True)
            continue
        for year in range(y0, y1 + 1):
            ys, ye = _year_window(str(year))
            if not _year_overlaps_csv(csv_p, ys, ye):
                print("skip book 无行情", stock, year, flush=True)
                continue
            out.append(
                {
                    "sample": "book",
                    "stock": stock,
                    "year": str(year),
                    "ma": ma,
                    "div": div,
                    "csv": csv_p,
                    "start": ys,
                    "end": ye,
                }
            )
    return out


def ma_control_jobs(src_jobs: list[dict[str, Any]], ma: str) -> list[dict[str, Any]]:
    kind = str(ma).upper()
    out: list[dict[str, Any]] = []
    for j in src_jobs:
        q = dict(j)
        q["sample"] = kind.lower()
        q["ma"] = kind
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


def job_payload(job: dict[str, Any], cell_dir: Path, overrides: dict[str, Any]) -> dict[str, Any]:
    dest = cell_dir / str(job["sample"]) / str(job["div"])
    dest.mkdir(parents=True, exist_ok=True)
    _assert_grid_dir(dest)
    stock = str(job["stock"])
    year = str(job["year"])
    ma = str(job["ma"])
    return {
        "csv": str(job["csv"]),
        "stock": stock,
        "start": str(job["start"]),
        "end": str(job["end"]),
        "year": year,
        "out_dir": str(dest),
        "quiet": True,
        "log_name": default_log_name(stock, year=year, ma_type=ma),
        "ma_type": ma,
        "dividend_type": str(job["div"]),
        "overrides": pickle_safe(overrides),
    }


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
    cell_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "id": cell["id"],
        "label": cell["label"],
        "kind": cell["kind"],
        "overrides": cell["overrides"],
        "n_jobs": len(jobs),
    }
    (cell_dir / "cell_meta.json").write_text(
        json.dumps(_json_ready(meta), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not jobs:
        raise GridError("格子 %s 无 job" % cell["id"])
    payloads = [job_payload(j, cell_dir, cell["overrides"]) for j in jobs]
    expected = expected_fingerprint(defaults, cell["overrides"])
    need_trail = "TRAIL_TIERS" in (cell.get("overrides") or {})

    def _progress(done: int, total: int, label: str) -> None:
        if on_progress is not None:
            on_progress(str(cell["id"]), done, total, label)
        else:
            print("[%s] %s/%s %s" % (cell["id"], done, total, label), flush=True)

    probe_idx = None
    rest: list[dict[str, Any]] = []
    for i, payload in enumerate(payloads):
        probe_rows = _run_payloads([payload], Path(payload["out_dir"]), _progress, 1)
        log0 = Path(str(probe_rows[0].get("log") or ""))
        if probe_rows[0].get("ok") and log0.is_file():
            assert_fingerprint(log0, expected, need_trail=need_trail)
            probe_idx = i
            rest = payloads[i + 1 :]
            break
        err = str(probe_rows[0].get("error") or "")
        if "无行情交集" in err:
            print(
                "skip probe 无行情",
                payload.get("stock"),
                payload.get("year"),
                flush=True,
            )
            continue
        raise GridError("格子 %s 探针失败: %s" % (cell["id"], err or log0))
    if probe_idx is None:
        raise GridError("格子 %s 探针失败: 全部 job 无行情交集" % cell["id"])
    if rest:
        _run_payloads(rest, Path(rest[0]["out_dir"]), _progress, workers)


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
) -> dict[str, Any]:
    cells = validate_spec(spec)
    if cell_id:
        want = str(cell_id).strip()
        cells = [c for c in cells if c["id"] == want]
        if not cells:
            raise GridError("没有格子 id=%s" % want)
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
    if len(jobs) > WARN_JOBS_SOFT:
        print(
            "WARN jobs/cell=%s > %s（空间抽取或年窗偏大；SMA/EMA 对照再 ×3）"
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
            {"stock": j["stock"], "year": j["year"], "ma": j["ma"], "div": j["div"]}
            for j in book
        ],
        "asset_split": _json_ready(split),
        "tune_stocks": list(split.get("tune_stocks") or []),
        "holdout_stocks": list(split.get("holdout_stocks") or []),
        "gate": gate_for_json(gate),
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
    }
    info.update(win)
    if dry_run:
        return info
    if not cell_id:
        prune_stale_cell_dirs(dest, [c["id"] for c in cells])
    defaults = load_exit_defaults()
    cells = sorted(cells, key=lambda c: 0 if c["id"] == "base" else 1)
    for cell in cells:
        print("== cell", cell["id"], cell["kind"], cell["overrides"], flush=True)
        run_cell(
            cell,
            jobs,
            dest / cell["id"],
            defaults,
            int(workers or 0),
            on_progress=progress,
        )
    mod = _load_summarize()
    out = mod.summarize_sweep(dest, gate=spec.get("gate"))
    rec = out.get("recommend") or {}
    print("wrote", out.get("summary_path"))
    print("recommend", rec.get("id"), rec.get("reason"))
    print("默认不改 config.py、不 deploy；用户说按建议修改后再改片段")
    info["summary"] = out
    info["recommend"] = rec
    return info


def summarize_only(
    sweep_dir: str | Path,
    gate: dict[str, Any] | None = None,
    cell_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    dest = Path(sweep_dir)
    _assert_grid_dir(dest)
    mod = _load_summarize()
    out = mod.summarize_sweep(dest, gate=gate, cell_ids=cell_ids)
    rec = out.get("recommend") or {}
    print("wrote", out.get("summary_path"))
    print("recommend", rec.get("id"), rec.get("reason"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="真实 local_bt 命名网格")
    ap.add_argument("--spec", default="", help="命名格子 JSON/YAML")
    ap.add_argument("--include-sma-ema", action="store_true", help="额外全 SMA / 全 EMA 对照")
    ap.add_argument("--workers", type=int, default=0, help="格内进程数；格子之间串行")
    ap.add_argument("--sweep-dir", default="", help="覆盖输出目录")
    ap.add_argument("--cell", default="", help="只跑指定格子 id")
    ap.add_argument("--summarize-only", action="store_true", help="不重跑，只 summarize")
    ap.add_argument("--dry-run", action="store_true", help="只打印 job 数")
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
    ap.add_argument("--n-tune", type=int, default=None, help="调参抽取数")
    ap.add_argument("--n-holdout", type=int, default=None, help="盲测抽取数")
    ap.add_argument("--seed", type=int, default=None, help="抽取 seed")
    ap.add_argument(
        "--reshuffle",
        action="store_true",
        help="忽略 freeze/spec 旧名单，按 seed 重新抽取",
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
        if not args.spec:
            raise GridError("需要 --spec")
        spec = load_spec(args.spec)
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
        split = fill_asset_split(spec)
        if args.asset_mode:
            split["mode"] = str(args.asset_mode).strip().lower()
        if args.n_tune is not None:
            split["n_tune"] = int(args.n_tune)
        if args.n_holdout is not None:
            split["n_holdout"] = int(args.n_holdout)
        if args.seed is not None:
            split["seed"] = int(args.seed)
        spec["asset_split"] = split
        run_sweep(
            spec,
            include_sma_ema=bool(args.include_sma_ema),
            workers=int(args.workers or 0),
            sweep_dir=args.sweep_dir or None,
            dry_run=bool(args.dry_run),
            cell_id=str(args.cell or ""),
            spec_path=str(args.spec),
            reshuffle=bool(args.reshuffle),
        )
    except GridError as e:
        raise SystemExit(str(e)) from e


if __name__ == "__main__":
    main()