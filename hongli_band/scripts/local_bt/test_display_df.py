# coding: utf-8
import unittest

import pandas as pd

from analyze import batch_summary_dataframe, trades_to_dataframe
from display_df import (
    insert_name_column,
    rename_columns,
    stock_axis_label,
    stock_display_name,
)
from select_config import book_stocks_to_editor_rows, editor_rows_to_book_stocks


class DisplayDfTests(unittest.TestCase):
    def test_stock_display_name_known(self):
        name = stock_display_name("600350.SH")
        self.assertEqual(name, "山东高速")
        self.assertNotEqual(name, "600350")

    def test_stock_display_name_unknown_fallback(self):
        name = stock_display_name("999999.SH")
        self.assertEqual(name, "999999")

    def test_insert_name_column_order(self):
        df = pd.DataFrame({"代码": ["600350.SH", "601988.SH"], "轮次": [1, 2]})
        out = insert_name_column(df)
        self.assertEqual(list(out.columns), ["代码", "名称", "轮次"])
        self.assertEqual(out.iloc[0]["名称"], "山东高速")

    def test_insert_name_column_missing_code(self):
        df = pd.DataFrame({"轮次": [1]})
        out = insert_name_column(df)
        self.assertEqual(list(out.columns), ["轮次"])

    def test_rename_columns_partial(self):
        df = pd.DataFrame({"year": [2020], "status": ["ok"], "extra": [1]})
        out = rename_columns(df, {"year": "年份", "status": "状态"})
        self.assertEqual(list(out.columns), ["年份", "状态", "extra"])

    def test_stock_axis_label(self):
        label = stock_axis_label("600350.SH")
        self.assertIn("600350.SH", label)
        self.assertIn("山东高速", label)

    def test_batch_summary_has_code_and_name(self):
        df = batch_summary_dataframe(
            [
                {
                    "stock": "600350.SH",
                    "ok": True,
                    "status": "成功",
                    "n_buy": 1,
                    "sum_pnl": 100.0,
                }
            ]
        )
        self.assertIn("代码", df.columns)
        self.assertIn("名称", df.columns)
        self.assertEqual(df.iloc[0]["代码"], "600350.SH")
        self.assertEqual(df.iloc[0]["名称"], "山东高速")

    def test_trades_to_dataframe_chinese_headers(self):
        empty = trades_to_dataframe([])
        self.assertIn("轮次", empty.columns)
        self.assertIn("买入日", empty.columns)
        self.assertNotIn("buy_open_day", empty.columns)
        df = trades_to_dataframe(
            [
                {
                    "i": 1,
                    "buy_open_day": "20240102",
                    "sell_exec_day": "20240110",
                    "buy_price": 10.0,
                    "sell_price": 11.0,
                    "shares": 100,
                    "pnl": 100.0,
                    "ret_pct": 10.0,
                    "hold_calendar_days": 8,
                }
            ]
        )
        self.assertEqual(df.iloc[0]["轮次"], 1)
        self.assertEqual(df.iloc[0]["买入日"], "20240102")

    def test_book_editor_rows_have_name_and_roundtrip(self):
        book = {
            "600350.SH": {"ma_type": "EMA", "dividend_type": "front_ratio"},
        }
        rows = book_stocks_to_editor_rows(book)
        self.assertEqual(rows[0]["名称"], "山东高速")
        self.assertEqual(rows[0]["均线类型"], "EMA")
        self.assertEqual(rows[0]["复权方式"], "front_ratio")
        back = editor_rows_to_book_stocks(rows)
        self.assertEqual(back["600350.SH"]["ma_type"], "EMA")
        self.assertNotIn("名称", back["600350.SH"])
        # 兼容旧英文列
        legacy = editor_rows_to_book_stocks(
            [{"代码": "601988.SH", "ma_type": "SMA", "dividend_type": "front"}]
        )
        self.assertEqual(legacy["601988.SH"]["ma_type"], "SMA")


if __name__ == "__main__":
    unittest.main()
