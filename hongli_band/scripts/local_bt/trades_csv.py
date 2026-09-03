# coding: utf-8
"""把本地回测成交写成国金「操作明细」同款 CSV。"""
from __future__ import annotations

import csv
import json
import re
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
    "可部署资金",
    "组合权益",
)


def _load_stock_meta() -> dict[str, tuple[str, str, str]]:
    """从同目录 stock_meta.json 加载；与 hongli_band/回测记录 终端导出一致。"""
    path = Path(__file__).with_name("stock_meta.json")
    if not path.is_file():
        raise FileNotFoundError(f"stock_meta.json not found: {path}")
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return {str(k): (str(v[0]), str(v[1]), str(v[2])) for k, v in raw.items()}


STOCK_META = _load_stock_meta()


def stock_meta(stock: str) -> tuple[str, str, str, str]:
    raw = str(stock or "").strip().upper()
    code = raw.split(".", 1)[0]
    if re.fullmatch(r"\d+\.0+", code):
        code = code.split(".", 1)[0]
    if code.isdigit():
        code = code.zfill(6)
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


def _pct(num: float, den: float) -> str:
    if den is None or float(den) <= 0:
        return "0.00%"
    return "%.2f%%" % (100.0 * float(num) / float(den))


class TradeLedger:
    """FIFO 持仓；买入盈利 0；卖出盈利 = 本笔成交实现盈亏。"""

    def __init__(self, stock: str):
        self.stock = str(stock or "").strip().upper()
        self.code, self.name, self.kind, self.industry = stock_meta(self.stock)
        self._px_digits = 3 if self.kind == "ETF" else 2
        self._lots: deque[dict] = deque()
        self.rows: list[list[str]] = []

    def on_buy(
        self,
        vol: int,
        price: float,
        when: Any,
        *,
        snap: dict[str, float] | None = None,
        snap_after: dict[str, float] | None = None,
        stock_mv: float | None = None,
    ) -> None:
        vol = int(vol)
        price = float(price)
        if vol < 100 or price <= 0:
            return
        self._lots.append({"shares": vol, "price": price})
        mv = float(price) * int(vol)
        if stock_mv is None:
            stock_mv = sum(int(l["shares"]) * float(l["price"]) for l in self._lots)
        self.rows.append(self._row("买入", when, price, vol, 0.0, snap, snap_after, mv, stock_mv))

    def on_sell(
        self,
        vol: int,
        price: float,
        when: Any,
        *,
        snap: dict[str, float] | None = None,
        snap_after: dict[str, float] | None = None,
        stock_mv: float | None = None,
    ) -> None:
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
        if stock_mv is None:
            stock_mv = sum(int(l["shares"]) * float(l["price"]) for l in self._lots)
        self.rows.append(self._row("卖出", when, price, vol, pnl, snap, snap_after, float(price) * vol, stock_mv))

    def _row(
        self,
        side: str,
        when: Any,
        price: float,
        vol: int,
        pnl: float,
        snap: dict[str, float] | None,
        snap_after: dict[str, float] | None,
        mv: float,
        stock_mv: float,
    ) -> list[str]:
        d = self._px_digits
        deploy = float((snap or {}).get("deploy_cap") or 0)
        eq_before = float((snap or {}).get("equity") or 0)
        eq_after = float((snap_after or {}).get("equity") or eq_before)
        if deploy > 0:
            buy_w = _pct(mv, deploy)
        else:
            buy_w = "0.00%"
        if eq_after > 0:
            cur_w = _pct(stock_mv, eq_after)
        else:
            cur_w = "0.00%"
        cap_s = _num(deploy, 2) if deploy > 0 else ""
        eq_s = _num(eq_after if snap_after else eq_before, 2) if (snap_after or snap) else ""
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
            buy_w,
            cur_w,
            str(int(vol)),
            _num(0.0, d),
            _num(mv, d),
            side,
            cap_s,
            eq_s,
        ]

    def write(self, path: str | Path) -> Path:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="gbk", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER)
            w.writerows(self.rows)
        return dest


