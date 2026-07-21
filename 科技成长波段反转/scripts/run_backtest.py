"""
历史回测：复现 model.md 选股公式 + 第四节出场规则。
池子：创业板(300*) + 科创板(688*)；不做历史市值过滤（数据源限制，结果会略宽于实盘）。
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import baostock as bs
import numpy as np
import pandas as pd

THEME_ROOT = Path(__file__).resolve().parents[1]  # …/科技成长波段反转
REPO_ROOT = THEME_ROOT.parent
DATA_DIR = REPO_ROOT / "data" / "daily"  # 仓库级共享日线缓存
OUT_DIR = THEME_ROOT / "output"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

# 回测区间（信号日起点）；日线多取 260+ 交易日预热
BT_START = "2023-01-01"
BT_END = "2026-07-20"
HIST_START = "2021-06-01"


@dataclass
class Trade:
    code: str
    name: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    stop_line: float
    hold_days: int
    ret_pct: float
    exit_reason: str
    max_dd_pct: float
    took_partial: bool


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def list_tech_stocks() -> pd.DataFrame:
    """当前存续的 300/688 列表（含名称）。"""
    rs = bs.query_stock_basic()
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    # code, code_name, ipoDate, outDate, type, status
    df = pd.DataFrame(
        rows,
        columns=["code", "code_name", "ipoDate", "outDate", "type", "status"],
    )
    # baostock code: sh.688xxx / sz.300xxx
    mask = df["code"].str.contains(r"(?:sh\.688|sz\.300)", regex=True) & (df["type"] == "1")
    # status 1=上市
    if "status" in df.columns:
        mask &= df["status"] == "1"
    out = df.loc[mask, ["code", "code_name", "ipoDate"]].copy()
    out["code6"] = out["code"].str[-6:]
    out["name"] = out["code_name"]
    return out.reset_index(drop=True)


def download_one(bs_code: str, start: str, end: str) -> pd.DataFrame | None:
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,volume,turn,tradestatus",
        start_date=start,
        end_date=end,
        frequency="d",
        adjustflag="2",
    )
    if rs.error_code != "0":
        return None
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return None
    df = pd.DataFrame(
        rows, columns=["date", "open", "high", "low", "close", "vol", "turn", "tradestatus"]
    )
    for c in ("open", "high", "low", "close", "vol", "turn"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["tradestatus"] == "1"]
    df = df.dropna(subset=["close", "vol"])
    df = df[df["vol"] > 0].reset_index(drop=True)
    return df


def ensure_cache(universe: pd.DataFrame, start: str, end: str, force: bool = False) -> None:
    lg = bs.login()
    print("baostock login:", lg.error_code, lg.error_msg)
    try:
        total = len(universe)
        for i, row in universe.iterrows():
            code6 = row["code6"]
            path = DATA_DIR / f"{code6}.csv"
            if path.exists() and not force:
                # 若缓存末日已覆盖 end，跳过
                try:
                    old = pd.read_csv(path, usecols=["date"])
                    if not old.empty and str(old["date"].iloc[-1])[:10] >= end:
                        continue
                except Exception:
                    pass
            if i % 50 == 0 or i == 0:
                print(f"  下载日线 {i+1}/{total} {code6} {row['name']}")
            df = download_one(row["code"], start, end)
            if df is not None and len(df) > 0:
                df.to_csv(path, index=False)
            time.sleep(0.02)
    finally:
        bs.logout()
        print("logout")


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["ma5"] = d["close"].rolling(5).mean()
    d["ma10"] = d["close"].rolling(10).mean()
    d["ma20"] = d["close"].rolling(20).mean()
    d["mavol5"] = d["vol"].rolling(5).mean()
    d["mavol60"] = d["vol"].rolling(60).mean()
    d["high_3m"] = d["high"].rolling(60).max()
    d["dif"] = ema(d["close"], 12) - ema(d["close"], 26)
    d["dea"] = ema(d["dif"], 9)
    # BOLL(20,2)
    mid = d["close"].rolling(20).mean()
    std = d["close"].rolling(20).std()
    d["boll_upper"] = mid + 2 * std
    d["pct"] = d["close"] / d["close"].shift(1)
    d["vol_ratio"] = d["vol"] / d["vol"].shift(1)
    return d


def signal_mask(d: pd.DataFrame) -> pd.Series:
    """向量化信号（与通达信公式一致）。"""
    # 地量：过去5日至少3日 vol < mavol60*0.4
    low = (d["vol"] < d["mavol60"] * 0.4).astype(int)
    low_vol = low.rolling(5).sum() >= 3

    dif, dea = d["dif"], d["dea"]
    prev_dif, prev_dea = dif.shift(1), dea.shift(1)
    cross = (prev_dif <= prev_dea) & (dif > dea)
    macd_ok = (dif < 0) & (cross | ((dif > dea) & (dif > prev_dif)))

    ma_min = pd.concat([d["ma5"], d["ma10"], d["ma20"]], axis=1).min(axis=1)
    one_pierce = (
        (d["close"] > d["ma5"])
        & (d["close"] > d["ma10"])
        & (d["close"] > d["ma20"])
        & (d["open"] < ma_min)
    )
    drop_ok = (d["high_3m"] - d["close"]) / d["high_3m"] * 100 >= 25
    big_sun = d["pct"] >= 1.045
    volume_bomb = (d["vol_ratio"] >= 2.3) & (d["vol"] > d["mavol5"])
    bars_ok = pd.Series(np.arange(len(d)) >= 259, index=d.index)

    return drop_ok & low_vol & macd_ok & one_pierce & big_sun & volume_bomb & bars_ok


def simulate_trade(d: pd.DataFrame, entry_i: int) -> dict | None:
    """
    从信号日 entry_i 尾盘买入。
    出场：R1 破起爆开盘；R2 半仓止盈；R3 余仓破 MA10；R4 满 20 个交易日。
    收益按仓位加权。
    """
    if entry_i >= len(d) - 1:
        return None

    entry = d.iloc[entry_i]
    entry_price = float(entry["close"])
    stop_line = float(entry["open"])
    if entry_price <= 0:
        return None

    pos = 1.0
    realized = 0.0
    took_partial = False
    peak = entry_price
    max_dd = 0.0
    exit_price = entry_price
    exit_i = entry_i
    reason = "R4"

    # 最多再持有 20 个交易日（含信号日则到 entry_i+19）
    last_i = min(entry_i + 19, len(d) - 1)

    for j in range(entry_i + 1, last_i + 1):
        row = d.iloc[j]
        px = float(row["close"])
        peak = max(peak, float(row["high"]))
        dd = (peak - px) / peak * 100
        max_dd = max(max_dd, dd)
        hold_days = j - entry_i
        profit = (px / entry_price - 1) * 100

        # R1 硬止损：收盘跌破起爆开盘价
        if px < stop_line:
            realized += pos * (px / entry_price - 1)
            pos = 0.0
            exit_price = px
            exit_i = j
            reason = "R1"
            break

        # R2：约 1 周、浮盈≥15%、触 BOLL 上轨、换手>20% → 减仓 50%
        turn = float(row["turn"]) if not np.isnan(row["turn"]) else 0.0
        if (
            (not took_partial)
            and hold_days >= 5
            and profit >= 15
            and px >= float(row["boll_upper"])
            and turn > 20
        ):
            realized += 0.5 * (px / entry_price - 1)
            pos = 0.5
            took_partial = True

        # R3：趋势跟随段，收盘破 MA10（全仓或余仓）
        # 未做半仓前也可用 MA10 保护？手册写的是「剩余 50%」跟 MA10；
        # 未触发 R2 时仍以 R1/R4 为主，避免过早被洗。仅在已减仓或持股≥10 日后启用 MA10。
        ma10 = float(row["ma10"])
        use_ma10 = took_partial or hold_days >= 10
        if use_ma10 and px < ma10:
            realized += pos * (px / entry_price - 1)
            pos = 0.0
            exit_price = px
            exit_i = j
            reason = "R3"
            break

        exit_price = px
        exit_i = j
        reason = "R4"

    if pos > 0:
        # 到期或循环结束清仓
        realized += pos * (exit_price / entry_price - 1)
        pos = 0.0
        if reason not in ("R1", "R3"):
            reason = "R4"

    ret_pct = realized * 100
    return {
        "entry_date": str(entry["date"])[:10],
        "exit_date": str(d.iloc[exit_i]["date"])[:10],
        "entry_price": round(entry_price, 3),
        "exit_price": round(float(exit_price), 3),
        "stop_line": round(stop_line, 3),
        "hold_days": int(exit_i - entry_i),
        "ret_pct": round(ret_pct, 2),
        "exit_reason": reason,
        "max_dd_pct": round(max_dd, 2),
        "took_partial": took_partial,
    }


def backtest_symbol(code6: str, name: str, bt_start: str, bt_end: str) -> list[Trade]:
    path = DATA_DIR / f"{code6}.csv"
    if not path.exists():
        return []
    raw = pd.read_csv(path)
    if len(raw) < 280:
        return []
    d = add_indicators(raw)
    sig = signal_mask(d)

    trades: list[Trade] = []
    i = 0
    n = len(d)
    while i < n:
        if not bool(sig.iloc[i]):
            i += 1
            continue
        dt = str(d.iloc[i]["date"])[:10]
        if dt < bt_start or dt > bt_end:
            i += 1
            continue
        # ST 名称粗滤
        if "ST" in str(name).upper():
            i += 1
            continue

        result = simulate_trade(d, i)
        if result is None:
            i += 1
            continue
        trades.append(
            Trade(
                code=code6,
                name=name,
                **result,
            )
        )
        # 持仓期内不再开新仓：跳到离场日之后
        exit_date = result["exit_date"]
        j = i + 1
        while j < n and str(d.iloc[j]["date"])[:10] <= exit_date:
            j += 1
        i = j
    return trades


def summarize(trades: list[Trade]) -> dict:
    if not trades:
        return {"trade_count": 0}
    rets = np.array([t.ret_pct for t in trades], dtype=float)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    by_reason = {}
    for t in trades:
        by_reason[t.exit_reason] = by_reason.get(t.exit_reason, 0) + 1

    # 简易资金曲线：每笔等权、不重叠资金占用假设（信号不并行计复利）
    # 改为：按入场日排序，同日多票等权平均后再串联（近似）
    df = pd.DataFrame([asdict(t) for t in trades])
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    daily = df.groupby("entry_date")["ret_pct"].mean().sort_index() / 100.0
    equity = (1 + daily).cumprod()
    total_ret = float(equity.iloc[-1] - 1) * 100 if len(equity) else 0.0

    return {
        "trade_count": len(trades),
        "win_count": int((rets > 0).sum()),
        "loss_count": int((rets <= 0).sum()),
        "win_rate_pct": round(float((rets > 0).mean() * 100), 2),
        "avg_ret_pct": round(float(rets.mean()), 2),
        "median_ret_pct": round(float(np.median(rets)), 2),
        "avg_win_pct": round(float(wins.mean()), 2) if len(wins) else None,
        "avg_loss_pct": round(float(losses.mean()), 2) if len(losses) else None,
        "max_ret_pct": round(float(rets.max()), 2),
        "min_ret_pct": round(float(rets.min()), 2),
        "avg_hold_days": round(float(np.mean([t.hold_days for t in trades])), 1),
        "exit_reason_counts": by_reason,
        "chain_equal_weight_total_ret_pct": round(total_ret, 2),
        "profit_factor": round(
            float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else None,
            2,
        )
        if len(losses) and float(losses.sum()) != 0
        else None,
    }


def main() -> None:
    print("=== 登录并获取股票池 ===")
    bs.login()
    try:
        universe = list_tech_stocks()
    finally:
        bs.logout()
    print(f"股票池: {len(universe)} 只（300/688）")

    print("=== 下载/刷新日线缓存 ===")
    ensure_cache(universe, HIST_START, BT_END, force=False)

    print("=== 回测中 ===")
    all_trades: list[Trade] = []
    for i, row in universe.iterrows():
        if i % 100 == 0:
            print(f"  回测进度 {i+1}/{len(universe)}")
        all_trades.extend(
            backtest_symbol(row["code6"], row["name"], BT_START, BT_END)
        )

    summary = summarize(all_trades)
    summary.update(
        {
            "bt_start": BT_START,
            "bt_end": BT_END,
            "universe_size": len(universe),
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "notes": [
                "入场：信号日收盘（尾盘一次到位）",
                "R1：收盘<起爆开盘价；R2：≥5日且盈≥15%且触BOLL上轨且换手>20%减半仓",
                "R3：已减仓或持股≥10日后收盘<MA10；R4：满20个交易日",
                "未做历史市值50-500亿过滤；未做概念/催化剂过滤",
                "同标的持仓期不叠加新信号；同日多票收益按等权均值再串联",
            ],
        }
    )

    trades_df = pd.DataFrame([asdict(t) for t in all_trades])
    stamp = f"{BT_START}_{BT_END}".replace("-", "")
    trades_path = OUT_DIR / f"backtest_trades_{stamp}.csv"
    summary_path = OUT_DIR / f"backtest_summary_{stamp}.json"
    trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # 可读 Markdown 报告
    md = [
        f"# 科技成长波段模型 · 历史回测报告",
        "",
        f"- **区间**：{BT_START} ~ {BT_END}",
        f"- **股票池**：创业板+科创板，共 {len(universe)} 只",
        f"- **信号数/交易数**：{summary.get('trade_count', 0)}",
        f"- **胜率**：{summary.get('win_rate_pct')}%",
        f"- **平均单笔收益**：{summary.get('avg_ret_pct')}%",
        f"- **中位数收益**：{summary.get('median_ret_pct')}%",
        f"- **平均持股交易日**：{summary.get('avg_hold_days')}",
        f"- **盈亏比(profit factor)**：{summary.get('profit_factor')}",
        f"- **等权串联近似总收益**：{summary.get('chain_equal_weight_total_ret_pct')}%",
        f"- **出场分布**：{summary.get('exit_reason_counts')}",
        "",
        "## 说明",
        "",
    ]
    for n in summary["notes"]:
        md.append(f"- {n}")
    md += [
        "",
        f"明细：`{trades_path.name}`",
        f"摘要：`{summary_path.name}`",
        "",
    ]
    def _table(frame: pd.DataFrame) -> str:
        cols = ["code", "name", "entry_date", "exit_date", "ret_pct", "hold_days", "exit_reason"]
        try:
            return frame[cols].to_markdown(index=False)
        except Exception:
            return "```\n" + frame[cols].to_string(index=False) + "\n```"

    if len(trades_df):
        md.append("## 收益最高 10 笔")
        md.append("")
        md.append(_table(trades_df.sort_values("ret_pct", ascending=False).head(10)))
        md.append("")
        md.append("## 收益最低 10 笔")
        md.append("")
        md.append(_table(trades_df.sort_values("ret_pct", ascending=True).head(10)))

    report_path = OUT_DIR / f"backtest_report_{stamp}.md"
    report_path.write_text("\n".join(md), encoding="utf-8")

    print("\n======== 回测摘要 ========")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"报告: {report_path}")
    print(f"明细: {trades_path}")


if __name__ == "__main__":
    main()
