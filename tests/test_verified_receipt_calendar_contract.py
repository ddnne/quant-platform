"""Dataset-conditional signed receipt evidence contract."""

from __future__ import annotations

import base64
from dataclasses import replace
import json

import pytest

from data_contracts.coverage import coverage_contract_for
from storage import verified_receipt as verifier_module
from storage.coverage_ledger import RequiredCoverageSegment, plan_required_segments
from storage.receipt_crypto import (
    AUDIT_SIGNED_RECEIPT_CLAIMS_VERSION_V2,
    LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION,
    PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST,
    PRODUCTION_RECEIPT_ENVIRONMENT,
    body_digest,
    canonical_evidence_digest,
    canonical_receipt_body,
)
from storage.verified_receipt import (
    ReceiptVerificationError,
    audit_collection_closure,
    require_verified_collection_closure,
)
from tests.receipt_test_support import (
    _SignedReceiptAuthority,
    _reconcile_collection_evidence,
)


_ACQUISITION_DIGESTS = (
    "acquisition_collection_manifest_file_digest",
    "acquisition_collection_digest",
    "acquisition_terminal_chain_digest",
)
_MASTER_CALENDAR_DIGESTS = (
    "official_calendar_evidence_digest",
    "official_calendar_raw_body_digest",
    "official_calendar_query_digest",
    "official_business_dates_digest",
    "official_calendar_binding_digest",
)
_JQUANTS_AUTHORITY_DIGESTS = frozenset(
    (*_ACQUISITION_DIGESTS, *_MASTER_CALENDAR_DIGESTS)
)


def _digest(label: str) -> str:
    return canonical_evidence_digest({"test_evidence": label})


def _extras(*, calendar: bool) -> dict[str, str]:
    fields = (
        *_ACQUISITION_DIGESTS,
        *(_MASTER_CALENDAR_DIGESTS if calendar else ()),
    )
    return {name: _digest(name) for name in fields}


def _required(dataset: str):
    if dataset == "jsda_otc_bond_reference_prices":
        return RequiredCoverageSegment(
            source="jsda",
            dataset=dataset,
            segment_id="2024-02",
            segment_start="2024-02-01",
            segment_end="2024-02-29",
            expected_scope={
                "coverage_mode": "official_archive",
                "expected_frequency": "business_day",
                "expected_item_unit": "official_archive_file",
                "segment_start": "2024-02-01",
                "segment_end": "2024-02-29",
            },
            expected_items=1,
        )
    target_end = "2024-02-29" if dataset == "equities_master" else "2025-01-31"
    segments = plan_required_segments(
        coverage_contract_for(dataset), target_end, source="jquants"
    )
    return next(segment for segment in segments if segment.segment_id == target_end[:7])


def _issue(
    receipt_ed25519_keys,
    *,
    dataset: str,
    extras: dict[str, object],
    include_common: bool = True,
    include_calendar: bool = True,
):
    required = _required(dataset)
    record = {"Date": required.segment_start, "Code": "1301"}
    evidence = _reconcile_collection_evidence(
        required=required,
        run_id=77,
        raw_pages=(json.dumps({"data": [record]}).encode("utf-8"),),
        raw_records=(record,),
        structured_records=(record,),
        checked_at="2026-08-27T00:00:00+00:00",
        extra_evidence=extras,
        include_jquants_acquisition_digests=include_common,
        include_master_calendar_digests=include_calendar,
    )
    receipt = _SignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    ).issue(evidence)
    return required, receipt


def _verify(receipt, required):
    return require_verified_collection_closure(
        receipt,
        required=required,
        expected_policy_version=coverage_contract_for(required.dataset).policy_version,
        expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
        expected_authority_instance_digest=(
            PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
        ),
    )


def _signed_claims(receipt) -> dict[str, object]:
    return json.loads(base64.b64decode(receipt.digests["signed_body_b64"]))


def _downgrade_for_audit(receipt, signing_key, version: str):
    digests = dict(receipt.digests)
    claims = json.loads(base64.b64decode(digests["signed_body_b64"]))
    claims["version"] = version
    claims.pop("environment")
    claims.pop("authority_instance_digest")
    scope = {
        key: claims[key]
        for key in (
            "coverage_policy_version",
            "source",
            "dataset",
            "segment_id",
            "segment_start",
            "segment_end",
            "expected_scope",
            "expected_items",
        )
    }
    claims["scope_digest"] = canonical_evidence_digest(scope)
    observation = {
        key: value
        for key, value in claims.items()
        if key
        not in {
            "version",
            "parser_normalizer_version",
            "issuer_id",
            "issued_at",
            "observation_digest",
        }
    }
    claims["observation_digest"] = canonical_evidence_digest(observation)
    signed_body = canonical_receipt_body(claims)
    digests.update(
        {
            "signed_body_b64": base64.b64encode(signed_body).decode("ascii"),
            "signature": signing_key.sign(signed_body),
            "body_digest": body_digest(signed_body),
            "scope_digest": claims["scope_digest"],
            "observation_digest": claims["observation_digest"],
        }
    )
    digests.pop("environment")
    digests.pop("authority_instance_digest")
    return replace(receipt, digests=digests)


