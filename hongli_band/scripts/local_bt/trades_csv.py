# coding: utf-8
"""把本地回测成交写成国金「操作明细」同款 CSV。"""
from __future__ import annotations

import csv
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any


HEADER = (
    "代码",
    "名称",
    "品种类型",
    "行业",
    "多空",
    "操作时间",
    "操作类型",
    "操作价格",
    "当前价格",
    "盈利",
    "买入权重(%)",
    "当前权重(%)",
    "数量",
    "交易费用",
    "市值",
    "业务类型",
)

# 与 hongli_band/回测记录 终端导出一致
STOCK_META = {
    "600350": ("山东高速", "股票", "交通运输"),
    "601398": ("工商银行", "股票", "银行"),
    "601939": ("建设银行", "股票", "银行"),
    "513530": ("港股通红利ETF华泰柏瑞", "ETF", "其它"),
}


def stock_meta(stock: str) -> tuple[str, str, str, str]:
    raw = str(stock or "").strip().upper()
    code = raw.split(".", 1)[0]
    name, kind, industry = STOCK_META.get(code, (code, "股票", "其它"))
    if code not in STOCK_META and (code.startswith("51") or code.startswith("56") or code.startswith("15")):
        kind = "ETF"
        industry = "其它"
    return code, name, kind, industry


def _fmt_time(when: Any) -> str:
    if when is None:
        return datetime.now().strftime("%Y-%m-%d 15:00:00")
    if hasattr(when, "strftime"):
        return when.strftime("%Y-%m-%d %H:%M:%S")
    digits = "".join(ch for ch in str(when) if ch.isdigit())
    if len(digits) >= 14:
        dt = datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    if len(digits) >= 8:
        dt = datetime.strptime(digits[:8], "%Y%m%d")
        return dt.strftime("%Y-%m-%d 15:00:00")
    return str(when)


def _num(val: float, digits: int) -> str:
    return ("%." + str(int(digits)) + "f") % float(val)


class TradeLedger:
    """FIFO 持仓；买入盈利 0；卖出盈利 = 本笔成交实现盈亏。"""

    def __init__(self, stock: str):
        self.stock = str(stock or "").strip().upper()
        self.code, self.name, self.kind, self.industry = stock_meta(self.stock)
        self._px_digits = 3 if self.kind == "ETF" else 2
        self._lots: deque[dict] = deque()
        self.rows: list[list[str]] = []

    def on_buy(self, vol: int, price: float, when: Any) -> None:
        vol = int(vol)
        price = float(price)
        if vol < 100 or price <= 0:
            return
        self._lots.append({"shares": vol, "price": price})
        self.rows.append(self._row("买入", when, price, vol, 0.0))

    def on_sell(self, vol: int, price: float, when: Any) -> None:
        vol = int(vol)
        price = float(price)
        if vol < 100 or price <= 0:
            return
        remain = vol
        pnl = 0.0
        while remain > 0 and self._lots:
            lot = self._lots[0]
            take = min(int(lot["shares"]), remain)
            pnl += (price - float(lot["price"])) * take
            lot["shares"] = int(lot["shares"]) - take
            remain -= take
            if int(lot["shares"]) <= 0:
                self._lots.popleft()
        self.rows.append(self._row("卖出", when, price, vol, pnl))

    def _row(self, side: str, when: Any, price: float, vol: int, pnl: float) -> list[str]:
        d = self._px_digits
        mv = float(price) * int(vol)
        return [
            self.code,
            self.name,
            self.kind,
            self.industry,
            "-",
            _fmt_time(when),
            side,
            _num(price, d),
            _num(price, d),
            _num(pnl, d),
            "0.00%",
            "0.00%",
            str(int(vol)),
            _num(0.0, d),
            _num(mv, d),
            side,
        ]

    def write(self, path: str | Path) -> Path:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="gbk", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER)
            w.writerows(self.rows)
        return dest


def wrap_fill_hooks(ns: dict, ledger: TradeLedger) -> None:
    orig_buy = ns["_apply_buy_fill"]
    orig_sell = ns["_apply_sell_fill"]

    def _buy(vol, price, opened_at, **extra):
        orig_buy(vol, price, opened_at, **extra)
        ledger.on_buy(vol, price, opened_at)

    def _sell(now, reason, last_hint, filled_vol, mark_half=False, lot_ids=None):
        orig_sell(
            now,
            reason,
            last_hint,
            filled_vol,
            mark_half=mark_half,
            lot_ids=lot_ids,
        )
        ledger.on_sell(filled_vol, last_hint, now)

    ns["_apply_buy_fill"] = _buy
    ns["_apply_sell_fill"] = _sell


def trades_csv_path(log_path: Path) -> Path:
    return log_path.with_name(log_path.stem + "_操作明细.csv")
