# coding: utf-8
"""数据分析加载加速：hold_metrics 开关 + list_score_years / list_csv_years。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from analyze import analyze_detail, list_csv_years, years_from_daily_metas
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


def _write_daily_csv(folder: Path, stock: str, start: str, end: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    code = stock.replace(".", "_")
    path = folder / ("%s_1d_%s_%s.csv" % (code, start, end))
    path.write_text(
        "stock,period,datetime,open,high,low,close,volume,amount\n"
        "%s,1d,%s,3.5,4.0,3.4,3.59,100,100\n"
        "%s,1d,%s,3.7,3.9,3.6,3.80,100,100\n" % (stock, start, stock, end),
        encoding="utf-8",
    )


class ListCsvYearsTests(unittest.TestCase):
    def test_years_from_daily_metas_empty(self):
        self.assertEqual(years_from_daily_metas(None), ())
        self.assertEqual(years_from_daily_metas([]), ())

    def test_years_from_daily_metas_union(self):
        metas = [
            {"start": "20200102", "end": "20210601"},
            {"start": "20190101", "end": "20201231"},
        ]
        self.assertEqual(years_from_daily_metas(metas), ("2019", "2020", "2021"))

    def test_list_csv_years_from_none_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_daily_csv(root / "none", "600350.SH", "20200102", "20221231")
            years = list_csv_years(root)
            self.assertEqual(years[0], "2020")
            self.assertEqual(years[-1], "2022")

    def test_list_csv_years_falls_back_to_front_ratio(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_daily_csv(root / "front_ratio", "600350.SH", "20180102", "20191231")
            years = list_csv_years(root)
            self.assertEqual(years, ("2018", "2019"))


if __name__ == "__main__":
    unittest.main()
