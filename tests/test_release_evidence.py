from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "build_release_evidence.py"
SPEC = importlib.util.spec_from_file_location("build_release_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def payload() -> dict[str, object]:
    sha = "a" * 40
    return {
        "source_sha": sha,
        "origin_main_sha": sha,
        "required_check": {"name": "Workers Builds", "status": "SUCCESS"},
        "cloudflare_build": {"status": "SUCCESS"},
        "merged_prs": [42],
        "open_prs": [],
        "deployments": {"quant-ops-mcp": {"version": "version-id", "sha": sha}},
        "migrations": {"quant-ops-projection": {"status": "APPLIED"}},
        "smoke": {"staging": "PASS", "production": "PASS"},
        "quant_mcp": {"tool_count": 17, "projection": "FRESH"},
        "backup": {
            "encrypted": True,
            "cipher": "AES-256-GCM",
            "ciphertext_digest": "sha256:" + "b" * 64,
        },
        "controlled_pilot": "NO-GO",
        "mass_research": "NO-GO",
        "rollback_status": "NOT_REQUIRED",
    }


def test_release_evidence_is_deterministic_and_content_addressed(tmp_path: Path) -> None:
    facts = payload()
    first = release.write_envelope(facts, tmp_path)
    second = release.write_envelope(facts, tmp_path)
    assert first == second
    document = json.loads(first.read_text(encoding="utf-8"))
    assert document["evidence_digest"] == release.payload_digest(facts)
    assert document["evidence_digest"].removeprefix("sha256:") in first.name
    assert first.stat().st_mode & 0o777 == 0o444


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_sha", "short", "full lowercase Git SHA"),
        ("mass_research", "GO", "Mass Research NO-GO"),
        ("controlled_pilot", "MAYBE", "GO or NO-GO"),
    ],
)
def test_release_evidence_rejects_policy_drift(
    field: str, value: object, message: str
) -> None:
    facts = payload()
    facts[field] = value
    with pytest.raises(ValueError, match=message):
        release.build_envelope(facts)


def test_release_evidence_rejects_secrets_and_local_paths() -> None:
    secret = payload()
    secret["smoke"] = {"api_token": "do-not-publish"}
    with pytest.raises(ValueError, match="secret-shaped key"):
        release.build_envelope(secret)

    local = payload()
    local["smoke"] = {"report": "/Users/operator/private/result.json"}
    with pytest.raises(ValueError, match="local absolute path"):
        release.build_envelope(local)


def test_release_evidence_keeps_backup_body_and_key_private() -> None:
    facts = payload()
    facts["backup"] = {
        "encrypted": True,
        "ciphertext_digest": "sha256:" + "b" * 64,
        "path": "backup.sql.enc",
    }
    with pytest.raises(ValueError, match="paths and key material"):
        release.build_envelope(facts)
