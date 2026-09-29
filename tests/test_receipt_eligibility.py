"""Signed receipt boundary: only Ed25519-verified receipts can COMPLETE."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from data_contracts import coverage_contract_for
from tests.receipt_test_support import (
    _SignedReceiptAuthority,
    _reconcile_collection_evidence,
)
from storage.coverage_ledger import (
    build_collection_receipt,
    evaluate_required_segments,
    evaluate_segment,
    is_complete_eligible_receipt,
    plan_required_segments,
)
from storage.receipt_policy import (
    is_recovered_only_digests,
    receipt_source_for_canonical_source,
)


def test_shared_receipt_source_and_recovery_policy_is_closed() -> None:
    assert receipt_source_for_canonical_source("jquants_premium_core") == "jquants"
    assert receipt_source_for_canonical_source("jquants_addon") == "jquants"
    assert receipt_source_for_canonical_source("jsda_governed") == "jsda"
    assert is_recovered_only_digests({"eligibility": "RECOVERED_RAW_ONLY"})
    assert is_recovered_only_digests({"origin": "parsed-staging-only"})
    assert is_recovered_only_digests({"eligibility": []})
    assert is_recovered_only_digests({"eligibility": None})
    assert is_recovered_only_digests({"eligibility": "TRUSTED_COLLECTION "})
    assert is_recovered_only_digests({"origin": {}})
    assert is_recovered_only_digests({"origin": None})
    assert is_recovered_only_digests({"synthetic": "true"})
    assert is_recovered_only_digests({"synthetic": None})
    assert not is_recovered_only_digests({})


def _month_required():
    policy = replace(
        coverage_contract_for("markets_calendar"),
        history_target_start="2025-01-01",
    )
    return policy, plan_required_segments(
        policy,
        "2025-01-31",
        expected_items_by_segment={"2025-01": 1},
    )[0]


def _authority(keys: SimpleNamespace) -> _SignedReceiptAuthority:
    return _SignedReceiptAuthority(signing_key=keys.signing_key)


def _issue(authority, required, raw, records):
    evidence = _reconcile_collection_evidence(
        required=required,
        run_id=1,
        raw_pages=(raw,),
        raw_records=records,
        structured_records=records,
        checked_at="2025-02-01T00:00:00+00:00",
    )
    return authority.issue(evidence)


def test_recovered_raw_only_cannot_complete():
    policy, req = _month_required()
    raw = b'{"data":[{"Date":"2025-01-01"}]}'
    receipt = build_collection_receipt(
        required=req,
        run_id=1,
        raw=raw,
        observed_items=1,
        structured_row_count=1,
        raw_row_count=1,
        extra_digests={
            "eligibility": "RECOVERED_RAW_ONLY",
            "origin": "recovered-raw-only",
        },
    )
    status, detail = evaluate_segment(policy, req, receipt)
    assert status == "PARTIAL"


def test_string_issuer_cannot_complete():
    policy, req = _month_required()
    raw = b'{"data":[{"Date":"2025-01-01"}]}'
    receipt = build_collection_receipt(
        required=req,
        run_id=1,
        raw=raw,
        observed_items=1,
        structured_row_count=1,
        raw_row_count=1,
        extra_digests={
            "eligibility": "TRUSTED_COLLECTION",
            "issuer_class": "TrustedReceiptIssuer",
            "issuer_id": "forged",
        },
    )
    assert receipt.digests.get("eligibility") == "RECOVERED_RAW_ONLY"
    status, _ = evaluate_segment(policy, req, receipt)
    assert status == "PARTIAL"


def test_signed_receipt_can_complete(receipt_ed25519_keys: SimpleNamespace):
    policy, req = _month_required()
    raw = b'{"data":[{"Date":"2025-01-01"}]}'
    auth = _authority(receipt_ed25519_keys)
    receipt = _issue(auth, req, raw, [{"Date": "2025-01-01"}])
    assert receipt.digests["signature"].startswith("ed25519:")
    status, detail = evaluate_segment(policy, req, receipt)
    assert status == "COMPLETE", detail


def test_malformed_recovery_sentinel_cannot_break_or_outrank_ledger(
    receipt_ed25519_keys: SimpleNamespace,
) -> None:
    policy, req = _month_required()
    raw = b'{"data":[{"Date":"2025-01-01"}]}'
    trusted = _issue(
        _authority(receipt_ed25519_keys),
        req,
        raw,
        [{"Date": "2025-01-01"}],
    )
    for key, value in (
        ("eligibility", []),
        ("eligibility", None),
        ("eligibility", "TRUSTED_COLLECTION "),
        ("origin", {}),
        ("origin", []),
        ("origin", None),
        ("synthetic", "true"),
        ("synthetic", None),
    ):
        malformed = replace(
            trusted,
            run_id=trusted.run_id + 1,
            checked_at="2025-02-02T00:00:00+00:00",
            digests={**trusted.digests, key: value},
        )
        aggregate, selected = evaluate_required_segments(policy, [req], [trusted, malformed])
        assert aggregate == "COMPLETE"
        assert selected[0][1] is trusted
        status, _detail = evaluate_segment(policy, req, malformed)
        assert status == "PARTIAL"


def test_signed_empty_data_envelope_is_not_complete(
    receipt_ed25519_keys: SimpleNamespace,
) -> None:
    """Signed SUCCESS over ``{"data":[]}`` is PARTIAL, not Coverage COMPLETE."""
    policy, req = _month_required()
    raw = b'{"data":[]}'
    auth = _authority(receipt_ed25519_keys)
    import pytest

    with pytest.raises(ValueError, match="zero-row SUCCESS"):
        _issue(auth, req, raw, [])


def test_evaluation_reuses_proof_but_rechecks_scope_and_changed_receipt(
    receipt_ed25519_keys, monkeypatch,
):
    import storage.coverage_ledger as ledger

    policy, required = _month_required()
    receipt = _issue(
        _authority(receipt_ed25519_keys), required,
        b'{"data":[{"Date":"2025-01-01"}]}', [{"Date": "2025-01-01"}],
    )
    verify = ledger.require_verified_collection_closure
    verified = []

    def counted_verify(value, **kwargs):
        verified.append(value)
        return verify(value, **kwargs)

    monkeypatch.setattr(ledger, "require_verified_collection_closure", counted_verify)
    _aggregate, evaluated = evaluate_required_segments(
        policy, [required, replace(required, expected_items=2)], [receipt],
    )
    assert [item[2] for item in evaluated] == ["COMPLETE", "PARTIAL"]
    assert "required.expected_items" in evaluated[1][3]["reason"]
    assert len(verified) == 1

    # Same DTO, mutated nested transport: a later evaluation must verify again.
    receipt.digests["signature"] = "ed25519:invalid"
    aggregate, evaluated = evaluate_required_segments(policy, [required], [receipt])
    assert aggregate == "PARTIAL"
    assert "receipt closure invalid" in evaluated[0][3]["reason"]
    assert len(verified) == 2
