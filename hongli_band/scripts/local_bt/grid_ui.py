# coding: utf-8
"""参数网格任务页：可视化加格、开跑、看 summary。"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, MutableMapping

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analyze import (
    DEFAULT_DIVIDEND_TYPE,
    DEFAULT_REPORT_ROOT,
    DIVIDEND_LABELS,
    DIVIDEND_TYPES,
)
from batch_year_perf import (
    list_grid_samples_with_details,
    portfolio_year_perf_from_grid_sample,
)
from equity_yearly import (
    build_daily_equity,
    daily_equity_for_year,
    year_perf_display_df,
)
from asset_split import (
    DEFAULT_N_HOLDOUT,
    DEFAULT_N_TUNE,
    DEFAULT_SEED,
    DEFAULT_UNIVERSE_DIR,
    AssetSplitError,
    draw_asset_split,
    fill_asset_split,
)
from grid_run import (
    GRID_ROOT,
    GridError,
    THEME,
    assemble_jobs,
    load_config_defaults,
    run_sweep,
    summarize_only,
    validate_spec,
)
from grid_gate import EPS_GATE, default_gate, validate_gate  # noqa: E402  # path via grid_run
from grid_spec import (
    YEAR_WINDOW_DEFAULTS,
    YEAR_WINDOW_KEYS,
    EDITOR_CELL_MAX,
    GROUP_ORDER,
    KIND_ENUM,
    WARN_CELL_SOFT,
    GridSpecError,
    apply_axes_to_selection,
    apply_year_windows,
    axes_from_cells,
    axes_from_selection,
    auto_sweep_name,
    build_cells,
    cell_is_current,
    correct_cell_kinds,
    default_param_selection,
    fill_year_windows,
    format_current,
    format_scan_values,
    generator_locked,
    keep_from_cells,
    make_spec,
    merge_param_selection,
    overrides_summary,
    param_catalog,
    product_count,
    reject_retired_min_ret,
    spec_json,
    sweep_name_ok,
    sweep_stem_from_axes,
)

GRID_CONFIG_DIR = THEME / "gridConfig"
GRID_MODE = "参数网格"


def _defaults() -> dict[str, Any]:
    return load_config_defaults()


def _migrate_old_sel(ss: Any) -> dict[str, dict[str, Any]]:
    sel = default_param_selection()
    fams = list(ss.get("grid_families") or [])
    extras = dict(ss.get("grid_extras") or {})
    if not fams and not extras:
        return sel
    for fam in fams:
        if fam not in sel:
            continue
        scan = extras.get(fam)
        sel[fam] = {
            "selected": True,
            "scan": format_scan_values(fam, scan) if scan else sel[fam].get("scan") or "",
        }
    return sel


def _ensure_state() -> None:
    ss = st.session_state
    ss.setdefault("grid_sweep", "")
    ss.setdefault("grid_compare_div", DEFAULT_DIVIDEND_TYPE)
    ss.setdefault("grid_workers", 0)
    ss.setdefault("grid_sma_ema", False)
    for key, default in YEAR_WINDOW_DEFAULTS.items():
        ss.setdefault("grid_%s" % key, int(default))
    if "grid_param_sel" not in ss:
        ss["grid_param_sel"] = _migrate_old_sel(ss)
    ss["grid_param_sel"] = merge_param_selection(ss.get("grid_param_sel"))
    ss.setdefault("grid_cells", [])
    ss.setdefault("grid_summary", None)
    ss.setdefault("grid_busy", False)
    ss.setdefault("grid_import_text", "")
    ss.setdefault("grid_param_group", "全部")
    ss.setdefault("grid_param_search", "")
    ss.setdefault("grid_asset_split", False)
    ss.setdefault("grid_n_tune", DEFAULT_N_TUNE)
    ss.setdefault("grid_n_holdout", DEFAULT_N_HOLDOUT)
    ss.setdefault("grid_asset_seed", DEFAULT_SEED)
    ss.setdefault("grid_tune_stocks", [])
    ss.setdefault("grid_holdout_stocks", [])
    ss.setdefault("grid_eligible_n", 0)
    ss.setdefault("grid_reshuffle", False)
    dg = default_gate()
    ss.setdefault("grid_gate_relative", bool(dg["relative_to_base"]))
    ss.setdefault("grid_gate_calmar_same_sign", bool(dg["calmar_same_sign"]))
    ss.setdefault("grid_gate_calmar_en", bool(dg["calmar"]["enabled"]))
    ss.setdefault("grid_gate_calmar_min", float(dg["calmar"]["min"]))
    ss.setdefault("grid_gate_max_dd_en", bool(dg["max_dd"]["enabled"]))
    ss.setdefault("grid_gate_max_dd_pct", abs(float(dg["max_dd"]["floor"])) * 100.0)
    ss.setdefault("grid_gate_oos_sharpe_en", bool(dg["oos_sharpe"]["enabled"]))
    ss.setdefault("grid_gate_oos_sharpe_min", float(dg["oos_sharpe"]["min"]))
    ss.setdefault("grid_gate_n_trades_en", bool(dg["n_trades"]["enabled"]))
    ss.setdefault("grid_gate_n_trades_min", int(dg["n_trades"]["min"]))
    ss.setdefault("grid_gate_n_trades_vs_base", float(dg["n_trades"]["vs_base_ratio"]))
    ss.setdefault("grid_gate_win_rate_en", bool(dg["win_rate"]["enabled"]))
    ss.setdefault("grid_gate_win_rate_min", float(dg["win_rate"]["min"]))
    ss.setdefault("grid_gate_pf_en", bool(dg["profit_factor"]["enabled"]))
    ss.setdefault("grid_gate_pf_min", float(dg["profit_factor"]["min"]))


def _gate_from_state() -> dict[str, Any]:
    """从侧栏读 gate；勿在 widget 实例化后回写同名 session 键。"""
    ss = st.session_state
    raw = {
        "relative_to_base": bool(ss.get("grid_gate_relative", False)),
        "calmar_same_sign": bool(ss.get("grid_gate_calmar_same_sign", False)),
        "calmar": {
            "enabled": bool(ss.get("grid_gate_calmar_en", False)),
            "min": float(ss.get("grid_gate_calmar_min") or 1.5),
        },
        "max_dd": {
            "enabled": bool(ss.get("grid_gate_max_dd_en", True)),
            "floor": -abs(float(ss.get("grid_gate_max_dd_pct") or 10.0)) / 100.0,
        },
        "oos_sharpe": {
            "enabled": bool(ss.get("grid_gate_oos_sharpe_en", True)),
            "min": float(ss.get("grid_gate_oos_sharpe_min") or 0.8),
        },
        "n_trades": {
            "enabled": bool(ss.get("grid_gate_n_trades_en", False)),
            "min": int(ss.get("grid_gate_n_trades_min") or 1),
            "vs_base_ratio": float(ss.get("grid_gate_n_trades_vs_base") or 0.5),
        },
        "win_rate": {
            "enabled": bool(ss.get("grid_gate_win_rate_en", True)),
            "min": float(ss.get("grid_gate_win_rate_min") or 45.0),
        },
        "profit_factor": {
            "enabled": bool(ss.get("grid_gate_pf_en", True)),
            "min": float(ss.get("grid_gate_pf_min") or 1.5),
        },
    }
    return validate_gate(raw)


def _asset_split_from_state() -> dict[str, Any]:
    if not st.session_state.get("grid_asset_split"):
        return fill_asset_split({"asset_split": {"mode": "off"}})
    return {
        "mode": "random_from_csv",
        "universe_dir": DEFAULT_UNIVERSE_DIR,
        "n_tune": int(st.session_state.get("grid_n_tune") or DEFAULT_N_TUNE),
        "n_holdout": int(st.session_state.get("grid_n_holdout") or DEFAULT_N_HOLDOUT),
        "seed": int(st.session_state.get("grid_asset_seed") or DEFAULT_SEED),
        "ma_type": "EMA",
        "dividend_type": str(
            st.session_state.get("grid_compare_div") or DEFAULT_DIVIDEND_TYPE
        ),
        "exclude": [],
        "tune_stocks": list(st.session_state.get("grid_tune_stocks") or []),
        "holdout_stocks": list(st.session_state.get("grid_holdout_stocks") or []),
        "eligible_n": int(st.session_state.get("grid_eligible_n") or 0),
    }


def _axes() -> dict[str, list[Any]]:
    return axes_from_selection(st.session_state.get("grid_param_sel") or {})


def _current_spec(defaults: dict[str, Any]) -> dict[str, Any]:
    cells = list(st.session_state.get("grid_cells") or [])
    if not cells:
        try:
            cells = build_cells(_axes(), defaults)
        except GridSpecError:
            cells = []
    return make_spec(
        cells,
        sweep=str(st.session_state.get("grid_sweep") or "grid"),
        compare_div=str(st.session_state.get("grid_compare_div") or DEFAULT_DIVIDEND_TYPE),
        year_start=int(st.session_state.get("grid_year_start") or YEAR_WINDOW_DEFAULTS["year_start"]),
        year_end=int(st.session_state.get("grid_year_end") or YEAR_WINDOW_DEFAULTS["year_end"]),
        tune_start=int(st.session_state.get("grid_tune_start") or YEAR_WINDOW_DEFAULTS["tune_start"]),
        tune_end=int(st.session_state.get("grid_tune_end") or YEAR_WINDOW_DEFAULTS["tune_end"]),
        check_start=int(st.session_state.get("grid_check_start") or YEAR_WINDOW_DEFAULTS["check_start"]),
        check_end=int(st.session_state.get("grid_check_end") or YEAR_WINDOW_DEFAULTS["check_end"]),
        asset_split=_asset_split_from_state(),
        gate=_gate_from_state(),
    )


def _sweep_dir(spec: dict[str, Any]) -> Path:
    return GRID_ROOT / str(spec.get("sweep") or "grid")


def _list_specs() -> list[Path]:
    if not GRID_CONFIG_DIR.is_dir():
        return []
    return sorted(GRID_CONFIG_DIR.glob("*.json"))


def _list_history() -> list[Path]:
    if not GRID_ROOT.is_dir():
        return []
    out: list[Path] = []
    for child in sorted(GRID_ROOT.iterdir()):
        p = child / "summary.json"
        if p.is_file():
            out.append(p)
    return out


def _persist_app() -> None:
    try:
        from ui_cache import CACHE_PATH, merge_form_cache, snapshot_form_state

        merge_form_cache(snapshot_form_state(st.session_state), CACHE_PATH)
    except Exception:
        pass


def render_grid_sidebar() -> None:
    _ensure_state()
    busy = bool(st.session_state.get("grid_busy"))
    if st.session_state.get("grid_asset_split"):
        st.caption(
            "主样本=csv/none 抽取名单（调参∪盲测）；均线/复权锁 compare_div。"
            "开 SMA/EMA 对照 jobs 约 ×3。"
        )
    else:
        st.caption("主样本=跟踪池 BOOK_STOCKS（config 锁定均线/复权），不可勾选。")
    last = str(st.session_state.get("grid_sweep") or "").strip()
    st.caption(
        "sweep 每次开跑自动生成"
        + (" · 当前 `%s`" % last if last else " · 尚未开跑")
    )
    y1, y2 = st.columns(2)
    with y1:
        st.number_input("回测年起", min_value=1990, max_value=2100, step=1, key="grid_year_start", disabled=busy, persist_state="session")
    with y2:
        st.number_input("回测年止", min_value=1990, max_value=2100, step=1, key="grid_year_end", disabled=busy, persist_state="session")
    t1, t2 = st.columns(2)
    with t1:
        st.number_input("调参期起", min_value=1990, max_value=2100, step=1, key="grid_tune_start", disabled=busy, persist_state="session")
    with t2:
        st.number_input("调参期止", min_value=1990, max_value=2100, step=1, key="grid_tune_end", disabled=busy, persist_state="session")
    c1, c2 = st.columns(2)
    with c1:
        st.number_input("验收期起", min_value=1990, max_value=2100, step=1, key="grid_check_start", disabled=busy, persist_state="session")
    with c2:
        st.number_input("验收期止", min_value=1990, max_value=2100, step=1, key="grid_check_end", disabled=busy, persist_state="session")
    st.caption("改回测年起止必须重跑；只改调参期/验收期可「只汇总」。两段须落在回测年内且不重叠。")
    try:
        apply_year_windows(
            {
                "year_start": st.session_state.get("grid_year_start"),
                "year_end": st.session_state.get("grid_year_end"),
                "tune_start": st.session_state.get("grid_tune_start"),
                "tune_end": st.session_state.get("grid_tune_end"),
                "check_start": st.session_state.get("grid_check_start"),
                "check_end": st.session_state.get("grid_check_end"),
            }
        )
    except GridSpecError as e:
        st.error(str(e))

    st.checkbox(
        "空间隔离（csv/none 抽取）",
        key="grid_asset_split",
        disabled=busy,
        persist_state="session",
    )
    if st.session_state.get("grid_asset_split"):
        st.caption("宇宙：`%s` · 调参/盲测互不重叠；盲测只否决不选参" % DEFAULT_UNIVERSE_DIR)
        a1, a2 = st.columns(2)
        with a1:
            st.number_input(
                "调参抽取数",
                min_value=1,
                max_value=500,
                step=1,
                key="grid_n_tune",
                disabled=busy,
                persist_state="session",
            )
        with a2:
            st.number_input(
                "盲测抽取数",
                min_value=1,
                max_value=500,
                step=1,
                key="grid_n_holdout",
                disabled=busy,
                persist_state="session",
            )
        st.number_input(
            "抽取 seed",
            min_value=0,
            max_value=2_147_483_647,
            step=1,
            key="grid_asset_seed",
            disabled=busy,
            persist_state="session",
        )
        b1, b2 = st.columns(2)
        with b1:
            if st.button("抽取", disabled=busy, key="grid_draw_split"):
                _draw_split_clicked(reshuffle=True)
        with b2:
            if st.button("重新抽取", disabled=busy, key="grid_redraw_split"):
                _draw_split_clicked(reshuffle=True)
        n_t = len(st.session_state.get("grid_tune_stocks") or [])
        n_h = len(st.session_state.get("grid_holdout_stocks") or [])
        st.caption(
            "合格池 %s · 已抽调参 %s / 盲测 %s"
            % (st.session_state.get("grid_eligible_n") or "—", n_t, n_h)
        )
        if n_t:
            with st.expander("调参标的", expanded=False):
                st.code(", ".join(st.session_state.get("grid_tune_stocks") or []))
        if n_h:
            with st.expander("盲测标的", expanded=False):
                st.code(", ".join(st.session_state.get("grid_holdout_stocks") or []))

    with st.expander("过门合格线", expanded=False):
        st.caption(
            "数字未改（盈亏比 1.5 / 回撤 10% / 卡玛 0.8）。口径已是单账户组合：须用新跑的 ★现行格看线，旧 sweep 作废。"
        )
        st.checkbox(
            "相对 base 不劣",
            key="grid_gate_relative",
            disabled=busy,
            persist_state="session",
        )
        st.checkbox(
            "卡玛同向（调参/验收）",
            key="grid_gate_calmar_same_sign",
            disabled=busy,
            persist_state="session",
        )
        if not any(cell_is_current(c) for c in (st.session_state.get("grid_cells") or [])):
            st.caption("当前预览无 ★现行 格：相对门 / 卡玛同向不生效。")

        def _gate_row(
            label: str,
            en_key: str,
            val_key: str,
            *,
            min_v: float,
            max_v: float,
            step: float,
            fmt: str = "%.2f",
            is_int: bool = False,
        ) -> None:
            c_en, c_val = st.columns([1, 2])
            with c_en:
                st.checkbox(label, key=en_key, disabled=busy, persist_state="session")
            en = bool(st.session_state.get(en_key))
            with c_val:
                if is_int:
                    st.number_input(
                        "阈值",
                        min_value=int(min_v),
                        max_value=int(max_v),
                        step=int(step),
                        key=val_key,
                        disabled=busy or not en,
                        persist_state="session",
                        label_visibility="collapsed",
                    )
                else:
                    st.number_input(
                        "阈值",
                        min_value=float(min_v),
                        max_value=float(max_v),
                        step=float(step),
                        format=fmt,
                        key=val_key,
                        disabled=busy or not en,
                        persist_state="session",
                        label_visibility="collapsed",
                    )

        _gate_row("卡玛 ≥", "grid_gate_calmar_en", "grid_gate_calmar_min", min_v=0.0, max_v=50.0, step=0.1)
        _gate_row(
            "回撤% ≤",
            "grid_gate_max_dd_en",
            "grid_gate_max_dd_pct",
            min_v=0.0,
            max_v=100.0,
            step=0.5,
            fmt="%.1f",
        )
        _gate_row(
            "夏普 ≥",
            "grid_gate_oos_sharpe_en",
            "grid_gate_oos_sharpe_min",
            min_v=-5.0,
            max_v=10.0,
            step=0.1,
        )
        _gate_row(
            "笔数 ≥",
            "grid_gate_n_trades_en",
            "grid_gate_n_trades_min",
            min_v=0,
            max_v=10000,
            step=1,
            is_int=True,
        )
        st.number_input(
            "笔数相对 base 比例",
            min_value=0.0,
            max_value=2.0,
            step=0.05,
            format="%.2f",
            key="grid_gate_n_trades_vs_base",
            disabled=busy or not bool(st.session_state.get("grid_gate_n_trades_en")),
            persist_state="session",
        )
        _gate_row(
            "胜率% ≥",
            "grid_gate_win_rate_en",
            "grid_gate_win_rate_min",
            min_v=0.0,
            max_v=100.0,
            step=1.0,
            fmt="%.1f",
        )
        _gate_row(
            "盈亏比 ≥",
            "grid_gate_pf_en",
            "grid_gate_pf_min",
            min_v=0.0,
            max_v=99.0,
            step=0.1,
        )
        try:
            _gate_from_state()
        except ValueError as e:
            st.error(str(e))

    st.checkbox("额外全 SMA / EMA 对照", key="grid_sma_ema", disabled=busy, persist_state="session")
    st.number_input(
        "格内进程数（0=自动）",
        min_value=0,
        max_value=16,
        step=1,
        key="grid_workers",
        disabled=busy,
        persist_state="session",
    )
    if st.button("保存 spec 到 gridConfig", disabled=busy, key="grid_save_spec"):
        _save_spec_clicked()
    with st.container(horizontal=True, wrap=False, vertical_alignment="center"):
        st.button(
            "开始网格",
            type="primary",
            disabled=busy,
            key="grid_start",
            on_click=_mark_start,
            wrap=False,
            width="stretch",
        )
        st.button(
            "只汇总已有结果",
            disabled=busy,
            key="grid_sum_only",
            on_click=_mark_summarize,
            wrap=False,
            width="stretch",
        )


def _draw_split_clicked(*, reshuffle: bool) -> None:
    defaults = _defaults()
    spec = _current_spec(defaults)
    try:
        apply_year_windows(spec)
        split = draw_asset_split(spec, reshuffle=reshuffle)
    except (AssetSplitError, GridSpecError) as e:
        st.session_state["grid_flash"] = str(e)
        return
    # 勿回写 grid_n_tune / grid_n_holdout：已绑定 number_input，实例化后改会抛 StreamlitAPIException
    st.session_state["grid_tune_stocks"] = list(split.get("tune_stocks") or [])
    st.session_state["grid_holdout_stocks"] = list(split.get("holdout_stocks") or [])
    st.session_state["grid_eligible_n"] = int(split.get("eligible_n") or 0)
    st.session_state["grid_flash"] = "已抽取 调参%s / 盲测%s（合格池 %s）" % (
        len(st.session_state["grid_tune_stocks"]),
        len(st.session_state["grid_holdout_stocks"]),
        st.session_state["grid_eligible_n"],
    )
    _persist_app()


def _existing_sweep_names() -> set[str]:
    if not GRID_ROOT.is_dir():
        return set()
    return {p.name for p in GRID_ROOT.iterdir()}


def _mint_sweep_name() -> str:
    return auto_sweep_name(_axes(), existing=_existing_sweep_names())


def _begin_run_request(ss: MutableMapping[str, Any]) -> None:
    ss["grid_action"] = "run"
    ss.pop("grid_pending_sweep", None)


def _mark_start() -> None:
    _begin_run_request(st.session_state)


def _mark_summarize() -> None:
    st.session_state["grid_action"] = "summarize"


def _save_spec_clicked() -> None:
    defaults = _defaults()
    spec = _current_spec(defaults)
    try:
        apply_year_windows(spec)
    except GridSpecError as e:
        st.session_state["grid_flash"] = str(e)
        return
    name = sweep_stem_from_axes(_axes())
    if not sweep_name_ok(name):
        st.session_state["grid_flash"] = "sweep 名非法"
        return
    spec["sweep"] = name
    GRID_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = GRID_CONFIG_DIR / ("%s.json" % name)
    path.write_text(spec_json(spec), encoding="utf-8")
    st.session_state["grid_flash"] = "已保存 %s" % path


def render_grid_mode() -> None:
    _ensure_state()
    defaults = _defaults()
    busy = bool(st.session_state.get("grid_busy"))
    flash = st.session_state.pop("grid_flash", None)
    if flash:
        st.info(str(flash))

    st.caption(
        "主样本默认=跟踪池 BOOK_STOCKS × 回测年；开启空间隔离后=csv/none 抽取名单。"
        "选参看调参标的验收期，且须与调参期同向；盲测盈亏只否决。"
        "默认不改 config.py / 不 deploy。"
    )
    _render_param_table(defaults, busy)
    _render_action_bar(defaults, busy)
    _render_preview(defaults, busy)
    _render_advanced(defaults, busy)
    _handle_actions(defaults)
    _render_results()


def _render_param_table(defaults: dict[str, Any], busy: bool) -> None:
    catalog = param_catalog()
    groups = [g for g in GROUP_ORDER if any(p.group == g for p in catalog)]
    c1, c2 = st.columns([2, 3])
    with c1:
        group = st.pills(
            "分组",
            options=["全部"] + groups,
            selection_mode="single",
            key="grid_param_group",
            disabled=busy,
        )
    with c2:
        search = str(
            st.text_input("搜索参数", key="grid_param_search", disabled=busy) or ""
        ).strip()
    group = str(group or "全部")
    cat_fp = tuple(p.id for p in catalog)
    filt = "%s|%s|%s" % (group, search.lower(), ",".join(cat_fp))
    if st.session_state.get("grid_param_filt") != filt:
        st.session_state.pop("grid_param_editor", None)
        st.session_state["grid_param_filt"] = filt

    sel = dict(st.session_state.get("grid_param_sel") or default_param_selection())
    q = search.lower()
    rows = []
    for spec in catalog:
        if group != "全部" and spec.group != group:
            continue
        blob = ("%s %s" % (spec.label, spec.id)).lower()
        if q and q not in blob:
            continue
        rec = dict(sel.get(spec.id) or {})
        rows.append(
            {
                "选用": bool(rec.get("selected")),
                "分组": spec.group,
                "参数": "%s %s" % (spec.label, spec.id),
                "现行": format_current(spec.id, defaults),
                "扫描取值": str(rec.get("scan") or ""),
                "键": spec.id,
            }
        )
    if not rows:
        st.info("没有匹配的参数。")
    else:
        df = pd.DataFrame(rows)
        edited = st.data_editor(
            df,
            num_rows="fixed",
            width="stretch",
            hide_index=True,
            disabled=["分组", "参数", "现行", "键"] if not busy else df.columns.tolist(),
            column_order=["选用", "分组", "参数", "现行", "扫描取值"],
            column_config={
                "选用": st.column_config.CheckboxColumn("选用", default=False),
                "扫描取值": st.column_config.TextColumn(
                    "扫描取值",
                    help="标量：逗号或空格分隔，如 6,10。百分数可写 6%、6 或 0.06。TRAIL_TIERS 写 JSON 整表，多组换行。",
                ),
            },
            key="grid_param_editor",
        )
        if not busy:
            label_map = {"%s %s" % (p.label, p.id): p.id for p in catalog}
            prev = dict(st.session_state.get("grid_param_sel") or {})
            changed = False
            for rec in edited.to_dict("records"):
                pid = str(rec.get("键") or "") or label_map.get(str(rec.get("参数") or ""), "")
                if not pid:
                    continue
                if pid not in sel:
                    sel[pid] = {"selected": False, "scan": ""}
                new_rec = {
                    "selected": bool(rec.get("选用")),
                    "scan": str(rec.get("扫描取值") or ""),
                }
                if dict(sel.get(pid) or {}) != new_rec:
                    changed = True
                sel[pid] = new_rec
            if changed or prev != sel:
                st.session_state["grid_param_sel"] = sel

    axes = _axes()
    try:
        n = product_count(axes, defaults)
    except GridSpecError as e:
        st.error(str(e))
        n = 0
    names = " × ".join(
        "%s %s" % (p.label, p.id) for p in catalog if p.id in axes
    ) or "（未选用）"
    st.caption("未勾选不进积；N = Π(各轴扫描个数) = **%s** 格 · 轴：%s" % (n, names))
    if n > WARN_CELL_SOFT:
        st.warning("格子数 %s > %s：技能建议少量命名格，叉乘多为交互项。" % (n, WARN_CELL_SOFT))


def _render_action_bar(defaults: dict[str, Any], busy: bool) -> None:
    locked = generator_locked(st.session_state.get("grid_cells") or [])
    if locked:
        st.warning("导入 spec 含非白名单键，生成器已锁定。仍可开跑。")
    with st.container(horizontal=True):
        do_build = st.button("生成格子", disabled=busy or locked, key="grid_build")
        st.button(
            "开始网格",
            type="primary",
            disabled=busy,
            key="grid_start_main",
            on_click=_mark_start,
        )
        st.button(
            "只汇总已有结果",
            disabled=busy,
            key="grid_sum_main",
            on_click=_mark_summarize,
        )
    if do_build:
        try:
            keep = keep_from_cells(st.session_state.get("grid_cells") or [])
            cells = build_cells(_axes(), defaults, keep=keep)
            st.session_state["grid_cells"] = cells
            st.session_state.pop("grid_cells_editor", None)
            st.success("已生成 %s 格" % len(cells))
        except GridSpecError as e:
            st.error(str(e))
    if not (st.session_state.get("grid_cells") or []):
        st.caption("尚未生成预览时，开跑会按当前参数表即时积格。")


def _render_preview(defaults: dict[str, Any], busy: bool) -> None:
    cells = list(st.session_state.get("grid_cells") or [])
    if not cells:
        st.info("点「生成格子」预览 spec。")
        return
    n = len(cells)
    if st.session_state.get("grid_preview_n") != n:
        st.session_state.pop("grid_cells_editor", None)
        st.session_state.pop("grid_cells_editor_v2", None)
    st.session_state["grid_preview_n"] = n
    current_ids = {str(c.get("id") or "") for c in cells if cell_is_current(c)}
    st.markdown(
        "**格子预览** · %s / 无硬上限%s"
        % (n, " · 浅蓝底=现行参数" if current_ids else "")
    )
    rows = []
    for c in cells:
        rows.append(
            {
                "删除": False,
                "id": c["id"],
                "label": c["label"],
                "kind": c["kind"],
                "覆盖": overrides_summary(c.get("overrides") or {}, defaults),
            }
        )
    df = pd.DataFrame(rows)
    show = df.drop(columns=["删除"])
    styled = show.style.apply(_style_current_ids(current_ids), axis=1)
    st.dataframe(styled, width="stretch", hide_index=True)
    if n > EDITOR_CELL_MAX:
        st.download_button(
            "下载 spec JSON",
            data=spec_json(_current_spec(defaults)),
            file_name="%s.json" % (sweep_stem_from_axes(_axes()) or "grid"),
            mime="application/json",
            key="grid_dl_spec",
        )
        return
    with st.expander("编辑格子", expanded=False):
        edited = st.data_editor(
            df,
            num_rows="fixed",
            width="stretch",
            hide_index=True,
            disabled=["id", "覆盖"] if not busy else df.columns.tolist(),
            column_order=["删除", "id", "label", "kind", "覆盖"],
            column_config={
                "删除": st.column_config.CheckboxColumn("删除", default=False),
                "kind": st.column_config.SelectboxColumn("kind", options=list(KIND_ENUM)),
            },
            key="grid_cells_editor_v2",
        )
        if busy:
            return
        by_id = {c["id"]: c for c in cells}
        out: list[dict[str, Any]] = []
        for rec in edited.to_dict("records"):
            cid = str(rec.get("id") or "")
            src = dict(by_id.get(cid) or {})
            if not src:
                continue
            if rec.get("删除"):
                continue
            src["label"] = str(rec.get("label") or cid)
            kind = str(rec.get("kind") or src.get("kind") or "other")
            if cid == "base":
                kind = "base"
            elif kind not in KIND_ENUM or kind == "base":
                kind = (
                    src.get("kind")
                    if src.get("kind") in KIND_ENUM and src.get("kind") != "base"
                    else "other"
                )
            src["kind"] = kind
            out.append(src)
        st.session_state["grid_cells"] = out


def _render_advanced(defaults: dict[str, Any], busy: bool) -> None:
    with st.expander("高级"):
        st.selectbox(
            "compare_div（PIT / 复权模式）",
            options=list(DIVIDEND_TYPES),
            format_func=lambda k: "%s（%s）" % (DIVIDEND_LABELS.get(k, k), k),
            key="grid_compare_div",
            disabled=busy,
        )
        st.caption("front_ratio=等比 PIT · front=价差 PIT · none/back*=不走 PIT")
        paths = _list_specs()
        labels = ["（选择文件）"] + [p.name for p in paths]
        pick = st.selectbox("从 gridConfig 导入", labels, key="grid_import_pick", disabled=busy)
        if pick and pick != "（选择文件）" and st.button("加载该 JSON", disabled=busy, key="grid_load_file"):
            path = GRID_CONFIG_DIR / pick
            _import_spec_text(path.read_text(encoding="utf-8"), defaults)
        text = st.text_area("或粘贴 spec JSON", key="grid_import_text", height=160, disabled=busy)
        if st.button("从文本导入", disabled=busy, key="grid_load_text"):
            _import_spec_text(str(text or ""), defaults)
        hist = _list_history()
        if hist:
            hlabels = [p.parent.name for p in hist]
            hi = st.selectbox("打开历史 summary", hlabels, key="grid_hist_pick")
            if st.button("加载历史", key="grid_hist_load"):
                path = hist[hlabels.index(hi)]
                try:
                    from summarize import legacy_sweep_reason  # noqa: WPS433
                except Exception:
                    legacy_sweep_reason = None  # type: ignore[assignment]
                why = None
                if callable(legacy_sweep_reason):
                    why = legacy_sweep_reason(path.parent)
                if why:
                    st.error(why)
                else:
                    st.session_state["grid_summary"] = json.loads(path.read_text(encoding="utf-8"))
                    st.session_state["grid_sweep"] = path.parent.name


def _import_spec_text(text: str, defaults: dict[str, Any]) -> None:
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as e:
        st.error("JSON 无效：%s" % e)
        return
    if not isinstance(spec, dict):
        st.error("spec 必须是对象")
        return
    try:
        reject_retired_min_ret(spec)
    except GridSpecError as e:
        st.error(str(e))
        return
    cells = correct_cell_kinds(spec.get("cells") or [], defaults)
    st.session_state["grid_cells"] = cells
    st.session_state.pop("grid_cells_editor", None)
    st.session_state.pop("grid_param_editor", None)
    if spec.get("sweep"):
        name = str(spec["sweep"])
        if (GRID_ROOT / name / "summary.json").is_file():
            st.session_state["grid_sweep"] = name
    if spec.get("compare_div"):
        st.session_state["grid_compare_div"] = str(spec["compare_div"])
    win = fill_year_windows(spec)
    for key in YEAR_WINDOW_KEYS:
        st.session_state["grid_%s" % key] = int(win[key])
    axes = axes_from_cells(cells, defaults)
    st.session_state["grid_param_sel"] = apply_axes_to_selection(None, axes)
    st.success("已导入 %s 格%s" % (len(cells), "（生成器锁定）" if generator_locked(cells) else ""))
    st.rerun()


def _handle_actions(defaults: dict[str, Any]) -> None:
    action = st.session_state.get("grid_action")
    if not action:
        return
    if action == "run" and not st.session_state.get("grid_pending_sweep"):
        name = _mint_sweep_name()
        st.session_state["grid_pending_sweep"] = name
        st.session_state["grid_sweep"] = name
    spec = _current_spec(defaults)
    if action == "summarize":
        st.session_state.pop("grid_action", None)
        name = str(st.session_state.get("grid_sweep") or "").strip()
        if not sweep_name_ok(name):
            st.error("还没有 sweep：请先开跑或从高级里加载历史")
            return
        dest = _sweep_dir(spec)
        try:
            # 侧栏 gate 优先；勿回写 widget 键。按当前预览 id 过滤，避免同 sweep 残留格进主表。
            want = [
                str(c.get("id") or "")
                for c in (spec.get("cells") or [])
                if str(c.get("id") or "").strip()
            ]
            out = summarize_only(dest, gate=_gate_from_state(), cell_ids=want or None)
            st.session_state["grid_summary"] = out
            st.success("已汇总")
        except Exception as e:
            st.error(str(e))
        return
    try:
        validate_spec(spec)
    except GridError as e:
        st.error(str(e))
        st.session_state.pop("grid_action", None)
        return
    if action != "run":
        return
    # 空间隔离：开跑前若无名单则先抽一次
    if (spec.get("asset_split") or {}).get("mode") == "random_from_csv":
        split = spec.get("asset_split") or {}
        if not split.get("tune_stocks") or not split.get("holdout_stocks"):
            try:
                drawn = draw_asset_split(spec, reshuffle=True)
            except AssetSplitError as e:
                st.error(str(e))
                return
            spec["asset_split"] = drawn
            st.session_state["grid_tune_stocks"] = list(drawn.get("tune_stocks") or [])
            st.session_state["grid_holdout_stocks"] = list(drawn.get("holdout_stocks") or [])
            st.session_state["grid_eligible_n"] = int(drawn.get("eligible_n") or 0)
    try:
        assemble_jobs(
            spec,
            include_sma_ema=bool(st.session_state.get("grid_sma_ema")),
        )
    except GridError as e:
        st.error(str(e))
        st.session_state.pop("grid_action", None)
        return
    st.session_state.pop("grid_action", None)
    _run_now(spec)


def _run_now(spec: dict[str, Any]) -> None:
    st.session_state["grid_busy"] = True
    bar = st.progress(0.0)
    status = st.empty()
    n_cells = max(len(spec.get("cells") or []), 1)
    cell_ids = [str(c.get("id") or "") for c in spec.get("cells") or []]

    def on_progress(cid: str, done: int, tot: int, label: str, **extra: Any) -> None:
        try:
            idx = cell_ids.index(str(cid))
        except ValueError:
            idx = 0
        inner = 0.0
        walk_total = extra.get("walk_total")
        try:
            wt = float(walk_total or 0)
            if wt > 0:
                inner = min(1.0, float(extra.get("walk_done") or 0) / wt)
        except (TypeError, ValueError):
            inner = 0.0
        frac = (float(idx) + (float(done) + inner) / float(tot or 1)) / float(n_cells)
        frac = min(1.0, frac)
        text = "%s/%s %s" % (done, tot, label)
        try:
            bar.progress(frac, text=text)
        except TypeError:
            bar.progress(frac)
        status.info("格子 **%s** · %s/%s %s" % (cid, done, tot, label))

    try:
        info = run_sweep(
            spec,
            include_sma_ema=bool(st.session_state.get("grid_sma_ema")),
            workers=int(st.session_state.get("grid_workers") or 0),
            progress=on_progress,
            reshuffle=False,
        )
        split = info.get("asset_split") or {}
        if split.get("tune_stocks"):
            st.session_state["grid_tune_stocks"] = list(split.get("tune_stocks") or [])
            st.session_state["grid_holdout_stocks"] = list(split.get("holdout_stocks") or [])
            st.session_state["grid_eligible_n"] = int(split.get("eligible_n") or 0)
        st.session_state["grid_summary"] = info.get("summary")
        rec = (info.get("recommend") or {}) if isinstance(info.get("recommend"), dict) else {}
        status.success("完成 · sweep **%s** · 推荐 %s" % (spec.get("sweep") or "", rec.get("id") or ""))
        bar.progress(1.0)
    except GridError as e:
        st.error(str(e))
    except Exception as e:
        st.error("%s: %s" % (type(e).__name__, e))
    finally:
        st.session_state["grid_busy"] = False
        st.session_state.pop("grid_pending_sweep", None)
        _persist_app()


def _grid_sweep_dir(summary: dict[str, Any]) -> Path:
    raw = str(summary.get("sweep_dir") or "").strip()
    if raw:
        p = Path(raw)
        if p.is_dir():
            return p
    return _sweep_dir(_current_spec(_defaults()))


def _plot_grid_year_equity(eq: pd.DataFrame, budget: float, title: str) -> go.Figure:
    fig = go.Figure()
    pts = eq.dropna(subset=["date"]) if eq is not None and "date" in eq.columns else eq
    if pts is None or pts.empty:
        fig.add_annotation(text="无已平仓成交", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
    else:
        fig.add_trace(
            go.Scatter(
                x=pd.to_datetime(pts["date"]),
                y=pts["equity"],
                mode="lines+markers",
                name="权益",
                line=dict(color="#1565c0", width=2),
                marker=dict(size=6),
                hovertemplate="%{x|%Y/%m/%d}<br>权益 %{y:,.2f}<extra></extra>",
            )
        )
        fig.add_hline(y=budget, line_dash="dash", line_color="#9e9e9e", annotation_text="预算")
    fig.update_layout(
        title=title,
        xaxis_title="日期",
        yaxis_title="权益 (元)",
        height=360,
        margin=dict(l=40, r=20, t=50, b=40),
        legend=dict(orientation="h"),
        xaxis=dict(tickformat="%Y/%m/%d"),
    )
    return fig


def _render_grid_year_perf(summary: dict[str, Any]) -> None:
    cells = list(summary.get("cells") or [])
    cell_ids = [str(c.get("id") or "") for c in cells if c.get("id")]
    if not cell_ids:
        return
    labels = {
        str(c.get("id")): "%s · %s" % (c.get("id"), c.get("label") or c.get("id"))
        for c in cells
        if c.get("id")
    }
    sweep_dir = _grid_sweep_dir(summary)
    st.subheader("分年绩效（组合权益切年）")
    rec_id = str((summary.get("recommend") or {}).get("id") or "")
    if st.session_state.get("grid_year_cell") not in cell_ids:
        st.session_state["grid_year_cell"] = rec_id if rec_id in cell_ids else cell_ids[0]
    cell_id = st.selectbox(
        "格子",
        options=cell_ids,
        format_func=lambda i: labels.get(i, i),
        key="grid_year_cell",
    )
    cell_dir = sweep_dir / str(cell_id)
    samples = list_grid_samples_with_details(cell_dir)
    if not samples:
        st.info("该格无操作明细")
        return
    if "book" in samples:
        default_sample = "book"
    else:
        default_sample = samples[0]
    sample_key = "grid_year_sample_%s" % cell_id
    if st.session_state.get(sample_key) not in samples:
        st.session_state[sample_key] = default_sample
    sample = st.selectbox("样本", options=samples, key=sample_key)
    try:
        fallback = float(_defaults().get("TRADE_BUDGET") or 100000.0)
    except (TypeError, ValueError):
        fallback = 100000.0
    cache = st.session_state.setdefault("_batch_detail_trade_cache", {})
    result = portfolio_year_perf_from_grid_sample(
        cell_dir, sample, fallback_budget=fallback, cache=cache
    )
    if not result.get("ok"):
        reason = str(result.get("reason") or "")
        st.info(reason if reason else "该格无操作明细")
        return

    n_buy = int(result.get("n_buy") or 0)
    sum_pnl = float(result.get("sum_pnl") or 0)
    m1, m2, m3 = st.columns(3)
    m1.metric("账户", 1)
    m2.metric("轮次", n_buy)
    m3.metric("已实现盈亏", "%.2f" % sum_pnl)

    st.caption(
        "单账户连续回放（最多 3 笔、CASH_RATIO × 权益复利）。分年切同一条组合权益，"
        "不是多票独立 10 万账户加总。权益 = 预算 + 已实现盈亏台阶（与实盘评估相同，非全日盯市）。"
    )
    tbl = result.get("table")
    if tbl is None or getattr(tbl, "empty", True):
        st.info("无成交轮次，无法按年汇总。")
        return
    st.dataframe(year_perf_display_df(tbl), width="stretch", hide_index=True)

    years = [str(y) for y in tbl["year"].tolist()]
    year_key = "grid_year_eq_%s_%s" % (cell_id, sample)
    if year_key not in st.session_state or st.session_state.get(year_key) not in years:
        st.session_state[year_key] = years[-1]
    year = st.selectbox("权益曲线年份", options=years, key=year_key)
    match = tbl.loc[tbl["year"].astype(str) == str(year)]
    if match.empty:
        st.info("该年无权益点。")
        return
    start_eq = float(match.iloc[0]["start_equity"])
    bud = float(result.get("budget") or fallback)
    daily = build_daily_equity(list(result.get("trades") or []), bud)
    eq_y = daily_equity_for_year(daily, year, start_equity=start_eq)
    st.plotly_chart(
        _plot_grid_year_equity(
            eq_y, bud, "%s 年组合权益（预算 + 已实现盈亏台阶）" % year
        ),
        use_container_width=True,
    )


def _window_metric(book: dict[str, Any], key: str, field: str, *, windows_key: str = "windows") -> Any:
    w = (book.get(windows_key) or {}).get(key) or {}
    return w.get(field)


_DETAIL_PERIODS = (
    ("全区间", "all"),
    ("调参期", "tune"),
    ("验收期", "check"),
)
_DETAIL_METRIC_COLS = (
    "夏普",
    "笔数",
    "卡玛",
    "回撤%",
    "胜率%",
    "盈亏比",
    "几何年化%",
    "账户盈亏",
)
_DETAIL_GROUP_SIZE = len(_DETAIL_PERIODS)


def _detail_window_rows(
    cell: dict[str, Any],
    book: dict[str, Any],
    *,
    windows_key: str = "windows",
) -> list[dict[str, Any]]:
    """每格固定 3 行（全区间 / 调参期 / 验收期），缺窗也出空指标行。"""
    cid = cell.get("id")
    label = cell.get("label")
    rows: list[dict[str, Any]] = []
    for period, wkey in _DETAIL_PERIODS:
        mdd = _window_metric(book, wkey, "max_dd", windows_key=windows_key)
        rows.append(
            {
                "id": cid,
                "label": label,
                "区间": period,
                "夏普": _window_metric(book, wkey, "sharpe", windows_key=windows_key),
                "笔数": _window_metric(book, wkey, "n_trades", windows_key=windows_key),
                "卡玛": _window_metric(book, wkey, "calmar", windows_key=windows_key),
                "回撤%": None if mdd is None else round(abs(float(mdd)) * 100.0, 2),
                "胜率%": _window_metric(book, wkey, "win_rate", windows_key=windows_key),
                "盈亏比": _window_metric(
                    book, wkey, "profit_factor", windows_key=windows_key
                ),
                "几何年化%": _window_metric(
                    book, wkey, "avg_ann_pct", windows_key=windows_key
                ),
                "账户盈亏": _window_metric(
                    book, wkey, "avg_year_pnl", windows_key=windows_key
                ),
            }
        )
    return rows


_DETAIL_TONE_COLS = ("夏普", "卡玛", "胜率%", "盈亏比", "几何年化%", "账户盈亏")
_DETAIL_PASS_COLOR = "#e74c3c"
_DETAIL_TONE_GATE_KEYS = {
    "夏普": "oos_sharpe",
    "卡玛": "calmar",
    "胜率%": "win_rate",
    "盈亏比": "profit_factor",
}
_DETAIL_LABEL_WIDTH = "10em"


def _fmt_detail_metric(col: str, val: Any) -> str:
    if val is None:
        return "—"
    try:
        x = float(val)
    except (TypeError, ValueError):
        return html.escape(str(val))
    if col == "笔数":
        return "%d" % int(round(x))
    if col == "夏普":
        return "%.4f" % x
    if col == "卡玛":
        return "%.3f" % x
    if col == "胜率%":
        return "%.1f" % x
    return "%.2f" % x


def _detail_metric_line(col: str, gate: dict[str, Any] | None) -> float | None:
    """着色比较线；非着色列返回 None。对应门关闭（或无门）时比 0。"""
    if col not in _DETAIL_TONE_COLS:
        return None
    key = _DETAIL_TONE_GATE_KEYS.get(col)
    if not key:
        return 0.0
    g = gate or {}
    rule = g.get(key) if isinstance(g.get(key), dict) else {}
    if not rule.get("enabled"):
        return 0.0
    try:
        return float(rule.get("min") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _detail_metric_tone(
    col: str, val: Any, gate: dict[str, Any] | None
) -> str | None:
    """过线返回 pass；未过线与缺值返回 None（保持默认字色）。"""
    line = _detail_metric_line(col, gate)
    if line is None or val is None:
        return None
    try:
        x = float(val)
    except (TypeError, ValueError):
        return None
    if x + EPS_GATE >= line:
        return "pass"
    return None


def _detail_table_palette() -> dict[str, str]:
    dark = True
    try:
        theme = getattr(getattr(st, "context", None), "theme", None)
        dark = str(getattr(theme, "type", "dark") or "dark").lower() != "light"
    except Exception:
        dark = True
    if dark:
        return {
            "color": "var(--text-color, #e6edf3)",
            "header_bg": "var(--secondary-background-color, #262730)",
            "border": "rgba(230,237,243,0.18)",
            "zebra": "rgba(255,255,255,0.04)",
        }
    return {
        "color": "var(--text-color, #1f2328)",
        "header_bg": "var(--secondary-background-color, #f0f2f6)",
        "border": "rgba(31,35,40,0.18)",
        "zebra": "rgba(0,0,0,0.04)",
    }


def _html_cell(
    text: str,
    style: str,
    *,
    tag: str = "td",
    rowspan: int | None = None,
) -> str:
    rs = ' rowspan="%d"' % rowspan if rowspan and rowspan > 1 else ""
    return "<%s%s style=\"%s\">%s</%s>" % (tag, rs, style, text, tag)


def _detail_window_table_html(
    rows: list[dict[str, Any]],
    gate: dict[str, Any] | None = None,
) -> str:
    pal = _detail_table_palette()
    cell_base = (
        "border:none;border-bottom:1px solid %s;padding:0.35rem 0.6rem;"
        "vertical-align:middle;color:%s;"
        % (pal["border"], pal["color"])
    )
    headers = ["id", "label", ""] + list(_DETAIL_METRIC_COLS)
    th_align = ["left", "left", "center"] + ["right"] * len(_DETAIL_METRIC_COLS)
    wrap = "overflow-x:auto;width:100%;"
    table = (
        "width:100%%;border-collapse:collapse;font-size:0.9rem;color:%s;"
        % pal["color"]
    )
    parts: list[str] = ['<div style="%s">' % wrap, '<table style="%s">' % table]
    parts.append("<thead><tr>")
    for h, align in zip(headers, th_align):
        th_style = (
            "%sbackground:%s;text-align:%s;font-weight:600;white-space:nowrap;"
            % (cell_base, pal["header_bg"], align)
        )
        if h == "label":
            th_style += "width:%s;max-width:%s;" % (
                _DETAIL_LABEL_WIDTH,
                _DETAIL_LABEL_WIDTH,
            )
        parts.append(_html_cell(html.escape(h), th_style, tag="th"))
    parts.append("</tr></thead><tbody>")
    n = len(rows)
    i = 0
    group_i = 0
    while i < n:
        chunk = rows[i : i + _DETAIL_GROUP_SIZE]
        span = len(chunk)
        zebra = pal["zebra"] if group_i % 2 == 1 else ""
        bg = "background:%s;" % zebra if zebra else ""
        for j, row in enumerate(chunk):
            parts.append("<tr>")
            if j == 0:
                id_style = "%s%stext-align:left;white-space:nowrap;" % (
                    cell_base,
                    bg,
                )
                label_style = (
                    "%s%stext-align:left;width:%s;max-width:%s;"
                    "white-space:normal;overflow-wrap:anywhere;"
                    % (cell_base, bg, _DETAIL_LABEL_WIDTH, _DETAIL_LABEL_WIDTH)
                )
                parts.append(
                    _html_cell(
                        html.escape(str(row.get("id") or "")),
                        id_style,
                        rowspan=span,
                    )
                )
                parts.append(
                    _html_cell(
                        html.escape(str(row.get("label") or "")),
                        label_style,
                        rowspan=span,
                    )
                )
            period_style = "%s%stext-align:center;white-space:nowrap;" % (
                cell_base,
                bg,
            )
            parts.append(
                _html_cell(html.escape(str(row.get("区间") or "")), period_style)
            )
            for col in _DETAIL_METRIC_COLS:
                extra = ""
                if _detail_metric_tone(col, row.get(col), gate) == "pass":
                    extra = "color:%s;" % _DETAIL_PASS_COLOR
                metric_style = (
                    "%s%stext-align:right;font-variant-numeric:tabular-nums;%s"
                    % (cell_base, bg, extra)
                )
                parts.append(
                    _html_cell(_fmt_detail_metric(col, row.get(col)), metric_style)
                )
            parts.append("</tr>")
        i += _DETAIL_GROUP_SIZE
        group_i += 1
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _render_detail_window_table(rows: list[dict[str, Any]], caption: str) -> None:
    st.caption(caption)
    body = _detail_window_table_html(rows, gate=_gate_from_state())
    try:
        st.html(body, width="stretch")
    except TypeError:
        st.html(body)


def _round_pnl(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(round(float(val)))
    except (TypeError, ValueError):
        return None


def _style_delta_cell(val: Any) -> str:
    """A 股习惯：正红负绿。元级 |x|<1 中性；小数（卡玛Δ）|x|<1e-4 中性。"""
    try:
        x = float(val)
    except (TypeError, ValueError):
        return ""
    thr = 1.0 if abs(x) >= 1.0 else 1e-4
    if abs(x) < thr:
        return ""
    if x > 0:
        return "color: #e74c3c"
    return "color: #27ae60"


def _style_current_ids(ids: set[str]):
    def _style(row: pd.Series) -> list[str]:
        if str(row.get("id") or "") in ids:
            return ["background-color: rgba(21,101,192,0.22)"] * len(row)
        return [""] * len(row)

    return _style


def _fail_metric_token(msg: str) -> str:
    s = str(msg or "")
    for name in ("卡玛", "回撤", "夏普", "笔数", "胜率", "盈亏比", "覆盖"):
        if name in s:
            return name
    if "同向" in s:
        return "同向"
    return s[:8] if s else ""


def _group_gate_fails(fails: Any) -> dict[str, list[str]]:
    """把 fails 拆成 验收 / 相对 / 同向 / 盲测，指标名去重保序。"""
    out: dict[str, list[str]] = {
        "验收": [],
        "相对": [],
        "同向": [],
        "盲测": [],
    }
    if isinstance(fails, str) and fails.strip():
        items = [x.strip() for x in fails.replace("；", ";").split(";") if x.strip()]
    elif isinstance(fails, list):
        items = [str(x) for x in fails if x]
    else:
        return out
    seen: dict[str, set[str]] = {k: set() for k in out}

    def add(bucket: str, token: str) -> None:
        if not token or token in seen[bucket]:
            return
        seen[bucket].add(token)
        out[bucket].append(token)

    for raw in items:
        s = str(raw)
        tok = _fail_metric_token(s)
        if "同向" in s:
            add("同向", "异号" if "不同向" in s else tok)
        elif s.startswith("盲测") or "盲测标的" in s:
            add("盲测", tok)
        elif "相对base" in s or "劣于base" in s or "无法比base" in s:
            add("相对", tok)
        else:
            add("验收", tok)
    return out


def _fail_summary_compact(groups: dict[str, list[str]]) -> str:
    parts: list[str] = []
    for key, label in (("验收", "验"), ("相对", "相"), ("同向", "向"), ("盲测", "盲")):
        toks = groups.get(key) or []
        if not toks:
            continue
        parts.append("%s:%s" % (label, ",".join(toks)))
    return " · ".join(parts)


def _render_fail_detail(notes_by_id: dict[str, Any], cells: list[dict[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for cell in cells:
        cid = cell.get("id")
        note = notes_by_id.get(cid) or {}
        fails = note.get("fails")
        if not fails and note.get("fail"):
            fails = note.get("fail")
        groups = _group_gate_fails(fails)
        if not any(groups.values()):
            continue
        rows.append(
            {
                "id": cid,
                "label": cell.get("label"),
                "验收绝对": " ".join(groups["验收"]) or "—",
                "相对base": " ".join(groups["相对"]) or "—",
                "同向": " ".join(groups["同向"]) or "—",
                "盲测": " ".join(groups["盲测"]) or "—",
                "全部": "；".join(str(x) for x in (fails if isinstance(fails, list) else [fails])),
            }
        )
    if not rows:
        return
    with st.expander("未过明细（按门分类）", expanded=True):
        st.caption("按验收绝对 / 相对 base / 同向 / 盲测拆开；全部原文不丢。主表只保留是否通过。")
        st.dataframe(
            pd.DataFrame(rows),
            width="stretch",
            hide_index=True,
            column_config={
                "全部": st.column_config.TextColumn("全部原文", width="large"),
            },
        )


def _render_results() -> None:
    summary = st.session_state.get("grid_summary")
    if not isinstance(summary, dict) or not summary.get("cells"):
        return
    rec = summary.get("recommend") or {}
    rec_id = str(rec.get("id") or "").strip()
    st.subheader("选参结论")
    sweep_label = str(summary.get("sweep") or "").strip()
    if sweep_label:
        st.caption("sweep `%s`" % sweep_label)
    rec_reason = str(rec.get("reason") or "")
    if rec_id:
        st.success("过门推荐 **%s** · %s" % (rec.get("label") or rec_id, rec_reason))
    else:
        st.warning(rec_reason or "无格子过门")
    try:
        from robust_ui import ROBUST_MODE
        from ui_cache import UI_MODE_KEY

        sweep_dir = _grid_sweep_dir(summary)
        sum_path = sweep_dir / "summary.json"
        can_robust = bool(rec_id) and sum_path.is_file()
        if not rec_id:
            st.caption("无过门推荐，不能送入实盘评估。")
        if can_robust and st.button("送入实盘评估", key="grid_to_robust"):
            try:
                rel = str(sum_path.resolve().relative_to(Path(__file__).resolve().parents[3])).replace(
                    "\\", "/"
                )
            except ValueError:
                rel = str(sum_path)
            st.session_state["robust_param_source"] = rel
            st.session_state[UI_MODE_KEY] = ROBUST_MODE
            st.rerun()
    except Exception:
        pass
    space = summary.get("asset_split") or {}
    space_on = bool(space.get("holdout_stocks") or space.get("tune_stocks"))
    if space_on:
        st.caption(
            "空间隔离：主列盈亏=调参标的（展示）；过门=侧栏绝对合格线；盲测复用同一 gate 否决。"
        )
    else:
        st.caption(
            "过门=侧栏已启用的绝对合格线；排序看验收期卡玛。默认不改 config / 不 deploy。"
        )
    win = fill_year_windows(summary)
    main_rows: list[dict[str, Any]] = []
    current_ids: set[str] = set()
    tune_detail_rows: list[dict[str, Any]] = []
    hold_detail_rows: list[dict[str, Any]] = []
    notes = rec.get("candidates") or []
    notes_by_id = {n.get("id"): n for n in notes if isinstance(n, dict)}
    cells = list(summary.get("cells") or [])
    for cell in cells:
        b = (cell.get("samples") or {}).get("book") or {}
        note = notes_by_id.get(cell.get("id")) or {}
        fails = note.get("fails")
        if not (isinstance(fails, list) and fails) and note.get("fail"):
            fails = note.get("fail")
        groups = _group_gate_fails(fails)
        compact = _fail_summary_compact(groups)
        cid = cell.get("id")
        chk_calmar = note.get("calmar")
        if chk_calmar is None:
            w_chk = (b.get("windows") or {}).get("check") or {}
            chk_calmar = w_chk.get("calmar")
        main: dict[str, Any] = {
            "id": cid,
            "label": cell.get("label"),
            "合计": _round_pnl(b.get("sum_pnl")),
            "调参期": _round_pnl(b.get("is_pnl")),
            "验收期": _round_pnl(b.get("oos_pnl")),
            "验收卡玛": None if chk_calmar is None else round(float(chk_calmar), 3),
        }
        if cell_is_current(cell) and cid:
            current_ids.add(str(cid))
        if "corner_oos_pnl" in b:
            main["盲测盈亏"] = _round_pnl(b.get("corner_oos_pnl"))
        main["是否通过"] = "否" if compact else "是"
        main_rows.append(main)
        tune_detail_rows.extend(_detail_window_rows(cell, b, windows_key="windows"))
        if isinstance(b.get("holdout_windows"), dict):
            hold_detail_rows.extend(
                _detail_window_rows(cell, b, windows_key="holdout_windows")
            )

    df = pd.DataFrame(main_rows)
    preview_ids = {
        str(c.get("id") or "")
        for c in (st.session_state.get("grid_cells") or [])
        if str(c.get("id") or "").strip()
    }
    extra_ids = [
        str(c.get("id") or "")
        for c in cells
        if str(c.get("id") or "").strip() and str(c.get("id") or "") not in preview_ids
    ]
    if preview_ids and extra_ids:
        st.warning(
            "主表含不在当前预览中的格子：%s。主表读的是该次 sweep 已跑结果，不是上方预览。"
            "请加载对应历史，或重新开跑（会生成新 sweep 目录）。"
            % "、".join(extra_ids)
        )
    st.caption(
        "调参期 %s–%s · 验收期 %s–%s%s · 单位：元（过门看侧栏；排序看验收卡玛）%s"
        % (
            win["tune_start"],
            win["tune_end"],
            win["check_start"],
            win["check_end"],
            " · 主列=调参标的" if space_on else "",
            " · 浅蓝底=现行参数" if current_ids else "",
        )
    )
    styled = df.style.apply(_style_current_ids(current_ids), axis=1)
    fmt: dict[str, str] = {}
    for col in ("合计", "调参期", "验收期", "盲测盈亏"):
        if col in df.columns:
            fmt[col] = "{:.0f}"
    if "验收卡玛" in df.columns:
        fmt["验收卡玛"] = "{:.3f}"
    if fmt:
        styled = styled.format(fmt, na_rep="—")
    st.dataframe(styled, width="stretch", hide_index=True)
    _render_fail_detail(notes_by_id, cells)

    with st.expander("窗内夏普 / 笔数 / 年化", expanded=False):
        _render_detail_window_table(
            tune_detail_rows,
            "调参标的" if space_on or hold_detail_rows else "跟踪池 / 主样本",
        )
        if hold_detail_rows:
            _render_detail_window_table(hold_detail_rows, "盲测标的（未参与调参）")
        st.caption(
            "过门用验收期窗内：卡玛、回撤%、夏普、笔数、胜率、盈亏比（非样本级整段）。"
            "笔数 = 窗内平仓；胜率 / 盈亏比按笔数。"
            "几何年化 / 卡玛 / 回撤来自同一条组合权益；账户盈亏 = 窗内期末 − 期初。"
            "旧 stock×年 sweep 须重跑，不能只汇总。"
        )
    st.caption(
        "合计 / 调参 / 验收是该窗账户盈亏（单账户、最多 3 笔、复利；空间隔离时主列=调参篮子）。"
    )
    _render_grid_year_perf(summary)
