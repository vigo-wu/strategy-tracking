# coding: utf-8
"""robust_score：deploy→holdout adapter、中位 GO、go_floor。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
LOCAL_BT = REPO / "factor_band" / "scripts" / "local_bt"
if str(LOCAL_BT) not in sys.path:
    sys.path.insert(0, str(LOCAL_BT))

from robust_score import (  # noqa: E402
    book_from_windows,
    eval_run_score,
    score_basket,
    score_cfg_for_json,
    validate_score,
)


def _kpi(**kwargs):
    row = {
        "n_trades": 40,
        "win_rate": 50.0,
        "profit_factor": 1.5,
        "max_dd": -0.10,
        "sharpe": 0.8,
        "oos_sharpe": 0.8,
        "avg_ann_pct": 10.0,
        "avg_year_pnl": 1000.0,
    }
    row.update(kwargs)
    return row


def _blocks(*, deploy_dd: float = -0.50) -> dict:
    return {
        "all": _kpi(max_dd=-0.10, sharpe=0.8),
        "tune": _kpi(max_dd=-0.10, avg_year_pnl=1000.0),
        "check": _kpi(max_dd=-0.10, avg_year_pnl=1000.0, n_trades=40),
        "deploy": _kpi(max_dd=deploy_dd, avg_year_pnl=1000.0, sharpe=0.4),
    }


class RobustScoreTests(unittest.TestCase):
    def test_adapter_dd_cap_ignores_deploy_drawdown(self) -> None:
        blocks = _blocks(deploy_dd=-0.50)
        book = book_from_windows(blocks)
        self.assertAlmostEqual(book["windows"]["all"]["max_dd"], -0.10)
        self.assertAlmostEqual(book["holdout_windows"]["all"]["max_dd"], -0.50)
        self.assertAlmostEqual(book["holdout_windows"]["check"]["max_dd"], -0.50)

        a = score_basket(blocks, {"dd_cap": 0.35})
        b = score_basket(blocks, {"dd_cap": 0.20})
        self.assertIsNotNone(a.get("s_def"))
        self.assertNotAlmostEqual(float(a["s_def"]), float(b["s_def"]))
        # 若盲测回撤混入防御，|dd|=0.50 超过两条 0 分线，s_def 会贴在盈亏盾上且不随 dd_cap 变。
        self.assertGreater(float(a["s_def"]), 30.0 + 1e-6)

    def test_median_go_and_nogo(self) -> None:
        go = eval_run_score(
            [{"total": 40.0}, {"total": 60.0}],
            {"go_floor": 50.0},
        )
        self.assertEqual(go["verdict"], "GO")
        self.assertAlmostEqual(float(go["median_total"]), 50.0)
        self.assertEqual(go["n_scored"], 2)

        nogo = eval_run_score(
            [{"total": 40.0}, {"total": 49.0}],
            {"go_floor": 50.0},
        )
        self.assertEqual(nogo["verdict"], "NO-GO")
        self.assertLess(float(nogo["median_total"]), 50.0)

    def test_n_scored_zero_is_nogo(self) -> None:
        empty = eval_run_score([], {"go_floor": 50.0})
        self.assertEqual(empty["verdict"], "NO-GO")
        self.assertEqual(empty["n_scored"], 0)
        self.assertIsNone(empty["median_total"])

        skipped = eval_run_score(
            [{"scored": False, "total": 90.0}, {"total": None}],
            {"go_floor": 50.0},
        )
        self.assertEqual(skipped["verdict"], "NO-GO")
        self.assertEqual(skipped["n_scored"], 0)

    def test_go_floor_illegal(self) -> None:
        with self.assertRaises(ValueError):
            validate_score({"go_floor": 0})
        with self.assertRaises(ValueError):
            validate_score({"go_floor": -1})
        with self.assertRaises(ValueError):
            validate_score({"go_floor": 100.1})
        ok = validate_score({"go_floor": 100})
        self.assertAlmostEqual(float(ok["go_floor"]), 100.0)
        dumped = score_cfg_for_json(ok)
        self.assertIn("go_floor", dumped)
        self.assertAlmostEqual(float(dumped["go_floor"]), 100.0)


if __name__ == "__main__":
    unittest.main()
