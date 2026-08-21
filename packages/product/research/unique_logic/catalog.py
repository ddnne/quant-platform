"""Load unique_logic declarations from ``specs/research_logics/*.yaml``.

Git catalog is the declaration. Scores live in R2/D1, not markdown.
The schema is intentionally small (no general YAML dependency).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from qp_paths import repo_root


def catalog_dir(*, root: Path | None = None) -> Path:
    return (root or repo_root()) / "specs" / "research_logics"


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
                        params[k.strip()] = _parse_scalar(rest)
                    i += 1
                data[key] = params
                continue
            if key == "datasets":
                items: list[Any] = []
                while i < n:
                    ln = lines[i]
                    if not ln.strip() or ln.lstrip().startswith("#"):
                        i += 1
                        continue
                    if not ln.startswith(" "):
                        break
                    if ln.strip().startswith("-"):
                        items.append(_parse_scalar(ln.strip()[1:]))
                    i += 1
                data[key] = items
                continue
            data[key] = None
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


def load_catalog_specs(*, root: Path | None = None) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for path in sorted(catalog_dir(root=root).glob("*.yaml")):
        spec = parse_catalog_yaml(path.read_text(encoding="utf-8"))
        spec["catalog_path"] = str(path)
        spec["catalog"] = True
        if spec.get("logic_id"):
            specs.append(spec)
    return specs


def catalog_spec(logic_id: str, *, root: Path | None = None) -> dict[str, Any] | None:
    lid = str(logic_id)
    for spec in load_catalog_specs(root=root):
        if str(spec.get("logic_id")) == lid:
            return spec
    return None
