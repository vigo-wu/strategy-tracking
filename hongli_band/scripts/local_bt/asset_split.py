# coding: utf-8
"""网格空间隔离：从 tools/csv/none 合格池随机抽取 tune / holdout（互不重叠）。"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Mapping

from analyze import (
    DEFAULT_CSV_ROOT,
    DEFAULT_DIVIDEND_TYPE,
    daily_csvs_by_stock,
    normalize_dividend_type,
    normalize_ma_type,
    resolve_typed_dir,
)
from grid_spec import fill_year_windows
from market_csv import compact_day

REPO = Path(__file__).resolve().parents[3]
DEFAULT_UNIVERSE_DIR = "tools/csv/none"
DEFAULT_N_TUNE = 20
DEFAULT_N_HOLDOUT = 20
DEFAULT_SEED = 42
ASSET_MODES = ("off", "random_from_csv")


class AssetSplitError(ValueError):
    """空间隔离 spec / 抽取错误。"""


def resolve_universe_dir(raw: str | Path | None = None) -> Path:
    """相对仓库根或绝对路径；已是 none 叶子则不再拼接。"""
    if raw is None or str(raw).strip() == "":
        p = REPO / DEFAULT_UNIVERSE_DIR
    else:
        p = Path(str(raw))
        if not p.is_absolute():
            p = REPO / p
    p = p.resolve()
    if p.name == "none":
        return p
    typed = resolve_typed_dir(p, "none")
    return typed


def _year_window(year: int) -> tuple[str, str]:
    y = int(year)
    return "%s0101" % y, "%s1231" % y


def _span_overlaps(span: tuple[str, str] | None, start: str, end: str) -> bool:
    if span is None:
        return False
    return max(str(start), span[0]) <= min(str(end), span[1])


def _meta_span(meta: Mapping[str, Any]) -> tuple[str, str] | None:
    ms = compact_day(str(meta.get("start") or ""))
    me = compact_day(str(meta.get("end") or ""))
    if len(ms) == 8 and len(me) == 8:
        return ms, me
    return None


def list_eligible_stocks(
    universe_dir: str | Path | None = None,
    year_start: int = 2018,
    year_end: int = 2026,
    *,
    exclude: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    """合格池：日线存在且与 [year_start, year_end] 至少一年有交集。"""
    data_dir = resolve_universe_dir(universe_dir)
    ban = {str(x).strip().upper() for x in (exclude or []) if str(x).strip()}
    y0, y1 = int(year_start), int(year_end)
    out: list[str] = []
    try:
        rows = daily_csvs_by_stock(data_dir)
    except Exception as e:
        raise AssetSplitError("无法枚举宇宙 %s: %s" % (data_dir, e)) from e
    for meta in rows:
        stock = str(meta.get("stock") or "").strip().upper()
        if not stock or stock in ban:
            continue
        span = _meta_span(meta)
        ok = False
        for year in range(y0, y1 + 1):
            ys, ye = _year_window(year)
            if _span_overlaps(span, ys, ye):
                ok = True
                break
        if ok:
            out.append(stock)
    return sorted(set(out))


def _norm_stock_list(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        parts = [p.strip().upper() for p in raw.replace(",", " ").split()]
        return sorted({p for p in parts if p})
    out: list[str] = []
    for x in raw:
        s = str(x or "").strip().upper()
        if s:
            out.append(s)
    return sorted(set(out))


def _opt_int(block: Mapping[str, Any], key: str) -> int | None:
    if key not in block or block.get(key) is None:
        return None
    try:
        return int(block.get(key))
    except (TypeError, ValueError):
        return None


def _counts_from_block(block: Mapping[str, Any]) -> tuple[int, int]:
    """n 同时填两篮；只填一侧则另一侧同值；两侧都有则保持（旧 freeze 可不等）。"""
    n_one = _opt_int(block, "n")
    n_tune_raw = _opt_int(block, "n_tune")
    n_hold_raw = _opt_int(block, "n_holdout")
    if n_one is not None:
        n = max(0, n_one)
        return n, n
    if n_tune_raw is not None and n_hold_raw is not None:
        return max(0, n_tune_raw), max(0, n_hold_raw)
    if n_tune_raw is not None:
        n = max(0, n_tune_raw)
        return n, n
    if n_hold_raw is not None:
        n = max(0, n_hold_raw)
        return n, n
    return DEFAULT_N_TUNE, DEFAULT_N_HOLDOUT


def fill_asset_split(spec: Mapping[str, Any] | None) -> dict[str, Any]:
    """缺字段回落默认；不抽名单。无 seed 则为 None（抽取用系统随机）。"""
    src = spec if isinstance(spec, Mapping) else {}
    raw = src.get("asset_split")
    block: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    mode = str(block.get("mode") or "off").strip().lower() or "off"
    if mode not in ASSET_MODES:
        mode = "off"
    compare = (
        normalize_dividend_type(src.get("compare_div"))
        or normalize_dividend_type(block.get("dividend_type"))
        or DEFAULT_DIVIDEND_TYPE
    )
    ma = normalize_ma_type(block.get("ma_type")) or "EMA"
    div = normalize_dividend_type(block.get("dividend_type")) or compare
    n_tune, n_holdout = _counts_from_block(block)
    seed = _opt_int(block, "seed")
    uni = str(block.get("universe_dir") or DEFAULT_UNIVERSE_DIR).strip() or DEFAULT_UNIVERSE_DIR
    exclude = _norm_stock_list(block.get("exclude"))
    out: dict[str, Any] = {
        "mode": mode,
        "universe_dir": uni,
        "n_tune": n_tune,
        "n_holdout": n_holdout,
        "seed": seed,
        "ma_type": ma,
        "dividend_type": div,
        "exclude": exclude,
        "tune_stocks": _norm_stock_list(block.get("tune_stocks")),
        "holdout_stocks": _norm_stock_list(block.get("holdout_stocks")),
        "eligible_n": int(block.get("eligible_n") or 0),
    }
    if n_tune == n_holdout:
        out["n"] = n_tune
    return out


def validate_asset_split(split: Mapping[str, Any]) -> dict[str, Any]:
    filled = fill_asset_split({"asset_split": split})
    if filled["mode"] == "off":
        return filled
    if filled["n_tune"] < 1:
        raise AssetSplitError("n_tune 须 ≥ 1")
    if filled["n_holdout"] < 1:
        raise AssetSplitError("n_holdout 须 ≥ 1")
    tune = list(filled["tune_stocks"])
    holdout = list(filled["holdout_stocks"])
    if tune or holdout:
        if not tune:
            raise AssetSplitError("tune_stocks 为空")
        if not holdout:
            raise AssetSplitError("holdout_stocks 为空")
        inter = set(tune) & set(holdout)
        if inter:
            raise AssetSplitError("tune 与 holdout 相交: %s" % ",".join(sorted(inter)[:8]))
        if len(tune) != len(set(tune)) or len(holdout) != len(set(holdout)):
            raise AssetSplitError("名单内部有重复")
    return filled


def _lists_from_freeze(freeze: Mapping[str, Any] | None) -> tuple[list[str], list[str]] | None:
    if not isinstance(freeze, Mapping):
        return None
    # freeze 顶层或 asset_split 子块
    block = freeze.get("asset_split") if isinstance(freeze.get("asset_split"), Mapping) else freeze
    tune = _norm_stock_list(block.get("tune_stocks"))
    holdout = _norm_stock_list(block.get("holdout_stocks"))
    if tune and holdout:
        return tune, holdout
    return None


def draw_asset_split(
    spec: Mapping[str, Any] | None,
    *,
    reshuffle: bool = False,
    freeze: Mapping[str, Any] | None = None,
    eligible: list[str] | None = None,
) -> dict[str, Any]:
    """抽取或复用名单；写回完整 asset_split 块（含最终名单）。"""
    win = fill_year_windows(spec)
    filled = fill_asset_split(spec)
    if filled["mode"] == "off":
        out = dict(filled)
        out["tune_stocks"] = []
        out["holdout_stocks"] = []
        out["eligible_n"] = 0
        return out

    if not reshuffle:
        reused = _lists_from_freeze(freeze)
        if reused is None and filled["tune_stocks"] and filled["holdout_stocks"]:
            reused = (filled["tune_stocks"], filled["holdout_stocks"])
        if reused is not None:
            tune, holdout = reused
            inter = set(tune) & set(holdout)
            if inter:
                raise AssetSplitError("复用名单 tune/holdout 相交")
            out = dict(filled)
            out["tune_stocks"] = list(tune)
            out["holdout_stocks"] = list(holdout)
            out["n_tune"] = len(tune)
            out["n_holdout"] = len(holdout)
            if out["n_tune"] == out["n_holdout"]:
                out["n"] = out["n_tune"]
            else:
                out.pop("n", None)
            if eligible is not None:
                out["eligible_n"] = len(eligible)
            elif out.get("eligible_n"):
                pass
            else:
                out["eligible_n"] = len(tune) + len(holdout)
            return validate_asset_split(out)

    pool = list(eligible) if eligible is not None else list_eligible_stocks(
        filled["universe_dir"],
        win["year_start"],
        win["year_end"],
        exclude=filled["exclude"],
    )
    need = int(filled["n_tune"]) + int(filled["n_holdout"])
    if need > len(pool):
        raise AssetSplitError(
            "合格池 %s 只，不足 n_tune(%s)+n_holdout(%s)=%s"
            % (len(pool), filled["n_tune"], filled["n_holdout"], need)
        )
    raw_seed = filled.get("seed")
    rng = random.Random() if raw_seed is None else random.Random(int(raw_seed))
    shuf = list(pool)
    rng.shuffle(shuf)
    n_t = int(filled["n_tune"])
    n_h = int(filled["n_holdout"])
    tune = sorted(shuf[:n_t])
    holdout = sorted(shuf[n_t : n_t + n_h])
    out = dict(filled)
    out["tune_stocks"] = tune
    out["holdout_stocks"] = holdout
    out["eligible_n"] = len(pool)
    if n_t == n_h:
        out["n"] = n_t
    else:
        out.pop("n", None)
    return validate_asset_split(out)


def stock_lock_rows(split: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """[(stock, ma, div), ...] tune∪holdout，保序：tune 再 holdout。"""
    filled = fill_asset_split({"asset_split": split})
    ma = str(filled["ma_type"])
    div = str(filled["dividend_type"])
    seen: set[str] = set()
    rows: list[tuple[str, str, str]] = []
    for stock in list(filled["tune_stocks"]) + list(filled["holdout_stocks"]):
        if stock in seen:
            continue
        seen.add(stock)
        rows.append((stock, ma, div))
    return rows


def default_csv_root_for_jobs() -> Path:
    """建 job 仍用 DEFAULT_CSV_ROOT（csv_for），与枚举宇宙解耦。"""
    return Path(DEFAULT_CSV_ROOT)
