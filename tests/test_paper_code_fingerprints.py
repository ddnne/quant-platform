"""Offline coverage for paper strategy/feature/code fingerprints."""

from __future__ import annotations

from dataclasses import replace

import features

from paper_runtime import (
    feature_definition_hashes,
    git_commit,
    strategy_definition_hash,
)
from strategies.examples import MomentumFeatureStrategy, Return1dFeatureStrategy


def test_strategy_definition_hash_is_stable_and_source_sensitive():
    first = strategy_definition_hash(Return1dFeatureStrategy())
    second = strategy_definition_hash(Return1dFeatureStrategy(threshold=1.0))
    momentum = strategy_definition_hash(MomentumFeatureStrategy())

    assert first.startswith("sha256:")
    assert first == second  # parameters are a separate identity component
    assert first != momentum


def test_feature_definition_hashes_are_version_pinned_and_deterministic():
    versions = {"momentum_n": "1.0.0", "return_1d": "1.0.0"}

    first = feature_definition_hashes(versions)
    second = feature_definition_hashes(dict(reversed(list(versions.items()))))

    assert first == second
    assert set(first) == set(versions)
    assert all(value.startswith("sha256:") for value in first.values())
    assert first["momentum_n"] != first["return_1d"]


def test_feature_definition_hash_includes_price_basis(monkeypatch):
    raw = features.get("return_1d")
    monkeypatch.setattr(features, "get", lambda *_args, **_kwargs: raw)
    raw_hash = feature_definition_hashes({raw.id: str(raw.version)})[raw.id]

    adjusted = replace(raw, price_basis="PIT_ADJUSTED")
    monkeypatch.setattr(features, "get", lambda *_args, **_kwargs: adjusted)
    adjusted_hash = feature_definition_hashes(
        {adjusted.id: str(adjusted.version)}
    )[adjusted.id]

    assert raw_hash != adjusted_hash


def test_git_commit_prefers_deployment_environment(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "deployment-commit")
    monkeypatch.setenv("GITHUB_SHA", "lower-priority")

    assert git_commit() == "deployment-commit"
