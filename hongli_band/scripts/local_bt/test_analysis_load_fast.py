# coding: utf-8
"""数据分析加载加速：hold_metrics 开关 + list_score_years。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from analyze import analyze_detail
from stock_select import list_score_years
from test_terminal_rounds import HEADER, _write_detail


class HoldMetricsFlagTests(unittest.TestCase):
    def test_analyze_detail_hold_metrics_false_skips_enrich(self):
        lines = [
            "600350,山东高速,股票,交运,多,2024-01-09 15:00:00,买入,3.59,3.59,0,0,0,4100,0,14719,普通",
            "600350,山东高速,股票,交运,多,2024-01-30 15:00:00,卖出,3.80,3.80,861,0,0,4100,0,15580,普通",
        ]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # 有行情也不应 enrich
            csv_dir = root / "front_ratio"
            csv_dir.mkdir()
            (csv_dir / "600350_SH_1d_20240109_20240130.csv").write_text(
                "stock,period,datetime,open,high,low,close,volume,amount\n"
                "600350.SH,1d,20240109,3.5,4.0,3.4,3.59,100,100\n"
                "600350.SH,1d,20240130,3.7,3.9,3.6,3.80,100,100\n",
                encoding="utf-8",
            )
            detail = _write_detail(csv_dir / "local_bt_600350_SH_2024_操作明细.csv", lines)
            r = analyze_detail(
                detail,
                budget=50000.0,
                csv_root=root,
                hold_metrics=False,
            )
            t = r["trades"][0]
            self.assertIsNone(t.get("hold_max_dd"))
            self.assertIsNone(t.get("hold_max_up"))
            r2 = analyze_detail(
                detail,
                budget=50000.0,
                csv_root=root,
                hold_metrics=True,
            )
            self.assertIsNotNone(r2["trades"][0].get("hold_max_dd"))
            self.assertIsNotNone(r2["trades"][0].get("hold_max_up"))


class ListScoreYearsTests(unittest.TestCase):
    def test_list_score_years_from_filenames(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fr = root / "front_ratio"
            fr.mkdir()
            # 单票分年
            (fr / "local_bt_600350_SH_2019_SMA_操作明细.csv").write_text(
                "\n".join([HEADER]) + "\n", encoding="gbk"
            )
            (fr / "local_bt_600350_SH_2020_EMA_操作明细.csv").write_text(
                "\n".join([HEADER]) + "\n", encoding="gbk"
            )
            # book score / hold
            (fr / "local_bt_book_score_2021_u01abdc66_操作明细.csv").write_text(
                "\n".join([HEADER]) + "\n", encoding="gbk"
            )
            (fr / "local_bt_book_hold_2022_p1_k05475781_操作明细.csv").write_text(
                "\n".join([HEADER]) + "\n", encoding="gbk"
            )
            years = list_score_years(root)
            self.assertEqual(years, ("2019", "2020", "2021", "2022"))


if __name__ == "__main__":
    unittest.main()
