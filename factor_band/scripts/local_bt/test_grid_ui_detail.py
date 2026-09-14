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
    from grid_ui import (
        _DETAIL_HOLD_BG_DARK,
        _DETAIL_TUNE_BG_DARK,
        _cell_column_mean,
        _composite_n_diffs_map,
        _default_robust_cell_id,
        _detail_metric_tone,
        _detail_window_rows,
        _detail_window_table_html,
        _iter_detail_groups,
        _metric_ranks,
        _pick_composite_recommend,
        _reorder_main_rows,
        _sort_detail_groups,
        _stack_detail_window_rows,
    )
except ImportError:
    _DETAIL_HOLD_BG_DARK = ""  # type: ignore[misc, assignment]
    _DETAIL_TUNE_BG_DARK = ""  # type: ignore[misc, assignment]
    _cell_column_mean = None  # type: ignore[misc, assignment]
    _composite_n_diffs_map = None  # type: ignore[misc, assignment]
    _default_robust_cell_id = None  # type: ignore[misc, assignment]
    _detail_metric_tone = None  # type: ignore[misc, assignment]
    _detail_window_rows = None  # type: ignore[misc, assignment]
    _detail_window_table_html = None  # type: ignore[misc, assignment]
    _iter_detail_groups = None  # type: ignore[misc, assignment]
    _metric_ranks = None  # type: ignore[misc, assignment]
    _pick_composite_recommend = None  # type: ignore[misc, assignment]
    _reorder_main_rows = None  # type: ignore[misc, assignment]
    _sort_detail_groups = None  # type: ignore[misc, assignment]
    _stack_detail_window_rows = None  # type: ignore[misc, assignment]


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
            self.assertIsNone(row["笔数"])
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
        self.assertEqual(rows[0]["笔数"], 3)
        self.assertEqual(rows[0]["几何年化%"], 12.3)
        self.assertEqual(rows[0]["账户盈亏"], 100.0)
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

    def test_basket_written_when_set(self) -> None:
        rows = _detail_window_rows(
            {"id": "sl06", "label": "止损 6%"}, {}, basket="调参"
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["篮子"] for r in rows], ["调参", "调参", "调参"])
        self.assertNotIn("篮子", _detail_window_rows({"id": "x", "label": "y"}, {})[0])


@unittest.skipIf(
    _stack_detail_window_rows is None or _detail_window_table_html is None,
    "streamlit (or grid_ui deps) not installed",
)
class GridUiDetailStackHtmlTest(unittest.TestCase):
    def test_space_off_three_rows_no_basket(self) -> None:
        rows = _stack_detail_window_rows(
            {"id": "sl06", "label": "止损 6%"}, {}, space_on=False
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["区间"] for r in rows], ["全区间", "调参期", "验收期"])
        self.assertTrue(all("篮子" not in r for r in rows))

    def test_space_on_six_rows_tune_then_holdout(self) -> None:
        book = {
            "windows": {"check": {"sharpe": 1.1, "n_trades": 4}},
            "holdout_windows": {"check": {"sharpe": 0.9, "n_trades": 2}},
        }
        rows = _stack_detail_window_rows(
            {"id": "sl06", "label": "止损 6%"}, book, space_on=True
        )
        self.assertEqual(len(rows), 6)
        self.assertEqual(
            [(r["篮子"], r["区间"]) for r in rows],
            [
                ("调参", "全区间"),
                ("调参", "调参期"),
                ("调参", "验收期"),
                ("盲测", "全区间"),
                ("盲测", "调参期"),
                ("盲测", "验收期"),
            ],
        )
        self.assertEqual(rows[2]["夏普"], 1.1)
        self.assertEqual(rows[2]["笔数"], 4)
        self.assertEqual(rows[5]["夏普"], 0.9)
        self.assertEqual(rows[5]["笔数"], 2)

    def test_space_on_missing_holdout_still_six_empty(self) -> None:
        rows = _stack_detail_window_rows(
            {"id": "sl06", "label": "止损 6%"}, {}, space_on=True
        )
        self.assertEqual(len(rows), 6)
        self.assertEqual([r["篮子"] for r in rows], ["调参"] * 3 + ["盲测"] * 3)
        self.assertTrue(all(r["夏普"] is None for r in rows))

    def test_html_no_basket_rowspan_3(self) -> None:
        rows = _stack_detail_window_rows(
            {"id": "sl06", "label": "止损 6%"}, {}, space_on=False
        )
        html = _detail_window_table_html(rows)
        self.assertNotIn("篮子", html)
        self.assertIn('rowspan="3"', html)
        self.assertNotIn('rowspan="6"', html)
        self.assertNotIn(_DETAIL_TUNE_BG_DARK, html)
        self.assertNotIn(_DETAIL_HOLD_BG_DARK, html)

    def test_html_basket_rowspan_6(self) -> None:
        rows = _stack_detail_window_rows(
            {"id": "sl06", "label": "止损 6%"}, {}, space_on=True
        )
        html = _detail_window_table_html(rows)
        self.assertIn("篮子", html)
        self.assertEqual(html.count(">调参</"), 1)
        self.assertEqual(html.count(">盲测</"), 1)
        self.assertIn('rowspan="6"', html)
        self.assertEqual(html.count('rowspan="3"'), 2)
        self.assertIn(_DETAIL_TUNE_BG_DARK, html)
        self.assertIn(_DETAIL_HOLD_BG_DARK, html)
        self.assertGreater(html.count(_DETAIL_TUNE_BG_DARK), 0)
        self.assertGreater(html.count(_DETAIL_HOLD_BG_DARK), 0)


