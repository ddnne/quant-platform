"""Pinned trust-root invariants for controlled Trader authorization."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from execution.trader_authority import (
    DEFAULT_TRADER_AUTHORIZATION_PUBLIC_KEYS_PATH,
    TraderAuthorizationPublicKeyRegistry,
    VerifiedTraderAuthorization,
)
from selection.budget_ledger import MassResearchDisabledError


def _row(*, key_id: str, status: str | None = "active") -> dict[str, object]:
    raw = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    row: dict[str, object] = {
        "key_id": key_id,
        "algorithm": "Ed25519",
        "public_key_b64": base64.b64encode(raw).decode("ascii"),
    }
    if status is not None:
        row["status"] = status
    return row


def _document(*rows: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "purpose": "controlled_trader_authorization_verification",
        "keys": list(rows),
    }


def _canonical(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _signed_authorization(
    private_key: Ed25519PrivateKey,
    *,
    key_id: str,
    issued: datetime,
    ttl_seconds: int = 1800,
) -> VerifiedTraderAuthorization:
    digest = "sha256:" + ("ab" * 32)
    body: dict[str, object] = {
        "format": "verified-trader-authorization/v1",
        "mode": "paper",
        "strategy_id": "strategy-v1",
        "strategy_spec_hash": digest,
        "max_gross_weight": 0.5,
        "ready_snapshot_id": digest,
        "ready_manifest_digest": digest,
        "readiness_attestation_id": "attestation-v1",
        "profile_digest": digest,
        "plan_set_digest": digest,
        "dependency_closure_digest": digest,
        "universe_contract_id": "universe-v1",
        "universe_rule_digest": digest,
        "resolved_universe_digest": digest,
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "cost_scenario": "BASE",
        "issued_at": issued.isoformat(),
        "expires_at": (issued + timedelta(seconds=ttl_seconds)).isoformat(),
        "key_id": key_id,
        "issuer": "ControlledTraderAuthorizationService/v1",
    }
    body["authorization_id"] = "sha256:" + hashlib.sha256(
        _canonical(body)
    ).hexdigest()
    signature = "ed25519:" + base64.b64encode(
        private_key.sign(_canonical(body))
    ).decode("ascii")
    return VerifiedTraderAuthorization(
        signature=signature,
        **{key: value for key, value in body.items() if key != "format"},
    )


@pytest.mark.parametrize("status", (None, "", "pending", "ACTIVE"))
def test_trader_registry_requires_explicit_supported_status(
    status: str | None,
) -> None:
    with pytest.raises(
        MassResearchDisabledError,
        match="explicit active/revoked",
    ):
        TraderAuthorizationPublicKeyRegistry.from_document(
            _document(_row(key_id="k1", status=status))
        )


@pytest.mark.parametrize(
    "rows",
    (
        (
            _row(key_id="active-one"),
            _row(key_id="active-two"),
        ),
    ),
)
def test_trader_registry_rejects_more_than_one_active_key(
    rows: tuple[dict[str, object], ...],
) -> None:
    with pytest.raises(
        MassResearchDisabledError,
        match="at most one active key",
    ):
        TraderAuthorizationPublicKeyRegistry.from_document(_document(*rows))


def test_trader_registry_accepts_zero_active_keys_as_pending() -> None:
    registry = TraderAuthorizationPublicKeyRegistry.from_document(
        _document(_row(key_id="revoked-only", status="revoked"))
    )
    assert len(registry._keys) == 0  # noqa: SLF001 - trust-root invariant


def test_committed_trader_registry_is_purpose_pinned_and_pending() -> None:
    document = json.loads(
        DEFAULT_TRADER_AUTHORIZATION_PUBLIC_KEYS_PATH.read_text(encoding="utf-8")
    )
    registry = TraderAuthorizationPublicKeyRegistry.load_pinned()
    row = document["keys"][0]
    assert row["key_id"] == "trader-authorization-20260825-v1"
    assert row["status"] == "revoked"
    assert document["purpose"] == "controlled_trader_authorization_verification"
    assert len(registry._keys) == 0  # noqa: SLF001 - trust-root invariant
    assert not registry.verify(
        key_id=row["key_id"],
        body={"format": "verified-trader-authorization/v1"},
        signature="ed25519:" + base64.b64encode(b"\x00" * 64).decode("ascii"),
    )


def test_product_exposes_no_trader_signing_or_opening_api() -> None:
    import execution
    import execution.trader_authority as trader_module

    forbidden = (
        "open_controlled_trader_authorization_issuer",
        "_ControlledTraderAuthorizationIssuer",
        "_ISSUER_TOKEN",
        "DEFAULT_TRADER_AUTHORIZATION_PRIVATE_KEY_PATH",
        "Ed25519PrivateKey",
    )
    for name in forbidden:
        assert not hasattr(trader_module, name)
        assert not hasattr(execution, name)
        assert name not in trader_module.__all__


def test_matching_revoked_home_key_cannot_enable_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import execution.trader_authority as trader_module

    private_key = Ed25519PrivateKey.generate()
    legacy_path = (
        tmp_path
        / ".config"
        / "quant-platform"
        / "trader_authorization_signing_key.pem"
    )
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    registry_path = tmp_path / "matching-revoked-registry.json"
    matching_row = {
        "key_id": "legacy-home-key",
        "algorithm": "Ed25519",
        "public_key_b64": base64.b64encode(
            private_key.public_key().public_bytes_raw()
        ).decode("ascii"),
        "status": "revoked",
    }
    registry_path.write_text(
        json.dumps(_document(matching_row)), encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        trader_module,
        "DEFAULT_TRADER_AUTHORIZATION_PUBLIC_KEYS_PATH",
        registry_path,
    )

    issued = datetime.now(timezone.utc)
    authorization = _signed_authorization(
        private_key, key_id="legacy-home-key", issued=issued
    )
    active_test_registry = TraderAuthorizationPublicKeyRegistry(
        {"legacy-home-key": private_key.public_key()}
    )

    assert legacy_path.is_file()
    with pytest.MonkeyPatch.context() as isolated:
        isolated.setattr(
            TraderAuthorizationPublicKeyRegistry,
            "load_pinned",
            classmethod(lambda cls: active_test_registry),
        )
        assert authorization.is_valid(now=issued)
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        authorization.is_valid(  # type: ignore[call-arg]
            verifier=active_test_registry,
            now=issued,
        )
    assert not authorization.is_valid(now=issued)
    assert not hasattr(
        trader_module, "open_controlled_trader_authorization_issuer"
    )


def test_trader_authorization_rejects_ttl_beyond_controlled_policy() -> None:
    private_key = Ed25519PrivateKey.generate()
    issued = datetime.now(timezone.utc)
    authorization = _signed_authorization(
        private_key,
        key_id="test-ttl",
        issued=issued,
        ttl_seconds=1801,
    )
    registry = TraderAuthorizationPublicKeyRegistry(
        {"test-ttl": private_key.public_key()}
    )
    with pytest.MonkeyPatch.context() as isolated:
        isolated.setattr(
            TraderAuthorizationPublicKeyRegistry,
            "load_pinned",
            classmethod(lambda cls: registry),
        )
        assert not authorization.is_valid(now=issued)


def test_verified_trader_authorization_is_final() -> None:
    with pytest.raises(TypeError, match="final"):

        class ForgedTraderAuthorization(VerifiedTraderAuthorization):
            pass
