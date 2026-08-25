"""Behavioral checks for the tracked secret-path CI gate."""

from __future__ import annotations

from pathlib import Path

from scripts.verify_secret_paths import (
    REDACTED,
    forbidden_tracked_paths,
    is_forbidden_tracked_path,
    scan_content_hits,
)


def test_five_currently_missed_secret_paths_are_rejected() -> None:
    missed = [
        ".env.local",
        ".dev.vars",
        "deploy/id_ed25519.key",
        "certs/client.p12",
        "config/credentials.json",
    ]
    for path in missed:
        assert is_forbidden_tracked_path(path)
    assert forbidden_tracked_paths(missed + [".env.example"]) == sorted(missed)


def test_env_example_is_the_safe_exception() -> None:
    assert is_forbidden_tracked_path(".env")
    assert is_forbidden_tracked_path("platform/.env.production")
    assert not is_forbidden_tracked_path(".env.example")
    assert not is_forbidden_tracked_path("platform/.env.example")


def test_additional_key_material_suffixes_and_secret_json_are_rejected() -> None:
    assert is_forbidden_tracked_path("tls/server.pem")
    assert is_forbidden_tracked_path("keystore.pfx")
    assert is_forbidden_tracked_path("app.jks")
    assert is_forbidden_tracked_path(".dev.vars.staging")
    assert is_forbidden_tracked_path("ops/secrets.json")
    assert not is_forbidden_tracked_path("platform/workers/ingestion-secrets/package.json")


def test_content_scan_redacts_matched_secret_values(tmp_path: Path) -> None:
    leaked = tmp_path / "leaked.txt"
    leaked.write_text("token=github_pat_abcdefghijklmnopqrstuvwxyz\nsafe line\n", encoding="utf-8")
    hits = scan_content_hits(["leaked.txt"], root=tmp_path)
    assert hits == [f"leaked.txt:1: {REDACTED}"]
    assert "github_pat_" not in hits[0]
    assert "abcdefghijklmnopqrstuvwxyz" not in hits[0]
