# coding: utf-8
"""HlBand 本地回测可视化（Streamlit）。

启动:
  streamlit run hongli_band/scripts/local_bt/app.py
  或: python hongli_band/local_bt_ui.py
"""
from __future__ import annotations

import sys
import traceback
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from analyze import (  # noqa: E402
    DEFAULT_CSV_ROOT,
    DEFAULT_DIVIDEND_TYPE,
    DEFAULT_REPORT_ROOT,
    DIVIDEND_LABELS,
    DIVIDEND_TYPES,
    analyze_detail,
    batch_summary_dataframe,
    batch_year_summary_dataframe,
    chart_ma_periods,
    daily_csvs_by_stock,
    date_to_ymd,
    daily_csv_for_stock,
    dividend_from_detail_path,
    div_compare_dataframe,
    dividend_label,
    enrich_detail_raw_hold_metrics,
    enrich_trades_hold_metrics,
    filter_trades_by_range,
    list_daily_csvs,
    list_detail_csvs,
    load_chart_ma_config,
    load_detail_raw,
    ma_compare_dataframe,
    ma_compare_year_dataframe,
    map_day_to_bar,
    match_daily_csv_for_detail,
    normalize_dividend_type,
    normalize_ma_type,
    ohlc_frame_for_chart,
    pair_ma_batch_rows,
    parse_budget_from_log,
    parse_stock_filter_tokens,
    peek_daily_csv_meta,
    resolve_chart_ma_kind,
    resolve_typed_dir,
    stock_from_detail_path,
    stock_matches_filter,
    summarize_batch_row,
    trades_to_dataframe,
    unique_dividend_types,
    union_date_range,
    ymd_to_date,
)
from display_df import (  # noqa: E402
    ANALYSIS_PERIOD_COLUMNS,
    ANALYSIS_YEAR_COLUMNS,
    insert_name_column,
    rename_columns,
    stock_axis_label,
    stock_display_name,
)
from run import (  # noqa: E402
    _run_payloads,
    build_batch_payloads,
    run_backtest,
    write_typed_summaries,
)
from select_config import (  # noqa: E402
    ANALYSIS_SIDEBAR,
    ANALYSIS_WIDGETS,
    DEFAULT_FILTERS,
    FILTER_WIDGETS,
    SELECT_SIDEBAR,
    WEIGHTS,
    WEIGHT_WIDGETS,
    book_stocks_to_editor_rows,
    cast_filter_value,
    editor_rows_to_book_stocks,
    load_book_defaults,
    load_book_stocks_full,
    widget_kwargs,
    year_max_for_window,
)
from select_analysis import (  # noqa: E402
    data_and_eval_years,
    run_fixed_book,
    run_walk_forward,
    write_analysis_csv,
    write_fixed_book_csv,
)
from book_backtest import analyze_book_detail  # noqa: E402
from stock_select import (  # noqa: E402
    SCORE_YEARS,
    coverage_notes,
    csv_dir_fingerprint,
    format_book_snippet,
    glob_fingerprint,
    infer_score_years,
    report_fingerprint,
    scan_reports,
    score_universe,
    write_select_csv,
)
from trades_csv import trades_csv_path  # noqa: E402

import streamlit as st  # noqa: E402


st.set_page_config(page_title="HlBand 本地回测", layout="wide")
st.title("HlBand Backtesting")

DIVIDEND_COLORS = {
    "none": "#616161",
    "front": "#1565c0",
    "back": "#6a1b9a",
    "front_ratio": "#e65100",
    "back_ratio": "#2e7d32",
}


# 与 peek 行为绑定：头窗 0 行时从头扫到第一根有效 K，改 peek 后必须换键
_DAILY_METAS_VER = 4


def _daily_dir_fingerprint(csv_dir: str) -> tuple:
    return glob_fingerprint(Path(csv_dir), "*_1d_*.csv") + (_DAILY_METAS_VER,)


@st.cache_data(show_spinner="扫描行情目录…")
def _cached_daily_metas(csv_dir: str, fingerprint: tuple) -> list[dict]:
    # fingerprint 仅作缓存键：目录内文件名/mtime/size 变化即失效
    _ = fingerprint
    return daily_csvs_by_stock(csv_dir)


@st.cache_data(show_spinner="扫描回测报告与日线股性…")
def _cached_select_scan(report_dir: str, csv_dir: str, fp_report: tuple, fp_csv: tuple) -> dict:
    _ = fp_report, fp_csv
    return scan_reports(report_dir, csv_dir)


def _fmt_ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _daily_csv_label(path: Path) -> str:
    div = normalize_dividend_type(path.parent.name)
    lab = DIVIDEND_LABELS.get(div, path.parent.name) if div else path.parent.name
    return "%s · %s" % (path.name, lab)


