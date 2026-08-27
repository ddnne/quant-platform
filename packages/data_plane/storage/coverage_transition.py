"""Verify and atomically consume a first-COMPLETE Coverage transition.

Generic Coverage refresh and sync deliberately cannot promote an aggregate to
``COMPLETE``.  A separately permissioned authority may authorize one exact
transition by signing the content-addressed document defined here.  This
process contains public verification material only: it independently replays
the active build cutoff, current policy, exact segment inventory, and every
selected signed receipt before applying the transition with a durable CAS
tombstone.

The checked-in production registry is intentionally empty until the external
authority is provisioned.  In that state application is ``PENDING`` and no
transition evidence or aggregate mutation is written.

Path identity is pinned and checked at the mutation and commit boundaries.
Preventing a same-user filesystem actor from racing those checks or restoring
an older database after commit remains an A2 deployment/provisioning control;
this verifier does not claim to create an OS principal boundary by itself.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import stat
from types import MappingProxyType
from typing import Any, Mapping, NoReturn, Sequence
from urllib.parse import quote

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from data_contracts.coverage import (
    COVERAGE_STATUSES,
    coverage_contract_for,
    coverage_policy_binding,
    coverage_policy_set_binding,
)
from storage.coverage_ledger import (
    CoverageInventoryAuthorityUnavailable,
    CoveragePublicationCutoffError,
    validation_coverage_cutoff_for_build,
    verify_exact_coverage_complete,
)


COVERAGE_TRANSITION_FORMAT = "coverage-complete-transition/v1"
COVERAGE_TRANSITION_DOMAIN = (
    "quant-platform/coverage/complete-transition/v1"
)
COVERAGE_TRANSITION_ISSUER = "CoverageCompleteTransitionAuthority/v1"
COVERAGE_TRANSITION_ALGORITHM = "Ed25519"
COVERAGE_TRANSITION_PENDING_REASON = (
    "COVERAGE_TRANSITION_AUTHORITY_UNPROVISIONED"
)
MAX_AUTHORIZATION_SECONDS = 15 * 60

_PINNED_REGISTRY_PATH = (
    Path(__file__).with_name("authorities")
    / "coverage_transition"
    / "public_keys.json"
)
# Filled with the canonical digest of the checked-in empty public registry.
_PINNED_REGISTRY_DIGEST = (
    "sha256:9e6c239cf85ab09999ef4aa90881a55abdcc246488df2c1ded9e9d2a5947de49"
)
_DIGEST_PREFIX = "sha256:"
_DATASET_COVERAGE_COLUMNS = (
    "dataset",
    "status",
    "policy_version",
    "collection_scope",
    "history_target_start",
    "history_target_end_rule",
    "coverage_mode",
    "expected_frequency",
    "universe_rule",
    "raw_retention_required",
    "structured_reconciliation_required",
    "governance_tier",
    "observed_start",
    "observed_end",
    "row_count",
    "source_run_id",
    "evaluated_at",
    "detail_json",
)
_TOMBSTONE_COLUMNS = (
    "transition_id",
    "format",
    "authority_domain",
    "issuer_key_id",
    "build_id",
    "publication_cutoff",
    "dataset_set_digest",
    "from_state_digest",
    "target_state_digest",
    "coverage_policy_set_digest",
    "inventory_set_digest",
    "receipt_set_digest",
    "signed_evidence_json",
    "consumed_at",
)
_TOMBSTONE_TRIGGER_NAMES = frozenset(
    {
        "coverage_complete_transition_tombstones_no_update",
        "coverage_complete_transition_tombstones_no_delete",
    }
)
_SIGNED_DOCUMENT_FIELDS = frozenset(
    {
        "format",
        "authority_domain",
        "issuer",
        "issuer_key_id",
        "algorithm",
        "transition_id",
        "body",
        "signature",
    }
)
_BODY_FIELDS = frozenset(
    {
        "build_id",
        "publication_cutoff",
        "datasets",
        "dataset_set_digest",
        "from_state",
        "from_state_digest",
        "target_state",
        "target_state_digest",
        "coverage_policy_set",
        "coverage_policy_set_digest",
        "inventory_set_digest",
        "inventory_count",
        "receipt_set_digest",
        "receipt_count",
        "issued_at",
        "expires_at",
    }
)


class CoverageTransitionError(ValueError):
    """A transition document or its live state binding is invalid."""


class CoverageTransitionAuthorityPending(RuntimeError):
    """The separately permissioned production authority is not provisioned."""

    status = "PENDING"
    reason_code = COVERAGE_TRANSITION_PENDING_REASON

    def __init__(self) -> None:
        super().__init__(f"{self.status}: {self.reason_code}")


class CoverageTransitionAlreadyConsumed(CoverageTransitionError):
    """The signed one-shot transition already has a durable tombstone."""


@dataclass(frozen=True, slots=True)
class _DatabaseIdentity:
    device: int
    inode: int


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonical_json(value: Any) -> str:
    return _canonical_bytes(value).decode("utf-8")


def _digest(value: Any) -> str:
    return _DIGEST_PREFIX + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_digest(value: Any, *, field: str) -> str:
    if type(value) is not str or len(value) != 71 or not value.startswith(
        _DIGEST_PREFIX
    ):
        raise CoverageTransitionError(f"{field} must be a sha256 digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise CoverageTransitionError(f"{field} must be a sha256 digest") from exc
    return value


def _freeze_json(value: Any, *, field: str = "document") -> Any:
    """Materialize authority input once and reject adapter-confused subclasses."""
    if type(value) is dict:
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str or key in frozen:
                raise TypeError(f"{field} keys must be unique built-in strings")
            frozen[key] = _freeze_json(item, field=f"{field}.{key}")
        return frozen
    if type(value) is list:
        return [
            _freeze_json(item, field=f"{field}[{index}]")
            for index, item in enumerate(value)
        ]
    if type(value) in {str, int, bool, type(None)}:
        return value
    raise TypeError(f"{field} must contain only exact JSON built-in values")


def _parse_utc_z(value: Any, *, field: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise CoverageTransitionError(f"{field} must be canonical UTC Z time")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CoverageTransitionError(f"{field} must be canonical UTC Z time") from exc
    canonical = parsed.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    if parsed.tzinfo is None or parsed.utcoffset() is None or canonical != value:
        raise CoverageTransitionError(f"{field} must be canonical UTC Z time")
    return parsed


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _observe_authorization_time(
    *,
    issued: datetime,
    expires: datetime,
    previous: datetime | None,
    stage: str,
    window_error: str,
) -> datetime:
    """Read internal UTC once and bind it to the window and prior reading."""

    observed = _utc_now()
    if (
        type(observed) is not datetime
        or observed.tzinfo is None
        or observed.utcoffset() is None
    ):
        raise CoverageTransitionError(
            f"Coverage transition internal clock is invalid at {stage}"
        )
    observed = observed.astimezone(timezone.utc)
    if previous is not None and observed < previous:
        raise CoverageTransitionError(
            f"Coverage transition clock moved backwards before {stage}"
        )
    if observed < issued or observed > expires:
        raise CoverageTransitionError(window_error)
    return observed


def _normalize_datasets(datasets: Sequence[str]) -> tuple[str, ...]:
    if type(datasets) not in {tuple, list}:
        raise TypeError("Coverage transition datasets must be a list or tuple")
    selected = tuple(datasets)
    if (
        not selected
        or any(type(item) is not str or not item for item in selected)
        or selected != tuple(sorted(selected))
        or len(selected) != len(set(selected))
    ):
        raise CoverageTransitionError(
            "Coverage transition datasets must be sorted and duplicate-free"
        )
    return selected


def _resolve_db_path(db_path: str) -> Path:
    if type(db_path) is not str or not db_path:
        raise TypeError("Coverage transition DB path must be an exact string")
    raw = Path(db_path)
    if raw.is_symlink():
        raise CoverageTransitionError("Coverage transition DB cannot be a symlink")
    resolved = raw.resolve(strict=True)
    if not resolved.is_file():
        raise CoverageTransitionError("Coverage transition DB must be a file")
    return resolved


def _assert_db_path_identity(path: Path, identity: _DatabaseIdentity) -> None:
    """Fail closed if the pathname no longer names the opened DB inode."""
    try:
        if path.is_symlink():
            raise CoverageTransitionError(
                "Coverage transition DB path became a symlink"
            )
        current = path.stat()
    except OSError as exc:
        raise CoverageTransitionError(
            "Coverage transition DB path identity is unavailable"
        ) from exc
    if (
        not stat.S_ISREG(current.st_mode)
        or (current.st_dev, current.st_ino)
        != (identity.device, identity.inode)
    ):
        raise CoverageTransitionError(
            "Coverage transition DB path no longer names the opened database"
        )


def _open_db(
    db_path: str,
    *,
    readonly: bool,
) -> tuple[sqlite3.Connection, Path, _DatabaseIdentity]:
    path = _resolve_db_path(db_path)
    before = path.stat()
    mode = "ro" if readonly else "rw"
    uri = "file:" + quote(str(path)) + f"?mode={mode}"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None)
    conn.row_factory = sqlite3.Row
    main = next(
        (
            Path(str(row[2])).resolve()
            for row in conn.execute("PRAGMA database_list")
            if str(row[1]) == "main"
        ),
        None,
    )
    after = path.stat()
    if (
        main != path
        or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
    ):
        conn.close()
        raise CoverageTransitionError(
            "Coverage transition DB identity changed while opening"
        )
    identity = _DatabaseIdentity(device=after.st_dev, inode=after.st_ino)
    return conn, path, identity


@dataclass(frozen=True, slots=True)
class CoverageTransitionPublicKeyRegistry:
    """Pinned public-key-only verifier; no private material or signer API."""

    _keys: Mapping[str, Ed25519PublicKey]

    def __post_init__(self) -> None:
        normalized: dict[str, Ed25519PublicKey] = {}
        for raw_id, key in self._keys.items():
            if type(raw_id) is not str or not raw_id or raw_id in normalized:
                raise CoverageTransitionError(
                    "Coverage transition key ids must be unique strings"
                )
            if not isinstance(key, Ed25519PublicKey):
                raise CoverageTransitionError(
                    "Coverage transition registry requires Ed25519 keys"
                )
            normalized[raw_id] = key
        if len(normalized) > 1:
            raise CoverageTransitionError(
                "Coverage transition registry permits one active key"
            )
        object.__setattr__(self, "_keys", MappingProxyType(normalized))

    @property
    def provisioned(self) -> bool:
        return bool(self._keys)

    @classmethod
    def from_document(
        cls, document: Mapping[str, Any]
    ) -> "CoverageTransitionPublicKeyRegistry":
        frozen = _freeze_json(document, field="registry")
        if set(frozen) != {"schema_version", "purpose", "keys"}:
            raise CoverageTransitionError(
                "Coverage transition registry shape is invalid"
            )
        if (
            frozen["schema_version"] != 1
            or frozen["purpose"]
            != "coverage_complete_transition_verification"
            or type(frozen["keys"]) is not list
        ):
            raise CoverageTransitionError(
                "Coverage transition registry identity is invalid"
            )
        active: dict[str, Ed25519PublicKey] = {}
        seen: set[str] = set()
        for row in frozen["keys"]:
            if type(row) is not dict or set(row) != {
                "key_id",
                "algorithm",
                "status",
                "public_key_b64",
            }:
                raise CoverageTransitionError(
                    "Coverage transition registry row is invalid"
                )
            key_id = row["key_id"]
            if type(key_id) is not str or not key_id or key_id in seen:
                raise CoverageTransitionError(
                    "Coverage transition key ids must be unique strings"
                )
            seen.add(key_id)
            if (
                row["algorithm"] != COVERAGE_TRANSITION_ALGORITHM
                or row["status"] not in {"active", "revoked"}
            ):
                raise CoverageTransitionError(
                    "Coverage transition registry algorithm/status is invalid"
                )
            if type(row["public_key_b64"]) is not str:
                raise CoverageTransitionError(
                    "Coverage transition public key encoding is invalid"
                )
            try:
                public = Ed25519PublicKey.from_public_bytes(
                    base64.b64decode(row["public_key_b64"], validate=True)
                )
            except (TypeError, ValueError) as exc:
                raise CoverageTransitionError(
                    "Coverage transition public key is invalid"
                ) from exc
            if row["status"] == "active":
                active[key_id] = public
        return cls(active)

    @classmethod
    def load_pinned(cls) -> "CoverageTransitionPublicKeyRegistry":
        try:
            document = json.loads(_PINNED_REGISTRY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CoverageTransitionError(
                "Coverage transition pinned registry cannot be loaded"
            ) from exc
        if type(document) is not dict or _digest(document) != _PINNED_REGISTRY_DIGEST:
            raise CoverageTransitionError(
                "Coverage transition pinned registry digest mismatch"
            )
        return cls.from_document(document)

    def verify(self, *, key_id: str, message: Mapping[str, Any], signature: str) -> bool:
        key = self._keys.get(key_id)
        if key is None or type(signature) is not str or not signature.startswith(
            "ed25519:"
        ):
            return False
        try:
            raw_signature = base64.b64decode(signature[8:], validate=True)
            key.verify(raw_signature, _canonical_bytes(dict(message)))
        except (TypeError, ValueError, InvalidSignature):
            return False
        return True


def coverage_transition_availability() -> Mapping[str, str]:
    """Return the stable production authority state without exposing keys."""
    registry = CoverageTransitionPublicKeyRegistry.load_pinned()
    if not registry.provisioned:
        return MappingProxyType(
            {
                "status": "PENDING",
                "reason_code": COVERAGE_TRANSITION_PENDING_REASON,
            }
        )
    return MappingProxyType({"status": "AVAILABLE", "reason_code": ""})


def _assert_current_policy_row(row: Mapping[str, Any]) -> None:
    text_fields = {
        "dataset",
        "status",
        "policy_version",
        "collection_scope",
        "history_target_start",
        "history_target_end_rule",
        "coverage_mode",
        "expected_frequency",
        "universe_rule",
        "governance_tier",
        "evaluated_at",
        "detail_json",
    }
    if any(type(row[field]) is not str for field in text_fields):
        raise CoverageTransitionError(
            "active Coverage row contains a noncanonical text value"
        )
    if any(
        type(row[field]) is not int or row[field] not in {0, 1}
        for field in (
            "raw_retention_required",
            "structured_reconciliation_required",
        )
    ):
        raise CoverageTransitionError(
            "active Coverage row contains a noncanonical boolean value"
        )
    if type(row["row_count"]) is not int or row["row_count"] < 0:
        raise CoverageTransitionError(
            "active Coverage row contains an invalid row count"
        )
    if row["source_run_id"] is not None and (
        type(row["source_run_id"]) is not int or row["source_run_id"] <= 0
    ):
        raise CoverageTransitionError(
            "active Coverage row contains an invalid source run id"
        )
    if any(
        row[field] is not None and type(row[field]) is not str
        for field in ("observed_start", "observed_end")
    ):
        raise CoverageTransitionError(
            "active Coverage row contains a noncanonical observed window"
        )
    dataset = row["dataset"]
    binding = coverage_policy_binding(dataset)
    contract = coverage_contract_for(dataset)
    if row["policy_version"] != binding["policy_version"]:
        raise CoverageTransitionError(
            f"active Coverage row is not current policy: {dataset}"
        )
    expected = {
        "collection_scope": contract.collection_scope,
        "history_target_start": contract.history_target_start,
        "history_target_end_rule": contract.history_target_end_rule,
        "coverage_mode": contract.coverage_mode,
        "expected_frequency": contract.expected_frequency,
        "universe_rule": contract.universe_rule,
        "raw_retention_required": int(contract.raw_retention_required),
        "structured_reconciliation_required": int(
            contract.structured_reconciliation_required
        ),
        "governance_tier": contract.governance_tier,
    }
    if any(row[field] != value for field, value in expected.items()):
        raise CoverageTransitionError(
            f"active Coverage row differs from current policy: {dataset}"
        )
    if row["status"] not in COVERAGE_STATUSES or row["status"] == "COMPLETE":
        raise CoverageTransitionError(
            f"first-COMPLETE transition requires non-COMPLETE active state: {dataset}"
        )
    try:
        detail = json.loads(str(row["detail_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CoverageTransitionError(
            f"active Coverage detail is malformed: {dataset}"
        ) from exc
    if type(detail) is not dict:
        raise CoverageTransitionError(
            f"active Coverage detail is not an object: {dataset}"
        )


def _read_active_rows(
    conn: sqlite3.Connection, datasets: tuple[str, ...]
) -> tuple[dict[str, Any], ...]:
    placeholders = ",".join("?" for _ in datasets)
    cursor = conn.execute(
        "SELECT " + ",".join(_DATASET_COVERAGE_COLUMNS)
        + f" FROM dataset_coverage WHERE dataset IN ({placeholders}) "
        + "ORDER BY dataset",
        datasets,
    )
    rows = tuple(dict(row) for row in cursor.fetchall())
    if tuple(row["dataset"] for row in rows) != datasets:
        raise CoverageTransitionError(
            "Coverage transition active dataset membership is incomplete"
        )
    for row in rows:
        _assert_current_policy_row(row)
    return rows


def _require_computed_complete_candidate(
    row: Mapping[str, Any],
    *,
    publication_cutoff: str,
    inventory_count: int,
) -> None:
    """Require the fail-closed generic evaluator's exact pre-transition state."""
    detail = json.loads(row["detail_json"])
    coverage = detail.get("coverage_v2")
    gate = coverage.get("aggregate_complete_gate") if type(coverage) is dict else None
    if type(gate) is not dict or any(
        gate.get(field) != expected
        for field, expected in {
            "mode": "generic_refresh_c10_transition_authority_unavailable",
            "computed_status": "COMPLETE",
            "persisted_status": "PARTIAL",
            "blocker": "transition_authority_required",
            "current_policy_version": row["policy_version"],
            "inventory_target_end": publication_cutoff,
        }.items()
    ):
        raise CoverageTransitionError(
            f"Coverage transition active state is not a computed COMPLETE "
            f"candidate: {row['dataset']}"
        )
    if row["status"] != "PARTIAL":
        raise CoverageTransitionError(
            f"Coverage transition candidate was not persisted PARTIAL: "
            f"{row['dataset']}"
        )
    required_segments = coverage.get("required_segments")
    status_counts = coverage.get("status_counts")
    if (
        type(required_segments) is not int
        or required_segments != inventory_count
        or type(status_counts) is not dict
        or set(status_counts) != {"COMPLETE"}
        or type(status_counts["COMPLETE"]) is not int
        or status_counts["COMPLETE"] != inventory_count
        or detail.get("global_failures") != []
    ):
        raise CoverageTransitionError(
            f"Coverage transition computed target is not exact COMPLETE: "
            f"{row['dataset']}"
        )
    if not str(row["dataset"]).startswith("jsda_"):
        checks = detail.get("checks")
        if type(checks) is not list or not checks or any(
            type(check) is not dict for check in checks
        ):
            raise CoverageTransitionError(
                f"Coverage transition validation evidence is missing: "
                f"{row['dataset']}"
            )
        validation = next(
            (check for check in checks if check.get("check_id") == "C2"),
            None,
        )
        if (
            validation is None
            or validation.get("status") != "pass"
            or type(validation.get("metrics")) is not dict
            or validation["metrics"].get("source") != "ingestion_validation"
            or validation["metrics"].get("validation_status") != "pass"
            or any(check.get("status") == "fail" for check in checks)
        ):
            raise CoverageTransitionError(
                f"Coverage transition validation is not PASS: {row['dataset']}"
            )


