# coding: utf-8
"""第 2 步回放基线：成交笔数 / reason / 期末仓 + 现网评槽抽样。"""
from __future__ import annotations

import json
import unittest

from freeze_recipe_baseline import FIXTURE, snapshot


class RecipeBaselineTests(unittest.TestCase):
    def test_replay_matches_frozen(self) -> None:
        self.assertTrue(FIXTURE.is_file(), "missing %s" % FIXTURE)
        frozen = json.loads(FIXTURE.read_text(encoding="utf-8"))
        got = snapshot()
        self.assertEqual(got["n_trades"], frozen["n_trades"])
        self.assertEqual(got["end_pos"], frozen["end_pos"])
        self.assertEqual(got["reasons"], frozen["reasons"])
        self.assertEqual(got["trades"], frozen["trades"])
        self.assertEqual(got["eval_cases"], frozen["eval_cases"])


if __name__ == "__main__":
    unittest.main()
