from __future__ import annotations

import importlib.util
from pathlib import Path
import sqlite3
import struct
import sys

import pytest
from cryptography.exceptions import InvalidTag


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "encrypt_d1_backup.py"
SPEC = importlib.util.spec_from_file_location("encrypt_d1_backup", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)

SHA = "a" * 40
EXPORTED_AT = "2026-08-25T06:00:00Z"


@pytest.fixture(autouse=True)
def _hermetic_sqlite3_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Exercise the CLI boundary without depending on the CI host image.

    Production still fails closed when the real ``sqlite3`` executable is
    absent.  The test process supplies a closed argv-compatible executable so
    restore, streaming, error, and publication behavior remain deterministic
    on both macOS and the Ubuntu Workers Builds image.
    """

    executable = tmp_path / "sqlite3-test-cli"
    executable.write_text(
        f"""#!{sys.executable}
import sqlite3
import sys

if len(sys.argv) != 4 or sys.argv[1:3] != ["-batch", "-bail"]:
    raise SystemExit(2)
connection = sqlite3.connect(sys.argv[3])
try:
    connection.executescript(sys.stdin.read())
    connection.commit()
except (OSError, sqlite3.Error):
    connection.close()
    raise SystemExit(1)
connection.close()
""",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    original_which = backup.shutil.which

    def which(name: str) -> str | None:
        if name == "sqlite3":
            return str(executable)
        return original_which(name)

    monkeypatch.setattr(backup.shutil, "which", which)
    return executable


def _quoted(column: str) -> str:
    return '"' + column.replace('"', '""') + '"'


def key(tmp_path: Path) -> Path:
    path = tmp_path / "backup.key"
    backup.generate_key(path)
    return path


def identity_kwargs() -> dict[str, str]:
    return {
        "environment": "production",
        "database_name": backup.GOVERNED_DATABASE_NAME,
        "database_id": backup.GOVERNED_DATABASE_ID,
        "exported_at": EXPORTED_AT,
        "release_source_sha": SHA,
    }


def governed_d1_export(
    tmp_path: Path,
    *,
    suffix: str = "",
    populate: bool = True,
    include_index: bool = True,
) -> Path:
    database = tmp_path / f"source{suffix}.sqlite3"
    connection = sqlite3.connect(database)
    try:
        for table, required_columns in backup._MINIMUM_SCHEMA.items():
            column_sql = []
            pk = backup._MINIMUM_PRIMARY_KEYS.get(table)
            for column in sorted(required_columns):
                column_sql.append(f'"{column}" TEXT NOT NULL' if pk and column in pk else f'"{column}" TEXT')
            extra_pk = ""
            if pk:
                extra_pk = f', PRIMARY KEY ({", ".join(_quoted(column) for column in sorted(pk))})'
            connection.execute(
                f'CREATE TABLE "{table}" ({", ".join(column_sql)}{extra_pk})'
            )
        if include_index:
            connection.execute(
                'CREATE INDEX "ix_records_dataset_avail" ON "jquants_records" '
                '("dataset", "available_at")'
            )
        if populate:
            for table in backup._REQUIRED_NONEMPTY_TABLES:
                columns = sorted(backup._MINIMUM_SCHEMA[table])
                placeholders = ", ".join("?" for _ in columns)
                connection.execute(
                    f'INSERT INTO "{table}" ({", ".join(_quoted(c) for c in columns)}) '
                    f"VALUES ({placeholders})",
                    tuple("governed" for _ in columns),
                )
        connection.commit()
        dump = "\n".join(connection.iterdump()) + "\n"
    finally:
        connection.close()
    database.unlink()
    source = tmp_path / f"quant-ingest{suffix}.sql"
    source.write_text(dump, encoding="utf-8")
    return source


def test_valid_d1_dump_encrypts_verifies_and_deletes_only_after_success(
    tmp_path: Path,
) -> None:
    source = governed_d1_export(tmp_path)
    encrypted = tmp_path / "quant-ingest.sql.enc"
    key_path = key(tmp_path)
    result = backup.encrypt_backup(
        source,
        encrypted,
        key_path,
        **identity_kwargs(),
    )
    assert result["format"] == backup.BACKUP_FORMAT
    assert result["verified"] is True
    assert result["plaintext_bytes"] > 0
    assert result["ciphertext_bytes"] > result["plaintext_bytes"]
    assert result["database"] == {
        "environment": "production",
        "name": backup.GOVERNED_DATABASE_NAME,
        "id": backup.GOVERNED_DATABASE_ID,
        "schema_profile": backup.SCHEMA_PROFILE,
    }
    assert result["exported_at"] == EXPORTED_AT
    assert result["key_id"].startswith("sha256:")
    assert result["nonce"]
    assert result["restore"]["integrity_check"] == "ok"
    assert result["restore"]["canonical_minimum_schema"] == "PASS"
    assert result["restore"]["required_nonempty_tables"] == "PASS"
    assert result["restore"]["source_sha"] == SHA
    assert not source.exists()
    assert encrypted.stat().st_mode & 0o777 == 0o600
    assert backup.verify_encrypted(encrypted, key_path) == result


def test_plaintext_retention_requires_explicit_opt_in(tmp_path: Path) -> None:
    source = governed_d1_export(tmp_path)
    encrypted = tmp_path / "quant-ingest.sql.enc"
    backup.encrypt_backup(
        source,
        encrypted,
        key(tmp_path),
        delete_source=False,
        **identity_kwargs(),
    )
    assert source.is_file()
    assert encrypted.is_file()


def test_empty_arbitrary_and_invalid_sql_fail_before_target_publication(
    tmp_path: Path,
) -> None:
    key_path = key(tmp_path)
    cases = {
        "empty": b"",
        "arbitrary": b"SELECT 1;\n",
        "invalid": b"this is not valid SQL and may contain a secret-value\n",
    }
    for name, body in cases.items():
        source = tmp_path / f"{name}.sql"
        target = tmp_path / f"{name}.enc"
        source.write_bytes(body)
        with pytest.raises(ValueError):
            backup.encrypt_backup(
                source,
                target,
                key_path,
                **identity_kwargs(),
            )
        assert source.read_bytes() == body
        assert not target.exists()
        assert not list(tmp_path.glob(f".{target.name}.*.partial"))


def test_missing_sqlite_cli_fails_closed_before_target_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = governed_d1_export(tmp_path)
    target = tmp_path / "missing-cli.enc"
    key_path = key(tmp_path)
    monkeypatch.setattr(backup.shutil, "which", lambda _name: None)
    with pytest.raises(ValueError, match="sqlite3 CLI is required"):
        backup.encrypt_backup(source, target, key_path, **identity_kwargs())
    assert source.is_file()
    assert not target.exists()


def test_wrong_database_identity_or_schema_fails_closed(tmp_path: Path) -> None:
    source = governed_d1_export(tmp_path, suffix="-identity")
    target = tmp_path / "identity.enc"
    key_path = key(tmp_path)
    wrong_identity = identity_kwargs()
    wrong_identity["database_id"] = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(ValueError, match="governed production database"):
        backup.encrypt_backup(source, target, key_path, **wrong_identity)
    assert source.is_file()
    assert not target.exists()

    wrong_schema = tmp_path / "wrong-schema.sql"
    wrong_schema.write_text("CREATE TABLE unrelated (id INTEGER);\n", encoding="utf-8")
    with pytest.raises(ValueError, match="canonical schema profile"):
        backup.encrypt_backup(
            wrong_schema,
            target,
            key_path,
            **identity_kwargs(),
        )
    assert wrong_schema.is_file()
    assert not target.exists()


def test_staging_identity_is_manifest_bound_and_cross_environment_fails(
    tmp_path: Path,
) -> None:
    source = governed_d1_export(tmp_path, suffix="-staging")
    target = tmp_path / "quant-ingest-staging.sql.enc"
    key_path = key(tmp_path)
    staging = backup._governed_database("staging")
    result = backup.encrypt_backup(
        source,
        target,
        key_path,
        environment="staging",
        database_name=staging["name"],
        database_id=staging["id"],
        exported_at=EXPORTED_AT,
        release_source_sha=SHA,
    )
    assert result["database"] == staging
    assert backup.verify_encrypted(target, key_path)["database"] == staging

    second = governed_d1_export(tmp_path, suffix="-cross-env")
    with pytest.raises(ValueError, match="governed staging database"):
        backup.encrypt_backup(
            second,
            tmp_path / "cross-env.enc",
            key_path,
            environment="staging",
            database_name=backup.GOVERNED_DATABASE_NAME,
            database_id=backup.GOVERNED_DATABASE_ID,
            exported_at=EXPORTED_AT,
            release_source_sha=SHA,
        )
    assert second.is_file()


def test_authenticated_environment_cannot_be_relabelled(tmp_path: Path) -> None:
    source = governed_d1_export(tmp_path, suffix="-environment")
    encrypted = tmp_path / "environment.enc"
    key_path = key(tmp_path)
    backup.encrypt_backup(source, encrypted, key_path, **identity_kwargs())
    raw = bytearray(encrypted.read_bytes())
    header_offset = len(backup.MAGIC) + backup.HEADER_LENGTH_BYTES
    header_length = struct.unpack(
        ">I", raw[len(backup.MAGIC) : header_offset]
    )[0]
    header = bytes(raw[header_offset : header_offset + header_length])
    replacement = header.replace(b'"environment":"production"', b'"environment":"staging___"')
    assert replacement != header
    raw[header_offset : header_offset + header_length] = replacement
    encrypted.write_bytes(raw)
    with pytest.raises((ValueError, InvalidTag)):
        backup.verify_encrypted(encrypted, key_path)


def test_tamper_is_rejected(tmp_path: Path) -> None:
    source = governed_d1_export(tmp_path)
    encrypted = tmp_path / "quant-ingest.sql.enc"
    key_path = key(tmp_path)
    backup.encrypt_backup(source, encrypted, key_path, **identity_kwargs())
    raw = bytearray(encrypted.read_bytes())
    header_length_offset = len(backup.MAGIC)
    header_length = struct.unpack(
        ">I",
        raw[
            header_length_offset : header_length_offset + backup.HEADER_LENGTH_BYTES
        ],
    )[0]
    ciphertext_offset = (
        len(backup.MAGIC)
        + backup.HEADER_LENGTH_BYTES
        + header_length
    )
    raw[ciphertext_offset] ^= 1
    encrypted.write_bytes(raw)
    with pytest.raises(InvalidTag):
        backup.verify_encrypted(encrypted, key_path)


def test_key_permissions_and_target_overwrite_fail_closed(tmp_path: Path) -> None:
    source = governed_d1_export(tmp_path)
    target = tmp_path / "quant-ingest.sql.enc"
    target.write_bytes(b"existing")
    key_path = key(tmp_path)
    with pytest.raises(FileExistsError):
        backup.encrypt_backup(source, target, key_path, **identity_kwargs())

    key_path.chmod(0o644)
    target.unlink()
    with pytest.raises(ValueError, match="permissions"):
        backup.encrypt_backup(source, target, key_path, **identity_kwargs())


def test_racing_target_creation_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = governed_d1_export(tmp_path, suffix="-race")
    original_source = source.read_bytes()
    target = tmp_path / "race.enc"
    key_path = key(tmp_path)
    real_link = backup.os.link

    def racing_link(source_path, target_path, **kwargs):
        Path(target_path).write_bytes(b"racing-owner")
        return real_link(source_path, target_path, **kwargs)

    monkeypatch.setattr(backup.os, "link", racing_link)
    with pytest.raises(FileExistsError):
        backup.encrypt_backup(source, target, key_path, **identity_kwargs())
    assert target.read_bytes() == b"racing-owner"
    assert source.read_bytes() == original_source
    assert not list(tmp_path.glob(f".{target.name}.*.partial"))


def test_key_generation_refuses_overwrite(tmp_path: Path) -> None:
    key_path = key(tmp_path)
    original = key_path.read_bytes()
    with pytest.raises(FileExistsError):
        backup.generate_key(key_path)
    assert key_path.read_bytes() == original


def test_verification_failure_keeps_plaintext_and_does_not_publish_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = governed_d1_export(tmp_path)
    original = source.read_bytes()
    target = tmp_path / "quant-ingest.sql.enc"
    key_path = key(tmp_path)

    def reject_verification(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise InvalidTag

    monkeypatch.setattr(backup, "verify_encrypted", reject_verification)
    with pytest.raises(InvalidTag):
        backup.encrypt_backup(source, target, key_path, **identity_kwargs())

    assert source.read_bytes() == original
    assert not target.exists()
    assert not list(tmp_path.glob(".*.partial"))


def test_metadata_wrong_key_truncation_and_ciphertext_replacement_fail(
    tmp_path: Path,
) -> None:
    source = governed_d1_export(tmp_path)
    encrypted = tmp_path / "quant-ingest.sql.enc"
    key_path = key(tmp_path)
    result = backup.encrypt_backup(
        source, encrypted, key_path, delete_source=False, **identity_kwargs()
    )
    assert result["key_id"].startswith("sha256:")
    assert result["nonce"]
    original = encrypted.read_bytes()

    tampered = bytearray(original)
    header_start = len(backup.MAGIC) + backup.HEADER_LENGTH_BYTES
    tampered[header_start + 8] ^= 1
    encrypted.write_bytes(tampered)
    with pytest.raises((ValueError, InvalidTag)):
        backup.verify_encrypted(encrypted, key_path)

    encrypted.write_bytes(original)
    other_key = key(tmp_path / "other")
    with pytest.raises(ValueError, match="key id"):
        backup.verify_encrypted(encrypted, other_key)

    encrypted.write_bytes(original[: len(backup.MAGIC) + 2])
    with pytest.raises(ValueError, match="truncated"):
        backup.verify_encrypted(encrypted, key_path)

    replacement_source = governed_d1_export(tmp_path, suffix="-replacement")
    replacement = tmp_path / "replacement.enc"
    backup.encrypt_backup(
        replacement_source,
        replacement,
        key_path,
        delete_source=False,
        **identity_kwargs(),
    )
    other_raw = replacement.read_bytes()
    header_length = struct.unpack(
        ">I",
        original[len(backup.MAGIC) : len(backup.MAGIC) + backup.HEADER_LENGTH_BYTES],
    )[0]
    original_header_end = (
        len(backup.MAGIC) + backup.HEADER_LENGTH_BYTES + header_length
    )
    other_header_length = struct.unpack(
        ">I",
        other_raw[len(backup.MAGIC) : len(backup.MAGIC) + backup.HEADER_LENGTH_BYTES],
    )[0]
    other_header_end = (
        len(backup.MAGIC) + backup.HEADER_LENGTH_BYTES + other_header_length
    )
    swapped = original[:original_header_end] + other_raw[other_header_end:]
    encrypted.write_bytes(swapped)
    with pytest.raises((ValueError, InvalidTag)):
        backup.verify_encrypted(encrypted, key_path)


def test_empty_required_evidence_and_missing_index_are_rejected(
    tmp_path: Path,
) -> None:
    key_path = key(tmp_path)
    empty = governed_d1_export(tmp_path, suffix="-empty", populate=False)
    target = tmp_path / "empty.enc"
    with pytest.raises(ValueError, match="canonical production data evidence"):
        backup.encrypt_backup(empty, target, key_path, **identity_kwargs())
    assert empty.is_file()
    assert not target.exists()

    missing_index = governed_d1_export(
        tmp_path, suffix="-no-index", include_index=False
    )
    with pytest.raises(ValueError, match="index invariants"):
        backup.encrypt_backup(
            missing_index, tmp_path / "missing-index.enc", key_path, **identity_kwargs()
        )
    assert missing_index.is_file()


def test_integrity_check_failure_preserves_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = governed_d1_export(tmp_path)
    original = source.read_bytes()
    target = tmp_path / "integrity.enc"
    key_path = key(tmp_path)

    real_connect = sqlite3.connect

    class _IntegrityFailure:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._conn = conn

        def execute(self, sql, *rest):
            if "integrity_check" in str(sql).lower():
                return self._conn.execute("SELECT 'not ok'")
            return self._conn.execute(sql, *rest)

        def close(self) -> None:
            self._conn.close()

    def fail_integrity(database, *args, **kwargs):
        return _IntegrityFailure(real_connect(database, *args, **kwargs))

    monkeypatch.setattr(backup.sqlite3, "connect", fail_integrity)
    with pytest.raises(ValueError, match="integrity_check"):
        backup.encrypt_backup(source, target, key_path, **identity_kwargs())
    assert source.read_bytes() == original
    assert not target.exists()


def test_encrypt_streams_in_bounded_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = governed_d1_export(tmp_path)
    sizes: list[int] = []
    original_open = Path.open

    def tracking_open(self, *args, **kwargs):
        handle = original_open(self, *args, **kwargs)
        if self.resolve() == source.resolve() and "b" in (args[0] if args else kwargs.get("mode", "r")):
            inner_read = handle.read

            def read(size=-1):
                chunk = inner_read(size)
                sizes.append(len(chunk))
                return chunk

            handle.read = read  # type: ignore[method-assign]
        return handle

    monkeypatch.setattr(Path, "open", tracking_open)
    backup.encrypt_backup(
        source,
        tmp_path / "streamed.enc",
        key(tmp_path),
        delete_source=False,
        **identity_kwargs(),
    )
    assert sizes
    assert max(sizes) <= backup.CHUNK_BYTES
