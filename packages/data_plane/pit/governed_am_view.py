"""Closed verifier for Controlled AM session rows.

A recomputable row self-hash, same-DB catalog digest, or table name is never
authority. Production views are minted only from a private one-shot snapshot
handle after READY envelope verification and after the container has
downloaded, hashed, size-checked, opened read-only, and pinned the exact
R2 snapshot object. Offline fixtures use a distinct type that cannot enter
the Controlled path.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping
from urllib.parse import quote

from ops.receipt_product import (
    PRODUCT_ARTIFACT_FIELDS,
    product_artifact_body_digest,
)

from .errors import SnapshotObservationClockError
from .query import (
    bind_external_readonly_connection,
    normalize_as_of,
    resolve_db_path,
)

GOVERNED_AM_DATASET_ID = "equities_bars_daily_am"
GOVERNED_DAILY_DATASET_ID = "equities_bars_daily"
_MORNING_CLOSE_SUFFIX = "T11:30:00+09:00"
_OPERATIONAL_USABLE_BY_SUFFIX = "T12:30:00+09:00"
_GOVERNED_AM_VIEW_TOKEN = object()
_OFFLINE_FIXTURE_AM_VIEW_TOKEN = object()
_HANDLE_TOKEN = object()
_SESSION_SCOPE_TOKEN = object()
_PM_CLOSE_CHANGE_DATE = "2024-11-05"


def _canonical_payload_text(payload: Any) -> str:
    if isinstance(payload, str):
        text = payload
        try:
            decoded = json.loads(payload)
        except (TypeError, ValueError):
            return text
        if isinstance(decoded, dict):
            return json.dumps(
                decoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
        return text
    if isinstance(payload, Mapping):
        return json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    return ""


def _payload_price(payload: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = payload.get(key)
        try:
            price = float(value)
        except (TypeError, ValueError):
            continue
        if price == price and price not in (float("inf"), float("-inf")) and price > 0.0:
            return price
    return None


def _am_payload_price(payload: Mapping[str, Any]) -> float | None:
    return _payload_price(
        payload, ("MAdjC", "MorningAdjustmentClose", "morning_adjustment_close")
    )


def _pm_payload_price(payload: Mapping[str, Any]) -> float | None:
    return _payload_price(
        payload, ("AAdjC", "AfternoonAdjustmentClose", "afternoon_adjustment_close")
    )


def _row_identity_for_corruption_check(row: Mapping[str, Any]) -> str:
    """Checksum of sealed row bytes. Not an authorization token."""

    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    checksum_payload = {
        key: payload[key] for key in payload if key != "am_row_identity"
    }
    body = {
        "dataset": GOVERNED_AM_DATASET_ID,
        "source": str(row.get("source") or ""),
        "natural_key": str(row.get("natural_key") or ""),
        "date": str(payload.get("Date") or payload.get("date") or "")[:10],
        "event_time": str(row.get("event_time") or ""),
        "available_at": str(row.get("available_at") or ""),
        "ingested_at": str(row.get("ingested_at") or ""),
        "payload_digest": "sha256:"
        + hashlib.sha256(
            _canonical_payload_text(checksum_payload).encode("utf-8")
        ).hexdigest(),
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _decode_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw:
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return dict(decoded) if isinstance(decoded, dict) else {}
    return {}


def official_afternoon_close_as_of(day: str) -> str:
    hhmmss = "15:30:00" if day >= _PM_CLOSE_CHANGE_DATE else "15:00:00"
    return f"{day}T{hhmmss}+09:00"


def am_information_cutoff(day: str) -> str:
    return f"{day}{_MORNING_CLOSE_SUFFIX}"


def am_operational_usable_by(day: str) -> str:
    return f"{day}{_OPERATIONAL_USABLE_BY_SUFFIX}"


def am_decision_row_is_visible(
    *,
    available_at: str,
    ingested_at: str,
    as_of: str,
) -> bool:
    """Non-price PIT visibility: availability and acquisition both <= cutoff."""

    if not available_at or not ingested_at or not as_of:
        return False
    return available_at <= as_of and ingested_at <= as_of


def am_product_row_is_admitted(
    *,
    available_at: str,
    ingested_at: str,
    session_date: str,
) -> bool:
    """Official AM product operational admission: clocks may be after 11:30.

    Event/session close remains D 11:30. Acquisition may be after 11:30 and
    must be authenticated and <= D 12:30. Noon acquisition is not relabeled
    as 11:30 availability.
    """

    if not available_at or not ingested_at or len(session_date) != 10:
        return False
    cutoff = am_information_cutoff(session_date)
    deadline = am_operational_usable_by(session_date)
    return (
        cutoff <= available_at <= deadline
        and cutoff <= ingested_at <= deadline
    )


def am_product_row_matches_session(
    *,
    event_time: str,
    available_at: str,
    ingested_at: str,
    session_date: str,
) -> bool:
    """Require the exact AM event clock and its same-day acquisition window."""

    return (
        event_time == am_information_cutoff(session_date)
        and am_product_row_is_admitted(
            available_at=available_at,
            ingested_at=ingested_at,
            session_date=session_date,
        )
    )


def _physical_sqlite_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _sqlite_file_identity(path: Path) -> tuple[int, ...]:
    metadata = path.stat()
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _reject_wal_sidecar(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            raise SnapshotObservationClockError(
                "pinned snapshot has WAL/SHM sidecars"
            )


def _open_immutable_readonly(path: Path) -> sqlite3.Connection:
    _reject_wal_sidecar(path)
    if path.is_symlink():
        raise SnapshotObservationClockError("pinned snapshot path is a symlink")
    resolved = path.resolve()
    if not resolved.is_file():
        raise SnapshotObservationClockError("pinned snapshot is missing")
    uri = "file:" + quote(str(resolved)) + "?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("SELECT 1")
    except sqlite3.Error as exc:
        conn.close()
        raise SnapshotObservationClockError(
            "pinned snapshot cannot be opened read-only"
        ) from exc
    return conn


def _observed_through_from_connection(conn: sqlite3.Connection) -> str:
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "snapshot_observation_clock" not in tables:
        raise SnapshotObservationClockError("snapshot observation clock is missing")
    rows = conn.execute(
        "SELECT observed_through FROM snapshot_observation_clock"
    ).fetchall()
    if len(rows) != 1:
        raise SnapshotObservationClockError(
            "snapshot observation clock is not a singleton"
        )
    text = str(rows[0][0] or "")
    canonical = normalize_as_of(text)
    if text != canonical:
        raise SnapshotObservationClockError(
            "snapshot observation clock is noncanonical"
        )
    return canonical


def _load_sealed_products(
    conn: Any, *, dataset_id: str
) -> tuple[set[tuple[str, ...]], list[dict[str, str]], set[str]]:
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "receipt_product_materializations" not in tables:
        return set(), [], set()
    columns = {
        str(item[1])
        for item in conn.execute("PRAGMA table_info(receipt_product_materializations)")
    }
    required = {"dataset", "artifact_digest", "artifact_body"}
    if not required <= columns:
        return set(), [], set()
    sealed: set[tuple[str, ...]] = set()
    product_rows: list[dict[str, str]] = []
    artifact_digests: set[str] = set()
    products = conn.execute(
        "SELECT artifact_digest, artifact_body FROM receipt_product_materializations "
        "WHERE source='jquants' AND dataset=?",
        (dataset_id,),
    ).fetchall()
    for product in products:
        digest = str(product["artifact_digest"] or "")
        body = product["artifact_body"]
        if type(body) is not str or not body:
            continue
        try:
            if product_artifact_body_digest(body) != digest:
                continue
        except ValueError:
            continue
        artifact_digests.add(digest)
        for line in body.splitlines():
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(parsed, dict):
                continue
            if any(field not in parsed for field in PRODUCT_ARTIFACT_FIELDS):
                continue
            if any(type(parsed[field]) is not str for field in PRODUCT_ARTIFACT_FIELDS):
                continue
            if (
                parsed["source"] != "jquants"
                or parsed["dataset"] != dataset_id
            ):
                continue
            sealed.add(tuple(parsed[field] for field in PRODUCT_ARTIFACT_FIELDS))
            product_rows.append({field: parsed[field] for field in PRODUCT_ARTIFACT_FIELDS})
    return sealed, product_rows, artifact_digests


def _load_sealed_am_products(
    conn: Any,
) -> tuple[set[tuple[str, ...]], list[dict[str, str]], set[str]]:
    return _load_sealed_products(conn, dataset_id=GOVERNED_AM_DATASET_ID)


def _load_authorized_am_rows(
    conn: Any,
    *,
    observed_through: str,
    sealed: set[tuple[str, ...]],
) -> tuple[tuple[MappingProxyType, ...], tuple[tuple[str, str], ...]]:
    if not sealed:
        return (), ()
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "jquants_records" not in tables:
        return (), ()
    rows = conn.execute(
        "SELECT source, dataset, natural_key, event_time, available_at, "
        "ingested_at, payload, raw_payload FROM jquants_records "
        "WHERE source='jquants' AND dataset=? "
        "ORDER BY event_time, natural_key",
        (GOVERNED_AM_DATASET_ID,),
    ).fetchall()
    authorized: list[MappingProxyType] = []
    unauthorized: list[tuple[str, str]] = []
    for raw in rows:
        ingested_at = str(raw["ingested_at"] or "")
        available_at = str(raw["available_at"] or "")
        event_time = str(raw["event_time"] or "")
        if (
            not ingested_at
            or not available_at
            or ingested_at > observed_through
            or available_at > observed_through
        ):
            continue
        payload = _decode_payload(raw["payload"])
        day = str(payload.get("Date") or payload.get("date") or "")[:10]
        if len(day) != 10:
            continue
        expected_event = am_information_cutoff(day)
        if not am_product_row_matches_session(
            event_time=event_time,
            available_at=available_at,
            ingested_at=ingested_at,
            session_date=day,
        ):
            continue
        morning = _am_payload_price(payload)
        if morning is None:
            continue
        payload_text = _canonical_payload_text(raw["payload"])
        raw_payload = raw["raw_payload"]
        raw_text = raw_payload if type(raw_payload) is str else ""
        candidate = (
            str(raw["source"] or ""),
            str(raw["dataset"] or ""),
            str(raw["natural_key"] or ""),
            event_time,
            available_at,
            ingested_at,
            payload_text,
            raw_text,
        )
        code = str(payload.get("Code") or payload.get("code") or "")
        if candidate not in sealed:
            if code:
                unauthorized.append((code, day))
            continue
        declared = str(payload.get("am_row_identity") or "")
        if declared:
            live_identity = _row_identity_for_corruption_check(
                {**dict(raw), "payload": payload}
            )
            if declared != live_identity:
                if code:
                    unauthorized.append((code, day))
                continue
        if not code:
            continue
        authorized.append(
            MappingProxyType(
                {
                    "code": code,
                    "date": day,
                    "close": morning,
                    "available_at": available_at,
                    "ingested_at": ingested_at,
                    "event_time": event_time,
                    "information_cutoff": expected_event,
                    "operational_usable_by": am_operational_usable_by(day),
                    "row_identity": _row_identity_for_corruption_check(
                        {**dict(raw), "payload": payload}
                    ),
                }
            )
        )
    return tuple(authorized), tuple(unauthorized)


def _verified_session_scope_fields(source: Any) -> dict[str, dict[str, Any]]:
    if isinstance(source, Mapping):
        entries = source.get("entries")
        if not isinstance(entries, list):
            raise SnapshotObservationClockError(
                "verified session product binding is missing from the Worker job"
            )
        result: dict[str, dict[str, Any]] = {}
        for dataset_id in (GOVERNED_DAILY_DATASET_ID, GOVERNED_AM_DATASET_ID):
            matching = [
                entry
                for entry in entries
                if isinstance(entry, Mapping)
                and str(entry.get("dataset_id") or "") == dataset_id
            ]
            if len(matching) != 1:
                raise SnapshotObservationClockError(
                    f"verified session binding does not include {dataset_id}"
                )
            entry = matching[0]
            result[dataset_id] = _verified_am_product_fields(
                product_artifact_digests=entry.get("product_artifact_digests"),
                natural_key_digest=entry.get("natural_key_digest"),
                natural_key_count=entry.get("natural_key_count"),
            )
        return result
    raise SnapshotObservationClockError(
        "verified session product binding is missing from the Worker job"
    )


def _verified_am_scope_fields(source: Any) -> dict[str, Any]:
    """Compatibility helper for tests; never mints a production handle."""

    return _verified_session_scope_fields(source)[GOVERNED_AM_DATASET_ID]


@dataclass(frozen=True, slots=True)
class _VerifiedControlledSessionScope:
    _token: object
    ready_manifest_digest: str
    signed_projection_document_digest: str
    profile_digest: str
    dependency_scope_proof_digest: str
    observed_through: str
    entries: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        if self._token is not _SESSION_SCOPE_TOKEN:
            raise TypeError("controlled session scope is an opaque Worker capability")


def _session_scope_from_verified_worker_job(
    *,
    session_scope: Any,
    ready_manifest_digest: Any,
    signed_projection_document_digest: Any,
    profile_digest: Any,
) -> _VerifiedControlledSessionScope:
    """Convert the already-verified Worker job scope into an opaque capability.

    The signed projection and READY envelope are verified by the Worker before
    this job exists. Embedded SQLite manifests are deliberately not accepted as
    authority here; they are reconciled separately by the container.
    """

    if not isinstance(session_scope, Mapping) or set(session_scope) != {
        "format",
        "dependency_scope_proof_digest",
        "observed_through",
        "entries",
    }:
        raise SnapshotObservationClockError("controlled session scope is not closed")
    if session_scope.get("format") != "controlled-session-scope/v1":
        raise SnapshotObservationClockError("controlled session scope format is invalid")
    for value, name in (
        (ready_manifest_digest, "ReadyManifest"),
        (signed_projection_document_digest, "signed projection"),
        (profile_digest, "profile"),
        (session_scope.get("dependency_scope_proof_digest"), "dependency scope"),
    ):
        if type(value) is not str or len(value) != 71 or not value.startswith("sha256:"):
            raise SnapshotObservationClockError(f"{name} digest is invalid")
    observed = session_scope.get("observed_through")
    if type(observed) is not str or normalize_as_of(observed) != observed:
        raise SnapshotObservationClockError("controlled session clock is noncanonical")
    bindings = _verified_session_scope_fields(session_scope)
    raw_entries = session_scope.get("entries")
    assert isinstance(raw_entries, list)
    if [str(entry.get("dataset_id") or "") for entry in raw_entries if isinstance(entry, Mapping)] != [
        GOVERNED_DAILY_DATASET_ID,
        GOVERNED_AM_DATASET_ID,
    ]:
        raise SnapshotObservationClockError("controlled session datasets are reordered")
    for entry in raw_entries:
        if not isinstance(entry, Mapping) or set(entry) != {
            "dataset_id",
            "natural_key_count",
            "natural_key_digest",
            "product_artifact_digests",
            "product_artifact_set_digest",
        }:
            raise SnapshotObservationClockError("controlled session entry is not closed")
        products = entry.get("product_artifact_digests")
        if not isinstance(products, list) or products != sorted(set(products)):
            raise SnapshotObservationClockError("controlled product digests are not canonical")
        encoded = json.dumps(products, sort_keys=True, separators=(",", ":"))
        actual_set_digest = "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        if entry.get("product_artifact_set_digest") != actual_set_digest:
            raise SnapshotObservationClockError("controlled product digest set is invalid")
    return _VerifiedControlledSessionScope(
        _token=_SESSION_SCOPE_TOKEN,
        ready_manifest_digest=str(ready_manifest_digest),
        signed_projection_document_digest=str(signed_projection_document_digest),
        profile_digest=str(profile_digest),
        dependency_scope_proof_digest=str(session_scope["dependency_scope_proof_digest"]),
        observed_through=observed,
        entries=MappingProxyType(
            {key: MappingProxyType(dict(value)) for key, value in bindings.items()}
        ),
    )


def _reconcile_embedded_ready_manifest(
    conn: sqlite3.Connection,
    verified_scope: _VerifiedControlledSessionScope,
) -> None:
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "local_snapshot_manifests" not in tables:
        raise SnapshotObservationClockError("verified snapshot manifest is missing")
    rows = conn.execute("SELECT manifest_json FROM local_snapshot_manifests").fetchall()
    if len(rows) != 1 or not rows[0][0]:
        raise SnapshotObservationClockError(
            "verified snapshot manifest is not a singleton"
        )
    try:
        manifest = json.loads(str(rows[0][0]))
    except (TypeError, ValueError) as exc:
        raise SnapshotObservationClockError(
            "verified snapshot manifest is malformed"
        ) from exc
    if not isinstance(manifest, dict) or not isinstance(
        manifest.get("ready_manifest"), dict
    ):
        raise SnapshotObservationClockError("embedded ReadyManifest is missing")
    nested = dict(manifest["ready_manifest"])
    declared_digest = nested.pop("manifest_digest", None)
    encoded = json.dumps(
        nested,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    recomputed = "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    if (
        declared_digest != verified_scope.ready_manifest_digest
        or recomputed != verified_scope.ready_manifest_digest
    ):
        raise SnapshotObservationClockError(
            "embedded ReadyManifest does not match verified Worker scope"
        )
    if nested.get("observed_through") != verified_scope.observed_through:
        raise SnapshotObservationClockError(
            "embedded ReadyManifest observation clock mismatch"
        )
    if nested.get("profile_digest") != verified_scope.profile_digest:
        raise SnapshotObservationClockError(
            "embedded ReadyManifest profile mismatch"
        )
    pit_contracts = nested.get("pit_contract_digests")
    if not isinstance(pit_contracts, dict) or pit_contracts.get(
        "dependency_scope"
    ) != verified_scope.dependency_scope_proof_digest:
        raise SnapshotObservationClockError(
            "embedded dependency scope does not match verified Worker scope"
        )
    embedded_scope = manifest.get("dependency_scope_evidence")
    if not isinstance(embedded_scope, dict) or embedded_scope.get(
        "proof_digest"
    ) != verified_scope.dependency_scope_proof_digest:
        raise SnapshotObservationClockError(
            "embedded dependency proof does not match verified Worker scope"
        )


def _verified_am_product_fields(
    *,
    product_artifact_digests: Any,
    natural_key_digest: Any,
    natural_key_count: Any,
) -> dict[str, Any]:
    if not isinstance(product_artifact_digests, (tuple, list)) or not product_artifact_digests:
        raise SnapshotObservationClockError(
            "signed AM product digest is missing from readiness/job proof"
        )
    if any(
        type(item) is not str or not item.startswith("sha256:")
        for item in product_artifact_digests
    ):
        raise SnapshotObservationClockError("signed AM product digest is malformed")
    if type(natural_key_digest) is not str or not natural_key_digest.startswith("sha256:"):
        raise SnapshotObservationClockError("signed AM natural-key digest is missing")
    if type(natural_key_count) is not int or natural_key_count < 1:
        raise SnapshotObservationClockError("signed AM natural-key count is missing")
    return {
        "product_artifact_digests": tuple(str(item) for item in product_artifact_digests),
        "natural_key_digest": natural_key_digest,
        "natural_key_count": natural_key_count,
    }


@dataclass(frozen=True, slots=True)
class OfflineFixtureAmSessionDataView:
    """Explicit fixture/Draft AM scope. Never authentic or Controlled-eligible."""

    _token: object
    observed_through: str
    _authorized: tuple[MappingProxyType, ...] = ()
    _unauthorized: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self._token is not _OFFLINE_FIXTURE_AM_VIEW_TOKEN:
            raise TypeError(
                "OfflineFixtureAmSessionDataView can only be minted as fixture scope"
            )

    @property
    def offline_fixture(self) -> bool:
        return True

    def authorized_rows(self, **_kwargs: Any) -> tuple[MappingProxyType, ...]:
        return ()

    def unauthorized_dates(self, **_kwargs: Any) -> dict[str, list[str]]:
        return {}

    def pm_fill_closes(self, **_kwargs: Any) -> dict[str, float]:
        return {}

    def engine_read_scope(self) -> Any:
        raise TypeError("fixture AM view cannot enter the Controlled path")


class VerifiedControlledSnapshotHandle:
    """One-shot pinned read-only snapshot. Owns the only Controlled connection."""

    def __init__(
        self,
        *,
        token: object,
        connection: sqlite3.Connection,
        observed_through: str,
        authorized: tuple[MappingProxyType, ...],
        unauthorized: tuple[tuple[str, str], ...],
        sealed_daily: set[tuple[str, ...]],
        physical_digest: str,
        file_identity: tuple[int, ...],
        pinned_path: str,
    ) -> None:
        if token is not _HANDLE_TOKEN:
            raise TypeError(
                "VerifiedControlledSnapshotHandle can only be minted by the "
                "closed snapshot verifier"
            )
        self._connection = connection
        self._observed_through = observed_through
        self._authorized = authorized
        self._unauthorized = unauthorized
        self._sealed_daily = frozenset(sealed_daily)
        self._physical_digest = physical_digest
        self._file_identity = file_identity
        self._pinned_path = pinned_path
        self._closed = False
        self._consumed = False
        self._view: GovernedAmSessionDataView | None = None
        self._scope_cm: Any = None
        self._batch_active = False

    @property
    def offline_fixture(self) -> bool:
        return False

    @property
    def observed_through(self) -> str:
        return self._observed_through

    @property
    def physical_digest(self) -> str:
        return self._physical_digest

    @property
    def pinned_db_path(self) -> Path:
        return Path(self._pinned_path)

    def _assert_controlled_batch(self) -> Path:
        path = self.assert_live()
        if not self._batch_active or not self._connection.in_transaction:
            raise SnapshotObservationClockError(
                "controlled snapshot transaction is not active"
            )
        return path

    def logical_snapshot_id(self) -> str:
        """Derive the logical identity on this handle's pinned transaction."""

        path = self._assert_controlled_batch()
        from paper_runtime.snapshot_identity import (
            _immutable_data_snapshot_id_from_pinned_connection,
        )

        return _immutable_data_snapshot_id_from_pinned_connection(
            self._connection,
            path=path,
        )

    def resolve_controlled_universe(
        self,
        *,
        period_start: str,
        period_end: str,
    ) -> Any:
        """Resolve PIT membership without exposing or reopening a DB path."""

        self._assert_controlled_batch()
        from research.universe_contract import (
            _resolve_tse_prime_with_fins_from_pinned_connection,
        )

        return _resolve_tse_prime_with_fins_from_pinned_connection(
            self._connection,
            period_start=period_start,
            period_end=period_end,
            observed_through=self._observed_through,
        )

    def am_session_data_view(self) -> "GovernedAmSessionDataView":
        self._assert_open()
        if self._view is None:
            self._view = GovernedAmSessionDataView(
                _token=_GOVERNED_AM_VIEW_TOKEN,
                observed_through=self._observed_through,
                _authorized=self._authorized,
                _unauthorized=self._unauthorized,
                _handle=self,
            )
        return self._view

    def _assert_open(self) -> None:
        if self._closed:
            raise SnapshotObservationClockError(
                "pinned snapshot handle is closed"
            )

    def assert_live(self) -> Path:
        self._assert_open()
        path = Path(self._pinned_path)
        if path.is_symlink():
            raise SnapshotObservationClockError("pinned snapshot path is a symlink")
        if not path.is_file():
            raise SnapshotObservationClockError("pinned snapshot is missing")
        resolved = str(path.resolve())
        if resolved != self._pinned_path:
            raise SnapshotObservationClockError("pinned snapshot connection was swapped")
        _reject_wal_sidecar(path)
        live_identity = _sqlite_file_identity(path)
        if live_identity != self._file_identity:
            raise SnapshotObservationClockError("pinned snapshot was replaced")
        try:
            self._connection.execute("SELECT 1")
        except sqlite3.Error as exc:
            raise SnapshotObservationClockError(
                "pinned snapshot connection is unusable"
            ) from exc
        return path

    def authorized_rows(
        self,
        *,
        as_of: str,
        codes: set[str],
        from_date: str,
        to_date: str,
        db_path: Any = None,
    ) -> tuple[MappingProxyType, ...]:
        if db_path is not None:
            raise SnapshotObservationClockError(
                "Controlled AM reads cannot reopen a pathname"
            )
        self.assert_live()
        decision_as_of = normalize_as_of(as_of)
        if decision_as_of > am_operational_usable_by(to_date):
            raise SnapshotObservationClockError(
                "AM decision read is after the 12:30 operational deadline"
            )
        visible: list[MappingProxyType] = []
        for row in self._authorized:
            if str(row["code"]) not in codes:
                continue
            day = str(row["date"])
            if day < from_date or day > to_date:
                continue
            if not am_product_row_matches_session(
                event_time=str(row["event_time"]),
                available_at=str(row["available_at"]),
                ingested_at=str(row["ingested_at"]),
                session_date=day,
            ):
                continue
            if str(row["available_at"]) > decision_as_of or str(row["ingested_at"]) > decision_as_of:
                continue
            visible.append(row)
        return tuple(visible)

    def unauthorized_dates(
        self, *, codes: set[str], from_date: str, to_date: str
    ) -> dict[str, list[str]]:
        self.assert_live()
        found: dict[str, list[str]] = {code: [] for code in codes}
        for code, day in self._unauthorized:
            if code not in found:
                continue
            if day < from_date or day > to_date:
                continue
            found[code].append(day)
        return found

    def pm_fill_closes(self, *, session_date: str, codes: set[str]) -> dict[str, float]:
        """Official same-day afternoon close from this pinned connection only."""

        self.assert_live()
        if not codes:
            return {}
        expected_event = official_afternoon_close_as_of(session_date)
        prices: dict[str, float] = {}
        conn = self._connection
        rows = conn.execute(
            "SELECT source, dataset, natural_key, event_time, available_at, "
            "ingested_at, payload, raw_payload FROM jquants_records "
            "WHERE source='jquants' AND dataset=? AND substr(event_time,1,10)=?",
            (GOVERNED_DAILY_DATASET_ID, session_date),
        ).fetchall()
        for row in rows:
            event_time = str(row["event_time"] or "")
            available_at = str(row["available_at"] or "")
            ingested_at = str(row["ingested_at"] or "")
            if event_time != expected_event or not available_at or not ingested_at:
                continue
            if available_at > self._observed_through or ingested_at > self._observed_through:
                continue
            payload = _decode_payload(row["payload"])
            code = str(payload.get("Code") or payload.get("code") or "")
            if code not in codes:
                continue
            candidate = (
                str(row["source"] or ""),
                str(row["dataset"] or ""),
                str(row["natural_key"] or ""),
                event_time,
                available_at,
                ingested_at,
                _canonical_payload_text(row["payload"]),
                row["raw_payload"] if type(row["raw_payload"]) is str else "",
            )
            if candidate not in self._sealed_daily:
                continue
            price = _pm_payload_price(payload)
            if price is not None:
                prices[code] = price
        return prices

    def bind_engine_reads(self) -> None:
        self.assert_live()
        if self._batch_active:
            if self._scope_cm is None:
                raise SnapshotObservationClockError(
                    "controlled batch read binding is missing"
                )
            return
        if self._consumed or self._scope_cm is not None:
            raise SnapshotObservationClockError(
                "pinned snapshot handle cannot be reused"
            )
        if not self._connection.in_transaction:
            raise SnapshotObservationClockError(
                "controlled snapshot transaction is not active"
            )
        self._consumed = True
        self._scope_cm = bind_external_readonly_connection(
            self._pinned_path,
            self._connection,
            identity_check=self.assert_live,
        )
        self._scope_cm.__enter__()

    def release_engine_reads(self) -> None:
        if self._batch_active:
            return
        cm = self._scope_cm
        self._scope_cm = None
        if cm is not None:
            cm.__exit__(None, None, None)

    def _begin_controlled_batch_reads(self) -> None:
        self.assert_live()
        if self._consumed or self._scope_cm is not None or self._batch_active:
            raise SnapshotObservationClockError(
                "pinned snapshot handle cannot be reused"
            )
        self._consumed = True
        self._batch_active = True
        try:
            if not self._connection.in_transaction:
                raise SnapshotObservationClockError(
                    "controlled snapshot transaction is not active"
                )
            self._scope_cm = bind_external_readonly_connection(
                self._pinned_path,
                self._connection,
                identity_check=self.assert_live,
            )
            self._scope_cm.__enter__()
        except Exception:
            try:
                self._connection.rollback()
            except sqlite3.Error:
                pass
            self._scope_cm = None
            self._batch_active = False
            raise

    def _end_controlled_batch_reads(self) -> None:
        if not self._batch_active:
            return
        self._batch_active = False
        self.release_engine_reads()

    @contextmanager
    def engine_read_scope(self) -> Iterator[None]:
        self.bind_engine_reads()
        try:
            yield
        finally:
            self.release_engine_reads()

    def close(self) -> None:
        if self._closed:
            raise SnapshotObservationClockError(
                "pinned snapshot handle is closed"
            )
        self._closed = True
        self._batch_active = False
        self.release_engine_reads()
        try:
            self._connection.close()
        except sqlite3.Error:
            pass


