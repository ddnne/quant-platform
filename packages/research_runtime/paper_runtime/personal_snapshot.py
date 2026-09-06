"""Small, unsigned SQLite snapshots for personal paper research.

This module deliberately does not publish product ``READY`` and does not use
receipt or signing authorities.  It takes one transactionally consistent
SQLite backup, binds the copied bytes and the caller's research scope into a
content address, and publishes read-only database/manifest siblings.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from data_contracts.personal_history_compact import (
    PERSONAL_HISTORY_COMPACT_BARS_TABLE,
    PERSONAL_HISTORY_COMPACT_MASTER_TABLE,
    compact_history_state,
)

from .snapshot_identity import data_snapshot_id


PERSONAL_SNAPSHOT_FORMAT = "personal-paper-snapshot/v1"
PERSONAL_POLICY_FORMAT = "personal-draft-policy/v1"
PERSONAL_PUBLICATION_STATE = "PERSONAL_DRAFT"
_TARGET_LOCAL_PUBLICATION_STATE = "SYNCED"
_PERSONAL_PROVENANCE_TABLE = "personal_snapshot_provenance"
_TYPED_DAILY_BARS_COLUMNS = {
    "source",
    "code",
    "date",
    "event_time",
    "available_at",
}

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_UNSTABLE_PUBLICATION_STATES = frozenset({"BUILDING", "VALIDATING"})
_STABLE_MANAGED_PUBLICATION_STATES = frozenset({"SYNCED", "READY", "REJECTED"})
_SOURCE_POLICY_FIELDS = frozenset(
    {
        "table_present",
        "row_present",
        "require_manifest",
        "snapshot_ready",
        "publication_state",
        "last_error",
    }
)
_MANIFEST_IDENTITY_FIELDS = frozenset(
    {
        "format",
        "database_sha256",
        "logical_data_snapshot_id",
        "required_datasets",
        "period",
        "closure_digests",
        "personal_policy",
        "source_policy_provenance",
        "observed_datasets",
    }
)


class PersonalSnapshotError(RuntimeError):
    """Raised when a personal snapshot cannot be created or verified."""


@dataclass(frozen=True, slots=True)
class PersonalSnapshot:
    """Verified value object for one immutable personal SQLite snapshot."""

    snapshot_id: str
    db_path: Path
    manifest_path: Path
    database_sha256: str
    logical_data_snapshot_id: str
    required_datasets: tuple[str, ...]
    period_start: str
    period_end: str
    closure_digests: tuple[str, ...]

    def verify(self) -> "PersonalSnapshot":
        """Re-read both artifacts and reject any drift from this value."""
        return verify_personal_snapshot(self)


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest_payload(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _iso_date(value: str, label: str) -> str:
    text = str(value).strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD)") from exc
    if parsed.isoformat() != text:
        raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD)")
    return text


def _dataset_ids(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("required_datasets must be an array")
    normalized = tuple(sorted({str(value).strip() for value in values}))
    if not normalized or any(not value for value in normalized):
        raise ValueError("required_datasets must contain non-empty dataset ids")
    return normalized


def _closure_ids(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("closure_digests must be an array")
    normalized = tuple(sorted({str(value).strip() for value in values}))
    if not normalized or any(
        _SHA256_RE.fullmatch(value) is None for value in normalized
    ):
        raise ValueError("closure_digests must contain canonical sha256 digests")
    return normalized


def _readonly_connection(path: Path) -> sqlite3.Connection:
    uri = "file:" + quote(str(path.resolve())) + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if exists is None:
        return set()
    return {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")
    }


def _aggregate_observation(
    connection: sqlite3.Connection,
    *,
    dataset_id: str,
    table: str,
    date_column: str,
    where: str = "",
) -> dict[str, Any] | None:
    row = connection.execute(
        f"SELECT '{dataset_id}' AS dataset,COUNT(*) AS row_count,"
        f"MIN({date_column}) AS min_event_date,MAX({date_column}) AS max_event_date "
        f"FROM {table}{where}"
    ).fetchone()
    if row is None or int(row["row_count"] or 0) < 1:
        return None
    return dict(row)


def _typed_daily_bars_observation(
    connection: sqlite3.Connection,
) -> dict[str, Any] | None:
    typed_columns = _table_columns(connection, "jquants_daily_bars")
    if not _TYPED_DAILY_BARS_COLUMNS <= typed_columns:
        return None
    return _aggregate_observation(
        connection,
        dataset_id="equities_bars_daily",
        table="jquants_daily_bars",
        date_column="date",
        where=" WHERE source='jquants'",
    )


def _source_policy_provenance(connection: sqlite3.Connection) -> dict[str, Any]:
    marker_columns = _table_columns(connection, _PERSONAL_PROVENANCE_TABLE)
    if marker_columns:
        required = {
            "singleton",
            "source_policy_json",
        }
        if not required <= marker_columns:
            raise PersonalSnapshotError(
                "personal snapshot provenance marker is incomplete"
            )
        marker = connection.execute(
            f"SELECT source_policy_json FROM {_PERSONAL_PROVENANCE_TABLE} "
            "WHERE singleton=1"
        ).fetchone()
        if marker is None:
            raise PersonalSnapshotError(
                "personal snapshot provenance marker is empty"
            )
        try:
            embedded = json.loads(str(marker["source_policy_json"]))
        except json.JSONDecodeError as exc:
            raise PersonalSnapshotError(
                "personal snapshot provenance marker is invalid"
            ) from exc
        if not isinstance(embedded, Mapping) or set(embedded) != _SOURCE_POLICY_FIELDS:
            raise PersonalSnapshotError(
                "personal snapshot source policy provenance is invalid"
            )
        return dict(embedded)

    columns = _table_columns(connection, "local_snapshot_policy")
    provenance: dict[str, Any] = {
        "table_present": bool(columns),
        "row_present": False,
        "require_manifest": None,
        "snapshot_ready": None,
        "publication_state": None,
        "last_error": None,
    }
    if not columns:
        return provenance
    if "singleton" not in columns:
        raise PersonalSnapshotError(
            "source local_snapshot_policy has no singleton identity"
        )
    row = connection.execute(
        "SELECT * FROM local_snapshot_policy WHERE singleton=1"
    ).fetchone()
    if row is None:
        return provenance
    provenance["row_present"] = True
    for name in ("require_manifest", "snapshot_ready"):
        if name in columns and row[name] is not None:
            try:
                provenance[name] = int(row[name])
            except (TypeError, ValueError) as exc:
                raise PersonalSnapshotError(
                    f"source local_snapshot_policy.{name} is not an integer"
                ) from exc
    for name in ("publication_state", "last_error"):
        if name in columns and row[name] is not None:
            provenance[name] = str(row[name])
    return provenance


def _personal_policy_document() -> dict[str, Any]:
    return {
        "format": PERSONAL_POLICY_FORMAT,
        "publication_state": PERSONAL_PUBLICATION_STATE,
        "local_snapshot_policy_state": _TARGET_LOCAL_PUBLICATION_STATE,
        "require_manifest": 0,
        "snapshot_ready": 0,
    }


def _install_personal_draft_policy(
    connection: sqlite3.Connection,
    source_provenance: Mapping[str, Any],
) -> None:
    if _table_columns(connection, _PERSONAL_PROVENANCE_TABLE):
        _verify_personal_draft_policy(
            connection,
            personal_policy=_personal_policy_document(),
            source_provenance=source_provenance,
        )
        return
    columns = _table_columns(connection, "local_snapshot_policy")
    if not columns:
        connection.execute(
            """
            CREATE TABLE local_snapshot_policy (
                singleton INTEGER PRIMARY KEY CHECK (singleton=1),
                require_manifest INTEGER NOT NULL DEFAULT 0,
                snapshot_ready INTEGER NOT NULL DEFAULT 0,
                sync_started_at TEXT,
                last_error TEXT,
                publication_state TEXT,
                active_build_id TEXT,
                active_snapshot_id TEXT
            )
            """
        )
    else:
        additions = {
            "require_manifest": "INTEGER NOT NULL DEFAULT 0",
            "snapshot_ready": "INTEGER NOT NULL DEFAULT 0",
            "last_error": "TEXT",
            "publication_state": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(
                    f"ALTER TABLE local_snapshot_policy ADD COLUMN {name} {definition}"
                )

    columns = _table_columns(connection, "local_snapshot_policy")
    cleared = [
        name for name in ("active_build_id", "active_snapshot_id") if name in columns
    ]
    assignments = [
        "require_manifest=0",
        "snapshot_ready=0",
        "publication_state=?",
        "last_error=NULL",
        *(f"{name}=NULL" for name in cleared),
    ]
    updated = connection.execute(
        "UPDATE local_snapshot_policy SET "
        + ",".join(assignments)
        + " WHERE singleton=1",
        (_TARGET_LOCAL_PUBLICATION_STATE,),
    )
    if updated.rowcount == 0:
        connection.execute(
            "INSERT INTO local_snapshot_policy "
            "(singleton,require_manifest,snapshot_ready,last_error,publication_state) "
            "VALUES (1,0,0,NULL,?)",
            (_TARGET_LOCAL_PUBLICATION_STATE,),
        )

    connection.execute(
        f"""
        CREATE TABLE {_PERSONAL_PROVENANCE_TABLE} (
            singleton INTEGER PRIMARY KEY CHECK (singleton=1),
            format TEXT NOT NULL,
            target_publication_state TEXT NOT NULL,
            target_local_publication_state TEXT NOT NULL,
            target_require_manifest INTEGER NOT NULL,
            target_snapshot_ready INTEGER NOT NULL,
            source_policy_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        f"INSERT INTO {_PERSONAL_PROVENANCE_TABLE} VALUES (1,?,?,?,?,?,?)",
        (
            PERSONAL_POLICY_FORMAT,
            PERSONAL_PUBLICATION_STATE,
            _TARGET_LOCAL_PUBLICATION_STATE,
            0,
            0,
            _canonical_bytes(dict(source_provenance)).decode("utf-8"),
        ),
    )


