"""Aggregate filled trades and export top-20 stocks by total PnL."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
TRADES = OUT / "backtest_trades_list_20230101_20260721.csv"


def main() -> None:
    df = pd.read_csv(TRADES, dtype={"code": str})
    df["code"] = df["code"].str.zfill(6)
    if "skipped" in df.columns:
        df = df[df["skipped"] == False]  # noqa: E712

    g = (
        df.groupby(["code", "name", "sector"], as_index=False)
        .agg(
            trades=("pnl", "count"),
            wins=("pnl", lambda s: int((s > 0).sum())),
            pnl_sum=("pnl", "sum"),
            ret_mean=("ret_pct", "mean"),
            ret_sum=("ret_pct", "sum"),
            hold_mean=("hold_days", "mean"),
        )
        .sort_values(["pnl_sum", "ret_mean", "trades"], ascending=[False, False, False])
        .reset_index(drop=True)
    )
    g["win_rate"] = (g["wins"] / g["trades"] * 100).round(1)
    top20 = g.head(20).copy()
    top20.insert(0, "rank", range(1, len(top20) + 1))

    csv_path = OUT / "top20_stocks_list_20230101_20260721.csv"
    md_path = OUT / "top20_stocks_list_20230101_20260721.md"
    top20.to_csv(csv_path, index=False, encoding="utf-8-sig")

    lines = [
        "# v3.1 list 回测 · 表现最好 20 只",
        "",
        "- 区间：2023-01-01 ~ 2026-07-21",
        "- 排序：按 **盈亏合计(元)** 降序；同分看均收益%、笔数",
        "- 来源：已成交 87 笔聚合（零信号标的不参与）",
        "",
        "| 排名 | 代码 | 名称 | 板块 | 笔数 | 胜率% | 均收益% | 收益%合计 | 盈亏合计(元) | 均持仓日 |",
        "| ---: | :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for _, r in top20.iterrows():
        lines.append(
            "| {rank} | {code} | {name} | {sector} | {trades} | {win_rate} | "
            "{ret_mean:.2f} | {ret_sum:.2f} | {pnl_sum:.2f} | {hold_mean:.1f} |".format(
                rank=int(r["rank"]),
                code=r["code"],
                name=r["name"],
                sector=r["sector"],
                trades=int(r["trades"]),
                win_rate=r["win_rate"],
                ret_mean=r["ret_mean"],
                ret_sum=r["ret_sum"],
                pnl_sum=r["pnl_sum"],
                hold_mean=r["hold_mean"],
            )
        )
    lines += [
        "",
        f"- Top20 盈亏合计：{top20['pnl_sum'].sum():.2f} 元",
        f"- Top20 成交笔数：{int(top20['trades'].sum())}",
        "",
        "## 代码清单（可直接替换 list）",
        "",
        "```",
        "\n".join(f"{c}  # {n}" for c, n in zip(top20["code"], top20["name"])),
        "```",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(md_path.read_text(encoding="utf-8"))
    print("CSV:", csv_path)


if __name__ == "__main__":
    main()