def _publication_binding(
    conn: sqlite3.Connection,
    *,
    db_path: Path,
    build_id: str,
    policy_version: str,
) -> tuple[str, dict[str, Any]]:
    try:
        cutoff = validation_coverage_cutoff_for_build(
            conn,
            db_path,
            build_id,
        )
    except CoveragePublicationCutoffError as exc:
        raise CoverageTransitionError(
            "Coverage transition build/cutoff authority is unavailable"
        ) from exc
    cursor = conn.execute(
        "SELECT build_id,state,staging_path,coverage_policy_version,created_at "
        "FROM snapshot_publications WHERE build_id=?",
        (build_id,),
    )
    rows = cursor.fetchall()
    if len(rows) != 1:
        raise CoverageTransitionError(
            "Coverage transition requires one active publication"
        )
    row = dict(rows[0])
    if any(
        type(row[field]) is not str or not row[field]
        for field in (
            "build_id",
            "state",
            "staging_path",
            "coverage_policy_version",
            "created_at",
        )
    ):
        raise CoverageTransitionError(
            "Coverage transition publication contains noncanonical values"
        )
    if row["coverage_policy_version"] != policy_version:
        raise CoverageTransitionError(
            "Coverage transition build policy differs from current policy set"
        )
    binding = {
        "build_id": row["build_id"],
        "state": row["state"],
        "staging_path_digest": _digest({"path": str(db_path)}),
        "coverage_policy_version": row["coverage_policy_version"],
        "created_at": row["created_at"],
        "publication_cutoff": cutoff,
    }
    return cutoff, binding


