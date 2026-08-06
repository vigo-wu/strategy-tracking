# coding: utf-8
"""QMT 回测日志 → 成交表 + 权益曲线 + 持仓着色 K 线 + Markdown 报告。

用法:
  python generate_report.py --theme hongli_band
  python generate_report.py --log path/to/log.txt --out-dir path/to/dir --tag HlBand
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

COLOR_HOLD = "#e53935"
COLOR_FLAT = "#43a047"
COLOR_BUY_MARK = "#b71c1c"
COLOR_SELL_MARK = "#1b5e20"

REPO_ROOT = Path(__file__).resolve().parents[4]  # scripts → skill → skills → .cursor → repo


def _ymd(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _ts(s: str | None) -> pd.Timestamp | None:
    if not s:
        return None
    return pd.Timestamp(str(s)[:8])


def slice_session(text: str, tag: str, ver: str | None) -> tuple[str, str]:
    """取末次 init 之后的日志段；返回 (seg, ver_found)。"""
    if ver:
        needle = f"{tag} {ver} init"
        idx = text.rfind(needle)
        if idx < 0:
            idx = text.rfind(f"{tag} v")
    else:
        idx = text.rfind(f"{tag} v")
        if idx < 0:
            idx = text.rfind(f"{tag} ")
    if idx < 0:
        return text, "?"
    seg = text[idx:]
    m = re.search(rf"{re.escape(tag)}\s+(v[\d.]+)\s+init", seg)
    return seg, (m.group(1) if m else (ver or "?"))


def parse_meta(seg: str, tag: str) -> dict:
    m = re.search(
        rf"{re.escape(tag)}\s+(v[\d.]+)\s+init\s+(\S+)\s+(\S+)\s+(\S+)\s+"
        r"PERIOD=\s*(\S+)\s+BACKTEST=\s*(\S+)\s+DRY_RUN=\s*(\S+)\s+"
        r"budget=\s*([0-9.]+)"
        r"(?:\s+wMA=\s*(\S+)\s+dMA=\s*(\S+)\s+bias5>=\s*([0-9.]+)\s+"
        r"stop=\s*([0-9.]+)\s+chase<\s*([0-9.]+))?",
        seg,
    )
    if not m:
        return {
            "tag": tag,
            "ver": "?",
            "stock": "?",
            "period": "?",
            "backtest": "?",
            "dry_run": "?",
            "budget": 0.0,
        }
    return {
        "tag": tag,
        "ver": m.group(1),
        "stock": m.group(2),
        "account": m.group(3),
        "account_type": m.group(4),
        "period": m.group(5),
        "backtest": m.group(6),
        "dry_run": m.group(7),
        "budget": float(m.group(8)),
        "wMA": m.group(9),
        "dMA": m.group(10),
        "bias5": m.group(11),
        "stop": m.group(12),
        "chase": m.group(13),
    }


def parse_trades(seg: str, tag: str, stock: str) -> list[dict]:
    """配对 BUY filled / SELL done，附带 signal/label/执行日。"""
    stock_esc = re.escape(stock)
    buys_sig = re.findall(
        rf"BUY by signal=(\S+)\s+label=([^\s]+)\s+all=([^\s]+)\s+"
        rf"signal_day=(\d+)\s+@open=([0-9.]+)\r?\n"
        rf"{re.escape(tag)}\s+BUY BUY[^\n]*\r?\n"
        rf"{re.escape(tag)}\s+BUY filled \{{'shares': (\d+), 'price': ([0-9.]+), "
        rf"'cost': ([0-9.]+), 'opened_at': '(\d+)'\}}",
        seg,
    )
    if not buys_sig:
        # 无 label 的旧格式
        fills = re.findall(
            rf"BUY filled \{{'shares': (\d+), 'price': ([0-9.]+),[^}}]*'opened_at': '(\d+)'\}}",
            seg,
        )
        buys_sig = [("-", "-", "-", f[2][:8], "0", f[0], f[1], "0", f[2]) for f in fills]

    sells_sig = re.findall(
        rf"SELL by signal=(\S+)\s+label=([^\s]+)\s+all=([^\s]+)\s+"
        rf"signal_day=(\d+)\s+@open=([0-9.]+)\r?\n"
        rf"{re.escape(tag)}\s+SELL (\S+)\s+{stock_esc}[^\n]*\r?\n"
        rf"{re.escape(tag)}\s+SELL done (\S+)\s+last=\s*([0-9.]+)\s+"
        rf"cleared \{{'shares': (\d+), 'price': ([0-9.]+)",
        seg,
    )
    sell_exec = []
    for m in re.finditer(
        rf"{re.escape(tag)}\s+(20\d{{6}})[^\n]*\n"
        rf"{re.escape(tag)}\s+SELL by signal=\S+[^\n]*\n"
        rf"{re.escape(tag)}\s+SELL (\S+)\s+{stock_esc}",
        seg,
    ):
        sell_exec.append(m.group(1))
    if not sell_exec:
        for m in re.finditer(
            rf"{re.escape(tag)}\s+(20\d{{6}})[^\n]*\n"
            rf"{re.escape(tag)}\s+SELL (\S+)\s+{stock_esc}",
            seg,
        ):
            sell_exec.append(m.group(1))

    if not sells_sig:
        dones = re.findall(
            rf"SELL done (\S+)\s+last=\s*([0-9.]+)\s+"
            rf"cleared \{{'shares': (\d+), 'price': ([0-9.]+)",
            seg,
        )
        sells_sig = [
            (d[0], d[0], d[0], sell_exec[i] if i < len(sell_exec) else "", "0", d[0], d[0], d[1], d[2], d[3])
            for i, d in enumerate(dones)
        ]

    trades = []
    n = min(len(buys_sig), len(sells_sig))
    for i in range(n):
        b = buys_sig[i]
        s = sells_sig[i]
        b_price = float(b[6])
        s_price = float(s[7]) if len(s) > 7 else float(s[1])
        shares = int(b[5])
        # normalize sell tuple shapes
        if len(s) >= 10:
            s_sig, s_lab, s_all, s_sday, s_open, _sord, _sdone, s_price, s_sh, _bp = (
                s[0], s[1], s[2], s[3], s[4], s[5], s[6], float(s[7]), int(s[8]), float(s[9])
            )
        else:
            s_sig, s_lab, s_sday, s_price = s[0], s[1], s[3], float(s[7]) if len(s) > 7 else float(s[1])
            s_sh = shares
        exec_day = sell_exec[i] if i < len(sell_exec) else s_sday
        open_day = b[8][:8]
        hold_days = None
        try:
            hold_days = (
                datetime.strptime(str(exec_day)[:8], "%Y%m%d")
                - datetime.strptime(open_day, "%Y%m%d")
            ).days
        except Exception:
            pass
        pnl = (s_price - b_price) * shares
        ret = (s_price - b_price) / b_price * 100.0 if b_price else 0.0
        trades.append(
            {
                "i": i + 1,
                "buy_signal": b[0],
                "buy_label": b[1],
                "buy_signal_day": b[3],
                "buy_open_day": open_day,
                "buy_price": b_price,
                "shares": shares,
                "cost": float(b[7]) if b[7] not in ("0", 0) else round(b_price * shares, 2),
                "sell_signal": s_sig,
                "sell_label": s_lab,
                "sell_signal_day": s_sday,
                "sell_exec_day": str(exec_day)[:8] if exec_day else "",
                "sell_price": s_price,
                "hold_calendar_days": hold_days,
                "ret_pct": ret,
                "pnl": pnl,
            }
        )
    return trades


def parse_diag(seg: str, tag: str) -> dict:
    dates = re.findall(rf"{re.escape(tag)}\s+(20\d{{6}})\s+", seg)
    last = re.findall(
        rf"{re.escape(tag)}\s+(20\d{{6}}).*hold=(\w+)\s+ret=(\S+)\s+pe=(\w+)\s+px=(\w+)\s+bt_held=(\d+)",
        seg,
    )
    return {
        "first_bar": dates[0] if dates else None,
        "last_bar": dates[-1] if dates else None,
        "last_state": last[-1] if last else None,
        "buy_skip": seg.count("buy skip"),
        "sell_skip": seg.count("sell skip"),
        "sticky_pe": len(re.findall(r"hold=True[^\n]*pe=True", seg)),
        "sticky_px": len(re.findall(r"hold=False[^\n]*px=True", seg)),
        "interrupt_noise": "KeyboardInterrupt" in seg[:2000] or False,
    }


def compute_stats(meta: dict, trades: list[dict], diag: dict) -> dict:
    rets = [t["ret_pct"] for t in trades]
    pnls = [t["pnl"] for t in trades]
    wins = [t for t in trades if t["ret_pct"] > 0]
    losses = [t for t in trades if t["ret_pct"] <= 0]
    buy_c = Counter(t["buy_signal"] for t in trades)
    sell_c = Counter(t["sell_signal"] for t in trades)
    return {
        "meta": meta,
        "diag": diag,
        "n_buy": len(trades),
        "n_sell": len(trades),
        "sum_pnl": round(sum(pnls), 2) if pnls else 0.0,
        "avg_ret": round(sum(rets) / len(rets), 2) if rets else 0.0,
        "win_n": len(wins),
        "loss_n": len(losses),
        "win_rate": round(len(wins) / len(rets) * 100, 1) if rets else 0.0,
        "max_win": round(max(rets), 2) if rets else 0.0,
        "max_loss": round(min(rets), 2) if rets else 0.0,
        "gross_profit": round(sum(t["pnl"] for t in wins), 2),
        "gross_loss": round(sum(t["pnl"] for t in losses), 2),
        "buy_dist": dict(buy_c),
        "sell_dist": dict(sell_c),
        "trades": trades,
    }


def equity_curve(trades: list[dict], budget: float) -> pd.DataFrame:
    """按卖出执行日累加已实现盈亏 → 权益 = budget + cum_pnl。"""
    rows = [{"date": None, "equity": budget, "cum_pnl": 0.0, "trade_i": 0}]
    cum = 0.0
    for t in trades:
        d = t.get("sell_exec_day") or t.get("sell_signal_day")
        cum += t["pnl"]
        rows.append(
            {
                "date": _ts(d),
                "equity": budget + cum,
                "cum_pnl": cum,
                "trade_i": t["i"],
                "ret_pct": t["ret_pct"],
                "pnl": t["pnl"],
            }
        )
    return pd.DataFrame(rows)


def fetch_ohlc(stock: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    code = stock.split(".")[0]
    mkt = "sh" if stock.upper().endswith(".SH") else "sz"
    df = None
    try:
        import akshare as ak

        raw = ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
        )
        df = raw.rename(
            columns={
                "日期": "Date",
                "开盘": "Open",
                "最高": "High",
                "最低": "Low",
                "收盘": "Close",
                "成交量": "Volume",
            }
        ).copy()
    except Exception as e:
        print("em fetch failed:", e, file=sys.stderr)

    if df is None or getattr(df, "empty", True):
        try:
            import akshare as ak

            raw = ak.fund_etf_hist_sina(symbol=f"{mkt}{code}")
            df = raw.rename(
                columns={
                    "date": "Date",
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume",
                }
            ).copy()
        except Exception as e:
            print("sina fetch failed:", e, file=sys.stderr)
            return pd.DataFrame()

    df["Date"] = pd.to_datetime(df["Date"])
    for c in ("Open", "High", "Low", "Close", "Volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Close"]).set_index("Date").sort_index()
    return df.loc[(df.index >= start) & (df.index <= end)]


def nearest_bar(df: pd.DataFrame, d: pd.Timestamp | None):
    if d is None or df.empty:
        return None
    if d in df.index:
        return d
    idx = int(df.index.searchsorted(d))
    if idx >= len(df.index):
        return df.index[-1]
    if idx == 0:
        return df.index[0]
    a, b = df.index[idx - 1], df.index[min(idx, len(df.index) - 1)]
    return a if abs((a - d).days) <= abs((b - d).days) else b


def holding_mask(df: pd.DataFrame, trades: list[dict]) -> np.ndarray:
    held = np.zeros(len(df), dtype=bool)
    for t in trades:
        b = nearest_bar(df, _ts(t["buy_open_day"]))
        s = nearest_bar(df, _ts(t["sell_exec_day"] or t["sell_signal_day"]))
        if b is None or s is None:
            continue
        if s < b:
            b, s = s, b
        held |= (df.index >= b) & (df.index <= s)
    return held


def plot_equity(eq: pd.DataFrame, out: Path, title: str):
    fig, ax = plt.subplots(figsize=(12, 4.5))
    pts = eq.dropna(subset=["date"])
    if pts.empty:
        ax.text(0.5, 0.5, "no closed trades", ha="center")
    else:
        ax.plot(pts["date"], pts["equity"], color="#1565c0", linewidth=2, marker="o", markersize=5)
        ax.axhline(eq.iloc[0]["equity"], color="#9e9e9e", linestyle="--", linewidth=1)
        ax.fill_between(pts["date"], eq.iloc[0]["equity"], pts["equity"], alpha=0.12, color="#1565c0")
    ax.set_title(title)
    ax.set_ylabel("权益 (元)")
    ax.grid(True, linestyle=":", alpha=0.5)
    fig.autofmt_xdate()
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


def plot_kline(
    df: pd.DataFrame,
    trades: list[dict],
    held: np.ndarray,
    out: Path,
    title: str,
):
    if df.empty:
        print("skip kline: empty OHLC", file=sys.stderr)
        return
    fig, (ax, axv) = plt.subplots(
        2, 1, figsize=(14, 7), sharex=True, gridspec_kw={"height_ratios": [3.2, 1], "hspace": 0.05}
    )
    width = 0.6
    for i, (_, row) in enumerate(df.iterrows()):
        c = COLOR_HOLD if held[i] else COLOR_FLAT
        o, h, l, cl = row["Open"], row["High"], row["Low"], row["Close"]
        ax.plot([i, i], [l, h], color=c, linewidth=0.9, zorder=2)
        bottom = min(o, cl)
        height = abs(cl - o)
        if height < 1e-9:
            height = max((h - l) * 0.02, 1e-4)
            bottom = cl - height / 2
        ax.add_patch(
            plt.Rectangle(
                (i - width / 2, bottom), width, height, facecolor=c, edgecolor=c, linewidth=0.6, zorder=3
            )
        )
    ax.set_xlim(-1, len(df))

    date_to_i = {d: i for i, d in enumerate(df.index)}
    for t in trades:
        bd = nearest_bar(df, _ts(t["buy_open_day"]))
        sd = nearest_bar(df, _ts(t["sell_exec_day"] or t["sell_signal_day"]))
        if bd is not None and bd in date_to_i:
            i = date_to_i[bd]
            ax.annotate(
                "B",
                xy=(i, t["buy_price"]),
                xytext=(0, 10),
                textcoords="offset points",
                ha="center",
                va="bottom",
                color=COLOR_BUY_MARK,
                fontsize=9,
                fontweight="bold",
                zorder=5,
            )
        if sd is not None and sd in date_to_i:
            i = date_to_i[sd]
            ax.annotate(
                "S",
                xy=(i, t["sell_price"]),
                xytext=(0, -10),
                textcoords="offset points",
                ha="center",
                va="top",
                color=COLOR_SELL_MARK,
                fontsize=9,
                fontweight="bold",
                zorder=5,
            )

    x = np.arange(len(df))
    axv.bar(x, df["Volume"].values, width=0.7, color=[COLOR_HOLD if h else COLOR_FLAT for h in held], alpha=0.75)
    tick_idx = np.linspace(0, len(df) - 1, min(10, len(df)), dtype=int)
    axv.set_xticks(tick_idx)
    axv.set_xticklabels([df.index[i].strftime("%Y-%m") for i in tick_idx])
    ax.set_ylabel("Price")
    axv.set_ylabel("Volume")
    ax.set_title(title, fontsize=12, pad=10)
    ax.grid(True, linestyle=":", alpha=0.45)
    axv.grid(True, linestyle=":", alpha=0.35)
    ax.legend(
        handles=[
            mpatches.Patch(color=COLOR_HOLD, label="持仓区间 K 线"),
            mpatches.Patch(color=COLOR_FLAT, label="空仓区间 K 线"),
            Line2D(
                [0],
                [0],
                marker="$B$",
                color=COLOR_BUY_MARK,
                markerfacecolor=COLOR_BUY_MARK,
                markersize=12,
                linestyle="None",
                label="B 买入",
            ),
            Line2D(
                [0],
                [0],
                marker="$S$",
                color=COLOR_SELL_MARK,
                markerfacecolor=COLOR_SELL_MARK,
                markersize=12,
                linestyle="None",
                label="S 卖出",
            ),
        ],
        loc="upper left",
        fontsize=8,
        framealpha=0.9,
    )
    fig.savefig(out, dpi=140, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


def write_trades_csv(trades: list[dict], out: Path):
    if not trades:
        return
    keys = list(trades[0].keys())
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for t in trades:
            w.writerow(t)
    print("wrote", out)


def render_markdown(stats: dict, paths: dict, title: str) -> str:
    m = stats["meta"]
    d = stats["diag"]
    trades = stats["trades"]
    today = date.today().isoformat()
    wr = stats["win_rate"]
    lines = [
        f"# {title}",
        "",
        "| 项 | 内容 |",
        "| :--- | :--- |",
        f"| 策略版本 | **{m.get('ver')}** |",
        f"| 标的 | **{m.get('stock')}** |",
        f"| 主图周期 | {m.get('period')} |",
        f"| 回测区间（日志 bar） | **{_ymd(d['first_bar']) if d.get('first_bar') else '?'} ~ {_ymd(d['last_bar']) if d.get('last_bar') else '?'}** |",
        f"| 单笔预算 | {m.get('budget'):,.0f} 元 |",
        f"| DRY_RUN | {m.get('dry_run')} |",
        f"| 日志来源 | `{paths.get('log_name', 'log.txt')}` |",
        f"| 报告日期 | {today} |",
        f"| 生成方式 | `qmt-backtest-report` 自动生成 |",
        "",
        "---",
        "",
        "## 1. 结论摘要",
        "",
        f"本轮回测 **{stats['n_buy']} 买 {stats['n_sell']} 卖**，粗算合计盈亏约 "
        f"**{stats['sum_pnl']:+,.2f} 元**"
        f"（相对预算 {m.get('budget'):,.0f} 约 **{stats['sum_pnl']/m['budget']*100 if m.get('budget') else 0:+.1f}%** 累计交易毛利）。"
        f"胜率 **{stats['win_n']}/{stats['n_buy']}（{wr}%）**，"
        f"最大单笔 **{stats['max_win']:+.2f}%** / **{stats['max_loss']:+.2f}%**。",
        "",
        f"工程：`buy skip`={d.get('buy_skip', 0)}，`sell skip`={d.get('sell_skip', 0)}；"
        f"pe 粘滞={d.get('sticky_pe', 0)}，px 粘滞={d.get('sticky_px', 0)}。",
        "",
        "---",
        "",
        "## 2. 回测环境与参数",
        "",
        "```",
        f"{m.get('tag')} {m.get('ver')} init {m.get('stock')} PERIOD={m.get('period')} "
        f"BACKTEST={m.get('backtest')} DRY_RUN={m.get('dry_run')} budget={m.get('budget')}",
        f"wMA={m.get('wMA')} dMA={m.get('dMA')} bias5>={m.get('bias5')} stop={m.get('stop')} chase<{m.get('chase')}",
        "```",
        "",
        "---",
        "",
        "## 3. 成交明细",
        "",
        "盈亏按「卖出价 − 买入价」× 股数粗算，**未单独拆佣金印花税**。",
        "",
        "| # | 开仓日 | 买点 | 买入价 | 股数 | 平仓日 | 卖点 | 卖出价 | 持仓(日) | 收益% | 盈亏(元) |",
        "| :---: | :--- | :--- | ---: | ---: | :--- | :--- | ---: | ---: | ---: | ---: |",
    ]
    for t in trades:
        lines.append(
            f"| {t['i']} | {t['buy_open_day']} | {t['buy_label']} | {t['buy_price']:.4f} | {t['shares']} | "
            f"{t['sell_exec_day']} | {t['sell_label']} | {t['sell_price']:.4f} | "
            f"{t['hold_calendar_days'] if t['hold_calendar_days'] is not None else '-'} | "
            f"{t['ret_pct']:+.2f} | {t['pnl']:+.2f} |"
        )
    lines += [
        "",
        f"**合计粗算盈亏：{stats['sum_pnl']:+,.2f} 元**",
        "",
        "---",
        "",
        "## 4. 绩效与信号分布",
        "",
        "| 指标 | 数值 |",
        "| :--- | :--- |",
        f"| 完整轮次 | {stats['n_buy']} |",
        f"| 胜 / 负 | {stats['win_n']} / {stats['loss_n']} |",
        f"| 胜率 | {wr}% |",
        f"| 平均单笔收益 | {stats['avg_ret']:+.2f}% |",
        f"| 最大单笔盈利 | {stats['max_win']:+.2f}% |",
        f"| 最大单笔亏损 | {stats['max_loss']:+.2f}% |",
        f"| 盈利合计 / 亏损合计 | {stats['gross_profit']:+.0f} / {stats['gross_loss']:+.0f} |",
        "",
        "### 买点分布",
        "",
        "| 信号 | 次数 |",
        "| :--- | :---: |",
    ]
    for k, v in stats["buy_dist"].items():
        lines.append(f"| `{k}` | {v} |")
    lines += [
        "",
        "### 卖点分布",
        "",
        "| 信号 | 次数 |",
        "| :--- | :---: |",
    ]
    for k, v in stats["sell_dist"].items():
        lines.append(f"| `{k}` | {v} |")
    lines += [
        "",
        "---",
        "",
        "## 5. 图表",
        "",
        f"- 权益曲线：[`{paths['equity'].name}`](./{paths['equity'].name})",
        f"- 持仓着色 K 线：[`{paths['kline'].name}`](./{paths['kline'].name})",
        f"- 成交 CSV：[`{paths['csv'].name}`](./{paths['csv'].name})",
        "",
        f"![权益曲线](./{paths['equity'].name})",
        "",
        f"![K线](./{paths['kline'].name})",
        "",
        "---",
        "",
        "## 6. 附录",
        "",
        f"- 原始日志：[`../{paths.get('log_name', 'log.txt')}`](../{paths.get('log_name', 'log.txt')})",
        f"- 统计 JSON：[`{paths['json'].name}`](./{paths['json'].name})",
        f"- 深度解读（可选）：同目录下人工笔记如 `r1.md`",
        "",
        "*本报告由 qmt-backtest-report 自动生成，仅供策略研发对照，不构成投资建议。*",
        "",
    ]
    return "\n".join(lines)


def resolve_theme(theme: str) -> Path:
    p = Path(theme)
    if p.is_dir():
        return p.resolve()
    cand = REPO_ROOT / theme
    if cand.is_dir():
        return cand.resolve()
    raise SystemExit(f"theme dir not found: {theme}")


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser(description="QMT backtest log → report artifacts")
    ap.add_argument("--theme", help="主题目录名或路径，如 hongli_band")
    ap.add_argument("--log", help="log.txt 路径")
    ap.add_argument("--out-dir", help="输出目录；默认 <主题>/report/")
    ap.add_argument("--tag", default=None, help="日志前缀，如 HlBand；默认从 init 行推断")
    ap.add_argument("--ver", default=None, help="如 v1.2；默认取末次 init")
    ap.add_argument("--title", default=None, help="报告标题")
    ap.add_argument("--no-kline", action="store_true", help="跳过行情拉取与 K 线")
    args = ap.parse_args(argv)

    if args.theme:
        theme_dir = resolve_theme(args.theme)
        log_path = Path(args.log).resolve() if args.log else theme_dir / "log.txt"
        out_dir = Path(args.out_dir).resolve() if args.out_dir else theme_dir / "report"
    elif args.log:
        log_path = Path(args.log).resolve()
        out_dir = Path(args.out_dir).resolve() if args.out_dir else log_path.parent / "report"
    else:
        raise SystemExit("需要 --theme 或 --log")

    out_dir.mkdir(parents=True, exist_ok=True)

    text = log_path.read_text(encoding="utf-8", errors="ignore")
    tag = args.tag
    if not tag:
        m = re.search(r"^(\w+)\s+v[\d.]+\s+init\s+", text, re.M)
        # 优先末次
        all_m = list(re.finditer(r"(\w+)\s+(v[\d.]+)\s+init\s+", text))
        if all_m:
            tag = all_m[-1].group(1)
        elif m:
            tag = m.group(1)
        else:
            tag = "HlBand"

    seg, ver = slice_session(text, tag, args.ver)
    meta = parse_meta(seg, tag)
    if args.ver:
        meta["ver"] = args.ver
    stock = meta.get("stock") or "561580.SH"
    trades = parse_trades(seg, tag, stock)
    diag = parse_diag(seg, tag)
    # interrupt 噪声常在会话前
    diag["interrupt_noise"] = "KeyboardInterrupt" in text[:3000]
    stats = compute_stats(meta, trades, diag)

    prefix = tag.lower()
    paths = {
        "equity": out_dir / f"{prefix}_equity.png",
        "kline": out_dir / f"{prefix}_trades_kline.png",
        "csv": out_dir / f"{prefix}_trades.csv",
        "json": out_dir / f"{prefix}_report_stats.json",
        "md": out_dir / "回测分析报告.md",
        "log_name": log_path.name,
    }

    eq = equity_curve(trades, float(meta.get("budget") or 50000))
    plot_equity(
        eq,
        paths["equity"],
        f"{tag} {meta.get('ver')} | {stock} | 权益曲线（预算+已实现盈亏）",
    )

    if not args.no_kline and trades:
        start = min(_ts(t["buy_open_day"]) for t in trades) - pd.Timedelta(days=30)
        end = max(_ts(t["sell_exec_day"] or t["sell_signal_day"]) for t in trades) + pd.Timedelta(days=15)
        df = fetch_ohlc(stock, start, end)
        held = holding_mask(df, trades) if not df.empty else np.array([])
        print("bars", len(df), "held", int(held.sum()) if len(held) else 0)
        plot_kline(
            df,
            trades,
            held,
            paths["kline"],
            f"{tag} {meta.get('ver')} | {stock} | 红=持仓(买→卖) 绿=空仓 ▲买 ▼卖",
        )
    elif args.no_kline:
        print("skip kline (--no-kline)")

    write_trades_csv(trades, paths["csv"])
    paths["json"].write_text(json.dumps(stats, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("wrote", paths["json"])

    title = args.title or f"{tag} 回测分析报告"
    md = render_markdown(stats, paths, title)
    paths["md"].write_text(md, encoding="utf-8")
    print("wrote", paths["md"])
    print(
        f"done: trades={len(trades)} sum_pnl={stats['sum_pnl']:+.2f} win_rate={stats['win_rate']}%"
    )


if __name__ == "__main__":
    main()
