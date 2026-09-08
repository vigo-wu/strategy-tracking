# coding: utf-8
"""解析网格各格组合 walk log → 账户盈亏 / 几何年化 / 过门推荐 JSON。

用法（仓库根目录）::

  python .cursor/skills/qmt-local-bt-grid/scripts/summarize.py --sweep-dir hongli_band/report/grid/stop_loss_confirm
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
LOCAL_BT = REPO / "hongli_band" / "scripts" / "local_bt"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(LOCAL_BT) not in sys.path:
    sys.path.insert(0, str(LOCAL_BT))

from local_bt_log import (  # noqa: E402
    BUDGET,
    parse_local_bt_log,
    parse_trade_budget,
)
from compound_wallet import parse_wallet_from_log  # noqa: E402
from robust_summarize import window_kpi_from_trades  # noqa: E402
from trades_csv import trades_csv_path  # noqa: E402
from grid_spec import (  # noqa: E402
    YEAR_WINDOW_KEYS,
    fill_year_windows,
    year_range_set,
)
from grid_gate import (  # noqa: E402
    EPS_GATE,
    fill_gate,
    gate_for_json,
    load_gate_from_sweep,
    validate_gate,
)

SAMPLES = ("book", "sma", "ema")
RE_LEGACY_LOG = re.compile(
    r"^local_bt_(\d{6})_(SZ|SH)_(\d{4})_(SMA|EMA)\.txt$",
    re.I,
)
EPS_PNL = 1.0


class GridSummarizeError(ValueError):
    """旧口径 log 或组合明细无法汇总。"""


def _json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_ready(x) for x in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _assert_not_legacy_logs(paths: Sequence[Path]) -> None:
    for path in paths:
        if RE_LEGACY_LOG.match(path.name):
            raise GridSummarizeError(
                "检测到旧 stock×年 网格 log（%s）。组合口径须重跑，不能只汇总。"
                % path.name
            )


def _walk_budget(log_path: Path, fallback: float = BUDGET) -> float:
    text = ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        text = ""
    wallet = parse_wallet_from_log(text) if text else {}
    start = wallet.get("wallet_cash_start")
    if start is not None:
        try:
            v = float(start)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    bud = parse_trade_budget(log_path, default=0.0)
    if bud > 0:
        return float(bud)
    return float(fallback)


def _sell_counts(trades: list[dict[str, Any]]) -> dict[str, Any]:
    by_sig: dict[str, int] = defaultdict(int)
    by_year: dict[int, float] = defaultdict(float)
    for t in trades:
        sig = str(t.get("sell_signal") or "-")
        by_sig[sig] += 1
        day = str(t.get("sell_exec_day") or "")
        if len(day) >= 4 and day[:4].isdigit():
            by_year[int(day[:4])] += float(t.get("pnl") or 0)
    return {
        "sell": dict(by_sig),
        "n_trail": int(by_sig.get("trail_stop", 0)),
        "n_stop": int(by_sig.get("stop_loss", 0)),
        "n_weekly": int(by_sig.get("weekly_bear", 0)),
        "n_time": int(by_sig.get("time_force", 0)),
        "by_year": {str(y): round(by_year[y], 2) for y in sorted(by_year)},
    }


def stats_from_trades(
    trades: list[dict[str, Any]],
    n_accounts_by_year: dict[int, int] | None = None,
    *,
    tune_years: set[int] | None = None,
    check_years: set[int] | None = None,
    run_years: set[int] | None = None,
    per_budget: float | None = None,
    tune_stocks: Any = None,
    holdout_stocks: Any = None,
) -> dict[str, Any]:
    """单账户组合窗 KPI。n_accounts_by_year / tune_stocks 仅兼容旧调用，不再按独立账户加总。"""
    del n_accounts_by_year, tune_stocks, holdout_stocks
    win = fill_year_windows(None)
    tune = set(tune_years) if tune_years is not None else year_range_set(
        win["tune_start"], win["tune_end"]
    )
    check = set(check_years) if check_years is not None else year_range_set(
        win["check_start"], win["check_end"]
    )
    run = set(run_years) if run_years is not None else year_range_set(
        win["year_start"], win["year_end"]
    )
    budget = float(BUDGET if per_budget is None else per_budget)
    windows = {
        "all": window_kpi_from_trades(trades, run, budget=budget),
        "tune": window_kpi_from_trades(trades, tune, budget=budget),
        "check": window_kpi_from_trades(trades, check, budget=budget),
    }
    extra = _sell_counts(trades)
    all_w = windows["all"]
    out: dict[str, Any] = {
        "n_trades": int(all_w.get("n_trades") or 0),
        "sum_pnl": all_w.get("avg_year_pnl"),
        "win_rate": all_w.get("win_rate"),
        "profit_factor": all_w.get("profit_factor"),
        "is_pnl": windows["tune"].get("avg_year_pnl"),
        "oos_pnl": windows["check"].get("avg_year_pnl"),
        "max_dd": all_w.get("max_dd"),
        "per_budget": budget,
        "windows": windows,
    }
    out.update(extra)
    return out


def _empty_stats() -> dict[str, Any]:
    return stats_from_trades([], {})


def _delta_stats(cell: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "sum_pnl",
        "is_pnl",
        "oos_pnl",
        "corner_oos_pnl",
        "asset_oos_pnl",
        "profit_factor",
        "win_rate",
        "max_dd",
    )
    out: dict[str, Any] = {}
    for k in keys:
        a = cell.get(k)
        b = base.get(k)
        if a is None or b is None:
            out[k] = None
        else:
            out[k] = round(
                float(a) - float(b),
                4 if k in ("profit_factor", "win_rate", "max_dd") else 2,
            )
    return out


def _load_asset_lists(root: Path) -> tuple[list[str] | None, list[str] | None]:
    for name in ("freeze.json", "spec.json"):
        path = root / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        block = data.get("asset_split") if isinstance(data.get("asset_split"), dict) else data
        mode = str(block.get("mode") or data.get("mode") or "off").strip().lower()
        if mode == "off":
            return None, None
        tune = [str(x).strip().upper() for x in (block.get("tune_stocks") or []) if str(x).strip()]
        holdout = [
            str(x).strip().upper() for x in (block.get("holdout_stocks") or []) if str(x).strip()
        ]
        if tune or holdout:
            return (tune or None), (holdout or None)
    return None, None


def summarize_cell(
    cell_dir: Path,
    *,
    tune_years: set[int] | None = None,
    check_years: set[int] | None = None,
    run_years: set[int] | None = None,
    tune_stocks: Any = None,
    holdout_stocks: Any = None,
) -> dict[str, Any]:
    del tune_stocks
    meta = _load_cell_meta(cell_dir)
    samples: dict[str, Any] = {}
    space_on = bool(holdout_stocks)
    for name in SAMPLES:
        primary_logs, holdout_logs = _split_walk_logs(cell_dir / name)
        _assert_not_legacy_logs(primary_logs + holdout_logs)
        trades, n_ok, n_fail, budget = parse_walk_logs(primary_logs)
        st = stats_from_trades(
            trades,
            tune_years=tune_years,
            check_years=check_years,
            run_years=run_years,
            per_budget=budget,
        )
        st["n_logs_ok"] = n_ok
        st["n_logs_fail"] = n_fail
        if space_on:
            h_trades, h_ok, h_fail, h_bud = parse_walk_logs(holdout_logs)
            hold = stats_from_trades(
                h_trades,
                tune_years=tune_years,
                check_years=check_years,
                run_years=run_years,
                per_budget=h_bud,
            )
            st["holdout_windows"] = hold.get("windows") or {}
            st["holdout_n_trades"] = int(hold.get("n_trades") or 0)
            st["holdout_n_logs"] = h_ok
            st["holdout_has_coverage"] = bool(h_ok > 0)
            st["corner_oos_pnl"] = hold.get("oos_pnl")
            st["asset_oos_pnl"] = hold.get("is_pnl")
            st["n_logs_ok"] = n_ok + h_ok
            st["n_logs_fail"] = n_fail + h_fail
        samples[name] = st
    rec = {
        "id": str(meta.get("id") or cell_dir.name),
        "label": str(meta.get("label") or cell_dir.name),
        "kind": str(meta.get("kind") or "other"),
        "overrides": meta.get("overrides") or {},
        "is_current": bool(meta.get("is_current")) or str(meta.get("id") or cell_dir.name) == "base",
        "samples": samples,
    }
    if meta.get("n_diffs") is not None:
        rec["n_diffs"] = meta.get("n_diffs")
    return rec


def parse_walk_logs(log_paths: list[Path]) -> tuple[list[dict[str, Any]], int, int, float]:
    trades: list[dict[str, Any]] = []
    n_ok = 0
    n_fail = 0
    budget = float(BUDGET)
    for path in log_paths:
        try:
            _banner, raw = parse_local_bt_log(path)
        except Exception:
            n_fail += 1
            continue
        n_ok += 1
        budget = _walk_budget(path, fallback=budget)
        for t in raw:
            trades.append(dict(t))
    return trades, n_ok, n_fail, float(budget)


def parse_logs(log_paths: list[Path]) -> tuple[list[dict[str, Any]], dict[int, int], int, int, float]:
    """兼容旧测试入口；组合 walk 不再计 n_accounts。"""
    _assert_not_legacy_logs(log_paths)
    trades, n_ok, n_fail, budget = parse_walk_logs(log_paths)
    return trades, {}, n_ok, n_fail, budget


def _is_holdout_log(path: Path) -> bool:
    if path.name.lower().startswith("holdout_"):
        return True
    return "holdout" in [str(p).lower() for p in path.parts]


def _split_walk_logs(sample_dir: Path) -> tuple[list[Path], list[Path]]:
    logs = _list_logs(sample_dir)
    primary: list[Path] = []
    holdout: list[Path] = []
    for path in logs:
        if _is_holdout_log(path):
            holdout.append(path)
        else:
            primary.append(path)
    return primary, holdout


def _list_logs(sample_dir: Path) -> list[Path]:
    if not sample_dir.is_dir():
        return []
    return sorted(
        p
        for p in sample_dir.rglob("*local_bt_book*.txt")
        if p.is_file()
    )


def _load_cell_meta(cell_dir: Path) -> dict[str, Any]:
    meta_p = cell_dir / "cell_meta.json"
    if meta_p.is_file():
        return json.loads(meta_p.read_text(encoding="utf-8"))
    return {"id": cell_dir.name, "label": cell_dir.name, "kind": "other", "overrides": {}}


def _sign(val: float | None, eps: float = EPS_PNL) -> int:
    if val is None:
        return 0
    x = float(val)
    if abs(x) < eps:
        return 0
    return 1 if x > 0 else -1


def _n_override_keys(overrides: Any) -> int:
    if not isinstance(overrides, dict):
        return 0
    return len(overrides)


def _cell_is_current(cell: Mapping[str, Any] | None) -> bool:
    if not cell:
        return False
    if cell.get("is_current"):
        return True
    return str(cell.get("id") or "") == "base"


def _baseline_cell(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    for cell in cells:
        if cell.get("is_current"):
            return cell
    for cell in cells:
        if str(cell.get("id") or "") == "base":
            return cell
    return None


def _cell_n_diffs(cell: Mapping[str, Any]) -> int:
    if _cell_is_current(cell):
        return 0
    if cell.get("n_diffs") is not None:
        try:
            return int(cell.get("n_diffs"))
        except (TypeError, ValueError):
            pass
    return _n_override_keys(cell.get("overrides"))


def _space_on_cells(cells: list[dict[str, Any]]) -> bool:
    for cell in cells:
        book = (cell.get("samples") or {}).get("book") or {}
        if "holdout_has_coverage" in book or "holdout_n_logs" in book:
            return True
    return False


def _win_block(sample: dict[str, Any], period: str, *, windows_key: str = "windows") -> dict[str, Any]:
    block = (sample.get(windows_key) or {}).get(period)
    return block if isinstance(block, dict) else {}


def _num(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _gate_absolute_fails(
    w: dict[str, Any],
    gate: dict[str, Any],
    *,
    prefix: str = "",
) -> list[str]:
    g = fill_gate(gate)
    fails: list[str] = []
    tag = prefix or "验收期"

    def miss(name: str) -> str:
        return "%s缺%s" % (tag, name)

    if g["calmar"]["enabled"]:
        v = _num(w.get("calmar"))
        if v is None:
            fails.append(miss("卡玛"))
        elif v < float(g["calmar"]["min"]) - EPS_GATE:
            fails.append("%s卡玛未达线" % tag)
    if g["max_dd"]["enabled"]:
        v = _num(w.get("max_dd"))
        if v is None:
            fails.append(miss("回撤"))
        elif v < float(g["max_dd"]["floor"]) - EPS_GATE:
            fails.append("%s回撤超限" % tag)
    if g["oos_sharpe"]["enabled"]:
        v = _num(w.get("sharpe"))
        if v is None:
            fails.append(miss("夏普"))
        elif v < float(g["oos_sharpe"]["min"]) - EPS_GATE:
            fails.append("%s夏普未达线" % tag)
    if g["n_trades"]["enabled"]:
        v = _num(w.get("n_trades"))
        if v is None:
            fails.append(miss("笔数"))
        elif v < float(g["n_trades"]["min"]) - EPS_GATE:
            fails.append("%s笔数不足" % tag)
    if g["win_rate"]["enabled"]:
        v = _num(w.get("win_rate"))
        if v is None:
            fails.append(miss("胜率"))
        elif v < float(g["win_rate"]["min"]) - EPS_GATE:
            fails.append("%s胜率未达线" % tag)
    if g["profit_factor"]["enabled"]:
        v = _num(w.get("profit_factor"))
        if v is None:
            fails.append(miss("盈亏比"))
        elif abs(v - 99.0) < 1e-9:
            pass  # 无亏损视为通过绝对线
        elif v < float(g["profit_factor"]["min"]) - EPS_GATE:
            fails.append("%s盈亏比未达线" % tag)
    return fails


def _gate_relative_fails(
    w: dict[str, Any],
    bw: dict[str, Any],
    gate: dict[str, Any],
    *,
    prefix: str = "",
) -> list[str]:
    g = fill_gate(gate)
    if not g["relative_to_base"]:
        return []
    fails: list[str] = []
    tag = prefix or "相对base"

    def worse(name: str) -> str:
        return "%s%s劣于base" % (tag, name)

    def need(name: str) -> str:
        return "%s缺%s无法比base" % (tag, name)

    pairs = (
        ("calmar", "卡玛", True),
        ("max_dd", "回撤", True),  # 更高（更浅）更好
        ("sharpe", "夏普", True),
        ("win_rate", "胜率", True),
        ("profit_factor", "盈亏比", True),
    )
    rule_key = {
        "calmar": "calmar",
        "max_dd": "max_dd",
        "sharpe": "oos_sharpe",
        "win_rate": "win_rate",
        "profit_factor": "profit_factor",
    }
    for field, label, higher_better in pairs:
        rk = rule_key[field]
        if not g[rk]["enabled"]:
            continue
        a = _num(w.get(field))
        b = _num(bw.get(field))
        if a is None or b is None:
            fails.append(need(label))
            continue
        if higher_better and a + EPS_GATE < b:
            fails.append(worse(label))
        elif not higher_better and a - EPS_GATE > b:
            fails.append(worse(label))

    if g["n_trades"]["enabled"]:
        a = _num(w.get("n_trades"))
        b = _num(bw.get("n_trades"))
        if a is None or b is None:
            fails.append(need("笔数"))
        else:
            need_n = float(g["n_trades"]["vs_base_ratio"]) * float(b)
            if a + EPS_GATE < need_n:
                fails.append("%s笔数相对base不足" % tag)
    return fails


def _calmar_delta(w: dict[str, Any], bw: dict[str, Any]) -> float | None:
    a = _num(w.get("calmar"))
    b = _num(bw.get("calmar"))
    if a is None or b is None:
        return None
    return round(a - b, 6)


def _eval_cell_gate(
    book: dict[str, Any],
    base_book: dict[str, Any] | None,
    gate: dict[str, Any],
    *,
    space_on: bool,
) -> list[str]:
    """返回全部失败文案；空列表表示通过。无对照格时跳过相对门 / 卡玛同向。"""
    g = fill_gate(gate)
    w_chk = _win_block(book, "check")
    bw_chk = _win_block(base_book or {}, "check")
    w_tune = _win_block(book, "tune")
    bw_tune = _win_block(base_book or {}, "tune")
    has_baseline = base_book is not None

    fails = _gate_absolute_fails(w_chk, g, prefix="验收期")
    if has_baseline:
        fails.extend(_gate_relative_fails(w_chk, bw_chk, g, prefix=""))

    if has_baseline and g["calmar_same_sign"]:
        d_chk = _calmar_delta(w_chk, bw_chk)
        d_tune = _calmar_delta(w_tune, bw_tune)
        if d_chk is None or d_tune is None:
            fails.append("缺卡玛无法同向")
        elif _sign(d_chk, EPS_GATE) * _sign(d_tune, EPS_GATE) < 0:
            fails.append("调参期与验收期卡玛不同向")

    if space_on:
        cell_cov = bool(book.get("holdout_has_coverage"))
        if not cell_cov:
            fails.append("盲测标的无覆盖")
        else:
            hw = _win_block(book, "check", windows_key="holdout_windows")
            fails.extend(_gate_absolute_fails(hw, g, prefix="盲测"))
            if has_baseline:
                hbw = _win_block(base_book or {}, "check", windows_key="holdout_windows")
                fails.extend(_gate_relative_fails(hw, hbw, g, prefix="盲测"))

    return fails


def pick_recommend(
    cells: list[dict[str, Any]],
    gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    g = validate_gate(gate)
    base = _baseline_cell(cells)
    has_baseline = base is not None

    def sample(cell: dict[str, Any], name: str) -> dict[str, Any]:
        return (cell.get("samples") or {}).get(name) or {}

    bb = sample(base, "book") if base is not None else {}
    space_on = _space_on_cells(cells)
    rank_warn = False

    passers: list[tuple[dict[str, Any], float, int]] = []
    notes: list[dict[str, Any]] = []

    for cell in cells:
        b = sample(cell, "book")
        w_chk = _win_block(b, "check")
        bw_chk = _win_block(bb, "check") if has_baseline else {}
        calmar = _num(w_chk.get("calmar"))
        oos = float(b.get("oos_pnl") or 0)
        d_calmar = _calmar_delta(w_chk, bw_chk) if has_baseline else None
        d_oos = round(oos - float(bb.get("oos_pnl") or 0), 2) if has_baseline else None
        d_is = (
            round(float(b.get("is_pnl") or 0) - float(bb.get("is_pnl") or 0), 2)
            if has_baseline
            else None
        )
        fails = _eval_cell_gate(
            b,
            bb if has_baseline else None,
            g,
            space_on=space_on,
        )
        fail_text = "；".join(fails) if fails else None
        row = {
            "id": cell["id"],
            "kind": cell.get("kind"),
            "calmar": calmar,
            "d_calmar": d_calmar,
            "d_oos": d_oos,
            "d_is": d_is,
            "d_corner": None
            if not (space_on and has_baseline)
            else round(
                float(b.get("corner_oos_pnl") or 0) - float(bb.get("corner_oos_pnl") or 0),
                2,
            ),
            "fail": fail_text,
            "fails": fails or None,
        }
        notes.append(row)
        if not fails:
            if calmar is None:
                rank_warn = True
                score = oos
            else:
                score = float(calmar)
            passers.append((cell, float(score), _cell_n_diffs(cell)))

    def _kind_score(n: dict[str, Any]) -> float:
        if n.get("calmar") is not None:
            return float(n["calmar"])
        if n.get("d_calmar") is not None:
            return float(n["d_calmar"])
        return float(n.get("d_oos") or 0)

    by_kind: dict[str, Any] = {}
    for kind in ("tighten", "loosen", "off", "other"):
        opts = [n for n in notes if n.get("kind") == kind]
        if not opts:
            continue
        best = max(opts, key=_kind_score)
        by_kind[kind] = best

    if not passers:
        reason = "无格子过门"
        if space_on and any(n.get("fail") and "盲测" in str(n.get("fail")) for n in notes):
            reason = "盲测未通过或未过门"
        return {
            "id": None,
            "label": None,
            "kind": None,
            "reason": reason,
            "candidates": notes,
            "by_kind": by_kind,
            "gate": gate_for_json(g),
        }

    best_score = max(p[1] for p in passers)
    pad = max(0.05, 0.2 * abs(best_score))
    close = [p for p in passers if p[1] >= best_score - pad]
    close.sort(key=lambda p: (p[2], -p[1]))
    picked = close[0][0]
    reason = "过门后按验收期卡玛排序；接近则少改结构"
    if rank_warn:
        reason = "WARN 缺卡玛回落验收盈亏；过门后接近则少改结构"
    if space_on and not rank_warn:
        reason = "过门且盲测未否决；按验收期卡玛排序，接近则少改结构"
    return {
        "id": picked["id"],
        "label": picked.get("label") or picked["id"],
        "kind": picked.get("kind"),
        "reason": reason,
        "candidates": notes,
        "by_kind": by_kind,
        "gate": gate_for_json(g),
    }


def attach_deltas(cells: list[dict[str, Any]]) -> None:
    base = _baseline_cell(cells)
    if base is None:
        return
    for cell in cells:
        deltas: dict[str, Any] = {}
        for name in SAMPLES:
            deltas[name] = _delta_stats(
                (cell.get("samples") or {}).get(name) or {},
                (base.get("samples") or {}).get(name) or {},
            )
        cell["delta_vs_base"] = deltas


def _load_spec_json(root: Path) -> dict[str, Any]:
    spec_p = root / "spec.json"
    if not spec_p.is_file():
        return {}
    try:
        data = json.loads(spec_p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def spec_cell_ids(spec: Any) -> set[str] | None:
    """spec.cells 有 id 则返回白名单；缺字段则不过滤（兼容旧 sweep）。"""
    if not isinstance(spec, dict):
        return None
    raw = spec.get("cells")
    if not isinstance(raw, list) or not raw:
        return None
    ids = {
        str(c.get("id") or "").strip()
        for c in raw
        if isinstance(c, dict) and str(c.get("id") or "").strip()
    }
    return ids or None


def _wanted_cell_ids(
    spec: dict[str, Any],
    cell_ids: Iterable[str] | None,
) -> set[str] | None:
    if cell_ids is not None:
        want = {str(x).strip() for x in cell_ids if str(x).strip()}
        return want or None
    return spec_cell_ids(spec)


def _load_sweep_windows(root: Path) -> dict[str, int]:
    for name in ("spec.json", "freeze.json"):
        path = root / name
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            return fill_year_windows(data)
    return fill_year_windows(None)


def _has_book_walk_logs(root: Path) -> bool:
    return any(p.is_file() for p in root.rglob("*local_bt_book*.txt"))


def legacy_sweep_reason(root: Path) -> str | None:
    """旧 stock×年 产物则返回须重跑文案。"""
    freeze_p = root / "freeze.json"
    if freeze_p.is_file():
        try:
            data = json.loads(freeze_p.read_text(encoding="utf-8"))
        except Exception:
            data = None
        if isinstance(data, dict):
            book = data.get("book")
            if isinstance(book, list) and book and isinstance(book[0], dict):
                row = book[0]
                if "year" in row and "basket" not in row:
                    return "该 sweep 是旧 stock×年 口径，须重跑网格后才能汇总。"
    if _has_book_walk_logs(root):
        return None
    logs = list(root.rglob("local_bt_*.txt"))
    try:
        _assert_not_legacy_logs(logs)
    except GridSummarizeError as e:
        return str(e)
    return None


def summarize_sweep(
    sweep_dir: str | Path,
    gate: dict[str, Any] | None = None,
    cell_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    root = Path(sweep_dir)
    if not root.is_dir():
        raise FileNotFoundError("sweep dir not found: %s" % root)
    why = legacy_sweep_reason(root)
    if why:
        raise GridSummarizeError(why)
    win = _load_sweep_windows(root)
    tune = year_range_set(win["tune_start"], win["tune_end"])
    check = year_range_set(win["check_start"], win["check_end"])
    run = year_range_set(win["year_start"], win["year_end"])
    tune_stocks, holdout_stocks = _load_asset_lists(root)
    gate_used = load_gate_from_sweep(root, override=gate)
    spec = _load_spec_json(root)
    want = _wanted_cell_ids(spec, cell_ids)
    cells: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if want is not None and child.name not in want:
            continue
        if not (child / "cell_meta.json").is_file() and not any(
            (child / s).is_dir() for s in SAMPLES
        ):
            continue
        cells.append(
            summarize_cell(
                child,
                tune_years=tune,
                check_years=check,
                run_years=run,
                tune_stocks=tune_stocks,
                holdout_stocks=holdout_stocks,
            )
        )
    attach_deltas(cells)
    rec = pick_recommend(cells, gate=gate_used)
    out = {
        "sweep": str(spec.get("sweep") or root.name),
        "sweep_dir": str(root),
        "n_cells": len(cells),
        "cells": cells,
        "recommend": rec,
        "gate": gate_for_json(gate_used),
        "note": "MAE 反事实不得写入推荐；默认不改 config / 不 deploy",
    }
    if tune_stocks or holdout_stocks:
        out["asset_split"] = {
            "tune_stocks": list(tune_stocks or []),
            "holdout_stocks": list(holdout_stocks or []),
        }
    for key in YEAR_WINDOW_KEYS:
        out[key] = int(win[key])
    out_p = root / "summary.json"
    out_p.write_text(
        json.dumps(_json_ready(out), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    out["summary_path"] = str(out_p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="local_bt 网格 summarize")
    ap.add_argument("--sweep-dir", required=True, help="report/grid/<sweep> 目录")
    ap.add_argument(
        "--gate-json",
        default="",
        help="覆盖过门配置 JSON 文件或内联 JSON 对象",
    )
    args = ap.parse_args()
    gate_override = None
    raw_gate = str(args.gate_json or "").strip()
    if raw_gate:
        p = Path(raw_gate)
        if p.is_file():
            gate_override = json.loads(p.read_text(encoding="utf-8"))
        else:
            gate_override = json.loads(raw_gate)
    out = summarize_sweep(args.sweep_dir, gate=gate_override)
    rec = out.get("recommend") or {}
    print("wrote", out.get("summary_path"))
    print("recommend", rec.get("id"), rec.get("reason"))


if __name__ == "__main__":
    main()
