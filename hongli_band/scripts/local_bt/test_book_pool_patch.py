# coding: utf-8
import unittest
from types import SimpleNamespace

from book_pool_patch import chart_next_frac_from_rows, collect_bt_book_lot_rows


def _mock_ns():
    return {
        "A": SimpleNamespace(stock="600350.SH", lots=[], position=None, is_backtest=True),
        "_norm_code": lambda c: str(c or "").strip().upper(),
        "_lot_row_from_dict": lambda lot: {
            "id": int(lot.get("id") or 1),
            "mv": float(lot.get("shares", 0)) * float(lot.get("price", 0)),
            "frac": lot.get("book_frac"),
            "shares": int(lot.get("shares") or 0),
        }
        if int(lot.get("shares") or 0) >= 100
        else None,
        "_has_position": lambda: False,
        "_bt_held_vol": lambda: 0,
        "_per_stock_map": lambda: {
            "601988.SH": {
                "_hot_lots": [{"id": 1, "shares": 13300, "price": 3.59, "book_frac": 0.5}],
                "_hot_position": None,
            }
        },
        "BOOK_STOCKS": {"601988.SH": {}, "600350.SH": {}},
        "_code_in_book": lambda _c: True,
        "_trade_budget_cap": lambda: 96036.13,
        "_finalize_lot_fracs": lambda rows_by, cap: rows_by,
        "_occupied_fracs": lambda rows_by: [
            float(r.get("frac") or 0.5) for rows in (rows_by or {}).values() for r in (rows or [])
        ],
        "_vacant_slots": lambda occupied: [0.3, 0.2] if occupied else [0.5, 0.3, 0.2],
        "_cfg_book_lot_max": lambda: 3,
        "_cfg_lot_open_frac": lambda: 0.5,
        "_cfg_lot_add_frac": lambda: 0.3,
        "_vacant_has_big": lambda vacant: any(abs(v - 0.5) < 0.02 for v in (vacant or [])),
        "_vacant_has_small": lambda vacant: any(abs(v - 0.5) >= 0.02 for v in (vacant or [])),
        "_remainder_frac": lambda occupied: max(0.0, 1.0 - sum(occupied or [])),
    }


class BookPoolPatchTests(unittest.TestCase):
    def test_collect_includes_hot_other_stock(self):
        ns = _mock_ns()
        rows = collect_bt_book_lot_rows(ns)
        self.assertIn("601988.SH", rows)
        self.assertEqual(len(rows["601988.SH"]), 1)

    def test_second_open_uses_add_frac_when_big_taken(self):
        ns = _mock_ns()
        rows = collect_bt_book_lot_rows(ns)
        frac = chart_next_frac_from_rows(ns, rows, opening=True)
        self.assertAlmostEqual(frac, 0.3)


if __name__ == "__main__":
    unittest.main()