@dataclass(frozen=True, slots=True)
class GovernedAmSessionDataView:
    """Opaque verified production AM data-view. Reconstructing it from public rows fails."""

    _token: object
    observed_through: str
    _authorized: tuple[MappingProxyType, ...]
    _unauthorized: tuple[tuple[str, str], ...]
    _handle: VerifiedControlledSnapshotHandle

    def __post_init__(self) -> None:
        if self._token is not _GOVERNED_AM_VIEW_TOKEN:
            raise TypeError(
                "GovernedAmSessionDataView can only be minted by the closed "
                "snapshot verifier"
            )
        if type(self._handle) is not VerifiedControlledSnapshotHandle:
            raise TypeError("production AM view requires a pinned snapshot handle")
        if self.offline_fixture:
            raise TypeError("production AM view cannot be fixture scope")

    @property
    def offline_fixture(self) -> bool:
        return False

    @property
    def physical_digest(self) -> str:
        return self._handle.physical_digest

    @property
    def pinned_db_path(self) -> Path:
        return self._handle.pinned_db_path

    def assert_pinned_artifact(self, db_path: Any = None) -> Path:
        if db_path is not None:
            resolved = str(resolve_db_path(db_path).resolve())
            if resolved != str(self._handle.pinned_db_path):
                raise SnapshotObservationClockError(
                    "pinned snapshot connection was swapped"
                )
        return self._handle.assert_live()

    def authorized_rows(
        self,
        *,
        as_of: str,
        codes: set[str],
        from_date: str,
        to_date: str,
        db_path: Any = None,
    ) -> tuple[MappingProxyType, ...]:
        return self._handle.authorized_rows(
            as_of=as_of,
            codes=codes,
            from_date=from_date,
            to_date=to_date,
            db_path=db_path,
        )

    def unauthorized_dates(
        self, *, codes: set[str], from_date: str, to_date: str
    ) -> dict[str, list[str]]:
        return self._handle.unauthorized_dates(
            codes=codes, from_date=from_date, to_date=to_date
        )

    def pm_fill_closes(self, *, session_date: str, codes: set[str]) -> dict[str, float]:
        return self._handle.pm_fill_closes(session_date=session_date, codes=codes)

    def bind_engine_reads(self) -> None:
        self._handle.bind_engine_reads()

    def release_engine_reads(self) -> None:
        self._handle.release_engine_reads()

    def engine_read_scope(self) -> Any:
        return self._handle.engine_read_scope()


