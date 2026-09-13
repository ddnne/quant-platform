from __future__ import annotations

import copy
import json
import subprocess
from io import BytesIO
from pathlib import Path
from urllib.request import Request

import pytest

from scripts import receipt_authority_pending_gate as pending


def _write_json(path: Path, document: object) -> None:
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _check_run(
    *,
    sha: str,
    status: str,
    conclusion: str | None,
) -> dict[str, object]:
    return {
        "name": pending._NATIVE_CHECK_NAME,
        "head_sha": sha,
        "status": status,
        "conclusion": conclusion,
        "app": {"id": 85455},
    }


def _check_runs_opener(payload: object):
    def opener(request: Request, timeout: object = None) -> BytesIO:
        assert timeout == pending._NATIVE_CHECK_TIMEOUT_SECONDS
        url = request.full_url
        assert "status=completed" not in url
        assert "filter=latest" in url
        assert "app_id=85455" in url
        return BytesIO(json.dumps(payload).encode("utf-8"))

    return opener


def test_native_required_check_accepts_latest_completed_success() -> None:
    sha = "e" * 40
    pending._require_native_required_check(
        sha,
        opener=_check_runs_opener(
            {
                "total_count": 1,
                "check_runs": [
                    _check_run(sha=sha, status="completed", conclusion="success")
                ],
            }
        ),
    )


@pytest.mark.parametrize(
    ("status", "conclusion", "head_sha", "match"),
    (
        ("in_progress", None, "e" * 40, "not completed success"),
        ("completed", "success", "f" * 40, "identity drifted"),
    ),
)
def test_native_required_check_rejects_unfinished_or_wrong_sha(
    status: str,
    conclusion: str | None,
    head_sha: str,
    match: str,
) -> None:
    expected = "e" * 40
    with pytest.raises(pending.PendingReceiptAuthorityError, match=match):
        pending._require_native_required_check(
            expected,
            opener=_check_runs_opener(
                {
                    "total_count": 1,
                    "check_runs": [
                        _check_run(
                            sha=head_sha,
                            status=status,
                            conclusion=conclusion,
                        )
                    ],
                }
            ),
        )


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_exact_pending_surface_is_provisioning_only(environment: str) -> None:
    evidence = pending.validate_pending_receipt_authority(environment)
    assert evidence["environment"] == environment
    assert evidence["authority_mode"] == "PENDING"
    assert evidence["active_key_count"] == 0
    assert evidence["public_surface"] == {
        "workers_dev": False,
        "preview_urls": False,
        "routes": [],
        "fetch_behavior": "NOT_FOUND_404",
    }
    assert evidence["allowed_rpc"] == ["public_key_registration"]
    assert evidence["forbidden_rpc"] == ["issue_for_segment", "recover_issue"]
    assert evidence["positive_operation_allowed"] is False
    assert evidence["pending_deployment_allowed"] is True
    assert evidence["strict_release_gate_applied"] is False
    assert evidence["strict_release_gate_unchanged"] is True
    assert evidence["authorization_scope"] == "PENDING_PROVISIONING_ONLY"


def test_active_or_cross_environment_registry_cannot_use_pending_gate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original = json.loads(
        pending.SCOPED_REGISTRY_PATHS["staging"].read_text(encoding="utf-8")
    )
    active = copy.deepcopy(original)
    active["authority_status"] = "ACTIVE"
    active["keys"] = [{"status": "active"}]
    body = dict(active)
    body.pop("registry_digest")
    active["registry_digest"] = pending._canonical_digest(body)
    path = tmp_path / "active.json"
    _write_json(path, active)
    monkeypatch.setitem(pending.SCOPED_REGISTRY_PATHS, "staging", path)
    with pytest.raises(
        pending.PendingReceiptAuthorityError, match="registry is active"
    ):
        pending.validate_pending_receipt_authority("staging")

    crossed = copy.deepcopy(original)
    crossed["environment"] = "production"
    body = dict(crossed)
    body.pop("registry_digest")
    crossed["registry_digest"] = pending._canonical_digest(body)
    _write_json(path, crossed)
    with pytest.raises(
        pending.PendingReceiptAuthorityError, match="unscoped"
    ):
        pending.validate_pending_receipt_authority("staging")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda row: row["vars"].update(AUTHORITY_MODE="ACTIVE"), "identity"),
        (lambda row: row["vars"].update(ACTIVATED_KEY_ID="forged"), "identity"),
        (lambda row: row.update(workers_dev=True), "identity"),
        (lambda row: row.update(preview_urls=True), "identity"),
        (
            lambda row: row.update(routes=[{"pattern": "authority.example/*"}]),
            "identity",
        ),
        (
            lambda row: row["r2_buckets"][0].update(bucket_name="shared-product"),
            "resources",
        ),
    ],
)
def test_active_key_url_and_resource_bypass_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    document = json.loads(
        pending.BINDING_MANIFEST_PATH.read_text(encoding="utf-8")
    )
    mutation(document["workers"]["receipt-evidence-authority"]["production"])
    path = tmp_path / "bindings.json"
    _write_json(path, document)
    monkeypatch.setattr(pending, "BINDING_MANIFEST_PATH", path)
    monkeypatch.setattr(pending, "build_manifest", lambda: document)
    with pytest.raises(pending.PendingReceiptAuthorityError, match=message):
        pending.validate_pending_receipt_authority("production")


def test_active_principal_declaration_is_never_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original = json.loads(
        pending.SCOPED_REGISTRY_PATHS["production"].read_text(encoding="utf-8")
    )
    active = copy.deepcopy(original)
    active["authority_status"] = "ACTIVE"
    active["keys"] = [{"status": "active"}]
    path = tmp_path / "production.json"
    _write_json(path, active)
    monkeypatch.setitem(pending.SCOPED_REGISTRY_PATHS, "production", path)
    with pytest.raises(
        pending.PendingReceiptAuthorityError,
        match="active, unscoped, or malformed",
    ):
        pending.validate_pending_receipt_authority("production")


def test_cli_source_identity_requires_exact_clean_reviewed_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            subprocess.CompletedProcess([], 0, "a" * 40 + "\n", ""),
            subprocess.CompletedProcess([], 0, " M unreviewed.py\n", ""),
        ]
    )
    monkeypatch.setattr(pending.subprocess, "run", lambda *_a, **_k: next(responses))
    with pytest.raises(
        pending.PendingReceiptAuthorityError, match="exact clean reviewed"
    ):
        pending._require_exact_clean_source("a" * 40)
    with pytest.raises(
        pending.PendingReceiptAuthorityError, match="exact lowercase"
    ):
        pending._require_exact_clean_source("HEAD")
