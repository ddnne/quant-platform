"""Trusted code fingerprints used by paper reproducibility manifests."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping


_GIT_COMMIT_ENV = (
    "GIT_COMMIT",
    "GITHUB_SHA",
    "CF_PAGES_COMMIT_SHA",
    "VERCEL_GIT_COMMIT_SHA",
)


def _digest(parts: Iterable[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for label, content in sorted(parts, key=lambda part: part[0]):
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def git_commit(repo_root: str | Path | None = None) -> str:
    """Return the deployment/git commit when available, otherwise ``""``."""
    for name in _GIT_COMMIT_ENV:
        value = os.environ.get(name, "").strip()
        if value:
            return value

    if repo_root is not None:
        root = Path(repo_root)
    else:
        try:
            from qp_paths import repo_root as _qp_repo_root

            root = _qp_repo_root()
        except Exception:
            root = Path(__file__).resolve().parents[1]
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _source_part(label: str, value: Any) -> tuple[str, bytes] | None:
    try:
        source = inspect.getsource(value)
    except (OSError, TypeError):
        source = ""
    if source:
        return label, source.encode("utf-8")

    try:
        source_path = inspect.getsourcefile(value)
    except TypeError:
        source_path = None
    if source_path:
        path = Path(source_path)
        try:
            return label, path.read_bytes()
        except OSError:
            pass
    return None


def strategy_definition_hash(strategy: Any) -> str:
    """Hash strategy source without including its runtime parameters."""
    explicit = getattr(strategy, "strategy_source_files", None)
    parts: list[tuple[str, bytes]] = []
    if explicit and not isinstance(explicit, (str, bytes, Path)):
        for source_path in explicit:
            path = Path(source_path)
            try:
                parts.append((path.name, path.read_bytes()))
            except OSError:
                continue

    strategy_type = type(strategy)
    if not parts:
        label = f"{strategy_type.__module__}.{strategy_type.__qualname__}"
        part = _source_part(label, strategy_type)
        if part is not None:
            parts.append(part)
    return _digest(parts) if parts else ""


def feature_definition_hashes(
    features_or_versions: Iterable[str] | Mapping[str, str],
) -> dict[str, str]:
    """Hash each registered feature definition and compute implementation."""
    import features

    hashes: dict[str, str] = {}
    if isinstance(features_or_versions, Mapping):
        requested = {
            str(feature_id): str(version)
            for feature_id, version in features_or_versions.items()
        }
    else:
        requested = {
            str(feature_id): "" for feature_id in features_or_versions
        }
    for feature_id, version in sorted(requested.items()):
        definition = features.get(feature_id, version or None)
        metadata = {
            "id": definition.id,
            "version": str(definition.version),
            "inputs": {
                "required": list(definition.inputs.required_kwargs),
                "optional": dict(definition.inputs.optional_kwargs),
                "as_of_rule": definition.inputs.as_of_rule,
            },
            "intended_role": definition.intended_role,
            "status": definition.status,
            "price_basis": definition.price_basis,
        }
        parts: list[tuple[str, bytes]] = [
            (
                "definition",
                json.dumps(
                    metadata,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8"),
            )
        ]
        source = _source_part("compute", definition.compute)
        if source is not None:
            parts.append(source)
        hashes[feature_id] = _digest(parts)
    return hashes


__all__ = [
    "feature_definition_hashes",
    "git_commit",
    "strategy_definition_hash",
]
