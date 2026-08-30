"""Focused repo-root resolution for checkout vs container runtime images."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import qp_paths

REPO = Path(__file__).resolve().parents[1]
DOCKERFILE = (
    REPO
    / "platform"
    / "workers"
    / "research-mass-eval"
    / "Dockerfile"
)
CONTAINER_DIR = (
    REPO / "platform" / "workers" / "research-mass-eval" / "container"
)


@pytest.fixture
def isolated_qp_paths(monkeypatch: pytest.MonkeyPatch):
    previous = qp_paths._CACHED
    previous_state = qp_paths._CACHED_ENV_STATE
    qp_paths._CACHED = None
    qp_paths._CACHED_ENV_STATE = None
    monkeypatch.delenv("QP_REPO_ROOT", raising=False)
    try:
        yield
    finally:
        qp_paths._CACHED = previous
        qp_paths._CACHED_ENV_STATE = previous_state


def _runtime_root(path: Path) -> Path:
    path.mkdir()
    (path / "pyproject.toml").write_text(
        "[project]\nname = \"runtime\"\n", encoding="utf-8"
    )
    (path / "qp_paths.py").write_text("# runtime marker\n", encoding="utf-8")
    (path / "packages" / "product" / "research").mkdir(parents=True)
    return path.resolve()


def test_explicit_runtime_root_does_not_require_tests(
    tmp_path: Path, isolated_qp_paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _runtime_root(tmp_path / "image-root")
    assert not (root / "tests").exists()
    monkeypatch.setenv("QP_REPO_ROOT", str(root))

    assert qp_paths.repo_root() == root


def test_empty_packages_runtime_is_rejected(
    tmp_path: Path, isolated_qp_paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "empty-packages"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname = \"quant-platform\"\n", encoding="utf-8"
    )
    (root / "qp_paths.py").write_text("# marker\n", encoding="utf-8")
    (root / "packages").mkdir()
    monkeypatch.setenv("QP_REPO_ROOT", str(root.resolve()))

    with pytest.raises(RuntimeError, match="packages/product/research"):
        qp_paths.repo_root()


def test_invalid_explicit_repo_root_fails_closed(
    tmp_path: Path, isolated_qp_paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = tmp_path / "decoy-checkout"
    decoy.mkdir()
    (decoy / "pyproject.toml").write_text(
        "[project]\nname = \"decoy\"\n", encoding="utf-8"
    )
    (decoy / "tests").mkdir()
    monkeypatch.setenv("QP_REPO_ROOT", str(decoy.resolve()))

    with pytest.raises(RuntimeError, match="QP_REPO_ROOT"):
        qp_paths.repo_root()


def test_checkout_cache_then_invalid_explicit_fails_closed(
    tmp_path: Path, isolated_qp_paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = Path(__file__).resolve().parents[1]
    assert qp_paths.repo_root() == checkout

    decoy = tmp_path / "decoy-after-cache"
    decoy.mkdir()
    (decoy / "pyproject.toml").write_text(
        "[project]\nname = \"runtime\"\n", encoding="utf-8"
    )
    (decoy / "packages").mkdir()
    monkeypatch.setenv("QP_REPO_ROOT", str(decoy.resolve()))

    with pytest.raises(RuntimeError, match="QP_REPO_ROOT"):
        qp_paths.repo_root()


def test_unset_repo_root_keeps_checkout_discovery(
    isolated_qp_paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("QP_REPO_ROOT", raising=False)
    checkout = Path(__file__).resolve().parents[1]

    assert qp_paths.repo_root() == checkout
    assert (qp_paths.repo_root() / "tests").is_dir()


def test_dockerfile_does_not_copy_catalog_tests_or_artifacts() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "legacy_strategy_catalog" not in text
    assert "COPY tests" not in text
    assert "COPY artifacts" not in text


def _link_min_runtime_tree(dst: Path) -> None:
    shutil.copy2(REPO / "pyproject.toml", dst / "pyproject.toml")
    shutil.copy2(REPO / "qp_paths.py", dst / "qp_paths.py")
    (dst / "packages").symlink_to(REPO / "packages")
    (dst / "specs").symlink_to(REPO / "specs")
    container_dst = (
        dst / "platform" / "workers" / "research-mass-eval" / "container"
    )
    container_dst.parent.mkdir(parents=True)
    container_dst.symlink_to(CONTAINER_DIR)
    assert not (dst / "tests").exists()
    assert not (dst / "artifacts").exists()


def test_personal_research_service_imports_without_legacy_catalog(
    tmp_path: Path,
) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    _link_min_runtime_tree(root)
    python_paths = [
        root,
        root / "packages" / "edge",
        root / "packages" / "data_plane",
        root / "packages" / "research_runtime",
        root / "packages" / "product",
        root / "platform" / "workers" / "research-mass-eval" / "container",
    ]
    code = r"""
import importlib
import pathlib
import sys

sys.path[:0] = sys.argv[1:]

replay_name = "legacy_strategy_catalog"
original_open = pathlib.Path.open
original_read_text = pathlib.Path.read_text

def reject_open(self, *args, **kwargs):
    if replay_name in self.parts:
        raise AssertionError(f"runtime import opened replay artifact: {self}")
    return original_open(self, *args, **kwargs)

def reject_read_text(self, *args, **kwargs):
    if replay_name in self.parts:
        raise AssertionError(f"runtime import read replay artifact: {self}")
    return original_read_text(self, *args, **kwargs)

pathlib.Path.open = reject_open
pathlib.Path.read_text = reject_read_text
importlib.import_module("personal_research_service")
blocked = sorted(
    name
    for name in sys.modules
    if name in {
        "research.unique_logic.catalog",
        "research.catalog_compiler",
        "research.catalog_active",
        "research.unique_logic.constants",
    }
)
if blocked:
    raise AssertionError(f"legacy catalog modules loaded: {blocked}")
"""
    env = os.environ.copy()
    env["QP_REPO_ROOT"] = str(root.resolve())
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in python_paths)
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, *(str(path) for path in python_paths)],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
