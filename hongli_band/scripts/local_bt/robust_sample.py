# coding: utf-8
"""实盘评估：从合格池随机抽 N 组篮子。"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Mapping, Sequence

from asset_split import list_eligible_stocks
from robust_spec import RobustSpecError, fill_sampling


def draw_baskets(
    eligible: Sequence[str],
    *,
    n_baskets: int,
    basket_size: int,
    seed: int,
) -> list[list[str]]:
    pool = sorted({str(s).strip().upper() for s in eligible if str(s).strip()})
    n = max(1, int(n_baskets))
    k = max(1, int(basket_size))
    if len(pool) < k:
        raise RobustSpecError("合格池 %s 只 < basket_size %s" % (len(pool), k))
    rng = random.Random(int(seed))
    out: list[list[str]] = []
    for _ in range(n):
        out.append(sorted(rng.sample(pool, k)))
    return out


def mean_pairwise_jaccard(baskets: Sequence[Sequence[str]]) -> float | None:
    sets = [set(b) for b in baskets if b]
    if len(sets) < 2:
        return None
    total = 0.0
    n = 0
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            u = sets[i] | sets[j]
            if not u:
                continue
            total += len(sets[i] & sets[j]) / float(len(u))
            n += 1
    if n <= 0:
        return None
    return round(total / n, 4)


def sample_baskets_for_spec(
    spec: Mapping[str, Any],
    *,
    reshuffle: bool = False,
    freeze: Mapping[str, Any] | None = None,
    eligible: list[str] | None = None,
) -> dict[str, Any]:
    sampling = fill_sampling(spec)
    n, k, seed = sampling["n_baskets"], sampling["basket_size"], sampling["seed"]
    uni = sampling["universe_dir"]

    frozen = None
    if not reshuffle and isinstance(freeze, Mapping):
        raw = freeze.get("baskets")
        if isinstance(raw, list) and raw:
            frozen = []
            for row in raw:
                if isinstance(row, Mapping) and row.get("stocks"):
                    stocks = [str(x).strip().upper() for x in row["stocks"] if str(x).strip()]
                elif isinstance(row, (list, tuple)):
                    stocks = [str(x).strip().upper() for x in row if str(x).strip()]
                else:
                    continue
                if stocks:
                    frozen.append(sorted(set(stocks)))
            if frozen and any(len(b) != k for b in frozen):
                frozen = None
            if frozen and len(frozen) != n:
                # allow freeze n to win if reshuffle off
                n = len(frozen)
                sampling["n_baskets"] = n

    if eligible is None:
        eligible = list_eligible_stocks(
            uni,
            year_start=int(spec.get("year_start") or 2018),
            year_end=int(spec.get("year_end") or 2026),
        )
    if frozen:
        baskets = frozen
    else:
        baskets = draw_baskets(eligible, n_baskets=n, basket_size=k, seed=seed)

    rows = [{"id": "basket_%03d" % (i + 1), "stocks": b} for i, b in enumerate(baskets)]
    return {
        "universe_dir": uni,
        "n_baskets": len(rows),
        "basket_size": k,
        "seed": seed,
        "eligible_n": len(eligible),
        "baskets": rows,
        "mean_jaccard": mean_pairwise_jaccard([r["stocks"] for r in rows]),
    }


def write_freeze(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_freeze(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None
