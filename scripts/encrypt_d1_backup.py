#!/usr/bin/env python3
"""Restore, validate, encrypt, and re-verify a production Cloudflare D1 export.

The SQL export is never trusted merely because Wrangler produced a file. It is
streamed into a temporary SQLite database, checked for integrity and the
canonical production ingestion schema, and only then encrypted. The restore
evidence is authenticated as AES-GCM associated data, so a later verifier can
recover the database identity and validation result without retaining the SQL.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import struct
import subprocess
import tempfile
from typing import Any, BinaryIO, Mapping
import uuid

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


MAGIC = b"QPDBENC2"
NONCE_BYTES = 12
TAG_BYTES = 16
KEY_BYTES = 32
HEADER_LENGTH_BYTES = 4
MAX_HEADER_BYTES = 64 * 1024
CHUNK_BYTES = 4 * 1024 * 1024
BACKUP_FORMAT = "quant-platform-d1-backup/aes-256-gcm-v2"
SCHEMA_PROFILE = "quant-ingest-production/v1"
GOVERNED_DATABASE_NAME = "quant-ingest"
GOVERNED_DATABASE_ID = "be6fdcf8-40be-41fc-9535-7facd1fc2ffc"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

# This is deliberately a minimum profile rather than a migration snapshot.
# A pre-migration production backup remains valid while an unrelated D1 (or a
# hand-written SQL file) cannot be mislabeled as the ingestion source of truth.
_MINIMUM_SCHEMA: Mapping[str, frozenset[str]] = {
    "jquants_listed_info": frozenset(
        {"source", "code", "snapshot_date", "event_time", "available_at", "ingested_at"}
    ),
    "jquants_daily_bars": frozenset(
        {"source", "code", "date", "event_time", "available_at", "ingested_at"}
    ),
    "jquants_market_calendar": frozenset(
        {"source", "date", "event_time", "available_at", "ingested_at"}
    ),
    "jquants_records": frozenset(
        {
            "source",
            "dataset",
            "natural_key",
            "event_time",
            "available_at",
            "ingested_at",
        }
    ),
    "ingestion_run_log": frozenset(
        {"id", "ran_at", "source", "runtime", "status"}
    ),
    "ingestion_validation": frozenset(
        {"id", "run_id", "dataset", "started_at", "finished_at", "status"}
    ),
    "ingestion_watermarks": frozenset(
        {"dataset", "last_ingested_at", "last_export_cursor"}
    ),
    "ingestion_change_log": frozenset(
        {"change_seq", "table_name", "source", "dataset", "natural_key"}
    ),
    "raw_retention_manifests": frozenset(
        {"dataset", "run_id", "manifest_key", "data_digest", "completeness"}
    ),
    "coverage_segments": frozenset(
        {"source", "dataset", "segment_id", "policy_version", "status"}
    ),
    "collection_receipts": frozenset(
        {
            "source",
            "dataset",
            "segment_id",
            "run_id",
            "raw_row_count",
            "structured_row_count",
            "status",
        }
    ),
    "jsda_otc_bond_reference_prices": frozenset(
        {"source", "publication_label_date", "security_code", "available_at", "raw_digest"}
    ),
    "jsda_corporate_bond_transactions": frozenset(
        {"source", "publication_label_date", "trade_date", "available_at", "raw_digest"}
    ),
    "jsda_repo_rates": frozenset(
        {"source", "as_of_date", "tenor", "available_at", "raw_digest"}
    ),
}
_REQUIRED_NONEMPTY_TABLES = ("ingestion_run_log", "jquants_records")
_MINIMUM_INDEXES: Mapping[str, frozenset[str]] = {
    "jquants_records": frozenset({"ix_records_dataset_avail"}),
}
_MINIMUM_PRIMARY_KEYS: Mapping[str, frozenset[str]] = {
    "jquants_records": frozenset({"source", "dataset", "natural_key"}),
    "ingestion_change_log": frozenset({"change_seq"}),
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _require_utc_timestamp(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp")
    try:
        observed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp") from exc
    if observed.tzinfo is None or observed.utcoffset() != timezone.utc.utcoffset(observed):
        raise ValueError(f"{label} must be an RFC3339 UTC timestamp")
    return value


def generate_key(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(os.urandom(KEY_BYTES))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _load_key(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError("backup encryption key must be a regular file")
    if path.stat().st_mode & 0o077:
        raise ValueError("backup encryption key permissions must be 0600 or stricter")
    key = path.read_bytes()
    if len(key) != KEY_BYTES:
        raise ValueError("backup encryption key must contain exactly 32 raw bytes")
    return key


def _resolved_distinct(*paths: Path) -> None:
    resolved = [path.resolve() for path in paths]
    if len(resolved) != len(set(resolved)):
        raise ValueError("source, encrypted target, and key must be distinct files")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _schema_inventory(conn: sqlite3.Connection) -> tuple[dict[str, Any], int]:
    table_names = tuple(
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    )
    tables: dict[str, dict[str, Any]] = {}
    for table in table_names:
        quoted = _quoted_identifier(table)
        columns = tuple(
            {
                "name": str(row[1]),
                "type": str(row[2] or ""),
                "not_null": int(row[3]),
                "default": row[4],
                "primary_key_ordinal": int(row[5]),
            }
            for row in conn.execute(f"PRAGMA table_info({quoted})")
        )
        indexes = tuple(
            {
                "name": str(row[1]),
                "unique": int(row[2]),
                "origin": str(row[3]),
                "partial": int(row[4]),
            }
            for row in conn.execute(f"PRAGMA index_list({quoted})")
        )
        tables[table] = {"columns": columns, "indexes": indexes}
    triggers = tuple(
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'trigger' ORDER BY name"
        )
    )
    inventory = {"tables": tables, "triggers": triggers}
    return inventory, len(table_names)


def _key_id(key: bytes) -> str:
    return "sha256:" + hashlib.sha256(key).hexdigest()


def _validate_database_identity(
    *, database_name: str, database_id: str, release_source_sha: str
) -> None:
    if database_name != GOVERNED_DATABASE_NAME or database_id != GOVERNED_DATABASE_ID:
        raise ValueError("D1 export identity is not the governed production database")
    if not _SHA.fullmatch(release_source_sha):
        raise ValueError("release_source_sha must be a full lowercase Git SHA")


def _restore_and_validate_export(
    source: Path,
    *,
    database_name: str,
    database_id: str,
    exported_at: str,
    release_source_sha: str,
    sqlite3_binary: str | None = None,
) -> tuple[dict[str, Any], str, int]:
    _validate_database_identity(
        database_name=database_name,
        database_id=database_id,
        release_source_sha=release_source_sha,
    )
    _require_utc_timestamp(exported_at, "exported_at")
    if not source.is_file() or source.is_symlink():
        raise ValueError("D1 backup source must be a regular file")
    if source.stat().st_size <= 0:
        raise ValueError("D1 backup source must be non-empty")

    executable = sqlite3_binary or shutil.which("sqlite3")
    if not executable:
        raise ValueError("sqlite3 CLI is required to validate the D1 SQL export")

    with tempfile.TemporaryDirectory(prefix="quant-platform-d1-restore-") as directory:
        restored = Path(directory) / "restored.sqlite3"
        digest = hashlib.sha256()
        source_bytes = 0
        # No shell is involved, and stdout/stderr are discarded deliberately:
        # a malformed export must not echo SQL rows or secrets into release logs.
        process = subprocess.Popen(
            [executable, "-batch", "-bail", str(restored)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        assert process.stdin is not None
        try:
            with source.open("rb") as handle:
                while chunk := handle.read(CHUNK_BYTES):
                    digest.update(chunk)
                    source_bytes += len(chunk)
                    process.stdin.write(chunk)
            process.stdin.close()
            return_code = process.wait()
        except BrokenPipeError as exc:
            process.stdin.close()
            process.wait()
            raise ValueError("D1 SQL export could not be restored") from exc
        except BaseException:
            process.kill()
            process.wait()
            raise
        if return_code != 0 or source_bytes <= 0 or not restored.is_file():
            raise ValueError("D1 SQL export could not be restored")

        try:
            connection = sqlite3.connect(
                f"file:{restored}?mode=ro&immutable=1", uri=True
            )
            try:
                integrity_rows = tuple(
                    str(row[0]) for row in connection.execute("PRAGMA integrity_check")
                )
                if integrity_rows != ("ok",):
                    raise ValueError("restored D1 database failed integrity_check")
                inventory, table_count = _schema_inventory(connection)
                tables = inventory["tables"]
                for table, required_columns in _MINIMUM_SCHEMA.items():
                    observed_columns = {
                        str(column["name"])
                        for column in tables.get(table, {}).get("columns", ())
                    }
                    if not required_columns.issubset(observed_columns):
                        raise ValueError(
                            "restored D1 database does not match the canonical schema profile"
                        )
                for table, required_pk in _MINIMUM_PRIMARY_KEYS.items():
                    pk_columns = {
                        str(column["name"])
                        for column in tables.get(table, {}).get("columns", ())
                        if int(column["primary_key_ordinal"]) > 0
                    }
                    if pk_columns != set(required_pk):
                        raise ValueError(
                            "restored D1 database is missing required primary-key invariants"
                        )
                for table, required_indexes in _MINIMUM_INDEXES.items():
                    observed_indexes = {
                        str(index["name"])
                        for index in tables.get(table, {}).get("indexes", ())
                    }
                    if not required_indexes.issubset(observed_indexes):
                        raise ValueError(
                            "restored D1 database is missing required index invariants"
                        )
                for table in _REQUIRED_NONEMPTY_TABLES:
                    quoted = _quoted_identifier(table)
                    if connection.execute(
                        f"SELECT 1 FROM {quoted} LIMIT 1"
                    ).fetchone() is None:
                        raise ValueError(
                            "restored D1 database lacks canonical production data evidence"
                        )
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise ValueError("restored D1 database validation failed") from exc

        schema_digest = _digest_bytes(_canonical_bytes(inventory))
        restore = {
            "evidence_id": str(uuid.uuid4()),
            "verified_at": _utc_now(),
            "source_sha": release_source_sha,
            "engine": "sqlite3-cli+integrity_check",
            "integrity_check": "ok",
            "canonical_minimum_schema": "PASS",
            "required_nonempty_tables": "PASS",
            "schema_digest": schema_digest,
            "table_count": table_count,
        }
        return restore, "sha256:" + digest.hexdigest(), source_bytes


def _header_payload(
    *,
    database_name: str,
    database_id: str,
    exported_at: str,
    restore: Mapping[str, Any],
    plaintext_bytes: int,
    plaintext_digest: str,
    key_id: str,
    nonce: bytes,
) -> dict[str, Any]:
    return {
        "format": BACKUP_FORMAT,
        "cipher": "AES-256-GCM",
        "key_id": key_id,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "database": {
            "name": database_name,
            "id": database_id,
            "schema_profile": SCHEMA_PROFILE,
        },
        "exported_at": exported_at,
        "restore": dict(restore),
        "plaintext_bytes": plaintext_bytes,
        "plaintext_digest": plaintext_digest,
    }


def _validate_authenticated_header(header: Any) -> Mapping[str, Any]:
    if not isinstance(header, Mapping) or set(header) != {
        "format",
        "cipher",
        "key_id",
        "nonce",
        "database",
        "exported_at",
        "restore",
        "plaintext_bytes",
        "plaintext_digest",
    }:
        raise ValueError("encrypted backup authenticated header schema is invalid")
    if header.get("format") != BACKUP_FORMAT or header.get("cipher") != "AES-256-GCM":
        raise ValueError("encrypted backup format or cipher is invalid")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(header.get("key_id") or "")):
        raise ValueError("encrypted backup key id is invalid")
    try:
        nonce = base64.b64decode(str(header.get("nonce") or ""), validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("encrypted backup nonce is invalid") from exc
    if len(nonce) != NONCE_BYTES:
        raise ValueError("encrypted backup nonce is invalid")
    database = header.get("database")
    if not isinstance(database, Mapping) or set(database) != {
        "name",
        "id",
        "schema_profile",
    }:
        raise ValueError("encrypted backup database identity is invalid")
    if (
        database.get("name") != GOVERNED_DATABASE_NAME
        or database.get("id") != GOVERNED_DATABASE_ID
        or database.get("schema_profile") != SCHEMA_PROFILE
    ):
        raise ValueError("encrypted backup database identity is invalid")
    _require_utc_timestamp(str(header.get("exported_at") or ""), "exported_at")
    restore = header.get("restore")
    if not isinstance(restore, Mapping) or set(restore) != {
        "evidence_id",
        "verified_at",
        "source_sha",
        "engine",
        "integrity_check",
        "canonical_minimum_schema",
        "required_nonempty_tables",
        "schema_digest",
        "table_count",
    }:
        raise ValueError("encrypted backup restore evidence schema is invalid")
    if (
        not _UUID.fullmatch(str(restore.get("evidence_id") or ""))
        or not _SHA.fullmatch(str(restore.get("source_sha") or ""))
        or restore.get("engine") != "sqlite3-cli+integrity_check"
        or restore.get("integrity_check") != "ok"
        or restore.get("canonical_minimum_schema") != "PASS"
        or restore.get("required_nonempty_tables") != "PASS"
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(restore.get("schema_digest") or ""))
        or not isinstance(restore.get("table_count"), int)
        or int(restore["table_count"]) < len(_MINIMUM_SCHEMA)
    ):
        raise ValueError("encrypted backup restore evidence is invalid")
    _require_utc_timestamp(str(restore.get("verified_at") or ""), "verified_at")
    if (
        not isinstance(header.get("plaintext_bytes"), int)
        or int(header["plaintext_bytes"]) <= 0
        or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", str(header.get("plaintext_digest") or "")
        )
    ):
        raise ValueError("encrypted backup plaintext evidence is invalid")
    return header


def _encrypt_stream(
    source: BinaryIO,
    target: BinaryIO,
    key: bytes,
    *,
    header_bytes: bytes,
    nonce: bytes,
) -> None:
    encoded_length = struct.pack(">I", len(header_bytes))
    associated_data = MAGIC + encoded_length + header_bytes
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(associated_data)
    target.write(associated_data)
    while chunk := source.read(CHUNK_BYTES):
        target.write(encryptor.update(chunk))
    target.write(encryptor.finalize())
    target.write(encryptor.tag)


def verify_encrypted(path: Path, key_path: Path) -> dict[str, object]:
    _resolved_distinct(path, key_path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("encrypted backup must be a regular file")
    key = _load_key(key_path)
    size = path.stat().st_size
    minimum = len(MAGIC) + HEADER_LENGTH_BYTES + NONCE_BYTES + TAG_BYTES
    if size <= minimum:
        raise ValueError("encrypted backup is truncated")
    plaintext_digest = hashlib.sha256()
    plaintext_bytes = 0
    with path.open("rb") as handle:
        if handle.read(len(MAGIC)) != MAGIC:
            raise ValueError("encrypted backup magic is invalid")
        encoded_length = handle.read(HEADER_LENGTH_BYTES)
        if len(encoded_length) != HEADER_LENGTH_BYTES:
            raise ValueError("encrypted backup header is truncated")
        header_length = struct.unpack(">I", encoded_length)[0]
        if header_length <= 0 or header_length > MAX_HEADER_BYTES:
            raise ValueError("encrypted backup header length is invalid")
        header_bytes = handle.read(header_length)
        if len(header_bytes) != header_length:
            raise ValueError("encrypted backup header is truncated")
        try:
            header = _validate_authenticated_header(json.loads(header_bytes))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("encrypted backup authenticated header is invalid") from exc
        nonce = base64.b64decode(str(header["nonce"]), validate=True)
        header_end = len(MAGIC) + HEADER_LENGTH_BYTES + header_length
        ciphertext_length = size - header_end - TAG_BYTES
        if ciphertext_length <= 0:
            raise ValueError("encrypted backup ciphertext is truncated")
        if header.get("key_id") != _key_id(key):
            raise ValueError("encrypted backup key id does not match the supplied key")
        handle.seek(size - TAG_BYTES)
        tag = handle.read(TAG_BYTES)
        handle.seek(header_end)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(MAGIC + encoded_length + header_bytes)
        remaining = ciphertext_length
        while remaining:
            chunk = handle.read(min(CHUNK_BYTES, remaining))
            if not chunk:
                raise ValueError("encrypted backup ciphertext is truncated")
            remaining -= len(chunk)
            plaintext = decryptor.update(chunk)
            plaintext_digest.update(plaintext)
            plaintext_bytes += len(plaintext)
        final = decryptor.finalize()
        plaintext_digest.update(final)
        plaintext_bytes += len(final)

    observed_digest = "sha256:" + plaintext_digest.hexdigest()
    if (
        plaintext_bytes != header["plaintext_bytes"]
        or observed_digest != header["plaintext_digest"]
    ):
        raise ValueError("encrypted backup does not reproduce authenticated plaintext evidence")
    return {
        "format": BACKUP_FORMAT,
        "cipher": "AES-256-GCM",
        "encrypted": True,
        "verified": True,
        "plaintext_bytes": plaintext_bytes,
        "plaintext_digest": observed_digest,
        "ciphertext_bytes": size,
        "ciphertext_digest": _digest_file(path),
        "authenticated_metadata_digest": _digest_bytes(header_bytes),
        "database": dict(header["database"]),
        "exported_at": header["exported_at"],
        "restore": dict(header["restore"]),
        "key_id": header["key_id"],
        "nonce": header["nonce"],
    }


def encrypt_backup(
    source: Path,
    target: Path,
    key_path: Path,
    *,
    database_name: str,
    database_id: str,
    exported_at: str,
    release_source_sha: str,
    delete_source: bool = True,
    sqlite3_binary: str | None = None,
) -> dict[str, object]:
    _resolved_distinct(source, target, key_path)
    if target.exists():
        raise FileExistsError(f"encrypted backup target already exists: {target.name}")
    key = _load_key(key_path)

    # Validation happens before the target directory or partial ciphertext is
    # created. Every validation failure therefore preserves the SQL source and
    # leaves the public target pathname absent.
    restore, source_digest, source_bytes = _restore_and_validate_export(
        source,
        database_name=database_name,
        database_id=database_id,
        exported_at=exported_at,
        release_source_sha=release_source_sha,
        sqlite3_binary=sqlite3_binary,
    )
    nonce = os.urandom(NONCE_BYTES)
    header = _header_payload(
        database_name=database_name,
        database_id=database_id,
        exported_at=exported_at,
        restore=restore,
        plaintext_bytes=source_bytes,
        plaintext_digest=source_digest,
        key_id=_key_id(key),
        nonce=nonce,
    )
    header_bytes = _canonical_bytes(header)
    if len(header_bytes) > MAX_HEADER_BYTES:
        raise ValueError("authenticated backup metadata is too large")

    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".partial",
    )
    temporary = Path(temporary_name)
    os.chmod(temporary, 0o600)
    try:
        with source.open("rb") as source_handle, os.fdopen(descriptor, "wb") as target_handle:
            _encrypt_stream(
                source_handle,
                target_handle,
                key,
                header_bytes=header_bytes,
                nonce=nonce,
            )
            target_handle.flush()
            os.fsync(target_handle.fileno())
        observed = verify_encrypted(temporary, key_path)
        if (
            observed["plaintext_digest"] != source_digest
            or observed["plaintext_bytes"] != source_bytes
            or observed["authenticated_metadata_digest"] != _digest_bytes(header_bytes)
        ):
            raise ValueError("encrypted backup verification did not reproduce the source")
        os.replace(temporary, target)
        _fsync_directory(target.parent)
        if delete_source:
            source.unlink()
            _fsync_directory(source.parent)
        return observed
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    keygen = subparsers.add_parser("keygen")
    keygen.add_argument("key", type=Path)

    encrypt = subparsers.add_parser("encrypt")
    encrypt.add_argument("source", type=Path)
    encrypt.add_argument("target", type=Path)
    encrypt.add_argument("--key", type=Path, required=True)
    encrypt.add_argument("--database-name", required=True)
    encrypt.add_argument("--database-id", required=True)
    encrypt.add_argument("--exported-at", required=True)
    encrypt.add_argument("--release-source-sha", required=True)
    encrypt.add_argument(
        "--keep-source",
        action="store_true",
        help="retain the plaintext after verified encryption (unsafe opt-in)",
    )

    verify = subparsers.add_parser("verify")
    verify.add_argument("encrypted", type=Path)
    verify.add_argument("--key", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "keygen":
        generate_key(args.key)
        print(json.dumps({"created": True}))
        return 0
    if args.command == "encrypt":
        result = encrypt_backup(
            args.source,
            args.target,
            args.key,
            database_name=args.database_name,
            database_id=args.database_id,
            exported_at=args.exported_at,
            release_source_sha=args.release_source_sha,
            delete_source=not args.keep_source,
        )
    else:
        result = verify_encrypted(args.encrypted, args.key)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
