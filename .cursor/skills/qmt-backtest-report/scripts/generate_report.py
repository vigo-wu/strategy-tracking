# coding: utf-8
"""QMT 回测日志 → 成交表 + 权益曲线 + 持仓着色 K 线 + Markdown 报告。

用法:
  python generate_report.py --theme hongli_band
  python generate_report.py --log path/to/log.txt --out-dir path/to/dir --tag HlBand

盈亏真源优先：<主题>/report/QMT终端操作明细.csv（引擎成交价/盈亏）；
log 仅提供买卖信号标签与配对骨架。无终端明细时回退 log 自记账价。
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

# 终端导出常见文件名（GBK）
TERMINAL_CSV_NAMES = (
    "QMT终端操作明细.csv",
    "QWT终端操作明细.csv",
    "终端操作明细.csv",
)


def _ymd(s: str) -> str:
    s = str(s).replace("-", "")[:8]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _ymd_compact(s: str | None) -> str | None:
    if not s:
        return None
    digits = re.sub(r"\D", "", str(s))
    return digits[:8] if len(digits) >= 8 else None


def _ts(s: str | None) -> pd.Timestamp | None:
    d = _ymd_compact(s)
    if not d:
        return None
    return pd.Timestamp(d)


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
        r"(?:ALLOW_T0=\s*\S+\s+)?budget=\s*([0-9.]+)"
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
    """按 opened_at 配对 BUY filled / SELL done，再回填 signal/label/执行日。"""
    tag_esc = re.escape(tag)
    stock_esc = re.escape(stock)

    buy_meta = []
    for m in re.finditer(
        rf"{tag_esc}\s+BUY by signal=(\S+)\s+label=([^\s]+)\s+all=([^\s]+)\s+"
        rf"(?:signal_day=(\d+)\s+)?(?:signal_tag=(\d+)\s+)?@open=([0-9.]+)",
        seg,
    ):
        day = str(m.group(4) or m.group(5) or "")[:8]
        buy_meta.append(
            {
                "pos": m.start(),
                "signal": m.group(1),
                "label": m.group(2),
                "signal_day": day,
            }
        )

    sell_meta = []
    for m in re.finditer(
        rf"(?:{tag_esc}\s+(20\d{{6}})\s+[^\n]*\r?\n)?"
        rf"{tag_esc}\s+SELL by signal=(\S+)\s+label=([^\s]+)\s+all=([^\s]+)\s+"
        rf"(?:signal_day=(\d+)\s+)?(?:signal_tag=(\d+)\s+)?@open=([0-9.]+)",
        seg,
    ):
        day = str(m.group(5) or m.group(6) or "")[:8]
        exec_day = str(m.group(1) or day or "")[:8]
        sell_meta.append(
            {
                "pos": m.start(),
                "exec_day": exec_day,
                "signal": m.group(2),
                "label": m.group(3),
                "signal_day": day or exec_day,
            }
        )
    if not sell_meta:
        for m in re.finditer(
            rf"{tag_esc}\s+(20\d{{6}})\s+[^\n]*\r?\n"
            rf"{tag_esc}\s+SELL (\S+)\s+{stock_esc}",
            seg,
        ):
            sell_meta.append(
                {
                    "pos": m.start(),
                    "exec_day": m.group(1),
                    "signal": m.group(2),
                    "label": m.group(2),
                    "signal_day": m.group(1),
                }
            )

    fills = []
    for m in re.finditer(
        rf"{tag_esc}\s+BUY filled \{{'shares': (\d+), 'price': ([0-9.]+), "
        rf"'cost': ([0-9.]+), 'opened_at': '(\d+)'[^}}]*\}}",
        seg,
    ):
        fills.append(
            {
                "pos": m.start(),
                "shares": int(m.group(1)),
                "price": float(m.group(2)),
                "cost": float(m.group(3)),
                "opened_at": m.group(4),
            }
        )

    dones = []
    for m in re.finditer(
        rf"{tag_esc}\s+SELL done (\S+)\s+last=\s*([0-9.]+)\s+"
        rf"cleared \{{'shares': (\d+), 'price': ([0-9.]+), 'cost': ([0-9.]+), "
        rf"'opened_at': '(\d+)'[^}}]*\}}",
        seg,
    ):
        dones.append(
            {
                "pos": m.start(),
                "signal": m.group(1),
                "price": float(m.group(2)),
                "shares": int(m.group(3)),
                "buy_price": float(m.group(4)),
                "cost": float(m.group(5)),
                "opened_at": m.group(6),
            }
        )

    sell_by_open = {d["opened_at"]: d for d in dones}
    trades = []
    for i, b in enumerate(fills, 1):
        s = sell_by_open.get(b["opened_at"])
        if s is None:
            continue
        bm = next((x for x in reversed(buy_meta) if x["pos"] < b["pos"]), None)
        sm = next((x for x in reversed(sell_meta) if x["pos"] < s["pos"]), None)
        open_day = b["opened_at"][:8]
        exec_day = (sm or {}).get("exec_day") or open_day
        s_sig = (sm or {}).get("signal") or s["signal"]
        s_lab = (sm or {}).get("label") or s_sig
        s_sday = (sm or {}).get("signal_day") or exec_day
        hold_days = None
        try:
            hold_days = (
                datetime.strptime(str(exec_day)[:8], "%Y%m%d")
                - datetime.strptime(open_day, "%Y%m%d")
            ).days
        except Exception:
            pass
        b_price = float(b["price"])
        s_price = float(s["price"])
        shares = int(b["shares"])
        pnl = (s_price - b_price) * shares
        ret = (s_price - b_price) / b_price * 100.0 if b_price else 0.0
        trades.append(
            {
                "i": i,
                "buy_signal": (bm or {}).get("signal") or "-",
                "buy_label": (bm or {}).get("label") or "-",
                "buy_signal_day": (bm or {}).get("signal_day") or open_day,
                "buy_open_day": open_day,
                "buy_price": b_price,
                "shares": shares,
                "cost": float(b["cost"]),
                "sell_signal": s_sig,
                "sell_label": s_lab,
                "sell_signal_day": s_sday,
                "sell_exec_day": str(exec_day)[:8],
                "sell_price": s_price,
                "hold_calendar_days": hold_days,
                "ret_pct": ret,
                "pnl": pnl,
            }
        )
    return trades


_CODE_COL_ALIASES = ("代码", "证券代码", "股票代码", "标的")


def normalize_terminal_code(val: object) -> str:
    """操作明细代码规范化：补前导零（002001），去掉市场后缀。

    pandas 把 002001 读成 int/float 2001 时也能还原为 6 位代码。
    """
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(val, bool):
        return ""
    if isinstance(val, (int, float)):
        try:
            fv = float(val)
            iv = int(fv)
            if fv == float(iv):
                s = str(iv)
            else:
                s = str(val).strip()
        except Exception:
            s = str(val).strip()
    else:
        s = str(val).strip().upper()
        if not s or s in ("NAN", "NONE", "NAT"):
            return ""
        # float 被写成 "2001.0"
        if re.fullmatch(r"\d+\.0+", s):
            s = s.split(".", 1)[0]
    if "." in s:
        s = s.split(".", 1)[0]
    if s.isdigit():
        s = s.zfill(6)
    return s


def _coerce_code_columns(df: pd.DataFrame) -> pd.DataFrame:
    """就地把代码列规范为 6 位字符串，避免导出/展示丢前导零。"""
    if df is None or df.empty:
        return df
    targets: list = []
    for col in df.columns:
        if str(col).strip() in _CODE_COL_ALIASES:
            targets.append(col)
    # 国金固定列序：列名乱码时首列仍是代码
    if not targets and df.shape[1] >= 13:
        targets.append(df.columns[0])
    for col in targets:
        df[col] = df[col].map(normalize_terminal_code)
    return df


def _read_csv_auto(path: Path) -> pd.DataFrame:
    last_err: Exception | None = None
    for enc in ("gbk", "gb18030", "utf-8-sig", "utf-8"):
        try:
            df = pd.read_csv(path, encoding=enc)
            return _coerce_code_columns(df)
        except Exception as e:
            last_err = e
    raise RuntimeError(f"cannot read {path}: {last_err}")


def _col_by_aliases(df: pd.DataFrame, *aliases: str) -> str | None:
    cols = {str(c).strip(): c for c in df.columns}
    for a in aliases:
        if a in cols:
            return cols[a]
    # 容错：列名乱码时按位置（国金导出固定顺序）
    return None


def _apply_bonus_pending(pending: list[dict], add_shares: int) -> None:
    """送转：按股数比例把新增股摊到未平买入 lot，总成本守恒。"""
    add = int(add_shares or 0)
    if add < 1 or not pending:
        return
    old_total = sum(int(x.get("shares") or 0) for x in pending)
    if old_total <= 0:
        return
    assigned = 0
    n = len(pending)
    for i, lot in enumerate(pending):
        old_sh = int(lot.get("shares") or 0)
        try:
            old_px = float(lot.get("price") or 0)
        except (TypeError, ValueError):
            old_px = 0.0
        old_cost = old_px * old_sh
        if i == n - 1:
            extra = max(add - assigned, 0)
        else:
            extra = int(round(add * old_sh / float(old_total)))
            assigned += extra
        new_sh = old_sh + extra
        lot["shares"] = new_sh
        if new_sh > 0 and old_cost > 0:
            lot["price"] = old_cost / float(new_sh)


def parse_terminal_rounds(path: Path, *, quiet: bool = False) -> list[dict]:
    """解析 QMT「操作明细」CSV → 买卖轮次（按代码各自 FIFO）。

    卖出若吃掉多笔买入，按买入 lot 拆成多轮（保留各笔买入日/买价）；
    盈亏按股数分摊卖出行「盈利」（末笔吃尾差）。
    「送转」行按成本守恒给未平买入加股缩价。
    quiet=True 时不向 stderr 刷 open-buy/orphan 警告（批量扫描/打分用）。
    """
    df = _read_csv_auto(path)
    if df.empty:
        return []

    c_time = _col_by_aliases(df, "操作时间", "成交时间", "时间")
    c_side = _col_by_aliases(df, "操作类型", "买卖方向", "方向")
    c_price = _col_by_aliases(df, "操作价格", "成交价格", "成交价", "价格")
    c_pnl = _col_by_aliases(df, "盈利", "盈亏", "实现盈亏")
    c_shares = _col_by_aliases(df, "数量", "成交数量", "股数")
    c_code = _col_by_aliases(df, "代码", "证券代码", "股票代码", "标的")
    # 固定列序回退：代码,名称,...,操作时间(5),操作类型(6),操作价格(7),...,盈利(9),...,数量(12)
    if c_time is None and df.shape[1] >= 13:
        cols = list(df.columns)
        c_code = c_code or cols[0]
        c_time, c_side, c_price, c_pnl, c_shares = cols[5], cols[6], cols[7], cols[9], cols[12]

    if not all([c_time, c_side, c_price, c_shares]):
        raise RuntimeError(f"terminal csv missing columns: {list(df.columns)}")

    rows = []
    for _, r in df.iterrows():
        day = _ymd_compact(r[c_time])
        if not day:
            continue
        side_raw = str(r[c_side]).strip()
        if "买" in side_raw:
            side = "buy"
        elif "卖" in side_raw:
            side = "sell"
        elif "送转" in side_raw:
            side = "bonus"
        else:
            continue
        try:
            price = float(r[c_price]) if pd.notna(r[c_price]) else 0.0
            shares = int(float(r[c_shares]))
        except Exception:
            continue
        pnl = None
        if c_pnl is not None and pd.notna(r[c_pnl]):
            try:
                pnl = float(r[c_pnl])
            except Exception:
                pnl = None
        code = ""
        if c_code is not None and pd.notna(r[c_code]):
            code = normalize_terminal_code(r[c_code])
        rows.append(
            {
                "day": day,
                "side": side,
                "price": price,
                "shares": shares,
                "pnl": pnl,
                "code": code,
                "raw_price": price,
            }
        )

    rounds: list[dict] = []
    # 按代码分队列，避免组合明细跨票 FIFO 错配（假收益% / 价格对不上盈利）
    pending_by_code: dict[str, list[dict]] = {}
    for r in rows:
        code = str(r.get("code") or "")
        if r["side"] == "buy":
            pending_by_code.setdefault(code, []).append(r)
            continue
        if r["side"] == "bonus":
            _apply_bonus_pending(pending_by_code.get(code) or [], int(r["shares"]))
            continue
        pending_buys = pending_by_code.get(code) or []
        if not pending_buys:
            if not quiet:
                print(
                    f"warn: orphan sell {r['day']} code={code or '-'} in terminal csv",
                    file=sys.stderr,
                )
            continue
        sell_p = float(r["price"])
        remain_sh = int(r["shares"])
        taken: list[dict] = []
        while remain_sh >= 100 and pending_buys:
            b = pending_buys[0]
            bsh = int(b["shares"])
            if bsh <= remain_sh:
                taken.append(pending_buys.pop(0))
                remain_sh -= bsh
            else:
                part = dict(b)
                part["shares"] = remain_sh
                taken.append(part)
                pending_buys[0] = dict(b)
                pending_buys[0]["shares"] = bsh - remain_sh
                remain_sh = 0
        if code in pending_by_code and not pending_by_code[code]:
            pending_by_code.pop(code, None)
        if not taken:
            if not quiet:
                print(
                    f"warn: orphan sell {r['day']} code={code or '-'} in terminal csv",
                    file=sys.stderr,
                )
            continue
        tot_sh = sum(int(x["shares"]) for x in taken)
        sh = int(r["shares"] or tot_sh)
        if tot_sh != int(r["shares"]) and not quiet:
            print(
                f"warn: shares mismatch buys {tot_sh} vs sell {r['day']}x{r['shares']}"
                f" code={code or '-'}",
                file=sys.stderr,
            )
        # 按买入 lot 拆轮次：保留各笔买入日/买价，避免加仓合并后信号与买入日错配
        sell_pnl = r["pnl"]
        allocated = 0.0
        for i, lot in enumerate(taken):
            lot_sh = int(lot["shares"])
            buy_p = float(lot["price"])
            if sell_pnl is None:
                lot_pnl = (sell_p - buy_p) * lot_sh
            elif i == len(taken) - 1:
                lot_pnl = float(sell_pnl) - allocated
            else:
                lot_pnl = float(sell_pnl) * (lot_sh / float(sh)) if sh else 0.0
                allocated += lot_pnl
            ret = (sell_p - buy_p) / buy_p * 100.0 if buy_p else 0.0
            raw_px = lot.get("raw_price", buy_p)
            try:
                raw_px = float(raw_px)
            except (TypeError, ValueError):
                raw_px = buy_p
            round_row = {
                "buy_open_day": lot["day"],
                "sell_exec_day": r["day"],
                "buy_price": buy_p,
                "buy_price_raw": raw_px,
                "sell_price": sell_p,
                "shares": lot_sh,
                "cost": round(buy_p * lot_sh, 2),
                "pnl": float(lot_pnl),
                "ret_pct": ret,
            }
            if code:
                round_row["stock"] = code
            rounds.append(round_row)
    open_left = sum(len(v) for v in pending_by_code.values())
    if open_left and not quiet:
        print(f"warn: {open_left} open buy(s) left in terminal csv", file=sys.stderr)
    return rounds


def find_terminal_csv(out_dir: Path, theme_dir: Path | None, explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            raise SystemExit(f"terminal csv not found: {p}")
        return p.resolve()
    search = []
    if out_dir:
        search.append(out_dir)
    if theme_dir:
        search.append(theme_dir)
        search.append(theme_dir / "report")
    seen: set[Path] = set()
    for d in search:
        d = d.resolve()
        if d in seen or not d.is_dir():
            continue
        seen.add(d)
        for name in TERMINAL_CSV_NAMES:
            cand = d / name
            if cand.is_file():
                return cand
        # 模糊：*操作明细*.csv / *terminal*trades*
        for cand in sorted(d.glob("*操作明细*.csv")) + sorted(d.glob("*terminal*.csv")):
            if cand.is_file():
                return cand
    return None


def apply_terminal_pnl(log_trades: list[dict], rounds: list[dict]) -> tuple[list[dict], dict]:
    """用终端轮次覆盖价格/盈亏；保留 log 的信号标签。按日期+股数对齐，失败则按序对齐。"""
    if not rounds:
        return log_trades, {"source": "log", "matched": 0, "n_terminal": 0}

    used = [False] * len(rounds)
    merged: list[dict] = []
    matched = 0
    seq_fallback = 0

    def _pick(t: dict) -> int | None:
        bday = _ymd_compact(t.get("buy_open_day"))
        sday = _ymd_compact(t.get("sell_exec_day"))
        sh = int(t.get("shares") or 0)
        # 严格：买日+卖日+股数
        for i, r in enumerate(rounds):
            if used[i]:
                continue
            if r["buy_open_day"] == bday and r["sell_exec_day"] == sday and r["shares"] == sh:
                return i
        # 次严：买日+股数
        for i, r in enumerate(rounds):
            if used[i]:
                continue
            if r["buy_open_day"] == bday and r["shares"] == sh:
                return i
        return None

    for t in log_trades:
        idx = _pick(t)
        if idx is None:
            # 顺序回退：第 i 笔
            i_ord = len(merged)
            if i_ord < len(rounds) and not used[i_ord]:
                idx = i_ord
                seq_fallback += 1
            else:
                # 找不到终端轮次：保留 log 价并标记
                nt = dict(t)
                nt["price_source"] = "log"
                merged.append(nt)
                continue
        used[idx] = True
        r = rounds[idx]
        nt = dict(t)
        nt["buy_open_day"] = r["buy_open_day"]
        nt["sell_exec_day"] = r["sell_exec_day"]
        nt["buy_price"] = r["buy_price"]
        nt["sell_price"] = r["sell_price"]
        nt["shares"] = r["shares"]
        nt["cost"] = r["cost"]
        nt["pnl"] = r["pnl"]
        nt["ret_pct"] = r["ret_pct"]
        try:
            nt["hold_calendar_days"] = (
                datetime.strptime(r["sell_exec_day"], "%Y%m%d")
                - datetime.strptime(r["buy_open_day"], "%Y%m%d")
            ).days
        except Exception:
            pass
        nt["price_source"] = "terminal"
        nt["i"] = len(merged) + 1
        merged.append(nt)
        matched += 1

    # 终端多出的轮次（log 未覆盖）——仍入库，信号标为未知
    for i, r in enumerate(rounds):
        if used[i]:
            continue
        merged.append(
            {
                "i": len(merged) + 1,
                "buy_signal": "-",
                "buy_label": "-",
                "buy_signal_day": r["buy_open_day"],
                "buy_open_day": r["buy_open_day"],
                "buy_price": r["buy_price"],
                "shares": r["shares"],
                "cost": r["cost"],
                "sell_signal": "-",
                "sell_label": "-",
                "sell_signal_day": r["sell_exec_day"],
                "sell_exec_day": r["sell_exec_day"],
                "sell_price": r["sell_price"],
                "hold_calendar_days": None,
                "ret_pct": r["ret_pct"],
                "pnl": r["pnl"],
                "price_source": "terminal_only",
            }
        )

    for i, t in enumerate(merged, 1):
        t["i"] = i

    info = {
        "source": "terminal",
        "matched": matched,
        "n_terminal": len(rounds),
        "n_log": len(log_trades),
        "seq_fallback": seq_fallback,
        "unmatched_log": sum(1 for t in merged if t.get("price_source") == "log"),
        "terminal_only": sum(1 for t in merged if t.get("price_source") == "terminal_only"),
    }
    return merged, info


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


def compute_stats(
    meta: dict, trades: list[dict], diag: dict, price_info: dict | None = None
) -> dict:
    rets = [t["ret_pct"] for t in trades]
    pnls = [t["pnl"] for t in trades]
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    buy_c = Counter(t["buy_signal"] for t in trades)
    sell_c = Counter(t["sell_signal"] for t in trades)
    return {
        "meta": meta,
        "diag": diag,
        "price_info": price_info or {"source": "log"},
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
        2, 1, figsize=(48, 7), sharex=True, gridspec_kw={"height_ratios": [3.2, 1], "hspace": 0.05}
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
    y_lo = float(df["Low"].min())
    y_hi = float(df["High"].max())
    y_pad = (y_hi - y_lo) * 0.08
    # 为下方 B/S 标注（约 20pt）预留下方空间
    ax.set_ylim(y_lo - y_pad * 1.2, y_hi + y_pad)

    date_to_i = {d: i for i, d in enumerate(df.index)}
    mark_offset_pts = -20  # B/S 在 K 线最低点下方约 20 点

    def _mark_bs(ax_, idx, label, color):
        low_px = float(df.iloc[idx]["Low"])
        # 虚线：K 线最低点 → 标注位置；标注落在最低点正下方
        ax_.annotate(
            label,
            xy=(idx, low_px),
            xytext=(0, mark_offset_pts),
            textcoords="offset points",
            ha="center",
            va="top",
            color=color,
            fontsize=10,
            fontweight="bold",
            zorder=6,
            arrowprops={
                "arrowstyle": "-",
                "linestyle": "--",
                "color": color,
                "linewidth": 0.9,
                "shrinkA": 0,
                "shrinkB": 2,
            },
        )

    for t in trades:
        bd = nearest_bar(df, _ts(t["buy_open_day"]))
        sd = nearest_bar(df, _ts(t["sell_exec_day"] or t["sell_signal_day"]))
        if bd is not None and bd in date_to_i:
            _mark_bs(ax, date_to_i[bd], "B", COLOR_BUY_MARK)
        if sd is not None and sd in date_to_i:
            _mark_bs(ax, date_to_i[sd], "S", COLOR_SELL_MARK)

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
    pi = stats.get("price_info") or {}
    trades = stats["trades"]
    today = date.today().isoformat()
    wr = stats["win_rate"]
    price_src = pi.get("source") or "log"
    if price_src == "terminal":
        pnl_note = (
            "盈亏/成交价以 **QMT 终端操作明细** 为真源（引擎 `passorder` 结算）；"
            "买卖信号标签来自 log。终端「盈利」字段优先，否则用（卖价−买价）×股数。"
        )
        src_row = f"| 盈亏真源 | **终端操作明细** `{paths.get('terminal_name', '')}` |"
    else:
        pnl_note = (
            "未找到终端操作明细，盈亏回退为 log 自记账价（多为前复权开盘），"
            "**可能与终端结算不一致**。建议导出 `QMT终端操作明细.csv` 至 `report/` 后重跑。"
        )
        src_row = "| 盈亏真源 | log 自记账（回退） |"
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
        f"| 日志来源 | `{paths.get('log_name', 'log.txt')}`（信号标签） |",
        src_row,
        f"| 报告日期 | {today} |",
        f"| 生成方式 | `qmt-backtest-report` 自动生成 |",
        "",
        "---",
        "",
        "## 1. 结论摘要",
        "",
        f"本轮回测 **{stats['n_buy']} 买 {stats['n_sell']} 卖**，合计盈亏约 "
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
        pnl_note,
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
        f"**合计盈亏：{stats['sum_pnl']:+,.2f} 元**",
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
    ]
    if paths.get("terminal_name"):
        lines.append(
            f"- 终端操作明细：[`{paths['terminal_name']}`](./{paths['terminal_name']})"
        )
    lines += [
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
    ap.add_argument(
        "--terminal-csv",
        default=None,
        help="QMT 终端操作明细.csv；默认在 report/ 下自动查找",
    )
    ap.add_argument(
        "--no-terminal",
        action="store_true",
        help="强制不用终端明细，仅用 log 自记账价",
    )
    ap.add_argument("--tag", default=None, help="日志前缀，如 HlBand；默认从 init 行推断")
    ap.add_argument("--ver", default=None, help="如 v1.2；默认取末次 init")
    ap.add_argument("--title", default=None, help="报告标题")
    ap.add_argument("--no-kline", action="store_true", help="跳过行情拉取与 K 线")
    args = ap.parse_args(argv)

    theme_dir: Path | None = None
    if args.theme:
        theme_dir = resolve_theme(args.theme)
        log_path = Path(args.log).resolve() if args.log else theme_dir / "log.txt"
        out_dir = Path(args.out_dir).resolve() if args.out_dir else theme_dir / "report"
    elif args.log:
        log_path = Path(args.log).resolve()
        out_dir = Path(args.out_dir).resolve() if args.out_dir else log_path.parent / "report"
        theme_dir = log_path.parent
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
    log_trades = parse_trades(seg, tag, stock)
    diag = parse_diag(seg, tag)
    # interrupt 噪声常在会话前
    diag["interrupt_noise"] = "KeyboardInterrupt" in text[:3000]

    price_info: dict = {"source": "log"}
    trades = log_trades
    terminal_path: Path | None = None
    if not args.no_terminal:
        terminal_path = find_terminal_csv(out_dir, theme_dir, args.terminal_csv)
        if terminal_path is not None:
            rounds = parse_terminal_rounds(terminal_path)
            trades, price_info = apply_terminal_pnl(log_trades, rounds)
            price_info["terminal_csv"] = str(terminal_path)
            print(
                f"price source=terminal file={terminal_path.name} "
                f"matched={price_info.get('matched')}/{price_info.get('n_terminal')} "
                f"log={price_info.get('n_log')}"
            )
        else:
            print("price source=log (no QMT终端操作明细.csv found under report/)", file=sys.stderr)

    stats = compute_stats(meta, trades, diag, price_info)

    prefix = tag.lower()
    paths = {
        "equity": out_dir / f"{prefix}_equity.png",
        "kline": out_dir / f"{prefix}_trades_kline.png",
        "csv": out_dir / f"{prefix}_trades.csv",
        "json": out_dir / f"{prefix}_report_stats.json",
        "md": out_dir / "回测分析报告.md",
        "log_name": log_path.name,
        "terminal_name": terminal_path.name if terminal_path else "",
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
        f"done: trades={len(trades)} sum_pnl={stats['sum_pnl']:+.2f} "
        f"win_rate={stats['win_rate']}% price_source={price_info.get('source')}"
    )


if __name__ == "__main__":
    main()
