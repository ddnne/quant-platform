"""Stable public facade for the split exact-four Trader WebAuthn authority."""

from execution.trader_webauthn_activation_v2 import (
    TRADER_AUTHORITY_ACTIVATION_PATH,
    TRADER_AUTHORITY_LIVE_STATE,
    _load_live_activation_document,
    _load_live_exact_four_trader_authority_v2 as _activation_loader,
)
from execution.trader_webauthn_authority_core_v2 import (
    ExactFourTraderWebAuthnAuthorityV2,
    _create_test_exact_four_trader_authority_v2,
)
from execution.trader_webauthn_ledger_v2 import SQLiteExactFourTraderLedgerV2
from execution.trader_webauthn_registry_v2 import (
    TRADER_ASSERTION_FORMAT,
    TRADER_CHALLENGE_FORMAT,
    TRADER_COMMITTED_HANDOFF_FORMAT,
    TRADER_CREDENTIAL_REGISTRY_FORMAT,
    TRADER_LEDGER_BACKEND,
    TRADER_LEDGER_EVENT_FORMAT,
    TRADER_RP_REGISTRY_FORMAT,
    TRADER_VERIFIER_BACKEND,
    CommittedExactFourTraderHandoffV2,
    ExactFourTraderAuthorityV2Error,
    ExactFourTraderCredentialRegistryV2,
    ExactFourTraderCredentialV2,
    ExactFourTraderRelyingPartyRegistryV2,
    ExactFourTraderRelyingPartyV2,
    IssuedExactFourTraderChallengeV2,
    VerifiedReadyAuthorityEvidenceV2,
    verify_ready_authority_response_v2,
)


def _load_live_exact_four_trader_authority_v2(
    *, server_bound: bool
) -> ExactFourTraderWebAuthnAuthorityV2:
    return _activation_loader(server_bound=server_bound)


def open_live_exact_four_trader_authority_v2() -> ExactFourTraderWebAuthnAuthorityV2:
    """Observe activated state; the returned object cannot launch positive ops."""

    return _load_live_exact_four_trader_authority_v2(server_bound=False)


def _open_server_bound_exact_four_trader_authority_v2(
) -> ExactFourTraderWebAuthnAuthorityV2:
    """Execution adapter hook used only inside UnixAuthorityService."""

    return _load_live_exact_four_trader_authority_v2(server_bound=True)


__all__ = [
    "TRADER_ASSERTION_FORMAT",
    "TRADER_AUTHORITY_ACTIVATION_PATH",
    "TRADER_AUTHORITY_LIVE_STATE",
    "TRADER_CHALLENGE_FORMAT",
    "TRADER_COMMITTED_HANDOFF_FORMAT",
    "TRADER_CREDENTIAL_REGISTRY_FORMAT",
    "TRADER_LEDGER_BACKEND",
    "TRADER_LEDGER_EVENT_FORMAT",
    "TRADER_RP_REGISTRY_FORMAT",
    "TRADER_VERIFIER_BACKEND",
    "CommittedExactFourTraderHandoffV2",
    "ExactFourTraderAuthorityV2Error",
    "ExactFourTraderCredentialRegistryV2",
    "ExactFourTraderCredentialV2",
    "ExactFourTraderRelyingPartyRegistryV2",
    "ExactFourTraderRelyingPartyV2",
    "ExactFourTraderWebAuthnAuthorityV2",
    "IssuedExactFourTraderChallengeV2",
    "SQLiteExactFourTraderLedgerV2",
    "VerifiedReadyAuthorityEvidenceV2",
    "open_live_exact_four_trader_authority_v2",
    "verify_ready_authority_response_v2",
]
