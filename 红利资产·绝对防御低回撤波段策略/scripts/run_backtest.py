"""
红利资产·绝对防御低回撤波段 · 历史回测（model.md 公式 + 第四节出场）。
池子近似：主板宽池 + 换手地量 + 均线支撑 + 右侧企稳；
中证红利/股息率未过滤，结果偏宽，需结合实盘成分解读。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import baostock as bs
import numpy as np
import pandas as pd

THEME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = THEME_ROOT.parent
DATA_DIR = REPO_ROOT / "data" / "daily"
OUT_DIR = THEME_ROOT / "output"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

BT_START = "2023-01-01"
BT_END = "2026-07-20"
HIST_START = "2021-01-01"
MIN_AMOUNT = 1.5e8
MAX_HOLD_DAYS = 20  # 约 4 周


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


def sma_tdx(series: pd.Series, n: int, m: int) -> pd.Series:
    out = []
    y: float | None = None
    for x in series:
        if pd.isna(x):
            out.append(np.nan)
            continue
        xf = float(x)
        if y is None or pd.isna(y):
            y = xf
        else:
            y = (m * xf + (n - m) * y) / n
        out.append(y)
    return pd.Series(out, index=series.index)


def list_main_board() -> pd.DataFrame:
    rs = bs.query_stock_basic()
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(
        rows, columns=["code", "code_name", "ipoDate", "outDate", "type", "status"]
    )
    mask = (
        df["code"].str.contains(r"(?:sh\.60|sz\.00)", regex=True)
        & (df["type"] == "1")
        & (df["status"] == "1")
        & (~df["code_name"].str.contains("ST", case=False, na=False))
    )
    out = df.loc[mask, ["code", "code_name"]].copy()
    out["code6"] = out["code"].str[-6:]
    out["name"] = out["code_name"]
    return out.reset_index(drop=True)


def download_one(bs_code: str, start: str, end: str) -> pd.DataFrame | None:
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,open,high,low,close,volume,amount,turn,tradestatus",
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
        rows,
        columns=["date", "open", "high", "low", "close", "vol", "amount", "turn", "tradestatus"],
    )
    for c in ("open", "high", "low", "close", "vol", "amount", "turn"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["tradestatus"] == "1"].dropna(subset=["close"])
    return df[df["vol"] > 0].reset_index(drop=True)


def ensure_cache(universe: pd.DataFrame, start: str, end: str) -> None:
    bs.login()
    try:
        for i, row in universe.iterrows():
            path = DATA_DIR / f"{row['code6']}.csv"
            need = True
            if path.exists():
                try:
                    old = pd.read_csv(path)
                    has_turn = "turn" in old.columns
                    last = str(old["date"].iloc[-1])[:10] if not old.empty else ""
                    if has_turn and last >= end:
                        need = False
                except Exception:
                    pass
            if not need:
                continue
            if i % 80 == 0:
                print(f"  下载 {i+1}/{len(universe)} {row['code6']}")
            df = download_one(row["code"], start, end)
            if df is not None and len(df):
                df.to_csv(path, index=False)
    finally:
        bs.logout()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if "turn" not in d.columns:
        d["turn"] = np.nan
    d["ma5"] = d["close"].rolling(5).mean()
    d["ma120"] = d["close"].rolling(120).mean()
    d["ma250"] = d["close"].rolling(250).mean()
    d["turn_ma3"] = d["turn"].rolling(3).mean()
    llv = d["low"].rolling(9).min()
    hhv = d["high"].rolling(9).max()
    denom = (hhv - llv).replace(0, np.nan)
    rsv = (d["close"] - llv) / denom * 100
    d["k"] = sma_tdx(rsv, 3, 1)
    d["d"] = sma_tdx(d["k"], 3, 1)
    # RSI(6)
    delta = d["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / 6, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / 6, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    d["rsi6"] = 100 - (100 / (1 + rs))
    return d


def signal_mask(d: pd.DataFrame) -> pd.Series:
    trend = (d["close"] > d["ma250"]) & (d["ma250"] >= d["ma250"].shift(1))
    near = (
        ((d["close"] >= d["ma120"]) & (d["close"] <= d["ma120"] * 1.03))
        | ((d["close"] >= d["ma250"]) & (d["close"] <= d["ma250"] * 1.03))
    )
    low_hs = d["turn_ma3"] <= 0.6
    cross_ma5 = (d["close"] > d["ma5"]) & (d["close"].shift(1) <= d["ma5"].shift(1))
    kdj_ok = (d["k"] < 30) & (d["k"].shift(1) <= d["d"].shift(1)) & (d["k"] > d["d"])
    right = cross_ma5 | kdj_ok
    liq = d["amount"] >= MIN_AMOUNT
    bars = pd.Series(np.arange(len(d)) >= 259, index=d.index)
    has_turn = d["turn"].notna()
    return trend & near & low_hs & right & liq & bars & has_turn


def anchor_stop(row: pd.Series) -> tuple[str, float]:
    near_120 = row["close"] >= row["ma120"] and row["close"] <= row["ma120"] * 1.03
    if near_120:
        return "MA120", float(row["ma120"] * 0.975)
    return "MA250", float(row["ma250"] * 0.975)


def simulate(d: pd.DataFrame, entry_i: int) -> dict | None:
    """尾盘买入；R1 破止损；R2 保本后仍持有；R3 止盈；R4 满约 20 交易日。"""
    if entry_i >= len(d) - 1:
        return None
    entry = d.iloc[entry_i]
    entry_px = float(entry["close"])
    _, stop = anchor_stop(entry)
    be_stop = False
    last_i = min(entry_i + MAX_HOLD_DAYS - 1, len(d) - 1)
    exit_i, exit_px, reason = entry_i, entry_px, "R4"

    for j in range(entry_i + 1, last_i + 1):
        row = d.iloc[j]
        px = float(row["close"])
        profit = (px / entry_px - 1) * 100
        active_stop = entry_px if be_stop else stop

        if px < active_stop:
            exit_i, exit_px, reason = j, px, "R1"
            break

        if (not be_stop) and profit >= 3:
            be_stop = True

        rsi = float(row["rsi6"]) if pd.notna(row["rsi6"]) else 0.0
        if profit >= 6 or rsi > 75:
            exit_i, exit_px, reason = j, px, "R3"
            break

        exit_i, exit_px, reason = j, px, "R4"

    return {
        "entry_date": str(entry["date"])[:10],
        "exit_date": str(d.iloc[exit_i]["date"])[:10],
        "entry_price": round(entry_px, 3),
        "exit_price": round(float(exit_px), 3),
        "stop_line": round(stop, 3),
        "hold_days": int(exit_i - entry_i),
        "ret_pct": round((float(exit_px) / entry_px - 1) * 100, 2),
        "exit_reason": reason,
    }


def backtest_one(code6: str, name: str) -> list[Trade]:
    path = DATA_DIR / f"{code6}.csv"
    if not path.exists():
        return []
    raw = pd.read_csv(path)
    if len(raw) < 280:
        return []
    if "turn" not in raw.columns or raw["turn"].isna().all():
        return []
    d = add_indicators(raw)
    sig = signal_mask(d)
    trades: list[Trade] = []
    i, n = 0, len(d)
    while i < n:
        if not bool(sig.iloc[i]):
            i += 1
            continue
        dt = str(d.iloc[i]["date"])[:10]
        if dt < BT_START or dt > BT_END:
            i += 1
            continue
        r = simulate(d, i)
        if not r:
            i += 1
            continue
        trades.append(Trade(code=code6, name=name, **r))
        exit_date = r["exit_date"]
        j = i + 1
        while j < n and str(d.iloc[j]["date"])[:10] <= exit_date:
            j += 1
        i = j
    return trades


def summarize(trades: list[Trade]) -> dict:
    if not trades:
        return {"trade_count": 0}
    rets = np.array([t.ret_pct for t in trades])
    by_r: dict[str, int] = {}
    for t in trades:
        by_r[t.exit_reason] = by_r.get(t.exit_reason, 0) + 1
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    return {
        "trade_count": len(trades),
        "win_rate_pct": round(float((rets > 0).mean() * 100), 2),
        "avg_ret_pct": round(float(rets.mean()), 2),
        "median_ret_pct": round(float(np.median(rets)), 2),
        "avg_win_pct": round(float(wins.mean()), 2) if len(wins) else None,
        "avg_loss_pct": round(float(losses.mean()), 2) if len(losses) else None,
        "avg_hold_days": round(float(np.mean([t.hold_days for t in trades])), 1),
        "exit_reason_counts": by_r,
        "max_ret_pct": round(float(rets.max()), 2),
        "min_ret_pct": round(float(rets.min()), 2),
        "notes": [
            "入场：信号日收盘；单票仓位回测未建模（实盘 25%）",
            "R1 破锚均线×0.975（保本后止损=成本）；R3 盈≥6%或RSI6>75；R4 满约20交易日",
            "未过滤中证红利成分与股息率；主板宽池 + 换手≤0.6% 近似",
        ],
    }


def main() -> None:
    print("=== 股票池 ===")
    bs.login()
    try:
        universe = list_main_board()
    finally:
        bs.logout()
    print(f"主板近似池 {len(universe)} 只")
    print("=== 缓存日线（含 turn） ===")
    ensure_cache(universe, HIST_START, BT_END)
    print("=== 回测 ===")
    all_trades: list[Trade] = []
    for i, row in universe.iterrows():
        if i % 100 == 0:
            print(f"  {i+1}/{len(universe)}")
        all_trades.extend(backtest_one(row["code6"], row["name"]))
    summary = summarize(all_trades)
    summary.update(
        {
            "bt_start": BT_START,
            "bt_end": BT_END,
            "universe_size": len(universe),
            "run_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    stamp = f"{BT_START}_{BT_END}".replace("-", "")
    trades_df = pd.DataFrame([asdict(t) for t in all_trades])
    trades_df.to_csv(OUT_DIR / f"backtest_trades_{stamp}.csv", index=False, encoding="utf-8-sig")
    (OUT_DIR / f"backtest_summary_{stamp}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md = [
        "# 红利资产·绝对防御低回撤波段 · 历史回测报告",
        "",
        f"- 区间：{BT_START} ~ {BT_END}",
        f"- 交易数：{summary.get('trade_count')}",
        f"- 胜率：{summary.get('win_rate_pct')}%",
        f"- 平均收益：{summary.get('avg_ret_pct')}%",
        f"- 中位数：{summary.get('median_ret_pct')}%",
        f"- 出场：{summary.get('exit_reason_counts')}",
        "",
    ]
    for n in summary.get("notes", []):
        md.append(f"- {n}")
    (OUT_DIR / f"backtest_report_{stamp}.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"报告已写 {OUT_DIR}")


if __name__ == "__main__":
    main()
