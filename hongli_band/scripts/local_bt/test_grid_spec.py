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
    coerce_level,
    correct_cell_kinds,
    default_param_selection,
    family_token,
    family_value_label,
    fill_year_windows,
    format_scan_values,
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
    validate_year_windows,
)

DEFAULTS = {
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
ARM04_TIERS = [
    [0.04, 0.06, 0.015, None],
    [0.06, 0.10, 0.03, 0.03],
    [0.10, None, 0.04, None],
]
GB02_TIERS = [
    [0.03, 0.06, 0.02, None],
    [0.06, 0.10, 0.03, 0.03],
    [0.10, None, 0.04, None],
]


def _sl(pct: float) -> dict:
    return {"factor_params": {"stop_loss": {"pct": pct}}}


class GridSpecTest(unittest.TestCase):
    def test_stop_loss_default_chips(self) -> None:
        cells = build_cells({"stop_loss.pct": [0.06, 0.10]}, DEFAULTS)
        ids = [c["id"] for c in cells]
        self.assertEqual(ids, ["sl06", "sl10"])
        by = {c["id"]: c for c in cells}
        self.assertFalse(by["sl06"]["is_current"])
        self.assertEqual(by["sl06"]["kind"], "tighten")
        self.assertEqual(by["sl06"]["overrides"]["factor_params"]["stop_loss"]["pct"], 0.06)
        self.assertEqual(by["sl10"]["kind"], "loosen")
        self.assertEqual(by["sl10"]["overrides"]["factor_params"]["stop_loss"]["pct"], 0.10)

    def test_scan_includes_current_marks(self) -> None:
        cells = build_cells({"stop_loss.pct": [0.06, 0.08, 0.10]}, DEFAULTS)
        ids = [c["id"] for c in cells]
        self.assertEqual(set(ids), {"sl06", "sl08", "sl10"})
        by = {c["id"]: c for c in cells}
        self.assertTrue(by["sl08"]["is_current"])
        self.assertEqual(by["sl08"]["n_diffs"], 0)
        self.assertTrue(by["sl06"]["recipe"])
        self.assertNotEqual(by["sl06"]["recipe"], by["sl08"]["recipe"])
        self.assertAlmostEqual(by["sl08"]["overrides"]["factor_params"]["stop_loss"]["pct"], 0.08)
        self.assertIn("★现行", by["sl08"]["label"])
        self.assertFalse(by["sl06"]["is_current"])

    def test_cartesian_stop_and_trail(self) -> None:
        cells = build_cells(
            {"stop_loss.pct": [0.06, 0.10], "trail_stop.tiers": [ARM04_TIERS]},
            DEFAULTS,
        )
        tok = family_token("trail_stop.tiers", coerce_level("trail_stop.tiers", ARM04_TIERS))
        ids = [c["id"] for c in cells]
        self.assertEqual(set(ids), {"sl06_%s" % tok, "sl10_%s" % tok})
        self.assertEqual(len(cells), 2)
        by = {c["id"]: c for c in cells}
        cid = "sl06_%s" % tok
        self.assertEqual(by[cid]["kind"], "other")
        self.assertEqual(set(by[cid]["overrides"]), {"factor_params"})
        self.assertTrue(
            struct_eq(by[cid]["overrides"]["factor_params"]["trail_stop"]["tiers"], ARM04_TIERS)
        )
        self.assertAlmostEqual(
            by[cid]["overrides"]["factor_params"]["trail_stop"]["tiers"][0][0], 0.04
        )

    def test_product_count(self) -> None:
        self.assertEqual(product_count({"stop_loss.pct": [0.06, 0.10]}, DEFAULTS), 2)
        self.assertEqual(
            product_count(
                {"stop_loss.pct": [0.06, 0.10], "trail_stop.tiers": [ARM04_TIERS]},
                DEFAULTS,
            ),
            2,
        )
        self.assertEqual(product_count({}, DEFAULTS), 0)

    def test_empty_scan_raises(self) -> None:
        with self.assertRaises(GridSpecError) as ctx:
            unique_levels("stop_loss.pct", [], DEFAULTS)
        self.assertIn("扫描取值", str(ctx.exception))
        with self.assertRaises(GridSpecError):
            build_cells({"stop_loss.pct": []}, DEFAULTS)

    def test_bars_zero_is_off(self) -> None:
        cells = build_cells({"time_force.bars": [0]}, DEFAULTS)
        by = {c["id"]: c for c in cells}
        self.assertEqual(by["tfb0"]["kind"], "off")
        self.assertEqual(by["tfb0"]["overrides"]["factor_params"]["time_force"]["bars"], 0)

    def test_dma_mid_zero_label(self) -> None:
        self.assertEqual(family_value_label("d_ma.mid", 0), "日线中均线关闭")
        self.assertEqual(family_value_label("d_ma.slow", 0), "日线慢均线关闭")
        defs = dict(DEFAULTS)
        defs["d_ma.mid"] = 20
        cells = build_cells({"d_ma.mid": [0]}, defs)
        by = {c["id"]: c for c in cells}
        self.assertEqual(by["dmm0"]["kind"], "other")
        self.assertEqual(by["dmm0"]["label"], "日线中均线关闭")
        self.assertEqual(by["dmm0"]["overrides"]["structure"]["d_ma"]["mid"], 0)

    def test_trail_tiers_rejects_hi_le_lo(self) -> None:
        bad = [
            [0.06, 0.06, 0.015, None],
            [0.06, 0.10, 0.03, 0.03],
            [0.10, None, 0.04, None],
        ]
        with self.assertRaises(GridSpecError) as ctx:
            unique_levels("trail_stop.tiers", [bad], DEFAULTS)
        self.assertIn("上限", str(ctx.exception))

    def test_keep_label_on_rebuild(self) -> None:
        first = build_cells({"stop_loss.pct": [0.06, 0.10]}, DEFAULTS)
        for c in first:
            if c["id"] == "sl06":
                c["label"] = "手改止损6"
                c["kind"] = "other"
        keep = keep_from_cells(first)
        second = build_cells({"stop_loss.pct": [0.06, 0.10]}, DEFAULTS, keep=keep)
        by = {c["id"]: c for c in second}
        self.assertEqual(by["sl06"]["label"], "手改止损6")
        self.assertEqual(by["sl06"]["kind"], "other")

    def test_correct_illegal_kind_inline(self) -> None:
        raw = [
            {"id": "base", "kind": "base", "overrides": {}},
            {"id": "sl06", "kind": "sl06", "overrides": _sl(0.06)},
        ]
        fixed = correct_cell_kinds(raw, DEFAULTS)
        self.assertEqual(fixed[1]["kind"], "tighten")
        path = REPO / ".cursor" / "skills" / "qmt-local-bt-grid" / "examples" / "stop_loss.json"
        spec = json.loads(path.read_text(encoding="utf-8"))
        fixed = correct_cell_kinds(spec["cells"], DEFAULTS)
        by = {c["id"]: c for c in fixed}
        self.assertEqual(by["base"]["kind"], "base")
        self.assertEqual(by["sl06"]["kind"], "tighten")
        self.assertEqual(by["sl10"]["kind"], "loosen")
        axes = axes_from_cells(fixed, DEFAULTS)
        self.assertIn("stop_loss.pct", axes)
        self.assertFalse(generator_locked(fixed))

    def test_infer_kind_stop(self) -> None:
        self.assertEqual(infer_kind("stop_loss.pct", 0.06, DEFAULTS), "tighten")
        self.assertEqual(infer_kind("stop_loss.pct", 0.10, DEFAULTS), "loosen")

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
        self.assertIn("chase.max_pct", ids)
        self.assertIn("w_bias.hard", ids)
        self.assertIn("pullback_vol.tol", ids)
        self.assertIn("pullback_vol.confirm_days", ids)
        self.assertIn("stop_loss.pct", ids)
        self.assertIn("atr_stop.k", ids)
        self.assertIn("atr.n", ids)
        self.assertIn("trail_stop.tiers", ids)
        self.assertNotIn("TRAIL", ids)
        self.assertNotIn("STOP_LOSS", ids)
        self.assertNotIn("STATE_FILE", ids)
        self.assertNotIn("DRY_RUN", ids)
        spec = next(p for p in param_catalog() if p.id == "trail_stop.tiers")
        self.assertEqual(spec.key, "trail_stop.tiers")
        self.assertEqual(spec.dtype, "tuple")
        self.assertEqual(spec.abbrev, "tt")
        self.assertEqual(spec.kind_mode, "exit")

    def test_parse_percent_and_int(self) -> None:
        self.assertAlmostEqual(parse_scan_token("stop_loss.pct", "6"), 0.06)
        self.assertAlmostEqual(parse_scan_token("stop_loss.pct", "0.06"), 0.06)
        self.assertAlmostEqual(parse_scan_token("stop_loss.pct", "6%"), 0.06)
        self.assertAlmostEqual(parse_scan_token("stop_loss.pct", "6％"), 0.06)
        self.assertEqual(parse_scan_token("pullback_vol.vol_n", "8"), 8)
        self.assertEqual(parse_scan_token("pullback_vol.confirm_days", "3"), 3)
        self.assertEqual(parse_scan_values("stop_loss.pct", "6, 10"), [0.06, 0.10])
        self.assertEqual(parse_scan_values("stop_loss.pct", "6% 10%"), [0.06, 0.10])
        self.assertEqual(parse_scan_values("stop_loss.pct", "6%,10%"), [0.06, 0.10])
        self.assertEqual(parse_scan_values("chase.max_pct", "3 7"), [0.03, 0.07])

    def test_cartesian_stop_and_chase(self) -> None:
        cells = build_cells(
            {"stop_loss.pct": [0.06, 0.10], "chase.max_pct": [0.03]},
            DEFAULTS,
        )
        ids = [c["id"] for c in cells]
        self.assertIn("sl06_ch03", ids)
        self.assertEqual(len(cells), 2)
        by = {c["id"]: c for c in cells}
        self.assertEqual(by["sl06_ch03"]["kind"], "other")
        self.assertAlmostEqual(
            by["sl06_ch03"]["overrides"]["factor_params"]["chase"]["max_pct"], 0.03
        )
        self.assertEqual(set(by["sl06_ch03"]["overrides"]), {"factor_params"})

    def test_default_selection_none(self) -> None:
        sel = default_param_selection()
        self.assertFalse(sel["stop_loss.pct"]["selected"])
        self.assertFalse(any(rec.get("selected") for rec in sel.values()))
        axes = axes_from_selection(sel)
        self.assertEqual(axes, {})
        cells = build_cells(axes, DEFAULTS)
        self.assertEqual(cells, [])

    def test_axes_from_cells_keeps_current_level(self) -> None:
        cells = build_cells({"stop_loss.pct": [0.06, 0.08, 0.10]}, DEFAULTS)
        axes = axes_from_cells(cells, DEFAULTS)
        self.assertIn("stop_loss.pct", axes)
        vals = axes["stop_loss.pct"]
        self.assertTrue(any(abs(float(v) - 0.08) < 1e-9 for v in vals))
        self.assertTrue(any(abs(float(v) - 0.06) < 1e-9 for v in vals))

    def test_merge_param_selection_fills_new_catalog_keys(self) -> None:
        stale = {"stop_loss.pct": {"selected": True, "scan": "6,10"}}
        merged = merge_param_selection(stale)
        self.assertIn("pullback_vol.confirm_days", merged)
        self.assertFalse(merged["pullback_vol.confirm_days"]["selected"])
        self.assertTrue(merged["stop_loss.pct"]["selected"])
        self.assertEqual(merged["stop_loss.pct"]["scan"], "6,10")
        self.assertNotIn("NOT_A_CONFIG", merged)

    def test_merge_drops_legacy_trail_axis(self) -> None:
        stale = {
            "TRAIL": {"selected": True, "scan": "4"},
            "stop_loss.pct": {"selected": True, "scan": "6,10"},
        }
        merged = merge_param_selection(stale)
        self.assertNotIn("TRAIL", merged)
        self.assertIn("trail_stop.tiers", merged)
        self.assertFalse(merged["trail_stop.tiers"]["selected"])
        self.assertTrue(merged["stop_loss.pct"]["selected"])

    def test_trail_json_scan_and_newline_roundtrip(self) -> None:
        scan = json.dumps(ARM04_TIERS, ensure_ascii=False, separators=(",", ":"))
        vals = parse_scan_values("trail_stop.tiers", scan)
        self.assertEqual(len(vals), 1)
        self.assertTrue(struct_eq(vals[0], ARM04_TIERS))
        text = format_scan_values("trail_stop.tiers", [CUR_TIERS, ARM04_TIERS])
        self.assertIn("\n", text)
        parsed = parse_scan_values("trail_stop.tiers", text)
        self.assertEqual(len(parsed), 2)
        self.assertTrue(struct_eq(parsed[0], CUR_TIERS))
        self.assertTrue(struct_eq(parsed[1], ARM04_TIERS))

    def test_trail_list_tuple_marks_current(self) -> None:
        cells = build_cells({"trail_stop.tiers": [CUR_TIERS]}, DEFAULTS)
        self.assertEqual(len(cells), 1)
        self.assertTrue(cells[0]["is_current"])
        self.assertEqual(cells[0]["n_diffs"], 0)
        self.assertIn("★现行", cells[0]["label"])

    def test_trail_only_arm_is_tighten(self) -> None:
        tight = [
            [0.02, 0.06, 0.015, None],
            [0.06, 0.10, 0.03, 0.03],
            [0.10, None, 0.04, None],
        ]
        cells = build_cells({"trail_stop.tiers": [tight]}, DEFAULTS)
        self.assertEqual(cells[0]["kind"], "tighten")
        self.assertFalse(cells[0]["is_current"])
        self.assertEqual(infer_kind("trail_stop.tiers", tight, DEFAULTS), "tighten")

    def test_trail_giveback_change_is_other(self) -> None:
        cells = build_cells({"trail_stop.tiers": [GB02_TIERS]}, DEFAULTS)
        self.assertEqual(cells[0]["kind"], "other")
        self.assertFalse(cells[0]["is_current"])

    def test_trail_table_summary_in_label(self) -> None:
        self.assertEqual(
            family_value_label("trail_stop.tiers", CUR_TIERS),
            "阶梯止盈 3%/1.5% · 6%/3%/底3% · 10%/4%",
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
            "pullback_vol.vol_n": [15],
            "pullback_vol.confirm_days": [1, 3],
        }
        self.assertEqual(sweep_stem_from_axes(axes), "vpn_vpc")
        when = datetime(2026, 9, 7, 20, 34, 12)
        self.assertEqual(
            auto_sweep_name(axes, when=when),
            "vpn_vpc_20260907_203412",
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
        self.assertIn("d_ma.mid", ids)
        self.assertIn("w_ma.mid", ids)
        self.assertIn("SCALE_ARM", ids)
        self.assertIn("time_force.bars", ids)

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
                        {"id": "dmm15", "overrides": {"d_ma.mid": 15}},
                    ]
                }
            )
        self.assertIn("d_ma.mid", str(ctx.exception))
        self.assertIn("structure", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
