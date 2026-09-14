"""Preready denial and DataPlane source-owner import check.

The first test asserts connect_readonly raises SnapshotNotReady on unpublished
storage. The second reads Import and ImportFrom from DataPlane source,
including function-local nodes, and does not execute those imports. Relative
names use importlib.util.resolve_name against the installed leaf package
context (setuptools loads packages/data_plane as storage.*, pit.*, …).
Invalid relative imports fail the check rather than being skipped. The
packages.<where-dir>.* index entries are lookup aliases for imported names.
Dynamic importlib strings and paths outside setuptools where=/py-modules are
not verified. The same index then applies a limited compiled-scope owner-edge:
paper_runtime.ready_publication must not import connection-private PIT SQL
modules. Equivalent aliases resolve to the same owner path. This does not ban
sqlite3, DataView, or trusted experiment-index/cache/budget stores, and it
does not claim other research_runtime or scripts crossings are closed.
"""

from __future__ import annotations

import ast
import importlib.util
import tomllib
from pathlib import Path

import pytest


def test_ordinary_product_caller_cannot_open_preready_storage(
    tmp_path: Path,
) -> None:
    import sqlite3

    from pit.query import connect_readonly
    from pit.errors import SnapshotNotReady

    path = tmp_path / "preready.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE local_snapshot_policy ("
        "singleton INTEGER PRIMARY KEY, require_manifest INTEGER, "
        "snapshot_ready INTEGER, publication_state TEXT)"
    )
    conn.execute(
        "INSERT INTO local_snapshot_policy VALUES (1, 1, 0, 'BUILDING')"
    )
    conn.commit()
    conn.close()
    with pytest.raises(SnapshotNotReady):
        connect_readonly(path)


def _first_party_index(
    root: Path,
) -> tuple[list[Path], dict[str, Path], dict[Path, str], list[str]]:
    setup = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
        "tool"
    ]["setuptools"]
    where_dirs = [root / Path(item) for item in setup["packages"]["find"]["where"]]
    index: dict[str, Path] = {}
    owners: dict[Path, str] = {}
    clashes: list[str] = []

    def add(name: str, path: Path, owner: str) -> None:
        prior_path = index.get(name)
        if prior_path is not None and prior_path != path:
            clashes.append(f"{name}: {prior_path} vs {path}")
            return
        index[name] = path
        prior_owner = owners.get(path)
        if prior_owner is not None and prior_owner != owner:
            clashes.append(f"{path}: {prior_owner} vs {owner}")
            return
        owners[path] = owner

    for where in where_dirs:
        owner = where.relative_to(root).as_posix()
        for py in where.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            rel = py.relative_to(where)
            parts = (
                rel.parent.parts
                if py.name == "__init__.py"
                else rel.with_suffix("").parts
            )
            if not parts:
                continue
            path = py.resolve()
            leaf = ".".join(parts)
            add(leaf, path, owner)
            add(f"packages.{where.name}.{leaf}", path, owner)
    for name in setup.get("py-modules", []):
        path = (root / f"{name}.py").resolve()
        if not path.is_file():
            clashes.append(f"missing py-module {path}")
            continue
        add(name, path, "py-module")
    return where_dirs, index, owners, clashes


def _import_targets(
    tree: ast.AST, package: str | None
) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                rel = "." * node.level + (node.module or "")
                try:
                    base = importlib.util.resolve_name(rel, package)
                except (ImportError, TypeError):
                    found.append((node.lineno, f"<invalid-relative {rel!r}>") )
                    continue
            else:
                base = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    if base:
                        found.append((node.lineno, base))
                    continue
                found.append(
                    (node.lineno, f"{base}.{alias.name}" if base else alias.name)
                )
    return found


def _prefix_hits(
    name: str, index: dict[str, Path], owners: dict[Path, str]
) -> list[tuple[str, Path, str]]:
    hits: list[tuple[str, Path, str]] = []
    parts = name.split(".")
    for end in range(1, len(parts) + 1):
        prefix = ".".join(parts[:end])
        path = index.get(prefix)
        if path is not None:
            hits.append((prefix, path, owners[path]))
    return hits


def test_data_plane_source_does_not_import_other_first_party_planes() -> None:
    root = Path(__file__).resolve().parents[1]
    where_dirs, index, owners, clashes = _first_party_index(root)
    assert not clashes, "first-party module ownership is ambiguous:\n" + "\n".join(
        clashes
    )
    homes = [where for where in where_dirs if where.name == "data_plane"]
    assert len(homes) == 1, (
        "setuptools where= should include one data_plane directory, "
        f"got {where_dirs}"
    )
    home = homes[0]
    home_owner = home.relative_to(root).as_posix()
    allowed = {home_owner, "py-module"}
    queue = [
        path.resolve()
        for path in home.rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    assert queue, f"no Python sources under {home}"
    seen: set[Path] = set()
    violations: list[str] = []
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        leaf = next(
            name
            for name, found in index.items()
            if found == path and not name.startswith("packages.")
        )
        package = leaf if path.name == "__init__.py" else (leaf.rpartition(".")[0] or None)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, name in _import_targets(tree, package):
            if name.startswith("<invalid-relative"):
                violations.append(f"{path}:{lineno} {name}")
                continue
            hits = _prefix_hits(name, index, owners)
            planes = {owner for _, _, owner in hits}
            if not planes or planes <= allowed:
                queue.extend(
                    hit_path
                    for _, hit_path, owner in hits
                    if owner == "py-module" and hit_path not in seen
                )
                continue
            violations.append(f"{path}:{lineno} imports {name!r} -> {hits}")
    assert not violations, (
        "DataPlane source imports another first-party plane:\n" + "\n".join(violations)
    )

    private_sql = {
        index[name]
        for name in (
            "pit.complete_master",
            "pit.scoped_selection",
            "pit.compiled_dependency_scope",
            "pit.receipt_scope",
            "pit.query",
        )
    }
    runtime_path = index["paper_runtime.ready_publication"]
    leaf = next(
        name
        for name, found in index.items()
        if found == runtime_path and not name.startswith("packages.")
    )
    package = (
        leaf if runtime_path.name == "__init__.py" else (leaf.rpartition(".")[0] or None)
    )
    tree = ast.parse(
        runtime_path.read_text(encoding="utf-8"), filename=str(runtime_path)
    )
    runtime_violations: list[str] = []
    for lineno, name in _import_targets(tree, package):
        if name.startswith("<invalid-relative"):
            runtime_violations.append(f"{runtime_path}:{lineno} {name}")
            continue
        hits = _prefix_hits(name, index, owners)
        if any(hit_path in private_sql for _, hit_path, _ in hits):
            runtime_violations.append(
                f"{runtime_path}:{lineno} imports {name!r} -> {hits}"
            )
    assert not runtime_violations, (
        "ready_publication imports connection-private PIT SQL owners "
        "(limited compiled-scope edge; other research_runtime/scripts "
        "crossings remain OPEN):\n"
        + "\n".join(runtime_violations)
    )
