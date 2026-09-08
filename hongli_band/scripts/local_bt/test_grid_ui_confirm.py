# coding: utf-8
"""grid_ui 开跑确认：防残留按钮把弹窗跳成直接开跑（无 Streamlit 则 skip）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:
    from grid_ui import (
        _apply_run_confirmed,
        _apply_run_dismissed,
        _begin_run_request,
        _clear_stale_confirm_keys,
        _confirm_open_key,
        _needs_run_confirm,
    )
except ImportError:
    _apply_run_confirmed = None  # type: ignore[misc, assignment]
    _apply_run_dismissed = None  # type: ignore[misc, assignment]
    _begin_run_request = None  # type: ignore[misc, assignment]
    _clear_stale_confirm_keys = None  # type: ignore[misc, assignment]
    _confirm_open_key = None  # type: ignore[misc, assignment]
    _needs_run_confirm = None  # type: ignore[misc, assignment]


@unittest.skipIf(_begin_run_request is None, "streamlit (or grid_ui deps) not installed")
class GridUiRunConfirmTest(unittest.TestCase):
    def test_first_click_always_needs_confirm(self) -> None:
        ss: dict = {}
        _begin_run_request(ss)
        self.assertEqual(ss["grid_action"], "run")
        self.assertTrue(ss["grid_await_confirm"])
        self.assertTrue(_needs_run_confirm(ss))
        self.assertFalse(ss["grid_run_ok"])

    def test_small_job_still_needs_confirm(self) -> None:
        # 旧 JOB_CONFIRM_THRESHOLD 会让小格直跑；确认门不得看任务数。
        ss = {"grid_run_ok": False}
        self.assertTrue(_needs_run_confirm(ss))

    def test_second_start_after_confirm_still_prompts(self) -> None:
        ss: dict = {"grid_confirm_go_1": True}
        _begin_run_request(ss)
        _apply_run_confirmed(ss)
        self.assertFalse(_needs_run_confirm(ss))
        _begin_run_request(ss)
        self.assertTrue(_needs_run_confirm(ss))
        self.assertFalse(ss["grid_run_ok"])
        self.assertEqual(ss["grid_confirm_nonce"], 2)
        self.assertNotIn("grid_confirm_go_1", ss)
        self.assertNotEqual(_confirm_open_key(1), _confirm_open_key(ss["grid_confirm_nonce"]))

    def test_stale_confirm_key_cleared_on_start(self) -> None:
        ss = {
            "grid_confirm_go": True,
            "grid_confirm_go_3": True,
            "grid_confirm_cancel_3": True,
            "grid_sweep": "keep",
        }
        _clear_stale_confirm_keys(ss)
        self.assertNotIn("grid_confirm_go", ss)
        self.assertNotIn("grid_confirm_go_3", ss)
        self.assertNotIn("grid_confirm_cancel_3", ss)
        self.assertEqual(ss["grid_sweep"], "keep")

    def test_dismiss_cancels_run_not_other_actions(self) -> None:
        ss: dict = {}
        _begin_run_request(ss)
        ss["grid_pending_sweep"] = "foo"
        _apply_run_dismissed(ss)
        self.assertIsNone(ss.get("grid_action"))
        self.assertFalse(ss["grid_await_confirm"])
        self.assertNotIn("grid_pending_sweep", ss)

        ss = {"grid_action": "summarize", "grid_run_ok": False}
        _apply_run_dismissed(ss)
        self.assertEqual(ss["grid_action"], "summarize")

    def test_dismiss_after_confirm_does_not_reset(self) -> None:
        ss: dict = {}
        _begin_run_request(ss)
        _apply_run_confirmed(ss)
        _apply_run_dismissed(ss)
        self.assertTrue(ss["grid_run_ok"])
        self.assertEqual(ss["grid_action"], "run")
        self.assertTrue(ss["grid_yield_for_dialog"])
        self.assertFalse(_needs_run_confirm(ss))


if __name__ == "__main__":
    unittest.main()
