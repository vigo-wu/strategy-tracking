# coding: utf-8
"""local_bt_log：BUY filled 含 lots= 仍能解析。"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from local_bt_log import (  # noqa: E402
    IS_YEARS,
    OOS_YEARS,
    _trades_from_log_text,
    _year_of,
    parse_local_bt_log,
)
from analyze import parse_budget_from_log  # noqa: E402


class LocalBtLogTest(unittest.TestCase):
    def test_year_split(self) -> None:
        self.assertIn(2018, IS_YEARS)
        self.assertIn(2026, OOS_YEARS)
        self.assertEqual(_year_of("20180615"), 2018)

    def test_parse_filled_with_lots(self) -> None:
        text = "\n".join(
            [
                "local_bt 600350.SH csv= x.csv walk= 20180101 20181231 ma_type= EMA",
                "BUY filled {'shares': 100, 'price': 10.0, 'cost': 1000.0, 'opened_at': '20180601000000', 'lots': 1}",
                "SELL by signal=stop_loss label=止损 signal_day=20180701",
                "SELL done stop_loss last= 9.0 cleared {'shares': 100, 'price': 10.0, 'cost': 1000.0, 'opened_at': '20180601000000', 'lots': 1}",
            ]
        )
        trades = _trades_from_log_text(text)
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["sell_signal"], "stop_loss")
        self.assertAlmostEqual(trades[0]["pnl"], -100.0)

    def test_parse_file_without_detail_csv(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "local_bt_600350_SH_2018_EMA.txt"
            path.write_text(
                "local_bt 600350.SH csv= x.csv walk= 20180101 20181231 ma_type= EMA\n"
                "BUY filled {'shares': 50, 'price': 2.0, 'cost': 100.0, 'opened_at': '20180301000000', 'lots': 1}\n"
                "SELL by signal=trail_stop label=止盈 signal_day=20180401\n"
                "SELL done trail_stop last= 2.5 cleared {'shares': 50, 'price': 2.0, 'cost': 100.0, 'opened_at': '20180301000000', 'lots': 1}\n",
                encoding="utf-8",
            )
            banner, trades = parse_local_bt_log(path)
            self.assertEqual(banner.get("stock"), "600350.SH")
            self.assertEqual(len(trades), 1)
            self.assertEqual(trades[0]["sell_signal"], "trail_stop")

    def test_parse_budget_from_log_defaults_to_trade_budget(self) -> None:
        self.assertEqual(parse_budget_from_log(None), 100000.0)
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "nope.txt"
            self.assertEqual(parse_budget_from_log(missing), 100000.0)
            path = Path(td) / "local_bt.txt"
            path.write_text("HlBand v1.69 init budget= 90000.0 cash_ratio= 0.9\n", encoding="utf-8")
            self.assertEqual(parse_budget_from_log(path), 90000.0)


if __name__ == "__main__":
    unittest.main()
