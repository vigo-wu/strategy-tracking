# === hlband/factors/catalog.py ===
# 叶子登记 / 默认阈值 / 网格轴元数据。运行时写入 RECIPE.factor_params。
# 文件名 = id；_factor_eval_<id> 在 lib/<id>.py。

LEAVES = {
    "pullback_vol": {
        "label": "买点1-缩量回踩强支撑",
        "group": "entry",
        "params": {
            "tol": {
                "default": 0.025,
                "percent": True,
                "abbrev": "mt",
                "label": "回踩容差",
                "axis": 0,
            },
            "ratio": {
                "default": 0.9,
                "percent": True,
                "abbrev": "vpr",
                "label": "缩量回踩比例",
                "axis": 1,
            },
            "vol_n": {
                "default": 10,
                "percent": False,
                "abbrev": "vpn",
                "label": "缩量窗口",
                "axis": 2,
            },
            "confirm_days": {
                "default": 2,
                "percent": False,
                "abbrev": "vpc",
                "label": "缩量确认日",
                "axis": 3,
            },
        },
    },
    "chase": {
        "label": "追高过滤跳过",
        "group": "entry",
        "params": {
            "max_pct": {
                "default": 0.05,
                "percent": True,
                "abbrev": "ch",
                "label": "追高禁开",
                "axis": 6,
            },
        },
    },
    "vol_dry": {
        "label": "无量阴跌禁开",
        "group": "entry",
        "params": {
            "ratio": {
                "default": 0.60,
                "percent": True,
                "abbrev": "vdr",
                "label": "无量阴跌比例",
                "axis": 4,
            },
            "n": {
                "default": 20,
                "percent": False,
                "abbrev": "vdn",
                "label": "无量窗口",
                "axis": 5,
            },
        },
    },
    "w_bias": {
        "label": "周线高位乖离禁开",
        "group": "entry",
        "params": {
            "hard": {
                "default": 0.08,
                "percent": True,
                "abbrev": "wb",
                "label": "周线高位禁开",
                "axis": 7,
            },
        },
    },
    "w_slope": {
        "label": "低位周线MA34未连升禁开",
        "group": "entry",
        "params": {
            "low": {
                "default": 0.02,
                "percent": True,
                "abbrev": "wl",
                "label": "低位乖离",
                "axis": 8,
            },
            "slope_weeks": {
                "default": 2,
                "percent": False,
                "abbrev": "ws",
                "label": "低位斜率周数",
                "axis": 9,
            },
        },
    },
    "weekly_bear": {
        "label": "周线转空强制清仓",
        "label_buy": "周线空头禁开",
        "group": "entry",
        "params": {},
    },
    "weekly_bear_confirm": {
        "label": "周线转空强制清仓",
        "group": "exit",
        "params": {
            "days": {
                "default": 2,
                "percent": False,
                "abbrev": "wbc",
                "label": "周线空确认日",
                "axis": 3,
            },
        },
    },
    "plat_break": {
        "label": "加仓-日线突破前期平台",
        "group": "scale",
        "params": {
            "lookback": {
                "default": 20,
                "percent": False,
                "abbrev": "spl",
                "label": "平台回看",
                "axis": 0,
            },
            "max_range": {
                "default": 0.10,
                "percent": True,
                "abbrev": "spr",
                "label": "平台振幅",
                "axis": 1,
            },
            "break_buf": {
                "default": 0.0,
                "percent": False,
                "abbrev": "spb",
                "label": "平台突破缓冲",
                "axis": 2,
            },
        },
    },
    "w_macd_golden": {
        "label": "加仓-周线MACD金叉柱放大",
        "group": "scale",
        "params": {
            "hist_expand": {
                "default": 1.2,
                "percent": False,
                "abbrev": "she",
                "label": "金叉柱放大",
                "axis": 3,
            },
        },
    },
    "stop_loss": {
        "label": "硬止损",
        "group": "exit",
        "params": {
            "pct": {
                "default": 0.08,
                "percent": True,
                "abbrev": "sl",
                "label": "止损",
                "kind": "smaller_tighten",
                "off": None,
                "axis": 0,
            },
        },
    },
    "atr_stop": {
        "label": "ATR止损",
        "group": "exit",
        "params": {
            "k": {
                "default": 2,
                "percent": False,
                "abbrev": "ask",
                "label": "ATR止损倍数",
                "kind": "smaller_tighten",
                "off": "le0",
                "axis": 4,
            },
        },
    },
    "trail_stop": {
        "label": "卖点1-移动止盈回撤",
        "group": "exit",
        "params": {
            "tiers": {
                "default": [
                    [0.03, 0.06, 0.015, None],
                    [0.06, 0.10, 0.03, 0.03],
                    [0.10, None, 0.04, None],
                ],
                "percent": False,
                "abbrev": "tt",
                "label": "阶梯止盈",
                "kind": "trail_tiers",
                "axis": 1,
            },
        },
    },
    "atr_trail_stop": {
        "label": "ATR移动止盈",
        "group": "exit",
        "params": {
            "k1": {
                "default": 2,
                "percent": False,
                "abbrev": "atk1",
                "label": "ATR移动武装",
                "kind": "smaller_tighten",
                "off": "le0",
                "axis": 5,
            },
            "k2": {
                "default": 2,
                "percent": False,
                "abbrev": "atk2",
                "label": "ATR移动回撤",
                "kind": "smaller_tighten",
                "off": "le0",
                "axis": 6,
            },
        },
    },
    "time_force": {
        "label": "卖点2-时间成本智能平仓",
        "group": "exit",
        "params": {
            "bars": {
                "default": 30,
                "percent": False,
                "abbrev": "tfb",
                "label": "时间成本 BARS",
                "kind": "smaller_tighten",
                "off": "le0",
                "axis": 2,
            },
            "arm": {
                "default": 0.03,
                "percent": True,
                "abbrev": "tfa",
                "label": "时间成本让路",
                "kind": "smaller_loosen",
                "off": "le0",
                "axis": 7,
            },
        },
    },
}


def _leaves_factor_params(leaves=None):
    table = {}
    src = LEAVES if leaves is None else leaves
    for fid, leaf in src.items():
        params = (leaf or {}).get("params") or {}
        if not params:
            continue
        block = {}
        for key, spec in params.items():
            block[key] = spec["default"]
        table[fid] = block
    return table


_rec = globals().get("RECIPE")
if isinstance(_rec, dict):
    _rec["factor_params"] = _leaves_factor_params()
