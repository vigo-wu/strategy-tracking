# coding: utf-8
"""网格过门配置：绝对合格线 + 相对 base；侧栏/spec 可配、逐项启用。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

EPS_GATE = 1e-6

_RULE_KEYS = (
    "calmar",
    "max_dd",
    "oos_sharpe",
    "n_trades",
    "win_rate",
    "profit_factor",
)


def default_gate() -> dict[str, Any]:
    return {
        "relative_to_base": True,
        "calmar_same_sign": False,
        "calmar": {"enabled": False, "min": 1.5},
        "max_dd": {"enabled": True, "floor": -0.10},
        "oos_sharpe": {"enabled": True, "min": 0.8},
        "n_trades": {"enabled": False, "min": 1, "vs_base_ratio": 0.5},
        "win_rate": {"enabled": True, "min": 45.0},
        "profit_factor": {"enabled": True, "min": 1.5},
    }


def _as_bool(raw: Any, default: bool) -> bool:
    if raw is None:
        return bool(default)
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return bool(default)


def _as_float(raw: Any, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _as_int(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def fill_gate(raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """缺字段回落默认；不抛错。"""
    out = default_gate()
    src = raw if isinstance(raw, Mapping) else {}
    # 允许嵌套在 {"gate": {...}}
    if "gate" in src and isinstance(src.get("gate"), Mapping) and "calmar" not in src:
        src = src["gate"]  # type: ignore[assignment]
    out["relative_to_base"] = _as_bool(src.get("relative_to_base"), out["relative_to_base"])
    out["calmar_same_sign"] = _as_bool(src.get("calmar_same_sign"), out["calmar_same_sign"])
    for key in _RULE_KEYS:
        base_rule = dict(out[key])
        rule_src = src.get(key)
        if not isinstance(rule_src, Mapping):
            continue
        base_rule["enabled"] = _as_bool(rule_src.get("enabled"), base_rule.get("enabled", True))
        if key == "max_dd":
            if "floor" in rule_src:
                base_rule["floor"] = _as_float(rule_src.get("floor"), base_rule["floor"])
            elif "pct" in rule_src:
                # 正百分数 10 → floor -0.10
                pct = abs(_as_float(rule_src.get("pct"), 10.0))
                base_rule["floor"] = -pct / 100.0
        elif key == "n_trades":
            base_rule["min"] = _as_int(rule_src.get("min"), base_rule["min"])
            base_rule["vs_base_ratio"] = _as_float(
                rule_src.get("vs_base_ratio"), base_rule.get("vs_base_ratio", 0.5)
            )
        else:
            base_rule["min"] = _as_float(rule_src.get("min"), base_rule["min"])
        out[key] = base_rule
    return out


def validate_gate(gate: Mapping[str, Any]) -> dict[str, Any]:
    filled = fill_gate(gate)
    if filled["calmar"]["min"] < 0:
        raise ValueError("gate.calmar.min 不能为负")
    if filled["max_dd"]["floor"] > 0:
        raise ValueError("gate.max_dd.floor 应为 ≤0（如 -0.10）")
    if filled["n_trades"]["min"] < 0:
        raise ValueError("gate.n_trades.min 不能为负")
    if filled["n_trades"]["vs_base_ratio"] < 0:
        raise ValueError("gate.n_trades.vs_base_ratio 不能为负")
    if filled["win_rate"]["min"] < 0 or filled["win_rate"]["min"] > 100:
        raise ValueError("gate.win_rate.min 应在 0–100")
    if filled["profit_factor"]["min"] < 0:
        raise ValueError("gate.profit_factor.min 不能为负")
    return filled


def any_absolute_enabled(gate: Mapping[str, Any]) -> bool:
    g = fill_gate(gate)
    return any(bool(g[k].get("enabled")) for k in _RULE_KEYS)


def load_gate_from_sweep(root: Any, override: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """override 优先，否则 freeze/spec 的 gate，再默认。"""
    if override is not None:
        return validate_gate(override)
    from pathlib import Path

    root_p = Path(root)
    for name in ("freeze.json", "spec.json"):
        path = root_p / name
        if not path.is_file():
            continue
        try:
            data = json_loads_safe(path)
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get("gate"), dict):
            return validate_gate(data["gate"])
    return validate_gate(None)


def json_loads_safe(path: Any) -> Any:
    import json
    from pathlib import Path

    return json.loads(Path(path).read_text(encoding="utf-8"))


def gate_for_json(gate: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(fill_gate(gate))