def _derive_transition_body(
    conn: sqlite3.Connection,
    db_path: Path,
    *,
    build_id: str,
    datasets: tuple[str, ...],
    issued_at: str,
    expires_at: str,
) -> dict[str, Any]:
    if type(build_id) is not str or not build_id:
        raise TypeError("Coverage transition build id must be an exact string")
    issued = _parse_utc_z(issued_at, field="issued_at")
    expires = _parse_utc_z(expires_at, field="expires_at")
    if expires <= issued or (expires - issued).total_seconds() > MAX_AUTHORIZATION_SECONDS:
        raise CoverageTransitionError(
            "Coverage transition authorization lifetime is invalid"
        )

    policy_set_raw = coverage_policy_set_binding(list(datasets))
    policy_set = {
        "policy_version": policy_set_raw["policy_version"],
        "policy_digest": policy_set_raw["policy_digest"],
        "datasets": [dict(item) for item in policy_set_raw["datasets"]],
    }
    active_rows = _read_active_rows(conn, datasets)
    publication_cutoff, publication = _publication_binding(
        conn,
        db_path=db_path,
        build_id=build_id,
        policy_version=str(policy_set["policy_version"]),
    )
    try:
        verification = verify_exact_coverage_complete(
            conn,
            datasets,
            target_end=publication_cutoff,
        )
    except CoverageInventoryAuthorityUnavailable as exc:
        raise CoverageTransitionError(
            "Coverage transition exact inventory authority is unavailable"
        ) from exc
    if not verification.inventory.exact:
        raise CoverageTransitionError(
            "Coverage transition target inventory is not exact"
        )
    if not verification.complete_eligible:
        raise CoverageTransitionError(
            "Coverage transition selected signed receipts are incomplete"
        )

    inventory_rows = sorted(
        (item.to_dict() for item in verification.inventory.expected_identities),
        key=_canonical_bytes,
    )
    receipt_rows = sorted(
        (closure.to_proof_dict() for closure in verification.closures),
        key=_canonical_bytes,
    )
    inventory_counts = {
        dataset: len(verification.inventory.segments_for(dataset))
        for dataset in datasets
    }
    for row in active_rows:
        _require_computed_complete_candidate(
            row,
            publication_cutoff=publication_cutoff,
            inventory_count=inventory_counts[row["dataset"]],
        )
    from_state = [
        {
            "dataset": row["dataset"],
            "status": row["status"],
            "policy_version": row["policy_version"],
            "policy_digest": coverage_policy_binding(row["dataset"])[
                "policy_digest"
            ],
            "row_digest": _digest(row),
        }
        for row in active_rows
    ]
    inventory_set_digest = _digest({"inventory": inventory_rows})
    receipt_set_digest = _digest({"receipts": receipt_rows})
    target_state = [
        {
            "dataset": row["dataset"],
            "status": "COMPLETE",
            "policy_version": row["policy_version"],
            "policy_digest": coverage_policy_binding(row["dataset"])[
                "policy_digest"
            ],
            "inventory_set_digest": inventory_set_digest,
            "receipt_set_digest": receipt_set_digest,
        }
        for row in active_rows
    ]
    return {
        "build_id": build_id,
        "publication_cutoff": publication_cutoff,
        "datasets": list(datasets),
        "dataset_set_digest": _digest({"datasets": list(datasets)}),
        "from_state": from_state,
        "from_state_digest": _digest(
            {"publication": publication, "rows": [dict(row) for row in active_rows]}
        ),
        "target_state": target_state,
        "target_state_digest": _digest({"target": target_state}),
        "coverage_policy_set": policy_set,
        "coverage_policy_set_digest": str(policy_set["policy_digest"]),
        "inventory_set_digest": inventory_set_digest,
        "inventory_count": len(inventory_rows),
        "receipt_set_digest": receipt_set_digest,
        "receipt_count": len(receipt_rows),
        "issued_at": issued_at,
        "expires_at": expires_at,
    }


