# coding: utf-8
"""local_bt 复利回测：动态可部署资金 + 现金账本（不改 QMT deploy）。"""
from __future__ import annotations

from typing import Any, Mapping


def _norm_stock(code: str) -> str:
    return str(code or "").strip().upper()


def _norm_budget_base(raw: Any) -> str:
    s = str(raw or "").strip()
    sl = s.lower()
    if sl in ("fixed", "fix") or s == "固定金额":
        return "fixed"
    return "equity"


def _pos_dict_mv(pos: dict | None) -> float:
    if not isinstance(pos, dict):
        return 0.0
    try:
        cost = float(pos.get("cost") or 0)
        if cost > 0:
            return cost
        shares = int(pos.get("shares") or 0)
        price = float(pos.get("price") or 0)
        if shares > 0 and price > 0:
            return float(shares) * float(price)
    except (TypeError, ValueError):
        return 0.0
    return 0.0


class CompoundWallet:
    """回测现金账本。equity：cap = cash_ratio × (cash + book_mv)；fixed：cap = cash_ratio × TRADE_BUDGET。"""

    def __init__(
        self,
        cash: float,
        *,
        cash_ratio: float = 0.90,
        enabled: bool = True,
        budget_base: str = "equity",
        fixed_amount: float = 0.0,
    ):
        self.cash = float(cash)
        self.initial_cash = float(cash)
        self.cash_ratio = float(cash_ratio)
        self.enabled = bool(enabled)
        self.budget_base = _norm_budget_base(budget_base)
        self.fixed_amount = float(fixed_amount or 0)

    def book_mv(self, ns: dict[str, Any]) -> float:
        a = ns.get("A")
        if a is None:
            return 0.0
        cur = _norm_stock(getattr(a, "stock", ""))
        total = 0.0
        fn = ns.get("_per_stock_map")
        mp = fn() if callable(fn) else {}
        for code, rec in (mp or {}).items():
            if _norm_stock(code) == cur:
                continue
            if isinstance(rec, dict):
                total += _pos_dict_mv(rec.get("_hot_position"))
        total += _pos_dict_mv(getattr(a, "position", None))
        return total

    def equity(self, ns: dict[str, Any]) -> float:
        return float(self.cash) + self.book_mv(ns)

    def deploy_cap(self, ns: dict[str, Any]) -> float:
        if self.budget_base == "fixed":
            amt = float(self.fixed_amount or 0)
            if amt <= 0:
                try:
                    amt = float((ns or {}).get("TRADE_BUDGET") or 0)
                except (TypeError, ValueError):
                    amt = 0.0
            if amt <= 0:
                amt = float(self.initial_cash or 0)
            if amt <= 0:
                return 0.0
            return float(self.cash_ratio) * amt
        e = self.equity(ns)
        if e <= 0:
            return 0.0
        return float(self.cash_ratio) * e

    def snapshot(self, ns: dict[str, Any]) -> dict[str, float]:
        cap = self.deploy_cap(ns)
        eq = self.equity(ns)
        return {"deploy_cap": cap, "equity": eq}

    def on_buy(self, vol: int, price: float) -> None:
        self.cash -= float(vol) * float(price)

    def on_sell(self, vol: int, price: float) -> None:
        self.cash += float(vol) * float(price)


def compound_enabled(overrides: Mapping[str, Any] | None) -> bool:
    if not overrides:
        return False
    return bool(overrides.get("compound_backtest") or overrides.get("COMPOUND_BACKTEST"))


def wallet_cash_from_overrides(overrides: Mapping[str, Any] | None, default_budget: float) -> float:
    if not overrides:
        return float(default_budget)
    raw = overrides.get("wallet_cash")
    if raw is None:
        raw = overrides.get("BT_WALLET_CASH")
    if raw is not None:
        return float(raw)
    return float(default_budget)


def make_wallet(
    ns: dict[str, Any],
    overrides: Mapping[str, Any] | None,
    default_budget: float,
) -> CompoundWallet | None:
    if not compound_enabled(overrides):
        return None
    cash = wallet_cash_from_overrides(overrides, default_budget)
    ratio = float(ns.get("CASH_RATIO") or 0.90)
    raw_base = None
    if overrides:
        raw_base = overrides.get("BUDGET_BASE")
    if raw_base is None:
        raw_base = ns.get("BUDGET_BASE")
    base = _norm_budget_base(raw_base)
    try:
        fixed_amt = float(ns.get("TRADE_BUDGET") or default_budget)
    except (TypeError, ValueError):
        fixed_amt = float(default_budget)
    if overrides and overrides.get("TRADE_BUDGET") is not None:
        try:
            fixed_amt = float(overrides.get("TRADE_BUDGET"))
        except (TypeError, ValueError):
            pass
    return CompoundWallet(
        cash,
        cash_ratio=ratio,
        enabled=True,
        budget_base=base,
        fixed_amount=fixed_amt,
    )


def make_ledger_wallet(
    ns: dict[str, Any],
    overrides: Mapping[str, Any] | None,
    default_budget: float,
) -> tuple[CompoundWallet, bool]:
    """明细列用账本：有复利接交易钱包；无复利也记账，但不改下单 cap。

    返回 (wallet, compound_on)。
    """
    trade = make_wallet(ns, overrides, default_budget)
    if trade is not None:
        return trade, True
    ratio = float(ns.get("CASH_RATIO") or 0.90)
    return CompoundWallet(float(default_budget), cash_ratio=ratio, enabled=True), False


def read_wallet_end(ns: dict[str, Any], wallet: CompoundWallet) -> float:
    return wallet.equity(ns)


def parse_wallet_from_log(text: str) -> dict[str, float | None]:
    out: dict[str, float | None] = {"wallet_cash_start": None, "wallet_cash_end": None}
    for line in str(text or "").splitlines():
        for part in line.split():
            if part.startswith("wallet_start="):
                try:
                    out["wallet_cash_start"] = float(part.split("=", 1)[1])
                except ValueError:
                    pass
            elif part.startswith("wallet_end="):
                try:
                    out["wallet_cash_end"] = float(part.split("=", 1)[1])
                except ValueError:
                    pass
    return out


def install_compound_patch(ns: dict[str, Any], wallet: CompoundWallet) -> None:
    """替换 _trade_budget_cap 为动态 deploy_cap。"""
    orig_cap = ns["_trade_budget_cap"]

    def _cap():
        if wallet.enabled:
            return wallet.deploy_cap(ns)
        return float(orig_cap() or 0)

    ns["_trade_budget_cap"] = _cap