def mint_offline_fixture_am_session_data_view(
    *, observed_through: str = ""
) -> OfflineFixtureAmSessionDataView:
    """Fixture/Draft capability. Always ineligible; cannot enter Controlled."""

    clock = observed_through or ""
    return OfflineFixtureAmSessionDataView(
        _token=_OFFLINE_FIXTURE_AM_VIEW_TOKEN,
        observed_through=clock,
    )


def assemble_governed_am_session_data_view(*_args: Any, **_kwargs: Any) -> Any:
    """Removed public assembler. Path/digest/mapping cannot mint production."""

    raise SnapshotObservationClockError(
        "production AM view cannot be minted from path, digest, or mapping"
    )


def _open_verified_controlled_snapshot(
    *,
    pinned_path: Any,
    verified_physical_digest: str,
    verified_session_scope: _VerifiedControlledSessionScope,
) -> VerifiedControlledSnapshotHandle:
    """Private one-shot opener. Callers must already have verified READY.

    The physical digest is rehashed from the pinned object. A plain Mapping
    is not accepted. Same-DB catalog rehash is compared to independently
    verified product fields, not treated as the proof itself.
    """

    if type(verified_session_scope) is not _VerifiedControlledSessionScope or isinstance(
        pinned_path, Mapping
    ):
        raise SnapshotObservationClockError(
            "production AM view cannot be minted from path, digest, or mapping"
        )
    if type(verified_physical_digest) is not str or not verified_physical_digest.startswith(
        "sha256:"
    ):
        raise SnapshotObservationClockError("physical snapshot digest is missing")
    expected_clock = verified_session_scope.observed_through
    path = resolve_db_path(pinned_path)
    if path.is_symlink() or not path.is_file():
        raise SnapshotObservationClockError("pinned snapshot is missing")
    resolved = path.resolve()
    live_digest = _physical_sqlite_digest(resolved)
    if live_digest != verified_physical_digest:
        raise SnapshotObservationClockError("physical snapshot digest mismatch")
    identity = _sqlite_file_identity(resolved)
    conn = _open_immutable_readonly(resolved)
    try:
        if _sqlite_file_identity(resolved) != identity:
            raise SnapshotObservationClockError(
                "pinned snapshot was replaced while opening"
            )
        # One immutable transaction spans authority reconciliation, logical
        # identity, universe resolution, AM features, and all PM fills.
        conn.execute("BEGIN")
        observed_through = _observed_through_from_connection(conn)
        if observed_through != expected_clock:
            raise SnapshotObservationClockError(
                "snapshot observation clock does not match manifest"
            )
        _reconcile_embedded_ready_manifest(conn, verified_session_scope)
        sealed_by_dataset: dict[str, set[tuple[str, ...]]] = {}
        for dataset_id in (GOVERNED_DAILY_DATASET_ID, GOVERNED_AM_DATASET_ID):
            binding = verified_session_scope.entries[dataset_id]
            sealed, product_rows, artifact_digests = _load_sealed_products(
                conn, dataset_id=dataset_id
            )
            if not product_rows:
                raise SnapshotObservationClockError(
                    f"sealed {dataset_id} product materialization is missing"
                )
            if artifact_digests != set(binding["product_artifact_digests"]):
                raise SnapshotObservationClockError(
                    f"{dataset_id} product digest set does not match signed PIT dependency scope"
                )
            live_keys = sorted({row["natural_key"] for row in product_rows})
            live_key_digest = "sha256:" + hashlib.sha256(
                json.dumps(live_keys, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if live_key_digest != binding["natural_key_digest"] or len(live_keys) != binding["natural_key_count"]:
                raise SnapshotObservationClockError(
                    f"{dataset_id} natural-key set does not match signed PIT dependency scope"
                )
            sealed_by_dataset[dataset_id] = sealed
        authorized, unauthorized = _load_authorized_am_rows(
            conn,
            observed_through=observed_through,
            sealed=sealed_by_dataset[GOVERNED_AM_DATASET_ID],
        )
        if _sqlite_file_identity(resolved) != identity:
            raise SnapshotObservationClockError(
                "pinned snapshot was replaced during verification"
            )
        return VerifiedControlledSnapshotHandle(
            token=_HANDLE_TOKEN,
            connection=conn,
            observed_through=observed_through,
            authorized=authorized,
            unauthorized=unauthorized,
            sealed_daily=sealed_by_dataset[GOVERNED_DAILY_DATASET_ID],
            physical_digest=verified_physical_digest,
            file_identity=identity,
            pinned_path=str(resolved),
        )
    except Exception:
        conn.close()
        raise


__all__ = [
    "GOVERNED_AM_DATASET_ID",
    "GovernedAmSessionDataView",
    "OfflineFixtureAmSessionDataView",
    "VerifiedControlledSnapshotHandle",
    "am_decision_row_is_visible",
    "am_information_cutoff",
    "am_operational_usable_by",
    "am_product_row_is_admitted",
    "mint_offline_fixture_am_session_data_view",
    "official_afternoon_close_as_of",
]