def _unsigned_request(body: Mapping[str, Any]) -> dict[str, Any]:
    transition_id = _digest(
        {
            "format": COVERAGE_TRANSITION_FORMAT,
            "authority_domain": COVERAGE_TRANSITION_DOMAIN,
            "body": dict(body),
        }
    )
    return {
        "format": COVERAGE_TRANSITION_FORMAT,
        "authority_domain": COVERAGE_TRANSITION_DOMAIN,
        "transition_id": transition_id,
        "body": dict(body),
    }


def build_coverage_transition_request(
    db_path: str,
    *,
    build_id: str,
    datasets: Sequence[str],
    issued_at: str,
    expires_at: str,
) -> Mapping[str, Any]:
    """Build an unsigned request; this is evidence input, never authority."""
    selected = _normalize_datasets(datasets)
    conn, path, identity = _open_db(db_path, readonly=True)
    try:
        conn.execute("BEGIN")
        request = build_coverage_transition_request_from_owned_connection(
            conn,
            governed_db_path=path,
            build_id=build_id,
            datasets=selected,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        _assert_db_path_identity(path, identity)
        return request
    finally:
        if conn.in_transaction:
            conn.rollback()
        conn.close()


def build_coverage_transition_request_from_owned_connection(
    conn: sqlite3.Connection,
    *,
    governed_db_path: str | Path,
    build_id: str,
    datasets: Sequence[str],
    issued_at: str,
    expires_at: str,
) -> Mapping[str, Any]:
    """Derive unsigned evidence from an already-frozen descriptor transaction."""
    if type(conn) is not sqlite3.Connection or not conn.in_transaction:
        raise CoverageTransitionError(
            "Coverage transition requires an owned frozen read transaction"
        )
    path = Path(governed_db_path)
    if not path.is_absolute():
        raise CoverageTransitionError("Coverage governed database path is not absolute")
    selected = _normalize_datasets(datasets)
    previous_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        body = _derive_transition_body(
            conn,
            path,
            build_id=build_id,
            datasets=selected,
            issued_at=issued_at,
            expires_at=expires_at,
        )
    finally:
        conn.row_factory = previous_factory
    return MappingProxyType(_unsigned_request(body))


def _validate_signed_document(document: Mapping[str, Any]) -> dict[str, Any]:
    frozen = _freeze_json(document)
    if set(frozen) != _SIGNED_DOCUMENT_FIELDS:
        raise CoverageTransitionError(
            "Coverage transition signed document shape is invalid"
        )
    if (
        frozen["format"] != COVERAGE_TRANSITION_FORMAT
        or frozen["authority_domain"] != COVERAGE_TRANSITION_DOMAIN
        or frozen["issuer"] != COVERAGE_TRANSITION_ISSUER
        or frozen["algorithm"] != COVERAGE_TRANSITION_ALGORITHM
        or type(frozen["issuer_key_id"]) is not str
        or not frozen["issuer_key_id"]
        or type(frozen["body"]) is not dict
        or set(frozen["body"]) != _BODY_FIELDS
    ):
        raise CoverageTransitionError(
            "Coverage transition signed document identity is invalid"
        )
    _require_digest(frozen["transition_id"], field="transition_id")
    body = frozen["body"]
    if type(body["build_id"]) is not str or not body["build_id"]:
        raise CoverageTransitionError("Coverage transition build id is invalid")
    _normalize_datasets(body["datasets"])
    for field in (
        "dataset_set_digest",
        "from_state_digest",
        "target_state_digest",
        "coverage_policy_set_digest",
        "inventory_set_digest",
        "receipt_set_digest",
    ):
        _require_digest(body[field], field=field)
    if (
        type(body["inventory_count"]) is not int
        or body["inventory_count"] <= 0
        or type(body["receipt_count"]) is not int
        or body["receipt_count"] <= 0
    ):
        raise CoverageTransitionError(
            "Coverage transition evidence counts must be positive integers"
        )
    _parse_utc_z(body["issued_at"], field="issued_at")
    _parse_utc_z(body["expires_at"], field="expires_at")
    expected_unsigned = _unsigned_request(body)
    if any(frozen[field] != expected_unsigned[field] for field in expected_unsigned):
        raise CoverageTransitionError(
            "Coverage transition id does not address its exact body"
        )
    return frozen


def _signature_message(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: document[field]
        for field in (
            "format",
            "authority_domain",
            "issuer",
            "issuer_key_id",
            "algorithm",
            "transition_id",
            "body",
        )
    }


def _pending() -> NoReturn:
    raise CoverageTransitionAuthorityPending()


def _assert_authority_schema(
    conn: sqlite3.Connection,
    *,
    require_clean_coverage_triggers: bool,
) -> None:
    """Require the exact v12 authority store and its owned trigger surface."""
    migration = conn.execute(
        "SELECT version,name FROM schema_migrations WHERE version=12"
    ).fetchall()
    if [tuple(row) for row in migration] != [
        (12, "phase631_coverage_complete_transition_tombstones")
    ]:
        raise CoverageTransitionError(
            "Coverage transition migration v12 identity is invalid"
        )

    coverage_columns = tuple(
        str(row[1])
        for row in conn.execute("PRAGMA table_info(dataset_coverage)")
    )
    tombstone_info = tuple(
        tuple(row)
        for row in conn.execute(
            "PRAGMA table_info(coverage_complete_transition_tombstones)"
        )
    )
    if coverage_columns != _DATASET_COVERAGE_COLUMNS:
        raise CoverageTransitionError(
            "Coverage transition aggregate schema is not authority-owned"
        )
    if (
        tuple(str(row[1]) for row in tombstone_info) != _TOMBSTONE_COLUMNS
        or any(str(row[2]).upper() != "TEXT" for row in tombstone_info)
        or tuple(int(row[5]) for row in tombstone_info) != (1,) + (0,) * 13
        or tuple(int(row[3]) for row in tombstone_info) != (0,) + (1,) * 13
        or any(row[4] is not None for row in tombstone_info)
    ):
        raise CoverageTransitionError(
            "Coverage transition tombstone schema is not canonical"
        )

    tombstone_triggers = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='trigger' AND tbl_name="
            "'coverage_complete_transition_tombstones'"
        )
    }
    if tombstone_triggers != _TOMBSTONE_TRIGGER_NAMES:
        raise CoverageTransitionError(
            "Coverage transition tombstone trigger ownership is invalid"
        )
    if require_clean_coverage_triggers:
        coverage_triggers = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='trigger' AND tbl_name='dataset_coverage'"
        ).fetchall()
        if coverage_triggers:
            raise CoverageTransitionError(
                "Coverage transition aggregate has unowned triggers"
            )


