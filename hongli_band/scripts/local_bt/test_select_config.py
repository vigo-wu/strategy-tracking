# coding: utf-8
"""选股侧栏配置：默认值落在控件范围内，字段与打分器对齐。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from select_config import (
    DEFAULT_FILTERS,
    FILTER_BY_KEY,
    FILTER_WIDGETS,
    WEIGHTS,
    widget_kwargs,
    year_max_for_window,
)


class SelectConfigTest(unittest.TestCase):
    def test_filter_keys_unique_and_match_defaults(self) -> None:
        keys = [w["key"] for w in FILTER_WIDGETS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(DEFAULT_FILTERS), set(keys))
        self.assertEqual(
            set(DEFAULT_FILTERS),
            {
                "min_n_buy",
                "min_n_buy_per_year",
                "min_years_traded",
                "min_pos_years",
                "min_pos_ratio",
                "max_win_pnl_share",
                "vol_drop_top",
                "top_n",
            },
        )

    def test_defaults_inside_static_bounds(self) -> None:
        for spec in FILTER_WIDGETS:
            lo = spec["min_value"]
            hi = spec["max_value"]
            val = spec["default"]
            self.assertGreaterEqual(val, lo, spec["key"])
            self.assertLessEqual(val, hi, spec["key"])

    def test_year_max_widget_kwargs_clamp(self) -> None:
        self.assertEqual(year_max_for_window(2), 5)
        self.assertEqual(year_max_for_window(8), 8)
        spec = FILTER_BY_KEY["min_years_traded"]
        kw = widget_kwargs(spec, year_max=5)
        self.assertEqual(kw["max_value"], 5)
        self.assertEqual(kw["value"], 2)
        kw = widget_kwargs(spec, year_max=1)
        self.assertEqual(kw["max_value"], 1)
        self.assertEqual(kw["value"], 1)

    def test_weights_sum_to_one(self) -> None:
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0, places=6)
        self.assertEqual(
            set(WEIGHTS),
            {"pnl", "win_rate", "stability", "profit_factor", "quality"},
        )


if __name__ == "__main__":
    unittest.main()
