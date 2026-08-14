# coding: utf-8
"""Validate QMT formulaLayout XML (panel.xml) against qmt-param-panel rules.

Usage:
  python .cursor/skills/qmt-param-panel/scripts/validate_panel.py path/to/panel.xml
  python .cursor/skills/qmt-param-panel/scripts/validate_panel.py panel.xml --config config.py
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ALLOWED_TYPES = frozenset({"intput", "combo", "radio", "checkBox"})
BIND_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FORBIDDEN_BINDS = frozenset(
    {
        "account",
        "accountType",
        "STATE_FILE",
        "LOG_DIR",
        "ACCOUNT_ID",
        "STRATEGY_NAME",
        "STRATEGY_VER",
        "_ORDER_FILLED",
        "_ORDER_DEAD",
    }
)


def _err(msg: str, errors: list[str]) -> None:
    errors.append(msg)


def parse_panel_binds(config_text: str) -> list[tuple[str, str, str]] | None:
    """Return PANEL_BINDS list or None if the name is absent."""
    try:
        tree = ast.parse(config_text)
    except SyntaxError as e:
        raise SystemExit("config.py parse error: %s" % e)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "PANEL_BINDS" in names:
                try:
                    raw = ast.literal_eval(node.value)
                except (ValueError, TypeError) as e:
                    raise SystemExit("PANEL_BINDS must be a literal tuple: %s" % e)
                out = []
                for row in raw:
                    if not (isinstance(row, (tuple, list)) and len(row) == 3):
                        raise SystemExit("PANEL_BINDS row must be (bind, const, kind)")
                    out.append((str(row[0]), str(row[1]), str(row[2])))
                return out
    return None


def validate(xml_path: Path, config_path: Path | None) -> list[str]:
    errors: list[str] = []
    text = xml_path.read_text(encoding="utf-8-sig")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return ["XML parse error: %s" % e]

    tag = root.tag.split("}")[-1]
    if tag != "TCStageLayout":
        _err("root must be TCStageLayout, got %s" % tag, errors)

    def _local(el):
        return el.tag.split("}")[-1]

    controls = [el for el in root if _local(el) == "control"]
    if len(controls) != 1:
        _err("need exactly 1 <control> (QMT reads only the first); got %d" % len(controls), errors)
    variables = []
    for c in controls[:1]:
        variables.extend(el for el in c if _local(el) == "variable")
    if len(variables) != 1:
        _err("need exactly 1 <variable> under <control>; got %d" % len(variables), errors)

    items = []
    for el in root.iter():
        if el.tag.split("}")[-1] == "item":
            items.append(el)
    if not items:
        _err("no <item> found", errors)

    binds: list[str] = []
    for el in items:
        bind = (el.get("bind") or "").strip()
        name = (el.get("name") or "").strip()
        typ = (el.get("type") or "").strip()
        value = el.get("value")
        if not bind:
            _err("item missing bind (name=%r)" % name, errors)
            continue
        if bind in FORBIDDEN_BINDS:
            _err("forbidden bind %s" % bind, errors)
        if not BIND_RE.match(bind):
            _err("bind must be ASCII identifier: %r" % bind, errors)
        if bind in binds:
            _err("duplicate bind %s" % bind, errors)
        binds.append(bind)
        if not name:
            _err("item %s missing name" % bind, errors)
        if value is None:
            _err("item %s missing value" % bind, errors)
        if typ not in ALLOWED_TYPES:
            _err("item %s type %r not in %s" % (bind, typ, sorted(ALLOWED_TYPES)), errors)
        if typ in ("combo", "radio"):
            lst = (el.get("list") or "").strip()
            if not lst:
                _err("item %s type=%s needs list=" % (bind, typ), errors)
            elif value is not None and str(value) not in [x.strip() for x in lst.split(",")]:
                _err("item %s value %r not in list %r" % (bind, value, lst), errors)
        if typ == "checkBox" and value is not None and str(value) not in ("True", "False"):
            _err("item %s checkBox value must be True or False, got %r" % (bind, value), errors)

    if config_path is not None:
        cfg = parse_panel_binds(config_path.read_text(encoding="utf-8-sig"))
        if cfg is None:
            _err("config.py has no PANEL_BINDS", errors)
        else:
            cfg_binds = [r[0] for r in cfg]
            xml_set, cfg_set = set(binds), set(cfg_binds)
            for b in sorted(xml_set - cfg_set):
                _err("XML bind %s missing from PANEL_BINDS" % b, errors)
            for b in sorted(cfg_set - xml_set):
                _err("PANEL_BINDS %s missing from XML" % b, errors)
            if len(cfg_binds) != len(set(cfg_binds)):
                _err("duplicate bind in PANEL_BINDS", errors)
            for bind, const, kind in cfg:
                if kind not in ("bool", "int", "float", "str"):
                    _err("PANEL_BINDS %s kind %r invalid" % (bind, kind), errors)
                if not BIND_RE.match(const):
                    _err("PANEL_BINDS const not identifier: %r" % const, errors)

    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate QMT panel.xml")
    ap.add_argument("xml", type=Path)
    ap.add_argument("--config", type=Path, default=None)
    args = ap.parse_args()
    if not args.xml.is_file():
        raise SystemExit("not a file: %s" % args.xml)
    if args.config is not None and not args.config.is_file():
        raise SystemExit("not a file: %s" % args.config)
    errors = validate(args.xml, args.config)
    if errors:
        for e in errors:
            print("FAIL", e)
        raise SystemExit(1)
    print("OK", args.xml)


if __name__ == "__main__":
    main()