def _plot_equity(eq: pd.DataFrame, budget: float, title: str, *, name: str = "权益", color: str = "#1565c0") -> go.Figure:
    fig = go.Figure()
    pts = eq.dropna(subset=["date"]) if eq is not None and "date" in eq.columns else eq
    if pts is None or pts.empty:
        fig.add_annotation(text="无已平仓成交", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
    else:
        fig.add_trace(
            go.Scatter(
                x=pts["date"],
                y=pts["equity"],
                mode="lines+markers",
                name=name,
                line=dict(color=color, width=2),
                marker=dict(size=6),
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
    )
    return fig


def _plot_equity_overlay(
    series: list[tuple[Any, str, str]],
    budget: float,
    title: str,
) -> go.Figure:
    fig = go.Figure()
    for eq, name, color in series:
        if eq is None or getattr(eq, "empty", True) or "date" not in getattr(eq, "columns", []):
            continue
        pts = eq.dropna(subset=["date"])
        if pts.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=pts["date"],
                y=pts["equity"],
                mode="lines+markers",
                name=name,
                line=dict(color=color, width=2),
                marker=dict(size=6),
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
    )
    return fig


def _plot_ma_delta_bar(pairs: list[dict], *, max_n: int = 40) -> go.Figure:
    fig = go.Figure()
    rows = [r for r in pairs if r.get("pnl_delta") is not None]
    rows = sorted(rows, key=lambda r: abs(float(r.get("pnl_delta") or 0)), reverse=True)[:max_n]
    if not rows:
        fig.add_annotation(text="无对照盈亏", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(height=240, margin=dict(l=40, r=20, t=50, b=40))
        return fig
    labels = []
    for r in rows:
        year = str(r.get("year") or "").strip()
        stock = str(r.get("stock") or "")
        labels.append("%s · %s" % (stock, year) if year else stock)
    deltas = [float(r.get("pnl_delta") or 0) for r in rows]
    colors = ["#e65100" if d >= 0 else "#1565c0" for d in deltas]
    fig.add_trace(
        go.Bar(
            x=deltas,
            y=labels,
            orientation="h",
            marker_color=colors,
            hovertemplate="%{y}<br>EMA−SMA %{x:,.0f} 元<extra></extra>",
        )
    )
    fig.update_layout(
        title="Δ盈亏（EMA − SMA；|Δ| 最大 %s 条）" % len(rows),
        xaxis_title="Δ盈亏 (元)",
        height=max(280, 18 * len(rows) + 80),
        margin=dict(l=120, r=20, t=50, b=40),
        yaxis=dict(autorange="reversed"),
    )
    return fig


def _plot_pnl_hist(trades: list[dict]) -> go.Figure:
    pnls = [float(t["pnl"]) for t in trades]
    fig = go.Figure()
    if pnls:
        fig.add_trace(go.Histogram(x=pnls, nbinsx=min(20, max(5, len(pnls))), name="盈亏", marker_color="#1565c0"))
    fig.update_layout(
        title="单笔已实现盈亏分布",
        xaxis_title="盈亏 (元)",
        yaxis_title="笔数",
        height=320,
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


def _ohlc_x_pos(ohlc: pd.DataFrame, ts: pd.Timestamp) -> int:
    loc = ohlc.index.get_loc(ts)
    return int(loc) if not isinstance(loc, slice) else int(loc.start)


def _kline_tick_vals(n: int, max_ticks: int = 12) -> list[int]:
    if n <= 0:
        return []
    if n == 1:
        return [0]
    n_ticks = min(max_ticks, n)
    vals = [int(round(i * (n - 1) / (n_ticks - 1))) for i in range(n_ticks)]
    return sorted(set(vals))


def _plot_kline(
    ohlc: pd.DataFrame,
    trades: list[dict],
    title: str,
    *,
    period: str = "1d",
    ma_life: int = 34,
) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.72, 0.28],
    )
    if ohlc.empty:
        fig.add_annotation(text="无 OHLC", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        return fig

    weekly = str(period or "1d").strip().lower() in ("1w", "week", "weekly", "w")
    candle_name = "周线" if weekly else "日线"

    # 按交易日等间距排布，周末/节假日不占轴（日历空隙不画）
    ohlc = ohlc.copy()
    ohlc.index = pd.DatetimeIndex(pd.to_datetime(ohlc.index).normalize())
    ohlc = ohlc[~ohlc.index.duplicated(keep="last")].sort_index()
    x_pos = list(range(len(ohlc)))
    x_dates = ohlc.index.strftime("%Y-%m-%d").tolist()

    fig.add_trace(
        go.Candlestick(
            x=x_pos,
            open=ohlc["Open"],
            high=ohlc["High"],
            low=ohlc["Low"],
            close=ohlc["Close"],
            name=candle_name,
            increasing_line_color="#e53935",
            decreasing_line_color="#43a047",
            customdata=x_dates,
            hovertemplate=(
                "%{customdata}<br>"
                "开 %{open}<br>高 %{high}<br>低 %{low}<br>收 %{close}"
                "<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )
    ma_colors = {
        "MA20": "#1565c0",
        "MA60": "#ef6c00",
        "MA5": "#6a1b9a",
        "MA13": "#00838f",
        "MA34": "#c62828",
    }
    ma_cols = [
        c
        for c in ohlc.columns
        if str(c).startswith("MA") and str(c)[2:].isdigit()
    ]
    for col in ma_cols:
        n = int(str(col)[2:])
        width = 2.4 if weekly and n == int(ma_life) else 1.5
        fig.add_trace(
            go.Scatter(
                x=x_pos,
                y=ohlc[col],
                name=col,
                mode="lines",
                line=dict(width=width, color=ma_colors.get(col, "#546e7a")),
                connectgaps=False,
                customdata=x_dates,
                hovertemplate="%{customdata}<br>" + col + " %{y:.4g}<extra></extra>",
            ),
            row=1,
            col=1,
        )
    if "Volume" in ohlc.columns:
        fig.add_trace(
            go.Bar(
                x=x_pos,
                y=ohlc["Volume"],
                name="成交量",
                marker_color="#90a4ae",
                customdata=x_dates,
                hovertemplate="%{customdata}<br>量 %{y}<extra></extra>",
            ),
            row=2,
            col=1,
        )

    # B 在 Low 下方、S 在 High 上方；虚线连到影线端点
    y_span = float(ohlc["High"].max() - ohlc["Low"].min()) or 1.0
    pad = y_span * 0.025
    color_b = "#b71c1c"
    color_s = "#1b5e20"

    buy_x, buy_y, buy_hover = [], [], []
    sell_x, sell_y, sell_hover = [], [], []

    for t in trades:
        bd = map_day_to_bar(ohlc, t.get("buy_open_day"), period)
        sd = map_day_to_bar(ohlc, t.get("sell_exec_day") or t.get("sell_signal_day"), period)
        ti = t.get("i", "")
        if bd is not None:
            xi = _ohlc_x_pos(ohlc, bd)
            low = float(ohlc.loc[bd, "Low"])
            px = float(t.get("buy_price") or low)
            label_y = low - pad
            fig.add_shape(
                type="line",
                x0=xi,
                x1=xi,
                y0=low,
                y1=label_y,
                line=dict(color=color_b, width=1, dash="dash"),
                row=1,
                col=1,
            )
            buy_x.append(xi)
            buy_y.append(label_y)
            buy_hover.append(f"买 #{ti} @ {px:.4g}<br>{bd.strftime('%Y-%m-%d')}")
        if sd is not None:
            xi = _ohlc_x_pos(ohlc, sd)
            high = float(ohlc.loc[sd, "High"])
            px = float(t.get("sell_price") or high)
            label_y = high + pad
            fig.add_shape(
                type="line",
                x0=xi,
                x1=xi,
                y0=high,
                y1=label_y,
                line=dict(color=color_s, width=1, dash="dash"),
                row=1,
                col=1,
            )
            sell_x.append(xi)
            sell_y.append(label_y)
            sell_hover.append(f"卖 #{ti} @ {px:.4g}<br>{sd.strftime('%Y-%m-%d')}")

    if buy_x:
        fig.add_trace(
            go.Scatter(
                x=buy_x,
                y=buy_y,
                mode="text",
                name="B 买入",
                text=["B"] * len(buy_x),
                textfont=dict(color=color_b, size=13, family="Arial Black"),
                hovertext=buy_hover,
                hovertemplate="%{hovertext}<extra></extra>",
            ),
            row=1,
            col=1,
        )
    if sell_x:
        fig.add_trace(
            go.Scatter(
                x=sell_x,
                y=sell_y,
                mode="text",
                name="S 卖出",
                text=["S"] * len(sell_x),
                textfont=dict(color=color_s, size=13, family="Arial Black"),
                hovertext=sell_hover,
                hovertemplate="%{hovertext}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    fig.update_layout(
        title=title,
        height=560,
        # 默认拖拽平移；滚轮缩放需配合 plotly config scrollZoom
        dragmode="pan",
        xaxis_rangeslider_visible=False,
        margin=dict(l=40, r=20, t=50, b=40),
        legend=dict(orientation="h"),
    )
    # 允许 x 轴缩放/平移；y 轴留出 B/S 边距
    y_lo = float(ohlc["Low"].min()) - pad * 2.2
    y_hi = float(ohlc["High"].max()) + pad * 2.2
    tickvals = _kline_tick_vals(len(ohlc))
    fig.update_xaxes(
        type="linear",
        fixedrange=False,
        rangeslider_visible=False,
        tickmode="array",
        tickvals=tickvals,
        ticktext=[x_dates[i] for i in tickvals],
    )
    fig.update_yaxes(title_text="价格", fixedrange=False, range=[y_lo, y_hi], row=1, col=1)
    fig.update_yaxes(title_text="量", fixedrange=False, row=2, col=1)
    fig.update_xaxes(title_text="日期", showticklabels=True, row=2, col=1)
    fig.update_xaxes(showticklabels=False, row=1, col=1)
    return fig


_KLINE_PLOT_CONFIG = {
    "scrollZoom": True,
    "displayModeBar": True,
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    "doubleClick": "reset",
}


def _ensure_hold_metrics(
    trades: list[dict[str, Any]],
    detail_path: Path,
    *,
    csv_root: str | None = None,
    dividend_type: str = "",
    stock: str = "",
) -> list[dict[str, Any]]:
    """成交轮次缺持有回撤/浮盈时补算。"""
    if not trades:
        return trades
    if all(
        t.get("hold_max_dd") is not None and t.get("hold_max_up") is not None for t in trades
    ):
        return trades
    return enrich_trades_hold_metrics(
        trades,
        csv_root=csv_root if csv_root is not None else DEFAULT_CSV_ROOT,
        dividend_type=dividend_type,
        detail_path=detail_path,
        default_stock=stock,
    )


def _show_trades_rounds(
    trades: list[dict[str, Any]],
    detail_path: Path,
    *,
    csv_root: str | None = None,
    dividend_type: str = "",
    stock: str = "",
    key_suffix: str = "",
) -> None:
    """成交轮次表：含持有回撤%/浮盈%，并提供导出。"""
    trades = _ensure_hold_metrics(
        trades,
        detail_path,
        csv_root=csv_root,
        dividend_type=dividend_type,
        stock=stock,
    )
    df = trades_to_dataframe(trades)
    st.subheader("成交轮次")
    st.caption(
        "持有回撤% = 区间收盘峰值回撤（≤0）；"
        "持有浮盈% = 区间最高价相对买价最大浮盈（≥0）。"
    )
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "持有回撤%": st.column_config.NumberColumn(
                "持有回撤%",
                help="持仓区间收盘价从峰值到谷底的最大回撤（百分比，≤0）",
                format="%.2f",
            ),
            "持有浮盈%": st.column_config.NumberColumn(
                "持有浮盈%",
                help="持仓区间最高价相对买价的最大浮盈 MFE（百分比，≥0）",
                format="%.2f",
            ),
        },
    )
    if not df.empty:
        dl_key = "dl_trades_%s_%s" % (detail_path.name, key_suffix or "main")
        st.download_button(
            "导出成交轮次 CSV",
            data=df.to_csv(index=False).encode("utf-8-sig"),
            file_name="%s_成交轮次.csv" % detail_path.stem.replace("_操作明细", ""),
            mime="text/csv",
            key=dl_key,
        )


def _show_detail_raw(
    detail_path: Path,
    trades: list[dict[str, Any]],
    *,
    csv_root: str | None = None,
    dividend_type: str = "",
    stock: str = "",
) -> None:
    """操作明细（原始）：卖出行附带持有回撤%/浮盈%。"""
    st.subheader("操作明细（原始）")
    try:
        trades = _ensure_hold_metrics(
            trades,
            detail_path,
            csv_root=csv_root,
            dividend_type=dividend_type,
            stock=stock,
        )
        raw = enrich_detail_raw_hold_metrics(load_detail_raw(detail_path), trades)
        st.dataframe(raw, use_container_width=True, hide_index=True)
    except Exception as e:
        st.warning("无法读取原始明细：%s" % e)


def _render_analysis(
    detail_path: Path,
    budget: float,
    ohlc_csv: Path | None,
    range_start: str,
    range_end: str,
    stock: str,
    *,
    show_metrics: bool = True,
    show_equity: bool = True,
    title_prefix: str = "",
    csv_root: str | None = None,
    dividend_type: str = "",
) -> dict:
    result = analyze_detail(
        detail_path,
        budget=budget,
        meta={
            "tag": "HlBand",
            "ver": "local",
            "stock": stock or "?",
            "period": "1d",
            "budget": float(budget),
        },
        csv_root=csv_root if csv_root is not None else DEFAULT_CSV_ROOT,
        dividend_type=dividend_type,
    )
    trades = result["trades"]
    if range_start or range_end:
        # 仅分析模式可按卖出日再筛
        filtered = filter_trades_by_range(trades, range_start, range_end)
        if filtered != trades and (range_start or range_end):
            # 重算 equity/stats
            from analyze import report_mod

            mod = report_mod()
            trades = filtered
            result["trades"] = trades
            result["stats"] = mod.compute_stats(
                {"tag": "HlBand", "ver": "local", "stock": stock or "?", "period": "1d", "budget": budget},
                trades,
                diag={},
                price_info={"source": "terminal", "terminal_csv": str(detail_path)},
            )
            result["equity"] = mod.equity_curve(trades, budget)
            trades = _ensure_hold_metrics(
                trades,
                detail_path,
                csv_root=csv_root,
                dividend_type=dividend_type,
                stock=stock,
            )
            result["trades"] = trades

    stats = result["stats"]
    if show_metrics:
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("轮次", int(stats.get("n_buy") or 0))
        c2.metric("总盈亏", f"{float(stats.get('sum_pnl') or 0):,.2f}")
        c3.metric("胜率", f"{float(stats.get('win_rate') or 0):.1f}%")
        c4.metric("平均收益%", f"{float(stats.get('avg_ret') or 0):.2f}")
        c5.metric("最大单笔%", f"{float(stats.get('max_win') or 0):.2f}")
        c6.metric("最大亏损%", f"{float(stats.get('max_loss') or 0):.2f}")

        st.caption(f"明细真源：`{detail_path}` · 预算 {budget:,.0f} 元")

    if show_equity:
        st.plotly_chart(
            _plot_equity(result["equity"], budget, (title_prefix + "权益曲线（预算 + 已实现盈亏累计）").strip()),
            use_container_width=True,
        )

        left, right = st.columns(2)
        with left:
            st.plotly_chart(_plot_pnl_hist(trades), use_container_width=True)
        with right:
            win_n = int(stats.get("win_n") or 0)
            loss_n = int(stats.get("loss_n") or 0)
            fig = go.Figure(
                data=[
                    go.Bar(
                        x=["盈利", "亏损"],
                        y=[win_n, loss_n],
                        marker_color=["#43a047", "#e53935"],
                        name="笔数",
                    )
                ]
            )
            fig.update_layout(
                title="盈亏笔数",
                yaxis_title="笔数",
                height=320,
                margin=dict(l=40, r=20, t=50, b=40),
            )
            st.plotly_chart(fig, use_container_width=True)

    if ohlc_csv and ohlc_csv.is_file():
        period_label = st.radio(
            "K线周期",
            ["日线", "周线"],
            horizontal=True,
            key="kline_period_%s_%s" % (detail_path.name, str(title_prefix).replace(" ", "_")),
        )
        period = "1w" if period_label == "周线" else "1d"
        ma_kind = resolve_chart_ma_kind(stock=stock, detail_path=detail_path)
        ohlc = ohlc_frame_for_chart(
            ohlc_csv,
            start=range_start,
            end=range_end,
            stock=stock,
            period=period,
            ma_kind=ma_kind,
            detail_path=detail_path,
        )
        periods = chart_ma_periods(period)
        ma_label = "MA" + "/".join(str(n) for n in periods)
        st.caption("K 线：滚轮缩放 · 拖拽左右平移 · 双击复位")
        ktitle = "%s %s · %s + 买卖点 · %s" % (
            period_label,
            ma_kind,
            ma_label,
            stock or ohlc_csv.name,
        )
        if title_prefix:
            ktitle = "%s%s" % (title_prefix, ktitle)
        cfg = load_chart_ma_config()
        ma_life = int((cfg or {}).get("w_life") or 34)
        st.plotly_chart(
            _plot_kline(ohlc, trades, ktitle, period=period, ma_life=ma_life),
            use_container_width=True,
            config=_KLINE_PLOT_CONFIG,
        )
    else:
        st.info("未绑定行情 CSV，跳过 K 线（仅分析明细时可选对应日线）。")

    _show_trades_rounds(
        trades,
        detail_path,
        csv_root=csv_root,
        dividend_type=dividend_type,
        stock=stock,
        key_suffix=str(title_prefix or "an").replace(" ", "_"),
    )

    _show_detail_raw(
        detail_path,
        trades,
        csv_root=csv_root,
        dividend_type=dividend_type,
        stock=stock,
    )
    return result


def _glob_hold_detail(out_dir: Path, year: str, period_i: int) -> Path | None:
    matches = sorted(out_dir.glob("local_bt_book_hold_%s_p%s_*_操作明细.csv" % (year, period_i)))
    return matches[0] if matches else None


def _glob_score_detail(out_dir: Path, year: str) -> Path | None:
    matches = sorted(out_dir.glob("local_bt_book_score_%s_u*_操作明细.csv" % (year)))
    return matches[0] if matches else None


def _resolve_hold_detail(row: dict[str, Any], out_dir: Path) -> Path | None:
    raw = str(row.get("hold_detail_path") or "").strip()
    if raw:
        p = Path(raw)
        if p.is_file():
            return p
    year = str(row.get("year") or "").strip()
    period_i = row.get("period_i")
    if year and period_i is not None:
        return _glob_hold_detail(out_dir, year, int(period_i))
    return None


def _render_book_detail_panel(
    detail_path: Path,
    budget: float,
    *,
    caption: str = "",
    csv_root: str | None = None,
    dividend_type: str = "",
) -> None:
    if not detail_path.is_file():
        st.warning("明细不存在：`%s`" % detail_path)
        return
    combo = analyze_book_detail(
        detail_path,
        budget=budget,
        csv_root=csv_root if csv_root is not None else DEFAULT_CSV_ROOT,
        dividend_type=dividend_type,
    )
    stats = combo.get("stats") or {}
    trades = combo.get("trades") or []
    st.caption(
        (caption + " · " if caption else "")
        + "明细 `%s` · 预算 %s 元"
        % (detail_path.name, f"{budget:,.0f}")
    )
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("轮次", int(stats.get("n_buy") or 0))
    c2.metric("总盈亏", f"{float(stats.get('sum_pnl') or 0):,.2f}")
    c3.metric("胜率", f"{float(stats.get('win_rate') or 0):.1f}%")
    c4.metric("平均收益%", f"{float(stats.get('avg_ret') or 0):.2f}")
    c5.metric("最大单笔%", f"{float(stats.get('max_win') or 0):.2f}")
    c6.metric("最大亏损%", f"{float(stats.get('max_loss') or 0):.2f}")
    st.plotly_chart(
        _plot_equity(combo.get("equity"), budget, "组合权益曲线（预算 + 已实现盈亏累计）"),
        use_container_width=True,
    )
    per = combo.get("per_stock") or {}
    if per:
        with st.expander("按票归因 KPI", expanded=False):
            rows = []
            for stock in sorted(per.keys()):
                k = per[stock] or {}
                rows.append(
                    {
                        "代码": stock,
                        "轮次": k.get("n_buy"),
                        "盈亏": k.get("sum_pnl"),
                        "胜率%": k.get("win_rate"),
                        "平均收益%": k.get("avg_ret"),
                    }
                )
            st.dataframe(
                insert_name_column(pd.DataFrame(rows), code_col="代码"),
                use_container_width=True,
                hide_index=True,
            )
    _show_trades_rounds(
        trades,
        detail_path,
        csv_root=csv_root,
        dividend_type=dividend_type,
        key_suffix="book",
    )
    _show_detail_raw(
        detail_path,
        trades,
        csv_root=csv_root,
        dividend_type=dividend_type,
    )


def _render_analysis_trade_records(result: dict[str, Any], params: dict[str, Any]) -> None:
    year_rows = list(result.get("year_rows") or [])
    if not year_rows:
        return
    book = dict(params.get("book_params") or load_book_defaults())
    budget = float(book.get("trade_budget") or book.get("TRADE_BUDGET") or 100000.0)
    out_dir = Path(str(result.get("report_dir") or resolve_typed_dir(DEFAULT_REPORT_ROOT, DEFAULT_DIVIDEND_TYPE)))
    score_paths = dict(result.get("score_detail_paths") or {})
    hold_opts: list[dict[str, Any]] = []
    for row in year_rows:
        if row.get("status") != "ok":
            continue
        path = _resolve_hold_detail(row, out_dir)
        if path is None:
            continue
        hold_opts.append({**row, "_detail_path": path})
    score_years = set(str(y) for y in score_paths.keys())
    for p in out_dir.glob("local_bt_book_score_*_操作明细.csv"):
        parts = p.stem.split("_")
        if len(parts) >= 5 and str(parts[4]).isdigit():
            score_years.add(str(parts[4]))
    score_years_sorted = sorted(score_years)
    if not hold_opts and not score_years_sorted:
        return
    st.subheader("回放操作记录")
    kinds = []
    if hold_opts:
        kinds.append("持有期回放")
    if score_years_sorted:
        kinds.append("打分预计算")
    if not kinds:
        st.info("暂无可用操作明细。")
        return
    kind = st.radio("回放类型", kinds, horizontal=True, key="analysis_trade_kind")
    if kind == "持有期回放":
        labels = []
        for row in hold_opts:
            hy = str(row.get("year") or "")
            picks = str(row.get("picks") or "")
            pnl = row.get("portfolio_pnl")
            pnl_s = "-" if pnl is None else "%.0f" % float(pnl)
            labels.append("%s · 盈亏 %s · %s" % (hy, pnl_s, picks or "（空）"))
        idx = st.selectbox("评估年", range(len(hold_opts)), format_func=lambda i: labels[i], key="analysis_hold_year")
        row = hold_opts[int(idx)]
        cap = "持有 %s · 段 %s · 选股年 %s" % (
            row.get("year"),
            row.get("period_i"),
            row.get("select_year"),
        )
        if row.get("wallet_start") is not None and row.get("wallet_end") is not None:
            cap += " · 权益 %.0f→%.0f" % (
                float(row.get("wallet_start") or 0),
                float(row.get("wallet_end") or 0),
            )
        _render_book_detail_panel(Path(row["_detail_path"]), budget, caption=cap)
    else:
        if not score_years_sorted:
            st.info("无打分预计算明细。")
            return
        sy = st.selectbox("打分自然年", score_years_sorted, key="analysis_score_year")
        sp = score_paths.get(str(sy))
        detail = Path(sp) if sp else _glob_score_detail(out_dir, str(sy))
        if detail is None or not detail.is_file():
            st.warning("未找到 %s 年打分预计算明细。" % sy)
            return
        _render_book_detail_panel(detail, budget, caption="打分预计算 %s（全打分池）" % sy)


def _render_ma_compare_panel(
    sma_pack: dict,
    ema_pack: dict,
    ohlc_csv: Path | None,
    range_start: str,
    range_end: str,
    stock: str,
) -> None:
    from analyze import pick_ma_winner

    sma_path = Path(sma_pack["detail"])
    ema_path = Path(ema_pack["detail"])
    budget = float(sma_pack.get("budget") or ema_pack.get("budget") or 50000.0)
    a_sma = analyze_detail(sma_path, budget=budget)
    a_ema = analyze_detail(ema_path, budget=budget)
    ss, es = a_sma["stats"] or {}, a_ema["stats"] or {}
    pick = pick_ma_winner(
        {"ok": True, "sum_pnl": ss.get("sum_pnl"), "win_rate": ss.get("win_rate")},
        {"ok": True, "sum_pnl": es.get("sum_pnl"), "win_rate": es.get("win_rate")},
    )
    pair = {
        "stock": stock,
        "year": "",
        "ok_sma": True,
        "ok_ema": True,
        "n_buy_sma": ss.get("n_buy"),
        "n_buy_ema": es.get("n_buy"),
        "sum_pnl_sma": ss.get("sum_pnl"),
        "sum_pnl_ema": es.get("sum_pnl"),
        "win_rate_sma": ss.get("win_rate"),
        "win_rate_ema": es.get("win_rate"),
        "avg_ret_sma": ss.get("avg_ret"),
        "avg_ret_ema": es.get("avg_ret"),
        "max_win_sma": ss.get("max_win"),
        "max_win_ema": es.get("max_win"),
        "max_loss_sma": ss.get("max_loss"),
        "max_loss_ema": es.get("max_loss"),
        "pnl_delta": pick.get("pnl_delta"),
        "winner": pick.get("winner"),
        "label": pick.get("label"),
        "why": pick.get("why"),
    }
    st.dataframe(ma_compare_dataframe([pair]), use_container_width=True, hide_index=True)
    st.caption("更优看总盈亏；接近时建议均线按胜率、再平 EMA。metric 为 EMA，delta 相对 SMA。")

    def _num(v: Any, default: float = 0.0) -> float:
        try:
            return float(v if v is not None else default)
        except (TypeError, ValueError):
            return default

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("轮次", int(_num(es.get("n_buy"))), delta=int(_num(es.get("n_buy")) - _num(ss.get("n_buy"))))
    c2.metric(
        "总盈亏",
        f"{_num(es.get('sum_pnl')):,.2f}",
        delta=f"{_num(es.get('sum_pnl')) - _num(ss.get('sum_pnl')):,.2f}",
    )
    c3.metric(
        "胜率",
        f"{_num(es.get('win_rate')):.1f}%",
        delta=f"{_num(es.get('win_rate')) - _num(ss.get('win_rate')):.1f}pp",
    )
    c4.metric(
        "平均收益%",
        f"{_num(es.get('avg_ret')):.2f}",
        delta=f"{_num(es.get('avg_ret')) - _num(ss.get('avg_ret')):.2f}",
    )
    c5.metric(
        "最大单笔%",
        f"{_num(es.get('max_win')):.2f}",
        delta=f"{_num(es.get('max_win')) - _num(ss.get('max_win')):.2f}",
    )
    c6.metric(
        "最大亏损%",
        f"{_num(es.get('max_loss')):.2f}",
        delta=f"{_num(es.get('max_loss')) - _num(ss.get('max_loss')):.2f}",
    )

    st.plotly_chart(
        _plot_equity_overlay(
            [
                (a_sma["equity"], "SMA", "#1565c0"),
                (a_ema["equity"], "EMA", "#e65100"),
            ],
            budget,
            "权益曲线对照（SMA / EMA）",
        ),
        width="stretch",
    )

    tab_sma, tab_ema = st.tabs(["SMA", "EMA"])
    with tab_sma:
        _render_analysis(
            sma_path,
            budget=budget,
            ohlc_csv=ohlc_csv,
            range_start=range_start,
            range_end=range_end,
            stock=stock,
            show_metrics=False,
            show_equity=False,
            title_prefix="SMA · ",
        )
    with tab_ema:
        _render_analysis(
            ema_path,
            budget=float(ema_pack.get("budget") or budget),
            ohlc_csv=ohlc_csv,
            range_start=range_start,
            range_end=range_end,
            stock=stock,
            show_metrics=False,
            show_equity=False,
            title_prefix="EMA · ",
        )


def _div_pack_for_compare(entry: dict, compare_ma: bool) -> dict:
    if compare_ma:
        return entry.get("ema") or entry.get("sma") or {}
    return entry.get("result") or entry.get("ema") or entry.get("sma") or {}


def _kpi_from_pack(pack: dict) -> dict:
    detail = pack.get("detail") or ""
    if not detail:
        return {"ok": False}
    budget = float(pack.get("budget") or 50000.0)
    analyzed = analyze_detail(Path(detail), budget=budget)
    stats = analyzed["stats"] or {}
    return {
        "ok": True,
        "n_buy": stats.get("n_buy"),
        "sum_pnl": stats.get("sum_pnl"),
        "win_rate": stats.get("win_rate"),
        "avg_ret": stats.get("avg_ret"),
        "equity": analyzed["equity"],
        "budget": budget,
    }


def _render_one_div_detail(
    entry: dict,
    *,
    compare_ma: bool,
    stock: str,
    start: str,
    end: str,
    title_prefix: str = "",
) -> None:
    ohlc = Path(entry["ohlc_csv"]) if entry.get("ohlc_csv") else None
    ohlc_ok = ohlc if ohlc and ohlc.is_file() else None
    if compare_ma and entry.get("sma") and entry.get("ema"):
        _render_ma_compare_panel(
            entry["sma"],
            entry["ema"],
            ohlc_ok,
            range_start=start,
            range_end=end,
            stock=stock,
        )
        return
    pack = _div_pack_for_compare(entry, compare_ma)
    if not pack.get("detail"):
        st.warning("该复权没有明细")
        return
    _render_analysis(
        Path(pack["detail"]),
        budget=float(pack.get("budget") or 50000.0),
        ohlc_csv=ohlc_ok,
        range_start=start,
        range_end=end,
        stock=stock,
        title_prefix=title_prefix,
    )


def _render_div_results(
    by_div: dict,
    *,
    compare_ma: bool,
    stock: str,
    start: str,
    end: str,
    tabs_key: str,
    default_div: str = "",
) -> None:
    divs_ok = [d for d in DIVIDEND_TYPES if d in by_div]
    if not divs_ok:
        st.warning("没有可查看的复权结果")
        return
    if len(divs_ok) >= 2:
        kpis: dict[str, dict] = {}
        series: list[tuple[Any, str, str]] = []
        budget = 50000.0
        for div in divs_ok:
            pack = _div_pack_for_compare(by_div[div], compare_ma)
            info = _kpi_from_pack(pack)
            kpis[div] = info
            if info.get("ok") and info.get("equity") is not None:
                series.append(
                    (
                        info["equity"],
                        dividend_label(div),
                        DIVIDEND_COLORS.get(div, "#1565c0"),
                    )
                )
                budget = float(info.get("budget") or budget)
        st.subheader("复权对照")
        st.dataframe(div_compare_dataframe(kpis, stock=stock), width="stretch", hide_index=True)
        if compare_ma:
            st.caption(
                "对照表与权益叠加用各复权的 EMA；切 tab 看 SMA。"
                "更优看总盈亏；接近再比胜率，仍平优先等比前复权。K 线因价格口径不同不叠加。"
            )
        else:
            st.caption(
                "更优看总盈亏；接近再比胜率，仍平优先等比前复权。K 线因价格口径不同不叠加。"
            )
        if series:
            st.plotly_chart(
                _plot_equity_overlay(series, budget, "权益曲线对照（复权）"),
                width="stretch",
            )
    if len(divs_ok) == 1:
        _render_one_div_detail(
            by_div[divs_ok[0]],
            compare_ma=compare_ma,
            stock=stock,
            start=start,
            end=end,
        )
        return
    labels = [dividend_label(d) for d in divs_ok]
    default_label = dividend_label(default_div) if default_div in divs_ok else labels[0]
    tabs = st.tabs(labels, on_change="rerun", key=tabs_key, default=default_label)
    for tab, div in zip(tabs, divs_ok):
        with tab:
            if not tab.open:
                continue
            _render_one_div_detail(
                by_div[div],
                compare_ma=compare_ma,
                stock=stock,
                start=start,
                end=end,
                title_prefix="%s · " % dividend_label(div),
            )


def _batch_div_packs(rows: list[dict], stock: str, year: str, compare_ma: bool) -> dict:
    by_div: dict[str, dict] = {}
    for r in rows:
        if str(r.get("stock") or "") != stock:
            continue
        if str(r.get("year") or "") != str(year or ""):
            continue
        if not r.get("ok"):
            continue
        div = normalize_dividend_type(r.get("dividend_type"))
        if not div:
            continue
        entry = by_div.setdefault(
            div,
            {"ohlc_csv": "", "sma": None, "ema": None, "result": None},
        )
        pack = {
            "detail": r.get("detail") or "",
            "budget": r.get("budget") or 50000.0,
            "log": r.get("log") or "",
        }
        ma = normalize_ma_type(r.get("ma_type"))
        if r.get("csv"):
            entry["ohlc_csv"] = r["csv"]
        if compare_ma and ma == "SMA":
            entry["sma"] = pack
        elif compare_ma and ma == "EMA":
            entry["ema"] = pack
        else:
            entry["result"] = pack
    return by_div


def _coerce_last_div_results() -> dict | None:
    saved = st.session_state.get("last_div_results")
    if saved and saved.get("by_div"):
        return saved
    cmp = st.session_state.get("last_compare")
    if cmp:
        return {
            "stock": cmp.get("stock") or "",
            "start": cmp.get("start") or "",
            "end": cmp.get("end") or "",
            "compare_ma": True,
            "by_div": {
                DEFAULT_DIVIDEND_TYPE: {
                    "ohlc_csv": cmp.get("ohlc_csv") or "",
                    "sma": cmp.get("sma"),
                    "ema": cmp.get("ema"),
                    "result": None,
                }
            },
        }
    last = st.session_state.get("last_result")
    if last:
        return {
            "stock": last.get("stock") or "",
            "start": last.get("start") or "",
            "end": last.get("end") or "",
            "compare_ma": False,
            "by_div": {
                DEFAULT_DIVIDEND_TYPE: {
                    "ohlc_csv": last.get("ohlc_csv") or "",
                    "sma": None,
                    "ema": None,
                    "result": last,
                }
            },
        }
    return None


def _render_batch_run(
    csv_root: str,
    divs: list[str],
    *,
    workers: int = 0,
    quiet: bool = True,
    compound: bool = False,
) -> None:
    if not divs:
        st.warning("请至少选择一种复权类型")
        return
    union_by: dict[str, dict] = {}
    empty_types = []
    skip_notes: list[str] = []
    for div in divs:
        csv_dir = str(resolve_typed_dir(csv_root, div))
        fp = _daily_dir_fingerprint(csv_dir)
        metas = _cached_daily_metas(csv_dir, fp)
        n_files = int(fp[0]) if fp else 0
        if n_files > len(metas):
            skip_notes.append(
                "%s：%s 个日线文件，解析 %s 只"
                % (dividend_label(div), n_files, len(metas))
            )
        if not metas:
            empty_types.append(div)
            continue
        for m in metas:
            stock = str(m.get("stock") or "").strip().upper()
            if not stock:
                continue
            prev = union_by.get(stock)
            if prev is None:
                union_by[stock] = {
                    "stock": stock,
                    "start": m["start"],
                    "end": m["end"],
                    "n": m["n"],
                    "by_div": {div: m},
                }
            else:
                prev["by_div"][div] = m
                if m["start"] < prev["start"]:
                    prev["start"] = m["start"]
                if m["end"] > prev["end"]:
                    prev["end"] = m["end"]
                prev["n"] = max(int(prev.get("n") or 0), int(m.get("n") or 0))
    if empty_types:
        st.caption("无行情：%s" % "、".join(dividend_label(x) for x in empty_types))
    metas = [union_by[k] for k in sorted(union_by)]
    if not metas:
        st.warning("所选复权目录无可用 `*_1d_*.csv`")
        return
    by_stock = {m["stock"]: m for m in metas}
    stocks = [m["stock"] for m in metas]
    pick_mode = st.radio(
        "标的范围",
        ["全部标的", "筛选标的"],
        horizontal=True,
        key="batch_pick_mode",
    )
    if pick_mode == "全部标的":
        picked = list(metas)
        st.caption(
            "已选 **%s** 只（%s 种复权并集）· 任务约 标的 × 年 × 均线 × 复权数"
            % (len(picked), len(divs))
        )
    else:
        q = str(
            st.text_input(
                "代码过滤",
                value="",
                key="batch_stock_filter",
                placeholder="600350,600028 或 600350 600028",
                help="多个代码用逗号或空格拼接；连续逗号、空格都可以。",
            )
            or ""
        )
        tokens = parse_stock_filter_tokens(q)
        options = [s for s in stocks if stock_matches_filter(s, tokens)]
        selected = st.multiselect(
            "标的",
            options=options,
            default=[],
            format_func=lambda s: "%s  ·  %s–%s  (%s根)"
            % (s, by_stock[s]["start"], by_stock[s]["end"], by_stock[s]["n"]),
            key="batch_stocks",
        )
        picked = [by_stock[s] for s in selected if s in by_stock]
        if options and not picked:
            st.caption("过滤后 %s 只，尚未勾选" % len(options))
    if skip_notes:
        st.caption("未计入：" + "；".join(skip_notes) + "（日线文件无法解析）")
    start_d = end_d = None
    run_btn = False
    split_label = "整段区间"
    compare_ma = False
    if not picked:
        st.info("请至少选择一只标的")
    else:
        u0, u1 = union_date_range(picked)
        d0, d1 = ymd_to_date(u0), ymd_to_date(u1)
        c_start, c_end = st.columns(2)
        with c_start:
            start_d = st.date_input("开始时间", value=d0, min_value=d0, max_value=d1, key="bt_batch_start")
        with c_end:
            end_d = st.date_input("结束时间", value=d1, min_value=d0, max_value=d1, key="bt_batch_end")
        if start_d > end_d:
            st.error("开始时间不能晚于结束时间")
        split_label = st.radio(
            "跑批类型",
            ["整段区间", "按自然年分段"],
            horizontal=True,
            key="batch_split",
        )
        if split_label == "按自然年分段":
            st.caption("每年独立账户、年初空仓；暖机仍用 walk 之前的历史 K 线。")
        compare_ma = st.checkbox("SMA/EMA 对照", value=False, key="batch_compare_ma")
        if compare_ma:
            st.caption(
                "每只（每年）各跑 SMA 与 EMA；再 × 复权数 %s。选股建议均线要用「按自然年分段 + 对照」。"
                % len(divs)
            )
        run_btn = st.button(
            "开始批量回测",
            type="primary",
            disabled=start_d > end_d or not divs,
        )

    split_mode = "year" if split_label == "按自然年分段" else "range"

    if run_btn and picked and start_d and end_d and start_d <= end_d:
        start_s = _fmt_ymd(start_d)
        end_s = _fmt_ymd(end_d)
        bar = st.progress(0.0)
        status = st.empty()
        all_rows: list[dict] = []
        all_pairs: list[dict] = []
        try:
            payloads: list[dict] = []
            for div in divs:
                out_dir = Path(resolve_typed_dir(DEFAULT_REPORT_ROOT, div))
                type_metas = []
                for p in picked:
                    m = (p.get("by_div") or {}).get(div)
                    if m:
                        type_metas.append(m)
                if not type_metas:
                    continue
                payloads.extend(
                    build_batch_payloads(
                        [Path(m["path"]) for m in type_metas],
                        start=start_s,
                        end=end_s,
                        out_dir=out_dir,
                        quiet=bool(quiet),
                        split=split_mode,
                        metas=type_metas,
                        compare_ma=bool(compare_ma),
                        dividend_type=div,
                    )
                )
            if compound:
                for p in payloads:
                    ov = dict(p.get("overrides") or {})
                    ov["compound_backtest"] = True
                    p["overrides"] = ov
            if not payloads:
                st.warning("所选区间与行情无交集，未生成任务。")
            else:

                def on_progress(i: int, n: int, stock: str) -> None:
                    bar.progress(min(1.0, 0.0 if n <= 0 else float(i) / float(n)))
                    if i < n:
                        status.info("正在 **%s**（%s/%s）…" % (stock, i + 1, n))
                    else:
                        status.success("完成 %s 个任务" % n)

                raw = _run_payloads(
                    payloads,
                    Path(DEFAULT_REPORT_ROOT),
                    on_progress,
                    int(workers),
                )
                rows = [summarize_batch_row(r) for r in raw]
                write_typed_summaries(rows, split=split_mode, compare_ma=bool(compare_ma))
                all_rows = rows
                if compare_ma:
                    all_pairs = pair_ma_batch_rows(rows)
                bar.progress(1.0)
                n_ok = sum(1 for r in all_rows if r.get("ok"))
                st.session_state["batch_result"] = {
                    "start": start_s,
                    "end": end_s,
                    "rows": all_rows,
                    "pairs": all_pairs,
                    "split": split_mode,
                    "compare_ma": bool(compare_ma),
                }
                st.success(
                    "完成 · 成功 %s · 失败 %s · 各复权目录已写 `local_bt_batch_summary.csv`"
                    % (n_ok, len(all_rows) - n_ok)
                )
        except Exception:
            st.error("批量回测失败")
            st.code(traceback.format_exc())

    batch = st.session_state.get("batch_result")
    if not batch:
        return
    split_saved = str(batch.get("split") or "range")
    compare_saved = bool(batch.get("compare_ma"))
    all_rows = list(batch.get("rows") or [])
    all_pairs = list(batch.get("pairs") or [])
    divs_in = unique_dividend_types(all_rows)
    picked_div = ""
    if len(divs_in) >= 2:
        opt_labels = ["全部"] + [dividend_label(d) for d in divs_in]
        picked_label = st.segmented_control(
            "复权筛选",
            opt_labels,
            default="全部",
            required=True,
            key="batch_div_filter",
        )
        if picked_label and picked_label != "全部":
            picked_div = next((d for d in divs_in if dividend_label(d) == picked_label), "")
    view_rows = all_rows
    view_pairs = all_pairs
    if picked_div:
        view_rows = [r for r in all_rows if normalize_dividend_type(r.get("dividend_type")) == picked_div]
        view_pairs = [p for p in all_pairs if normalize_dividend_type(p.get("dividend_type")) == picked_div]
    st.divider()
    if compare_saved:
        st.subheader("SMA / EMA 对照")
        st.caption("Δ盈亏 = EMA − SMA。更优看总盈亏；接近时建议均线按胜率、再平 EMA。")
        if split_saved == "year":
            st.dataframe(ma_compare_year_dataframe(view_pairs), width="stretch", hide_index=True)
        st.dataframe(ma_compare_dataframe(view_pairs), width="stretch", hide_index=True)
        st.plotly_chart(_plot_ma_delta_bar(view_pairs), width="stretch")
    elif split_saved == "year":
        st.subheader("按年汇总")
        st.caption("每年独立账户；胜率 / 平均收益% 按轮次加权。合计盈亏不是组合净值。多种复权按年×复权拆开。")
        st.dataframe(
            batch_year_summary_dataframe(view_rows),
            width="stretch",
            hide_index=True,
        )
    st.subheader("按标的汇总")
    st.caption("各标的独立账户、独立预算；合计盈亏不是组合净值。")
    st.dataframe(batch_summary_dataframe(view_rows), width="stretch", hide_index=True)

    show_div_in_label = (not picked_div) and len(unique_dividend_types(view_rows if not compare_saved else view_pairs)) >= 2

    def _row_label(r: dict) -> str:
        parts = [str(r.get("stock") or "")]
        year = str(r.get("year") or "").strip()
        if split_saved == "year" and year:
            parts.append(year)
        if show_div_in_label:
            div = normalize_dividend_type(r.get("dividend_type"))
            if div:
                parts.append(dividend_label(div))
        return " · ".join(p for p in parts if p)

    if compare_saved:
        ok_pairs = [p for p in view_pairs if p.get("sma_detail") or p.get("ema_detail")]
        if not ok_pairs:
            st.warning("没有成功的对照，无法查看明细。")
            return
        labels = [_row_label(p) for p in ok_pairs]
        pick = st.selectbox("查看标的对照明细", labels, key="batch_detail_stock")
        pair = next(p for p in ok_pairs if _row_label(p) == pick)
        st.divider()
        st.subheader("明细 · %s · 更优 %s" % (pick, pair.get("label") or pair.get("winner") or "-"))
        stock = str(pair.get("stock") or "")
        year = str(pair.get("year") or "")
        start_s = str(pair.get("walk_start") or batch.get("start") or "")
        end_s = str(pair.get("walk_end") or batch.get("end") or "")
        sibling = _batch_div_packs(all_rows, stock, year, True)
        if not picked_div and len(sibling) >= 2:
            _render_div_results(
                sibling,
                compare_ma=True,
                stock=stock,
                start=start_s,
                end=end_s,
                tabs_key="batch_div_tabs",
                default_div=normalize_dividend_type(pair.get("dividend_type")),
            )
            return
        ohlc = Path(pair.get("sma_csv") or pair.get("ema_csv") or "")
        sma_pack = {
            "detail": pair.get("sma_detail") or "",
            "budget": pair.get("budget") or 50000.0,
        }
        ema_pack = {
            "detail": pair.get("ema_detail") or "",
            "budget": pair.get("budget") or 50000.0,
        }
        if not sma_pack["detail"] or not ema_pack["detail"]:
            st.warning("对照两侧明细不齐。")
            return
        _render_ma_compare_panel(
            sma_pack,
            ema_pack,
            ohlc if ohlc.is_file() else None,
            range_start=start_s,
            range_end=end_s,
            stock=stock,
        )
        return

    ok_rows = [r for r in view_rows if r.get("ok") and r.get("detail")]
    if not ok_rows:
        st.warning("没有成功的标的，无法查看明细。")
        return

    labels = [_row_label(r) for r in ok_rows]
    pick = st.selectbox("查看标的明细", labels, key="batch_detail_stock")
    row = next(r for r in ok_rows if _row_label(r) == pick)
    st.divider()
    st.subheader("明细 · %s" % pick)
    stock = str(row.get("stock") or "")
    year = str(row.get("year") or "")
    start_s = str(row.get("walk_start") or batch.get("start") or "")
    end_s = str(row.get("walk_end") or batch.get("end") or "")
    sibling = _batch_div_packs(all_rows, stock, year, False)
    if not picked_div and len(sibling) >= 2:
        _render_div_results(
            sibling,
            compare_ma=False,
            stock=stock,
            start=start_s,
            end=end_s,
            tabs_key="batch_div_tabs",
            default_div=normalize_dividend_type(row.get("dividend_type")),
        )
        return
    ohlc = Path(row["csv"]) if row.get("csv") else None
    _render_analysis(
        Path(row["detail"]),
        budget=float(row.get("budget") or 50000.0),
        ohlc_csv=ohlc if ohlc and ohlc.is_file() else None,
        range_start=start_s,
        range_end=end_s,
        stock=stock,
    )


def _select_display_df(df: pd.DataFrame, *, passed_only: bool = False, score_years: tuple[str, ...] | None = None) -> pd.DataFrame:
    src = df[df["passed"]].copy() if passed_only and "passed" in df.columns else df.copy()
    if src.empty:
        return pd.DataFrame()
    out = pd.DataFrame()
    out["名次"] = src["rank"]
    out["代码"] = src["stock"]
    out["得分"] = pd.to_numeric(src["score"], errors="coerce") * 100.0
    out["建议均线"] = src["ma_type_suggest"].map(lambda x: x if str(x or "").strip() else "缺对照")
    if "ma_type_why" in src.columns:
        out["均线来源"] = src["ma_type_why"]
    if "div_type_suggest" in src.columns:
        out["建议复权"] = src["div_type_suggest"].map(
            lambda x: dividend_label(x) if str(x or "").strip() else "缺对照"
        )
    if "div_type_why" in src.columns:
        out["复权来源"] = src["div_type_why"]
    if "ma_pnl_delta" in src.columns:
        out["Δ盈亏"] = src["ma_pnl_delta"]
    out["白名单"] = src["in_book"].map(lambda x: "是" if x else "")
    out["跨年轮次"] = src["n_buy"]
    if "n_buy_year_min" in src.columns:
        out["年最少轮次"] = src["n_buy_year_min"]
    out["成交年"] = src["n_years_traded"]
    out["盈利年"] = src["n_years_pos"]
    out["稳定性"] = pd.to_numeric(src["stability"], errors="coerce") * 100.0
    out["年等权盈亏"] = src["pnl_year_mean"]
    out["胜率"] = src["win_rate"]
    out["利润因子"] = src["profit_factor"]
    out["策略质量"] = src["quality"]
    out["trail占比"] = pd.to_numeric(src["trail_share"], errors="coerce") * 100.0
    out["最大回撤"] = pd.to_numeric(src["max_dd"], errors="coerce") * 100.0
    out["年化波动"] = pd.to_numeric(src["vol_ann"], errors="coerce") * 100.0
    out["贴线率"] = pd.to_numeric(src["touch_ma20"], errors="coerce") * 100.0
    out["近期"] = src["recent_flag"]
    out["未过原因"] = src["fail_reason"]
    years = score_years or SCORE_YEARS
    for y in years:
        col = "pnl_%s" % y
        if col in src.columns:
            out["盈亏%s" % y] = src[col]
    return insert_name_column(out.reset_index(drop=True), code_col="代码")


def _plot_year_heatmap(heat: pd.DataFrame, score_years: tuple[str, ...] | None = None) -> go.Figure:
    fig = go.Figure()
    if heat is None or heat.empty:
        fig.add_annotation(text="无过线标的", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(height=200, margin=dict(l=40, r=20, t=40, b=40))
        return fig
    zdf = heat.copy()
    years = score_years or SCORE_YEARS
    y_cols = ["pnl_%s" % y for y in years]
    rename = {c: c.replace("pnl_", "") for c in y_cols}
    rename["recent_pnl"] = "近期"
    keep = ["stock"] + [c for c in y_cols + ["recent_pnl"] if c in zdf.columns]
    zdf = zdf[keep].set_index("stock")
    zdf = zdf.rename(columns=rename)
    y_labels = [stock_axis_label(str(s)) for s in zdf.index]
    fig.add_trace(
        go.Heatmap(
            z=zdf.values,
            x=list(zdf.columns),
            y=y_labels,
            colorscale="RdYlGn",
            zmid=0,
            colorbar=dict(title="盈亏 (元)"),
            hovertemplate="%{y} · %{x}<br>盈亏 %{z:,.0f} 元<extra></extra>",
        )
    )
    fig.update_layout(
        title="年度盈亏（过线标的；含未走完年；无年份整段不进主分）",
        xaxis_title="区间",
        yaxis_title="代码",
        height=max(280, 28 * len(zdf) + 80),
        margin=dict(l=100, r=20, t=50, b=40),
        yaxis=dict(autorange="reversed"),
    )
    return fig


def _plot_sell_pie(counts: dict) -> go.Figure:
    fig = go.Figure()
    labels = []
    values = []
    for k, v in (counts or {}).items():
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        labels.append(str(k))
        values.append(n)
    if not values:
        fig.add_annotation(text="无卖出信号", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(height=280, margin=dict(l=20, r=20, t=40, b=20))
        return fig
    fig.add_trace(go.Pie(labels=labels, values=values, hole=0.35, name="卖出"))
    fig.update_layout(
        title="卖出原因（分年合计）",
        height=320,
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h"),
    )
    return fig


def _render_select(
    csv_dir: str,
    report_dir: str,
    filters: dict,
    score_years: tuple[str, ...] | None = None,
    scanned: dict | None = None,
) -> None:
    if scanned is None:
        try:
            scanned = _cached_select_scan(
                report_dir,
                csv_dir,
                report_fingerprint(report_dir),
                csv_dir_fingerprint(csv_dir),
            )
        except Exception:
            st.error("扫描回测报告失败")
            st.code(traceback.format_exc())
            return

    scored = score_universe(scanned, filters=filters, score_years=score_years)
    df = scored["df"]
    passed = scored["passed"]
    rec = scored["recommend"]
    cov = scored.get("coverage") or {}
    years = tuple(scored.get("score_years") or SCORE_YEARS)
    out_path = Path(report_dir) / "local_bt_stock_select.csv"
    try:
        write_select_csv(df, out_path)
    except Exception as e:
        st.warning("写选股 CSV 失败：%s" % e)

    for line in coverage_notes(cov, scanned):
        st.markdown("- " + line)

    n_all = int(cov.get("n_stock") or 0)
    n_pass = 0 if passed is None or passed.empty else len(passed)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("扫描标的", n_all)
    c2.metric("过线", n_pass)
    c3.metric("推荐池", 0 if rec is None or rec.empty else len(rec))
    cut = scored.get("vol_cut")
    c4.metric("波动上限", "-" if cut is None else "%.1f%%" % (float(cut) * 100.0))
    st.caption("产物：`%s` · 扫描全部复权子目录 · 不自动改 `BOOK_STOCKS`" % out_path)

    st.subheader("现白名单对照")
    book_rank = scored.get("book_rank")
    if book_rank is None or book_rank.empty:
        st.info("现白名单四只不在本次扫描结果里（可能还没跑过分年回测）。")
    else:
        st.dataframe(_select_display_df(book_rank, score_years=years), use_container_width=True, hide_index=True)

    st.subheader("推荐池 Top %s" % int(filters.get("top_n") or 6))
    if rec is None or rec.empty:
        st.warning("没有过线标的。放宽侧栏阈值，或先补齐分年批量回测。")
    else:
        st.dataframe(_select_display_df(rec, score_years=years), use_container_width=True, hide_index=True)
        st.caption("建议均线/复权按侧栏选定年重算；缺对照的票不写入 snippet。不自动改 `BOOK_STOCKS`。")
        st.code(format_book_snippet(rec), language="python")

    st.subheader("打分总表")
    view = st.radio("显示", ["仅过线", "全部（含未过）"], horizontal=True, key="select_view")
    table = _select_display_df(df, passed_only=(view == "仅过线"), score_years=years)
    if table.empty:
        st.info("无行可显示")
    else:
        st.dataframe(table, use_container_width=True, hide_index=True)

    st.subheader("年度盈亏热力")
    heat = scored.get("heatmap")
    if heat is not None and not heat.empty and len(heat) > 40:
        heat = heat.head(40)
        st.caption("过线标的较多，热力只画得分最高的 40 只。")
    st.plotly_chart(_plot_year_heatmap(heat, score_years=years), use_container_width=True)

    details = scored.get("details") or {}
    names = [] if passed is None or passed.empty else passed["stock"].tolist()
    if names:
        st.subheader("标的展开")
        pick = st.selectbox("过线标的", names, key="select_detail_stock")
        one = df[df["stock"] == pick]
        if not one.empty:
            st.dataframe(_select_display_df(one, score_years=years), use_container_width=True, hide_index=True)
        info = details.get(pick) or {}
        year_rows = []
        years = info.get("years") or {}
        for y in years:
            k = years.get(y)
            if not k:
                year_rows.append({"年份": y, "状态": "缺文件", "轮次": None, "总盈亏": None, "胜率": None})
                continue
            year_rows.append(
                {
                    "年份": y,
                    "状态": "有",
                    "轮次": k.get("n_buy"),
                    "总盈亏": k.get("sum_pnl"),
                    "胜率": k.get("win_rate"),
                    "平均收益%": k.get("avg_ret"),
                    "利润因子": k.get("profit_factor"),
                    "最大回撤": None if k.get("max_dd") is None else float(k["max_dd"]) * 100.0,
                    "trail占比": None
                    if not k.get("sell")
                    else 100.0
                    * float(k["sell"].get("trail_stop") or 0)
                    / max(1, sum(int(v) for v in k["sell"].values())),
                }
            )
        recent = info.get("recent")
        if recent:
            year_rows.append(
                {
                    "年份": "近期",
                    "状态": "有",
                    "轮次": recent.get("n_buy"),
                    "总盈亏": recent.get("sum_pnl"),
                    "胜率": recent.get("win_rate"),
                    "平均收益%": recent.get("avg_ret"),
                    "利润因子": recent.get("profit_factor"),
                    "最大回撤": None
                    if recent.get("max_dd") is None
                    else float(recent["max_dd"]) * 100.0,
                    "trail占比": None,
                }
            )
        left, right = st.columns([1.4, 1])
        with left:
            st.dataframe(pd.DataFrame(year_rows), use_container_width=True, hide_index=True)
        with right:
            st.plotly_chart(_plot_sell_pie(info.get("sell") or {}), use_container_width=True)
        st.caption("看 K 线 / 成交明细请切到「仅分析已有明细」。")


def _render_select_filter_widgets(year_max: int) -> dict[str, Any]:
    """按 select_config.FILTER_WIDGETS 画硬过滤控件。"""
    out: dict[str, Any] = {}
    for spec in FILTER_WIDGETS:
        kwargs = widget_kwargs(spec, year_max=year_max)
        key = str(spec["key"])
        label = str(spec["label"])
        wkey = "select_flt_%s" % key
        if wkey in st.session_state:
            kwargs.pop("value", None)
        widget = str(spec.get("widget") or "number_input")
        if widget == "slider":
            raw = st.slider(label, key=wkey, **kwargs)
        else:
            raw = st.number_input(label, key=wkey, **kwargs)
        out[key] = cast_filter_value(spec, raw)
        cap = spec.get("caption")
        if cap:
            st.caption(str(cap))
    return out


def _render_select_sidebar() -> tuple[dict[str, Any], tuple[str, ...] | None, dict | None]:
    """选股侧栏：打分年份 + 硬过滤。默认值/范围见 select_config.py。"""
    cfg = SELECT_SIDEBAR
    st.subheader(str(cfg["year_section"]))
    try:
        scanned = _cached_select_scan(
            str(DEFAULT_REPORT_ROOT),
            str(DEFAULT_CSV_ROOT),
            report_fingerprint(str(DEFAULT_REPORT_ROOT)),
            csv_dir_fingerprint(str(DEFAULT_CSV_ROOT)),
        )
    except Exception:
        scanned = {"stocks": {}, "book": {}, "score_years": ()}
        st.error("扫描回测报告失败")
        st.code(traceback.format_exc())
    avail = infer_score_years((scanned or {}).get("stocks") or {}) or tuple(SCORE_YEARS)
    start_key = str(cfg["year_start_key"])
    end_key = str(cfg["year_end_key"])
    start = st.selectbox(str(cfg["year_start_label"]), list(avail), index=0, key=start_key)
    end_opts = [y for y in avail if str(y) >= str(start)] or list(avail)
    if st.session_state.get(end_key) not in end_opts:
        st.session_state[end_key] = end_opts[-1]
    end = st.selectbox(str(cfg["year_end_label"]), end_opts, key=end_key)
    if str(end) < str(start):
        start, end = end, start
    select_years = tuple(y for y in avail if str(start) <= str(y) <= str(end))
    if not select_years:
        select_years = avail
    st.caption(str(cfg["year_caption"]) % (select_years[0], select_years[-1]))
    st.subheader(str(cfg["filter_section"]))
    filters = _render_select_filter_widgets(year_max_for_window(len(select_years)))
    if st.button(str(cfg["refresh_label"])):
        _cached_select_scan.clear()
        st.rerun()
    return filters, select_years, scanned


def _collect_analysis_form(avail: tuple[str, ...], defaults: dict[str, Any]) -> dict[str, Any]:
    cfg = ANALYSIS_SIDEBAR
    analysis_type = st.radio(
        "分析类型",
        ["Walk-forward", "固定标的"],
        horizontal=True,
        index=0 if str(defaults.get("analysis_type") or "Walk-forward") != "固定标的" else 1,
        key="analysis_type_radio",
    )
    if analysis_type == "固定标的":
        if st.button("从 config 重载 BOOK_STOCKS", key="analysis_reload_book"):
            st.session_state["analysis_book_rows"] = book_stocks_to_editor_rows(load_book_stocks_full())
            st.rerun()
        if "analysis_book_rows" not in st.session_state:
            st.session_state["analysis_book_rows"] = book_stocks_to_editor_rows(
                defaults.get("book_stocks") or load_book_stocks_full()
            )

    start_default = str(defaults.get("data_start") or (avail[0] if avail else ""))
    end_default = str(defaults.get("data_end") or (avail[-1] if avail else ""))
    if start_default and end_default and end_default < start_default:
        start_default, end_default = end_default, start_default
    with st.form(str(cfg["form_key"])):
        st.subheader(str(cfg["title"]))
        st.caption(str(cfg["scan_caption"]))
        params: dict[str, Any] = dict(defaults)
        params["analysis_type"] = analysis_type
        st.markdown("**%s**" % cfg["year_section"])
        c1, c2 = st.columns(2)
        with c1:
            start = st.selectbox(
                str(cfg["year_start_label"]),
                list(avail),
                index=list(avail).index(start_default) if start_default in avail else 0,
                key="analysis_form_data_start",
            )
        with c2:
            end_opts = [y for y in avail if y >= start] or list(avail)
            end = st.selectbox(
                str(cfg["year_end_label"]),
                end_opts,
                index=end_opts.index(end_default) if end_default in end_opts else len(end_opts) - 1,
                key="analysis_form_data_end",
            )

        if analysis_type == "固定标的":
            st.markdown("**固定标的（默认 config.BOOK_STOCKS，可改；不写回）**")
            edited = st.data_editor(
                pd.DataFrame(st.session_state.get("analysis_book_rows") or []),
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "代码": st.column_config.TextColumn("代码", required=True),
                    "名称": st.column_config.TextColumn("名称", disabled=True),
                    "均线类型": st.column_config.SelectboxColumn(
                        "均线类型", options=["EMA", "SMA"], required=True
                    ),
                    "复权方式": st.column_config.SelectboxColumn(
                        "复权方式",
                        options=list(DIVIDEND_TYPES),
                        required=True,
                        format_func=lambda k: "%s（%s）" % (DIVIDEND_LABELS.get(k, k), k),
                    ),
                },
                key="analysis_book_editor",
            )
            params["book_stocks"] = editor_rows_to_book_stocks(edited)
            params["force_rerun"] = st.checkbox("强制重跑回放", value=bool(params.get("force_rerun")))
            params["compound_backtest"] = st.checkbox(
                "复利回测",
                value=bool(params.get("compound_backtest", True)),
            )
        else:
            st.markdown("**%s**" % cfg["walk_section"])
            ac1, ac2, ac3 = st.columns(3)
            with ac1:
                params["lookback_n"] = int(
                    st.number_input(
                        "打分回看年数",
                        min_value=1,
                        max_value=10,
                        value=int(params.get("lookback_n") or 2),
                        step=1,
                    )
                )
            with ac2:
                params["rebalance_years"] = int(
                    st.number_input(
                        "换仓周期",
                        min_value=1,
                        max_value=10,
                        value=int(params.get("rebalance_years") or 1),
                        step=1,
                    )
                )
            with ac3:
                params["top_k"] = int(
                    st.number_input(
                        "每段持仓只数",
                        min_value=1,
                        max_value=9,
                        value=int(params.get("top_k") or 3),
                        step=1,
                    )
                )
            params["score_mode"] = st.selectbox(
                "打分 KPI",
                ["portfolio", "single"],
                index=0 if str(params.get("score_mode") or "portfolio") == "portfolio" else 1,
                format_func=lambda x: "组合回放（推荐）" if x == "portfolio" else "单票 KPI（回退）",
            )
            params["score_pool"] = st.selectbox(
                "打分池",
                ["scanned", "passed_prefilter"],
                index=0 if str(params.get("score_pool") or "scanned") == "scanned" else 1,
                format_func=lambda x: "扫描全池" if x == "scanned" else "宽松预过滤",
            )
            params["force_rerun"] = st.checkbox("强制重跑回放", value=bool(params.get("force_rerun")))
            params["compound_backtest"] = st.checkbox(
                "复利回测（持有期跨年传递权益）",
                value=bool(params.get("compound_backtest", True)),
            )
            params["workers"] = int(
                st.number_input(
                    "打分并行进程（0=顺序）",
                    min_value=0,
                    max_value=8,
                    value=int(params.get("workers") or 0),
                    step=1,
                )
            )
            st.markdown("**%s**" % cfg["filter_section"])
            flt: dict[str, Any] = {}
            for spec in FILTER_WIDGETS:
                kwargs = widget_kwargs(spec, year_max=year_max_for_window(max(int(params["lookback_n"]), 1)))
                fk = "analysis_flt_%s" % spec["key"]
                if str(spec.get("widget") or "") == "slider":
                    flt[spec["key"]] = cast_filter_value(spec, st.slider(str(spec["label"]), key=fk, **kwargs))
                else:
                    flt[spec["key"]] = cast_filter_value(
                        spec, st.number_input(str(spec["label"]), key=fk, **kwargs)
                    )
            params["filters"] = flt
            with st.expander(str(cfg["advanced_section"])):
                weights = dict(WEIGHTS)
                wc = st.columns(len(WEIGHT_WIDGETS))
                for i, wspec in enumerate(WEIGHT_WIDGETS):
                    with wc[i]:
                        weights[wspec["key"]] = float(
                            st.number_input(
                                str(wspec["label"]),
                                min_value=0.0,
                                max_value=1.0,
                                value=float(
                                    (params.get("weights") or {}).get(wspec["key"], wspec["default"])
                                ),
                                step=0.05,
                                key="analysis_w_%s" % wspec["key"],
                            )
                        )
                params["weights"] = weights

        st.markdown("**%s**" % cfg["book_section"])
        bc1, bc2 = st.columns(2)
        book = load_book_defaults()
        with bc1:
            params["trade_budget"] = float(
                st.number_input(
                    "组合资金帽（元）",
                    min_value=10000.0,
                    value=float(params.get("trade_budget") or book["trade_budget"]),
                    step=10000.0,
                )
            )
            params["book_lot_max"] = int(
                st.number_input(
                    "BOOK_LOT_MAX",
                    min_value=1,
                    max_value=9,
                    value=int(params.get("book_lot_max") or book["book_lot_max"]),
                    step=1,
                )
            )
        with bc2:
            params["lot_open_frac"] = float(
                st.slider(
                    "大仓档",
                    min_value=0.1,
                    max_value=0.9,
                    value=float(params.get("lot_open_frac") or book["lot_open_frac"]),
                    step=0.05,
                )
            )
            params["lot_add_frac"] = float(
                st.slider(
                    "加仓档",
                    min_value=0.05,
                    max_value=0.5,
                    value=float(params.get("lot_add_frac") or book["lot_add_frac"]),
                    step=0.05,
                )
            )
        submitted = st.form_submit_button(str(cfg["submit_label"]))
    if str(end) < str(start):
        start, end = end, start
    lookback = int(params.get("lookback_n") or 2)
    data_years, eval_years = data_and_eval_years(str(start), str(end), lookback, avail)
    params["data_start"] = str(start)
    params["data_end"] = str(end)
    params["data_years"] = data_years
    params["eval_years"] = eval_years
    if submitted and analysis_type == "Walk-forward" and data_years:
        first_eval = eval_years[0] if eval_years else "-"
        st.info(
            str(cfg["year_caption"])
            % (data_years[0], data_years[-1], lookback, first_eval, eval_years[-1] if eval_years else "-")
        )
    elif submitted and analysis_type == "固定标的":
        st.info("固定标的连续回放 %s–%s · %s 只" % (start, end, len(params.get("book_stocks") or {})))
    return submitted, params


def _year_summary_display_df(yr: pd.DataFrame) -> pd.DataFrame:
    hide = ("pick_details", "hold_detail_path", "wallet_start", "wallet_end", "skipped_buys")
    cols = [c for c in yr.columns if c not in hide]
    out = yr[cols] if cols else yr
    return rename_columns(out, ANALYSIS_YEAR_COLUMNS)


def _period_summary_display_df(pr: pd.DataFrame) -> pd.DataFrame:
    return rename_columns(pr, ANALYSIS_PERIOD_COLUMNS)


@st.dialog("所选标的")
def _dialog_year_picks(year_label: str, details: list[dict[str, Any]]) -> None:
    st.caption("评估年 %s" % year_label)
    if not details:
        st.info("该年无标的明细（窗口不足 / 无推荐 / 旧结果未含 pick_details）。")
        return
    rows = []
    for d in details:
        div = str(d.get("dividend_type") or "")
        code = str(d.get("stock") or "")
        rows.append(
            {
                "代码": code,
                "名称": stock_display_name(code),
                "均线类型": d.get("ma_type") or "-",
                "复权方式": "%s（%s）" % (DIVIDEND_LABELS.get(div, div), div) if div else "-",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_fixed_book_results(result: dict[str, Any], params: dict[str, Any]) -> None:
    cfg = ANALYSIS_SIDEBAR
    if st.button(str(cfg["reset_label"]), key="analysis_reset_fixed"):
        st.session_state.pop(str(cfg["result_key"]), None)
        st.session_state.pop(str(cfg["params_key"]), None)
        st.rerun()
    st.caption("参数：%s" % {k: v for k, v in params.items() if k != "book_stocks"})
    for line in result.get("notes") or []:
        st.markdown("- " + line)
    s = result.get("summary") or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("标的数", s.get("n_stocks"))
    c2.metric("轮次", s.get("n_buy"))
    pnl = s.get("total_pnl")
    c3.metric("组合盈亏", "-" if pnl is None else "%.0f" % float(pnl))
    if s.get("wallet_start") is not None and s.get("wallet_end") is not None:
        c4.metric(
            "权益",
            "%.0f→%.0f" % (float(s["wallet_start"]), float(s["wallet_end"])),
        )
    else:
        c4.metric("状态", s.get("status") or "-")
    detail = str(result.get("hold_detail_path") or "").strip()
    if detail and Path(detail).is_file():
        book = dict(params.get("book_params") or load_book_defaults())
        budget = float(book.get("trade_budget") or params.get("trade_budget") or 100000.0)
        st.subheader("回放操作记录")
        cap = "固定标的 · %s–%s" % (
            (result.get("params") or {}).get("start"),
            (result.get("params") or {}).get("end"),
        )
        if s.get("wallet_start") is not None and s.get("wallet_end") is not None:
            cap += " · 权益 %.0f→%.0f" % (float(s["wallet_start"]), float(s["wallet_end"]))
        _render_book_detail_panel(Path(detail), budget, caption=cap)
    out_path = Path(str(DEFAULT_REPORT_ROOT)) / "local_bt_fixed_book.csv"
    try:
        write_fixed_book_csv(result, out_path)
        st.caption("产物：`%s`" % out_path)
    except Exception as e:
        st.warning("写 CSV 失败：%s" % e)


def _render_analysis_results(result: dict[str, Any], params: dict[str, Any]) -> None:
    if str(result.get("mode") or params.get("analysis_type") or "") in ("fixed", "固定标的"):
        _render_fixed_book_results(result, params)
        return
    cfg = ANALYSIS_SIDEBAR
    if st.button(str(cfg["reset_label"]), key="analysis_reset"):
        st.session_state.pop(str(cfg["result_key"]), None)
        st.session_state.pop(str(cfg["params_key"]), None)
        st.rerun()
    st.caption("参数：%s" % params)
    for line in result.get("notes") or []:
        st.markdown("- " + line)
    s = result.get("summary") or {}
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("有效评估年", s.get("n_ok_years"))
    c2.metric("组合合计盈亏", "%.0f" % float(s.get("total_pnl") or 0))
    c3.metric("年均盈亏", "-" if s.get("mean_pnl") is None else "%.0f" % float(s["mean_pnl"]))
    ratio = s.get("pos_ratio")
    c4.metric("盈利年占比", "-" if ratio is None else "%.0f%%" % (100.0 * float(ratio)))
    yr = pd.DataFrame(result.get("year_rows") or [])
    if not yr.empty:
        st.subheader("分年汇总")
        st.dataframe(_year_summary_display_df(yr), use_container_width=True, hide_index=True)
        year_rows = list(result.get("year_rows") or [])
        labels = []
        for row in year_rows:
            hy = str(row.get("year") or "")
            picks = str(row.get("picks") or "")
            status = str(row.get("status") or "")
            labels.append("%s · %s · %s" % (hy, status, picks or "（空）"))
        c_sel, c_btn = st.columns([4, 1], vertical_alignment="bottom")
        with c_sel:
            idx = st.selectbox(
                "查看哪一年的标的",
                range(len(year_rows)),
                format_func=lambda i: labels[i],
                key="analysis_year_picks_idx",
            )
        with c_btn:
            if st.button("查看标的", key="analysis_year_picks_btn", use_container_width=True):
                row = year_rows[int(idx)]
                details = list(row.get("pick_details") or [])
                _dialog_year_picks(str(row.get("year") or ""), details)
    pr = pd.DataFrame(result.get("period_rows") or [])
    if not pr.empty:
        with st.expander("换仓段汇总"):
            st.dataframe(_period_summary_display_df(pr), use_container_width=True, hide_index=True)
    eq = result.get("equity_pts") or []
    if eq:
        edf = pd.DataFrame(eq)
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(x=edf["year"], y=edf["cum_pnl"], mode="lines+markers", name="累计组合盈亏")
        )
        compound = bool(s.get("compound_backtest") or params.get("compound_backtest"))
        title = (
            "累计权益变动（复利 · 跨年传递）"
            if compound
            else "累计组合盈亏（固定预算 · 非复利）"
        )
        fig.update_layout(title=title, height=360)
        st.plotly_chart(fig, use_container_width=True)
        if compound and s.get("final_wallet") is not None:
            st.caption(
                "初始权益 %s → 期末权益 %s"
                % (
                    "%.0f" % float(s.get("initial_wallet") or 0),
                    "%.0f" % float(s.get("final_wallet") or 0),
                )
            )
    _render_analysis_trade_records(result, params)
    out_path = Path(str(DEFAULT_REPORT_ROOT)) / "local_bt_select_analysis.csv"
    try:
        write_analysis_csv(result, out_path)
        st.caption("产物：`%s`" % out_path)
    except Exception as e:
        st.warning("写 CSV 失败：%s" % e)


def _render_analysis_mode(scanned: dict | None) -> None:
    cfg = ANALYSIS_SIDEBAR
    avail = infer_score_years((scanned or {}).get("stocks") or {}) or tuple(SCORE_YEARS)
    if not avail:
        avail = tuple(str(y) for y in range(2018, 2027))
        st.caption("未扫到分年报告，年份列表使用 2018–2026 兜底（固定标的仍可读 CSV）。")
    defaults = dict(st.session_state.get(str(cfg["params_key"])) or {})
    defaults.setdefault("lookback_n", 2)
    defaults.setdefault("rebalance_years", 1)
    defaults.setdefault("top_k", 3)
    defaults.setdefault("compound_backtest", True)
    defaults.setdefault("analysis_type", "Walk-forward")
    defaults.update(load_book_defaults())
    result = st.session_state.get(str(cfg["result_key"]))
    if result is None:
        submitted, params = _collect_analysis_form(avail, defaults)
        if submitted:
            with st.spinner("组合回放分析中…"):
                try:
                    book_params = {
                        "trade_budget": params.get("trade_budget"),
                        "book_lot_max": params.get("book_lot_max"),
                        "lot_open_frac": params.get("lot_open_frac"),
                        "lot_add_frac": params.get("lot_add_frac"),
                    }
                    if str(params.get("analysis_type") or "") == "固定标的":
                        result = run_fixed_book(
                            params.get("book_stocks") or load_book_stocks_full(),
                            data_start=str(params.get("data_start") or ""),
                            data_end=str(params.get("data_end") or ""),
                            book_params=book_params,
                            csv_root=str(DEFAULT_CSV_ROOT),
                            report_dir=str(DEFAULT_REPORT_ROOT),
                            compound_backtest=bool(params.get("compound_backtest", True)),
                            force_rerun=bool(params.get("force_rerun")),
                        )
                    else:
                        result = run_walk_forward(
                            scanned or {"stocks": {}, "portfolio_kpi": {}},
                            data_start=str(params.get("data_start") or ""),
                            data_end=str(params.get("data_end") or ""),
                            lookback_n=int(params.get("lookback_n") or 2),
                            rebalance_years=int(params.get("rebalance_years") or 1),
                            top_k=int(params.get("top_k") or 3),
                            filters=params.get("filters") or dict(DEFAULT_FILTERS),
                            weights=params.get("weights") or dict(WEIGHTS),
                            book_params=book_params,
                            csv_root=str(DEFAULT_CSV_ROOT),
                            report_dir=str(DEFAULT_REPORT_ROOT),
                            score_mode=str(params.get("score_mode") or "portfolio"),
                            score_pool=str(params.get("score_pool") or "scanned"),
                            force_rerun=bool(params.get("force_rerun")),
                            workers=int(params.get("workers") or 0),
                            compound_backtest=bool(params.get("compound_backtest", True)),
                        )
                    st.session_state[str(cfg["result_key"])] = result
                    st.session_state[str(cfg["params_key"])] = params
                    st.session_state["analysis_book_rows"] = book_stocks_to_editor_rows(
                        params.get("book_stocks") or {}
                    )
                    st.rerun()
                except Exception:
                    st.error("分析失败")
                    st.code(traceback.format_exc())
        return
    params = st.session_state.get(str(cfg["params_key"])) or defaults
    _render_analysis_results(result, params)

# ---------- sidebar / controls ----------
mode = st.radio("模式", ["跑本地回测", "仅分析已有明细", "选股方案", "数据分析"], horizontal=True)
scope = "单标的"
if mode == "跑本地回测":
    scope = st.radio("范围", ["单标的", "批量（按标的汇总）"], horizontal=True)

with st.sidebar:
    st.header("参数")
    csv_root = str(DEFAULT_CSV_ROOT)
    divs: list[str] = []
    if mode != "选股方案" and mode != "数据分析":
        csv_root = st.text_input("行情根目录", value=str(DEFAULT_CSV_ROOT))
        divs = st.multiselect(
            "复权类型",
            options=list(DIVIDEND_TYPES),
            default=[DEFAULT_DIVIDEND_TYPE],
            format_func=lambda k: "%s（%s）" % (DIVIDEND_LABELS.get(k, k), k),
            key="bt_dividend_types",
        )
        if divs:
            st.caption(
                "已选 %s 种 · 行情 `csv/<type>/` · 产物 `report/<type>/`"
                % len(divs)
            )
        else:
            st.warning("请至少选择一种复权")
    else:
        st.caption(str(SELECT_SIDEBAR["scan_caption"]) if mode == "选股方案" else str(ANALYSIS_SIDEBAR["scan_caption"]))
    report_dirs = [str(resolve_typed_dir(DEFAULT_REPORT_ROOT, d)) for d in divs]
    csv_dirs = [str(resolve_typed_dir(csv_root, d)) for d in divs]
    csv_dir = csv_dirs[0] if csv_dirs else str(resolve_typed_dir(csv_root, DEFAULT_DIVIDEND_TYPE))
    report_dir = report_dirs[0] if report_dirs else str(resolve_typed_dir(DEFAULT_REPORT_ROOT, DEFAULT_DIVIDEND_TYPE))
    uploaded = None
    quiet = True
    workers = 0
    compound_bt = True
    if mode == "跑本地回测" and scope == "单标的":
        uploaded = st.file_uploader("或上传日线 CSV", type=["csv"])
    if mode == "跑本地回测":
        quiet = not st.checkbox("详细日志（慢）", value=False, key="bt_verbose")
        compound_bt = st.checkbox("复利回测", value=True, key="bt_compound")
        if scope == "批量（按标的汇总）":
            workers = int(
                st.number_input("进程数（0=自动）", min_value=0, max_value=16, value=0, step=1, key="bt_workers")
            )
    select_filters = dict(DEFAULT_FILTERS)
    select_years: tuple[str, ...] | None = None
    select_scanned: dict | None = None
    analysis_scanned: dict | None = None
    if mode == "选股方案":
        select_filters, select_years, select_scanned = _render_select_sidebar()
    elif mode == "数据分析":
        if st.button(str(ANALYSIS_SIDEBAR["refresh_label"]), key="analysis_refresh"):
            _cached_select_scan.clear()
            st.session_state.pop(str(ANALYSIS_SIDEBAR["result_key"]), None)
            st.session_state.pop(str(ANALYSIS_SIDEBAR["params_key"]), None)
            st.rerun()
        try:
            analysis_scanned = _cached_select_scan(
                str(DEFAULT_REPORT_ROOT),
                str(DEFAULT_CSV_ROOT),
                report_fingerprint(str(DEFAULT_REPORT_ROOT)),
                csv_dir_fingerprint(str(DEFAULT_CSV_ROOT)),
            )
        except Exception:
            analysis_scanned = {"stocks": {}, "portfolio_kpi": {}}
            st.error("扫描回测报告失败")
            st.code(traceback.format_exc())

if mode == "选股方案":
    _render_select(
        str(DEFAULT_CSV_ROOT),
        str(DEFAULT_REPORT_ROOT),
        select_filters,
        score_years=select_years,
        scanned=select_scanned,
    )
elif mode == "数据分析":
    _render_analysis_mode(analysis_scanned)
elif mode == "跑本地回测" and scope == "批量（按标的汇总）":
    _render_batch_run(csv_root, list(divs), workers=workers, quiet=quiet, compound=compound_bt)
elif mode == "跑本地回测":
    union_by: dict[str, dict] = {}
    for div in divs:
        d = str(resolve_typed_dir(csv_root, div))
        for m in _cached_daily_metas(d, _daily_dir_fingerprint(d)):
            stock = str(m.get("stock") or "").strip().upper()
            if not stock:
                continue
            prev = union_by.get(stock)
            if prev is None:
                union_by[stock] = {
                    "stock": stock,
                    "start": m["start"],
                    "end": m["end"],
                    "n": m["n"],
                    "by_div": {div: m},
                }
            else:
                prev["by_div"][div] = m
                if m["start"] < prev["start"]:
                    prev["start"] = m["start"]
                if m["end"] > prev["end"]:
                    prev["end"] = m["end"]
                prev["n"] = max(int(prev.get("n") or 0), int(m.get("n") or 0))
    stock_opts = sorted(union_by)
    col_a, col_b = st.columns([2, 1])
    with col_a:
        selected_csv = None
        pick_stock = ""
        if uploaded is not None:
            tmp = HERE / "_upload_daily.csv"
            tmp.write_bytes(uploaded.getvalue())
            selected_csv = tmp
            st.success("已使用上传文件：%s（只写入第一种复权）" % uploaded.name)
        elif stock_opts:
            pick_stock = st.selectbox("数据源（按标的，复权并集）", stock_opts, index=0)
            first_div = next(iter((union_by[pick_stock].get("by_div") or {})), None)
            if first_div:
                selected_csv = Path(union_by[pick_stock]["by_div"][first_div]["path"])
        else:
            st.warning("所选复权目录无 `*_1d_*.csv`")

    meta = None
    if uploaded is not None and selected_csv and selected_csv.is_file():
        try:
            meta = peek_daily_csv_meta(selected_csv)
        except Exception as e:
            st.error(f"读取行情失败：{e}")
            meta = None
    elif pick_stock and pick_stock in union_by:
        u = union_by[pick_stock]
        meta = {
            "stock": pick_stock,
            "start": u["start"],
            "end": u["end"],
            "n": u["n"],
            "path": str(selected_csv) if selected_csv else "",
        }

    if meta:
        d0 = ymd_to_date(meta["start"])
        d1 = ymd_to_date(meta["end"])
        st.caption(f"标的 **{meta['stock']}** · {meta['n']} 根日线 · {meta['start']}–{meta['end']}")
        c_start, c_end = st.columns(2)
        with c_start:
            start_d = st.date_input("开始时间", value=d0, min_value=d0, max_value=d1, key="bt_start")
        with c_end:
            end_d = st.date_input("结束时间", value=d1, min_value=d0, max_value=d1, key="bt_end")
        if start_d > end_d:
            st.error("开始时间不能晚于结束时间")
        compare_ma = st.checkbox("SMA/EMA 对照", value=False, key="single_compare_ma")
        run_btn = st.button(
            "开始回测",
            type="primary",
            disabled=start_d > end_d or not divs,
        )
    else:
        start_d = end_d = None
        run_btn = False
        compare_ma = False

    if run_btn and meta and start_d and end_d and divs:
        start_s = _fmt_ymd(start_d)
        end_s = _fmt_ymd(end_d)
        stock = str(meta["stock"] or pick_stock or "").strip().upper()
        skipped = []
        by_div: dict[str, dict] = {}
        try:
            run_divs = list(divs)
            if uploaded is not None:
                run_divs = divs[:1]
            bt_ov = {"compound_backtest": True} if compound_bt else None
            for div in run_divs:
                if uploaded is not None:
                    csv_one = selected_csv
                else:
                    csv_one = daily_csv_for_stock(resolve_typed_dir(csv_root, div), stock)
                if csv_one is None or not Path(csv_one).is_file():
                    skipped.append(div)
                    continue
                out_dir = Path(resolve_typed_dir(DEFAULT_REPORT_ROOT, div))
                if compare_ma:
                    packs = {}
                    for kind in ("SMA", "EMA"):
                        with st.spinner(
                            "回测 %s · %s %s %s–%s …"
                            % (dividend_label(div), kind, stock, start_s, end_s)
                        ):
                            log_path = run_backtest(
                                csv_one,
                                start=start_s,
                                end=end_s,
                                stock=stock,
                                out_dir=out_dir,
                                quiet=bool(quiet),
                                ma_type=kind,
                                overrides=bt_ov,
                            )
                        detail = trades_csv_path(log_path)
                        packs[kind] = {
                            "log": str(log_path),
                            "detail": str(detail),
                            "budget": parse_budget_from_log(log_path),
                        }
                    by_div[div] = {
                        "ohlc_csv": str(csv_one),
                        "sma": packs["SMA"],
                        "ema": packs["EMA"],
                        "result": None,
                    }
                else:
                    with st.spinner(
                        "回测 %s · %s %s–%s …" % (dividend_label(div), stock, start_s, end_s)
                    ):
                        log_path = run_backtest(
                            csv_one,
                            start=start_s,
                            end=end_s,
                            stock=stock,
                            out_dir=out_dir,
                            quiet=bool(quiet),
                            overrides=bt_ov,
                        )
                    detail = trades_csv_path(log_path)
                    by_div[div] = {
                        "ohlc_csv": str(csv_one),
                        "sma": None,
                        "ema": None,
                        "result": {
                            "log": str(log_path),
                            "detail": str(detail),
                            "budget": parse_budget_from_log(log_path),
                        },
                    }
            if skipped:
                st.warning("缺行情已跳过：%s" % "、".join(dividend_label(x) for x in skipped))
            if by_div:
                st.session_state["last_div_results"] = {
                    "stock": stock,
                    "start": start_s,
                    "end": end_s,
                    "compare_ma": bool(compare_ma),
                    "by_div": by_div,
                }
                st.session_state.pop("last_result", None)
                st.session_state.pop("last_compare", None)
                if compare_ma:
                    st.success("完成对照 · 已写入所选复权目录")
                else:
                    first = next(iter(by_div.values()))
                    pack = first.get("result") or {}
                    st.success(
                        "完成 · %s 种复权 · log `%s`"
                        % (len(by_div), Path(str(pack.get("log") or "")).name)
                    )
            elif skipped:
                st.error("所选复权都没有该标的行情")
        except Exception:
            st.error("回测失败")
            st.code(traceback.format_exc())

    saved = _coerce_last_div_results()
    if saved:
        st.divider()
        _render_div_results(
            saved.get("by_div") or {},
            compare_ma=bool(saved.get("compare_ma")),
            stock=str(saved.get("stock") or ""),
            start=str(saved.get("start") or ""),
            end=str(saved.get("end") or ""),
            tabs_key="single_div_tabs",
        )

else:
    details = list_detail_csvs(report_dirs or report_dir, include_hist=True)
    labels = [str(p.relative_to(REPO)) if str(p).startswith(str(REPO)) else p.name for p in details]
    if not labels:
        st.warning("未找到操作明细（`hongli_band/回测记录` 或所选 `report/<type>/*操作明细*`）")
    else:
        idx = st.selectbox("已有明细", range(len(labels)), format_func=lambda i: labels[i])
        detail_path = details[idx]
        stock_guess = stock_from_detail_path(detail_path)
        div_guess = dividend_from_detail_path(detail_path)
        ohlc_match = match_daily_csv_for_detail(
            detail_path,
            csv_root,
            fallback_divs=divs,
        )
        daily_all: list[Path] = []
        seen_paths: set[str] = set()

        def _add_daily(p: Path) -> None:
            try:
                key = str(p.resolve())
            except Exception:
                key = str(p)
            if key in seen_paths:
                return
            seen_paths.add(key)
            daily_all.append(p)

        if ohlc_match is not None:
            _add_daily(Path(ohlc_match))
        for d in csv_dirs or [csv_dir]:
            for p in list_daily_csvs(d):
                _add_daily(p)
        opt_keys = [""] + [str(p) for p in daily_all]
        default_idx = 0
        if ohlc_match is not None:
            try:
                want = str(Path(ohlc_match).resolve())
            except Exception:
                want = str(ohlc_match)
            for i, p in enumerate(daily_all):
                try:
                    got = str(p.resolve())
                except Exception:
                    got = str(p)
                if got == want or str(p) == str(ohlc_match):
                    default_idx = i + 1
                    break
        ohlc_opt = st.selectbox(
            "关联日线（可选，画 K 线）",
            options=opt_keys,
            index=min(default_idx, max(0, len(opt_keys) - 1)),
            format_func=lambda k: "（不关联）" if not k else _daily_csv_label(Path(k)),
            key="an_ohlc_%s_%s" % (detail_path.parent.name, detail_path.name),
        )
        ohlc_csv = None
        stock = stock_guess
        d0 = d1 = None
        if ohlc_opt:
            ohlc_csv = Path(ohlc_opt)
            if ohlc_csv.is_file():
                try:
                    meta = peek_daily_csv_meta(ohlc_csv)
                    stock = str(meta.get("stock") or stock_guess or "")
                    d0, d1 = ymd_to_date(meta["start"]), ymd_to_date(meta["end"])
                except Exception as e:
                    st.warning(f"日线读取失败：{e}")
                    ohlc_csv = None
            else:
                ohlc_csv = None
        auto_on = False
        if ohlc_match is not None and ohlc_csv is not None:
            try:
                auto_on = ohlc_csv.resolve() == Path(ohlc_match).resolve()
            except Exception:
                auto_on = str(ohlc_csv) == str(ohlc_match)
        if auto_on:
            st.caption(
                "已按明细关联 %s · %s"
                % (
                    stock_guess or stock or "?",
                    dividend_label(
                        normalize_dividend_type(ohlc_csv.parent.name) or div_guess
                    ),
                )
            )
        elif ohlc_match is None:
            want_div = div_guess or (divs[0] if divs else DEFAULT_DIVIDEND_TYPE)
            st.caption(
                "未找到对应日线，缺 `csv/%s/` 下 %s"
                % (want_div, stock_guess or detail_path.name)
            )

        # 明细自身时间范围
        try:
            raw = load_detail_raw(detail_path)
            time_col = None
            for c in raw.columns:
                if str(c).strip() in ("操作时间", "成交时间", "时间"):
                    time_col = c
                    break
            if time_col is None and raw.shape[1] >= 6:
                time_col = raw.columns[5]
            days = []
            if time_col is not None:
                for v in raw[time_col]:
                    try:
                        days.append(date_to_ymd(str(v)))
                    except Exception:
                        pass
            days = [d for d in days if len(d) == 8]
            if days:
                d0 = d0 or ymd_to_date(min(days))
                d1 = d1 or ymd_to_date(max(days))
        except Exception:
            pass

        if d0 and d1:
            c_start, c_end = st.columns(2)
            with c_start:
                start_d = st.date_input("开始时间", value=d0, key="an_start")
            with c_end:
                end_d = st.date_input("结束时间", value=d1, key="an_end")
            start_s, end_s = _fmt_ymd(start_d), _fmt_ymd(end_d)
        else:
            start_s = end_s = ""
            st.caption("无法推断明细时间范围，将分析全部记录")

        budget = st.number_input("预算（元）", min_value=1000.0, value=50000.0, step=1000.0)
        if st.button("加载分析", type="primary"):
            st.session_state["analyze_only"] = {
                "detail": str(detail_path),
                "budget": float(budget),
                "ohlc_csv": str(ohlc_csv) if ohlc_csv else "",
                "stock": stock,
                "start": start_s,
                "end": end_s,
            }

        ao = st.session_state.get("analyze_only")
        if ao:
            st.divider()
            _render_analysis(
                Path(ao["detail"]),
                budget=float(ao["budget"]),
                ohlc_csv=Path(ao["ohlc_csv"]) if ao.get("ohlc_csv") else None,
                range_start=ao.get("start") or "",
                range_end=ao.get("end") or "",
                stock=ao.get("stock") or "",
            )
