# === fband/factors/catalog.py ===
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
    "keltner_vol": {
        "label": "通道内缩量",
        "group": "entry",
        "params": {
            "k": {
                "default": 2.0,
                "percent": False,
                "abbrev": "kvk",
                "label": "通道倍数",
                "axis": 10,
            },
            "ratio": {
                "default": 0.9,
                "percent": True,
                "abbrev": "kvr",
                "label": "通道缩量比例",
                "axis": 11,
            },
            "min_ratio": {
                "default": 0.5,
                "percent": True,
                "abbrev": "kvm",
                "label": "通道缩量下限",
                "axis": 12,
            },
            "vol_n": {
                "default": 10,
                "percent": False,
                "abbrev": "kvn",
                "label": "通道缩量窗口",
                "axis": 13,
            },
            "confirm_days": {
                "default": 2,
                "percent": False,
                "abbrev": "kvc",
                "label": "通道缩量确认日",
                "axis": 14,
            },
        },
    },
    "above_ema": {
        "label": "价在趋势均线上",
        "group": "entry",
        "params": {},
    },
    "scale_arm": {
        "label": "加仓-浮盈持仓周柱门槛",
        "group": "scale",
        "params": {
            "arm": {
                "default": 0.03,
                "percent": True,
                "abbrev": "sa",
                "label": "加仓门槛",
                "axis": 0,
            },
            "bars": {
                "default": 8,
                "percent": False,
                "abbrev": "sab",
                "label": "加仓持仓日",
                "axis": 1,
            },
            "hist_min": {
                "default": -0.01,
                "percent": False,
                "abbrev": "swh",
                "label": "加仓周柱下限",
                "axis": 2,
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
                "default": 2.0,
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
                "default": 2.0,
                "percent": False,
                "abbrev": "atk1",
                "label": "ATR移动保本",
                "kind": "smaller_tighten",
                "off": "le0",
                "axis": 5,
            },
            "k2": {
                "default": 2.0,
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
