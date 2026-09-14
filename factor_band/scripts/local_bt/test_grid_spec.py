# coding: utf-8
"""grid_spec：单族 / 笛卡尔积 / kind / TRAIL patch / 导入纠正。"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from grid_spec import (  # noqa: E402
    GridSpecError,
    auto_sweep_name,
    axes_from_cells,
    axes_from_selection,
    build_cells,
    catalog_ids,
    correct_cell_kinds,
    default_param_selection,
    family_token,
    family_value_label,
    fill_year_windows,
    generator_locked,
    infer_kind,
    keep_from_cells,
    make_spec,
    merge_param_selection,
    overrides_summary,
    parse_scan_token,
    parse_scan_values,
    param_catalog,
    product_count,
    reject_retired_min_ret,
    struct_eq,
    sweep_stem_from_axes,
    unique_levels,
    validate_trail_tiers,
    validate_year_windows,
    trail_table_summary,
)

DEFAULTS = {
    "atr_stop.k": 2.0,
    "atr_trail_stop.k1": 2.0,
    "atr_trail_stop.k2": 2.0,
    "keltner_vol.k": 2.0,
    "keltner_vol.ratio": 0.9,
    "keltner_vol.vol_n": 10,
    "keltner_vol.confirm_days": 2,
    "ema.1d.mid": 20,
    "stop_loss.pct": 0.08,
    "time_force.bars": 30,
    "trail_stop.tiers": (
        (0.03, 0.06, 0.015, None),
        (0.06, 0.10, 0.03, 0.03),
        (0.10, None, 0.04, None),
    ),
    "chase.max_pct": 0.05,
}
CUR_TIERS = [
    [0.03, 0.06, 0.015, None],
    [0.06, 0.10, 0.03, 0.03],
    [0.10, None, 0.04, None],
]


def _sl(pct: float) -> dict:
    return {"factor_params": {"stop_loss": {"pct": pct}}}


def _ask(k: float) -> dict:
    return {"factor_params": {"atr_stop": {"k": k}}}


class GridSpecTest(unittest.TestCase):
    def test_atr_stop_default_chips(self) -> None:
        cells = build_cells({"atr_stop.k": [1.5, 2.5]}, DEFAULTS)
        ids = [c["id"] for c in cells]
        self.assertEqual(ids, ["ask1p5", "ask2p5"])
        by = {c["id"]: c for c in cells}
        self.assertFalse(by["ask1p5"]["is_current"])
        self.assertEqual(by["ask1p5"]["kind"], "tighten")
        self.assertEqual(by["ask1p5"]["overrides"]["factor_params"]["atr_stop"]["k"], 1.5)
        self.assertEqual(by["ask2p5"]["kind"], "loosen")
        self.assertEqual(by["ask2p5"]["overrides"]["factor_params"]["atr_stop"]["k"], 2.5)

    def test_scan_includes_current_marks(self) -> None:
        cells = build_cells({"atr_stop.k": [1.5, 2.0, 2.5]}, DEFAULTS)
        ids = [c["id"] for c in cells]
        self.assertEqual(set(ids), {"ask1p5", "ask2", "ask2p5"})
        by = {c["id"]: c for c in cells}
        self.assertTrue(by["ask2"]["is_current"])
        self.assertEqual(by["ask2"]["n_diffs"], 0)
        self.assertTrue(by["ask1p5"]["recipe"])
        self.assertNotEqual(by["ask1p5"]["recipe"], by["ask2"]["recipe"])
        self.assertAlmostEqual(by["ask2"]["overrides"]["factor_params"]["atr_stop"]["k"], 2.0)
        self.assertIn("★现行", by["ask2"]["label"])
        self.assertFalse(by["ask1p5"]["is_current"])

    def test_cartesian_ask_and_keltner_ratio(self) -> None:
        cells = build_cells(
            {"atr_stop.k": [1.5, 2.5], "keltner_vol.ratio": [0.8]},
            DEFAULTS,
        )
        ids = [c["id"] for c in cells]
        self.assertEqual(set(ids), {"ask1p5_kvr80", "ask2p5_kvr80"})
        self.assertEqual(len(cells), 2)
        by = {c["id"]: c for c in cells}
        cid = "ask1p5_kvr80"
        self.assertEqual(by[cid]["kind"], "other")
        self.assertEqual(set(by[cid]["overrides"]), {"factor_params"})
        self.assertAlmostEqual(by[cid]["overrides"]["factor_params"]["keltner_vol"]["ratio"], 0.8)
        self.assertAlmostEqual(by[cid]["overrides"]["factor_params"]["atr_stop"]["k"], 1.5)

    def test_product_count(self) -> None:
        self.assertEqual(product_count({"atr_stop.k": [1.5, 2.5]}, DEFAULTS), 2)
        self.assertEqual(
            product_count(
                {"atr_stop.k": [1.5, 2.5], "keltner_vol.ratio": [0.8]},
                DEFAULTS,
            ),
            2,
        )
        self.assertEqual(product_count({}, DEFAULTS), 0)

    def test_empty_scan_raises(self) -> None:
        with self.assertRaises(GridSpecError) as ctx:
            unique_levels("atr_stop.k", [], DEFAULTS)
        self.assertIn("扫描取值", str(ctx.exception))
        with self.assertRaises(GridSpecError):
            build_cells({"atr_stop.k": []}, DEFAULTS)

    def test_unused_axis_raises(self) -> None:
        with self.assertRaises(GridSpecError) as ctx:
            build_cells({"stop_loss.pct": [0.06, 0.10]}, DEFAULTS)
        self.assertIn("stop_loss.pct", str(ctx.exception))

    def test_atr_stop_zero_is_off(self) -> None:
        cells = build_cells({"atr_stop.k": [0]}, DEFAULTS)
        by = {c["id"]: c for c in cells}
        self.assertEqual(by["ask0"]["kind"], "off")
        self.assertEqual(by["ask0"]["overrides"]["factor_params"]["atr_stop"]["k"], 0)

    def test_dma_mid_zero_label(self) -> None:
        self.assertEqual(family_value_label("ema.1d.mid", 0), "日线中均线关闭")
        self.assertEqual(family_value_label("ema.1d.slow", 0), "日线慢均线关闭")
        defs = dict(DEFAULTS)
        defs["ema.1d.mid"] = 20
        cells = build_cells({"ema.1d.mid": [0]}, defs)
        by = {c["id"]: c for c in cells}
        self.assertEqual(by["e1dm0"]["kind"], "other")
        self.assertEqual(by["e1dm0"]["label"], "日线中均线关闭")
        self.assertEqual(by["e1dm0"]["overrides"]["structure"]["ema"]["1d"]["mid"], 0)

    def test_structure_deep_merge_keeps_siblings(self) -> None:
        from grid_spec import deep_merge_structure

        base = {"ema": {"1d": {"mid": 20, "slow": 60, "trend": 120}}}
        merged = deep_merge_structure(base, {"ema": {"1d": {"trend": 150}}})
        self.assertEqual(merged["ema"]["1d"]["mid"], 20)
        self.assertEqual(merged["ema"]["1d"]["slow"], 60)
        self.assertEqual(merged["ema"]["1d"]["trend"], 150)

    def test_trail_tiers_rejects_hi_le_lo(self) -> None:
        bad = [
            [0.06, 0.06, 0.015, None],
            [0.06, 0.10, 0.03, 0.03],
            [0.10, None, 0.04, None],
        ]
        with self.assertRaises(GridSpecError) as ctx:
            validate_trail_tiers(bad)
        self.assertIn("上限", str(ctx.exception))

    def test_keep_label_on_rebuild(self) -> None:
        first = build_cells({"atr_stop.k": [1.5, 2.5]}, DEFAULTS)
        for c in first:
            if c["id"] == "ask1p5":
                c["label"] = "手改ATR1.5"
                c["kind"] = "other"
        keep = keep_from_cells(first)
        second = build_cells({"atr_stop.k": [1.5, 2.5]}, DEFAULTS, keep=keep)
        by = {c["id"]: c for c in second}
        self.assertEqual(by["ask1p5"]["label"], "手改ATR1.5")
        self.assertEqual(by["ask1p5"]["kind"], "other")

    def test_correct_illegal_kind_inline(self) -> None:
        raw = [
            {"id": "base", "kind": "base", "overrides": {}},
            {"id": "ask1p5", "kind": "sl06", "overrides": _ask(1.5)},
        ]
        fixed = correct_cell_kinds(raw, DEFAULTS)
        self.assertEqual(fixed[1]["kind"], "tighten")
        path = REPO / ".cursor" / "skills" / "qmt-local-bt-grid" / "examples" / "stop_loss.json"
        spec = json.loads(path.read_text(encoding="utf-8"))
        fixed = correct_cell_kinds(spec["cells"], DEFAULTS)
        by = {c["id"]: c for c in fixed}
        self.assertEqual(by["base"]["kind"], "base")
        self.assertEqual(by["ask1p5"]["kind"], "tighten")
        self.assertEqual(by["ask2p5"]["kind"], "loosen")
        axes = axes_from_cells(fixed, DEFAULTS)
        self.assertIn("atr_stop.k", axes)
        self.assertFalse(generator_locked(fixed))

    def test_infer_kind_atr_stop(self) -> None:
        self.assertEqual(infer_kind("atr_stop.k", 1.5, DEFAULTS), "tighten")
        self.assertEqual(infer_kind("atr_stop.k", 2.5, DEFAULTS), "loosen")
        self.assertEqual(infer_kind("atr_stop.k", 0, DEFAULTS), "off")

    def test_infer_kind_atr_trail(self) -> None:
        from grid_run import load_config_defaults

        defaults = load_config_defaults()
        self.assertEqual(infer_kind("atr_trail_stop.k1", 1, defaults), "tighten")
        self.assertEqual(infer_kind("atr_trail_stop.k1", 1.5, defaults), "tighten")
        self.assertEqual(infer_kind("atr_trail_stop.k2", 3, defaults), "loosen")
        self.assertEqual(infer_kind("atr_trail_stop.k1", 0, defaults), "off")

    def test_unknown_keys_lock_generator(self) -> None:
        cells = [
            {"id": "base", "kind": "base", "overrides": {}},
            {"id": "x", "kind": "other", "overrides": {"NOT_A_CONFIG": 0.1}},
        ]
        self.assertTrue(generator_locked(cells))
        known = [
            {"id": "base", "kind": "base", "overrides": {}},
            {
                "id": "ch03",
                "kind": "other",
                "overrides": {"factor_params": {"chase": {"max_pct": 0.03}}},
            },
        ]
        self.assertFalse(generator_locked(known))
        dotted = [
            {"id": "sl06", "kind": "other", "overrides": {"stop_loss.pct": 0.06}},
        ]
        self.assertTrue(generator_locked(dotted))

    def test_overrides_summary(self) -> None:
        self.assertEqual(overrides_summary({}), "（无覆盖）")
        self.assertIn("stop_loss.pct=0.06", overrides_summary(_sl(0.06)))

    def test_catalog_includes_entry_not_infra(self) -> None:
        ids = catalog_ids()
        self.assertIn("keltner_vol.k", ids)
        self.assertIn("keltner_vol.ratio", ids)
        self.assertIn("keltner_vol.vol_n", ids)
        self.assertIn("keltner_vol.confirm_days", ids)
        self.assertIn("atr_stop.k", ids)
        self.assertIn("atr_trail_stop.k1", ids)
        self.assertIn("atr_trail_stop.k2", ids)
        self.assertNotIn("chase.max_pct", ids)
        self.assertNotIn("w_bias.hard", ids)
        self.assertNotIn("pullback_vol.tol", ids)
        self.assertNotIn("pullback_vol.confirm_days", ids)
        self.assertNotIn("stop_loss.pct", ids)
        self.assertNotIn("time_force.arm", ids)
        self.assertNotIn("time_force.bars", ids)
        self.assertNotIn("trail_stop.tiers", ids)
        self.assertIn("atr.n", ids)
        self.assertIn("ema.1d.trend", ids)
        self.assertIn("keltner.ema_n", ids)
        self.assertIn("keltner.atr_n", ids)
        self.assertNotIn("TRAIL", ids)
        self.assertNotIn("STOP_LOSS", ids)
        self.assertNotIn("STATE_FILE", ids)
        self.assertNotIn("DRY_RUN", ids)
        ask = next(p for p in param_catalog() if p.id == "atr_stop.k")
        self.assertEqual(ask.dtype, "float")
        self.assertEqual(ask.abbrev, "ask")
        self.assertEqual(ask.kind_mode, "exit")
        k1 = next(p for p in param_catalog() if p.id == "atr_trail_stop.k1")
        self.assertEqual(k1.dtype, "float")
        self.assertEqual(k1.abbrev, "atk1")
        self.assertEqual(k1.kind_mode, "exit")
        k2 = next(p for p in param_catalog() if p.id == "atr_trail_stop.k2")
        self.assertEqual(k2.dtype, "float")
        self.assertEqual(k2.abbrev, "atk2")
        self.assertNotEqual(k2.dtype, "percent")
        kvr = next(p for p in param_catalog() if p.id == "keltner_vol.ratio")
        self.assertEqual(kvr.dtype, "percent")
        self.assertEqual(kvr.abbrev, "kvr")

    def test_parse_percent_and_int(self) -> None:
        self.assertAlmostEqual(parse_scan_token("keltner_vol.ratio", "80"), 0.80)
        self.assertAlmostEqual(parse_scan_token("keltner_vol.ratio", "0.8"), 0.80)
        self.assertAlmostEqual(parse_scan_token("keltner_vol.ratio", "80%"), 0.80)
        self.assertAlmostEqual(parse_scan_token("keltner_vol.ratio", "80％"), 0.80)
        self.assertEqual(parse_scan_token("keltner_vol.vol_n", "8"), 8)
        self.assertEqual(parse_scan_token("keltner_vol.confirm_days", "3"), 3)
        self.assertEqual(parse_scan_values("keltner_vol.ratio", "80, 90"), [0.80, 0.90])
        self.assertEqual(parse_scan_values("keltner_vol.ratio", "80% 90%"), [0.80, 0.90])
        self.assertEqual(parse_scan_values("keltner_vol.ratio", "80%,90%"), [0.80, 0.90])

    def test_atr_multiplier_float_scan(self) -> None:
        from grid_run import load_config_defaults

        self.assertAlmostEqual(parse_scan_token("atr_stop.k", "1.5"), 1.5)
        self.assertEqual(parse_scan_values("atr_stop.k", "1.5,2,2.5"), [1.5, 2.0, 2.5])
        self.assertEqual(parse_scan_values("atr_trail_stop.k1", "1.5 2.0"), [1.5, 2.0])
        self.assertEqual(parse_scan_values("atr_trail_stop.k2", "1.5"), [1.5])
        self.assertEqual(family_token("atr_stop.k", 1.5), "ask1p5")
        self.assertEqual(family_token("atr_trail_stop.k1", 1.5), "atk11p5")
        defaults = load_config_defaults()
        cells = build_cells({"atr_stop.k": [1.5, 2.0]}, defaults)
        by = {c["id"]: c for c in cells}
        self.assertEqual(by["ask1p5"]["overrides"]["factor_params"]["atr_stop"]["k"], 1.5)
        self.assertFalse(by["ask1p5"]["is_current"])
        self.assertEqual(by["ask1p5"]["kind"], "tighten")
        self.assertTrue(by["ask2"]["is_current"])

    def test_cartesian_ask_and_vol_n(self) -> None:
        cells = build_cells(
            {"atr_stop.k": [1.5, 2.5], "keltner_vol.vol_n": [8]},
            DEFAULTS,
        )
        ids = [c["id"] for c in cells]
        self.assertIn("ask1p5_kvn8", ids)
        self.assertEqual(len(cells), 2)
        by = {c["id"]: c for c in cells}
        self.assertEqual(by["ask1p5_kvn8"]["kind"], "other")
        self.assertEqual(by["ask1p5_kvn8"]["overrides"]["factor_params"]["keltner_vol"]["vol_n"], 8)
        self.assertEqual(set(by["ask1p5_kvn8"]["overrides"]), {"factor_params"})

    def test_default_selection_none(self) -> None:
        sel = default_param_selection()
        self.assertFalse(sel["atr_stop.k"]["selected"])
        self.assertFalse(any(rec.get("selected") for rec in sel.values()))
        axes = axes_from_selection(sel)
        self.assertEqual(axes, {})
        cells = build_cells(axes, DEFAULTS)
        self.assertEqual(cells, [])

    def test_axes_from_cells_keeps_current_level(self) -> None:
        cells = build_cells({"atr_stop.k": [1.5, 2.0, 2.5]}, DEFAULTS)
        axes = axes_from_cells(cells, DEFAULTS)
        self.assertIn("atr_stop.k", axes)
        vals = axes["atr_stop.k"]
        self.assertTrue(any(abs(float(v) - 2.0) < 1e-9 for v in vals))
        self.assertTrue(any(abs(float(v) - 1.5) < 1e-9 for v in vals))

    def test_merge_param_selection_fills_new_catalog_keys(self) -> None:
        stale = {"stop_loss.pct": {"selected": True, "scan": "6,10"}}
        merged = merge_param_selection(stale)
        self.assertNotIn("stop_loss.pct", merged)
        self.assertNotIn("pullback_vol.confirm_days", merged)
        self.assertIn("keltner_vol.confirm_days", merged)
        self.assertFalse(merged["keltner_vol.confirm_days"]["selected"])
        self.assertIn("atr_stop.k", merged)
        self.assertFalse(merged["atr_stop.k"]["selected"])
        self.assertNotIn("NOT_A_CONFIG", merged)

    def test_merge_drops_legacy_trail_axis(self) -> None:
        stale = {
            "TRAIL": {"selected": True, "scan": "4"},
            "stop_loss.pct": {"selected": True, "scan": "6,10"},
        }
        merged = merge_param_selection(stale)
        self.assertNotIn("TRAIL", merged)
        self.assertNotIn("trail_stop.tiers", merged)
        self.assertNotIn("stop_loss.pct", merged)
        self.assertIn("atr_stop.k", merged)
        self.assertFalse(merged["atr_stop.k"]["selected"])

    def test_trail_table_summary_in_label(self) -> None:
        self.assertEqual(
            trail_table_summary(CUR_TIERS),
            "3%/1.5% · 6%/3%/底3% · 10%/4%",
        )

    def test_year_windows_fill_and_overlap(self) -> None:
        filled = fill_year_windows({})
        self.assertEqual(filled["year_start"], 2018)
        self.assertEqual(filled["check_end"], 2026)
        spec = make_spec([{"id": "base", "kind": "base", "overrides": {}}], sweep="t")
        self.assertEqual(spec["tune_end"], 2022)
        with self.assertRaises(GridSpecError) as ctx:
            validate_year_windows(
                {
                    "year_start": 2018,
                    "year_end": 2026,
                    "tune_start": 2018,
                    "tune_end": 2023,
                    "check_start": 2023,
                    "check_end": 2026,
                }
            )
        self.assertIn("重叠", str(ctx.exception))
        ok = validate_year_windows(
            {
                "year_start": 2020,
                "year_end": 2024,
                "tune_start": 2020,
                "tune_end": 2021,
                "check_start": 2023,
                "check_end": 2024,
            }
        )
        self.assertEqual(ok["tune_end"], 2021)

    def test_auto_sweep_name_from_axes(self) -> None:
        axes = {
            "keltner_vol.vol_n": [15],
            "keltner_vol.confirm_days": [1, 3],
        }
        self.assertEqual(sweep_stem_from_axes(axes), "kvn_kvc")
        when = datetime(2026, 9, 7, 20, 34, 12)
        self.assertEqual(
            auto_sweep_name(axes, when=when),
            "kvn_kvc_20260907_203412",
        )
        self.assertEqual(sweep_stem_from_axes({}), "grid")
        taken = auto_sweep_name({}, when=when, existing=["grid_20260907_203412"])
        self.assertEqual(taken, "grid_20260907_203412_2")

    def test_catalog_omits_retired_knobs(self) -> None:
        ids = catalog_ids()
        self.assertNotIn("TIME_FORCE_MIN_RET", ids)
        self.assertNotIn("TIME_FORCE_GRACE_BARS", ids)
        self.assertNotIn("SCALE_MAX", ids)
        self.assertNotIn("W_MA_MID", ids)
        self.assertNotIn("W_MA_SLOW", ids)
        self.assertNotIn("D_MA_MID", ids)
        self.assertIn("ema.1d.mid", ids)
        self.assertIn("ema.1w.mid", ids)
        self.assertNotIn("SCALE_ARM", ids)
        self.assertNotIn("SCALE_ARM_BARS", ids)
        self.assertNotIn("SCALE_W_HIST_MIN", ids)
        self.assertNotIn("scale_arm.arm", ids)
        self.assertNotIn("scale_arm.bars", ids)
        self.assertNotIn("scale_arm.hist_min", ids)
        self.assertNotIn("time_force.bars", ids)

    def test_reject_retired_min_ret_spec(self) -> None:
        with self.assertRaises(GridSpecError) as ctx:
            reject_retired_min_ret(
                {
                    "cells": [
                        {
                            "id": "tfm0",
                            "overrides": {"TIME_FORCE_MIN_RET": 0.0},
                        }
                    ]
                }
            )
        self.assertIn("TIME_FORCE_MIN_RET", str(ctx.exception))

    def test_reject_retired_grace_spec(self) -> None:
        with self.assertRaises(GridSpecError) as ctx:
            reject_retired_min_ret(
                {
                    "cells": [
                        {
                            "id": "tfg5",
                            "overrides": {"TIME_FORCE_GRACE_BARS": 5},
                        }
                    ]
                }
            )
        self.assertIn("TIME_FORCE_GRACE_BARS", str(ctx.exception))

    def test_reject_old_scale_arm_key(self) -> None:
        with self.assertRaises(GridSpecError) as ctx:
            reject_retired_min_ret(
                {
                    "cells": [
                        {"id": "sa3", "overrides": {"SCALE_ARM": 0.03}},
                    ]
                }
            )
        self.assertIn("SCALE_ARM", str(ctx.exception))

    def test_reject_old_factor_key(self) -> None:
        with self.assertRaises(GridSpecError) as ctx:
            reject_retired_min_ret(
                {
                    "cells": [
                        {"id": "sl06", "overrides": {"STOP_LOSS": 0.06}},
                    ]
                }
            )
        self.assertIn("STOP_LOSS", str(ctx.exception))

    def test_reject_flat_factor_path(self) -> None:
        with self.assertRaises(GridSpecError) as ctx:
            reject_retired_min_ret(
                {
                    "cells": [
                        {"id": "sl06", "overrides": {"stop_loss.pct": 0.06}},
                    ]
                }
            )
        self.assertIn("stop_loss.pct", str(ctx.exception))
        self.assertIn("factor_params", str(ctx.exception))

    def test_reject_old_structure_key(self) -> None:
        with self.assertRaises(GridSpecError) as ctx:
            reject_retired_min_ret(
                {
                    "cells": [
                        {"id": "dmm15", "overrides": {"D_MA_MID": 15}},
                    ]
                }
            )
        self.assertIn("D_MA_MID", str(ctx.exception))

    def test_reject_flat_structure_path(self) -> None:
        with self.assertRaises(GridSpecError) as ctx:
            reject_retired_min_ret(
                {
                    "cells": [
                        {"id": "e1dm15", "overrides": {"d_ma.mid": 15}},
                    ]
                }
            )
        self.assertIn("d_ma.mid", str(ctx.exception))
        self.assertIn("structure", str(ctx.exception))

    def test_reject_nested_old_structure_root(self) -> None:
        with self.assertRaises(GridSpecError) as ctx:
            reject_retired_min_ret(
                {
                    "cells": [
                        {"id": "x", "overrides": {"structure": {"d_ma": {"mid": 15}}}},
                    ]
                }
            )
        self.assertIn("d_ma", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
