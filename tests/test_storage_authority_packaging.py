"""Package-owned storage verification authorities retain exact identities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from storage import coverage_transition, verified_receipt


_ROOT = Path(__file__).resolve().parents[1]
_COVERAGE_RAW_DIGEST = (
    "4ea51389a65da233f25235a3444fcadc3946013be36518908244458f79eb3a94"
)
_COVERAGE_CANONICAL_DIGEST = (
    "sha256:9e6c239cf85ab09999ef4aa90881a55abdcc246488df2c1ded9e9d2a5947de49"
)
_RECEIPT_SCHEMA_RAW_DIGEST = (
    "123cbb43180aa7d22e41541589cc28bf0da27f120533b796458c831fb655f261"
)


def _raw_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_coverage_transition_registry_is_package_owned_and_digest_stable() -> None:
    path = coverage_transition._PINNED_REGISTRY_PATH
    assert path == (
        Path(coverage_transition.__file__).resolve().with_name("authorities")
        / "coverage_transition"
        / "public_keys.json"
    )
    assert _raw_digest(path) == _COVERAGE_RAW_DIGEST
    document = json.loads(path.read_text(encoding="utf-8"))
    assert coverage_transition._digest(document) == _COVERAGE_CANONICAL_DIGEST
    assert coverage_transition._PINNED_REGISTRY_DIGEST == (
        _COVERAGE_CANONICAL_DIGEST
    )
    assert not coverage_transition.CoverageTransitionPublicKeyRegistry.load_pinned().provisioned
    assert not (_ROOT / "specs/coverage_transition/public_keys.json").exists()


def test_signed_receipt_schema_is_package_owned_and_digest_stable() -> None:
    path = verified_receipt._SCHEMA_PATH
    assert path == (
        Path(verified_receipt.__file__).resolve().with_name("authorities")
        / "receipts"
        / "signed_receipt_claims.schema.json"
    )
    assert _raw_digest(path) == _RECEIPT_SCHEMA_RAW_DIGEST
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["$id"] == "specs/receipts/signed_receipt_claims.schema.json"
    assert document["title"] == "SignedCollectionClosureClaimsV2"
    assert not (
        _ROOT / "specs/receipts/signed_receipt_claims.schema.json"
    ).exists()
