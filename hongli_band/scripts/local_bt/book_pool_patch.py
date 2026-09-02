# coding: utf-8
"""local_bt 组合回测：全池 BOOK 槽位/分档（跨标的汇总 hot state）。"""
from __future__ import annotations

from typing import Any


def _norm_code(ns: dict[str, Any], code: str) -> str:
    fn = ns.get("_norm_code")
    if callable(fn):
        return str(fn(code or "")).strip().upper()
    return str(code or "").strip().upper()


def _lot_rows_from_lots(ns: dict[str, Any], lots: list | None) -> list[dict]:
    out: list[dict] = []
    fn = ns.get("_lot_row_from_dict")
    if not callable(fn):
        return out
    for lot in lots or []:
        if isinstance(lot, dict):
            row = fn(lot)
            if row:
                out.append(row)
    return out


def _lot_rows_from_position(ns: dict[str, Any], pos: dict | None) -> list[dict]:
    if not isinstance(pos, dict):
        return []
    try:
        vol = int(pos.get("shares") or 0)
        px = float(pos.get("price") or 0)
    except (TypeError, ValueError):
        return []
    if vol < 100 or px <= 0:
        return []
    raw_frac = pos.get("book_frac")
    return [{"id": 1, "mv": float(vol) * float(px), "frac": raw_frac, "shares": vol}]


def _rows_for_stock(ns: dict[str, Any], stock: str) -> list[dict]:
    a = ns.get("A")
    st = _norm_code(ns, stock)
    if not st or a is None:
        return []
    cur = _norm_code(ns, getattr(a, "stock", ""))
    if st == cur:
        rows = _lot_rows_from_lots(ns, getattr(a, "lots", None))
        if rows:
            return rows
        has_pos = ns.get("_has_position")
        if callable(has_pos) and has_pos():
            return _lot_rows_from_position(ns, getattr(a, "position", None))
        bt_vol = ns.get("_bt_held_vol")
        if callable(bt_vol) and int(bt_vol() or 0) >= 100:
            return _lot_rows_from_position(ns, getattr(a, "position", None))
        return []
    fn = ns.get("_per_stock_map")
    mp = fn() if callable(fn) else {}
    rec = mp.get(stock) or mp.get(st) or {}
    if not isinstance(rec, dict):
        return []
    rows = _lot_rows_from_lots(ns, rec.get("_hot_lots"))
    if rows:
        return rows
    return _lot_rows_from_position(ns, rec.get("_hot_position"))


def collect_bt_book_lot_rows(ns: dict[str, Any]) -> dict[str, list[dict]]:
    """回测：BOOK_STOCKS + 当前图 + universe hot → {stock: [lot_row]}。"""
    book = ns.get("BOOK_STOCKS") or {}
    codes: set[str] = set()
    for raw in book.keys():
        st = _norm_code(ns, raw)
        if st:
            codes.add(st)
    a = ns.get("A")
    if a is not None:
        cur = _norm_code(ns, getattr(a, "stock", ""))
        if cur:
            codes.add(cur)
    fn = ns.get("_per_stock_map")
    if callable(fn):
        for raw in (fn() or {}).keys():
            st = _norm_code(ns, raw)
            if st:
                codes.add(st)
    in_book = ns.get("_code_in_book")
    rows_by: dict[str, list[dict]] = {}
    for st in sorted(codes):
        if callable(in_book) and not in_book(st):
            continue
        rows = _rows_for_stock(ns, st)
        if rows:
            rows_by[st] = rows
    return rows_by


def chart_next_frac_from_rows(ns: dict[str, Any], rows_by: dict[str, list[dict]], opening: bool) -> float:
    """与 hlband budget._chart_next_frac 相同，但 rows_by 已由调用方全池汇总。"""
    opening = bool(opening)
    sleeve = float(ns["_trade_budget_cap"]() or 0)
    finalize = ns["_finalize_lot_fracs"]
    occupied_fn = ns["_occupied_fracs"]
    vacant_fn = ns["_vacant_slots"]
    cfg_max = ns["_cfg_book_lot_max"]
    cfg_open = ns["_cfg_lot_open_frac"]
    cfg_add = ns["_cfg_lot_add_frac"]
    vacant_has_big = ns["_vacant_has_big"]
    vacant_has_small = ns["_vacant_has_small"]
    remainder = ns["_remainder_frac"]

    finalized = finalize(rows_by, sleeve)
    occupied = occupied_fn(finalized)
    vacant = vacant_fn(occupied)
    n_held = len(occupied)
    slots_left = int(cfg_max()) - n_held
    if slots_left <= 0:
        return 0.0
    if (not opening) and vacant_has_big(vacant) and slots_left <= 1:
        return 0.0
    if slots_left <= 1:
        return float(remainder(occupied))
    if opening:
        if vacant_has_big(vacant):
            return float(cfg_open())
        if vacant_has_small(vacant):
            return float(cfg_add())
        return 0.0
    if vacant_has_small(vacant):
        return float(cfg_add())
    return 0.0


def install_book_pool_patch(ns: dict[str, Any]) -> None:
    """回测时 _chart_next_frac / _book_n_held_live 按全池 hot 汇总。"""
    if ns.get("_local_bt_book_pool_installed"):
        return
    orig_frac = ns["_chart_next_frac"]
    orig_n_held = ns["_book_n_held_live"]

    def _chart_next_frac_pool(opening):
        a = ns.get("A")
        if not getattr(a, "is_backtest", False):
            return orig_frac(opening)
        rows_by = collect_bt_book_lot_rows(ns)
        return chart_next_frac_from_rows(ns, rows_by, opening)

    def _book_n_held_pool(held=None):
        a = ns.get("A")
        if getattr(a, "is_backtest", False):
            rows_by = collect_bt_book_lot_rows(ns)
            return int(sum(len(v or []) for v in rows_by.values()))
        return orig_n_held(held)

    ns["_chart_next_frac_orig_local_bt"] = orig_frac
    ns["_chart_next_frac"] = _chart_next_frac_pool
    ns["_book_n_held_live"] = _book_n_held_pool
    ns["_local_bt_book_pool_installed"] = True
