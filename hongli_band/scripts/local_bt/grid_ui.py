# coding: utf-8
"""参数网格任务页：可视化加格、开跑、看 summary。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    batch_naive_year_perf,
    list_grid_samples_with_details,
    rows_from_grid_sample_dir,
)
from equity_yearly import (
    build_daily_equity,
    daily_equity_for_year,
    year_perf_display_df,
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
from grid_spec import (
    YEAR_WINDOW_DEFAULTS,
    YEAR_WINDOW_KEYS,
    EDITOR_CELL_MAX,
    GROUP_ORDER,
    JOB_CONFIRM_THRESHOLD,
    KIND_ENUM,
    WARN_CELL_SOFT,
    GridSpecError,
    apply_axes_to_selection,
    apply_year_windows,
    axes_from_cells,
    axes_from_selection,
    build_cells,
    correct_cell_kinds,
    default_param_selection,
    fill_year_windows,
    format_current,
    format_scan_values,
    generator_locked,
    keep_from_cells,
    make_spec,
    overrides_summary,
    param_catalog,
    product_count,
    spec_json,
    sweep_name_ok,
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
    ss.setdefault("grid_sweep", "stop_loss")
    ss.setdefault("grid_compare_div", DEFAULT_DIVIDEND_TYPE)
    ss.setdefault("grid_workers", 0)
    ss.setdefault("grid_sma_ema", False)
    for key, default in YEAR_WINDOW_DEFAULTS.items():
        ss.setdefault("grid_%s" % key, int(default))
    if "grid_param_sel" not in ss:
        ss["grid_param_sel"] = _migrate_old_sel(ss)
    ss.setdefault("grid_cells", [])
    ss.setdefault("grid_summary", None)
    ss.setdefault("grid_busy", False)
    ss.setdefault("grid_overwrite_ok", False)
    ss.setdefault("grid_run_ok", False)
    ss.setdefault("grid_import_text", "")
    ss.setdefault("grid_param_group", "全部")
    ss.setdefault("grid_param_search", "")


def _axes() -> dict[str, list[Any]]:
    return axes_from_selection(st.session_state.get("grid_param_sel") or {})


def _current_spec(defaults: dict[str, Any]) -> dict[str, Any]:
    cells = list(st.session_state.get("grid_cells") or [])
    if not cells:
        cells = build_cells(_axes(), defaults)
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
    st.caption("主样本=跟踪池 BOOK_STOCKS（config 锁定均线/复权），不可勾选。")
    st.text_input("sweep 名", key="grid_sweep", disabled=busy, persist_state="session")
    if not sweep_name_ok(str(st.session_state.get("grid_sweep") or "")):
        st.error("sweep 名不能为空或含路径字符")
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


def _mark_start() -> None:
    st.session_state["grid_action"] = "run"


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
    name = str(spec.get("sweep") or "")
    if not sweep_name_ok(name):
        st.session_state["grid_flash"] = "sweep 名非法"
        return
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
        "主样本=跟踪池 BOOK_STOCKS × 回测年。选参看验收期，且须与调参期同向。"
        "默认不改 config.py / 不 deploy。"
    )
    axes = _axes()
    if "TIME_FORCE_BARS" in axes and "TIME_FORCE_MIN_RET" in axes:
        st.caption("BARS=0 再叉乘 MIN_RET 经济上重复，不自动删格。")

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
    filt = "%s|%s" % (group, search.lower())
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
                    help="多个值用逗号或空格分隔，如 6,10 或 6 10。百分数可写 6%、6 或 0.06。",
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
                if pid not in sel:
                    continue
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
        n = product_count(axes, defaults) if axes else 1
    except GridSpecError as e:
        st.error(str(e))
        n = 0
    names = " × ".join(
        "%s %s" % (p.label, p.id) for p in catalog if p.id in axes
    ) or "（未选用）"
    st.caption("未勾选不进积；勾选轴始终含现行一档。N = Π(各轴水平数) = **%s** 格 · 轴：%s" % (n, names))
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
            st.session_state["grid_overwrite_ok"] = False
            st.session_state["grid_run_ok"] = False
            st.success("已生成 %s 格" % len(cells))
        except GridSpecError as e:
            st.error(str(e))
    if not (st.session_state.get("grid_cells") or []):
        st.caption("尚未生成预览时，开跑会按当前参数表即时积格（至少含 base）。")


def _render_preview(defaults: dict[str, Any], busy: bool) -> None:
    cells = list(st.session_state.get("grid_cells") or [])
    if not cells:
        st.info("点「生成格子」预览 spec。")
        return
    n = len(cells)
    if st.session_state.get("grid_preview_n") != n:
        st.session_state.pop("grid_cells_editor", None)
    st.session_state["grid_preview_n"] = n
    st.markdown("**格子预览** · %s / 无硬上限 · 已含 base" % n)
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
    if n > EDITOR_CELL_MAX:
        st.dataframe(df.drop(columns=["删除"]), width="stretch", hide_index=True)
        st.download_button(
            "下载 spec JSON",
            data=spec_json(_current_spec(defaults)),
            file_name="%s.json" % (st.session_state.get("grid_sweep") or "grid"),
            mime="application/json",
            key="grid_dl_spec",
        )
        return
    edited = st.data_editor(
        df,
        num_rows="fixed",
        width="stretch",
        hide_index=True,
        disabled=["id", "覆盖"] if not busy else df.columns.tolist(),
        column_config={
            "删除": st.column_config.CheckboxColumn("删除", default=False),
            "kind": st.column_config.SelectboxColumn("kind", options=list(KIND_ENUM)),
        },
        key="grid_cells_editor",
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
        if cid != "base" and rec.get("删除"):
            continue
        src["label"] = str(rec.get("label") or cid)
        kind = str(rec.get("kind") or src.get("kind") or "other")
        if cid == "base":
            kind = "base"
        elif kind not in KIND_ENUM:
            kind = src.get("kind") or "other"
        src["kind"] = kind
        out.append(src)
    if not any(c["id"] == "base" for c in out) and "base" in by_id:
        out.insert(0, by_id["base"])
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
    cells = correct_cell_kinds(spec.get("cells") or [], defaults)
    st.session_state["grid_cells"] = cells
    st.session_state.pop("grid_cells_editor", None)
    st.session_state.pop("grid_param_editor", None)
    if spec.get("sweep"):
        st.session_state["grid_sweep"] = str(spec["sweep"])
    if spec.get("compare_div"):
        st.session_state["grid_compare_div"] = str(spec["compare_div"])
    win = fill_year_windows(spec)
    for key in YEAR_WINDOW_KEYS:
        st.session_state["grid_%s" % key] = int(win[key])
    axes = axes_from_cells(cells, defaults)
    st.session_state["grid_param_sel"] = apply_axes_to_selection(None, axes)
    st.success("已导入 %s 格%s" % (len(cells), "（生成器锁定）" if generator_locked(cells) else ""))
    st.rerun()


@st.dialog("覆盖已有 sweep 目录")
def _dialog_overwrite(path: Path) -> None:
    st.write("目录已存在：`%s`" % path)
    if st.button("确认覆盖", type="primary"):
        st.session_state["grid_overwrite_ok"] = True
        st.session_state["grid_action"] = "run"
        st.rerun()


@st.dialog("确认开跑")
def _dialog_confirm_run(n_cells: int, n_jobs: int, total: int) -> None:
    st.write("格子 **%s** · 每格 job **%s** · 总任务约 **%s**" % (n_cells, n_jobs, total))
    st.caption("格间串行，可能很久。默认不改 config。")
    if st.button("确认开跑", type="primary"):
        st.session_state["grid_run_ok"] = True
        st.session_state["grid_action"] = "run"
        st.rerun()


def _handle_actions(defaults: dict[str, Any]) -> None:
    action = st.session_state.pop("grid_action", None)
    if not action:
        return
    spec = _current_spec(defaults)
    if action == "summarize":
        dest = _sweep_dir(spec)
        try:
            out = summarize_only(dest)
            st.session_state["grid_summary"] = out
            st.success("已汇总")
        except Exception as e:
            st.error(str(e))
        return
    try:
        validate_spec(spec)
    except GridError as e:
        st.error(str(e))
        return
    if action != "run":
        return
    dest = _sweep_dir(spec)
    if dest.exists() and any(dest.iterdir()) and not st.session_state.get("grid_overwrite_ok"):
        _dialog_overwrite(dest)
        return
    try:
        _book, jobs = assemble_jobs(
            spec,
            include_sma_ema=bool(st.session_state.get("grid_sma_ema")),
        )
        n_jobs = len(jobs)
    except GridError as e:
        st.error(str(e))
        return
    n_cells = len(spec["cells"])
    total = n_cells * n_jobs
    need_confirm = n_cells > WARN_CELL_SOFT or total > JOB_CONFIRM_THRESHOLD
    if need_confirm and not st.session_state.get("grid_run_ok"):
        _dialog_confirm_run(n_cells, n_jobs, total)
        return
    _run_now(spec, n_jobs, total)


def _run_now(spec: dict[str, Any], n_jobs: int, total: int) -> None:
    st.session_state["grid_busy"] = True
    bar = st.progress(0.0)
    status = st.empty()
    n_cells = max(len(spec.get("cells") or []), 1)
    cell_ids = [str(c.get("id") or "") for c in spec.get("cells") or []]

    def on_progress(cid: str, done: int, tot: int, label: str) -> None:
        try:
            idx = cell_ids.index(str(cid))
        except ValueError:
            idx = 0
        frac = (float(idx) + (float(done) / float(tot or 1))) / float(n_cells)
        bar.progress(min(1.0, frac))
        status.info("格子 **%s** · %s/%s %s" % (cid, done, tot, label))

    try:
        info = run_sweep(
            spec,
            include_sma_ema=bool(st.session_state.get("grid_sma_ema")),
            workers=int(st.session_state.get("grid_workers") or 0),
            progress=on_progress,
        )
        st.session_state["grid_summary"] = info.get("summary")
        rec = (info.get("recommend") or {}) if isinstance(info.get("recommend"), dict) else {}
        status.success("完成 · 推荐 %s" % (rec.get("id") or ""))
        bar.progress(1.0)
    except GridError as e:
        st.error(str(e))
    except Exception as e:
        st.error("%s: %s" % (type(e).__name__, e))
    finally:
        st.session_state["grid_busy"] = False
        st.session_state["grid_overwrite_ok"] = False
        st.session_state["grid_run_ok"] = False
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
    st.subheader("分年绩效（单票合计）")
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
    job_rows = rows_from_grid_sample_dir(cell_dir, sample, fallback_budget=fallback)
    if not job_rows:
        st.info("该格无操作明细")
        return
    cache = st.session_state.setdefault("_batch_detail_trade_cache", {})
    result = batch_naive_year_perf(
        job_rows,
        split="year",
        cache=cache,
        allow_mixed_ma=True,
    )
    if not result.get("ok"):
        reason = str(result.get("reason") or "")
        st.info(reason if reason else "该格无操作明细")
        return

    n_ok = int(result.get("n_ok") or 0)
    n_buy = int(result.get("n_buy") or 0)
    sum_pnl = float(result.get("sum_pnl") or 0)
    pos_ratio = result.get("pos_ratio")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("成功任务数", n_ok)
    m2.metric("轮次合计", n_buy)
    m3.metric("总盈亏", "%.2f" % sum_pnl)
    if pos_ratio is None:
        m4.metric("盈利任务占比", "—")
    else:
        m4.metric("盈利任务占比", "%.1f%%" % (float(pos_ratio) * 100.0))

    st.caption(
        "各票独立账户的已实现盈亏按卖出年相加（数据分析里的「单票合计盈亏」），"
        "不是共享钱包的组合净值。年化 / 回撤分母 = 成功任务数 × 单票预算"
        "（按年分段用该年成功任务数）。本表多了年化、回撤、夏普。"
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
    trades_y = list((result.get("trades_by_year") or {}).get(year) or [])
    bud_y = float((result.get("budget_by_year") or {}).get(year) or result.get("budget") or 0)
    daily = build_daily_equity(trades_y, bud_y)
    eq_y = daily_equity_for_year(daily, year, start_equity=start_eq)
    st.plotly_chart(
        _plot_grid_year_equity(
            eq_y, bud_y, "%s 年权益曲线（单票合计 · 预算 + 已实现盈亏累计）" % year
        ),
        use_container_width=True,
    )


def _window_metric(book: dict[str, Any], key: str, field: str) -> Any:
    w = (book.get("windows") or {}).get(key) or {}
    return w.get(field)


def _render_results() -> None:
    summary = st.session_state.get("grid_summary")
    if not isinstance(summary, dict) or not summary.get("cells"):
        return
    rec = summary.get("recommend") or {}
    st.subheader("选参结论")
    st.success("%s · %s" % (rec.get("label") or rec.get("id") or "—", rec.get("reason") or ""))
    st.caption("禁止用 MAE 反事实当结论。默认不改 config / 不 deploy。选参宇宙是跟踪池，过拟合风险高于大样本。")
    win = fill_year_windows(summary)
    tune_h = "调参期（%s–%s）" % (win["tune_start"], win["tune_end"])
    check_h = "验收期（%s–%s）" % (win["check_start"], win["check_end"])
    rows = []
    for cell in summary.get("cells") or []:
        b = (cell.get("samples") or {}).get("book") or {}
        db = (cell.get("delta_vs_base") or {}).get("book") or {}
        notes = rec.get("candidates") or []
        fail = next((n.get("fail") for n in notes if n.get("id") == cell.get("id")), None)
        row = {
            "id": cell.get("id"),
            "label": cell.get("label"),
            "kind": cell.get("kind"),
            "合计": b.get("sum_pnl"),
            tune_h: b.get("is_pnl"),
            check_h: b.get("oos_pnl"),
            "验收期相对现行": db.get("oos_pnl"),
        }
        for prefix, wkey in (
            ("全区间", "all"),
            ("调参期", "tune"),
            ("验收期", "check"),
        ):
            row["%s夏普" % prefix] = _window_metric(b, wkey, "sharpe")
            row["%s开仓" % prefix] = _window_metric(b, wkey, "n_open")
            row["%s平均年化%%" % prefix] = _window_metric(b, wkey, "avg_ann_pct")
            row["%s平均盈亏" % prefix] = _window_metric(b, wkey, "avg_year_pnl")
        row["过门"] = "否" if fail else "是"
        rows.append(row)
    df = pd.DataFrame(rows)
    num_cfg = {}
    for prefix in ("全区间", "调参期", "验收期"):
        num_cfg["%s夏普" % prefix] = st.column_config.NumberColumn("%s夏普" % prefix, format="%.4f")
        num_cfg["%s开仓" % prefix] = st.column_config.NumberColumn("%s开仓" % prefix, format="%d")
        num_cfg["%s平均年化%%" % prefix] = st.column_config.NumberColumn(
            "%s平均年化%%" % prefix, format="%.2f"
        )
        num_cfg["%s平均盈亏" % prefix] = st.column_config.NumberColumn(
            "%s平均盈亏" % prefix, format="%.2f"
        )
    for col in ("合计", tune_h, check_h, "验收期相对现行"):
        num_cfg[col] = st.column_config.NumberColumn(col, format="%.2f")
    st.dataframe(df, width="stretch", hide_index=True, column_config=num_cfg)
    st.caption(
        "合计 / 调参期 / 验收期是卖出年已实现盈亏之和。"
        "夏普 / 开仓 / 平均年化% / 平均盈亏与下方分年绩效同口径（每年独立空仓）；"
        "平均盈亏是窗内各年当年盈亏的算术平均，不等于合计除以年数。"
        "窗内夏普是各年日收益拼接后算一次，不是各年夏普平均。"
    )
    _render_grid_year_perf(summary)