def _expected_tombstone(
    document: Mapping[str, Any],
    *,
    consumed_at: str,
) -> dict[str, Any]:
    body = document["body"]
    return {
        "transition_id": document["transition_id"],
        "format": document["format"],
        "authority_domain": document["authority_domain"],
        "issuer_key_id": document["issuer_key_id"],
        "build_id": body["build_id"],
        "publication_cutoff": body["publication_cutoff"],
        "dataset_set_digest": body["dataset_set_digest"],
        "from_state_digest": body["from_state_digest"],
        "target_state_digest": body["target_state_digest"],
        "coverage_policy_set_digest": body["coverage_policy_set_digest"],
        "inventory_set_digest": body["inventory_set_digest"],
        "receipt_set_digest": body["receipt_set_digest"],
        "signed_evidence_json": _canonical_json(document),
        "consumed_at": consumed_at,
    }


def _expected_target_row(
    row: Mapping[str, Any],
    *,
    document: Mapping[str, Any],
    consumed_at: str,
) -> dict[str, Any]:
    body = document["body"]
    detail = json.loads(row["detail_json"])
    coverage = detail.get("coverage_v2")
    if type(coverage) is not dict:
        raise CoverageTransitionError(
            "Coverage transition candidate evidence disappeared before CAS"
        )
    coverage = dict(coverage)
    candidate_gate = coverage.get("aggregate_complete_gate")
    if type(candidate_gate) is not dict:  # defensive; reverified before CAS
        raise CoverageTransitionError(
            "Coverage transition candidate gate disappeared before CAS"
        )
    coverage["complete_transition"] = {
        "format": COVERAGE_TRANSITION_FORMAT,
        "transition_id": document["transition_id"],
        "build_id": body["build_id"],
        "publication_cutoff": body["publication_cutoff"],
        "dataset_set_digest": body["dataset_set_digest"],
        "coverage_policy_set_digest": body["coverage_policy_set_digest"],
        "inventory_set_digest": body["inventory_set_digest"],
        "receipt_set_digest": body["receipt_set_digest"],
        "candidate_gate_digest": _digest(candidate_gate),
    }
    coverage["aggregate_complete_gate"] = {
        **candidate_gate,
        "mode": "signed_coverage_transition_authority",
        "persisted_status": "COMPLETE",
        "inventory_status": "EXACT",
        "selected_receipt_status": "VERIFIED",
        "blocker": None,
        "transition_id": document["transition_id"],
    }
    detail["coverage_v2"] = coverage
    expected = dict(row)
    expected.update(
        {
            "status": "COMPLETE",
            "evaluated_at": consumed_at,
            "detail_json": _canonical_json(detail),
        }
    )
    return expected


