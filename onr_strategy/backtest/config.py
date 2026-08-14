# coding: utf-8
"""v0.1 回测冻结参数。P1–P12 提案在此生效；大单默认关闭（P12）。"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Tuple


SPEC_VER = "v0.1"
EXIT_MODES = ("open", "rules", "next_close")


@dataclass(frozen=True)
class OnrConfig:
    spec_ver: str = SPEC_VER

    ipo_trading_days: int = 60
    adv_days: int = 20
    adv_min_amount: float = 1.5e8
    float_cap_min: float = 30e8
    float_cap_max: float = 150e8
    exclude_bj: bool = True

    t_decision: int = 1445
    t_recheck: int = 1450
    t_tail_start: int = 1430
    t_open: int = 930
    t_flat_deadline: int = 945
    t_low_confirm: int = 935
    t_force_exit: int = 1000

    ret_min: float = 0.03
    ret_max: float = 0.06
    shadow_max: float = 0.015
    momentum_min: float = 0.008
    pullback_max: float = 0.005
    vol_ratio_min: float = 1.5
    large_buy_min: float = 0.40
    industry_top_q: float = 0.15
    index_dump_ret: float = -0.004
    index_dump_vol_ratio: float = 1.5
    index_codes: Tuple[str, ...] = ("000001.SH", "399006.SZ")

    use_ma: bool = True
    use_ret_window: bool = True
    use_shadow: bool = True
    use_momentum: bool = True
    use_pullback: bool = True
    use_vol_ratio: bool = True
    use_large_order: bool = False
    use_industry: bool = False
    use_index_filter: bool = True
    use_recheck_1450: bool = True
    index_missing_policy: str = "pass"

    max_names: int = 3
    weight_per_name: float = 0.125
    lot_size: int = 100
    init_cash: float = 1_000_000.0

    commission: float = 0.00025
    stamp_sell: float = 0.0005
    buy_impact: float = 0.0

    exit_mode: str = "rules"
    high_open: float = 0.005
    low_open: float = -0.005
    stop_from_cost: float = 0.02
    flat_pump_ret: float = 0.01
    max_hold_days: int = 3

    baseline_seed: int = 42

    def with_exit(self, mode: str) -> "OnrConfig":
        if mode not in EXIT_MODES:
            raise ValueError("exit_mode must be one of %s" % (EXIT_MODES,))
        return replace(self, exit_mode=mode)

    def disable(self, *names: str) -> "OnrConfig":
        kw = {}
        for name in names:
            key = name.strip()
            if not key:
                continue
            if key.startswith("use_"):
                attr = key
            else:
                attr = "use_" + key
            if not hasattr(self, attr):
                raise ValueError("unknown factor flag: %s" % key)
            kw[attr] = False
        return replace(self, **kw)


def parse_disable(text: str) -> Tuple[str, ...]:
    if not text:
        return ()
    return tuple(p.strip() for p in text.split(",") if p.strip())
