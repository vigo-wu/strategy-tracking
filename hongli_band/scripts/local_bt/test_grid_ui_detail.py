# coding: utf-8
"""grid_ui 窗内子表：一格三行拼装（无 Streamlit 则 skip）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    from grid_ui import _detail_metric_tone, _detail_window_rows
except ImportError:
    _detail_metric_tone = None  # type: ignore[misc, assignment]
    _detail_window_rows = None  # type: ignore[misc, assignment]


@unittest.skipIf(_detail_window_rows is None, "streamlit (or grid_ui deps) not installed")
class GridUiDetailRowsTest(unittest.TestCase):
    def test_always_three_rows_period_order(self) -> None:
        rows = _detail_window_rows({"id": "sl06", "label": "止损 6%"}, {})
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["区间"] for r in rows], ["全区间", "调参期", "验收期"])
        for row in rows:
            self.assertEqual(row["id"], "sl06")
            self.assertEqual(row["label"], "止损 6%")
            self.assertIsNone(row["夏普"])
            self.assertIsNone(row["开仓"])
            self.assertIsNone(row["回撤%"])

    def test_drawdown_abs_pct_and_metrics(self) -> None:
        book = {
            "windows": {
                "all": {
                    "sharpe": 1.23456,
                    "n_open": 4,
                    "n_trades": 3,
                    "calmar": 2.1,
                    "max_dd": -0.1234,
                    "win_rate": 50.0,
                    "profit_factor": 1.5,
                    "avg_ann_pct": 12.3,
                    "avg_year_pnl": 100.0,
                },
                "tune": {"sharpe": 0.5, "max_dd": 0.08},
            }
        }
        rows = _detail_window_rows({"id": "base", "label": "现行"}, book)
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(rows[0]["回撤%"], 12.34)
        self.assertEqual(rows[0]["夏普"], 1.23456)
        self.assertEqual(rows[0]["开仓"], 4)
        self.assertEqual(rows[0]["笔数"], 3)
        self.assertAlmostEqual(rows[1]["回撤%"], 8.0)
        self.assertEqual(rows[1]["夏普"], 0.5)
        self.assertIsNone(rows[2]["夏普"])
        self.assertIsNone(rows[2]["回撤%"])

    def test_holdout_windows_key(self) -> None:
        book = {
            "holdout_windows": {
                "check": {"sharpe": 0.9, "n_trades": 2, "max_dd": -0.05},
            }
        }
        rows = _detail_window_rows(
            {"id": "h1", "label": "盲测"}, book, windows_key="holdout_windows"
        )
        self.assertEqual(len(rows), 3)
        self.assertIsNone(rows[0]["夏普"])
        self.assertEqual(rows[2]["夏普"], 0.9)
        self.assertEqual(rows[2]["笔数"], 2)
        self.assertAlmostEqual(rows[2]["回撤%"], 5.0)


@unittest.skipIf(_detail_metric_tone is None, "streamlit (or grid_ui deps) not installed")
class GridUiDetailToneTest(unittest.TestCase):
    def test_missing_and_non_tone_cols(self) -> None:
        gate = {"oos_sharpe": {"enabled": True, "min": 0.8}}
        self.assertIsNone(_detail_metric_tone("夏普", None, gate))
        self.assertIsNone(_detail_metric_tone("开仓", 10, gate))
        self.assertIsNone(_detail_metric_tone("回撤%", 2.5, gate))

    def test_sharpe_enabled_gate(self) -> None:
        gate = {"oos_sharpe": {"enabled": True, "min": 0.8}}
        self.assertEqual(_detail_metric_tone("夏普", 0.8, gate), "pass")
        self.assertEqual(_detail_metric_tone("夏普", 1.2, gate), "pass")
        self.assertIsNone(_detail_metric_tone("夏普", 0.79, gate))

    def test_sharpe_disabled_uses_zero(self) -> None:
        gate = {"oos_sharpe": {"enabled": False, "min": 0.8}}
        self.assertEqual(_detail_metric_tone("夏普", 0.0, gate), "pass")
        self.assertEqual(_detail_metric_tone("夏普", 0.1, gate), "pass")
        self.assertIsNone(_detail_metric_tone("夏普", -0.01, gate))

    def test_calmar_enabled_and_disabled(self) -> None:
        on = {"calmar": {"enabled": True, "min": 1.5}}
        self.assertEqual(_detail_metric_tone("卡玛", 1.5, on), "pass")
        self.assertIsNone(_detail_metric_tone("卡玛", 1.4, on))
        off = {"calmar": {"enabled": False, "min": 1.5}}
        self.assertEqual(_detail_metric_tone("卡玛", 0.01, off), "pass")
        self.assertIsNone(_detail_metric_tone("卡玛", -0.01, off))

    def test_ann_and_pnl_vs_zero(self) -> None:
        self.assertEqual(_detail_metric_tone("平均年化%", 0.0, {}), "pass")
        self.assertIsNone(_detail_metric_tone("平均年化%", -0.67, {}))
        self.assertEqual(_detail_metric_tone("平均盈亏", 1.0, None), "pass")
        self.assertIsNone(_detail_metric_tone("平均盈亏", -3593.38, None))

    def test_win_rate_and_profit_factor(self) -> None:
        wr = {"win_rate": {"enabled": True, "min": 45.0}}
        self.assertEqual(_detail_metric_tone("胜率%", 45.0, wr), "pass")
        self.assertEqual(_detail_metric_tone("胜率%", 58.7, wr), "pass")
        self.assertIsNone(_detail_metric_tone("胜率%", 44.9, wr))
        wr_off = {"win_rate": {"enabled": False, "min": 45.0}}
        self.assertEqual(_detail_metric_tone("胜率%", 0.0, wr_off), "pass")
        self.assertIsNone(_detail_metric_tone("胜率%", -0.1, wr_off))
        pf = {"profit_factor": {"enabled": True, "min": 1.5}}
        self.assertEqual(_detail_metric_tone("盈亏比", 1.5, pf), "pass")
        self.assertIsNone(_detail_metric_tone("盈亏比", 0.83, pf))
        pf_off = {"profit_factor": {"enabled": False, "min": 1.5}}
        self.assertEqual(_detail_metric_tone("盈亏比", 0.01, pf_off), "pass")
        self.assertIsNone(_detail_metric_tone("盈亏比", -0.01, pf_off))


if __name__ == "__main__":
    unittest.main()