def test_v3_master_requires_exact_calendar_digest_inventory(
    receipt_ed25519_keys,
) -> None:
    required, complete = _issue(
        receipt_ed25519_keys,
        dataset="equities_master",
        extras=_extras(calendar=True),
    )
    assert _verify(complete, required).dataset == "equities_master"

    _required_segment, regressed = _issue(
        receipt_ed25519_keys,
        dataset="equities_master",
        extras=_extras(calendar=False),
        include_calendar=False,
    )
    assert list(
        verifier_module._claims_validator().iter_errors(  # noqa: SLF001
            _signed_claims(regressed)
        )
    )
    with pytest.raises(
        ReceiptVerificationError,
        match="J-Quants authority digest inventory",
    ):
        _verify(regressed, required)


@pytest.mark.parametrize(
    ("dataset", "expected"),
    [
        ("markets_calendar", frozenset(_ACQUISITION_DIGESTS)),
        ("equities_master", _JQUANTS_AUTHORITY_DIGESTS),
    ],
)
def test_canonical_test_producer_emits_dataset_authority_inventory(
    receipt_ed25519_keys, dataset: str, expected: frozenset[str]
) -> None:
    required, receipt = _issue(
        receipt_ed25519_keys,
        dataset=dataset,
        extras={},
    )
    claims = _signed_claims(receipt)
    extras = claims["extra_digests"]
    assert isinstance(extras, dict)
    assert frozenset(extras) & _JQUANTS_AUTHORITY_DIGESTS == expected
    _verify(receipt, required)


@pytest.mark.parametrize("missing", _MASTER_CALENDAR_DIGESTS)
def test_v3_master_rejects_each_missing_calendar_digest(
    receipt_ed25519_keys, missing: str
) -> None:
    extras = _extras(calendar=True)
    extras.pop(missing)
    required, receipt = _issue(
        receipt_ed25519_keys,
        dataset="equities_master",
        extras=extras,
        include_calendar=False,
    )
    with pytest.raises(
        ReceiptVerificationError,
        match="J-Quants authority digest inventory",
    ):
        _verify(receipt, required)


def test_v3_master_rejects_malformed_calendar_digest(receipt_ed25519_keys) -> None:
    extras: dict[str, object] = _extras(calendar=True)
    extras["official_calendar_evidence_digest"] = "sha256:" + "G" * 64
    required, receipt = _issue(
        receipt_ed25519_keys, dataset="equities_master", extras=extras
    )
    with pytest.raises(ReceiptVerificationError, match="is not sha256"):
        _verify(receipt, required)


def test_v3_non_master_forbids_calendar_digest_inventory(
    receipt_ed25519_keys,
) -> None:
    required, receipt = _issue(
        receipt_ed25519_keys,
        dataset="markets_calendar",
        extras=_extras(calendar=True),
    )
    with pytest.raises(
        ReceiptVerificationError,
        match="J-Quants authority digest inventory",
    ):
        _verify(receipt, required)


@pytest.mark.parametrize("missing", _ACQUISITION_DIGESTS)
def test_v3_jquants_rejects_each_missing_common_acquisition_digest(
    receipt_ed25519_keys, missing: str
) -> None:
    extras = _extras(calendar=True)
    extras.pop(missing)
    required, receipt = _issue(
        receipt_ed25519_keys,
        dataset="equities_master",
        extras=extras,
        include_common=False,
    )
    with pytest.raises(
        ReceiptVerificationError,
        match="J-Quants authority digest inventory",
    ):
        _verify(receipt, required)


def test_v3_non_jquants_forbids_jquants_authority_digests(
    receipt_ed25519_keys,
) -> None:
    required, receipt = _issue(
        receipt_ed25519_keys,
        dataset="jsda_otc_bond_reference_prices",
        extras=_extras(calendar=True),
    )
    with pytest.raises(
        ReceiptVerificationError,
        match="J-Quants authority digest inventory",
    ):
        _verify(receipt, required)


@pytest.mark.parametrize(
    "version",
    [
        LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION,
        AUDIT_SIGNED_RECEIPT_CLAIMS_VERSION_V2,
    ],
)
def test_legacy_master_without_calendar_digests_remains_audit_only(
    receipt_ed25519_keys, version: str
) -> None:
    required, receipt = _issue(
        receipt_ed25519_keys,
        dataset="equities_master",
        extras=_extras(calendar=False),
        include_calendar=False,
    )
    legacy = _downgrade_for_audit(
        receipt, receipt_ed25519_keys.signing_key, version
    )
    audited = audit_collection_closure(
        legacy,
        required=required,
        expected_policy_version=coverage_contract_for(required.dataset).policy_version,
        expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
        expected_authority_instance_digest=(
            PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
        ),
    )
    assert audited["version"] == version
    with pytest.raises(ReceiptVerificationError, match="audit-only"):
        _verify(legacy, required)