@unittest.skipIf(_detail_metric_tone is None, "streamlit (or grid_ui deps) not installed")
class GridUiDetailToneTest(unittest.TestCase):
    def test_missing_and_non_tone_cols(self) -> None:
        gate = {"oos_sharpe": {"enabled": True, "min": 0.8}}
        self.assertIsNone(_detail_metric_tone("夏普", None, gate))
        self.assertIsNone(_detail_metric_tone("笔数", 10, gate))
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
        self.assertEqual(_detail_metric_tone("几何年化%", 0.0, {}), "pass")
        self.assertIsNone(_detail_metric_tone("几何年化%", -0.67, {}))
        self.assertEqual(_detail_metric_tone("账户盈亏", 1.0, None), "pass")
        self.assertIsNone(_detail_metric_tone("账户盈亏", -3593.38, None))

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


def _sharpe_book(all_s: float | None, tune_s: float | None, check_s: float | None) -> dict:
    windows: dict[str, dict] = {}
    if all_s is not None:
        windows["all"] = {"sharpe": all_s}
    if tune_s is not None:
        windows["tune"] = {"sharpe": tune_s}
    if check_s is not None:
        windows["check"] = {"sharpe": check_s}
    return {"windows": windows}


def _dd_book(all_dd: float, tune_dd: float, check_dd: float) -> dict:
    return {
        "windows": {
            "all": {"max_dd": all_dd},
            "tune": {"max_dd": tune_dd},
            "check": {"max_dd": check_dd},
        }
    }