def _publication_state(connection: sqlite3.Connection) -> str | None:
    table = connection.execute(
        "SELECT 1 FROM sqlite_schema WHERE type='table' "
        "AND name='local_snapshot_policy'"
    ).fetchone()
    if table is None:
        return None
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(local_snapshot_policy)")
    }
    if "publication_state" not in columns:
        return None
    row = connection.execute(
        "SELECT publication_state FROM local_snapshot_policy WHERE singleton=1"
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0]).strip().upper()


def _reject_unstable_policy(connection: sqlite3.Connection, *, where: str) -> None:
    state = _publication_state(connection)
    if state in _UNSTABLE_PUBLICATION_STATES:
        raise PersonalSnapshotError(
            f"{where} local snapshot policy is {state}; retry after sync finishes"
        )


def _quick_check(connection: sqlite3.Connection) -> None:
    rows = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
    if rows != ["ok"]:
        raise PersonalSnapshotError(
            "personal SQLite snapshot quick_check failed: " + "; ".join(rows)
        )


def _backup_sqlite(source_path: Path, target_path: Path) -> dict[str, Any]:
    """Copy one committed SQLite view; WAL-resident commits are included."""
    source = _readonly_connection(source_path)
    target = sqlite3.connect(target_path)
    target.row_factory = sqlite3.Row
    try:
        _reject_unstable_policy(source, where="source")
        source.backup(target)
        target.commit()
        _reject_unstable_policy(target, where="copied")
        source_provenance = _source_policy_provenance(target)
        _install_personal_draft_policy(target, source_provenance)
        target.commit()
        _quick_check(target)
        # The artifact must be a standalone main database with no required
        # WAL sidecar.  Backup already copied committed WAL pages.
        target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        target.execute("PRAGMA journal_mode=DELETE")
        target.commit()
        _quick_check(target)
        # Catch a source that entered an explicitly unstable state while the
        # backup was running.  The copied view is consistent, but publishing
        # it during an active sync would be operationally surprising.
        _reject_unstable_policy(source, where="source")
        return source_provenance
    except sqlite3.Error as exc:
        raise PersonalSnapshotError(f"personal SQLite backup failed: {exc}") from exc
    finally:
        target.close()
        source.close()


