"""
红利T策略 · 历史回测（v2.5 日线优化版）。
标的：list.md（默认 561580）
资金：底仓 20 万；Float A 5 万；Float B 2.5 万（总盘 27.5 万）
信号：R-A=零浮仓+下轨+J<=0；R-B=有A+下轨+J<=0+相对A跌幅>=2.5%；
      R高抛=上轨+J>=100 → 当日一次清全部浮仓；无 R1 止损
成交：信号日收盘；不计税费；不含红利再投
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

THEME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = THEME_ROOT.parent
DATA_DIR = REPO_ROOT / "data" / "daily"
OUT_DIR = THEME_ROOT / "output"
LIST_MD = THEME_ROOT / "list.md"
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

BT_START = "2023-05-30"
BT_END = "2026-07-24"
HIST_START = "2023-05-30"

# 定额仓位（口述 2026-07-27）
BASE_BUDGET = 200_000.0
FLOAT_A_BUDGET = 50_000.0
FLOAT_B_BUDGET = 25_000.0
TOTAL_CAPITAL = BASE_BUDGET + FLOAT_A_BUDGET + FLOAT_B_BUDGET  # 275_000
MAX_FLOAT_SLOTS = 2
SPACE_STEP = 0.025

BOLL_N = 20
BOLL_K = 2.0
MA_N = 20
KDJ_N = 9


def to_bs_code(code6: str) -> str:
    c = code6.zfill(6)
    if c.startswith(("5", "6", "9")):
        return f"sh.{c}"
    return f"sz.{c}"


def load_list_md(path: Path = LIST_MD) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        m = re.match(r"\|\s*\d+\s*\|\s*(\d{6})\s*\|\s*([^|]+?)\s*\|", line.strip())
        if not m:
            continue
        code6, name = m.group(1), m.group(2).strip()
        rows.append({"code": to_bs_code(code6), "code6": code6, "name": name})
    if not rows:
        raise ValueError(f"未能从 {path} 解析到股票代码")
    return pd.DataFrame(rows)


def lot_shares(price: float, budget: float) -> int:
    if price <= 0 or budget <= 0:
        return 0
    return int(budget // (price * 100)) * 100


def _read_cache(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        cached = pd.read_csv(path)
        return None if cached.empty else cached
    except Exception:
        return None


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    colmap = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "vol",
        "成交额": "amount",
        "date": "date",
        "open": "open",
        "close": "close",
        "high": "high",
        "low": "low",
        "vol": "vol",
        "volume": "vol",
        "amount": "amount",
    }
    out = df.rename(columns={c: colmap[c] for c in df.columns if c in colmap})
    need = ["date", "open", "high", "low", "close"]
    if any(c not in out.columns for c in need):
        return None
    if "vol" not in out.columns:
        out["vol"] = 0
    if "amount" not in out.columns:
        out["amount"] = 0
    for c in ("open", "high", "low", "close", "vol", "amount"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out["date"] = out["date"].astype(str).str[:10]
    out = out.dropna(subset=["close", "open"]).reset_index(drop=True)
    return out if len(out) else None


def _download_akshare(code6: str, start: str, end: str) -> pd.DataFrame | None:
    try:
        import akshare as ak

        raw = ak.fund_etf_hist_em(
            symbol=code6,
            period="daily",
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="qfq",
        )
        return _normalize_ohlcv(raw)
    except Exception as e:
        print(f"  akshare fail {code6}: {e}")
        return None


def fetch_hist(code6: str, start: str, end: str, *, force: bool = False) -> pd.DataFrame | None:
    cache = DATA_DIR / f"{code6}.csv"
    cached = _read_cache(cache)
    cache_ok = (
        cached is not None
        and str(cached["date"].iloc[-1])[:10] >= end[:10]
        and str(cached["date"].iloc[0])[:10] <= start[:10]
        and len(cached) >= 200
    )
    if not force and cache_ok:
        return cached
    df = _download_akshare(code6, start, end)
    if df is not None and len(df):
        df.to_csv(cache, index=False)
        return df
    return cached


def calc_daily_indicators(d: pd.DataFrame) -> pd.DataFrame:
    out = d.copy()
    out["ma20"] = out["close"].rolling(MA_N).mean()
    mid = out["close"].rolling(BOLL_N).mean()
    std = out["close"].rolling(BOLL_N).std(ddof=0)
    out["boll_mid"] = mid
    out["boll_upper"] = mid + BOLL_K * std
    out["boll_lower"] = mid - BOLL_K * std
    low_n = out["low"].rolling(KDJ_N).min()
    high_n = out["high"].rolling(KDJ_N).max()
    rsv = (out["close"] - low_n) / (high_n - low_n).replace(0, pd.NA) * 100
    out["k"] = rsv.ewm(com=2, adjust=False).mean()
    out["d"] = out["k"].ewm(com=2, adjust=False).mean()
    out["j"] = 3 * out["k"] - 2 * out["d"]
    return out


@dataclass
class Trade:
    code: str
    name: str
    leg: str  # base | floatA | floatB
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    hold_days: int
    ret_pct: float
    exit_reason: str
    shares: int
    cost: float
    proceeds: float
    pnl: float
    skipped: bool = False
    skip_reason: str = ""


def try_open_float(
    *,
    code6: str,
    name: str,
    date: str,
    price: float,
    cash: float,
    float_pos: list[dict],
    tranche_budget: float,
    slot: str,
    skipped: list[Trade],
) -> float:
    use_budget = min(tranche_budget, cash)
    sh = lot_shares(price, use_budget)
    cost = sh * price
    if sh <= 0 or cost > cash + 1e-9:
        skipped.append(
            Trade(
                code=code6,
                name=name,
                leg=slot,
                entry_date=date,
                exit_date=date,
                entry_price=price,
                exit_price=price,
                hold_days=0,
                ret_pct=0.0,
                exit_reason="跳过",
                shares=0,
                cost=0.0,
                proceeds=0.0,
                pnl=0.0,
                skipped=True,
                skip_reason="现金不足/不足1手",
            )
        )
        return cash
    cash -= cost
    float_pos.append(
        {
            "slot": slot,
            "entry_date": date,
            "entry_price": price,
            "shares": sh,
            "cost": cost,
        }
    )
    return cash


def close_all_float(
    *,
    code6: str,
    name: str,
    date: str,
    price: float,
    cash: float,
    float_pos: list[dict],
    date_to_i: dict[str, int],
    reason: str,
    trades: list[Trade],
) -> float:
    while float_pos:
        pos = float_pos.pop(0)
        proceeds = pos["shares"] * price
        pnl = proceeds - pos["cost"]
        ret = pnl / pos["cost"] * 100 if pos["cost"] else 0.0
        ei = date_to_i.get(pos["entry_date"], 0)
        xi = date_to_i.get(date, ei)
        trades.append(
            Trade(
                code=code6,
                name=name,
                leg=pos.get("slot", "float"),
                entry_date=pos["entry_date"],
                exit_date=date,
                entry_price=pos["entry_price"],
                exit_price=price,
                hold_days=max(0, xi - ei),
                ret_pct=round(ret, 2),
                exit_reason=reason,
                shares=pos["shares"],
                cost=round(pos["cost"], 2),
                proceeds=round(proceeds, 2),
                pnl=round(pnl, 2),
            )
        )
        cash += proceeds
    return cash


def backtest_one(
    code6: str,
    name: str,
    daily: pd.DataFrame,
    bt_start: str,
    bt_end: str,
) -> tuple[list[Trade], list[Trade], dict]:
    daily = daily.copy()
    daily["date"] = daily["date"].astype(str).str[:10]
    daily = daily.sort_values("date").reset_index(drop=True)
    daily = daily[daily["date"] <= bt_end].reset_index(drop=True)
    ind = calc_daily_indicators(daily)

    trades: list[Trade] = []
    skipped: list[Trade] = []
    cash = TOTAL_CAPITAL
    base_shares = 0
    base_cost_price = 0.0
    base_entry_date = ""
    float_pos: list[dict] = []

    start_rows = ind[ind["date"] >= bt_start]
    if start_rows.empty:
        return [], [], {"error": "无回测区间日线", "code": code6}

    first = start_rows.iloc[0]
    base_day = str(first["date"])[:10]
    base_px = float(first["open"])
    sh = lot_shares(base_px, BASE_BUDGET)
    if sh > 0:
        cost = sh * base_px
        cash -= cost
        base_shares = sh
        base_cost_price = base_px
        base_entry_date = base_day
    else:
        skipped.append(
            Trade(
                code=code6,
                name=name,
                leg="base",
                entry_date=base_day,
                exit_date=base_day,
                entry_price=base_px,
                exit_price=base_px,
                hold_days=0,
                ret_pct=0.0,
                exit_reason="跳过",
                shares=0,
                cost=0.0,
                proceeds=0.0,
                pnl=0.0,
                skipped=True,
                skip_reason="底仓不足1手",
            )
        )

    dates = ind["date"].tolist()
    date_to_i = {d: i for i, d in enumerate(dates)}

    for _, row in ind.iterrows():
        ddate = str(row["date"])[:10]
        if ddate < bt_start or ddate > bt_end:
            continue
        if pd.isna(row["boll_lower"]) or pd.isna(row["j"]):
            continue

        close = float(row["close"])
        lower = float(row["boll_lower"])
        upper = float(row["boll_upper"])
        j = float(row["j"])
        touch_lower = close <= lower * 1.002
        touch_upper = close >= upper * 0.998
        buy_sig = touch_lower and j <= 0
        sell_sig = touch_upper and j >= 100

        # 高抛：一次清全部浮仓（无 R1）
        if sell_sig and float_pos:
            cash = close_all_float(
                code6=code6,
                name=name,
                date=ddate,
                price=close,
                cash=cash,
                float_pos=float_pos,
                date_to_i=date_to_i,
                reason="R高抛",
                trades=trades,
            )

        if not buy_sig:
            continue

        # Float A：仅零浮仓
        if len(float_pos) == 0:
            cash = try_open_float(
                code6=code6,
                name=name,
                date=ddate,
                price=close,
                cash=cash,
                float_pos=float_pos,
                tranche_budget=FLOAT_A_BUDGET,
                slot="floatA",
                skipped=skipped,
            )
            continue

        # Float B：须有且仅有 A，且空间 ≥2.5%
        if len(float_pos) == 1 and float_pos[0].get("slot") == "floatA":
            a_px = float_pos[0]["entry_price"]
            space_ok = close <= a_px * (1.0 - SPACE_STEP)
            if not space_ok:
                drop_pct = (a_px - close) / a_px * 100 if a_px else 0.0
                skipped.append(
                    Trade(
                        code=code6,
                        name=name,
                        leg="floatB",
                        entry_date=ddate,
                        exit_date=ddate,
                        entry_price=close,
                        exit_price=close,
                        hold_days=0,
                        ret_pct=0.0,
                        exit_reason="跳过",
                        shares=0,
                        cost=0.0,
                        proceeds=0.0,
                        pnl=0.0,
                        skipped=True,
                        skip_reason=f"空间不足2.5%(相对A跌{drop_pct:.2f}%)",
                    )
                )
            else:
                cash = try_open_float(
                    code6=code6,
                    name=name,
                    date=ddate,
                    price=close,
                    cash=cash,
                    float_pos=float_pos,
                    tranche_budget=FLOAT_B_BUDGET,
                    slot="floatB",
                    skipped=skipped,
                )

    # 期末了结（浮仓允许套牢至期末盯市）
    last = ind[ind["date"] <= bt_end].iloc[-1]
    last_date = str(last["date"])[:10]
    last_close = float(last["close"])
    cash = close_all_float(
        code6=code6,
        name=name,
        date=last_date,
        price=last_close,
        cash=cash,
        float_pos=float_pos,
        date_to_i=date_to_i,
        reason="期末",
        trades=trades,
    )
    if base_shares > 0:
        proceeds = base_shares * last_close
        cost = base_shares * base_cost_price
        pnl = proceeds - cost
        ret = pnl / cost * 100 if cost else 0.0
        ei = date_to_i.get(base_entry_date, 0)
        xi = date_to_i.get(last_date, ei)
        trades.append(
            Trade(
                code=code6,
                name=name,
                leg="base",
                entry_date=base_entry_date,
                exit_date=last_date,
                entry_price=base_cost_price,
                exit_price=last_close,
                hold_days=max(0, xi - ei),
                ret_pct=round(ret, 2),
                exit_reason="期末底仓",
                shares=base_shares,
                cost=round(cost, 2),
                proceeds=round(proceeds, 2),
                pnl=round(pnl, 2),
            )
        )
        cash += proceeds

    float_trades = [t for t in trades if t.leg.startswith("float")]
    rets = [t.ret_pct for t in float_trades]
    wins = [r for r in rets if r > 0]
    summary = {
        "code": code6,
        "name": name,
        "base_entry": base_entry_date,
        "end_date": last_date,
        "end_equity": round(cash, 2),
        "total_return_pct": round((cash / TOTAL_CAPITAL - 1) * 100, 2),
        "float_trades": len(float_trades),
        "float_win_rate": round(len(wins) / len(rets) * 100, 1) if rets else None,
        "float_avg_ret": round(float(np.mean(rets)), 2) if rets else None,
        "float_median_ret": round(float(np.median(rets)), 2) if rets else None,
        "float_pnl": round(sum(t.pnl for t in float_trades), 2),
        "base_pnl": round(sum(t.pnl for t in trades if t.leg == "base"), 2),
        "skipped": len(skipped),
    }
    return trades, skipped, summary


def exit_dist(trades: list[Trade]) -> dict[str, int]:
    d: dict[str, int] = {}
    for t in trades:
        d[t.exit_reason] = d.get(t.exit_reason, 0) + 1
    return d


def write_report(
    *,
    stamp: str,
    universe_tag: str,
    list_path: Path,
    bt_start: str,
    bt_end: str,
    trades: list[Trade],
    skipped: list[Trade],
    summaries: list[dict],
    zero_signal: list[str],
) -> Path:
    float_trades = [t for t in trades if str(t.leg).startswith("float")]
    base_trades = [t for t in trades if t.leg == "base"]
    if len(summaries) == 1:
        end_equity = summaries[0]["end_equity"]
        total_ret = summaries[0]["total_return_pct"]
    else:
        total_pnl = sum(t.pnl for t in trades)
        end_equity = round(TOTAL_CAPITAL + total_pnl, 2)
        total_ret = round((end_equity / TOTAL_CAPITAL - 1) * 100, 2)

    rets = [t.ret_pct for t in float_trades]
    wins = [r for r in rets if r > 0]
    dist = exit_dist(trades)

    lines: list[str] = []
    lines.append(f"# 红利T策略回测报告 · v2.5 日线优化 · {universe_tag}")
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    lines.append(f"- **区间**：{bt_start} ~ {bt_end}")
    lines.append(f"- **池**：`{list_path.name}`（{len(summaries)} 只）")
    lines.append(
        f"- **资金**：总盘 **{TOTAL_CAPITAL:,.0f}**；底仓 **{BASE_BUDGET:,.0f}**；"
        f"Float A **{FLOAT_A_BUDGET:,.0f}**；Float B **{FLOAT_B_BUDGET:,.0f}**；"
        f"B 空间步长 **≥{SPACE_STEP:.1%}**"
    )
    lines.append(f"- **浮仓成交**：{len(float_trades)} 笔 · 跳过 {len(skipped)}")
    lines.append(f"- **底仓腿**：{len(base_trades)} 笔（期末盯市了结）")
    lines.append(f"- **期末权益**：{end_equity:,.2f}（总收益 **{total_ret}%**）")
    if rets:
        lines.append(
            f"- **浮仓胜率**：{len(wins)/len(rets)*100:.1f}% · "
            f"均收益 {float(np.mean(rets)):.2f}% · 中位数 {float(np.median(rets)):.2f}%"
        )
    else:
        lines.append("- **浮仓胜率**：无浮仓成交")
    lines.append(f"- **出场分布**：{dist}")
    if summaries:
        lines.append(
            f"- **浮仓盈亏合计**：{sum(s.get('float_pnl', 0) for s in summaries):,.2f} 元 · "
            f"**底仓盈亏**：{sum(s.get('base_pnl', 0) for s in summaries):,.2f} 元"
        )
    lines.append("")
    lines.append("## 假设")
    lines.append("")
    lines.append("- **v2.5**：日线 BOLL(20,2)+KDJ；收盘成交；**无 R1 止损**")
    lines.append("- **R-A**：零浮仓 + 下轨 + J≤0 → 定额 Float A")
    lines.append(
        f"- **R-B**：有 A + 下轨 + J≤0 + 收盘 ≤ A价×(1−{SPACE_STEP:.1%}) → 定额 Float B；否则跳过"
    )
    lines.append("- **R高抛**：上轨 + J≥100 → **当日一次清全部浮仓**")
    lines.append("- 被套不割肉；期末未平浮仓按收盘盯市了结")
    lines.append(f"- 底仓：起点开盘定额 **{BASE_BUDGET:,.0f}** 买入持有至期末")
    lines.append("- **不计**税费；**不含**红利再投")
    lines.append("")

    if zero_signal:
        lines.append("## 零信号标的")
        lines.append("")
        for z in zero_signal:
            lines.append(f"- {z}")
        lines.append("")

    by_code: dict[str, float] = {}
    for t in float_trades:
        by_code[t.code] = by_code.get(t.code, 0.0) + t.pnl
    ranked = sorted(by_code.items(), key=lambda x: x[1], reverse=True)
    if ranked:
        lines.append("## 分票浮仓盈亏 Top / Bottom")
        lines.append("")
        lines.append("| 代码 | 浮仓盈亏(元) |")
        lines.append("| :--- | ---: |")
        for code, pnl in ranked[:5]:
            lines.append(f"| {code} | {pnl:,.2f} |")
        lines.append("")

    lines.append("## 信号交易明细（按入场日 · 已成交）")
    lines.append("")
    lines.append(
        "| # | 代码 | 名称 | 腿 | 入场日 | 出场日 | 买入 | 卖出 | 股数 | 成本 | 盈亏 | 收益% | 出场 |"
    )
    lines.append(
        "| ---: | :--- | :--- | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |"
    )
    ordered = sorted(trades, key=lambda t: (t.entry_date, t.code, t.leg))
    for i, t in enumerate(ordered, 1):
        lines.append(
            f"| {i} | {t.code} | {t.name} | {t.leg} | {t.entry_date} | {t.exit_date} | "
            f"{t.entry_price:.4f} | {t.exit_price:.4f} | {t.shares} | {t.cost:,.2f} | "
            f"{t.pnl:,.2f} | {t.ret_pct:.2f} | {t.exit_reason} |"
        )
    if not ordered:
        lines.append("| — | — | — | — | — | — | — | — | — | — | — | — | 无成交 |")
    lines.append("")

    if skipped:
        lines.append("## 跳过信号")
        lines.append("")
        lines.append("| 代码 | 名称 | 腿 | 日期 | 原因 |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for t in skipped:
            lines.append(
                f"| {t.code} | {t.name} | {t.leg} | {t.entry_date} | {t.skip_reason} |"
            )
        lines.append("")

    lines.append("---")
    lines.append(f"*生成于 {datetime.now().isoformat(timespec='seconds')} · stamp `{stamp}`*")
    path = OUT_DIR / f"backtest_report_{universe_tag}_{stamp}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="红利T v2.5 日线回测")
    parser.add_argument("--universe", choices=["list", "mainboard"], default="list")
    parser.add_argument("--list", type=Path, default=LIST_MD)
    parser.add_argument("--start", default=BT_START)
    parser.add_argument("--end", default=BT_END)
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()

    if args.universe == "mainboard":
        print("本策略为单标的 ETF 做 T，请用 --universe list")
        raise SystemExit(2)

    universe = load_list_md(args.list)
    stamp = f"{args.start.replace('-', '')}_{args.end.replace('-', '')}"
    tag = "list"
    print(
        f"HongliT BT v2.5 | {args.start}~{args.end} | "
        f"n={len(universe)} | capital={TOTAL_CAPITAL:,.0f} | space>={SPACE_STEP:.1%}"
    )

    all_trades: list[Trade] = []
    all_skipped: list[Trade] = []
    summaries: list[dict] = []
    zero_signal: list[str] = []

    for _, row in universe.iterrows():
        code6, name = row["code6"], row["name"]
        df = fetch_hist(code6, HIST_START, args.end, force=args.force_refresh)
        if df is None or len(df) < 60:
            print(f"  FAIL data {code6} {name}")
            zero_signal.append(f"{code6} {name}（数据不足）")
            continue
        trades, skipped, summary = backtest_one(code6, name, df, args.start, args.end)
        if summary.get("error"):
            zero_signal.append(f"{code6} {name}（{summary['error']}）")
            continue
        all_trades.extend(trades)
        all_skipped.extend(skipped)
        summaries.append(summary)
        ft = summary.get("float_trades", 0)
        print(
            f"  OK {code6} {name} float={ft} skip={summary['skipped']} "
            f"ret={summary['total_return_pct']}% equity={summary['end_equity']:,.0f}"
        )

    trades_path = OUT_DIR / f"backtest_trades_{tag}_{stamp}.csv"
    pd.DataFrame([asdict(t) for t in all_trades]).to_csv(
        trades_path, index=False, encoding="utf-8-sig"
    )
    skip_path = None
    if all_skipped:
        skip_path = OUT_DIR / f"backtest_skipped_{tag}_{stamp}.csv"
        pd.DataFrame([asdict(t) for t in all_skipped]).to_csv(
            skip_path, index=False, encoding="utf-8-sig"
        )

    report_path = write_report(
        stamp=stamp,
        universe_tag=tag,
        list_path=args.list,
        bt_start=args.start,
        bt_end=args.end,
        trades=all_trades,
        skipped=all_skipped,
        summaries=summaries,
        zero_signal=zero_signal,
    )

    float_trades = [t for t in all_trades if str(t.leg).startswith("float")]
    rets = [t.ret_pct for t in float_trades]
    payload = {
        "version": "v2.5",
        "universe": tag,
        "list_path": str(args.list),
        "start": args.start,
        "end": args.end,
        "total_capital": TOTAL_CAPITAL,
        "base_budget": BASE_BUDGET,
        "float_a_budget": FLOAT_A_BUDGET,
        "float_b_budget": FLOAT_B_BUDGET,
        "space_step": SPACE_STEP,
        "r1_stop": None,
        "summaries": summaries,
        "float_trade_count": len(float_trades),
        "skipped_count": len(all_skipped),
        "float_win_rate": round(len([r for r in rets if r > 0]) / len(rets) * 100, 1)
        if rets
        else None,
        "float_avg_ret": round(float(np.mean(rets)), 2) if rets else None,
        "exit_dist": exit_dist(all_trades),
        "report": str(report_path),
        "trades_csv": str(trades_path),
        "skipped_csv": str(skip_path) if skip_path else None,
        "note": "v2.5；无R1；B须相对A跌>=2.5%；高抛一次清仓；不计税费",
    }
    summary_path = OUT_DIR / f"backtest_summary_{tag}_{stamp}.json"
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {report_path}")
    print(f"trades: {trades_path}")
    print(f"summary: {summary_path}")


if __name__ == "__main__":
    main()
