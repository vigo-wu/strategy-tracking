# coding: utf-8
"""导入 spec：pending 在 _ensure_state 写 widget 键，避免实例化后赋值。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    from grid_ui import GRID_CONFIG_DIR, _apply_pending_import, _list_specs, _spec_import_payload
    from grid_run import load_config_defaults
except ImportError:
    _apply_pending_import = None  # type: ignore[misc, assignment]
    _spec_import_payload = None  # type: ignore[misc, assignment]
    load_config_defaults = None  # type: ignore[misc, assignment]
    GRID_CONFIG_DIR = None  # type: ignore[misc, assignment]
    _list_specs = None  # type: ignore[misc, assignment]


@unittest.skipIf(_spec_import_payload is None, "streamlit (or grid_ui deps) not installed")
class GridUiImportPendingTest(unittest.TestCase):
    def test_payload_and_apply_sets_compare_div_on_plain_dict(self) -> None:
        defaults = load_config_defaults()
        spec = {
            "theme": "hongli_band",
            "sweep": "entry_structure_core",
            "compare_div": "front_ratio",
            "year_start": 2018,
            "year_end": 2026,
            "tune_start": 2018,
            "tune_end": 2022,
            "check_start": 2023,
            "check_end": 2026,
            "cells": [
                {"id": "base", "label": "现行", "kind": "base", "overrides": {}},
            ],
        }
        payload = _spec_import_payload(spec, defaults)
        self.assertEqual(payload["compare_div"], "front_ratio")
        self.assertEqual(payload["windows"]["check_start"], 2023)
        self.assertTrue(payload["cells"])

        ss: dict = {"grid_compare_div": "none"}
        _apply_pending_import(ss, payload)
        self.assertEqual(ss["grid_compare_div"], "front_ratio")
        self.assertEqual(ss["grid_check_start"], 2023)
        self.assertEqual(len(ss["grid_cells"]), 1)
        self.assertIn("已导入 1 格", ss.get("grid_flash") or "")

    def test_list_specs_only_grid_config(self) -> None:
        paths = _list_specs()
        for path in paths:
            self.assertEqual(path.parent.resolve(), GRID_CONFIG_DIR.resolve())


if __name__ == "__main__":
    unittest.main()