@unittest.skipIf(
    _cell_column_mean is None or _sort_detail_groups is None or _reorder_main_rows is None,
    "streamlit (or grid_ui deps) not installed",
)
class GridUiColumnSortTest(unittest.TestCase):
    def test_mean_skips_none_and_non_numeric(self) -> None:
        chunk = [{"夏普": 1.0}, {"夏普": None}, {"夏普": "x"}, {"夏普": 3.0}]
        self.assertAlmostEqual(_cell_column_mean(chunk, "夏普"), 2.0)
        self.assertIsNone(_cell_column_mean([{"夏普": None}], "夏普"))

    def test_space_off_sharpe_mean_desc(self) -> None:
        a = _stack_detail_window_rows(
            {"id": "a", "label": "A"}, _sharpe_book(0.2, 0.4, 0.6), space_on=False
        )
        b = _stack_detail_window_rows(
            {"id": "b", "label": "B"}, _sharpe_book(1.0, 0.8, 0.6), space_on=False
        )
        # A mean 0.4, B mean 0.8
        rows = a + b
        ordered = _sort_detail_groups(rows, "夏普", True)
        self.assertEqual([r["id"] for r in ordered], ["b"] * 3 + ["a"] * 3)
        self.assertEqual([r["区间"] for r in ordered[:3]], ["全区间", "调参期", "验收期"])
        asc = _sort_detail_groups(rows, "夏普", False)
        self.assertEqual([r["id"] for r in asc], ["a"] * 3 + ["b"] * 3)

    def test_space_on_holdout_pulls_mean_down(self) -> None:
        high_tune = {
            "windows": {
                "all": {"sharpe": 1.0},
                "tune": {"sharpe": 1.0},
                "check": {"sharpe": 1.0},
            },
            "holdout_windows": {
                "all": {"sharpe": 0.0},
                "tune": {"sharpe": 0.0},
                "check": {"sharpe": 0.0},
            },
        }
        even = {
            "windows": {
                "all": {"sharpe": 0.8},
                "tune": {"sharpe": 0.8},
                "check": {"sharpe": 0.8},
            },
            "holdout_windows": {
                "all": {"sharpe": 0.8},
                "tune": {"sharpe": 0.8},
                "check": {"sharpe": 0.8},
            },
        }
        a = _stack_detail_window_rows({"id": "a", "label": "A"}, high_tune, space_on=True)
        b = _stack_detail_window_rows({"id": "b", "label": "B"}, even, space_on=True)
        self.assertEqual(len(a), 6)
        # A mean 0.5, B mean 0.8
        ordered = _sort_detail_groups(a + b, "夏普", True)
        self.assertEqual([r["id"] for r in ordered], ["b"] * 6 + ["a"] * 6)
        self.assertEqual(
            [(r["篮子"], r["区间"]) for r in ordered[:6]],
            [
                ("调参", "全区间"),
                ("调参", "调参期"),
                ("调参", "验收期"),
                ("盲测", "全区间"),
                ("盲测", "调参期"),
                ("盲测", "验收期"),
            ],
        )

    def test_empty_holdout_not_treated_as_zero(self) -> None:
        only_tune = {
            "windows": {
                "all": {"sharpe": 1.2},
                "tune": {"sharpe": 1.1},
                "check": {"sharpe": 1.0},
            }
        }
        both = {
            "windows": {
                "all": {"sharpe": 0.6},
                "tune": {"sharpe": 0.6},
                "check": {"sharpe": 0.6},
            },
            "holdout_windows": {
                "all": {"sharpe": 0.6},
                "tune": {"sharpe": 0.6},
                "check": {"sharpe": 0.6},
            },
        }
        a = _stack_detail_window_rows({"id": "a", "label": "A"}, only_tune, space_on=True)
        b = _stack_detail_window_rows({"id": "b", "label": "B"}, both, space_on=True)
        self.assertAlmostEqual(_cell_column_mean(a, "夏普"), 1.1)
        self.assertAlmostEqual(_cell_column_mean(b, "夏普"), 0.6)
        ordered = _sort_detail_groups(a + b, "夏普", True)
        self.assertEqual(ordered[0]["id"], "a")

    def test_all_none_last_both_dirs(self) -> None:
        empty = _stack_detail_window_rows(
            {"id": "empty", "label": "空"}, {}, space_on=False
        )
        has = _stack_detail_window_rows(
            {"id": "has", "label": "有"}, _sharpe_book(0.1, 0.1, 0.1), space_on=False
        )
        rows = empty + has
        for desc in (True, False):
            ordered = _sort_detail_groups(rows, "夏普", desc)
            self.assertEqual([r["id"] for r in ordered], ["has"] * 3 + ["empty"] * 3)

    def test_tie_keeps_original_order(self) -> None:
        a = _stack_detail_window_rows(
            {"id": "a", "label": "A"}, _sharpe_book(0.5, 0.5, 0.5), space_on=False
        )
        b = _stack_detail_window_rows(
            {"id": "b", "label": "B"}, _sharpe_book(0.5, 0.5, 0.5), space_on=False
        )
        ordered = _sort_detail_groups(a + b, "夏普", True)
        self.assertEqual([r["id"] for r in ordered], ["a"] * 3 + ["b"] * 3)

    def test_drawdown_mean_asc_smaller_first(self) -> None:
        a = _stack_detail_window_rows(
            {"id": "a", "label": "A"}, _dd_book(-0.10, -0.20, -0.30), space_on=False
        )
        b = _stack_detail_window_rows(
            {"id": "b", "label": "B"}, _dd_book(-0.05, -0.05, -0.05), space_on=False
        )
        # 表内回撤% 为绝对值：A mean 20, B mean 5
        self.assertAlmostEqual(_cell_column_mean(a, "回撤%"), 20.0)
        self.assertAlmostEqual(_cell_column_mean(b, "回撤%"), 5.0)
        ordered = _sort_detail_groups(a + b, "回撤%", False)
        self.assertEqual(ordered[0]["id"], "b")

    def test_illegal_metric_keeps_order(self) -> None:
        a = _stack_detail_window_rows(
            {"id": "a", "label": "A"}, _sharpe_book(0.1, 0.1, 0.1), space_on=False
        )
        b = _stack_detail_window_rows(
            {"id": "b", "label": "B"}, _sharpe_book(2.0, 2.0, 2.0), space_on=False
        )
        rows = a + b
        self.assertEqual(_sort_detail_groups(rows, "不是列", True), rows)

    def test_reorder_main_follows_detail_ids(self) -> None:
        main = [{"id": "a", "合计": 1}, {"id": "b", "合计": 2}]
        detail = [{"id": "b"}, {"id": "b"}, {"id": "a"}]
        out = _reorder_main_rows(main, detail)
        self.assertEqual([r["id"] for r in out], ["b", "a"])


