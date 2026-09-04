# coding: utf-8
"""真实 local_bt 命名网格：冻结 winner、隔离目录、格间串行。

用法（仓库根目录）::

  python hongli_band/scripts/local_bt/grid_run.py --spec .cursor/skills/qmt-local-bt-grid/examples/stop_loss.json
  python hongli_band/scripts/local_bt/grid_run.py --spec cells.json --book-only
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
THEME = REPO / "hongli_band"
HLBAND_CONFIG = THEME / "scripts" / "qmt" / "hlband" / "config.py"
GRID_ROOT = THEME / "report" / "grid"
COMPARE_DEFAULT = THEME / "report" / "front_ratio" / "local_bt_ma_compare.csv"
SKILL_SUMMARIZE = (
    REPO / ".cursor" / "skills" / "qmt-local-bt-grid" / "scripts" / "summarize.py"
)

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from analyze import (  # noqa: E402
    DEFAULT_CSV_ROOT,
    DEFAULT_DIVIDEND_TYPE,
    csv_source_dividend_type,
    daily_csvs_by_stock,
    normalize_dividend_type,
    normalize_ma_type,
    resolve_typed_dir,
)
from run import (  # noqa: E402
    _as_trail_tiers,
    _run_payloads,
    default_log_name,
)

MAX_CELLS = 8
YEAR_START, YEAR_END = 2018, 2026
RE_STOP = re.compile(r"\bstop=\s*([0-9.eE+-]+)")
RE_TFB = re.compile(r"\btime_force_bars=\s*(-?\d+)")
RE_TFM = re.compile(r"\btime_force_min_ret=\s*([0-9.eE+-]+)")
RE_ARM = re.compile(r"\btrail_arm=\s*([0-9.eE+-]+|None)")

_CSV_INDEX: dict[tuple[str, str], Path] = {}


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
            raise SystemExit("YAML spec 需要 PyYAML，请改用 JSON") from e
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise SystemExit("spec 必须是对象")
    return data


def validate_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    cells = list(spec.get("cells") or [])
    if not cells:
        raise SystemExit("spec.cells 为空")
    if len(cells) > MAX_CELLS:
        raise SystemExit("格子数 %s > %s（含 base）" % (len(cells), MAX_CELLS))
    ids: list[str] = []
    n_base = 0
    out: list[dict[str, Any]] = []
    for raw in cells:
        if not isinstance(raw, dict):
            raise SystemExit("每个 cell 必须是对象")
        cid = str(raw.get("id") or "").strip()
        if not cid:
            raise SystemExit("cell 缺少 id")
        if cid in ids:
            raise SystemExit("重复 cell id: %s" % cid)
        ids.append(cid)
        kind = str(raw.get("kind") or ("base" if cid == "base" else "other")).strip().lower()
        if cid == "base":
            n_base += 1
            kind = "base"
        overrides = raw.get("overrides") or {}
        if not isinstance(overrides, dict):
            raise SystemExit("%s.overrides 必须是对象" % cid)
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
        raise SystemExit("必须恰好一个 id=base 的格子，当前 %s" % n_base)
    return out


def _load_hlband_config():
    spec = importlib.util.spec_from_file_location("hlband_config_grid", HLBAND_CONFIG)
    if spec is None or spec.loader is None:
        raise SystemExit("无法读取 %s" % HLBAND_CONFIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_exit_defaults() -> dict[str, Any]:
    mod = _load_hlband_config()
    return {
        "STOP_LOSS": float(getattr(mod, "STOP_LOSS")),
        "TIME_FORCE_BARS": int(getattr(mod, "TIME_FORCE_BARS")),
        "TIME_FORCE_MIN_RET": float(getattr(mod, "TIME_FORCE_MIN_RET")),
        "TRAIL_TIERS": getattr(mod, "TRAIL_TIERS"),
    }


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
        raise SystemExit("config.BOOK_STOCKS 为空或无法解析")
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
        raise SystemExit("config.BOOK_STOCKS 没有有效标的")
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
        raise SystemExit(
            "指纹 stop 不符 log=%s got=%s expected=%s" % (log_path, got["stop"], expected["stop"])
        )
    if not got["has_tfb"] or got["time_force_bars"] != expected["time_force_bars"]:
        raise SystemExit(
            "指纹 time_force_bars 不符 log=%s got=%s expected=%s"
            % (log_path, got["time_force_bars"], expected["time_force_bars"])
        )
    if got["time_force_min_ret"] is not None and not _num_eq(
        got["time_force_min_ret"], expected["time_force_min_ret"]
    ):
        raise SystemExit(
            "指纹 time_force_min_ret 不符 log=%s got=%s expected=%s"
            % (log_path, got["time_force_min_ret"], expected["time_force_min_ret"])
        )
    if need_trail:
        if not got["has_trail_arm"] or not _num_eq(got["trail_arm"], expected["trail_arm"]):
            raise SystemExit(
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
    hit = _CSV_INDEX.get(key)
    return hit if hit is not None and hit.is_file() else None


def _year_window(year: str) -> tuple[str, str]:
    y = str(int(year))
    return "%s0101" % y, "%s1231" % y


def freeze_winner_jobs(compare_csv: Path, div: str) -> list[dict[str, Any]]:
    if not compare_csv.is_file():
        raise SystemExit(
            "缺少冻结 winner 表 %s ；请先跑基线 local_bt 均线对照" % compare_csv
        )
    df = pd.read_csv(compare_csv)
    jobs: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        stock = str(r.get("stock") or "").strip().upper()
        year = str(int(r["year"])) if pd.notna(r.get("year")) else ""
        ma = str(r.get("winner") or "").strip().upper()
        if not stock or not year or ma not in ("SMA", "EMA"):
            continue
        csv_col = "sma_csv" if ma == "SMA" else "ema_csv"
        csv_p = Path(str(r.get(csv_col) or ""))
        if not csv_p.is_file():
            alt = csv_for(stock, div)
            csv_p = alt if alt is not None else csv_p
        if not csv_p.is_file():
            print("skip winner 无 CSV", stock, year, ma, flush=True)
            continue
        start, end = _year_window(year)
        jobs.append(
            {
                "sample": "winner",
                "stock": stock,
                "year": year,
                "ma": ma,
                "div": div,
                "csv": csv_p,
                "start": start,
                "end": end,
            }
        )
    if not jobs:
        raise SystemExit("winner 冻结名单为空: %s" % compare_csv)
    return jobs


def book_jobs() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for stock, ma, div in load_book_lock():
        csv_p = csv_for(stock, div)
        if csv_p is None:
            print("skip book 无 CSV", stock, div, flush=True)
            continue
        for year in range(YEAR_START, YEAR_END + 1):
            ys, ye = _year_window(str(year))
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


def ma_control_jobs(winner_jobs: list[dict[str, Any]], ma: str) -> list[dict[str, Any]]:
    kind = str(ma).upper()
    out: list[dict[str, Any]] = []
    for j in winner_jobs:
        q = dict(j)
        q["sample"] = kind.lower()
        q["ma"] = kind
        out.append(q)
    return out


def _assert_grid_dir(path: Path) -> None:
    parts = [str(x).lower() for x in path.parts]
    if "grid" not in parts:
        raise SystemExit("禁止把网格 log 写到非 report/grid 目录: %s" % path)
    if "front_ratio" in parts and "grid" in parts:
        idx_g = parts.index("grid")
        # report/grid/.../front_ratio 作为 sample 下的复权子目录允许
        if idx_g > parts.index("front_ratio"):
            raise SystemExit("禁止覆盖基线 report/front_ratio: %s" % path)


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
        raise SystemExit("无法加载 %s" % SKILL_SUMMARIZE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_cell(
    cell: dict[str, Any],
    jobs: list[dict[str, Any]],
    cell_dir: Path,
    defaults: dict[str, Any],
    workers: int,
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
        raise SystemExit("格子 %s 无 job" % cell["id"])
    payloads = [job_payload(j, cell_dir, cell["overrides"]) for j in jobs]
    expected = expected_fingerprint(defaults, cell["overrides"])
    need_trail = "TRAIL_TIERS" in (cell.get("overrides") or {})

    def _progress(done: int, total: int, label: str) -> None:
        print("[%s] %s/%s %s" % (cell["id"], done, total, label), flush=True)

    probe = [payloads[0]]
    probe_rows = _run_payloads(probe, Path(probe[0]["out_dir"]), _progress, 1)
    log0 = Path(str(probe_rows[0].get("log") or ""))
    if not probe_rows[0].get("ok") or not log0.is_file():
        raise SystemExit(
            "格子 %s 探针失败: %s" % (cell["id"], probe_rows[0].get("error") or log0)
        )
    assert_fingerprint(log0, expected, need_trail=need_trail)
    rest = payloads[1:]
    if rest:
        _run_payloads(rest, Path(rest[0]["out_dir"]), _progress, workers)


def main() -> None:
    ap = argparse.ArgumentParser(description="真实 local_bt 命名网格")
    ap.add_argument("--spec", default="", help="命名格子 JSON/YAML")
    ap.add_argument("--book-only", action="store_true", help="只跑跟踪池 4 只")
    ap.add_argument("--include-sma-ema", action="store_true", help="额外全 SMA / 全 EMA 对照")
    ap.add_argument("--workers", type=int, default=0, help="格内进程数；格子之间串行")
    ap.add_argument("--compare-csv", default="", help="冻结 winner 的 local_bt_ma_compare.csv")
    ap.add_argument("--sweep-dir", default="", help="覆盖输出目录")
    ap.add_argument("--cell", default="", help="只跑指定格子 id")
    ap.add_argument("--summarize-only", action="store_true", help="不重跑，只 summarize")
    ap.add_argument("--dry-run", action="store_true", help="只打印 job 数")
    args = ap.parse_args()

    if args.summarize_only:
        if not args.sweep_dir and not args.spec:
            raise SystemExit("--summarize-only 需要 --sweep-dir 或 --spec")
        if args.sweep_dir:
            sweep_dir = Path(args.sweep_dir)
        else:
            spec = load_spec(args.spec)
            sweep = str(spec.get("sweep") or Path(args.spec).stem)
            sweep_dir = GRID_ROOT / sweep
        _assert_grid_dir(sweep_dir)
        mod = _load_summarize()
        out = mod.summarize_sweep(sweep_dir)
        rec = out.get("recommend") or {}
        print("wrote", out.get("summary_path"))
        print("recommend", rec.get("id"), rec.get("reason"))
        return

    if not args.spec:
        raise SystemExit("需要 --spec")
    spec = load_spec(args.spec)
    cells = validate_spec(spec)
    if args.cell:
        want = str(args.cell).strip()
        cells = [c for c in cells if c["id"] == want]
        if not cells:
            raise SystemExit("没有格子 id=%s" % want)

    sweep = str(spec.get("sweep") or Path(args.spec).stem)
    compare_div = str(spec.get("compare_div") or "front_ratio")
    sweep_dir = Path(args.sweep_dir) if args.sweep_dir else GRID_ROOT / sweep
    _assert_grid_dir(sweep_dir)

    compare_csv = Path(args.compare_csv) if args.compare_csv else COMPARE_DEFAULT
    if spec.get("compare_csv"):
        compare_csv = Path(str(spec["compare_csv"]))

    winner = [] if args.book_only else freeze_winner_jobs(compare_csv, compare_div)
    book = book_jobs()
    jobs: list[dict[str, Any]] = []
    jobs.extend(winner)
    jobs.extend(book)
    if args.include_sma_ema and winner:
        jobs.extend(ma_control_jobs(winner, "SMA"))
        jobs.extend(ma_control_jobs(winner, "EMA"))

    sweep_dir.mkdir(parents=True, exist_ok=True)
    (sweep_dir / "spec.json").write_text(
        json.dumps(_json_ready(spec), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    freeze_meta = {
        "compare_csv": str(compare_csv),
        "compare_div": compare_div,
        "n_winner": len(winner),
        "n_book": len(book),
        "n_jobs": len(jobs),
        "book_only": bool(args.book_only),
        "include_sma_ema": bool(args.include_sma_ema),
        "winner": [
            {"stock": j["stock"], "year": j["year"], "ma": j["ma"], "div": j["div"]}
            for j in winner
        ],
    }
    (sweep_dir / "freeze.json").write_text(
        json.dumps(freeze_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "sweep=%s cells=%s jobs/cell=%s winner=%s book=%s"
        % (sweep, len(cells), len(jobs), len(winner), len(book)),
        flush=True,
    )
    if args.dry_run:
        return

    defaults = load_exit_defaults()
    cells = sorted(cells, key=lambda c: 0 if c["id"] == "base" else 1)
    for cell in cells:
        print("== cell", cell["id"], cell["kind"], cell["overrides"], flush=True)
        run_cell(cell, jobs, sweep_dir / cell["id"], defaults, int(args.workers or 0))

    mod = _load_summarize()
    out = mod.summarize_sweep(sweep_dir)
    rec = out.get("recommend") or {}
    print("wrote", out.get("summary_path"))
    print("recommend", rec.get("id"), rec.get("reason"))
    print("默认不改 config.py、不 deploy；用户说按建议修改后再改片段")


if __name__ == "__main__":
    main()
