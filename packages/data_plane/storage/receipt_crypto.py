"""Ed25519 receipt signing authority (Phase 6.2.3 P0).

Private key material is loaded only by the trusted ingestion runtime.
Coverage/READY verification uses public keys only — issuer_class strings
alone never grant COMPLETE eligibility.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

CONFIG_DIR = Path.home() / ".config" / "quant-platform"
PRIVATE_KEY_ENV = "QUANT_RECEIPT_SIGNING_KEY_PEM"
PRIVATE_KEY_FILE = CONFIG_DIR / "receipt_signing_key.pem"
VERIFY_KEYS_ENV = "QUANT_RECEIPT_VERIFY_KEYS"
DISABLE_HOST_PEM_ENV = "QUANT_RECEIPT_DISABLE_HOST_PEM"


def _host_pem_disabled() -> bool:
    """True under pytest or QUANT_RECEIPT_DISABLE_HOST_PEM=1.

    Explicit pem=/path=/QUANT_RECEIPT_SIGNING_KEY_PEM are unaffected.
    Missing keys stay fail-closed (None).
    """
    if os.environ.get(DISABLE_HOST_PEM_ENV, "").strip() == "1":
        return True
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _contracts_dir() -> Path:
    """Locate data_contracts on disk (import-stable; layout may be packages/*)."""
    import importlib.util

    spec = importlib.util.find_spec("data_contracts")
    if spec is not None:
        if spec.submodule_search_locations:
            return Path(next(iter(spec.submodule_search_locations)))
        if spec.origin:
            return Path(spec.origin).resolve().parent
    from qp_paths import repo_root

    root = repo_root()
    for candidate in (
        root / "packages" / "data_plane" / "data_contracts",
        root / "data_contracts",
    ):
        if candidate.is_dir():
            return candidate
    return root / "packages" / "data_plane" / "data_contracts"


PUBLIC_KEYS_PATH = _contracts_dir() / "receipt_verify_public_keys.json"


def _verify_keys_path(path: Path | None = None) -> Path:
    """Resolve public-key registry: explicit path, env override, then production default."""
    if path is not None:
        return path
    override = os.environ.get(VERIFY_KEYS_ENV, "").strip()
    if override:
        return Path(override)
    return PUBLIC_KEYS_PATH


PARSER_NORMALIZER_VERSION = "coverage-receipt/v4-ed25519-closure"
SIGNED_RECEIPT_CLAIMS_VERSION = "signed-receipt-claims/v2"
LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION = "signed-receipt-claims/v1"

# Closed claim names plus envelope aliases. extra_digests cannot occupy these.
STANDARD_CLAIM_KEYS = frozenset(
    {
        "version",
        "coverage_policy_version",
        "dataset",
        "source",
        "segment_id",
        "segment_start",
        "segment_end",
        "expected_scope",
        "expected_items",
        "observed_items",
        "raw_page_count",
        "source_request_digest",
        "raw_manifest_digest",
        "raw_digest",
        "raw_count",
        "structured_digest",
        "structured_count",
        "parser_normalizer_version",
        "structured_generation",
        "pagination_exhausted",
        "discovery_exhausted",
        "status",
        "error",
        "scope_digest",
        "observation_digest",
        "run_id",
        "issuer_id",
        "issued_at",
        "checked_at",
        "extra_digests",
        "raw",
        "eligibility",
        "signature",
        "signed_body_b64",
        "issuer_class",
        "issuer_key_id",
        "body_digest",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_receipt_body(fields: Mapping[str, Any]) -> bytes:
    """Deterministic JSON bytes for signing (sorted keys, no whitespace)."""
    return json.dumps(
        dict(fields),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")


def body_digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def canonical_evidence_digest(payload: Any) -> str:
    """Digest bytes verbatim or structured evidence as closed canonical JSON."""
    raw = payload if isinstance(payload, bytes) else json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    ).encode("utf-8")
    return body_digest(raw)


@dataclass(frozen=True)
class ReceiptSigningKey:
    """Private signing material — never construct from public digests."""

    key_id: str
    _private: Ed25519PrivateKey

    def sign(self, body: bytes) -> str:
        sig = self._private.sign(body)
        return "ed25519:" + base64.b64encode(sig).decode("ascii")


@dataclass(frozen=True)
class ReceiptVerifyKey:
    key_id: str
    public_key: Ed25519PublicKey

    def verify(self, body: bytes, signature: str) -> bool:
        if not signature.startswith("ed25519:"):
            return False
        try:
            raw = base64.b64decode(signature[len("ed25519:") :], validate=True)
            self.public_key.verify(raw, body)
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False


def generate_keypair(*, key_id: str = "dev-receipt-v1") -> tuple[bytes, bytes, str]:
    """Return (private_pem, public_raw, key_id) for bootstrap/tests."""
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv_pem, pub, key_id


def load_signing_key(
    *,
    pem: bytes | str | None = None,
    path: Path | None = None,
    key_id: str | None = None,
) -> ReceiptSigningKey | None:
    """Load private key from explicit pem, path, env, or config file.

    Returns None if no private material is configured (production fail-closed
    for signing; tests inject keys explicitly).

    Under pytest (PYTEST_CURRENT_TEST) or QUANT_RECEIPT_DISABLE_HOST_PEM=1,
    the host config file is not read. Explicit pem=, path=, and
    QUANT_RECEIPT_SIGNING_KEY_PEM still apply.
    """
    material: bytes | None = None
    if pem is not None:
        material = pem.encode("utf-8") if isinstance(pem, str) else pem
    elif path is not None and path.is_file():
        material = path.read_bytes()
    else:
        env = os.environ.get(PRIVATE_KEY_ENV, "").strip()
        if env:
            material = env.encode("utf-8") if "BEGIN" in env else base64.b64decode(env)
        elif not _host_pem_disabled() and PRIVATE_KEY_FILE.is_file():
            material = PRIVATE_KEY_FILE.read_bytes()
    if not material:
        return None
    priv = serialization.load_pem_private_key(material, password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        raise TypeError("receipt signing key must be Ed25519")
    kid = key_id or os.environ.get("QUANT_RECEIPT_KEY_ID")
    if not kid:
        # Prefer key_id from committed public-key registry when present.
        try:
            keys_path = _verify_keys_path()
            if keys_path.is_file():
                doc = json.loads(keys_path.read_text(encoding="utf-8"))
                rows = doc.get("keys") or []
                if rows and rows[0].get("key_id"):
                    kid = str(rows[0]["key_id"])
        except (OSError, json.JSONDecodeError, TypeError, KeyError):
            kid = None
    kid = kid or "receipt-v1"
    return ReceiptSigningKey(key_id=kid, _private=priv)


@lru_cache(maxsize=8)
def _load_verify_key_file(
    path_text: str, mtime_ns: int, size: int
) -> tuple[ReceiptVerifyKey, ...]:
    """Parse one immutable registry generation; stat fields key the cache."""
    del mtime_ns, size
    keys_path = Path(path_text)
    out: dict[str, ReceiptVerifyKey] = {}
    if keys_path.is_file():
        doc = json.loads(keys_path.read_text(encoding="utf-8"))
        for row in doc.get("keys") or []:
            kid = str(row["key_id"])
            raw = base64.b64decode(str(row["public_key_b64"]))
            out[kid] = ReceiptVerifyKey(
                key_id=kid,
                public_key=Ed25519PublicKey.from_public_bytes(raw),
            )
    return tuple(out.values())


def load_verify_keys(
    *,
    extra: Mapping[str, bytes] | None = None,
    path: Path | None = None,
) -> dict[str, ReceiptVerifyKey]:
    """Load public keys for receipt verification, cached per file generation."""
    keys_path = _verify_keys_path(path)
    try:
        stat = keys_path.stat()
        rows = _load_verify_key_file(
            str(keys_path.resolve()), stat.st_mtime_ns, stat.st_size
        )
    except OSError:
        rows = ()
    out = {row.key_id: row for row in rows}
    if extra:
        for kid, raw in extra.items():
            out[kid] = ReceiptVerifyKey(
                key_id=kid,
                public_key=Ed25519PublicKey.from_public_bytes(raw),
            )
    return out


def partition_extra_digests(extra_digests: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy extra_digests excluding standard claims and envelope aliases."""
    if extra_digests is None:
        return {}
    if not isinstance(extra_digests, Mapping):
        raise TypeError("extra_digests must be a mapping")
    return {
        str(key): value
        for key, value in extra_digests.items()
        if str(key) not in STANDARD_CLAIM_KEYS
    }


def verify_receipt_signature(
    digests: Mapping[str, Any],
    *,
    verify_keys: Mapping[str, ReceiptVerifyKey] | None = None,
) -> bool:
    """True iff digests carry a valid Ed25519 signature over the body."""
    body_b64 = digests.get("signed_body_b64")
    signature = digests.get("signature")
    key_id = digests.get("issuer_key_id")
    if not isinstance(body_b64, str) or not isinstance(signature, str):
        return False
    if not isinstance(key_id, str) or not key_id:
        return False
    keys = verify_keys if verify_keys is not None else load_verify_keys()
    vk = keys.get(key_id)
    if vk is None:
        return False
    try:
        body = base64.b64decode(body_b64, validate=True)
    except (ValueError, TypeError):
        return False
    return vk.verify(body, signature)


def build_signed_digest_fields(
    *,
    signing_key: ReceiptSigningKey,
    closure_claims: Mapping[str, Any],
    issued_at: str | None = None,
) -> dict[str, Any]:
    """Sign a pre-reconciled v2 closure.

    This function deliberately accepts one closed claims object rather than
    caller-supplied counts and digests.  Only the ingestion reconciliation
    boundary builds that object; this layer adds issuer identity and signs it.
    """
    issued = issued_at or _now()
    body_fields = dict(closure_claims)
    extras = partition_extra_digests(body_fields.get("extra_digests"))
    body_fields.update(
        {
            "version": SIGNED_RECEIPT_CLAIMS_VERSION,
            "parser_normalizer_version": PARSER_NORMALIZER_VERSION,
            "issuer_id": signing_key.key_id,
            "issued_at": issued,
            "extra_digests": extras,
        }
    )
    forbidden = {
        "signature",
        "signed_body_b64",
        "body_digest",
        "eligibility",
        "issuer_class",
        "issuer_key_id",
    }
    overlap = sorted(forbidden & set(closure_claims))
    if overlap:
        raise ValueError(f"closure claims contain signature envelope fields: {overlap}")
    body = canonical_receipt_body(body_fields)
    signature = signing_key.sign(body)
    envelope = {
        "eligibility": "TRUSTED_COLLECTION",
        "issuer_class": "SignedReceiptAuthority",
        "issuer_key_id": signing_key.key_id,
        "issuer_id": signing_key.key_id,
        "parser_normalizer_version": PARSER_NORMALIZER_VERSION,
        "signed_body_b64": base64.b64encode(body).decode("ascii"),
        "signature": signature,
        "body_digest": body_digest(body),
        "issued_at": issued,
        "checked_at": body_fields["checked_at"],
        "source_request_digest": body_fields["source_request_digest"],
        "raw_manifest_digest": body_fields["raw_manifest_digest"],
        "raw": body_fields["raw_digest"],
        "structured_generation": body_fields["structured_generation"],
        "structured_digest": body_fields["structured_digest"],
        "scope_digest": body_fields["scope_digest"],
        "observation_digest": body_fields["observation_digest"],
        "extra_digests": extras,
    }
    envelope.update(extras)
    return envelope


__all__ = [
    "PARSER_NORMALIZER_VERSION",
    "LEGACY_SIGNED_RECEIPT_CLAIMS_VERSION",
    "SIGNED_RECEIPT_CLAIMS_VERSION",
    "STANDARD_CLAIM_KEYS",
    "ReceiptSigningKey",
    "ReceiptVerifyKey",
    "build_signed_digest_fields",
    "canonical_evidence_digest",
    "canonical_receipt_body",
    "generate_keypair",
    "load_signing_key",
    "load_verify_keys",
    "partition_extra_digests",
    "verify_receipt_signature",
]