class CombinedTradeLedger:
    """组合回放：按当前激活标的写入同一明细表。"""

    def __init__(self, stock_getter):
        self._stock_getter = stock_getter
        self.rows: list[list[str]] = []
        self._lots: dict[str, deque] = {}

    def _ledger(self, stock: str) -> TradeLedger:
        lg = TradeLedger(stock)
        lg.rows = self.rows
        lg._lots = self._lots.setdefault(str(stock).strip().upper(), deque())
        return lg

    def on_buy(
        self,
        vol: int,
        price: float,
        when: Any,
        *,
        snap: dict[str, float] | None = None,
        snap_after: dict[str, float] | None = None,
        stock_mv: float | None = None,
        ns: dict | None = None,
    ) -> None:
        stock = str(self._stock_getter() or "").strip().upper()
        if not stock:
            return
        if stock_mv is None and ns is not None:
            from compound_wallet import _pos_dict_mv  # noqa: WPS433

            stock_mv = _pos_dict_mv(getattr(ns.get("A"), "position", None))
        self._ledger(stock).on_buy(
            vol,
            price,
            when,
            snap=snap,
            snap_after=snap_after,
            stock_mv=stock_mv,
        )

    def on_sell(
        self,
        vol: int,
        price: float,
        when: Any,
        *,
        snap: dict[str, float] | None = None,
        snap_after: dict[str, float] | None = None,
        stock_mv: float | None = None,
        ns: dict | None = None,
    ) -> None:
        stock = str(self._stock_getter() or "").strip().upper()
        if not stock:
            return
        if stock_mv is None and ns is not None:
            from compound_wallet import _pos_dict_mv  # noqa: WPS433

            stock_mv = _pos_dict_mv(getattr(ns.get("A"), "position", None))
        self._ledger(stock).on_sell(
            vol,
            price,
            when,
            snap=snap,
            snap_after=snap_after,
            stock_mv=stock_mv,
        )

    def write(self, path: str | Path) -> Path:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", encoding="gbk", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEADER)
            w.writerows(self.rows)
        return dest


def wrap_fill_hooks(
    ns: dict,
    ledger: TradeLedger | CombinedTradeLedger,
    wallet: Any | None = None,
) -> None:
    orig_buy = ns["_apply_buy_fill"]
    orig_sell = ns["_apply_sell_fill"]

    def _snap_before():
        if wallet is not None and wallet.enabled:
            return wallet.snapshot(ns)
        return None

    def _buy(vol, price, opened_at, **extra):
        snap = _snap_before()
        orig_buy(vol, price, opened_at, **extra)
        if wallet is not None and wallet.enabled:
            wallet.on_buy(vol, price)
        snap_after = _snap_before()
        kw: dict[str, Any] = {"snap": snap, "snap_after": snap_after}
        if isinstance(ledger, CombinedTradeLedger):
            kw["ns"] = ns
        ledger.on_buy(vol, price, opened_at, **kw)

    def _sell(now, reason, last_hint, filled_vol, mark_half=False, lot_ids=None):
        snap = _snap_before()
        orig_sell(
            now,
            reason,
            last_hint,
            filled_vol,
            mark_half=mark_half,
            lot_ids=lot_ids,
        )
        if wallet is not None and wallet.enabled:
            wallet.on_sell(filled_vol, last_hint)
        snap_after = _snap_before()
        kw: dict[str, Any] = {"snap": snap, "snap_after": snap_after}
        if isinstance(ledger, CombinedTradeLedger):
            kw["ns"] = ns
        ledger.on_sell(filled_vol, last_hint, now, **kw)

    ns["_apply_buy_fill"] = _buy
    ns["_apply_sell_fill"] = _sell


def trades_csv_path(log_path: Path) -> Path:
    return log_path.with_name(log_path.stem + "_操作明细.csv")
