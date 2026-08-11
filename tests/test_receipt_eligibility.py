"""Signed receipt boundary: only Ed25519-verified receipts can COMPLETE."""
from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from data_contracts import coverage_contract_for
from storage.coverage_ledger import (
    build_collection_receipt,
    evaluate_segment,
    plan_required_segments,
)
from storage.receipt_crypto import ReceiptSigningKey, generate_keypair
from storage.trusted_receipt import SignedReceiptAuthority
import storage.receipt_crypto as rc


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


def _authority() -> SignedReceiptAuthority:
    priv_pem, pub, kid = generate_keypair(key_id="test-key")
    keys_path = rc.PUBLIC_KEYS_PATH
    try:
        doc = json.loads(keys_path.read_text(encoding="utf-8"))
    except Exception:
        doc = {"schema_version": 1, "keys": []}
    keys = [k for k in (doc.get("keys") or []) if k.get("key_id") != kid]
    keys.append(
        {
            "key_id": kid,
            "public_key_b64": base64.b64encode(pub).decode(),
            "algorithm": "Ed25519",
        }
    )
    doc["keys"] = keys
    keys_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    priv = load_pem_private_key(priv_pem, password=None)
    assert isinstance(priv, Ed25519PrivateKey)
    return SignedReceiptAuthority(
        signing_key=ReceiptSigningKey(key_id=kid, _private=priv)
    )


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


def test_signed_receipt_can_complete():
    policy, req = _month_required()
    raw = b'{"data":[{"Date":"2025-01-01"}]}'
    auth = _authority()
    receipt = auth.issue(
        required=req,
        run_id=1,
        raw=raw,
        observed_items=1,
        structured_row_count=1,
        raw_row_count=1,
    )
    assert receipt.digests["signature"].startswith("ed25519:")
    status, detail = evaluate_segment(policy, req, receipt)
    assert status == "COMPLETE", detail
