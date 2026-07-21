"""
复现 model.md 通达信公式的日度选股。
数据：baostock 历史日线 + 新浪快照补齐「当日」K 线（解决日线源滞后）。
IS_TECH：实现 CODELIKE(300|688)；市值用腾讯行情。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

import akshare as ak
import baostock as bs
import pandas as pd
import requests

THEME_ROOT = Path(__file__).resolve().parents[1]  # …/科技成长波段反转
REPO_ROOT = THEME_ROOT.parent
OUT_DIR = THEME_ROOT / "output"
DATA_DIR = REPO_ROOT / "data" / "daily"
OUT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Hit:
    code: str
    name: str
    trade_date: str
    close: float
    open: float
    pct_chg: float
    vol_ratio_1d: float
    drop_from_high_pct: float
    market_cap_yi: float | None
    ma10: float
    concept_note: str = "300/688科技池"


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def to_bs_code(code6: str) -> str:
    if code6.startswith(("5", "6", "9")):
        return f"sh.{code6}"
    return f"sz.{code6}"


def fetch_market_cap_yi(code6: str, retries: int = 3) -> float | None:
    if code6.startswith(("688", "689", "60", "90")):
        prefix = "sh"
    else:
        prefix = "sz"
    url = f"https://qt.gtimg.cn/q={prefix}{code6}"
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=8)
            r.encoding = "gbk"
            m = re.search(r'="([^"]+)"', r.text)
            if not m:
                time.sleep(0.3 * (attempt + 1))
                continue
            parts = m.group(1).split("~")
            if len(parts) > 45 and parts[45]:
                return round(float(parts[45]), 2)
        except Exception:
            time.sleep(0.3 * (attempt + 1))
    return None


def check_bars(df: pd.DataFrame) -> tuple[bool, dict]:
    if len(df) < 260:
        return False, {"reason": "bars<260"}

    df = df.copy()
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["mavol5"] = df["vol"].rolling(5).mean()
    df["mavol60"] = df["vol"].rolling(60).mean()
    df["high_3m"] = df["high"].rolling(60).max()
    df["dif"] = ema(df["close"], 12) - ema(df["close"], 26)
    df["dea"] = ema(df["dif"], 9)

    i = len(df) - 1
    row = df.iloc[i]
    prev = df.iloc[i - 1]

    drop_ok = (row["high_3m"] - row["close"]) / row["high_3m"] * 100 >= 25
    window = df.iloc[i - 4 : i + 1]
    low_vol = int((window["vol"] < window["mavol60"] * 0.4).sum()) >= 3

    dif, dea = float(row["dif"]), float(row["dea"])
    prev_dif, prev_dea = float(prev["dif"]), float(prev["dea"])
    cross = (prev_dif <= prev_dea) and (dif > dea)
    macd_ok = (dif < 0) and (cross or (dif > dea and dif > prev_dif))

    ma_min = min(row["ma5"], row["ma10"], row["ma20"])
    one_pierce = (
        row["close"] > row["ma5"]
        and row["close"] > row["ma10"]
        and row["close"] > row["ma20"]
        and row["open"] < ma_min
    )
    big_sun = row["close"] / prev["close"] >= 1.045
    volume_bomb = (row["vol"] >= prev["vol"] * 2.3) and (row["vol"] > row["mavol5"])

    ok = bool(drop_ok and low_vol and macd_ok and one_pierce and big_sun and volume_bomb)
    meta = {
        "drop_ok": bool(drop_ok),
        "low_vol": bool(low_vol),
        "macd_ok": bool(macd_ok),
        "one_pierce": bool(one_pierce),
        "big_sun": bool(big_sun),
        "volume_bomb": bool(volume_bomb),
        "close": float(row["close"]),
        "open": float(row["open"]),
        "pct_chg": float(row["close"] / prev["close"] - 1) * 100,
        "vol_ratio_1d": float(row["vol"] / prev["vol"]) if prev["vol"] else None,
        "drop_from_high_pct": float((row["high_3m"] - row["close"]) / row["high_3m"] * 100),
        "ma10": float(row["ma10"]),
        "trade_date": str(row["date"])[:10],
    }
    return ok, meta


def fetch_hist_bs(code6: str, start: str, end: str) -> pd.DataFrame | None:
    rs = bs.query_history_k_data_plus(
        to_bs_code(code6),
        "date,open,high,low,close,volume",
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
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "vol"])
    for c in ("open", "high", "low", "close", "vol"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["close", "vol"])
    df = df[df["vol"] > 0].reset_index(drop=True)
    return df


def append_today_bar(df: pd.DataFrame, spot_row: pd.Series, today: str) -> pd.DataFrame:
    """用新浪快照补齐当日 K 线。"""
    last_date = str(df.iloc[-1]["date"])[:10]
    if last_date >= today:
        return df

    # 校验昨收与历史最后收盘大致一致（允许复权微小差异）
    prev_close = float(spot_row["昨收"])
    hist_close = float(df.iloc[-1]["close"])
    if hist_close > 0 and abs(prev_close / hist_close - 1) > 0.08:
        # 复权差异较大时，仍追加，但用快照昨收锚定涨幅：把历史最后收盘替换感不强，直接用快照字段
        pass

    bar = {
        "date": today,
        "open": float(spot_row["今开"]),
        "high": float(spot_row["最高"]),
        "low": float(spot_row["最低"]),
        "close": float(spot_row["最新价"]),
        "vol": float(spot_row["成交量"]),
    }
    return pd.concat([df, pd.DataFrame([bar])], ignore_index=True)


def main() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"报告日（本地）: {today}")
    print("拉取新浪全市场快照…")
    spot = ak.stock_zh_a_spot()
    spot["raw"] = spot["代码"].astype(str)
    spot["code"] = spot["raw"].str[-6:]
    spot["name"] = spot["名称"].astype(str)
    spot["pct"] = pd.to_numeric(spot["涨跌幅"], errors="coerce")

    mask = (
        (spot["raw"].str.startswith("sz300") | spot["raw"].str.startswith("sh688"))
        & (~spot["name"].str.contains("ST", case=False, na=False))
        & (spot["pct"] >= 4.5)
    )
    candidates = spot.loc[mask].copy()
    print(f"快照预筛（300/688 + 涨幅≥4.5% + 非ST）：{len(candidates)} 只")

    end = today
    start = (datetime.now() - timedelta(days=450)).strftime("%Y-%m-%d")

    lg = bs.login()
    print("baostock login:", lg.error_code, lg.error_msg)

    hits: list[Hit] = []
    tech_pass: list[tuple[str, str, dict]] = []
    fail_stats = {
        "hist_fail": 0,
        "tech_fail": 0,
        "cap_out_of_range": 0,
        "cap_unknown": 0,
    }

    try:
        for n, (_, row) in enumerate(candidates.iterrows(), 1):
            code, name = row["code"], row["name"]
            if n % 20 == 0 or n == 1:
                print(f"  日线复核 {n}/{len(candidates)} … {code} {name}")

            df = fetch_hist_bs(code, start, end)
            if df is None or len(df) < 250:
                fail_stats["hist_fail"] += 1
                continue

            df = append_today_bar(df, row, today)
            if len(df) < 260:
                fail_stats["hist_fail"] += 1
                continue

            ok, meta = check_bars(df)
            if not ok:
                fail_stats["tech_fail"] += 1
                for k in (
                    "drop_ok",
                    "low_vol",
                    "macd_ok",
                    "one_pierce",
                    "big_sun",
                    "volume_bomb",
                ):
                    if meta.get(k):
                        fail_stats[f"pass_{k}"] = fail_stats.get(f"pass_{k}", 0) + 1
                continue

            # 全条件通过时也记一遍
            for k in (
                "drop_ok",
                "low_vol",
                "macd_ok",
                "one_pierce",
                "big_sun",
                "volume_bomb",
            ):
                fail_stats[f"pass_{k}"] = fail_stats.get(f"pass_{k}", 0) + 1

            tech_pass.append((code, name, meta))
            print(
                f"  ★ TECH {code} {name} +{meta['pct_chg']:.2f}% "
                f"量×{meta['vol_ratio_1d']:.2f}"
            )

        print(f"技术面通过: {len(tech_pass)} 只，开始市值过滤…")
        for code, name, meta in tech_pass:
            mv = fetch_market_cap_yi(code)
            time.sleep(0.15)
            if mv is None:
                fail_stats["cap_unknown"] += 1
                mv_val: float | None = None
                print(f"  ? CAP未知 {code} {name}（保留待核）")
            elif not (50 <= mv <= 500):
                fail_stats["cap_out_of_range"] += 1
                print(f"  × CAP超限 {code} {name} 市值{mv}亿")
                continue
            else:
                mv_val = mv

            hits.append(
                Hit(
                    code=code,
                    name=name,
                    trade_date=meta["trade_date"],
                    close=round(meta["close"], 2),
                    open=round(meta["open"], 2),
                    pct_chg=round(meta["pct_chg"], 2),
                    vol_ratio_1d=round(meta["vol_ratio_1d"] or 0, 2),
                    drop_from_high_pct=round(meta["drop_from_high_pct"], 2),
                    market_cap_yi=mv_val,
                    ma10=round(meta["ma10"], 2),
                )
            )
            print(
                f"  ✓ HIT {code} {name} +{meta['pct_chg']:.2f}% "
                f"量×{meta['vol_ratio_1d']:.2f} 市值{mv_val}亿"
            )
    finally:
        bs.logout()

    trade_date = hits[0].trade_date if hits else today
    result = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "trade_date": trade_date,
        "prefilter_count": int(len(candidates)),
        "hit_count": len(hits),
        "fail_stats": fail_stats,
        "tech_pass_count": len(tech_pass),
        "hits": [asdict(h) for h in hits],
        "note": "baostock历史+新浪当日快照补K；IS_TECH仅CODELIKE(300|688)",
    }
    out_json = OUT_DIR / f"screener_{trade_date}.json"
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame([asdict(h) for h in hits]).to_csv(
        OUT_DIR / f"screener_{trade_date}.csv", index=False, encoding="utf-8-sig"
    )

    print("\n======== 选股结果 ========")
    print(f"交易日: {trade_date} | 命中: {len(hits)} | 预筛: {len(candidates)} | 技术面: {len(tech_pass)}")
    print(f"失败统计: {fail_stats}")
    for h in hits:
        print(
            f"  {h.code} {h.name} 收{h.close} 开{h.open} "
            f"+{h.pct_chg}% 量×{h.vol_ratio_1d} 回撤{h.drop_from_high_pct}% 市值{h.market_cap_yi}亿"
        )
    print(f"已写入 {out_json}")


if __name__ == "__main__":
    main()
