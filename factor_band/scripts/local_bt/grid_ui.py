# coding: utf-8
"""参数网格任务页：可视化加格、开跑、看 summary。"""
from __future__ import annotations

import html
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, MutableMapping

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
    DEFAULT_N_TUNE,
    DEFAULT_UNIVERSE_DIR,
    AssetSplitError,
    draw_asset_split,
    fill_asset_split,
)
from grid_run import (
    GRID_ROOT,
    REPO,
    GridError,
    THEME,
    assemble_jobs,
    is_cell_dir,
    load_config_defaults,
    resolve_pool_workers,
    summarize_only,
    validate_spec,
)
from grid_progress import (
    SPAWN_GRACE_SEC,
    can_resume,
    done_cell_ids,
    grid_worker_argv,
    load_progress,
    mark_running_dead_as_dirty,
    progress_caption,
    spawn_creationflags,
    stop_worker_and_dirty,
    tail_text,
    ui_worker_busy,
    walk_progress_ratio,
    worker_definitely_dead,
    worker_is_alive,
)
from grid_score import default_score, score_cell, validate_score  # noqa: E402
from summarize import pick_recommend  # noqa: E402
from grid_spec import (
    YEAR_WINDOW_DEFAULTS,
    YEAR_WINDOW_KEYS,
    EDITOR_CELL_MAX,
    GROUP_ORDER,
    KIND_ENUM,
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


def _sweep_path(name: str) -> Path:
    return GRID_ROOT / str(name or "").strip()


def _load_grid_progress(name: str) -> dict[str, Any] | None:
    dest = _sweep_path(name)
    if not str(name or "").strip() or not dest.is_dir():
        return None
    return load_progress(dest)


def _reconcile_if_dead(name: str) -> dict[str, Any] | None:
    dest = _sweep_path(name)
    prog = _load_grid_progress(name)
    if not prog:
        return None
    if not worker_definitely_dead(prog):
        return prog
    return mark_running_dead_as_dirty(dest, prog, is_cell_dir)


def _grid_session_busy_kwargs() -> dict[str, Any]:
    spawned = st.session_state.get("grid_worker_spawned_at")
    try:
        spawned_at = float(spawned) if spawned is not None else None
    except (TypeError, ValueError):
        spawned_at = None
    return {
        "session_pid": int(st.session_state.get("grid_worker_pid") or 0),
        "spawned_at": spawned_at,
        "grace": SPAWN_GRACE_SEC,
        "stopping": bool(st.session_state.get("grid_stopping")),
    }


def _grid_worker_live(name: str = "") -> bool:
    sweep = str(name or st.session_state.get("grid_sweep") or "").strip()
    if not sweep:
        return False
    return ui_worker_busy(_load_grid_progress(sweep), **_grid_session_busy_kwargs())


def _grid_is_busy() -> bool:
    name = str(st.session_state.get("grid_sweep") or "").strip()
    prog = _load_grid_progress(name) if name else None
    busy = ui_worker_busy(prog, **_grid_session_busy_kwargs())
    st.session_state["grid_busy"] = busy
    if not busy:
        st.session_state["grid_worker_pid"] = 0
        st.session_state.pop("grid_worker_spawned_at", None)
        st.session_state["grid_stopping"] = False
    return busy


def _begin_resume_request(ss: MutableMapping[str, Any]) -> None:
    ss["grid_action"] = "resume"
    ss.pop("grid_pending_sweep", None)


def _begin_pause_request(ss: MutableMapping[str, Any]) -> None:
    ss["grid_action"] = "pause"


def _mark_resume() -> None:
    _begin_resume_request(st.session_state)


def _mark_pause() -> None:
    _begin_pause_request(st.session_state)


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
    pending = ss.pop("grid_pending_import", None)
    if isinstance(pending, dict) and pending:
        _apply_pending_import(ss, pending)
    ss.setdefault("grid_sweep", "")
    ss.setdefault("grid_compare_div", DEFAULT_DIVIDEND_TYPE)
    ss.setdefault("grid_workers", 0)
    for key, default in YEAR_WINDOW_DEFAULTS.items():
        ss.setdefault("grid_%s" % key, int(default))
    if "grid_param_sel" not in ss:
        ss["grid_param_sel"] = _migrate_old_sel(ss)
    ss["grid_param_sel"] = merge_param_selection(ss.get("grid_param_sel"))
    ss.setdefault("grid_cells", [])
    ss.setdefault("grid_summary", None)
    ss.setdefault("grid_busy", False)
    ss.setdefault("grid_batch_size", 10)
    ss.setdefault("grid_import_text", "")
    ss.setdefault("grid_param_group", "全部")
    ss.setdefault("grid_param_search", "")
    ss.setdefault("grid_asset_split", False)
    if "grid_n_draw" not in ss:
        legacy = ss.get("grid_n_tune")
        try:
            ss["grid_n_draw"] = int(legacy if legacy is not None else DEFAULT_N_TUNE)
        except (TypeError, ValueError):
            ss["grid_n_draw"] = int(DEFAULT_N_TUNE)
    ss.setdefault("grid_tune_stocks", [])
    ss.setdefault("grid_holdout_stocks", [])
    ss.setdefault("grid_eligible_n", 0)
    ss.setdefault("grid_reshuffle", False)
    ss.setdefault("grid_full_span", False)
    ds = default_score()
    ss.setdefault("grid_score_w_def", float(ds["w_def"]) * 100.0)
    ss.setdefault("grid_score_w_str", float(ds["w_str"]) * 100.0)
    ss.setdefault("grid_score_w_res", float(ds["w_res"]) * 100.0)
    ss.setdefault("grid_score_w_gen", float(ds["w_gen"]) * 100.0)
    ss.setdefault("grid_score_dd_cap_pct", float(ds["dd_cap"]) * 100.0)
    ss.setdefault("grid_score_factor_target", float(ds["factor_target"]))
    ss.setdefault("grid_score_pf_cap", float(ds["pf_cap"]))
    ss.setdefault("grid_score_sharpe_target", float(ds["sharpe_target"]))
    ss.setdefault("grid_score_n_trades_floor", int(ds["n_trades_floor"]))
    ss.setdefault("grid_score_n_trades_full", int(ds["n_trades_full"]))
    ss.setdefault("grid_sort_metric", "总分")
    ss.setdefault("grid_sort_dir", "降")
    ss.setdefault("grid_sort_metric_prev", "总分")
    ss.setdefault(_DETAIL_PAGE_SIZE_KEY, _DETAIL_PAGE_SIZE_DEFAULT)
    ss.setdefault(_DETAIL_PAGE_KEY, 1)
    ss.setdefault(_DETAIL_PAGE_TOKEN_KEY, "")


def _score_from_state() -> dict[str, Any]:
    """从侧栏读评分配置；勿在 widget 实例化后回写同名 session 键。"""
    ss = st.session_state
    raw = {
        "w_def": float(ss.get("grid_score_w_def") or 30.0),
        "w_str": float(ss.get("grid_score_w_str") or 25.0),
        "w_res": float(ss.get("grid_score_w_res") or 25.0),
        "w_gen": float(ss.get("grid_score_w_gen") or 20.0),
        "dd_cap": float(ss.get("grid_score_dd_cap_pct") or 35.0),
        "factor_target": float(ss.get("grid_score_factor_target") or 0.5),
        "pf_cap": float(ss.get("grid_score_pf_cap") or 5.0),
        "sharpe_target": float(ss.get("grid_score_sharpe_target") or 0.5),
        "n_trades_floor": float(ss.get("grid_score_n_trades_floor") or 30.0),
        "n_trades_full": float(ss.get("grid_score_n_trades_full") or 80.0),
    }
    return validate_score(raw)


def _score_cfg_for_view() -> dict[str, Any]:
    try:
        return _score_from_state()
    except ValueError:
        return default_score()


def _asset_split_from_state() -> dict[str, Any]:
    if not st.session_state.get("grid_asset_split"):
        return fill_asset_split({"asset_split": {"mode": "off"}})
    try:
        n = int(st.session_state.get("grid_n_draw") or DEFAULT_N_TUNE)
    except (TypeError, ValueError):
        n = int(DEFAULT_N_TUNE)
    if n < 1:
        n = 1
    return {
        "mode": "random_from_csv",
        "universe_dir": DEFAULT_UNIVERSE_DIR,
        "n": n,
        "n_tune": n,
        "n_holdout": n,
        "ma_type": "EMA",
        "dividend_type": str(
            st.session_state.get("grid_compare_div") or DEFAULT_DIVIDEND_TYPE
        ),
        "exclude": [],
        "full_span": bool(st.session_state.get("grid_full_span")),
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
        score=_score_cfg_for_view(),
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
    busy = _grid_is_busy()
    if st.session_state.get("grid_asset_split"):
        st.caption(
            "主样本=csv/none 抽取名单（调参∪盲测）；均线/复权锁 compare_div。"
        )
    else:
        st.caption("主样本=跟踪池 BOOK_STOCKS（config 锁定均线/复权），不可勾选。")
    last = str(st.session_state.get("grid_sweep") or "").strip()
    prog = _load_grid_progress(last) if last else None
    if _grid_is_busy():
        st.caption(
            "正在跑 sweep `%s` · 暂停后本组整组重来；继续不换目录"
            % last
        )
    elif last:
        st.caption("当前 sweep `%s` · 新开跑会 mint 新目录；继续沿用此目录" % last)
    else:
        st.caption("sweep 新开跑自动生成 · 尚未开跑")
    if prog:
        cap = progress_caption(prog)
        if cap:
            st.caption(cap)
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
        st.caption(
            "宇宙：`%s` · 抽 N 只调参，再从剩余抽 N 只盲测（不重叠）。"
            "盲测空间分进入排名。改数量或勾选后须再点抽取，否则开跑沿用已抽名单。"
            % DEFAULT_UNIVERSE_DIR
        )
        st.number_input(
            "抽取数",
            min_value=1,
            max_value=500,
            step=1,
            key="grid_n_draw",
            disabled=busy,
            persist_state="session",
        )
        st.checkbox(
            "只抽全区间有行情",
            key="grid_full_span",
            disabled=busy,
            persist_state="session",
        )
        st.caption("勾选后：起始年年内已有第一根、且行情接到宇宙最末日。改勾选须再点抽取。")
        if st.button("抽取", disabled=busy, key="grid_draw_split"):
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

    with st.expander("评分维度", expanded=False):
        st.caption("改这里再点「只汇总」会重算推荐与主表分数，不必重跑。")
        w1, w2 = st.columns(2)
        with w1:
            st.number_input(
                "防御权重%",
                min_value=0.0,
                max_value=100.0,
                step=1.0,
                format="%.0f",
                key="grid_score_w_def",
                disabled=busy,
                persist_state="session",
            )
            st.number_input(
                "复原权重%",
                min_value=0.0,
                max_value=100.0,
                step=1.0,
                format="%.0f",
                key="grid_score_w_res",
                disabled=busy,
                persist_state="session",
            )
        with w2:
            st.number_input(
                "结构权重%",
                min_value=0.0,
                max_value=100.0,
                step=1.0,
                format="%.0f",
                key="grid_score_w_str",
                disabled=busy,
                persist_state="session",
            )
            st.number_input(
                "泛化权重%",
                min_value=0.0,
                max_value=100.0,
                step=1.0,
                format="%.0f",
                key="grid_score_w_gen",
                disabled=busy,
                persist_state="session",
            )
        w_sum = (
            float(st.session_state.get("grid_score_w_def") or 0.0)
            + float(st.session_state.get("grid_score_w_str") or 0.0)
            + float(st.session_state.get("grid_score_w_res") or 0.0)
            + float(st.session_state.get("grid_score_w_gen") or 0.0)
        )
        st.caption("当前权重和 %.0f%%（打分时归一成 1；无盲测摊掉泛化）" % w_sum)
        st.number_input(
            "回撤 0 分线 %",
            min_value=0.1,
            max_value=100.0,
            step=1.0,
            format="%.1f",
            key="grid_score_dd_cap_pct",
            disabled=busy,
            persist_state="session",
        )
        st.number_input(
            "获利因子目标",
            min_value=0.01,
            max_value=10.0,
            step=0.05,
            format="%.2f",
            key="grid_score_factor_target",
            disabled=busy,
            persist_state="session",
        )
        st.number_input(
            "盈亏比封顶",
            min_value=0.1,
            max_value=99.0,
            step=0.5,
            format="%.1f",
            key="grid_score_pf_cap",
            disabled=busy,
            persist_state="session",
        )
        st.number_input(
            "夏普目标",
            min_value=0.01,
            max_value=5.0,
            step=0.05,
            format="%.2f",
            key="grid_score_sharpe_target",
            disabled=busy,
            persist_state="session",
        )
        n1, n2 = st.columns(2)
        with n1:
            st.number_input(
                "笔数 0 分线",
                min_value=0,
                max_value=10000,
                step=1,
                key="grid_score_n_trades_floor",
                disabled=busy,
                persist_state="session",
            )
        with n2:
            st.number_input(
                "笔数满分线",
                min_value=1,
                max_value=10000,
                step=1,
                key="grid_score_n_trades_full",
                disabled=busy,
                persist_state="session",
            )
        try:
            _score_from_state()
        except ValueError as e:
            st.error(str(e))

    st.number_input(
        "并行进程数（0=自动=min(walk 数, CPU)；格间与格内共用）",
        min_value=0,
        max_value=16,
        step=1,
        key="grid_workers",
        disabled=busy,
        persist_state="session",
    )
    st.number_input(
        "每批格数（一组没跑完则整组重来）",
        min_value=1,
        max_value=500,
        step=1,
        key="grid_batch_size",
        disabled=busy,
        persist_state="session",
    )
    n_preview = len(st.session_state.get("grid_cells") or [])
    jobs_per = 2 if st.session_state.get("grid_asset_split") else 1
    n_walks = max(0, n_preview * jobs_per)
    pool_n = resolve_pool_workers(int(st.session_state.get("grid_workers") or 0), n_walks)
    bs = int(st.session_state.get("grid_batch_size") or 10)
    n_batches = (n_preview + bs - 1) // bs if n_preview and bs else 0
    st.caption(
        "将开 %s 路（%s 格 × %s walk）· 约 %s 组"
        % (pool_n, n_preview, jobs_per, n_batches)
    )
    if st.button("保存 spec 到 gridConfig", disabled=busy, key="grid_save_spec"):
        _save_spec_clicked()
    resume_ok = bool(not busy and last and can_resume(prog))
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
            "暂停",
            disabled=not busy,
            key="grid_pause",
            on_click=_mark_pause,
            wrap=False,
            width="stretch",
        )
        st.button(
            "继续",
            disabled=not resume_ok,
            key="grid_resume",
            on_click=_mark_resume,
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
    # 勿回写 grid_n_draw：已绑定 number_input，实例化后改会抛 StreamlitAPIException
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
    _handle_actions(defaults)
    flash = st.session_state.pop("grid_flash", None)
    if flash:
        st.info(str(flash))

    st.caption(
        "主样本默认=跟踪池 BOOK_STOCKS × 回测年；开启空间隔离后=csv/none 抽取名单。"
        "选参看调参标的验收期，且须与调参期同向；盲测盈亏只否决。"
        "默认不改 config.py / 不 deploy。"
    )
    _poll_grid_worker()
    busy = _grid_is_busy()
    _render_param_table(defaults, busy)
    _render_action_bar(defaults, busy)
    _render_preview(defaults, busy)
    _render_advanced(defaults, busy)
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
                    help="标量：逗号或空格分隔，如 6,10。百分数可写 6%、6 或 0.06。ATR 倍数可写 1.5。trail_stop.tiers 写 JSON 整表，多组换行。",
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


def _render_action_bar(defaults: dict[str, Any], busy: bool) -> None:
    locked = generator_locked(st.session_state.get("grid_cells") or [])
    if locked:
        st.warning("导入 spec 含非白名单键，生成器已锁定。仍可开跑。")
    name = str(st.session_state.get("grid_sweep") or "").strip()
    prog = _load_grid_progress(name) if name else None
    resume_ok = bool(not busy and name and can_resume(prog))
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
            "暂停",
            disabled=not busy,
            key="grid_pause_main",
            on_click=_mark_pause,
        )
        st.button(
            "继续",
            disabled=not resume_ok,
            key="grid_resume_main",
            on_click=_mark_resume,
        )
        st.button(
            "只汇总已有结果",
            disabled=busy,
            key="grid_sum_main",
            on_click=_mark_summarize,
        )
    st.caption("只汇总按窗 KPI 重算四维综合分；侧栏过门线只着色、不改推荐。")
    if prog:
        cap = progress_caption(prog)
        if cap:
            st.caption(cap)
    if busy:
        st.caption("暂停已请求后将结束进程；未完成的一组会整组重跑。")
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
            hi = st.selectbox("打开历史 summary", hlabels, key="grid_hist_pick", disabled=busy)
            if st.button("加载历史", key="grid_hist_load", disabled=busy):
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


def _spec_import_payload(spec: Mapping[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """解析 spec → pending；不写 widget 键（须在下一轮 _ensure_state 里套）。"""
    reject_retired_min_ret(spec)
    cells = correct_cell_kinds(spec.get("cells") or [], defaults)
    win = fill_year_windows(spec)
    axes = axes_from_cells(cells, defaults)
    payload: dict[str, Any] = {
        "cells": cells,
        "windows": {key: int(win[key]) for key in YEAR_WINDOW_KEYS},
        "param_sel": apply_axes_to_selection(None, axes),
        "flash": "已导入 %s 格%s"
        % (len(cells), "（生成器锁定）" if generator_locked(cells) else ""),
    }
    if spec.get("sweep"):
        payload["sweep"] = str(spec["sweep"])
    if spec.get("compare_div"):
        payload["compare_div"] = str(spec["compare_div"])
    return payload


def _apply_pending_import(ss: MutableMapping[str, Any], pending: Mapping[str, Any]) -> None:
    ss["grid_cells"] = list(pending.get("cells") or [])
    ss.pop("grid_cells_editor", None)
    ss.pop("grid_cells_editor_v2", None)
    ss.pop("grid_param_editor", None)
    name = str(pending.get("sweep") or "").strip()
    if name and (GRID_ROOT / name / "summary.json").is_file():
        ss["grid_sweep"] = name
    if pending.get("compare_div"):
        ss["grid_compare_div"] = str(pending["compare_div"])
    windows = pending.get("windows") or {}
    if isinstance(windows, Mapping):
        for key in YEAR_WINDOW_KEYS:
            if key in windows:
                ss["grid_%s" % key] = int(windows[key])
    if pending.get("param_sel") is not None:
        ss["grid_param_sel"] = dict(pending["param_sel"])
    if pending.get("flash"):
        ss["grid_flash"] = str(pending["flash"])


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
        payload = _spec_import_payload(spec, defaults)
    except GridSpecError as e:
        st.error(str(e))
        return
    st.session_state["grid_pending_import"] = payload
    st.rerun()


def _handle_actions(defaults: dict[str, Any]) -> None:
    action = st.session_state.get("grid_action")
    if not action:
        return
    if action == "pause":
        st.session_state.pop("grid_action", None)
        name = str(st.session_state.get("grid_sweep") or "").strip()
        dest = GRID_ROOT / name if name else None
        pid = int(st.session_state.get("grid_worker_pid") or 0)
        prog = _load_grid_progress(name) if name else None
        if not pid and prog:
            pid = int(prog.get("worker_pid") or 0)
        st.session_state["grid_stopping"] = True
        st.session_state["grid_busy"] = True
        if dest is None or not name:
            st.session_state["grid_stopping"] = False
            st.session_state["grid_busy"] = False
            st.session_state["grid_worker_pid"] = 0
            return
        with st.spinner("正在结束进程树，退出后再标脏组…"):
            result = stop_worker_and_dirty(dest, pid, is_cell_dir)
        if not result.get("ok"):
            st.error("进程未在时限内退出，请再点暂停；继续已禁用。")
            _persist_app()
            return
        st.session_state["grid_stopping"] = False
        st.session_state["grid_busy"] = False
        st.session_state["grid_worker_pid"] = 0
        st.session_state.pop("grid_worker_spawned_at", None)
        st.session_state["grid_flash"] = "已暂停：进程已退出，本组将整组重跑。"
        _persist_app()
        st.rerun()
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
            prog = load_progress(dest)
            want = done_cell_ids(prog) if prog else []
            if not want:
                want = [
                    str(c.get("id") or "")
                    for c in (spec.get("cells") or [])
                    if str(c.get("id") or "").strip()
                ]
            out = summarize_only(dest, score=_score_from_state(), cell_ids=want or None)
            st.session_state["grid_summary"] = out
            st.success("已汇总")
        except Exception as e:
            st.error(str(e))
        return
    if action == "resume":
        st.session_state.pop("grid_action", None)
        name = str(st.session_state.get("grid_sweep") or "").strip()
        if not sweep_name_ok(name):
            st.error("还没有 sweep：请先开跑")
            return
        dest = GRID_ROOT / name
        spec_file = dest / "spec.json"
        if not spec_file.is_file():
            st.error("找不到 %s" % spec_file)
            return
        if ui_worker_busy(_load_grid_progress(name), **_grid_session_busy_kwargs()):
            st.error("仍有 worker 在跑，请先暂停")
            return
        prog = _reconcile_if_dead(name)
        if not can_resume(prog):
            st.error("没有可继续的组")
            return
        _spawn_grid_worker(dest, spec_file, resume=True)
        return
    try:
        validate_spec(spec)
    except GridError as e:
        st.error(str(e))
        st.session_state.pop("grid_action", None)
        return
    if action != "run":
        st.session_state.pop("grid_action", None)
        return
    if _grid_is_busy():
        st.session_state.pop("grid_action", None)
        st.error("已有网格在跑")
        return
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
        assemble_jobs(spec)
    except GridError as e:
        st.error(str(e))
        st.session_state.pop("grid_action", None)
        return
    st.session_state.pop("grid_action", None)
    dest = _sweep_dir(spec)
    dest.mkdir(parents=True, exist_ok=True)
    spec_file = dest / "spec.json"
    spec_file.write_text(spec_json(spec), encoding="utf-8")
    _spawn_grid_worker(dest, spec_file, resume=False, spec=spec)


def _spawn_grid_worker(
    dest: Path,
    spec_file: Path,
    *,
    resume: bool,
    spec: dict[str, Any] | None = None,
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    cmd = grid_worker_argv(
        spec_path=str(spec_file),
        sweep_dir=str(dest),
        workers=int(st.session_state.get("grid_workers") or 0),
        batch_size=int(st.session_state.get("grid_batch_size") or 10),
        resume=bool(resume),
    )
    log_path = dest / "worker.log"
    log_f = open(log_path, "ab")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            shell=False,
            creationflags=spawn_creationflags(),
        )
    except Exception as e:
        log_f.close()
        st.error("无法启动网格进程：%s" % e)
        st.session_state["grid_busy"] = False
        st.session_state["grid_stopping"] = False
        st.session_state.pop("grid_pending_sweep", None)
        return
    log_f.close()
    st.session_state["grid_worker_pid"] = int(proc.pid)
    st.session_state["grid_worker_spawned_at"] = time.time()
    st.session_state["grid_busy"] = True
    st.session_state["grid_stopping"] = False
    st.session_state.pop("grid_pending_sweep", None)
    if spec:
        split = spec.get("asset_split") or {}
        if split.get("tune_stocks"):
            st.session_state["grid_tune_stocks"] = list(split.get("tune_stocks") or [])
            st.session_state["grid_holdout_stocks"] = list(split.get("holdout_stocks") or [])
            st.session_state["grid_eligible_n"] = int(split.get("eligible_n") or 0)
    st.session_state["grid_flash"] = (
        "已启动进程 pid=%s。进度在下方刷新。"
        % proc.pid
    )
    _persist_app()
    st.rerun()


def _sync_grid_worker_state(*, load_summary: bool = True) -> dict[str, Any] | None:
    name = str(st.session_state.get("grid_sweep") or "").strip()
    if not name:
        return None
    dest = GRID_ROOT / name
    prog = _reconcile_if_dead(name)
    live = ui_worker_busy(prog, **_grid_session_busy_kwargs())
    was_busy = bool(st.session_state.get("grid_busy"))
    st.session_state["grid_busy"] = bool(live)
    if was_busy and not live:
        st.session_state["grid_worker_pid"] = 0
        st.session_state.pop("grid_pending_sweep", None)
        st.session_state.pop("grid_worker_spawned_at", None)
        st.session_state["grid_stopping"] = False
        if load_summary:
            summary_p = dest / "summary.json"
            if summary_p.is_file():
                try:
                    st.session_state["grid_summary"] = json.loads(summary_p.read_text(encoding="utf-8"))
                except Exception:
                    pass
        _persist_app()
    return prog


def _render_run_status() -> None:
    name = str(st.session_state.get("grid_sweep") or "").strip()
    prog = _load_grid_progress(name) if name else None
    busy = bool(st.session_state.get("grid_busy")) or ui_worker_busy(
        prog, **_grid_session_busy_kwargs()
    )
    if not name and not busy:
        return
    cap = progress_caption(prog) if prog else ""
    if busy:
        st.info(
            "正在跑网格"
            + (" · %s" % cap if cap else " · 正在写 progress")
        )
    elif cap:
        st.caption(cap)
    frac, walk_tot = walk_progress_ratio(prog)
    if walk_tot > 0:
        st.progress(frac)
        st.caption("本组 walk %.1f / %s" % (float(prog.get("batch_walk_done") or 0), walk_tot))
    if prog:
        n_done = len(done_cell_ids(prog))
        n_all = len([x for x in (prog.get("cell_ids") or []) if str(x).strip()])
        if n_all:
            st.caption("已完成格子 %s / %s" % (n_done, n_all))
        batches = prog.get("batches") or []
        if (
            n_done
            and not worker_is_alive(prog)
            and any(isinstance(b, dict) and str(b.get("status") or "") != "done" for b in batches)
        ):
            st.caption("未跑完：推荐只基于已完成组。")
    if name:
        log_path = GRID_ROOT / name / "worker.log"
        tail = tail_text(log_path, 16)
        if tail:
            st.code(tail, language="text")


def _progress_tick() -> None:
    was = bool(st.session_state.get("grid_busy"))
    _sync_grid_worker_state()
    _render_run_status()
    now = bool(st.session_state.get("grid_busy"))
    if was != now:
        st.rerun()


_PROGRESS_FRAG = None


def _call_progress_fragment() -> None:
    global _PROGRESS_FRAG
    if _PROGRESS_FRAG is None:
        fn = _progress_tick
        if hasattr(st, "fragment"):
            try:
                fn = st.fragment(run_every=2.0)(_progress_tick)
            except Exception:
                fn = _progress_tick
        _PROGRESS_FRAG = fn
    _PROGRESS_FRAG()


def _poll_grid_worker() -> None:
    _sync_grid_worker_state()
    _call_progress_fragment()


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
_SORT_TOTAL = "总分"
_SORT_OPTIONS = (_SORT_TOTAL,) + _DETAIL_METRIC_COLS
_DETAIL_GROUP_SIZE = len(_DETAIL_PERIODS)
_DETAIL_PAGE_SIZES = (5, 10, 20)
_DETAIL_PAGE_SIZE_DEFAULT = 5
_DETAIL_PAGE_KEY = "grid_detail_page"
_DETAIL_PAGE_SIZE_KEY = "grid_detail_page_size"
_DETAIL_PAGE_TOKEN_KEY = "grid_detail_page_token"


def _detail_window_rows(
    cell: dict[str, Any],
    book: dict[str, Any],
    *,
    windows_key: str = "windows",
    basket: str | None = None,
) -> list[dict[str, Any]]:
    """每格固定 3 行（全区间 / 调参期 / 验收期），缺窗也出空指标行。"""
    cid = cell.get("id")
    label = cell.get("label")
    rows: list[dict[str, Any]] = []
    for period, wkey in _DETAIL_PERIODS:
        mdd = _window_metric(book, wkey, "max_dd", windows_key=windows_key)
        row: dict[str, Any] = {
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
        if basket:
            row["篮子"] = basket
        rows.append(row)
    return rows


def _stack_detail_window_rows(
    cell: dict[str, Any],
    book: dict[str, Any],
    *,
    space_on: bool,
) -> list[dict[str, Any]]:
    """无空间隔离 3 行；有则调参 3 + 盲测 3（缺 holdout 窗也出空行）。"""
    if not space_on:
        return _detail_window_rows(cell, book, windows_key="windows")
    tune = _detail_window_rows(
        cell, book, windows_key="windows", basket="调参"
    )
    hold = _detail_window_rows(
        cell, book, windows_key="holdout_windows", basket="盲测"
    )
    return tune + hold


def _cell_column_mean(chunk: list[dict[str, Any]], metric: str) -> float | None:
    """一格该列非空数字等权平均；全空返回 None。"""
    vals: list[float] = []
    for row in chunk:
        raw = row.get(metric)
        if raw is None:
            continue
        try:
            vals.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not vals:
        return None
    return sum(vals) / float(len(vals))


def _detail_sort_group_size(rows: list[dict[str, Any]]) -> int:
    if _detail_table_has_basket(rows):
        return _DETAIL_GROUP_SIZE * 2
    return _DETAIL_GROUP_SIZE


def _iter_detail_groups(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if not rows:
        return []
    group_size = _detail_sort_group_size(rows)
    return [rows[i : i + group_size] for i in range(0, len(rows), group_size)]


def _coerce_detail_page_size(raw: Any) -> int:
    try:
        size = int(raw)
    except (TypeError, ValueError):
        return _DETAIL_PAGE_SIZE_DEFAULT
    if size in _DETAIL_PAGE_SIZES:
        return size
    return _DETAIL_PAGE_SIZE_DEFAULT


def _detail_page_count(n_groups: int, size: int) -> int:
    if n_groups <= 0:
        return 1
    step = size if size > 0 else _DETAIL_PAGE_SIZE_DEFAULT
    return max(1, (n_groups + step - 1) // step)


def _slice_detail_page(
    groups: list[list[dict[str, Any]]],
    page: int,
    size: int,
) -> list[dict[str, Any]]:
    """按整格切片；page 为 1-based。"""
    if not groups:
        return []
    step = size if size > 0 else _DETAIL_PAGE_SIZE_DEFAULT
    n_pages = _detail_page_count(len(groups), step)
    try:
        idx = int(page)
    except (TypeError, ValueError):
        idx = 1
    idx = min(max(idx, 1), n_pages)
    start = (idx - 1) * step
    out: list[dict[str, Any]] = []
    for chunk in groups[start : start + step]:
        out.extend(chunk)
    return out


def _detail_page_token() -> str:
    ss = st.session_state
    return "%s|%s|%s" % (
        ss.get("grid_sweep") or "",
        ss.get("grid_sort_metric") or "",
        ss.get("grid_sort_dir") or "",
    )


def _reset_detail_page_if_context_changed() -> None:
    """换 sweep / 表序时回到第 1 页；须在 pagination 控件实例化前写键。"""
    ss = st.session_state
    token = _detail_page_token()
    if ss.get(_DETAIL_PAGE_TOKEN_KEY) != token:
        ss[_DETAIL_PAGE_TOKEN_KEY] = token
        ss[_DETAIL_PAGE_KEY] = 1


def _sort_detail_groups(
    rows: list[dict[str, Any]],
    metric: str,
    descending: bool,
) -> list[dict[str, Any]]:
    """按列综合均值排整格；非法列名保持原序；缺值整格垫底。"""
    if not rows or metric not in _DETAIL_METRIC_COLS:
        return list(rows)
    groups = _iter_detail_groups(rows)

    def _key(chunk: list[dict[str, Any]]) -> tuple[int, float]:
        mean = _cell_column_mean(chunk, metric)
        if mean is None:
            return (1, 0.0)
        return (0, -mean if descending else mean)

    groups.sort(key=_key)
    out: list[dict[str, Any]] = []
    for chunk in groups:
        out.extend(chunk)
    return out


def _reorder_main_rows(
    main_rows: list[dict[str, Any]],
    detail_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按明细组出现的 id 重排主表；明细没有的主表行追加在后。"""
    if not main_rows:
        return []
    seen: list[str] = []
    for row in detail_rows:
        cid = str(row.get("id") or "")
        if cid and cid not in seen:
            seen.append(cid)
    by_id = {str(r.get("id") or ""): r for r in main_rows}
    used: set[str] = set()
    out: list[dict[str, Any]] = []
    for cid in seen:
        row = by_id.get(cid)
        if row is None:
            continue
        out.append(row)
        used.add(cid)
    for row in main_rows:
        cid = str(row.get("id") or "")
        if cid not in used:
            out.append(row)
            used.add(cid)
    return out


def _sort_main_by_total(
    rows: list[dict[str, Any]],
    *,
    descending: bool,
) -> list[dict[str, Any]]:
    def _key(row: dict[str, Any]) -> tuple[int, float]:
        raw = row.get("总分")
        if raw is None:
            return (1, 0.0)
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return (1, 0.0)
        return (0, -v if descending else v)

    return sorted(rows, key=_key)


def _reorder_detail_to_main(
    detail_rows: list[dict[str, Any]],
    main_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """按主表 id 顺序重排明细组。"""
    if not detail_rows:
        return []
    groups = _iter_detail_groups(detail_rows)
    by_id: dict[str, list[dict[str, Any]]] = {}
    for chunk in groups:
        cid = str(chunk[0].get("id") or "") if chunk else ""
        if cid and cid not in by_id:
            by_id[cid] = chunk
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for row in main_rows:
        cid = str(row.get("id") or "")
        chunk = by_id.get(cid)
        if not chunk:
            continue
        out.extend(chunk)
        used.add(cid)
    for chunk in groups:
        cid = str(chunk[0].get("id") or "") if chunk else ""
        if cid in used:
            continue
        out.extend(chunk)
        used.add(cid)
    return out


_DETAIL_TONE_COLS = ("夏普", "卡玛", "胜率%", "盈亏比", "几何年化%", "账户盈亏", "回撤%", "笔数")
_DETAIL_PASS_COLOR = "#e74c3c"
_EPS_TONE = 1e-6
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


def _detail_metric_tone(
    col: str, val: Any, score: dict[str, Any] | None
) -> str | None:
    """过线返回 pass；未过线与缺值返回 None（保持默认字色）。"""
    if col not in _DETAIL_TONE_COLS or val is None:
        return None
    try:
        x = float(val)
    except (TypeError, ValueError):
        return None
    cfg = score or {}
    if col == "回撤%":
        try:
            cap = float(cfg.get("dd_cap") or 0.35) * 100.0
        except (TypeError, ValueError):
            cap = 35.0
        if x <= cap + _EPS_TONE:
            return "pass"
        return None
    if col == "笔数":
        try:
            floor = float(cfg.get("n_trades_floor") or 30.0)
        except (TypeError, ValueError):
            floor = 30.0
        if x + _EPS_TONE >= floor:
            return "pass"
        return None
    if x + _EPS_TONE >= 0.0:
        return "pass"
    return None


_DETAIL_TUNE_BG_DARK = "rgba(56, 139, 253, 0.12)"
_DETAIL_HOLD_BG_DARK = "rgba(210, 153, 34, 0.12)"
_DETAIL_TUNE_BG_LIGHT = "rgba(56, 139, 253, 0.10)"
_DETAIL_HOLD_BG_LIGHT = "rgba(210, 153, 34, 0.12)"


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
            "tune": _DETAIL_TUNE_BG_DARK,
            "hold": _DETAIL_HOLD_BG_DARK,
        }
    return {
        "color": "var(--text-color, #1f2328)",
        "header_bg": "var(--secondary-background-color, #f0f2f6)",
        "border": "rgba(31,35,40,0.18)",
        "zebra": "rgba(0,0,0,0.04)",
        "tune": _DETAIL_TUNE_BG_LIGHT,
        "hold": _DETAIL_HOLD_BG_LIGHT,
    }


def _basket_row_bg(pal: dict[str, str], basket: str) -> str:
    if basket == "调参":
        return pal.get("tune") or ""
    if basket == "盲测":
        return pal.get("hold") or ""
    return ""


def _html_cell(
    text: str,
    style: str,
    *,
    tag: str = "td",
    rowspan: int | None = None,
) -> str:
    rs = ' rowspan="%d"' % rowspan if rowspan and rowspan > 1 else ""
    return "<%s%s style=\"%s\">%s</%s>" % (tag, rs, style, text, tag)


def _detail_table_has_basket(rows: list[dict[str, Any]]) -> bool:
    return any(str(r.get("篮子") or "").strip() for r in rows)


def _detail_window_table_html(
    rows: list[dict[str, Any]],
    score: dict[str, Any] | None = None,
) -> str:
    pal = _detail_table_palette()
    cell_base = (
        "border:none;border-bottom:1px solid %s;padding:0.35rem 0.6rem;"
        "vertical-align:middle;color:%s;"
        % (pal["border"], pal["color"])
    )
    has_basket = _detail_table_has_basket(rows)
    group_size = (_DETAIL_GROUP_SIZE * 2) if has_basket else _DETAIL_GROUP_SIZE
    if has_basket:
        headers = ["id", "label", "篮子", ""] + list(_DETAIL_METRIC_COLS)
        th_align = ["left", "left", "center", "center"] + ["right"] * len(
            _DETAIL_METRIC_COLS
        )
    else:
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
        chunk = rows[i : i + group_size]
        span = len(chunk)
        zebra = pal["zebra"] if group_i % 2 == 1 else ""
        id_bg = "background:%s;" % zebra if zebra else ""
        for j, row in enumerate(chunk):
            basket = str(row.get("篮子") or "")
            row_color = _basket_row_bg(pal, basket) if has_basket else zebra
            row_bg = "background:%s;" % row_color if row_color else ""
            parts.append("<tr>")
            if j == 0:
                id_style = "%s%stext-align:left;white-space:nowrap;" % (
                    cell_base,
                    id_bg,
                )
                label_style = (
                    "%s%stext-align:left;width:%s;max-width:%s;"
                    "white-space:normal;overflow-wrap:anywhere;"
                    % (cell_base, id_bg, _DETAIL_LABEL_WIDTH, _DETAIL_LABEL_WIDTH)
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
            mid_style = "%s%stext-align:center;white-space:nowrap;" % (
                cell_base,
                row_bg,
            )
            if has_basket and (
                j == 0
                or str(chunk[j - 1].get("篮子") or "") != str(row.get("篮子") or "")
            ):
                basket_span = 0
                for later in chunk[j:]:
                    if str(later.get("篮子") or "") != basket:
                        break
                    basket_span += 1
                parts.append(
                    _html_cell(
                        html.escape(basket),
                        mid_style,
                        rowspan=basket_span,
                    )
                )
            parts.append(
                _html_cell(html.escape(str(row.get("区间") or "")), mid_style)
            )
            for col in _DETAIL_METRIC_COLS:
                extra = ""
                if _detail_metric_tone(col, row.get(col), score) == "pass":
                    extra = "color:%s;" % _DETAIL_PASS_COLOR
                metric_style = (
                    "%s%stext-align:right;font-variant-numeric:tabular-nums;%s"
                    % (cell_base, row_bg, extra)
                )
                parts.append(
                    _html_cell(_fmt_detail_metric(col, row.get(col)), metric_style)
                )
            parts.append("</tr>")
        i += group_size
        group_i += 1
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _render_detail_window_table(rows: list[dict[str, Any]], caption: str) -> None:
    st.caption(caption)
    groups = _iter_detail_groups(rows)
    n_groups = len(groups)
    _reset_detail_page_if_context_changed()
    size = _DETAIL_PAGE_SIZE_DEFAULT
    page = 1
    if n_groups > _DETAIL_PAGE_SIZE_DEFAULT:
        c_size, c_page = st.columns([1.4, 2.6], vertical_alignment="bottom")
        with c_size:
            picked = st.segmented_control(
                "每页格数",
                options=list(_DETAIL_PAGE_SIZES),
                key=_DETAIL_PAGE_SIZE_KEY,
                required=True,
                persist_state="session",
            )
            size = _coerce_detail_page_size(
                picked if picked is not None else st.session_state.get(_DETAIL_PAGE_SIZE_KEY)
            )
        n_pages = _detail_page_count(n_groups, size)
        with c_page:
            if n_pages > 1:
                page = st.pagination(
                    n_pages,
                    key=_DETAIL_PAGE_KEY,
                    persist_state="session",
                    width="stretch",
                )
            start_i = (int(page) - 1) * size + 1
            end_i = min(int(page) * size, n_groups)
            st.caption("本页格子 %d–%d / 共 %d" % (start_i, end_i, n_groups))
    page_rows = _slice_detail_page(groups, page, size)
    body = _detail_window_table_html(page_rows, score=_score_cfg_for_view())
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


def _default_sort_dir(metric: str) -> str:
    return "升" if metric == "回撤%" else "降"


def _sync_sort_dir_on_metric_change() -> None:
    """切列时重置方向：回撤%→升，其余→降。同列不改，方便手调。"""
    ss = st.session_state
    raw = ss.get("grid_sort_metric")
    metric = str(raw or _SORT_TOTAL)
    if metric not in _SORT_OPTIONS:
        metric = _SORT_TOTAL
    if raw != metric:
        ss["grid_sort_metric"] = metric
    prev = ss.get("grid_sort_metric_prev")
    if prev != metric:
        ss["grid_sort_dir"] = _default_sort_dir(metric)
        ss["grid_sort_metric_prev"] = metric


def _render_result_sort_bar() -> tuple[str, bool]:
    _sync_sort_dir_on_metric_change()
    c1, c2 = st.columns([4, 1])
    with c1:
        picked = st.pills(
            "表序",
            options=list(_SORT_OPTIONS),
            selection_mode="single",
            key="grid_sort_metric",
        )
    with c2:
        st.radio("方向", ["降", "升"], horizontal=True, key="grid_sort_dir")
    metric = str(picked or st.session_state.get("grid_sort_metric") or _SORT_TOTAL)
    if metric not in _SORT_OPTIONS:
        metric = _SORT_TOTAL
    descending = str(st.session_state.get("grid_sort_dir") or "降") != "升"
    if metric == _SORT_TOTAL:
        st.caption("表序按格子总分 · %s" % ("降" if descending else "升"))
    else:
        st.caption(
            "表序按 %s 综合均值 · %s（调参/盲测 × 各区间等权；缺窗跳过）"
            % (metric, "降" if descending else "升")
        )
    return metric, descending


def _default_robust_cell_id(cells: list[dict[str, Any]], rec_id: str) -> str:
    ids = [str(c.get("id") or "").strip() for c in cells if str(c.get("id") or "").strip()]
    cand = str(rec_id or "").strip()
    if cand and cand in ids:
        return cand
    return ids[0] if ids else ""


def _summary_relpath(sum_path: Path) -> str:
    try:
        return str(sum_path.resolve().relative_to(Path(__file__).resolve().parents[3])).replace(
            "\\", "/"
        )
    except ValueError:
        return str(sum_path)


def _round_score(val: Any, nd: int = 2) -> float | None:
    if val is None:
        return None
    try:
        return round(float(val), nd)
    except (TypeError, ValueError):
        return None


def _cell_score_note(
    cell: dict[str, Any],
    *,
    space_on: bool,
    cfg: Mapping[str, Any] | None,
) -> dict[str, Any]:
    book = (cell.get("samples") or {}).get("book") or {}
    sc = score_cell(book, space_on=space_on, cfg=cfg)
    sc["label"] = cell.get("label")
    return sc


def _render_results() -> None:
    summary = st.session_state.get("grid_summary")
    if not isinstance(summary, dict) or not summary.get("cells"):
        return
    space = summary.get("asset_split") or {}
    win = fill_year_windows(summary)
    cells = list(summary.get("cells") or [])
    space_on = bool(space.get("holdout_stocks") or space.get("tune_stocks"))
    if not space_on:
        space_on = any(
            bool(((c.get("samples") or {}).get("book") or {}).get("holdout_windows"))
            for c in cells
        )
    cfg = _score_cfg_for_view()
    rec = pick_recommend(cells, score=cfg)
    score_by_id: dict[str, dict[str, Any]] = {}
    for cell in cells:
        cid = cell.get("id")
        score_by_id[cid] = _cell_score_note(cell, space_on=space_on, cfg=cfg)
    rec_id = str(rec.get("id") or "").strip()
    rec_reason = str(rec.get("reason") or "")
    rec_total = _round_score(rec.get("total"))
    main_rows: list[dict[str, Any]] = []
    current_ids: set[str] = set()
    detail_rows: list[dict[str, Any]] = []
    for cell in cells:
        b = (cell.get("samples") or {}).get("book") or {}
        cid = cell.get("id")
        sc = score_by_id.get(cid) or {}
        main: dict[str, Any] = {
            "id": cid,
            "label": cell.get("label"),
            "总分": _round_score(sc.get("total")),
            "防御": _round_score(sc.get("s_def")),
            "结构": _round_score(sc.get("s_str")),
            "复原": _round_score(sc.get("s_res")),
            "泛化": None if sc.get("s_gen") is None else _round_score(sc.get("s_gen")),
            "合计": _round_pnl(b.get("sum_pnl")),
            "调参期": _round_pnl(b.get("is_pnl")),
            "验收期": _round_pnl(b.get("oos_pnl")),
        }
        if cell_is_current(cell) and cid:
            current_ids.add(str(cid))
        if "corner_oos_pnl" in b:
            main["盲测盈亏"] = _round_pnl(b.get("corner_oos_pnl"))
        main_rows.append(main)
        detail_rows.extend(_stack_detail_window_rows(cell, b, space_on=space_on))

    st.subheader("选参结论")
    sweep_label = str(summary.get("sweep") or "").strip()
    if sweep_label:
        st.caption("sweep `%s`" % sweep_label)
    name = str(st.session_state.get("grid_sweep") or summary.get("sweep") or "").strip()
    prog = _load_grid_progress(name) if name else None
    if prog and done_cell_ids(prog):
        batches = prog.get("batches") or []
        if any(isinstance(b, dict) and str(b.get("status") or "") != "done" for b in batches):
            st.caption("未跑完：推荐只基于已完成组。")
    if rec_id:
        tot_txt = "—" if rec_total is None else "%.2f 分" % rec_total
        st.success(
            "综合推荐 **%s** · %s · %s"
            % (rec.get("label") or rec_id, tot_txt, rec_reason)
        )
    else:
        st.warning(rec_reason or "无格子可评分")
    try:
        from robust_ui import ROBUST_MODE
        from ui_cache import UI_MODE_KEY

        sweep_dir = _grid_sweep_dir(summary)
        sum_path = sweep_dir / "summary.json"
        cell_ids = [
            str(c.get("id") or "").strip()
            for c in cells
            if str(c.get("id") or "").strip()
        ]
        label_by_id = {
            str(c.get("id") or "").strip(): str(c.get("label") or c.get("id") or "")
            for c in cells
            if str(c.get("id") or "").strip()
        }
        default_id = _default_robust_cell_id(cells, rec_id)
        cur = str(st.session_state.get("grid_robust_cell") or "").strip()
        if cell_ids and cur not in cell_ids:
            st.session_state["grid_robust_cell"] = default_id
        can_robust = bool(cell_ids) and sum_path.is_file()
        if can_robust:
            c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
            with c1:
                picked = st.selectbox(
                    "送入实盘评估",
                    options=cell_ids,
                    format_func=lambda i: "%s · %s" % (i, label_by_id.get(i, i)),
                    key="grid_robust_cell",
                )
            with c2:
                do_send = st.button("送入", type="primary", key="grid_to_robust")
            st.caption("锁定该格 overrides 做随机组合。默认送入综合推荐格。")
            if do_send:
                cid = str(picked or st.session_state.get("grid_robust_cell") or "").strip()
                if cid in label_by_id:
                    st.session_state["robust_param_source"] = _summary_relpath(sum_path)
                    st.session_state["robust_cell_id"] = cid
                    st.session_state[UI_MODE_KEY] = ROBUST_MODE
                    st.rerun()
        elif not sum_path.is_file():
            st.caption("无 summary.json，不能送入实盘评估。")
    except Exception:
        pass
    if space_on:
        st.caption(
            "空间隔离：主列盈亏=调参标的（展示）；空间分进入排名，盲测不再只否决。默认不改 config / 不 deploy。"
        )
    else:
        st.caption("推荐按四维综合分（无盲测时空间维权重摊到另三维）。默认不改 config / 不 deploy。")

    sort_metric, sort_desc = _render_result_sort_bar()
    if sort_metric == _SORT_TOTAL:
        main_rows = _sort_main_by_total(main_rows, descending=sort_desc)
        detail_rows = _reorder_detail_to_main(detail_rows, main_rows)
    else:
        detail_rows = _sort_detail_groups(detail_rows, sort_metric, sort_desc)
        main_rows = _reorder_main_rows(main_rows, detail_rows)
    dir_label = "降" if sort_desc else "升"

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
    order_hint = (
        "格子总分"
        if sort_metric == _SORT_TOTAL
        else "%s 综合均值" % sort_metric
    )
    st.caption(
        "调参期 %s–%s · 验收期 %s–%s%s · 单位：元"
        "（推荐看四维综合分；表序按 %s · %s）%s"
        % (
            win["tune_start"],
            win["tune_end"],
            win["check_start"],
            win["check_end"],
            " · 主列=调参标的" if space_on else "",
            order_hint,
            dir_label,
            " · 浅蓝底=现行参数" if current_ids else "",
        )
    )
    styled = df.style.apply(_style_current_ids(current_ids), axis=1)
    fmt: dict[str, str] = {}
    for col in ("合计", "调参期", "验收期", "盲测盈亏"):
        if col in df.columns:
            fmt[col] = "{:.0f}"
    for col in ("总分", "防御", "结构", "复原", "泛化"):
        if col in df.columns:
            fmt[col] = "{:.2f}"
    if fmt:
        styled = styled.format(fmt, na_rep="—")
    st.dataframe(styled, width="stretch", hide_index=True)

    with st.expander("窗内夏普 / 笔数 / 年化", expanded=False):
        _render_detail_window_table(
            detail_rows,
            (
                "调参 3 行 + 盲测 3 行；空间分按全区间夏普比，两篮数字不可加总"
                if space_on
                else "跟踪池 / 主样本"
            ),
        )
        st.caption(
            "综合分用窗内 KPI：防御=同账户回撤+盈亏盾；结构=验收期胜率×盈亏比与笔数；"
            "复原=调参/验收夏普与年化衰减；有空间隔离时泛化进排名。"
            "笔数 = 窗内平仓；胜率 / 盈亏比按笔数。"
            "几何年化 / 卡玛 / 回撤来自同一条组合权益；账户盈亏 = 窗内期末 − 期初。"
            "旧 stock×年 sweep 须重跑，不能只汇总。"
        )
    st.caption(
        "合计 / 调参 / 验收是该窗账户盈亏（单账户、最多 3 笔、复利；空间隔离时主列=调参篮子）。"
    )
    _render_grid_year_perf(summary)
