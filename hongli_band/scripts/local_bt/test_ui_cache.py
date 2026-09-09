# coding: utf-8
"""表单草稿缓存：roundtrip / 坏 JSON / hydrate 不覆盖 / merge 保切片。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from ui_cache import (
    clamp_choice,
    form_cache_keys,
    hydrate_session,
    is_editor_key,
    load_form_cache,
    merge_form_cache,
    snapshot_form_state,
)


class UiCacheTest(unittest.TestCase):
    def test_editor_keys_excluded_from_whitelist(self) -> None:
        keys = form_cache_keys()
        self.assertIn("ui_mode", keys)
        self.assertIn("analysis_book_rows", keys)
        self.assertIn("select_flt_top_n", keys)
        self.assertNotIn("analysis_book_editor", keys)
        self.assertIn("grid_sweep", keys)
        self.assertIn("grid_param_sel", keys)
        self.assertIn("grid_n_draw", keys)
        self.assertIn("grid_full_span", keys)
        self.assertNotIn("grid_n_tune", keys)
        self.assertNotIn("grid_asset_seed", keys)
        self.assertNotIn("grid_cells_editor", keys)
        self.assertNotIn("grid_param_editor", keys)
        self.assertTrue(is_editor_key("analysis_book_editor"))
        self.assertTrue(is_editor_key("grid_cells_editor"))
        self.assertTrue(is_editor_key("grid_param_editor"))
        self.assertTrue(is_editor_key("analysis_wf_editor_2021"))
        self.assertFalse(is_editor_key("analysis_wf_rows"))

    def test_roundtrip_and_bad_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cache.json"
            self.assertEqual(load_form_cache(path), {})
            merge_form_cache(
                {
                    "ui_mode": "数据分析",
                    "analysis_wf_rows": {"2021": [{"代码": "600350.SH"}]},
                    "analysis_book_editor": {"ignored": True},
                    "not_a_form_key": 1,
                },
                path,
            )
            loaded = load_form_cache(path)
            self.assertEqual(loaded["ui_mode"], "数据分析")
            self.assertEqual(loaded["analysis_wf_rows"]["2021"][0]["代码"], "600350.SH")
            self.assertNotIn("analysis_book_editor", loaded)
            self.assertNotIn("not_a_form_key", loaded)

            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(load_form_cache(path), {})

            path.write_text("[]\n", encoding="utf-8")
            self.assertEqual(load_form_cache(path), {})

    def test_hydrate_does_not_overwrite(self) -> None:
        state = {"ui_mode": "选股方案", "analysis_book_editor": {"stale": True}}
        payload = {
            "ui_mode": "数据分析",
            "select_flt_top_n": 8,
            "analysis_book_rows": [{"代码": "600028.SH"}],
            "analysis_book_editor": {"from_file": True},
        }
        applied = hydrate_session(state, payload)
        self.assertEqual(state["ui_mode"], "选股方案")
        self.assertIn("select_flt_top_n", applied)
        self.assertEqual(state["select_flt_top_n"], 8)
        self.assertEqual(state["analysis_book_rows"], [{"代码": "600028.SH"}])
        self.assertNotIn("analysis_book_editor", state)
        state["select_flt_top_n"] = 4
        hydrate_session(state, payload)
        self.assertEqual(state["select_flt_top_n"], 4)

    def test_merge_select_slice_keeps_analysis_baskets(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cache.json"
            merge_form_cache(
                {
                    "ui_mode": "数据分析",
                    "analysis_wf_rows": {"2022": [{"代码": "600350.SH"}]},
                    "analysis_book_rows": [{"代码": "601088.SH"}],
                    "select_flt_top_n": 6,
                },
                path,
            )
            merge_form_cache({"select_flt_top_n": 9, "select_year_start": "2021"}, path)
            loaded = load_form_cache(path)
            self.assertEqual(loaded["select_flt_top_n"], 9)
            self.assertEqual(loaded["select_year_start"], "2021")
            self.assertEqual(loaded["analysis_wf_rows"]["2022"][0]["代码"], "600350.SH")
            self.assertEqual(loaded["analysis_book_rows"][0]["代码"], "601088.SH")
            self.assertEqual(loaded["ui_mode"], "数据分析")

    def test_snapshot_skips_missing_and_editor_keys(self) -> None:
        snap = snapshot_form_state(
            {
                "ui_mode": "跑本地回测",
                "analysis_book_editor": {"nope": 1},
                "batch_result": {"rows": []},
            }
        )
        self.assertEqual(snap, {"ui_mode": "跑本地回测"})

    def test_clamp_choice(self) -> None:
        years = ["2020", "2021", "2022"]
        self.assertEqual(clamp_choice("2021", years), "2021")
        self.assertEqual(clamp_choice("1999", years), "2020")
        self.assertEqual(clamp_choice("1999", years, "2022"), "2022")
        self.assertEqual(clamp_choice(None, ()), None)

    def test_file_is_valid_json_after_merge(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cache.json"
            merge_form_cache({"bt_scope": "批量", "bt_dividend_types": ["front", "none"]}, path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(raw["bt_scope"], "批量")
            self.assertEqual(raw["bt_dividend_types"], ["front", "none"])

    def test_load_migrates_grid_n_tune(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cache.json"
            path.write_text(
                json.dumps({"grid_n_tune": 4, "grid_asset_seed": 43, "ui_mode": "参数网格"}),
                encoding="utf-8",
            )
            loaded = load_form_cache(path)
            self.assertEqual(loaded["grid_n_draw"], 4)
            self.assertNotIn("grid_n_tune", loaded)
            self.assertNotIn("grid_asset_seed", loaded)


if __name__ == "__main__":
    unittest.main()