def _apply_cas(
    conn: sqlite3.Connection,
    *,
    document: Mapping[str, Any],
    active_rows: tuple[dict[str, Any], ...],
    consumed_at: str,
) -> tuple[dict[str, Any], ...]:
    expected_tombstone = _expected_tombstone(
        document,
        consumed_at=consumed_at,
    )
    conn.execute(
        """
        INSERT INTO coverage_complete_transition_tombstones (
            transition_id,format,authority_domain,issuer_key_id,build_id,
            publication_cutoff,dataset_set_digest,from_state_digest,
            target_state_digest,coverage_policy_set_digest,
            inventory_set_digest,receipt_set_digest,signed_evidence_json,
            consumed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        tuple(expected_tombstone[column] for column in _TOMBSTONE_COLUMNS),
    )
    where = " AND ".join(f"{column} IS ?" for column in _DATASET_COVERAGE_COLUMNS)
    expected_rows: list[dict[str, Any]] = []
    for row in active_rows:
        expected = _expected_target_row(
            row,
            document=document,
            consumed_at=consumed_at,
        )
        cursor = conn.execute(
            "UPDATE dataset_coverage SET status='COMPLETE',evaluated_at=?,"
            "detail_json=? WHERE " + where,
            (
                expected["evaluated_at"],
                expected["detail_json"],
                *(row[column] for column in _DATASET_COVERAGE_COLUMNS),
            ),
        )
        if cursor.rowcount != 1:
            raise CoverageTransitionError(
                "Coverage transition active-state CAS failed"
            )
        expected_rows.append(expected)
    return tuple(expected_rows)


def _assert_tombstone_immutable(
    conn: sqlite3.Connection,
    *,
    transition_id: str,
) -> None:
    """Behaviorally prove both v12 mutation barriers inside a savepoint."""
    probes = (
        (
            "UPDATE coverage_complete_transition_tombstones "
            "SET consumed_at=consumed_at WHERE transition_id=?",
            "update",
        ),
        (
            "DELETE FROM coverage_complete_transition_tombstones "
            "WHERE transition_id=?",
            "delete",
        ),
    )
    for sql, operation in probes:
        savepoint = f"coverage_transition_{operation}_probe"
        conn.execute(f"SAVEPOINT {savepoint}")
        protected = False
        try:
            conn.execute(sql, (transition_id,))
        except sqlite3.IntegrityError:
            protected = True
        finally:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
        if not protected:
            raise CoverageTransitionError(
                f"Coverage transition tombstone {operation} barrier is absent"
            )


def _assert_post_apply_state(
    conn: sqlite3.Connection,
    *,
    db_path: Path,
    document: Mapping[str, Any],
    active_rows: tuple[dict[str, Any], ...],
    expected_rows: tuple[dict[str, Any], ...],
    consumed_at: str,
) -> None:
    """Independently reread every committed-intent fact before commit."""
    body = document["body"]
    datasets = _normalize_datasets(body["datasets"])
    placeholders = ",".join("?" for _ in datasets)
    observed_rows = tuple(
        dict(row)
        for row in conn.execute(
            "SELECT " + ",".join(_DATASET_COVERAGE_COLUMNS)
            + f" FROM dataset_coverage WHERE dataset IN ({placeholders}) "
            + "ORDER BY dataset",
            datasets,
        ).fetchall()
    )
    if observed_rows != expected_rows:
        raise CoverageTransitionError(
            "Coverage transition target rows failed post-CAS verification"
        )

    expected_tombstone = _expected_tombstone(
        document,
        consumed_at=consumed_at,
    )
    tombstones = tuple(
        dict(row)
        for row in conn.execute(
            "SELECT " + ",".join(_TOMBSTONE_COLUMNS)
            + " FROM coverage_complete_transition_tombstones "
            + "WHERE transition_id=? OR (build_id=? AND dataset_set_digest=?)",
            (
                document["transition_id"],
                body["build_id"],
                body["dataset_set_digest"],
            ),
        ).fetchall()
    )
    if tombstones != (expected_tombstone,):
        raise CoverageTransitionError(
            "Coverage transition tombstone failed exact post-CAS verification"
        )

    policy_set_raw = coverage_policy_set_binding(list(datasets))
    policy_set = {
        "policy_version": policy_set_raw["policy_version"],
        "policy_digest": policy_set_raw["policy_digest"],
        "datasets": [dict(item) for item in policy_set_raw["datasets"]],
    }
    if (
        policy_set != body["coverage_policy_set"]
        or policy_set["policy_digest"] != body["coverage_policy_set_digest"]
    ):
        raise CoverageTransitionError(
            "Coverage transition policy changed during CAS"
        )

    publication_cutoff, publication = _publication_binding(
        conn,
        db_path=db_path,
        build_id=body["build_id"],
        policy_version=str(policy_set["policy_version"]),
    )
    if (
        publication_cutoff != body["publication_cutoff"]
        or _digest(
            {
                "publication": publication,
                "rows": [dict(row) for row in active_rows],
            }
        )
        != body["from_state_digest"]
    ):
        raise CoverageTransitionError(
            "Coverage transition publication binding changed during CAS"
        )

    try:
        verification = verify_exact_coverage_complete(
            conn,
            datasets,
            target_end=publication_cutoff,
        )
    except CoverageInventoryAuthorityUnavailable as exc:
        raise CoverageTransitionError(
            "Coverage transition exact inventory authority disappeared during CAS"
        ) from exc
    if not verification.inventory.exact or not verification.complete_eligible:
        raise CoverageTransitionError(
            "Coverage transition exact evidence changed during CAS"
        )
    inventory_rows = sorted(
        (item.to_dict() for item in verification.inventory.expected_identities),
        key=_canonical_bytes,
    )
    receipt_rows = sorted(
        (closure.to_proof_dict() for closure in verification.closures),
        key=_canonical_bytes,
    )
    if any(
        observed != body[field]
        for field, observed in {
            "inventory_set_digest": _digest({"inventory": inventory_rows}),
            "inventory_count": len(inventory_rows),
            "receipt_set_digest": _digest({"receipts": receipt_rows}),
            "receipt_count": len(receipt_rows),
        }.items()
    ):
        raise CoverageTransitionError(
            "Coverage transition evidence digests changed during CAS"
        )

    _assert_authority_schema(
        conn,
        require_clean_coverage_triggers=True,
    )
    _assert_tombstone_immutable(
        conn,
        transition_id=document["transition_id"],
    )


def apply_signed_coverage_transition(
    db_path: str,
    document: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Verify live state and atomically consume one signed transition.

    The function owns its connection and transaction.  It accepts no caller
    verifier, signing key, clock, cutoff, counts, digests, or target rows.
    """
    registry = CoverageTransitionPublicKeyRegistry.load_pinned()
    if not registry.provisioned:
        _pending()
    frozen = _validate_signed_document(document)
    message = _signature_message(frozen)
    if not registry.verify(
        key_id=frozen["issuer_key_id"],
        message=message,
        signature=frozen["signature"],
    ):
        raise CoverageTransitionError("Coverage transition signature is invalid")

    body = frozen["body"]
    issued = _parse_utc_z(body["issued_at"], field="issued_at")
    expires = _parse_utc_z(body["expires_at"], field="expires_at")
    if (
        expires <= issued
        or (expires - issued).total_seconds() > MAX_AUTHORIZATION_SECONDS
    ):
        raise CoverageTransitionError(
            "Coverage transition authorization is not current"
        )
    initial_now = _observe_authorization_time(
        issued=issued,
        expires=expires,
        previous=None,
        stage="initial verification",
        window_error="Coverage transition authorization is not current",
    )

    conn, path, identity = _open_db(db_path, readonly=False)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _assert_authority_schema(
            conn,
            require_clean_coverage_triggers=False,
        )
        try:
            seen = conn.execute(
                "SELECT transition_id FROM "
                "coverage_complete_transition_tombstones "
                "WHERE transition_id=? OR (build_id=? AND dataset_set_digest=?)",
                (
                    frozen["transition_id"],
                    body["build_id"],
                    body["dataset_set_digest"],
                ),
            ).fetchone()
        except sqlite3.Error as exc:
            raise CoverageTransitionError(
                "Coverage transition migration v12 is unavailable"
            ) from exc
        if seen is not None:
            raise CoverageTransitionAlreadyConsumed(
                "Coverage transition evidence was already consumed"
            )
        datasets = _normalize_datasets(body["datasets"])
        expected_body = _derive_transition_body(
            conn,
            path,
            build_id=body["build_id"],
            datasets=datasets,
            issued_at=body["issued_at"],
            expires_at=body["expires_at"],
        )
        if body != expected_body:
            raise CoverageTransitionError(
                "Coverage transition does not bind the exact live active/target state"
            )
        active_rows = _read_active_rows(conn, datasets)
        final_now = _observe_authorization_time(
            issued=issued,
            expires=expires,
            previous=initial_now,
            stage="state verification",
            window_error=(
                "Coverage transition authorization expired during verification"
            ),
        )
        consumed_at = final_now.isoformat(timespec="seconds")
        _assert_db_path_identity(path, identity)
        expected_rows = _apply_cas(
            conn,
            document=frozen,
            active_rows=active_rows,
            consumed_at=consumed_at,
        )
        _assert_post_apply_state(
            conn,
            db_path=path,
            document=frozen,
            active_rows=active_rows,
            expected_rows=expected_rows,
            consumed_at=consumed_at,
        )
        _assert_db_path_identity(path, identity)
        _observe_authorization_time(
            issued=issued,
            expires=expires,
            previous=final_now,
            stage="commit",
            window_error="Coverage transition authorization expired before commit",
        )
        conn.commit()
        return MappingProxyType(
            {
                "status": "COMPLETE",
                "transition_id": frozen["transition_id"],
                "build_id": body["build_id"],
                "publication_cutoff": body["publication_cutoff"],
                "dataset_set_digest": body["dataset_set_digest"],
            }
        )
    except BaseException:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


__all__ = [
    "COVERAGE_TRANSITION_ALGORITHM",
    "COVERAGE_TRANSITION_DOMAIN",
    "COVERAGE_TRANSITION_FORMAT",
    "COVERAGE_TRANSITION_ISSUER",
    "COVERAGE_TRANSITION_PENDING_REASON",
    "CoverageTransitionAlreadyConsumed",
    "CoverageTransitionAuthorityPending",
    "CoverageTransitionError",
    "CoverageTransitionPublicKeyRegistry",
    "MAX_AUTHORIZATION_SECONDS",
    "apply_signed_coverage_transition",
    "build_coverage_transition_request",
    "build_coverage_transition_request_from_owned_connection",
    "coverage_transition_availability",
]