def _identity_from_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {key: manifest.get(key) for key in sorted(_MANIFEST_IDENTITY_FIELDS)}


def _stem(snapshot_id: str) -> str:
    if _SHA256_RE.fullmatch(snapshot_id) is None:
        raise PersonalSnapshotError(f"invalid personal snapshot id: {snapshot_id!r}")
    return snapshot_id.replace(":", "_", 1)


def _publish_file_without_replace(temporary: Path, destination: Path) -> None:
    try:
        os.link(temporary, destination)
    except FileExistsError:
        pass
    finally:
        temporary.unlink(missing_ok=True)


def _bind_personal_draft_source(
    source_db: str | Path,
    bind_dir: str | Path,
) -> tuple[Path, bool]:
    """Return an unmanaged DRAFT source, copying stable managed input first.

    This is the OfflineFixture/container composition boundary.  Ordinary PIT
    readers still reject managed pre-READY bytes.  A stable managed source is
    transactionally backed up, stripped of its publication authority, marked
    PERSONAL_DRAFT, and content-addressed before a typed DRAFT view can bind
    it.  Active BUILDING/VALIDATING input is always rejected.
    """

    source_path = Path(source_db).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"personal draft source is missing: {source_path}")
    source = _readonly_connection(source_path)
    try:
        _reject_unstable_policy(source, where="source")
        if _table_columns(source, _PERSONAL_PROVENANCE_TABLE):
            provenance = _source_policy_provenance(source)
            _verify_personal_draft_policy(
                source,
                personal_policy=_personal_policy_document(),
                source_provenance=provenance,
            )
            return source_path, False
        policy_columns = _table_columns(source, "local_snapshot_policy")
        if not policy_columns:
            return source_path, False
        policy = source.execute(
            "SELECT * FROM local_snapshot_policy WHERE singleton=1"
        ).fetchone()
        if policy is None:
            return source_path, False
        require_manifest = bool(
            policy["require_manifest"] if "require_manifest" in policy.keys() else 0
        )
        snapshot_ready = bool(
            policy["snapshot_ready"] if "snapshot_ready" in policy.keys() else 0
        )
        managed = require_manifest or snapshot_ready
        if not managed:
            return source_path, False
        state = str(
            policy["publication_state"]
            if "publication_state" in policy.keys()
            and policy["publication_state"] is not None
            else ""
        ).upper()
        if state not in _STABLE_MANAGED_PUBLICATION_STATES:
            raise PersonalSnapshotError(
                "managed personal draft source has no stable publication state"
            )
    finally:
        source.close()

    destination = Path(bind_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    fd, raw_temporary = tempfile.mkstemp(
        prefix=".personal-draft-bind.", suffix=".sqlite.tmp", dir=destination
    )
    os.close(fd)
    temporary = Path(raw_temporary)
    try:
        provenance = _backup_sqlite(source_path, temporary)
        copied = _readonly_connection(temporary)
        try:
            _verify_personal_draft_policy(
                copied,
                personal_policy=_personal_policy_document(),
                source_provenance=provenance,
            )
        finally:
            copied.close()
        os.utime(temporary, ns=(0, 0))
        digest = _file_digest(temporary)
        bound_path = destination / f"personal-draft-bind-{_stem(digest)}.sqlite"
        os.chmod(temporary, 0o444)
        _publish_file_without_replace(temporary, bound_path)
        if _file_digest(bound_path) != digest:
            raise PersonalSnapshotError(
                f"personal draft bind collision or tamper: {bound_path}"
            )
        os.chmod(bound_path, 0o444)
        return bound_path.resolve(), True
    finally:
        temporary.unlink(missing_ok=True)


def _write_manifest_without_replace(path: Path, payload: Mapping[str, Any]) -> None:
    data = _canonical_bytes(payload) + b"\n"
    fd, raw_temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(raw_temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o444)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise PersonalSnapshotError(
                    f"personal snapshot manifest collision: {path}"
                )
    finally:
        temporary.unlink(missing_ok=True)


def _observed_dataset_evidence(
    connection: sqlite3.Connection,
    required_datasets: Sequence[str],
    *,
    period_start: str,
    period_end: str,
) -> list[dict[str, Any]]:
    generic_columns = _table_columns(connection, "jquants_records")
    required_generic = {"source", "dataset", "event_time", "payload"}
    by_dataset: dict[str, dict[str, Any]] = {}
    if required_generic <= generic_columns:
        placeholders = ",".join("?" for _ in required_datasets)
        rows = connection.execute(
            "SELECT dataset,COUNT(*) AS row_count,"
            "MIN(substr(event_time,1,10)) AS min_event_date,"
            "MAX(substr(event_time,1,10)) AS max_event_date "
            "FROM jquants_records WHERE source='jquants' "
            f"AND dataset IN ({placeholders}) GROUP BY dataset ORDER BY dataset",
            tuple(required_datasets),
        ).fetchall()
        by_dataset.update(
            (str(row["dataset"]), dict(row)) for row in rows
        )

    compact_state = compact_history_state(connection)
    if compact_state == "invalid":
        raise PersonalSnapshotError(
            "personal snapshot compact v7 marker or schema is invalid"
        )
    if compact_state == "mixed":
        raise PersonalSnapshotError(
            "personal snapshot cannot mix compact with typed or generic "
            "equity master or bars"
        )

    if compact_state == "compact":
        if "equities_master" in required_datasets:
            compact_master = _aggregate_observation(
                connection,
                dataset_id="equities_master",
                table=PERSONAL_HISTORY_COMPACT_MASTER_TABLE,
                date_column="snapshot_date",
            )
            if compact_master is not None:
                by_dataset["equities_master"] = compact_master
        if "equities_bars_daily" in required_datasets:
            compact_bars = _aggregate_observation(
                connection,
                dataset_id="equities_bars_daily",
                table=PERSONAL_HISTORY_COMPACT_BARS_TABLE,
                date_column="date",
            )
            if compact_bars is not None:
                by_dataset["equities_bars_daily"] = compact_bars
    elif "equities_bars_daily" in required_datasets:
        typed_bars = _typed_daily_bars_observation(connection)
        if typed_bars is not None:
            # The personal hydrator promotes its largest/query-hot partition into
            # the existing indexed typed table at completion. Prefer that
            # representation, while retaining generic observations for older
            # fixtures and snapshots.
            generic_bars = by_dataset.get("equities_bars_daily")
            if generic_bars is not None and int(generic_bars["row_count"] or 0) > 0:
                raise PersonalSnapshotError(
                    "personal snapshot cannot mix generic and typed daily bars"
                )
            by_dataset["equities_bars_daily"] = typed_bars

    evidence: list[dict[str, Any]] = []
    for dataset_id in required_datasets:
        row = by_dataset.get(dataset_id)
        if row is None or int(row["row_count"] or 0) < 1:
            raise PersonalSnapshotError(
                f"required dataset {dataset_id!r} has no observed rows"
            )
        try:
            minimum = _iso_date(str(row["min_event_date"] or ""), "min_event_date")
            maximum = _iso_date(str(row["max_event_date"] or ""), "max_event_date")
        except ValueError as exc:
            raise PersonalSnapshotError(
                f"required dataset {dataset_id!r} has invalid event dates"
            ) from exc
        evidence.append(
            {
                "dataset_id": dataset_id,
                "evidence_status": "OBSERVED",
                "row_count": int(row["row_count"]),
                "min_event_date": minimum,
                "max_event_date": maximum,
            }
        )

    observed = {item["dataset_id"]: item for item in evidence}
    calendar_evidence = observed.get("markets_calendar")
    if calendar_evidence is not None and (
        calendar_evidence["min_event_date"] > period_start
        or calendar_evidence["max_event_date"] < period_end
    ):
        raise PersonalSnapshotError(
            "markets_calendar observed range does not cover the requested period"
        )

    bars_evidence = observed.get("equities_bars_daily")
    if bars_evidence is not None:
        if calendar_evidence is None:
            raise PersonalSnapshotError(
                "equities_bars_daily range requires observed markets_calendar rows"
            )
        calendar_rows = connection.execute(
            "SELECT substr(event_time,1,10) AS event_date,payload "
            "FROM jquants_records WHERE source='jquants' "
            "AND dataset='markets_calendar' "
            "AND substr(event_time,1,10) BETWEEN ? AND ? ORDER BY event_time",
            (period_start, period_end),
        ).fetchall()
        trading_days: list[str] = []
        for row in calendar_rows:
            try:
                payload = json.loads(str(row["payload"]))
            except (TypeError, json.JSONDecodeError) as exc:
                raise PersonalSnapshotError(
                    "markets_calendar contains an invalid observed payload"
                ) from exc
            if not isinstance(payload, Mapping):
                raise PersonalSnapshotError(
                    "markets_calendar contains a non-object observed payload"
                )
            holiday = next(
                (
                    str(payload[name])
                    for name in ("HolidayDivision", "HolDiv", "holiday_division")
                    if payload.get(name) is not None
                ),
                "",
            )
            if holiday == "1":
                trading_days.append(str(row["event_date"]))
        if not trading_days:
            raise PersonalSnapshotError(
                "markets_calendar has no observed trading day in the requested period"
            )
        if (
            bars_evidence["min_event_date"] > trading_days[0]
            or bars_evidence["max_event_date"] < trading_days[-1]
        ):
            raise PersonalSnapshotError(
                "equities_bars_daily observed range does not cover requested "
                "trading days"
            )
    return evidence


def _verify_personal_draft_policy(
    connection: sqlite3.Connection,
    *,
    personal_policy: Any,
    source_provenance: Any,
) -> None:
    expected_policy = _personal_policy_document()
    if personal_policy != expected_policy:
        raise PersonalSnapshotError("personal snapshot DRAFT policy is invalid")
    if not isinstance(source_provenance, Mapping):
        raise PersonalSnapshotError(
            "personal snapshot source policy provenance is missing"
        )
    source_document = dict(source_provenance)
    if set(source_document) != _SOURCE_POLICY_FIELDS:
        raise PersonalSnapshotError(
            "personal snapshot source policy provenance is invalid"
        )
    source_state = str(source_document.get("publication_state") or "").upper()
    if source_state in _UNSTABLE_PUBLICATION_STATES:
        raise PersonalSnapshotError(
            f"personal snapshot source policy provenance is {source_state}"
        )

    columns = _table_columns(connection, "local_snapshot_policy")
    required = {
        "singleton",
        "require_manifest",
        "snapshot_ready",
        "publication_state",
        "last_error",
    }
    if not required <= columns:
        raise PersonalSnapshotError("personal snapshot target policy is incomplete")
    policy = connection.execute(
        "SELECT * FROM local_snapshot_policy WHERE singleton=1"
    ).fetchone()
    if (
        policy is None
        or int(policy["require_manifest"]) != 0
        or int(policy["snapshot_ready"]) != 0
        or str(policy["publication_state"]) != _TARGET_LOCAL_PUBLICATION_STATE
        or policy["last_error"] is not None
        or any(
            policy[name] is not None
            for name in ("active_build_id", "active_snapshot_id")
            if name in columns
        )
    ):
        raise PersonalSnapshotError("personal snapshot target is not DRAFT-only")

    marker_columns = _table_columns(connection, _PERSONAL_PROVENANCE_TABLE)
    if not marker_columns:
        raise PersonalSnapshotError("personal snapshot provenance marker is missing")
    marker = connection.execute(
        f"SELECT * FROM {_PERSONAL_PROVENANCE_TABLE} WHERE singleton=1"
    ).fetchone()
    if marker is None:
        raise PersonalSnapshotError("personal snapshot provenance marker is empty")
    try:
        marker_source = json.loads(str(marker["source_policy_json"]))
    except json.JSONDecodeError as exc:
        raise PersonalSnapshotError(
            "personal snapshot provenance marker is invalid"
        ) from exc
    if (
        str(marker["format"]) != PERSONAL_POLICY_FORMAT
        or str(marker["target_publication_state"]) != PERSONAL_PUBLICATION_STATE
        or str(marker["target_local_publication_state"])
        != _TARGET_LOCAL_PUBLICATION_STATE
        or int(marker["target_require_manifest"]) != 0
        or int(marker["target_snapshot_ready"]) != 0
        or marker_source != source_document
    ):
        raise PersonalSnapshotError(
            "personal snapshot provenance marker does not match its manifest"
        )


def materialize_personal_snapshot(
    source_db: str | Path,
    snapshot_dir: str | Path,
    *,
    required_datasets: Sequence[str],
    period_start: str,
    period_end: str,
    closure_digests: Sequence[str],
) -> PersonalSnapshot:
    """Create or reopen one idempotent, unsigned personal research snapshot."""
    source_path = Path(source_db).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"personal snapshot source is missing: {source_path}")
    start = _iso_date(period_start, "period_start")
    end = _iso_date(period_end, "period_end")
    if start > end:
        raise ValueError("personal snapshot period_start must be <= period_end")
    datasets = _dataset_ids(required_datasets)
    closures = _closure_ids(closure_digests)

    destination = Path(snapshot_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    fd, raw_temporary = tempfile.mkstemp(
        prefix=".personal-snapshot.", suffix=".sqlite.tmp", dir=destination
    )
    os.close(fd)
    temporary = Path(raw_temporary)
    try:
        source_provenance = _backup_sqlite(source_path, temporary)
        copied = _readonly_connection(temporary)
        try:
            observed_datasets = _observed_dataset_evidence(
                copied,
                datasets,
                period_start=start,
                period_end=end,
            )
            _verify_personal_draft_policy(
                copied,
                personal_policy=_personal_policy_document(),
                source_provenance=source_provenance,
            )
        finally:
            copied.close()
        # The existing logical ``data_snapshot_id`` has a legacy fallback that
        # includes main-file mtime when a small fixture has no watermarks.
        # Normalize it so byte-identical personal artifacts remain idempotent.
        os.utime(temporary, ns=(0, 0))
        database_sha256 = _file_digest(temporary)
        database_path = destination / f"{_stem(database_sha256)}.sqlite"
        os.chmod(temporary, 0o444)
        _publish_file_without_replace(temporary, database_path)
        if _file_digest(database_path) != database_sha256:
            raise PersonalSnapshotError(
                f"personal snapshot database collision or tamper: {database_path}"
            )
        os.chmod(database_path, 0o444)
        try:
            logical_id = data_snapshot_id(database_path)
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            raise PersonalSnapshotError(
                f"personal logical data_snapshot_id failed: {exc}"
            ) from exc
        identity: dict[str, Any] = {
            "format": PERSONAL_SNAPSHOT_FORMAT,
            "database_sha256": database_sha256,
            "logical_data_snapshot_id": logical_id,
            "required_datasets": list(datasets),
            "period": {"start": start, "end": end},
            "closure_digests": list(closures),
            "personal_policy": _personal_policy_document(),
            "source_policy_provenance": source_provenance,
            "observed_datasets": observed_datasets,
        }
        snapshot_id = _digest_payload(identity)
        stem = _stem(snapshot_id)
        manifest_path = destination / f"{stem}.manifest.json"
        manifest = {
            **identity,
            "snapshot_id": snapshot_id,
            "database_file": database_path.name,
        }

        _write_manifest_without_replace(manifest_path, manifest)
        os.chmod(manifest_path, 0o444)
        return verify_personal_snapshot(manifest_path)
    finally:
        temporary.unlink(missing_ok=True)


def verify_personal_snapshot(
    snapshot: PersonalSnapshot | str | Path,
) -> PersonalSnapshot:
    """Verify filenames, hashes, scope identity, permissions, and SQLite health."""
    expected = snapshot if isinstance(snapshot, PersonalSnapshot) else None
    manifest_file = Path(
        expected.manifest_path if expected is not None else snapshot
    ).resolve()
    try:
        raw = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PersonalSnapshotError(
            f"personal snapshot manifest is unreadable: {manifest_file}"
        ) from exc
    if not isinstance(raw, dict) or raw.get("format") != PERSONAL_SNAPSHOT_FORMAT:
        raise PersonalSnapshotError("unsupported personal snapshot manifest")

    snapshot_id = str(raw.get("snapshot_id") or "")
    stem = _stem(snapshot_id)
    expected_manifest_name = f"{stem}.manifest.json"
    if manifest_file.name != expected_manifest_name:
        raise PersonalSnapshotError("personal snapshot manifest filename/id mismatch")

    if not _MANIFEST_IDENTITY_FIELDS.issubset(raw):
        raise PersonalSnapshotError("personal snapshot identity is incomplete")
    identity = _identity_from_manifest(raw)
    if _digest_payload(identity) != snapshot_id:
        raise PersonalSnapshotError("personal snapshot manifest/id mismatch")

    database_sha256 = str(raw.get("database_sha256") or "")
    if _SHA256_RE.fullmatch(database_sha256) is None:
        raise PersonalSnapshotError("personal snapshot database_sha256 is invalid")
    expected_database_name = f"{_stem(database_sha256)}.sqlite"
    if raw.get("database_file") != expected_database_name:
        raise PersonalSnapshotError("personal snapshot database filename/hash mismatch")
    database_path = manifest_file.parent / expected_database_name
    if not database_path.is_file():
        raise PersonalSnapshotError(
            f"personal snapshot database is missing: {database_path}"
        )
    if _file_digest(database_path) != database_sha256:
        raise PersonalSnapshotError("personal snapshot database hash mismatch")
    logical_id = str(raw.get("logical_data_snapshot_id") or "")
    try:
        actual_logical_id = data_snapshot_id(database_path)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise PersonalSnapshotError(
            f"personal logical data_snapshot_id failed: {exc}"
        ) from exc
    if logical_id != actual_logical_id:
        raise PersonalSnapshotError("personal logical data_snapshot_id mismatch")

    period = raw.get("period")
    if not isinstance(period, Mapping):
        raise PersonalSnapshotError("personal snapshot period is missing")
    try:
        start = _iso_date(str(period.get("start") or ""), "period.start")
        end = _iso_date(str(period.get("end") or ""), "period.end")
        datasets = _dataset_ids(raw.get("required_datasets") or ())
        closures = _closure_ids(raw.get("closure_digests") or ())
    except (TypeError, ValueError) as exc:
        raise PersonalSnapshotError(str(exc)) from exc
    if start > end:
        raise PersonalSnapshotError("personal snapshot period is reversed")
    if list(datasets) != raw.get("required_datasets"):
        raise PersonalSnapshotError("personal snapshot datasets are not canonical")
    if list(closures) != raw.get("closure_digests"):
        raise PersonalSnapshotError(
            "personal snapshot closure digests are not canonical"
        )

    for path in (database_path, manifest_file):
        if path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            raise PersonalSnapshotError(
                f"personal snapshot artifact is writable: {path}"
            )
    connection = _readonly_connection(database_path)
    try:
        _verify_personal_draft_policy(
            connection,
            personal_policy=raw.get("personal_policy"),
            source_provenance=raw.get("source_policy_provenance"),
        )
        observed_datasets = _observed_dataset_evidence(
            connection,
            datasets,
            period_start=start,
            period_end=end,
        )
        if raw.get("observed_datasets") != observed_datasets:
            raise PersonalSnapshotError(
                "personal snapshot observed dataset evidence mismatch"
            )
        _reject_unstable_policy(connection, where="personal snapshot")
        _quick_check(connection)
    finally:
        connection.close()

    verified = PersonalSnapshot(
        snapshot_id=snapshot_id,
        db_path=database_path.resolve(),
        manifest_path=manifest_file,
        database_sha256=database_sha256,
        logical_data_snapshot_id=logical_id,
        required_datasets=datasets,
        period_start=start,
        period_end=end,
        closure_digests=closures,
    )
    if expected is not None and verified != expected:
        raise PersonalSnapshotError(
            "personal snapshot value does not match its artifacts"
        )
    return verified


__all__ = [
    "PERSONAL_SNAPSHOT_FORMAT",
    "PersonalSnapshot",
    "PersonalSnapshotError",
    "materialize_personal_snapshot",
    "verify_personal_snapshot",
]
