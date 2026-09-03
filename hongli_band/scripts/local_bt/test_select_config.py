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
    basket_from_import_text,
    clamp_top_n,
    coerce_book_stocks_dict,
    is_year_keyed_baskets,
    parse_book_stocks_text,
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

    def test_clamp_top_n_matches_sidebar_max(self) -> None:
        hi = int(FILTER_BY_KEY["top_n"]["max_value"])
        self.assertEqual(clamp_top_n(10), hi)
        self.assertEqual(clamp_top_n(hi), hi)
        self.assertEqual(clamp_top_n(3), 3)
        self.assertEqual(clamp_top_n(None), int(DEFAULT_FILTERS["top_n"]))
        self.assertEqual(clamp_top_n(0), int(DEFAULT_FILTERS["top_n"]))

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


SAMPLE_BOOK = """
{
    "600350.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"}, # 山东高速
    "601939.SH": {"ma_type": "SMA", "dividend_type": "front"}, # 建设银行
    "600028.SH": {"ma_type": "EMA", "dividend_type": "front"}, # 中国石油
    "600188.SH": {"ma_type": "EMA", "dividend_type": "front"}, # 兖矿能源
    "603259.SH": {"ma_type": "EMA", "dividend_type": "front"}, # 药明康德
}
"""


class BookStocksParseTests(unittest.TestCase):
    def test_parse_commented_config_snippet(self) -> None:
        data = parse_book_stocks_text(SAMPLE_BOOK)
        self.assertIn("600350.SH", data)
        self.assertEqual(data["601939.SH"]["ma_type"], "SMA")
        book = coerce_book_stocks_dict(data)
        self.assertEqual(book["600350.SH"]["dividend_type"], "front_ratio")
        self.assertEqual(book["603259.SH"]["ma_type"], "EMA")

    def test_parse_book_stocks_prefix_and_trailing_comma(self) -> None:
        text = (
            "BOOK_STOCKS = {\n"
            '  "601988.SH": "SMA",\n'
            "}"
        )
        data = parse_book_stocks_text(text)
        book = coerce_book_stocks_dict(data)
        self.assertEqual(book["601988.SH"]["ma_type"], "SMA")

    def test_year_keyed_extract(self) -> None:
        text = (
            "{\n"
            '  "2022": {"600350.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"}},\n'
            '  "2023": {"601988.SH": "SMA"},\n'
            "}"
        )
        self.assertTrue(is_year_keyed_baskets(parse_book_stocks_text(text)))
        y22 = basket_from_import_text(text, "2022")
        self.assertEqual(set(y22), {"600350.SH"})
        y23 = basket_from_import_text(text, "2023")
        self.assertEqual(y23["601988.SH"]["ma_type"], "SMA")
        with self.assertRaises(ValueError):
            basket_from_import_text(text, "2024")

    def test_empty_and_invalid(self) -> None:
        with self.assertRaises(ValueError):
            parse_book_stocks_text("   ")
        with self.assertRaises(ValueError):
            parse_book_stocks_text("[1, 2, 3]")
        self.assertFalse(is_year_keyed_baskets({}))
        self.assertFalse(is_year_keyed_baskets(None))


if __name__ == "__main__":
    unittest.main()