def _metric_book(
    *,
    sharpe: float | None = None,
    ann: float | None = None,
    dd_pct: float | None = None,
    pf: float | None = None,
) -> dict:
    win: dict[str, float] = {}
    if sharpe is not None:
        win["sharpe"] = sharpe
    if ann is not None:
        win["avg_ann_pct"] = ann
    if dd_pct is not None:
        win["max_dd"] = -abs(dd_pct) / 100.0
    if pf is not None:
        win["profit_factor"] = pf
    return {"windows": {"all": dict(win), "tune": dict(win), "check": dict(win)}}


def _composite_groups(*cells: tuple[str, dict]) -> list[list[dict]]:
    rows: list[dict] = []
    for cid, book in cells:
        rows.extend(
            _stack_detail_window_rows({"id": cid, "label": cid}, book, space_on=False)
        )
    return _iter_detail_groups(rows)


@unittest.skipIf(
    _pick_composite_recommend is None
    or _metric_ranks is None
    or _composite_n_diffs_map is None,
    "streamlit (or grid_ui deps) not installed",
)
class GridUiCompositeRecommendTest(unittest.TestCase):
    def test_metric_ranks_ties_and_missing(self) -> None:
        self.assertEqual(_metric_ranks([2.0, 1.0], descending=True), [1.0, 2.0])
        self.assertEqual(_metric_ranks([1.0, 1.0], descending=True), [1.5, 1.5])
        self.assertEqual(_metric_ranks([None, 1.0], descending=True), [2.0, 1.0])
        self.assertEqual(_metric_ranks([30.0, 5.0], descending=False), [2.0, 1.0])

    def test_all_four_better_wins(self) -> None:
        groups = _composite_groups(
            ("a", _metric_book(sharpe=2.0, ann=20.0, dd_pct=5.0, pf=2.5)),
            ("b", _metric_book(sharpe=0.5, ann=1.0, dd_pct=25.0, pf=1.0)),
        )
        rec = _pick_composite_recommend(groups, {"a": 9, "b": 0})
        self.assertIsNotNone(rec)
        self.assertEqual(rec["id"], "a")
        self.assertAlmostEqual(rec["mean_rank"], 1.0)

    def test_sharpe_only_best_loses_to_other_three(self) -> None:
        groups = _composite_groups(
            ("a", _metric_book(sharpe=2.0, ann=1.0, dd_pct=30.0, pf=1.0)),
            ("b", _metric_book(sharpe=1.0, ann=10.0, dd_pct=5.0, pf=2.0)),
        )
        rec = _pick_composite_recommend(groups)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["id"], "b")
        self.assertAlmostEqual(rec["mean_rank"], 1.25)

    def test_missing_sharpe_still_competes(self) -> None:
        groups = _composite_groups(
            ("a", _metric_book(ann=20.0, dd_pct=5.0, pf=2.0)),
            ("b", _metric_book(sharpe=0.1, ann=1.0, dd_pct=25.0, pf=1.0)),
        )
        rec = _pick_composite_recommend(groups)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["id"], "a")
        a_chunk, b_chunk = groups
        self.assertIsNone(_cell_column_mean(a_chunk, "夏普"))
        self.assertEqual(_metric_ranks([None, 0.1], descending=True), [2.0, 1.0])

    def test_all_empty_returns_none(self) -> None:
        groups = _composite_groups(("empty", {}))
        self.assertIsNone(_pick_composite_recommend(groups))

    def test_tie_prefers_fewer_n_diffs_current_is_zero(self) -> None:
        book = _metric_book(sharpe=1.0, ann=10.0, dd_pct=8.0, pf=1.5)
        groups = _composite_groups(("a", book), ("b", book))
        rec = _pick_composite_recommend(groups, {"a": 3, "b": 1})
        self.assertEqual(rec["id"], "b")
        rec_cur = _pick_composite_recommend(groups, {"a": 0, "b": 2})
        self.assertEqual(rec_cur["id"], "a")
        nd = _composite_n_diffs_map(
            [
                {"id": "cur", "is_current": True, "n_diffs": 4},
                {"id": "x", "n_diffs": 2},
                {"id": "y"},
            ]
        )
        self.assertEqual(nd["cur"], 0)
        self.assertEqual(nd["x"], 2)
        self.assertGreater(nd["y"], 2)


@unittest.skipIf(_default_robust_cell_id is None, "streamlit (or grid_ui deps) not installed")
class GridUiRobustCellPickTest(unittest.TestCase):
    def test_prefers_rec_then_composite_then_first(self) -> None:
        cells = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        self.assertEqual(_default_robust_cell_id(cells, "b", "c"), "b")
        self.assertEqual(_default_robust_cell_id(cells, "", "c"), "c")
        self.assertEqual(_default_robust_cell_id(cells, "nope", "also"), "a")
        self.assertEqual(_default_robust_cell_id([], "b", "c"), "")


if __name__ == "__main__":
    unittest.main()
