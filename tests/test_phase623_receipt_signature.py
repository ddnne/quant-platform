"""Phase 6.2.3 signature forgery rejection and staging-only JSDA."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from storage.coverage_ledger import (
    RequiredCoverageSegment,
    evaluate_segment,
    is_complete_eligible_receipt,
)
from tests.receipt_test_support import (
    TestReconciledEvidence,
    _SignedReceiptAuthority,
    _reconcile_collection_evidence,
)
from storage.verified_receipt import ReceiptVerificationError, verify


def _issue(
    auth: _SignedReceiptAuthority,
    required: RequiredCoverageSegment,
    *,
    raw: bytes = b'{"data":[{"Date":"2025-01-01"}]}',
    records: list[dict] | None = None,
    structured: list[dict] | None = None,
    extra_evidence: dict | None = None,
):
    raw_records = records or [{"Date": "2025-01-01"}]
    structured_records = structured or list(raw_records)
    evidence = _reconcile_collection_evidence(
        required=required,
        run_id=1,
        raw_pages=(raw,),
        raw_records=raw_records,
        structured_records=structured_records,
        checked_at="2025-04-01T00:00:01+00:00",
        extra_evidence=extra_evidence,
    )
    return auth.issue(evidence)


def test_storage_package_hides_synthetic() -> None:
    import storage

    assert not hasattr(storage, "build_synthetic_complete_receipt")
    assert not hasattr(storage, "_SignedReceiptAuthority")
    assert not hasattr(storage, "TrustedReceiptIssuer")


def test_reconciled_evidence_constructor_and_replace_are_not_capabilities(
    receipt_ed25519_keys: SimpleNamespace,
) -> None:
    auth = _SignedReceiptAuthority(signing_key=receipt_ed25519_keys.signing_key)
    required = _calendar_required()
    import ingestion.runtime_authority as runtime
    import storage.trusted_receipt as trusted

    assert not hasattr(runtime, "_reconcile_collection_evidence")
    assert not hasattr(trusted, "_make_reconciled_collection_evidence")
    assert not hasattr(trusted, "_SignedReceiptAuthority")
    with pytest.raises(TypeError, match="opaque"):
        TestReconciledEvidence(  # type: ignore[call-arg]
            _seal=object(), required=required, claims={}
        )
    evidence = _reconcile_collection_evidence(
        required=required,
        run_id=1,
        raw_pages=(b'[{"Date":"2025-01-01"}]',),
        raw_records=({"Date": "2025-01-01"},),
        structured_records=({"Date": "2025-01-01"},),
        checked_at="2025-04-01T00:00:01+00:00",
    )
    forged_claims = dict(evidence.claims)
    forged_claims["observed_items"] = 2
    forged = replace(evidence, claims=forged_claims)
    with pytest.raises(TypeError, match="fixture-minted"):
        auth.issue(forged)


def test_reconciled_evidence_and_verified_closure_are_deeply_immutable(
    receipt_ed25519_keys: SimpleNamespace,
) -> None:
    auth = _SignedReceiptAuthority(signing_key=receipt_ed25519_keys.signing_key)
    required = replace(
        _calendar_required(),
        expected_scope={
            "month": "2025-01",
            "selection": {"markets": ["TSE"]},
        },
    )
    evidence = _reconcile_collection_evidence(
        required=required,
        run_id=1,
        raw_pages=(b'[{"Date":"2025-01-01"}]',),
        raw_records=({"Date": "2025-01-01"},),
        structured_records=({"Date": "2025-01-01"},),
        checked_at="2025-04-01T00:00:01+00:00",
        extra_evidence={"audit": {"sources": ["official"]}},
    )

    with pytest.raises(TypeError):
        evidence.required.expected_scope["selection"]["markets"] = ("evil",)
    with pytest.raises(TypeError):
        evidence.extra_digests["audit"]["sources"] = ("evil",)

    closure = verify(auth.issue(evidence), required=required)
    with pytest.raises(TypeError):
        closure.expected_scope["selection"]["markets"] = ("evil",)
    with pytest.raises(TypeError):
        closure.extra_digests["audit"]["sources"] = ("evil",)
    forged_closure = replace(
        closure,
        _claims={"source": "evil"},
    )
    with pytest.raises(TypeError, match="verifier-minted"):
        _ = forged_closure.source


def test_forged_signature_rejected(receipt_ed25519_keys: SimpleNamespace):
    auth = _SignedReceiptAuthority(signing_key=receipt_ed25519_keys.signing_key)
    req = RequiredCoverageSegment(
        source="jquants",
        dataset="markets_calendar",
        segment_id="2025-01",
        segment_start="2025-01-01",
        segment_end="2025-01-31",
        expected_scope={"month": "2025-01"},
        expected_items=1,
    )
    good = _issue(auth, req)
    assert is_complete_eligible_receipt(good)
    # Tamper signature
    bad_digests = dict(good.digests)
    bad_digests["signature"] = "ed25519:" + base64.b64encode(b"\x00" * 64).decode()
    from storage.coverage_ledger import CollectionReceipt

    forged = CollectionReceipt(
        source=good.source,
        dataset=good.dataset,
        segment_id=good.segment_id,
        segment_start=good.segment_start,
        segment_end=good.segment_end,
        expected_scope=good.expected_scope,
        expected_items=good.expected_items,
        observed_items=good.observed_items,
        raw_page_count=good.raw_page_count,
        raw_row_count=good.raw_row_count,
        structured_row_count=good.structured_row_count,
        pagination_exhausted=good.pagination_exhausted,
        digests=bad_digests,
        run_id=good.run_id,
        status=good.status,
        error=good.error,
        checked_at=good.checked_at,
    )
    assert not is_complete_eligible_receipt(forged)


def test_stateful_digest_mapping_cannot_swap_signed_body_after_verification(
    receipt_ed25519_keys: SimpleNamespace,
) -> None:
    """The former A-signature/B-claims confused deputy is fail-closed."""
    from storage.coverage_ledger import CollectionReceipt
    from storage.verified_receipt import audit_signed_receipt_claims

    authority = _SignedReceiptAuthority(
        signing_key=receipt_ed25519_keys.signing_key
    )
    required_a = _calendar_required()
    required_b = replace(
        required_a,
        segment_id="2025-02",
        segment_start="2025-02-01",
        segment_end="2025-02-28",
        expected_scope={"month": "2025-02"},
    )
    receipt_a = _issue(authority, required_a)
    receipt_b = _issue(authority, required_b)

    class SwitchingDigests(dict):
        def __init__(self) -> None:
            super().__init__(receipt_b.digests)
            self.body_reads = 0

        def get(self, key, default=None):
            if key == "signed_body_b64":
                self.body_reads += 1
                if self.body_reads == 1:
                    return receipt_a.digests[key]
            if key == "signature":
                return receipt_a.digests[key]
            return super().get(key, default)

    switched = replace(receipt_b, digests=SwitchingDigests())
    with pytest.raises(ReceiptVerificationError, match="exact built-in dict"):
        verify(switched, required=required_b)
    with pytest.raises(ReceiptVerificationError, match="exact built-in dict"):
        audit_signed_receipt_claims(switched)
    assert not is_complete_eligible_receipt(switched)

    stable_transplant = replace(
        receipt_b,
        digests={
            **receipt_b.digests,
            "signature": receipt_a.digests["signature"],
        },
    )
    with pytest.raises(ReceiptVerificationError, match="signature is invalid"):
        verify(stable_transplant, required=required_b)

    # The ordinary exact DTO remains the sole accepted transport type.
    assert verify(receipt_b, required=required_b).segment_id == "2025-02"
    assert type(receipt_b) is CollectionReceipt


def test_receipt_and_scalar_subclasses_cannot_enter_closure_authority(
    receipt_ed25519_keys: SimpleNamespace,
) -> None:
    from storage.coverage_ledger import CollectionReceipt

    receipt = _issue(
        _SignedReceiptAuthority(signing_key=receipt_ed25519_keys.signing_key),
        _calendar_required(),
    )

    class ReceiptSubclass(CollectionReceipt):
        pass

    subclass = ReceiptSubclass(
        **{
            name: object.__getattribute__(receipt, name)
            for name in CollectionReceipt.__dataclass_fields__
        }
    )
    with pytest.raises(ReceiptVerificationError, match="exact CollectionReceipt"):
        verify(subclass)

    class StatefulString(str):
        pass

    scalar_subclass = replace(receipt, dataset=StatefulString(receipt.dataset))
    with pytest.raises(ReceiptVerificationError, match="exact non-empty strings"):
        verify(scalar_subclass)

    class ScopeSubclass(dict):
        pass

    scope_subclass = replace(
        receipt, expected_scope=ScopeSubclass(receipt.expected_scope)
    )
    with pytest.raises(ReceiptVerificationError, match="exact JSON"):
        verify(scope_subclass)


def test_prior_v3_receipt_remains_audit_only_and_loses_complete_eligibility(
    receipt_ed25519_keys: SimpleNamespace,
) -> None:
    from storage.receipt_crypto import body_digest, canonical_receipt_body
    from storage.verified_receipt import audit_signed_receipt_claims

    receipt = _issue(
        _SignedReceiptAuthority(signing_key=receipt_ed25519_keys.signing_key),
        _calendar_required(),
    )
    claims = json.loads(base64.b64decode(receipt.digests["signed_body_b64"]))
    claims["parser_normalizer_version"] = "coverage-receipt/v3-ed25519-closure"
    body = canonical_receipt_body(claims)
    digests = dict(receipt.digests)
    digests.update(
        {
            "parser_normalizer_version": claims["parser_normalizer_version"],
            "signed_body_b64": base64.b64encode(body).decode("ascii"),
            "signature": receipt_ed25519_keys.signing_key.sign(body),
            "body_digest": body_digest(body),
        }
    )
    prior_v3 = replace(receipt, digests=digests)

    assert audit_signed_receipt_claims(prior_v3)[
        "parser_normalizer_version"
    ] == "coverage-receipt/v3-ed25519-closure"
    with pytest.raises(ReceiptVerificationError, match="parser_normalizer_version"):
        verify(prior_v3, required=_calendar_required())
    assert not is_complete_eligible_receipt(prior_v3)


def test_signed_body_cannot_gain_eligibility_from_a_caller_issuer_class(
    receipt_ed25519_keys: SimpleNamespace,
) -> None:
    receipt = _issue(
        _SignedReceiptAuthority(signing_key=receipt_ed25519_keys.signing_key),
        _calendar_required(),
    )
    mutated = replace(
        receipt,
        digests={**receipt.digests, "issuer_class": "CallerSuppliedAuthority"},
    )
    with pytest.raises(ReceiptVerificationError, match="issuer class"):
        verify(mutated, required=_calendar_required())
    assert not is_complete_eligible_receipt(mutated)


def _calendar_required() -> RequiredCoverageSegment:
    return RequiredCoverageSegment(
        source="jquants",
        dataset="markets_calendar",
        segment_id="2025-01",
        segment_start="2025-01-01",
        segment_end="2025-01-31",
        expected_scope={"month": "2025-01"},
        expected_items=1,
    )


def test_signature_transplant_onto_mutated_outer_receipt_rejected(
    receipt_ed25519_keys: SimpleNamespace,
):
    from data_contracts import coverage_contract_for

    auth = _SignedReceiptAuthority(signing_key=receipt_ed25519_keys.signing_key)
    req = _calendar_required()
    raw = b'{"data":[{"Date":"2025-01-01"}]}'
    good = _issue(auth, req, raw=raw)
    verify(good, required=req, raw=raw)
    assert is_complete_eligible_receipt(good)

    transplanted = replace(
        good,
        segment_id="2099-12",
        segment_start="2099-12-01",
        segment_end="2099-12-31",
    )
    assert transplanted.digests["signature"] == good.digests["signature"]
    assert transplanted.digests["signed_body_b64"] == good.digests["signed_body_b64"]
    with pytest.raises(ReceiptVerificationError):
        verify(transplanted)
    assert not is_complete_eligible_receipt(transplanted)

    spoofed_required = replace(
        req,
        segment_id="2099-12",
        segment_start="2099-12-01",
        segment_end="2099-12-31",
    )
    policy = coverage_contract_for("markets_calendar")
    status, _detail = evaluate_segment(policy, spoofed_required, transplanted)
    assert status != "COMPLETE"


def test_extra_digests_cannot_override_standard_claims(
    receipt_ed25519_keys: SimpleNamespace,
):
    from storage.coverage_ledger import compute_raw_digest

    auth = _SignedReceiptAuthority(signing_key=receipt_ed25519_keys.signing_key)
    req = _calendar_required()
    raw = b'{"data":[{"Date":"2025-01-01"}]}'
    receipt = _issue(
        auth,
        req,
        raw=raw,
        extra_evidence={
            "dataset": "evil-dataset",
            "raw_digest": "sha256:" + "f" * 64,
            "eligibility": "TRUSTED_COLLECTION",
            "origin": "operator-note",
        },
    )
    body = json.loads(base64.b64decode(receipt.digests["signed_body_b64"]))
    assert body["dataset"] == req.dataset
    assert "dataset" not in body["extra_digests"]
    assert "raw_digest" not in body["extra_digests"]
    assert body["extra_digests"]["origin"] == "operator-note"
    assert receipt.digests["raw"] == compute_raw_digest(raw)
    assert receipt.digests["raw"] != "sha256:" + "f" * 64
    verify(receipt, required=req, raw=raw)
    assert is_complete_eligible_receipt(receipt)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", "jsda"),
        ("dataset", "equities_master"),
        ("segment_id", "tampered"),
        ("segment_start", "2024-12-01"),
        ("segment_end", "2025-02-01"),
        ("expected_scope", {"month": "tampered"}),
        ("expected_items", 2),
        ("observed_items", 2),
        ("raw_page_count", 2),
        ("raw_row_count", 2),
        ("structured_row_count", 2),
        ("pagination_exhausted", False),
        ("run_id", 2),
        ("status", "FAILED"),
        ("error", "tampered"),
        ("checked_at", "2099-01-01T00:00:00+00:00"),
    ],
)
def test_every_outer_complete_input_is_bound(
    receipt_ed25519_keys: SimpleNamespace, field: str, value: object
) -> None:
    auth = _SignedReceiptAuthority(signing_key=receipt_ed25519_keys.signing_key)
    receipt = _issue(auth, _calendar_required())
    mutated = replace(receipt, **{field: value})
    with pytest.raises(ReceiptVerificationError):
        verify(mutated)
    assert not is_complete_eligible_receipt(mutated)


@pytest.mark.parametrize(
    "field",
    [
        "raw",
        "structured_digest",
        "source_request_digest",
        "raw_manifest_digest",
        "scope_digest",
        "observation_digest",
    ],
)
def test_every_digest_alias_is_bound(
    receipt_ed25519_keys: SimpleNamespace, field: str
) -> None:
    auth = _SignedReceiptAuthority(signing_key=receipt_ed25519_keys.signing_key)
    receipt = _issue(auth, _calendar_required())
    digests = dict(receipt.digests)
    digests[field] = "sha256:" + "f" * 64
    mutated = replace(receipt, digests=digests)
    with pytest.raises(ReceiptVerificationError):
        verify(mutated)


def test_valid_signature_cannot_bypass_scope_observation_digest_chain(
    receipt_ed25519_keys: SimpleNamespace,
) -> None:
    from tests.receipt_test_support import build_test_signed_digest_fields

    auth = _SignedReceiptAuthority(signing_key=receipt_ed25519_keys.signing_key)
    receipt = _issue(auth, _calendar_required())
    claims = json.loads(base64.b64decode(receipt.digests["signed_body_b64"]))
    claims["scope_digest"] = "sha256:" + "f" * 64
    for envelope_field in (
        "version",
        "parser_normalizer_version",
        "issuer_id",
        "issued_at",
    ):
        claims.pop(envelope_field)
    inconsistent_but_signed = build_test_signed_digest_fields(
        signing_key=receipt_ed25519_keys.signing_key,
        closure_claims=claims,
    )
    mutated = replace(receipt, digests=inconsistent_but_signed)

    with pytest.raises(ReceiptVerificationError, match="digest chain"):
        verify(mutated)


def test_jsda_staging_never_complete_eligible(tmp_path: Path):
    from ingestion.jsda.r2_parse import run_jsda_staging_parse
    import sqlite3
    from storage.sqlite_store import SqliteStore

    raw = tmp_path / "raw" / "jsda" / "jsda_tokyo_repo_rates" / "file_trrts"
    raw.mkdir(parents=True)
    # minimal csv
    (raw / "x.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    db = tmp_path / "t.sqlite"
    store = SqliteStore(db)
    result = run_jsda_staging_parse(
        raw_root=tmp_path / "raw", conn=store._conn, run_id=1
    )
    assert result.state == "PARSED_STAGING_ONLY"
    assert result.staging_evidence_written >= 1
    # digests may be JSON column or expanded; re-read via ledger helper
    assert result.rows_parsed >= 1
    # Staging path must not produce COMPLETE-eligible signed digests.
    row = store._conn.execute(
        "SELECT digests_json FROM collection_receipts LIMIT 1"
    ).fetchone()
    if row is None:
        # schema may store digests as TEXT digests column
        cols = [
            r[1]
            for r in store._conn.execute(
                "PRAGMA table_info(collection_receipts)"
            ).fetchall()
        ]
        dig_col = "digests" if "digests" in cols else cols[-1]
        row = store._conn.execute(
            f"SELECT {dig_col} FROM collection_receipts LIMIT 1"
        ).fetchone()
    assert row is not None
    digests = json.loads(row[0]) if isinstance(row[0], str) else dict(row[0] or {})
    assert digests.get("origin") == "parsed-staging-only" or digests.get(
        "state"
    ) == "PARSED_STAGING_ONLY"
    assert digests.get("eligibility") != "TRUSTED_COLLECTION" or not digests.get(
        "signature"
    )
