"""Pinned trust-root invariants for controlled Trader authorization."""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from execution.trader_authority import (
    DEFAULT_TRADER_AUTHORIZATION_PUBLIC_KEYS_PATH,
    TraderAuthorizationPublicKeyRegistry,
    open_controlled_trader_authorization_issuer,
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
        (_row(key_id="revoked-only", status="revoked"),),
        (
            _row(key_id="active-one"),
            _row(key_id="active-two"),
        ),
    ),
)
def test_trader_registry_requires_exactly_one_active_key(
    rows: tuple[dict[str, object], ...],
) -> None:
    with pytest.raises(
        MassResearchDisabledError,
        match="exactly one active key",
    ):
        TraderAuthorizationPublicKeyRegistry.from_document(_document(*rows))


def test_committed_trader_registry_is_purpose_pinned_and_exact_one() -> None:
    document = json.loads(
        DEFAULT_TRADER_AUTHORIZATION_PUBLIC_KEYS_PATH.read_text(encoding="utf-8")
    )
    registry = TraderAuthorizationPublicKeyRegistry.from_document(document)
    row = document["keys"][0]
    assert row["key_id"] == "trader-authorization-20260825-v1"
    assert row["status"] == "active"
    assert document["purpose"] == "controlled_trader_authorization_verification"
    assert len(registry._keys) == 1  # noqa: SLF001 - trust-root invariant


def test_production_trader_signer_has_no_key_or_path_injection_surface() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        open_controlled_trader_authorization_issuer(  # type: ignore[call-arg]
            key_id="attacker",
            private_key_path="/tmp/attacker.pem",
        )
