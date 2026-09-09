# coding: utf-8
"""grid_ui 开跑：点开始网格直接进入 run，不再弹确认。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    from grid_ui import _begin_pause_request, _begin_resume_request, _begin_run_request
except ImportError:
    _begin_run_request = None  # type: ignore[misc, assignment]
    _begin_resume_request = None  # type: ignore[misc, assignment]
    _begin_pause_request = None  # type: ignore[misc, assignment]


@unittest.skipIf(_begin_run_request is None, "streamlit (or grid_ui deps) not installed")
class GridUiRunStartTest(unittest.TestCase):
    def test_start_sets_run_action_immediately(self) -> None:
        ss: dict = {"grid_pending_sweep": "old"}
        _begin_run_request(ss)
        self.assertEqual(ss["grid_action"], "run")
        self.assertNotIn("grid_pending_sweep", ss)
        self.assertFalse(ss.get("grid_await_confirm"))
        self.assertFalse(ss.get("grid_run_ok"))
        self.assertFalse(ss.get("grid_yield_for_dialog"))

    def test_second_start_still_runs_without_confirm(self) -> None:
        ss: dict = {"grid_confirm_go_1": True}
        _begin_run_request(ss)
        ss["grid_pending_sweep"] = "minted"
        _begin_run_request(ss)
        self.assertEqual(ss["grid_action"], "run")
        self.assertNotIn("grid_pending_sweep", ss)

    def test_resume_does_not_mint(self) -> None:
        ss: dict = {"grid_sweep": "keep_me", "grid_pending_sweep": "old"}
        _begin_resume_request(ss)
        self.assertEqual(ss["grid_action"], "resume")
        self.assertEqual(ss["grid_sweep"], "keep_me")
        self.assertNotIn("grid_pending_sweep", ss)

    def test_pause_sets_action(self) -> None:
        ss: dict = {"grid_sweep": "keep_me"}
        _begin_pause_request(ss)
        self.assertEqual(ss["grid_action"], "pause")
        self.assertEqual(ss["grid_sweep"], "keep_me")


if __name__ == "__main__":
    unittest.main()
