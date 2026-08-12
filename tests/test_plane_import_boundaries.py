"""Plane-level import allow-list (static AST).

Encodes ADR ``adr_llm_friendly_refactor.md`` §5.1 / §6.4:

- Leaf import names stay top-level (``import pit``); physical path is plane.
- Cross-plane edges must be on the allow-list.
- Explicit exceptions: ``data_access → features|paper_runtime`` (read façade),
  ``paper_runtime → storage|cf_platform|data_contracts`` (READY control plane),
  ``risk → agents`` (soft type edge).
- Hard bans: product must not import ``ingestion`` market clients;
  ``core``/``features`` must not import ``storage`` / ``ingestion``;
  ``pit``/``ingestion`` must not import research/product compute packages.

Does **not** replace package-local guards
(``test_core_data_boundary``, ``test_features_data_boundary``,
``test_strategies_static_boundaries``).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_ROOT = REPO_ROOT / "packages"

# leaf package name → plane directory under packages/
LEAF_TO_PLANE: dict[str, str] = {}
for _plane_dir in PACKAGES_ROOT.iterdir():
    if not _plane_dir.is_dir() or _plane_dir.name.startswith("."):
        continue
    for _leaf in _plane_dir.iterdir():
        if _leaf.is_dir() and (_leaf / "__init__.py").exists():
            LEAF_TO_PLANE[_leaf.name] = _plane_dir.name

FIRST_PARTY = frozenset(LEAF_TO_PLANE)

# Plane-level default: which planes a plane may import from.
# Package-level exceptions refine this further.
ALLOWED_PLANE_DEPS: dict[str, frozenset[str]] = {
    "edge": frozenset({"edge", "data_plane"}),
    "data_plane": frozenset({"data_plane", "edge"}),
    # research_runtime may reach data_plane (pit/storage) and edge (cf_platform helpers)
    "research_runtime": frozenset({"research_runtime", "data_plane", "edge"}),
    # product may use research_runtime + data_plane (knowledge→storage, agents→strategies)
    "product": frozenset({"product", "research_runtime", "data_plane"}),
}

# Cross-plane package edges that are intentional exceptions to the strict
# plane matrix (or refine package bans below).
ALLOWED_CROSS_PACKAGE: frozenset[tuple[str, str]] = frozenset(
    {
        # shared read adapter under data_plane (ADR §5.1)
        ("data_access", "features"),
        ("data_access", "paper_runtime"),
        # soft edge (inventory); keep until types move
        ("risk", "agents"),
    }
)

# Package roots that must never appear in these packages (highest-value bans).
PACKAGE_FORBIDDEN_ROOTS: dict[str, frozenset[str]] = {
    "core": frozenset(
        {
            "storage",
            "ingestion",
            "data_access",
            "agents",
            "gateway",
            "selection",
            "execution",
            "research",
            "knowledge",
            "cf_platform",
            "mcp_servers",
            "ops",
            "sqlite3",
            "httpx",
            "requests",
        }
    ),
    "features": frozenset(
        {
            "storage",
            "ingestion",
            "data_access",
            "agents",
            "gateway",
            "selection",
            "execution",
            "research",
            "knowledge",
            "cf_platform",
            "mcp_servers",
            "ops",
            "core",  # features must not depend on backtest engine
            "strategies",
            "sqlite3",
            "httpx",
            "requests",
        }
    ),
    "pit": frozenset(
        {
            "core",
            "features",
            "strategies",
            "paper_runtime",
            "agents",
            "gateway",
            "selection",
            "execution",
            "research",
            "knowledge",
            "risk",
            "data_access",
        }
    ),
    "ingestion": frozenset(
        {
            "core",
            "features",
            "strategies",
            "paper_runtime",
            "agents",
            "gateway",
            "selection",
            "execution",
            "research",
            "knowledge",
            "risk",
            "data_access",
            "pit",  # writers must not read via pit in-process as a cycle
        }
    ),
    "agents": frozenset(
        {
            "ingestion",
            "pit",
            "storage",
            "sqlite3",
            "httpx",
            "requests",
        }
    ),
    "gateway": frozenset(
        {
            "ingestion",
            "pit",
            "storage",
            "socket",
            "httpx",
            "requests",
            "sqlite3",
        }
    ),
    "selection": frozenset({"ingestion", "pit", "storage", "httpx", "requests"}),
    "research": frozenset({"ingestion", "httpx", "requests"}),
    "knowledge": frozenset({"ingestion", "httpx", "requests", "pit"}),
    "execution": frozenset({"ingestion", "pit", "storage", "httpx", "requests"}),
    "strategies": frozenset(
        {
            "ingestion",
            "pit",
            "storage",
            "cf_platform",
            "httpx",
            "requests",
            "sqlite3",
            "socket",
        }
    ),
    "data_contracts": frozenset(
        {
            "ingestion",
            "storage",
            "pit",
            "core",
            "features",
            "strategies",
            "agents",
            "httpx",
            "requests",
        }
    ),
}


def _python_files_for_leaf(leaf: str) -> list[Path]:
    plane = LEAF_TO_PLANE[leaf]
    root = PACKAGES_ROOT / plane / leaf
    return sorted(
        p
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts
        and "test" not in p.parts  # skip nested tests if any
        and not p.name.startswith("test_")
    )


def _imported_roots(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, root_module) for absolute imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name.split(".", 1)[0]))
        elif isinstance(node, ast.ImportFrom):
            # relative imports stay inside package / plane
            if node.level and node.level > 0:
                continue
            if node.module:
                found.append((node.lineno, node.module.split(".", 1)[0]))
    return found


def _collect_edges() -> list[tuple[str, str, Path, int, str]]:
    """(from_leaf, to_root, path, lineno, kind) edges where to_root is first-party or banned std/third."""
    edges: list[tuple[str, str, Path, int, str]] = []
    for leaf in sorted(LEAF_TO_PLANE):
        for path in _python_files_for_leaf(leaf):
            for lineno, root in _imported_roots(path):
                if root == leaf:
                    continue
                edges.append((leaf, root, path, lineno, root))
    return edges


def test_leaf_packages_discovered():
    """Sanity: layout planes expose expected leaf packages."""
    assert "pit" in LEAF_TO_PLANE and LEAF_TO_PLANE["pit"] == "data_plane"
    assert "core" in LEAF_TO_PLANE and LEAF_TO_PLANE["core"] == "research_runtime"
    assert "agents" in LEAF_TO_PLANE and LEAF_TO_PLANE["agents"] == "product"
    assert "cf_platform" in LEAF_TO_PLANE and LEAF_TO_PLANE["cf_platform"] == "edge"
    # Batch Z not partially introduced
    assert "quant_platform" not in LEAF_TO_PLANE


def test_package_forbidden_roots():
    """High-value package bans (core/features/pit/ingestion/product/strategies)."""
    offenders: list[str] = []
    for leaf, forbidden in sorted(PACKAGE_FORBIDDEN_ROOTS.items()):
        if leaf not in LEAF_TO_PLANE:
            continue
        for path in _python_files_for_leaf(leaf):
            for lineno, root in _imported_roots(path):
                if root in forbidden:
                    rel = path.relative_to(REPO_ROOT)
                    offenders.append(f"{rel}:{lineno}: {leaf} imports forbidden {root!r}")
    assert not offenders, "package forbidden-import violations:\n" + "\n".join(offenders)


def test_plane_cross_import_allow_list():
    """First-party cross-plane imports must be allow-listed.

    Exceptions:
    - data_access → features / paper_runtime (shared read adapter)
    - risk → agents (soft type edge)
    - data_plane → research_runtime only via those data_access exceptions
    - research_runtime → product only via risk → agents
    """
    offenders: list[str] = []
    for from_leaf, to_root, path, lineno, _ in _collect_edges():
        if to_root not in FIRST_PARTY:
            continue
        from_plane = LEAF_TO_PLANE[from_leaf]
        to_plane = LEAF_TO_PLANE[to_root]
        if from_plane == to_plane:
            continue
        # explicit package exceptions
        if (from_leaf, to_root) in ALLOWED_CROSS_PACKAGE:
            continue
        # data_access may only cross into research_runtime for the allow-listed targets
        if from_leaf == "data_access" and to_plane == "research_runtime":
            offenders.append(
                f"{path.relative_to(REPO_ROOT)}:{lineno}: "
                f"data_access → {to_root} not in allow-list "
                f"(allowed: features, paper_runtime)"
            )
            continue
        allowed_planes = ALLOWED_PLANE_DEPS.get(from_plane, frozenset())
        if to_plane not in allowed_planes:
            offenders.append(
                f"{path.relative_to(REPO_ROOT)}:{lineno}: "
                f"{from_leaf}({from_plane}) → {to_root}({to_plane}) "
                f"not allowed (plane allow: {sorted(allowed_planes)}; "
                f"package exceptions: data_access→features|paper_runtime, risk→agents)"
            )
    assert not offenders, "plane allow-list violations:\n" + "\n".join(offenders)


def test_product_does_not_import_ingestion():
    """Product plane must not pull market HTTP clients from ingestion."""
    offenders: list[str] = []
    for leaf, plane in LEAF_TO_PLANE.items():
        if plane != "product":
            continue
        for path in _python_files_for_leaf(leaf):
            for lineno, root in _imported_roots(path):
                if root == "ingestion":
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{lineno}: "
                        f"{leaf} must not import ingestion"
                    )
    assert not offenders, "product→ingestion violations:\n" + "\n".join(offenders)


def test_data_access_bridge_exception_documented():
    """data_access may import features and paper_runtime (intentional bridge)."""
    roots: set[str] = set()
    for path in _python_files_for_leaf("data_access"):
        for _, root in _imported_roots(path):
            if root in FIRST_PARTY:
                roots.add(root)
    # must use the bridge targets that exist today
    assert "features" in roots or "paper_runtime" in roots
    # must not import product packages
    product_leaks = sorted(r for r in roots if LEAF_TO_PLANE.get(r) == "product")
    assert not product_leaks, f"data_access must not import product: {product_leaks}"


def test_no_quant_platform_namespace_imports():
    """Batch Z deferred: no quant_platform.* imports in packages."""
    offenders: list[str] = []
    for leaf in LEAF_TO_PLANE:
        for path in _python_files_for_leaf(leaf):
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), start=1):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                if "import quant_platform" in line or "from quant_platform" in line:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{i}: {line.strip()}")
    assert not offenders, "Batch Z quant_platform imports present:\n" + "\n".join(offenders)
