# coding: utf-8
"""滚动选股资格：扫描宇宙内、上市满 N 年、打分窗日均成交额分位。无 ST。"""
from __future__ import annotations

from typing import Any, Iterable

from market_csv import compact_day, load_daily_csv
from select_config import SELECT_AMOUNT_DROP_BOTTOM, SELECT_LISTING_MIN_YEARS


def listing_year_from_meta(meta: dict[str, Any] | None) -> int | None:
    if not meta:
        return None
    start = compact_day(str(meta.get("start") or ""))
    if len(start) >= 4 and start[:4].isdigit():
        return int(start[:4])
    return None


def mean_amount_in_years(path: str, years: Iterable[str]) -> float | None:
    keep = {str(y) for y in years if str(y).isdigit()}
    if not keep or not path:
        return None
    try:
        _code, bars = load_daily_csv(path)
    except Exception:
        return None
    vals: list[float] = []
    for b in bars:
        try:
            if float(b.close) <= 0:
                continue
            day = compact_day(str(b.day or ""))
            if len(day) < 4 or day[:4] not in keep:
                continue
            amt = float(b.amount or 0.0)
        except (TypeError, ValueError):
            continue
        if amt > 0:
            vals.append(amt)
    if not vals:
        return None
    return float(sum(vals) / len(vals))


def qualify_stocks(
    stocks: Iterable[str],
    *,
    select_year: int,
    score_years: tuple[str, ...],
    csv_meta_by_stock: dict[str, dict[str, Any]] | None = None,
    listing_min_years: int = SELECT_LISTING_MIN_YEARS,
    amount_drop_bottom: float = SELECT_AMOUNT_DROP_BOTTOM,
    amount_by_stock: dict[str, float] | None = None,
) -> dict[str, Any]:
    """截面资格。成交额分位只在 score_years 内计算，不用全样本。"""
    names = [str(s).strip().upper() for s in stocks if str(s).strip()]
    metas = csv_meta_by_stock or {}
    reasons: dict[str, str] = {}
    listing_ok: list[str] = []
    n_no_listing = 0
    min_list_year = int(select_year) - max(int(listing_min_years), 0)
    for stock in names:
        meta = metas.get(stock) or metas.get(stock.replace(".", "_")) or {}
        ly = listing_year_from_meta(meta)
        if ly is None:
            reasons[stock] = "无日线上市日"
            n_no_listing += 1
            continue
        if ly > min_list_year:
            reasons[stock] = "上市未满 %s 年" % listing_min_years
            continue
        listing_ok.append(stock)

    amounts: dict[str, float] = {}
    injected = amount_by_stock or {}
    for stock in listing_ok:
        if stock in injected:
            try:
                val = float(injected[stock])
            except (TypeError, ValueError):
                val = 0.0
            if val > 0:
                amounts[stock] = val
            else:
                reasons[stock] = "打分窗无成交额"
            continue
        meta = metas.get(stock) or {}
        path = str(meta.get("path") or "")
        mean_amt = mean_amount_in_years(path, score_years)
        if mean_amt is None or mean_amt <= 0:
            reasons[stock] = "打分窗无成交额"
            continue
        amounts[stock] = mean_amt

    drop = min(max(float(amount_drop_bottom or 0.0), 0.0), 0.5)
    amount_cut = None
    eligible: list[str] = []
    amt_vals = [float(v) for v in amounts.values()]
    if amt_vals and drop > 0 and len(amt_vals) >= 2:
        ordered = sorted(amt_vals)
        k = drop * (len(ordered) - 1)
        lo = int(k)
        hi = min(lo + 1, len(ordered) - 1)
        frac = k - lo
        amount_cut = float(ordered[lo] * (1.0 - frac) + ordered[hi] * frac)
        for stock in listing_ok:
            if stock in reasons:
                continue
            amt = amounts.get(stock)
            if amt is None:
                continue
            if amt < amount_cut:
                reasons[stock] = "成交额分位过低"
                continue
            eligible.append(stock)
    else:
        eligible = [s for s in listing_ok if s not in reasons]

    return {
        "eligible": set(eligible),
        "reasons": reasons,
        "amount_cut": amount_cut,
        "n_listing_ok": len(listing_ok),
        "n_no_listing": n_no_listing,
        "n_eligible": len(eligible),
        "select_year": int(select_year),
        "score_years": list(score_years),
        "listing_min_years": int(listing_min_years),
        "amount_drop_bottom": drop,
    }
