"""Focused repo-root resolution for checkout vs container runtime images."""

from __future__ import annotations

from pathlib import Path

import pytest

import qp_paths


@pytest.fixture
def isolated_qp_paths(monkeypatch: pytest.MonkeyPatch):
    previous = qp_paths._CACHED
    qp_paths._CACHED = None
    monkeypatch.delenv("QP_REPO_ROOT", raising=False)
    try:
        yield
    finally:
        qp_paths._CACHED = previous


def _runtime_root(path: Path) -> Path:
    path.mkdir()
    (path / "pyproject.toml").write_text("[project]\nname = \"runtime\"\n", encoding="utf-8")
    (path / "packages").mkdir()
    return path.resolve()


def test_explicit_runtime_root_does_not_require_tests(
    tmp_path: Path, isolated_qp_paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _runtime_root(tmp_path / "image-root")
    assert not (root / "tests").exists()
    monkeypatch.setenv("QP_REPO_ROOT", str(root))

    assert qp_paths.repo_root() == root


def test_invalid_explicit_repo_root_fails_closed(
    tmp_path: Path, isolated_qp_paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = tmp_path / "decoy-checkout"
    decoy.mkdir()
    (decoy / "pyproject.toml").write_text("[project]\nname = \"decoy\"\n", encoding="utf-8")
    (decoy / "tests").mkdir()
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
