#!/usr/bin/env python3
"""Concrete C4/C10/R5 handlers for the isolated local authority runtime.

The classes here are authority-process code.  They accept only the narrow
payload selected by their exact Unix method ACL, derive governed values from
configured or descriptor-bound evidence, sign with protected key custody, and
return evidence consumable by the existing public-key-only product boundaries.
The checked-in key registries remain PENDING, so these handlers cannot produce
a usable positive capability in the current checkout.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import sqlite3
import stat
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from ops import d1_sync_signing, projection_signing, trust_domain
from paper_runtime import begin_snapshot_sync, readiness_attestation
from storage import coverage_transition

from scripts import authority_protocol_runtime, export_ops_projection, sync_d1_to_sqlite
from scripts.local_ready_registry import (
    LocalReadyRegistryError,
    derive_ready_authority_resource_digest,
    load_scoped_ready_public_keys,
    ready_authority_instance_id,
)
from scripts.local_authority_service import (
    REQUEST_FORMAT,
    AuthorityRequestContext,
    FileEd25519KeyCustody,
    LocalAuthorityError,
    LocalAuthorityPending,
    call_unix_authority,
    decode_strict_json,
    sha256_digest,
)

_READY_TTL_SECONDS = 60 * 60
OWNED_MIRROR_EVIDENCE_FORMAT = "d1-owned-frozen-mirror/v1"
_OWNED_MIRROR_FIELDS = {
    "format",
    "environment",
    "purpose",
    "governed_db_path",
    "descriptor",
    "sync_identity",
    "sync_identity_digest",
}
_DESCRIPTOR_FIELDS = {
    "owner_uid",
    "device",
    "inode",
    "size",
    "mtime_ns",
    "mode",
    "content_digest",
}
_D1_RECONCILED_FACT_FIELDS = {
    "sync_kind",
    "export_digest",
    "artifact_format",
    "source_change_seq",
    "applied_change_seq",
    "source_content_digest",
    "local_content_digest",
    "source_schema_digest",
    "schema_digest",
    "table_counts",
    "prior_audit_digest",
    "exported_at",
}


def _require_payload_fields(
    payload: Mapping[str, Any], *, fields: set[str], operation: str
) -> dict[str, Any]:
    if type(payload) not in {dict, MappingProxyType}:
        raise LocalAuthorityError(f"{operation} payload must be an object")
    frozen = dict(payload)
    if set(frozen) != fields:
        raise LocalAuthorityError(f"{operation} payload fields are not closed")
    return frozen


def _decode_standard_base64(value: object, *, field: str) -> bytes:
    if type(value) is not str or not value:
        raise LocalAuthorityError(f"{field} must be base64 text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (TypeError, ValueError) as exc:
        raise LocalAuthorityError(f"{field} is invalid base64") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise LocalAuthorityError(f"{field} is not canonical base64")
    return decoded


def _custody_public_key(custody: FileEd25519KeyCustody) -> Ed25519PublicKey:
    try:
        return Ed25519PublicKey.from_public_bytes(
            base64.b64decode(custody.public_key_base64(), validate=True)
        )
    except (TypeError, ValueError) as exc:  # pragma: no cover - adapter invariant
        raise LocalAuthorityError("authority custody public key is invalid") from exc


def _append_content_addressed(
    directory: Path,
    *,
    prefix: str,
    content: bytes,
) -> tuple[str, str]:
    """Create one immutable authority artifact without replace semantics."""

    if type(content) is not bytes or not content:
        raise LocalAuthorityError("authority artifact must be non-empty bytes")
    try:
        info = directory.lstat()
    except OSError as exc:
        raise LocalAuthorityPending("authority artifact store is unavailable") from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o027
    ):
        raise LocalAuthorityError("authority artifact store is not protected")
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    name = f"{prefix}-{digest.removeprefix('sha256:')}.json"
    path = directory / name
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(path, flags, 0o440)
    except FileExistsError:
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise LocalAuthorityError(
                "authority artifact collision is unreadable"
            ) from exc
        if existing != content:
            raise LocalAuthorityError("authority artifact digest collision")
        return name, digest
    except OSError as exc:
        raise LocalAuthorityError("authority artifact create failed") from exc
    try:
        offset = 0
        while offset < len(content):
            offset += os.write(fd, content[offset:])
        os.fsync(fd)
        os.fchmod(fd, 0o440)
    except BaseException:
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
    else:
        os.close(fd)
    directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return name, digest


def _json_materialize(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_materialize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_materialize(item) for item in value]
    if type(value) in {str, int, bool, type(None)}:
        return value
    raise LocalAuthorityError("owned mirror identity is not exact JSON")


def _hash_regular_fd(fd: int) -> tuple[str, os.stat_result]:
    try:
        flags = fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE
        before = os.fstat(fd)
    except OSError as exc:
        raise LocalAuthorityError("owned mirror descriptor is unavailable") from exc
    if flags != os.O_RDONLY or not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
        raise LocalAuthorityError("owned mirror descriptor is not read-only SQLite")
    digest = hashlib.sha256()
    offset = 0
    while offset < before.st_size:
        chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
        if not chunk:
            raise LocalAuthorityError("owned mirror descriptor changed while hashing")
        digest.update(chunk)
        offset += len(chunk)
    after = os.fstat(fd)
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise LocalAuthorityError("owned mirror descriptor changed while hashing")
    return "sha256:" + digest.hexdigest(), after


def _open_d1_owned_readonly_fd(db_path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(db_path, flags)
        info = os.fstat(fd)
    except OSError as exc:
        raise LocalAuthorityError("d1_sync governed mirror cannot be opened") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        os.close(fd)
        raise LocalAuthorityError("d1_sync governed mirror ownership is unsafe")
    return fd


def _owned_mirror_evidence(
    fd: int,
    *,
    environment: str,
    purpose: str,
    governed_db_path: Path,
    sync_identity: Mapping[str, object],
) -> dict[str, Any]:
    content_digest, info = _hash_regular_fd(fd)
    identity = _json_materialize(sync_identity)
    if type(identity) is not dict:
        raise LocalAuthorityError("owned mirror sync identity is invalid")
    return {
        "format": OWNED_MIRROR_EVIDENCE_FORMAT,
        "environment": environment,
        "purpose": purpose,
        "governed_db_path": str(governed_db_path),
        "descriptor": {
            "owner_uid": info.st_uid,
            "device": info.st_dev,
            "inode": info.st_ino,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "mode": stat.S_IMODE(info.st_mode),
            "content_digest": content_digest,
        },
        "sync_identity": identity,
        "sync_identity_digest": sha256_digest(identity),
    }


def _validate_owned_mirror(
    payload: Mapping[str, Any],
    fds: Sequence[int],
    *,
    environment: str,
    purpose: str,
    expected_d1_uid: int,
) -> tuple[
    sqlite3.Connection,
    dict[str, Any],
    str,
    dict[str, Any],
    tuple[int, int, int],
]:
    values = _require_payload_fields(
        payload,
        fields={"owned_mirror_evidence", "selector"},
        operation=purpose,
    )
    if len(fds) != 1 or type(values["owned_mirror_evidence"]) is not dict:
        raise LocalAuthorityError("authority requires one d1-owned mirror descriptor")
    evidence = values["owned_mirror_evidence"]
    if (
        set(evidence) != _OWNED_MIRROR_FIELDS
        or evidence["format"] != OWNED_MIRROR_EVIDENCE_FORMAT
        or evidence["environment"] != environment
        or evidence["purpose"] != purpose
        or type(evidence["governed_db_path"]) is not str
        or not Path(evidence["governed_db_path"]).is_absolute()
        or type(evidence["descriptor"]) is not dict
        or set(evidence["descriptor"]) != _DESCRIPTOR_FIELDS
        or type(evidence["sync_identity"]) is not dict
        or evidence["sync_identity_digest"] != sha256_digest(evidence["sync_identity"])
        or type(values["selector"]) is not dict
    ):
        raise LocalAuthorityError("owned mirror evidence identity is invalid")
    digest, info = _hash_regular_fd(fds[0])
    descriptor = evidence["descriptor"]
    observed = {
        "owner_uid": info.st_uid,
        "device": info.st_dev,
        "inode": info.st_ino,
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "mode": stat.S_IMODE(info.st_mode),
        "content_digest": digest,
    }
    if observed != descriptor or info.st_uid != expected_d1_uid:
        raise LocalAuthorityError("mirror descriptor is not owned by d1_sync")
    governed_path = Path(evidence["governed_db_path"])
    try:
        governed_lstat = governed_path.lstat()
        governed_stat = governed_path.stat()
    except OSError as exc:
        raise LocalAuthorityError("owned governed mirror path is unavailable") from exc
    if stat.S_ISLNK(governed_lstat.st_mode) or (
        governed_stat.st_dev,
        governed_stat.st_ino,
    ) != (info.st_dev, info.st_ino):
        raise LocalAuthorityError("owned governed mirror path differs from descriptor")
    conn = authority_protocol_runtime._connect_readonly_fd(fds[0])
    try:
        conn.execute("BEGIN")
        measured = authority_protocol_runtime._remeasure_applied_mirror_identity(conn)
        if _json_materialize(measured) != evidence["sync_identity"]:
            raise LocalAuthorityError("owned mirror sync identity changed")
        final_digest, final_info = _hash_regular_fd(fds[0])
        if final_digest != digest or final_info.st_ino != info.st_ino:
            raise LocalAuthorityError("owned mirror changed during verification")
    except BaseException:
        conn.close()
        raise
    return (
        conn,
        dict(values["selector"]),
        evidence["governed_db_path"],
        dict(evidence),
        (int(info.st_dev), int(info.st_ino), int(info.st_size)),
    )


class OpsProjectionRenderAndSign:
    """C4: render from an authenticated read-only mirror FD, then sign."""

    operation = "ops_projection:render_and_sign"

    def __init__(
        self,
        *,
        environment: str,
        custody: FileEd25519KeyCustody,
        artifact_store: str | Path,
        expected_d1_uid: int,
    ) -> None:
        if environment not in {"staging", "production"}:
            raise LocalAuthorityError("Ops Projection environment is invalid")
        self.environment = environment
        self.custody = custody
        self.artifact_store = Path(artifact_store)
        self.expected_d1_uid = expected_d1_uid

    def __call__(
        self,
        _context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
    ) -> Mapping[str, Any]:
        conn, selector, _, _evidence, authority_file_identity = (
            _validate_owned_mirror(
                payload,
                fds,
                environment=self.environment,
                purpose="ops_projection",
                expected_d1_uid=self.expected_d1_uid,
            )
        )
        if selector:
            conn.close()
            raise LocalAuthorityError("Ops Projection selector must be empty")
        try:
            sync_identity = (
                authority_protocol_runtime._remeasure_applied_mirror_identity(conn)
            )
            frozen_sync_identity = authority_protocol_runtime._deep_immutable(
                sync_identity
            )
            candidate = (
                export_ops_projection._render_projection_candidate_from_authority_connection(
                    conn,
                    frozen_sync_identity,
                    authority_file_identity=authority_file_identity,
                )
            )
        finally:
            conn.close()
        candidate_document = json.loads(candidate.candidate_bytes)
        envelope = dict(candidate_document["projection"]["envelope"])
        sync_identity = candidate_document["sync_identity"]
        envelope.update(
            {
                "environment": self.environment,
                "resource_identity": trust_domain.projection_resource_identity(
                    environment=self.environment,
                    source=sync_identity,
                ),
            }
        )
        projection_signing._validate_envelope(
            envelope, expected_environment=self.environment
        )
        body = projection_signing._signed_body(
            key_id=self.custody.key_id,
            envelope=envelope,
        )
        signed_document = {
            **body,
            "signature": self.custody.sign(
                projection_signing.canonical_json_bytes(body)
            ),
        }
        public = _custody_public_key(self.custody)
        projection_signing._verify_document(
            signed_document,
            {self.custody.key_id: public},
            expected_environment=self.environment,
        )
        active = projection_signing._load_pinned_active_keys(self.environment)
        active_public = active.get(self.custody.key_id)
        if (
            active_public is None
            or active_public.public_bytes_raw() != public.public_bytes_raw()
        ):
            raise LocalAuthorityPending(
                "Ops Projection public registry does not activate the custody key"
            )
        projection_signing.verify_pinned_ops_projection(
            signed_document, expected_environment=self.environment
        )
        signed_bytes = projection_signing.canonical_json_bytes(signed_document)
        signed_name, signed_store_digest = _append_content_addressed(
            self.artifact_store,
            prefix="ops-projection-signed",
            content=signed_bytes,
        )
        return {
            "status": "SIGNED",
            "signed_artifact": signed_name,
            "signed_store_digest": signed_store_digest,
            "signed_document_base64": base64.b64encode(signed_bytes).decode("ascii"),
            "signed_document_digest": "sha256:"
            + hashlib.sha256(signed_bytes).hexdigest(),
            "issuer_key_id": self.custody.key_id,
        }


class CoverageTransitionAuthorize:
    """C10 signer: derive from the d1-owned FD and return, never callback."""

    operation = "coverage_transition:authorize"

    def __init__(
        self,
        *,
        environment: str,
        custody: FileEd25519KeyCustody,
        expected_d1_uid: int,
    ) -> None:
        if environment not in {"staging", "production"}:
            raise LocalAuthorityError("Coverage environment is invalid")
        self.environment = environment
        self.custody = custody
        self.expected_d1_uid = expected_d1_uid

    def __call__(
        self,
        _context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
    ) -> Mapping[str, Any]:
        conn, selector, governed_db_path, evidence, _authority_file_identity = (
            _validate_owned_mirror(
                payload,
                fds,
                environment=self.environment,
                purpose="coverage_transition",
                expected_d1_uid=self.expected_d1_uid,
            )
        )
        build_id = selector.get("build_id")
        datasets = selector.get("datasets")
        if (
            type(build_id) is not str
            or not build_id
            or type(datasets) is not list
            or not datasets
            or any(type(item) is not str or not item for item in datasets)
        ):
            conn.close()
            raise LocalAuthorityError("Coverage authorization selector is invalid")
        issued = datetime.now(UTC).replace(microsecond=0)
        expires = issued + timedelta(
            seconds=min(300, coverage_transition.MAX_AUTHORIZATION_SECONDS)
        )
        try:
            request = dict(
                coverage_transition.build_coverage_transition_request_from_owned_connection(
                    conn,
                    governed_db_path=governed_db_path,
                    build_id=build_id,
                    datasets=datasets,
                    issued_at=issued.isoformat().replace("+00:00", "Z"),
                    expires_at=expires.isoformat().replace("+00:00", "Z"),
                )
            )
            body = dict(request["body"])
            sync_identity = evidence["sync_identity"]
            body.update(
                {
                    "environment": self.environment,
                    "resource_identity": {
                        "environment": self.environment,
                        "source_d1": sync_identity["resource_identity"],
                        "source_audit_digest": sync_identity["audit_digest"],
                        "source_export_digest": sync_identity["export_digest"],
                        "source_change_seq": sync_identity["source_change_seq"],
                        "governed_db_content_digest": evidence["descriptor"][
                            "content_digest"
                        ],
                    },
                }
            )
            request = coverage_transition._unsigned_request(body)
        finally:
            conn.close()
        document = {
            "format": request["format"],
            "authority_domain": request["authority_domain"],
            "issuer": coverage_transition.COVERAGE_TRANSITION_ISSUER,
            "issuer_key_id": self.custody.key_id,
            "algorithm": coverage_transition.COVERAGE_TRANSITION_ALGORITHM,
            "transition_id": request["transition_id"],
            "body": request["body"],
        }
        message = coverage_transition._signature_message(document)
        document["signature"] = self.custody.sign(
            coverage_transition._canonical_bytes(message)
        )
        frozen = coverage_transition._validate_signed_document(
            document, expected_environment=self.environment
        )
        registry = coverage_transition.CoverageTransitionPublicKeyRegistry.load_pinned(
            expected_environment=self.environment
        )
        if not registry.provisioned or not registry.verify(
            key_id=self.custody.key_id,
            message=message,
            signature=frozen["signature"],
        ):
            raise LocalAuthorityPending(
                "Coverage transition public registry does not activate the custody key"
            )
        return {
            "status": "SIGNED",
            "transition_id": frozen["transition_id"],
            "build_id": frozen["body"]["build_id"],
            "dataset_set_digest": frozen["body"]["dataset_set_digest"],
            "signed_transition_digest": sha256_digest(frozen),
            "signed_transition": frozen,
            "issuer_key_id": self.custody.key_id,
        }


class D1FreezeAndRenderOpsProjection:
    operation = "d1_sync:freeze_and_render_ops_projection"

    def __init__(
        self,
        *,
        environment: str,
        governed_db_path: str | Path,
        ops_socket_path: str | Path,
        ops_uid: int,
    ) -> None:
        self.environment = environment
        self.environment = trust_domain.require_environment(environment)
        self.governed_db_path = Path(governed_db_path).absolute()
        self.ops_socket_path = Path(ops_socket_path)
        self.ops_uid = ops_uid

    def __call__(
        self,
        _context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
    ) -> Mapping[str, Any]:
        if payload or fds:
            raise LocalAuthorityError("d1 Ops freeze accepts no caller evidence")
        handle = sync_d1_to_sqlite.open_authenticated_applied_mirror(
            self.governed_db_path
        )

        def consume(
            _conn: sqlite3.Connection, identity: Mapping[str, object]
        ) -> Mapping[str, Any]:
            fd = _open_d1_owned_readonly_fd(self.governed_db_path)
            try:
                evidence = _owned_mirror_evidence(
                    fd,
                    environment=self.environment,
                    purpose="ops_projection",
                    governed_db_path=self.governed_db_path,
                    sync_identity=identity,
                )
                request = {
                    "format": REQUEST_FORMAT,
                    "request_id": sha256_digest(
                        {"operation": self.operation, "evidence": evidence}
                    ),
                    "operation": OpsProjectionRenderAndSign.operation,
                    "purpose": "render_owned_mirror_projection",
                    "payload": {"owned_mirror_evidence": evidence, "selector": {}},
                }
                result = call_unix_authority(
                    self.ops_socket_path,
                    request,
                    expected_server_uid=self.ops_uid,
                    read_only_fd=fd,
                )
                expected_fields = {
                    "status",
                    "signed_artifact",
                    "signed_store_digest",
                    "signed_document_base64",
                    "signed_document_digest",
                    "issuer_key_id",
                }
                if type(result) not in {dict, MappingProxyType} or set(result) != expected_fields:
                    raise LocalAuthorityError(
                        "Ops authority response is not one closed signed document"
                    )
                signed_bytes = _decode_standard_base64(
                    result["signed_document_base64"],
                    field="signed_document_base64",
                )
                if (
                    result["status"] != "SIGNED"
                    or result["signed_document_digest"]
                    != "sha256:" + hashlib.sha256(signed_bytes).hexdigest()
                ):
                    raise LocalAuthorityError(
                        "Ops authority response is not signed evidence"
                    )
                verified = projection_signing._verify_pinned_document(
                    signed_bytes, expected_environment=self.environment
                )
                if verified.issuer_key_id != result["issuer_key_id"]:
                    raise LocalAuthorityError(
                        "Ops authority response issuer identity differs"
                    )
                return result
            finally:
                os.close(fd)

        return sync_d1_to_sqlite._consume_authenticated_applied_mirror(handle, consume)


class _SealedD1SyncAudit:
    """Single-use result passed only from D1 authority signing to persistence."""

    __slots__ = ("_consumed", "_document")

    def __init__(self, document: dict[str, Any]) -> None:
        self._document = document
        self._consumed = False

    def _consume_for_persistence(self) -> tuple[str, str, str, dict[str, Any]]:
        if self._consumed:
            raise LocalAuthorityError("sealed D1 sync audit was already consumed")
        self._consumed = True
        document = self._document
        return (
            d1_sync_signing.d1_sync_digest(document),
            document["issuer_key_id"],
            document["signature"],
            document,
        )


class _D1SyncAuditSealer:
    """Consume only the opaque exact-reconciliation capability and sign it."""

    def __init__(self, custody: FileEd25519KeyCustody, *, environment: str) -> None:
        self.custody = custody
        self.environment = trust_domain.require_environment(environment)

    def preflight(self) -> None:
        try:
            registry = d1_sync_signing._load_registry_document(self.environment)
        except d1_sync_signing.D1SyncAuditError as exc:
            raise LocalAuthorityPending(
                "D1 sync public registry is unavailable"
            ) from exc
        matches = [
            row
            for row in registry["keys"]
            if row["key_id"] == self.custody.key_id
            and row["status"] == "active"
            and row["public_key_base64"] == self.custody.public_key_base64()
        ]
        if registry["authority_status"] != "ACTIVE" or len(matches) != 1:
            raise LocalAuthorityPending(
                "D1 sync public registry does not activate the custody key"
            )

    def __call__(self, reconciled_export: object) -> _SealedD1SyncAudit:
        self.preflight()
        try:
            facts = (
                sync_d1_to_sqlite._private_export.
                _consume_authenticated_export_for_authority(
                    reconciled_export
                )
            )
        except RuntimeError as exc:
            raise LocalAuthorityError(
                "D1 sync signer requires opaque reconciled export evidence"
            ) from exc
        if type(facts) is not dict or set(facts) != _D1_RECONCILED_FACT_FIELDS:
            raise LocalAuthorityError("D1 reconciled export facts are not closed")
        issued_at = d1_sync_signing._utc_now().isoformat()
        resource = dict(trust_domain.d1_resource_identity(self.environment))
        envelope = {
            "schema_version": d1_sync_signing.AUDIT_ENVELOPE_SCHEMA,
            "authority_id": resource["authority_id"],
            "source_mode": "WRANGLER_REMOTE",
            "environment": self.environment,
            "resource_identity": resource,
            "d1_name": resource["name"],
            "d1_id": resource["database_id"],
            **facts,
            "registry_digest": (
                d1_sync_signing.registry_document_digest(self.environment)
            ),
            "issued_at": issued_at,
        }
        body = {
            "schema_version": d1_sync_signing.SIGNED_DOCUMENT_SCHEMA,
            "algorithm": "Ed25519",
            "issuer_key_id": self.custody.key_id,
            "envelope": envelope,
        }
        document = {
            **body,
            "signature": self.custody.sign(
                d1_sync_signing.canonical_d1_sync_bytes(body)
            ),
        }
        d1_sync_signing.verify_signed_d1_sync_audit(
            document, expected_environment=self.environment
        )
        return _SealedD1SyncAudit(document)


def _read_protected_cloudflare_token(path: Path, *, expected_uid: int) -> str:
    try:
        before = path.lstat()
    except OSError as exc:
        raise LocalAuthorityPending(
            "D1 sync Cloudflare credential file is unavailable"
        ) from exc
    if (
        not path.is_absolute()
        or not stat.S_ISREG(before.st_mode)
        or before.st_uid != expected_uid
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) != 0o400
    ):
        raise LocalAuthorityError("D1 sync Cloudflare credential file is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        raw = os.read(fd, 514)
        after = os.fstat(fd)
    except OSError as exc:
        raise LocalAuthorityPending(
            "D1 sync Cloudflare credential cannot be read"
        ) from exc
    finally:
        if "fd" in locals():
            os.close(fd)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or len(raw) > 513
    ):
        raise LocalAuthorityError("D1 sync Cloudflare credential changed while read")
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    try:
        token = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise LocalAuthorityError("D1 sync Cloudflare credential is invalid") from exc
    if (
        not 20 <= len(token) <= 512
        or any(character.isspace() for character in token)
    ):
        raise LocalAuthorityError("D1 sync Cloudflare credential is invalid")
    return token


def _execute_governed_remote_sync(
    *,
    governed_db_path: Path,
    expected_applied_cursor: int,
    credential_token: str,
    node_executable_path: Path,
    wrangler_cli_path: Path,
    wrangler_config_path: Path,
    sealer: _D1SyncAuditSealer,
    environment: str,
) -> Mapping[str, Any]:
    """Acquire the pinned D1, reconcile, sign, persist and freeze one mirror."""

    from types import SimpleNamespace

    from storage.sqlite_store import SqliteStore

    store = SqliteStore(governed_db_path)
    temporary: tempfile.TemporaryDirectory[str] | None = None
    source_conn: sqlite3.Connection | None = None
    try:
        sync_d1_to_sqlite._ensure_control_tables(store._conn)
        sync_d1_to_sqlite._ensure_export_sync_audit(store)
        store._conn.commit()
        observed_cursor = sync_d1_to_sqlite._last_change_seq(store)
        if observed_cursor != expected_applied_cursor:
            raise LocalAuthorityError(
                "D1 sync expected applied cursor does not match the governed mirror"
            )
        incremental = sync_d1_to_sqlite._latest_trusted_sync_audit(store) is not None
        sealer.preflight()
        temporary = tempfile.TemporaryDirectory(prefix="quant-authority-d1-sync-")
        acquired = (
            sync_d1_to_sqlite._private_export.
            _acquire_pinned_wrangler_export_with_preflight(
                Path(temporary.name),
                authority_preflight=sealer.preflight,
                credential_token=credential_token,
                authority_node_path=node_executable_path,
                authority_wrangler_cli_path=wrangler_cli_path,
                authority_wrangler_config_path=wrangler_config_path,
                authority_environment=environment,
            )
        )
        source_conn = acquired.open_source()
        args = SimpleNamespace(
            table=None,
            incremental=incremental,
            since=None,
            page_limit=sync_d1_to_sqlite.DEFAULT_PAGE_LIMIT,
            max_pages=sync_d1_to_sqlite.DEFAULT_MAX_PAGES,
            pilot_ready_evidence=None,
            snapshot_dir=None,
            db=str(governed_db_path),
        )
        begin_snapshot_sync(
            store._conn,
            started_at=datetime.now(UTC).isoformat(),
        )
        seen, registered, skipped, failures = (
            sync_d1_to_sqlite._run_private_export_sync(
                store,
                source_conn,
                list(sync_d1_to_sqlite.DEFAULT_TABLES),
                args,
                export_digest=acquired.export_digest,
                artifact_format=acquired.artifact_format,
                authenticated_acquisition=acquired,
                seal_authenticated_export=sealer,
            )
        )
        sync_d1_to_sqlite._finalize_sync_policy(
            store,
            args,
            failures,
            source_mode="WRANGLER_REMOTE",
        )
        if failures:
            raise LocalAuthorityError(
                "governed D1 reconciliation failed: " + "; ".join(failures)
            )
        sync_d1_to_sqlite._freeze_authenticated_current_applied_mirror(store)
        identity = sync_d1_to_sqlite._authenticated_applied_mirror_identity_from_conn(
            store._conn
        )
        return {
            "status": "SYNCED",
            "prior_applied_cursor": expected_applied_cursor,
            "source_change_seq": identity["source_change_seq"],
            "applied_change_seq": identity["applied_change_seq"],
            "audit_digest": identity["audit_digest"],
            "export_digest": identity["export_digest"],
            "issuer_key_id": identity["issuer_key_id"],
            "seen": seen,
            "registered": registered,
            "skipped": skipped,
        }
    finally:
        store.close()
        if source_conn is not None:
            source_conn.close()
        if temporary is not None:
            temporary.cleanup()


class D1SyncNow:
    """Sync only the configured D1 through authenticated acquisition/reconciliation."""

    operation = "d1_sync:sync_now"

    def __init__(
        self,
        *,
        environment: str,
        governed_db_path: str | Path,
        cloudflare_token_path: str | Path,
        node_executable_path: str | Path,
        wrangler_cli_path: str | Path,
        wrangler_config_path: str | Path,
        custody: FileEd25519KeyCustody,
        expected_uid: int,
        executor: Callable[..., Mapping[str, Any]] = _execute_governed_remote_sync,
    ) -> None:
        self.environment = trust_domain.require_environment(environment)
        self.governed_db_path = Path(governed_db_path).absolute()
        self.cloudflare_token_path = Path(cloudflare_token_path).absolute()
        self.node_executable_path = Path(node_executable_path).absolute()
        self.wrangler_cli_path = Path(wrangler_cli_path).absolute()
        self.wrangler_config_path = Path(wrangler_config_path).absolute()
        self.custody = custody
        self.expected_uid = expected_uid
        self.executor = executor

    def __call__(
        self,
        _context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
    ) -> Mapping[str, Any]:
        values = _require_payload_fields(
            payload,
            fields={"expected_applied_cursor"},
            operation=self.operation,
        )
        expected = values["expected_applied_cursor"]
        if type(expected) is not int or expected < 0 or fds:
            raise LocalAuthorityError(
                "d1 sync requires one exact non-negative expected cursor"
            )
        try:
            info = self.governed_db_path.lstat()
        except OSError as exc:
            raise LocalAuthorityPending("governed D1 mirror is unavailable") from exc
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != self.expected_uid
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise LocalAuthorityError("governed D1 mirror ownership is unsafe")
        token = _read_protected_cloudflare_token(
            self.cloudflare_token_path,
            expected_uid=self.expected_uid,
        )
        result = self.executor(
            governed_db_path=self.governed_db_path,
            expected_applied_cursor=expected,
            credential_token=token,
            node_executable_path=self.node_executable_path,
            wrangler_cli_path=self.wrangler_cli_path,
            wrangler_config_path=self.wrangler_config_path,
            sealer=_D1SyncAuditSealer(
                self.custody, environment=self.environment
            ),
            environment=self.environment,
        )
        if type(result) is not dict or result.get("status") != "SYNCED":
            raise LocalAuthorityError("D1 sync executor returned invalid evidence")
        return result


class D1FreezeAuthorizeApplyCoverage:
    operation = "d1_sync:freeze_authorize_apply_coverage"

    def __init__(
        self,
        *,
        environment: str,
        governed_db_path: str | Path,
        coverage_socket_path: str | Path,
        coverage_uid: int,
    ) -> None:
        self.environment = environment
        self.governed_db_path = Path(governed_db_path).absolute()
        self.coverage_socket_path = Path(coverage_socket_path)
        self.coverage_uid = coverage_uid

    def __call__(
        self,
        _context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
    ) -> Mapping[str, Any]:
        selector = _require_payload_fields(
            payload, fields={"build_id", "datasets"}, operation=self.operation
        )
        if fds:
            raise LocalAuthorityError("d1 Coverage freeze accepts no caller descriptor")
        handle = sync_d1_to_sqlite.open_authenticated_applied_mirror(
            self.governed_db_path
        )

        def consume(
            _conn: sqlite3.Connection, identity: Mapping[str, object]
        ) -> Mapping[str, Any]:
            fd = _open_d1_owned_readonly_fd(self.governed_db_path)
            try:
                evidence = _owned_mirror_evidence(
                    fd,
                    environment=self.environment,
                    purpose="coverage_transition",
                    governed_db_path=self.governed_db_path,
                    sync_identity=identity,
                )
                request = {
                    "format": REQUEST_FORMAT,
                    "request_id": sha256_digest(
                        {
                            "operation": self.operation,
                            "evidence": evidence,
                            "selector": selector,
                        }
                    ),
                    "operation": CoverageTransitionAuthorize.operation,
                    "purpose": "coverage_v3_transition",
                    "payload": {
                        "owned_mirror_evidence": evidence,
                        "selector": selector,
                    },
                }
                return call_unix_authority(
                    self.coverage_socket_path,
                    request,
                    expected_server_uid=self.coverage_uid,
                    read_only_fd=fd,
                )
            finally:
                os.close(fd)

        signed = sync_d1_to_sqlite._consume_authenticated_applied_mirror(
            handle, consume
        )
        document = signed.get("signed_transition")
        if type(document) is not dict or signed.get("status") != "SIGNED":
            raise LocalAuthorityError(
                "Coverage authority did not return one signed transition"
            )
        applied = coverage_transition.apply_signed_coverage_transition(
            str(self.governed_db_path),
            document,
            expected_environment=self.environment,
        )
        return {
            **dict(applied),
            "signed_transition_digest": signed["signed_transition_digest"],
            "issuer_key_id": signed["issuer_key_id"],
        }


def _hash_open_file(fd: int) -> tuple[str, os.stat_result]:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
        raise LocalAuthorityError("READY snapshot artifact is not a regular file")
    digest = hashlib.sha256()
    offset = 0
    while offset < before.st_size:
        chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
        if not chunk:
            raise LocalAuthorityError("READY snapshot changed while hashing")
        digest.update(chunk)
        offset += len(chunk)
    after = os.fstat(fd)
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise LocalAuthorityError("READY snapshot changed while hashing")
    return "sha256:" + digest.hexdigest(), after


def _load_ready_snapshot(
    snapshot_root: Path,
    snapshot_id: str,
) -> tuple[dict[str, Any], dict[str, Any], str, tuple[int, int, int, int]]:
    from paper_runtime.snapshot import (
        RESEARCH_SNAPSHOT_MANIFEST_FORMAT,
        _artifact_stem,
        _immutable_data_snapshot_id,
        _research_manifest_digest,
        _research_manifest_id,
    )

    stem = _artifact_stem(snapshot_id)
    artifact = snapshot_root / f"{stem}.sqlite"
    manifest_path = snapshot_root / f"{stem}.manifest.json"
    if artifact.is_symlink() or manifest_path.is_symlink():
        raise LocalAuthorityError("READY snapshot paths cannot be symlinks")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(artifact, flags)
    except OSError as exc:
        raise LocalAuthorityError("READY snapshot artifact cannot be opened") from exc
    try:
        artifact_digest, info = _hash_open_file(fd)
        if stat.S_IMODE(info.st_mode) & 0o222:
            raise LocalAuthorityError("READY snapshot artifact is writable")
        descriptor_path = Path(f"/dev/fd/{fd}")
        if not descriptor_path.exists():
            descriptor_path = Path(f"/proc/self/fd/{fd}")
        conn = sqlite3.connect(f"file:{descriptor_path}?mode=ro&immutable=1", uri=True)
        try:
            rows = conn.execute(
                "SELECT format,manifest_json FROM local_snapshot_manifests "
                "WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchall()
        finally:
            conn.close()
        if len(rows) != 1 or rows[0][0] != RESEARCH_SNAPSHOT_MANIFEST_FORMAT:
            raise LocalAuthorityError("READY embedded research manifest is missing")
        embedded = decode_strict_json(
            rows[0][1].encode("utf-8"), field="embedded research manifest"
        )
        try:
            external_raw = manifest_path.read_bytes()
        except OSError as exc:
            raise LocalAuthorityError(
                "READY external research manifest is missing"
            ) from exc
        external = decode_strict_json(external_raw, field="external research manifest")
        manifest_info = manifest_path.lstat()
        if stat.S_IMODE(manifest_info.st_mode) & 0o222:
            raise LocalAuthorityError("READY research manifest is writable")
        if external != embedded:
            raise LocalAuthorityError("READY embedded/external manifest mismatch")
        if (
            external.get("state") != "READY"
            or external.get("snapshot_id") != snapshot_id
            or _research_manifest_id(external) != snapshot_id
            or external.get("manifest_digest") != _research_manifest_digest(external)
            or _immutable_data_snapshot_id(descriptor_path) != snapshot_id
        ):
            raise LocalAuthorityError("READY research snapshot identity is invalid")
        ready_manifest = external.get("ready_manifest")
        if type(ready_manifest) is not dict:
            raise LocalAuthorityError("READY snapshot has no embedded ReadyManifest")
        readiness_attestation._validate_exact_four_ready_manifest(
            ready_manifest,
            expected_snapshot_id=snapshot_id,
        )
        final_digest, final_info = _hash_open_file(fd)
        if final_digest != artifact_digest:
            raise LocalAuthorityError("READY snapshot changed during validation")
        identity = (
            final_info.st_dev,
            final_info.st_ino,
            final_info.st_size,
            final_info.st_mtime_ns,
        )
        return external, ready_manifest, artifact_digest, identity
    finally:
        os.close(fd)


class ReadyPublishProfilePlanBound:
    """R5: independently reopen exact-four artifact/evidence and sign READY."""

    operation = "ready:publish_profile_plan_bound"

    def __init__(
        self,
        *,
        environment: str,
        snapshot_root: str | Path,
        custody: FileEd25519KeyCustody,
    ) -> None:
        self.environment = trust_domain.require_environment(environment)
        self.snapshot_root = Path(snapshot_root).resolve(strict=True)
        self.custody = custody

    def __call__(
        self,
        _context: AuthorityRequestContext,
        payload: Mapping[str, Any],
        fds: Sequence[int],
    ) -> Mapping[str, Any]:
        values = _require_payload_fields(
            payload,
            fields={"snapshot_id", "signed_projection_base64"},
            operation=self.operation,
        )
        if fds:
            raise LocalAuthorityError("READY publication reopens its governed store")
        snapshot_id = values["snapshot_id"]
        if type(snapshot_id) is not str:
            raise LocalAuthorityError("READY snapshot id is invalid")
        signed_projection = _decode_standard_base64(
            values["signed_projection_base64"],
            field="signed_projection_base64",
        )
        outer, manifest, artifact_digest, initial_identity = _load_ready_snapshot(
            self.snapshot_root,
            snapshot_id,
        )
        from research.ready_manifest import _verified_production_projection_evidence

        verified_projection = _verified_production_projection_evidence(
            signed_projection,
            list(manifest["dataset_ids"]),
        )
        retained_rows = outer.get("profile_coverage_evidence")
        if type(retained_rows) is not dict or set(retained_rows) != set(
            verified_projection.rows
        ):
            raise LocalAuthorityError("READY retained projection membership mismatch")
        for dataset_id, signed_row in verified_projection.rows.items():
            retained = retained_rows.get(dataset_id)
            if type(retained) is not dict:
                raise LocalAuthorityError("READY retained projection row is missing")
            expected = dict(signed_row)
            expected["applied_sync_generation"] = expected["applied_cursor"]
            if any(retained.get(key) != value for key, value in expected.items()):
                raise LocalAuthorityError(
                    f"READY retained projection evidence mismatch: {dataset_id}"
                )
        if any(
            row.get("signed_projection_document_digest")
            != verified_projection.signed_document_digest
            or row.get("signed_projection_issuer_key_id")
            != verified_projection.issuer_key_id
            for row in retained_rows.values()
        ):
            raise LocalAuthorityError("READY signed projection identity mismatch")

        verified_at = datetime.now(UTC)
        expires_at = verified_at + timedelta(seconds=_READY_TTL_SECONDS)
        evidence_digest = readiness_attestation._digest(
            {"manifest": manifest, "immutable_db_digest": artifact_digest}
        )
        attestation_id = sha256_digest(
            {
                "snapshot_id": snapshot_id,
                "ready_manifest_digest": manifest["manifest_digest"],
                "immutable_db_digest": artifact_digest,
                "verified_at": verified_at.isoformat(),
                "nonce": str(uuid4()),
            }
        )
        document = {
            "format": readiness_attestation.READINESS_ATTESTATION_FORMAT,
            "environment": self.environment,
            "authority_instance_id": ready_authority_instance_id(self.environment),
            "attestation_id": attestation_id,
            "readiness_scope": "PILOT",
            "snapshot_id": snapshot_id,
            "profile_id": manifest["profile_id"],
            "profile_version": manifest["profile_version"],
            "profile_digest": manifest["profile_digest"],
            "plan_ids": manifest["plan_ids"],
            "plan_set_digest": manifest["plan_set_digest"],
            "dependency_closure_digest": manifest["dependency_closure_digest"],
            "universe_rule_digest": manifest["universe_rule_digest"],
            "resolved_universe_digest": manifest["resolved_universe_digest"],
            "dataset_ids": manifest["dataset_ids"],
            "ready_state": "READY",
            "ready_manifest_digest": manifest["manifest_digest"],
            "immutable_db_digest": artifact_digest,
            "coverage_policy_version": manifest["coverage_policy_version"],
            "coverage_policy_digest": manifest["coverage_policy_digest"],
            "coverage_proof_digest": manifest["coverage_proof_digest"],
            "governed_membership_digest": manifest["dataset_membership_digest"],
            "raw_proof_digest": manifest["raw_proof_digest"],
            "receipt_proof_digest": manifest["receipt_proof_digest"],
            "validation_proof_digest": manifest["validation_proof_digest"],
            "b0_quality_proof_digest": manifest["b0_proof_digest"],
            "b4_quality_proof_digest": manifest["b4_proof_digest"],
            "source_generation": manifest["source_generation"],
            "export_cursor": manifest["export_cursor"],
            "applied_cursor": manifest["applied_cursor"],
            "verified_at": verified_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "evidence_digest": evidence_digest,
            "key_id": self.custody.key_id,
            "issuer": "ReadyPublicationService/v3",
        }
        document["authority_resource_digest"] = derive_ready_authority_resource_digest(
            environment=self.environment,
            snapshot_id=snapshot_id,
            immutable_db_digest=artifact_digest,
            ready_manifest_digest=manifest["manifest_digest"],
            signed_projection_document_digest=(
                verified_projection.signed_document_digest
            ),
        )
        document["signed_projection_document_digest"] = (
            verified_projection.signed_document_digest
        )
        document["signature"] = self.custody.sign(
            readiness_attestation._canonical_bytes(document)
        )
        attestation_bytes = readiness_attestation._canonical_bytes(document)
        try:
            scoped_keys = load_scoped_ready_public_keys(
                expected_environment=self.environment
            )
        except LocalReadyRegistryError as exc:
            raise LocalAuthorityPending("READY public registry is unavailable") from exc
        scoped_key = scoped_keys.get(
            (
                self.environment,
                document["authority_instance_id"],
                self.custody.key_id,
            )
        )
        public = _custody_public_key(self.custody)
        if (
            scoped_key is None
            or scoped_key.public_bytes_raw() != public.public_bytes_raw()
        ):
            raise LocalAuthorityPending(
                "READY public registry does not activate the custody key"
            )
        _, _, final_digest, final_identity = _load_ready_snapshot(
            self.snapshot_root,
            snapshot_id,
        )
        if final_digest != artifact_digest or final_identity != initial_identity:
            raise LocalAuthorityError("READY snapshot changed before issuance")
        return {
            "status": "SIGNED",
            "snapshot_id": snapshot_id,
            "environment": self.environment,
            "authority_instance_id": document["authority_instance_id"],
            "authority_resource_digest": document["authority_resource_digest"],
            "attestation_id": attestation_id,
            "attestation_base64": base64.b64encode(attestation_bytes).decode("ascii"),
            "attestation_digest": "sha256:"
            + hashlib.sha256(attestation_bytes).hexdigest(),
            "ready_manifest_digest": manifest["manifest_digest"],
            "immutable_db_digest": artifact_digest,
            "signed_projection_document_digest": (
                verified_projection.signed_document_digest
            ),
            "issuer_key_id": self.custody.key_id,
        }


__all__ = [
    "OWNED_MIRROR_EVIDENCE_FORMAT",
    "CoverageTransitionAuthorize",
    "D1FreezeAndRenderOpsProjection",
    "D1FreezeAuthorizeApplyCoverage",
    "D1SyncNow",
    "OpsProjectionRenderAndSign",
    "ReadyPublishProfilePlanBound",
]
