# coding: utf-8
"""持有期最大回撤 / 最大浮盈。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analyze import (
    enrich_detail_raw_hold_metrics,
    enrich_trades_hold_metrics,
    hold_max_dd_from_closes,
    hold_max_up_from_highs,
    infer_dividend_type_from_path,
)


class HoldMaxDdTests(unittest.TestCase):
    def test_hold_max_dd_from_closes(self):
        self.assertIsNone(hold_max_dd_from_closes([]))
        self.assertIsNone(hold_max_dd_from_closes([10.0]))
        self.assertAlmostEqual(hold_max_dd_from_closes([10.0, 12.0, 9.0]), -25.0, places=4)
        self.assertAlmostEqual(hold_max_dd_from_closes([10.0, 11.0, 12.0]), 0.0, places=4)

    def test_hold_max_up_from_highs(self):
        self.assertIsNone(hold_max_up_from_highs([], 10.0))
        self.assertIsNone(hold_max_up_from_highs([12.0], 0))
        # 买价 10，High 10/12/11 → 20%
        self.assertAlmostEqual(hold_max_up_from_highs([10.0, 12.0, 11.0], 10.0), 20.0, places=4)

    def test_infer_dividend_type_from_path(self):
        self.assertEqual(
            infer_dividend_type_from_path(Path("report/front_ratio/x_操作明细.csv")),
            "front_ratio",
        )
        self.assertEqual(infer_dividend_type_from_path(None), "front_ratio")

    def test_enrich_trades_hold_metrics_synthetic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            csv_dir = root / "front_ratio"
            csv_dir.mkdir(parents=True)
            daily = csv_dir / "600350_SH_1d_20240102_20240110.csv"
            daily.write_text(
                "stock,period,datetime,open,high,low,close,volume,amount\n"
                "600350.SH,1d,20240102,10,10.5,9.5,10,100,100\n"
                "600350.SH,1d,20240103,11,13,11,12,100,100\n"
                "600350.SH,1d,20240108,9,9.5,8.5,9,100,100\n"
                "600350.SH,1d,20240110,10,10.2,9.8,10,100,100\n",
                encoding="utf-8",
            )
            detail = root / "front_ratio" / "local_bt_book_操作明细.csv"
            trades = [
                {
                    "i": 1,
                    "stock": "600350",
                    "buy_open_day": "20240102",
                    "sell_exec_day": "20240110",
                    "buy_price": 10.0,
                    "shares": 100,
                }
            ]
            out = enrich_trades_hold_metrics(trades, csv_root=root, detail_path=detail)
            self.assertAlmostEqual(float(out[0]["hold_max_dd"]), -25.0, places=4)
            # max High=13 vs buy 10 → 30%
            self.assertAlmostEqual(float(out[0]["hold_max_up"]), 30.0, places=4)

    def test_enrich_missing_csv_is_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "front_ratio").mkdir()
            detail = root / "front_ratio" / "x_操作明细.csv"
            trades = [
                {
                    "stock": "600350",
                    "buy_open_day": "20240102",
                    "sell_exec_day": "20240110",
                    "buy_price": 10.0,
                }
            ]
            out = enrich_trades_hold_metrics(trades, csv_root=root, detail_path=detail)
            self.assertIsNone(out[0].get("hold_max_dd"))
            self.assertIsNone(out[0].get("hold_max_up"))

    def test_enrich_detail_raw_sell_rows_only(self):
        raw = pd.DataFrame(
            [
                {
                    "代码": "600350",
                    "操作时间": "2024-01-02 15:00:00",
                    "操作类型": "买入",
                    "数量": 100,
                },
                {
                    "代码": "600350",
                    "操作时间": "2024-01-10 15:00:00",
                    "操作类型": "卖出",
                    "数量": 100,
                },
            ]
        )
        trades = [
            {
                "stock": "600350",
                "sell_exec_day": "20240110",
                "shares": 100,
                "hold_max_dd": -5.0,
                "hold_max_up": 12.5,
            }
        ]
        out = enrich_detail_raw_hold_metrics(raw, trades)
        self.assertTrue(pd.isna(out.iloc[0]["持有回撤%"]) or out.iloc[0]["持有回撤%"] is None)
        self.assertTrue(pd.isna(out.iloc[0]["持有浮盈%"]) or out.iloc[0]["持有浮盈%"] is None)
        self.assertEqual(out.iloc[1]["持有回撤%"], -5.0)
        self.assertEqual(out.iloc[1]["持有浮盈%"], 12.5)


if __name__ == "__main__":
    unittest.main()
