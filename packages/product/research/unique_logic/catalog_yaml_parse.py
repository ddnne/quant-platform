"""Constrained catalog YAML overlay parse (bytes → fields). Not load SoT.

Overlay remains opt-in via QP_ALLOW_YAML_OVERLAY in catalog.py. This module
does not replace compiled migration.jsonl.
"""
from __future__ import annotations

from typing import Any


def _parse_scalar(raw: str) -> Any:
    s = raw.strip()
    if s in {"true", "True"}:
        return True
    if s in {"false", "False"}:
        return False
    if s in {"null", "None", "~", ""}:
        return None if s != "" else ""
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def parse_catalog_yaml(text: str) -> dict[str, Any]:
    """Parse the constrained catalog schema (scalars, folded text, lists, params map)."""
    data: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent != 0:
            i += 1
            continue
        if raw.rstrip().endswith(":") and raw.strip()[:-1].strip() and ":" not in raw.strip()[:-1]:
            key = raw.strip()[:-1]
            i += 1
            if key == "params":
                params: dict[str, Any] = {}
                while i < n:
                    ln = lines[i]
                    if not ln.strip() or ln.lstrip().startswith("#"):
                        i += 1
                        continue
                    if not ln.startswith(" "):
                        break
                    if ":" in ln:
                        k, _, rest = ln.strip().partition(":")
                        key_p = k.strip()
                        val = _parse_scalar(rest)
                        if key_p == "gates":
                            if val in (None, "", "None"):
                                params[key_p] = []
                            elif isinstance(val, str):
                                params[key_p] = [
                                    x.strip()
                                    for x in val.split(",")
                                    if x.strip() and x.strip() != "None"
                                ]
                            else:
                                params[key_p] = [str(val)]
                        else:
                            params[key_p] = val
                    i += 1
                data[key] = params
                continue
            items: list[Any] = []
            saw_list = False
            while i < n:
                ln = lines[i]
                if not ln.strip() or ln.lstrip().startswith("#"):
                    i += 1
                    continue
                if not ln.startswith(" "):
                    break
                if ln.strip().startswith("-"):
                    saw_list = True
                    items.append(_parse_scalar(ln.strip()[1:]))
                i += 1
            data[key] = items if saw_list else None
            continue
        if ":" in raw:
            key, _, rest = raw.partition(":")
            key = key.strip()
            rest = rest.strip()
            if rest in {">", "|"}:
                buf: list[str] = []
                i += 1
                while i < n:
                    ln = lines[i]
                    if not ln.strip():
                        i += 1
                        continue
                    if not ln.startswith(" "):
                        break
                    buf.append(ln.strip())
                    i += 1
                data[key] = " ".join(buf)
                continue
            data[key] = _parse_scalar(rest)
        i += 1
    return data
