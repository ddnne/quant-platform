"""Private sqlite bind and DRAFT source copy for paper_runtime adapters.

Not a product API. Product/research must not import this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote


PERSONAL_POLICY_FORMAT = "personal-draft-policy/v1"
PERSONAL_PUBLICATION_STATE = "PERSONAL_DRAFT"
_TARGET_LOCAL_PUBLICATION_STATE = "SYNCED"
_PERSONAL_PROVENANCE_TABLE = "personal_snapshot_provenance"
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


class PersonalSnapshotError(RuntimeError):
    """Raised when a personal snapshot cannot be created or verified."""


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


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


def draft_sqlite_path(view: Any) -> Path:
    from .personal_research_view import (
        PersonalResearchDataView,
        PersonalResearchViewError,
    )

    if not isinstance(view, PersonalResearchDataView):
        raise PersonalResearchViewError("draft sqlite bind requires a research data view")
    source = getattr(view, "_source", None)
    if not isinstance(source, Path):
        raise PersonalResearchViewError("draft view has no sqlite backend")
    return source


def draft_artifact_root(view: Any) -> Path:
    from .personal_research_view import (
        PersonalResearchDataView,
        PersonalResearchViewError,
    )

    if not isinstance(view, PersonalResearchDataView):
        raise PersonalResearchViewError("draft artifact bind requires a research data view")
    root = getattr(view, "_artifacts", None)
    if not isinstance(root, Path):
        raise PersonalResearchViewError("draft view has no artifact sink")
    return root


def activate_prepared_sqlite(view: Any, source: Path) -> None:
    from .personal_research_view import (
        PersonalResearchDataView,
        PersonalResearchViewError,
    )

    if not isinstance(view, PersonalResearchDataView):
        raise PersonalResearchViewError("prepared sqlite bind requires a research data view")
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise PersonalResearchViewError(f"prepared snapshot is missing: {path}")
    object.__setattr__(view, "_source", path)


__all__ = [
    "activate_prepared_sqlite",
    "draft_artifact_root",
    "draft_sqlite_path",
]
