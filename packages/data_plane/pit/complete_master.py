"""Private complete-master selection using existing receipt authority.

READY publication and the pinned Controlled handle resolve universe day
slices through this owner, loading persisted official_calendar_raw bodies
from the same owned connection. It does not mint COMPLETE from counts,
booleans, or caller-selected codes.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from data_contracts import coverage_contract_for
from ingestion.jquants.official_business_calendar import (
    derive_official_business_calendar,
)
from ops.receipt_product import (
    PRODUCT_ARTIFACT_FIELDS,
    catalog_owned_product_row_digests,
    iter_product_artifact_body_rows,
    product_artifact_digest_ordered,
    product_row_digest,
    verify_full_segment_product_materialization,
)
from storage.coverage_ledger import CollectionReceipt
from storage.receipt_crypto import (
    PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST,
    PRODUCTION_RECEIPT_ENVIRONMENT,
)
from storage.verified_receipt import (
    VerifiedCollectionClosure,
    require_verified_collection_closure,
)

from .errors import PitError
from .universe_pit import (
    UniverseDaySlice,
    UniverseMasterMember,
    _Event,
    _VersionIdentity,
    _calendar_dates,
    _compact_flag_from_connection,
    _event_from_row,
    _interned_master_members,
    _parse_dt,
    _table_columns,
    _universe_day_slices_from_connection,
)


COMPLETE_MASTER_SELECTION_EVIDENCE = "complete-master-selection-evidence/v1"
_MASTER_DATASET = "equities_master"
_MEASURED_CALENDAR_DIGESTS = (
    "official_calendar_raw_body_digest",
    "official_calendar_query_digest",
    "official_business_dates_digest",
    "official_calendar_binding_digest",
)
_PRODUCT_REQUIRED = {
    "operation_id",
    "run_id",
    "source",
    "dataset",
    "segment_id",
    "artifact_key",
    "artifact_digest",
    "artifact_body",
    "row_count",
    "byte_count",
    "manifest_key",
    "manifest_digest",
    "raw_manifest_key",
    "raw_manifest_digest",
    "raw_page_count",
    "raw_row_count",
    "raw_bytes",
    "committed_at",
}


def _row_mapping(raw: Any) -> dict[str, Any]:
    return {str(key): raw[key] for key in raw.keys()}


def _collection_receipt_from_row(raw: Mapping[str, Any]) -> CollectionReceipt:
    expected_scope = json.loads(str(raw["expected_scope"]))
    digests = json.loads(str(raw["digests_json"]))
    return CollectionReceipt(
        source=str(raw["source"]),
        dataset=str(raw["dataset"]),
        segment_id=str(raw["segment_id"]),
        segment_start=str(raw["segment_start"]),
        segment_end=str(raw["segment_end"]),
        expected_scope=expected_scope,
        expected_items=(
            None if raw["expected_items"] is None else int(raw["expected_items"])
        ),
        observed_items=int(raw["observed_items"]),
        raw_page_count=int(raw["raw_page_count"]),
        raw_row_count=int(raw["raw_row_count"]),
        structured_row_count=int(raw["structured_row_count"]),
        pagination_exhausted=bool(raw["pagination_exhausted"]),
        digests=digests,
        run_id=int(raw["run_id"]),
        status=str(raw["status"]),
        error=None if raw["error"] is None else str(raw["error"]),
        checked_at=str(raw["checked_at"]),
    )


def _product_row_from_event(event: _Event) -> dict[str, str]:
    row = {
        "source": event.identity[0],
        "dataset": event.identity[1],
        "natural_key": event.identity[2],
        "event_time": event.event_time_text,
        "available_at": event.available_at_text,
        "ingested_at": event.ingested_at_text,
        "payload": event.payload_text,
        "raw_payload": event.raw_payload_text,
    }
    if any(type(value) is not str for value in row.values()) or any(
        not row[field]
        for field in (
            "source",
            "dataset",
            "natural_key",
            "event_time",
            "available_at",
            "ingested_at",
            "payload",
        )
    ):
        raise PitError(
            "equities_master selected version is missing exact product fields"
        )
    return row


def _version_identity_from_product(row: Mapping[str, str]) -> _VersionIdentity:
    return (row["source"], row["dataset"], row["natural_key"])


def _raw_calendar_digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _index_calendar_bodies(value: Sequence[bytes]) -> dict[str, bytes]:
    """Index untrusted official calendar bytes by signed raw-body digest."""

    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PitError(
            "official calendar raw bodies must be the exact signed calendar artifacts"
        )
    if not value or any(type(item) is not bytes or not item for item in value):
        raise PitError(
            "official calendar raw body is missing; complete master remains inactive"
        )
    indexed: dict[str, bytes] = {}
    for body in value:
        digest = _raw_calendar_digest(body)
        previous = indexed.get(digest)
        if previous is not None and previous != body:
            raise PitError("official calendar raw body digest is duplicated")
        indexed[digest] = body
    return indexed


def _segment_intersects(start: str, end: str, *, seed: str, period_end: str) -> bool:
    return not (end < seed or start > period_end)


@dataclass(frozen=True, slots=True)
class _CompactVersion:
    identity: _VersionIdentity
    activation: datetime
    ingested: datetime
    version_digest: str


@dataclass(frozen=True, slots=True)
class _GenerationSnapshot:
    identities: frozenset[_VersionIdentity]
    versions: Mapping[_VersionIdentity, _CompactVersion]


@dataclass(frozen=True, slots=True)
class _VerifiedGeneration:
    closure: VerifiedCollectionClosure
    segment_start: str
    segment_end: str
    business_dates: tuple[str, ...]
    business_dates_digest: str
    snapshots: Mapping[str, _GenerationSnapshot]


def _version_visible(
    version: _CompactVersion, *, as_of: datetime, observed_through: datetime
) -> bool:
    return version.activation <= as_of and version.ingested <= observed_through


def _snapshot_visibility(
    snapshot: _GenerationSnapshot,
    *,
    as_of: datetime,
    observed_through: datetime,
) -> str:
    visible = 0
    for version in snapshot.versions.values():
        if _version_visible(
            version, as_of=as_of, observed_through=observed_through
        ):
            visible += 1
    if visible == 0:
        return "none"
    if visible == len(snapshot.identities):
        return "full"
    return "partial"


class _CompleteMembershipGate:
    """Bind one complete candidate set from verified artifacts. Not mintable."""

    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        official_calendars: Mapping[str, bytes] | None,
        period_end: str,
        observed_through: datetime,
        observed_through_text: str,
    ) -> None:
        self._conn = conn
        self._official_calendars = official_calendars
        self._period_end = period_end
        self._observed_through = observed_through
        self._observed_through_text = observed_through_text
        self._seed_snapshot_date: str | None = None
        self._generations: tuple[_VerifiedGeneration, ...] = ()

    @property
    def seed_snapshot_date(self) -> str:
        if self._seed_snapshot_date is None:
            raise PitError("complete master seed snapshot is missing")
        return self._seed_snapshot_date

    @property
    def generations(self) -> tuple[_VerifiedGeneration, ...]:
        return self._generations

    def _bind_selected_version(self, event: _Event) -> None:
        digest = product_row_digest(_product_row_from_event(event))
        for generation in self._generations:
            snapshot = generation.snapshots.get(event.snapshot_date)
            if snapshot is None:
                continue
            held = snapshot.versions.get(event.identity)
            if held is not None and held.version_digest == digest:
                return
        raise PitError(
            "selected equities_master version is not bound to a verified artifact: "
            f"{event.identity[2]}"
        )

    def _assert_source_domain(self, *, seed: str) -> None:
        segments = [
            (generation.segment_start, generation.segment_end)
            for generation in self._generations
        ]
        missing_dates = [
            day
            for day in _calendar_dates(seed, self._period_end)
            if not any(start <= day <= end for start, end in segments)
        ]
        if missing_dates:
            raise PitError(
                "official master segment does not cover source date "
                f"{missing_dates[0]}; complete master remains inactive"
            )
        covered_snapshots = {
            snapshot_date
            for generation in self._generations
            for snapshot_date, snapshot in generation.snapshots.items()
            if snapshot.identities
        }
        seen_business: set[str] = set()
        business_dates: list[str] = []
        for generation in self._generations:
            for day in generation.business_dates:
                if seed <= day <= self._period_end and day not in seen_business:
                    seen_business.add(day)
                    business_dates.append(day)
        missing_snapshots = [
            day for day in business_dates if day not in covered_snapshots
        ]
        if missing_snapshots:
            raise PitError(
                "official business date is missing a complete master snapshot: "
                + ",".join(missing_snapshots[:5])
            )

    def _require_unique_complete_identities(
        self,
        *,
        snapshot_date: str,
        as_of: datetime,
        selected: Mapping[_VersionIdentity, _Event],
    ) -> frozenset[_VersionIdentity]:
        covering = [
            generation
            for generation in self._generations
            if snapshot_date in generation.snapshots
            and generation.snapshots[snapshot_date].identities
        ]
        if not covering:
            raise PitError(
                f"equities_master snapshot {snapshot_date} has no verified complete artifact"
            )
        selected_ids = frozenset(selected)
        full: list[_VerifiedGeneration] = []
        partial: list[_VerifiedGeneration] = []
        for generation in covering:
            visibility = _snapshot_visibility(
                generation.snapshots[snapshot_date],
                as_of=as_of,
                observed_through=self._observed_through,
            )
            if visibility == "partial":
                partial.append(generation)
            elif visibility == "full":
                full.append(generation)
        if not full:
            raise PitError(
                f"equities_master snapshot {snapshot_date} is only partially PIT-visible"
                if partial
                else (
                    f"equities_master snapshot {snapshot_date} has no "
                    "PIT-visible complete artifact"
                )
            )
        keysets = {
            generation.snapshots[snapshot_date].identities for generation in full
        }
        if len(keysets) != 1:
            raise PitError(
                f"equities_master snapshot {snapshot_date} has ambiguous complete generations"
            )
        unique = next(iter(keysets))
        for generation in partial:
            if generation.snapshots[snapshot_date].identities != unique:
                raise PitError(
                    f"equities_master snapshot {snapshot_date} is only partially PIT-visible"
                )
        if selected_ids != unique:
            missing = sorted(identity[2] for identity in unique - selected_ids)
            if missing:
                raise PitError(
                    "equities_master snapshot "
                    f"{snapshot_date} is only partially PIT-visible; missing={missing[:5]}"
                )
            raise PitError(
                f"equities_master snapshot {snapshot_date} has ambiguous complete generations"
            )
        return unique

    def resolve(
        self,
        *,
        decision_date: str,
        as_of: datetime,
        current_snapshot: str,
        current_members: Mapping[_VersionIdentity, _Event],
        master_latest: Mapping[_VersionIdentity, _Event],
        intern: dict[tuple[str, str, str], UniverseMasterMember],
    ) -> tuple[UniverseMasterMember, ...]:
        del master_latest
        if not current_snapshot or not current_members:
            raise PitError(
                f"equities_master has no PIT-visible snapshot for {decision_date}"
            )
        if self._seed_snapshot_date is None:
            self._seed_snapshot_date = current_snapshot
            self._generations = _load_required_master_generations(
                self._conn,
                official_calendars=self._official_calendars,
                observed_through=self._observed_through_text,
                seed=current_snapshot,
                period_end=self._period_end,
            )
            self._assert_source_domain(seed=current_snapshot)
        elif current_snapshot < self._seed_snapshot_date:
            raise PitError(
                f"equities_master snapshot {current_snapshot} precedes the complete seed"
            )
        selected = {
            identity: event
            for identity, event in current_members.items()
            if event.snapshot_date == current_snapshot
        }
        self._require_unique_complete_identities(
            snapshot_date=current_snapshot,
            as_of=as_of,
            selected=selected,
        )
        for event in selected.values():
            self._bind_selected_version(event)
        return _interned_master_members(
            selected.values(),
            snapshot_date=current_snapshot,
            intern=intern,
        )


@dataclass(frozen=True, slots=True)
class CompleteMasterProof:
    """Owner-side complete-master provenance. Not a feature input."""

    format: str
    seed_snapshot_date: str
    receipt_digests: tuple[str, ...]
    official_business_dates_digests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _OwnedCompleteMasterSelection:
    slices: tuple[UniverseDaySlice, ...]
    proof: CompleteMasterProof


def _verify_calendar_against_closure(
    closure: VerifiedCollectionClosure,
    *,
    official_calendar_raw: bytes,
) -> Any:
    extras = closure.extra_digests
    missing = [name for name in _MEASURED_CALENDAR_DIGESTS if name not in extras]
    if missing:
        raise PitError(
            "signed equities_master closure is missing official calendar digest: "
            + ",".join(missing)
        )
    try:
        calendar = derive_official_business_calendar(
            official_calendar_raw,
            segment_start=closure.segment_start[:10],
            segment_end=closure.segment_end[:10],
        )
    except (TypeError, ValueError) as exc:
        raise PitError(
            "official calendar raw body does not derive a bounded business calendar"
        ) from exc
    measured = {
        "official_calendar_raw_body_digest": calendar.raw_body_digest,
        "official_calendar_query_digest": calendar.calendar_query_digest,
        "official_business_dates_digest": calendar.business_dates_digest,
        "official_calendar_binding_digest": calendar.binding_digest,
    }
    mismatched = [
        name for name, digest in measured.items() if extras.get(name) != digest
    ]
    if mismatched:
        raise PitError(
            "measured official calendar digest does not match the signed closure: "
            + ",".join(mismatched)
        )
    return calendar


def _owned_product_row_digests(
    conn: sqlite3.Connection,
    *,
    segment_start: str,
    segment_end: str,
    observed_through: str,
) -> set[str]:
    tables: list[str] = []
    for table in ("jquants_records", "jquants_records_revisions"):
        if not _table_columns(conn, table):
            continue
        if set(PRODUCT_ARTIFACT_FIELDS) - _table_columns(conn, table):
            raise PitError(f"universe requires canonical {table} schema")
        tables.append(table)
    if not tables:
        return set()
    return catalog_owned_product_row_digests(
        conn,
        source="jquants",
        dataset=_MASTER_DATASET,
        segment_start=segment_start,
        segment_end=segment_end,
        observed_through=observed_through,
        tables=tuple(tables),
    )


def _compact_snapshots_from_artifact(
    body: str,
    *,
    owned_digests: set[str],
    retain_start: str,
    retain_end: str,
) -> tuple[int, str, int, dict[str, _GenerationSnapshot]]:
    grouped: dict[str, dict[_VersionIdentity, _CompactVersion]] = {}

    def rows():
        for raw in iter_product_artifact_body_rows(body):
            digest = product_row_digest(raw)
            if digest not in owned_digests:
                raise PitError(
                    "verified equities_master artifact row is not materialized "
                    "on the owner connection"
                )
            event = _event_from_row(raw, insertion=0, dataset=_MASTER_DATASET)
            identity = _version_identity_from_product(raw)
            if identity != event.identity or not event.snapshot_date:
                raise PitError("equities_master artifact row is inconsistent")
            if retain_start <= event.snapshot_date <= retain_end:
                bucket = grouped.setdefault(event.snapshot_date, {})
                if identity in bucket:
                    raise PitError(
                        "equities_master artifact duplicates snapshot identity "
                        f"{identity[2]}"
                    )
                bucket[identity] = _CompactVersion(
                    identity=identity,
                    activation=event.activation,
                    ingested=event.ingested,
                    version_digest=digest,
                )
            yield raw

    observed_count, observed_digest, observed_bytes = (
        product_artifact_digest_ordered(rows())
    )
    snapshots = {
        snapshot_date: _GenerationSnapshot(
            identities=frozenset(versions),
            versions=MappingProxyType(versions),
        )
        for snapshot_date, versions in grouped.items()
    }
    return observed_count, observed_digest, observed_bytes, snapshots


def _iter_success_closures(
    conn: sqlite3.Connection,
) -> tuple[VerifiedCollectionClosure, ...]:
    if not _PRODUCT_REQUIRED <= _table_columns(
        conn, "receipt_product_materializations"
    ):
        raise PitError(
            "receipt_product_materializations is missing required columns"
        )
    if "authority_operation_id" not in _table_columns(conn, "ingestion_run_log"):
        raise PitError("ingestion_run_log.authority_operation_id is missing")
    if not _table_columns(conn, "collection_receipts"):
        raise PitError("collection_receipts is missing")
    receipts = [
        _row_mapping(raw)
        for raw in conn.execute(
            "SELECT * FROM collection_receipts WHERE source='jquants' "
            "AND dataset=? ORDER BY run_id",
            (_MASTER_DATASET,),
        )
    ]
    if not receipts:
        raise PitError(
            "collection_receipts has no equities_master row; complete master remains inactive"
        )
    policy_version = coverage_contract_for(_MASTER_DATASET).policy_version
    closures: list[VerifiedCollectionClosure] = []
    for stored in receipts:
        if str(stored.get("status") or "") != "SUCCESS":
            continue
        try:
            receipt = _collection_receipt_from_row(stored)
            closure = require_verified_collection_closure(
                receipt,
                expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
                expected_authority_instance_digest=(
                    PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
                ),
                expected_policy_version=policy_version,
            )
        except Exception:
            continue
        if type(closure) is not VerifiedCollectionClosure:
            continue
        closures.append(closure)
    return tuple(closures)


def _verify_one_generation(
    conn: sqlite3.Connection,
    closure: VerifiedCollectionClosure,
    *,
    official_calendars: Mapping[str, bytes] | None,
    observed_through: str,
    seed: str,
    period_end: str,
) -> _VerifiedGeneration | None:
    extras = closure.extra_digests
    raw_digest = extras.get("official_calendar_raw_body_digest")
    if type(raw_digest) is not str or not raw_digest:
        raise PitError(
            "signed equities_master closure is missing official calendar digest: "
            "official_calendar_raw_body_digest"
        )
    if official_calendars is None:
        calendar_raw = _official_calendar_raw_body_for_digest(conn, raw_digest)
    else:
        calendar_raw = official_calendars.get(raw_digest)
        if calendar_raw is None:
            raise PitError(
                "official calendar raw body is missing for signed equities_master "
                f"run {closure.run_id}; complete master remains inactive"
            )
    calendar = _verify_calendar_against_closure(
        closure, official_calendar_raw=calendar_raw
    )
    segment_key = (closure.segment_start[:10], closure.segment_end[:10])
    product_rows = [
        _row_mapping(raw)
        for raw in conn.execute(
            "SELECT operation_id,run_id,source,dataset,segment_id,"
            "artifact_key,artifact_digest,artifact_body,row_count,"
            "byte_count,manifest_key,manifest_digest,raw_manifest_key,"
            "raw_manifest_digest,raw_page_count,raw_row_count,"
            "raw_bytes,committed_at FROM receipt_product_materializations "
            "WHERE source=? AND dataset=? AND segment_id=? AND run_id=?",
            (
                closure.source,
                closure.dataset,
                closure.segment_id,
                closure.run_id,
            ),
        )
    ]
    if len(product_rows) != 1:
        return None
    product = product_rows[0]
    if (
        product.get("source") != closure.source
        or product.get("dataset") != closure.dataset
        or product.get("segment_id") != closure.segment_id
        or product.get("run_id") != closure.run_id
    ):
        return None
    run_rows = [
        _row_mapping(raw)
        for raw in conn.execute(
            "SELECT id,source,runtime,status,authority_operation_id "
            "FROM ingestion_run_log WHERE id=?",
            (closure.run_id,),
        )
    ]
    raw_manifests = [
        _row_mapping(raw)
        for raw in conn.execute(
            "SELECT dataset,run_id,manifest_key,page_count,row_count,"
            "raw_bytes,data_digest FROM raw_retention_manifests "
            "WHERE dataset=? AND run_id=?",
            (closure.dataset, closure.run_id),
        )
    ]
    owned_digests = _owned_product_row_digests(
        conn,
        segment_start=segment_key[0],
        segment_end=segment_key[1],
        observed_through=observed_through,
    )
    try:
        observed_count, observed_digest, observed_bytes, snapshots = (
            _compact_snapshots_from_artifact(
                product["artifact_body"],
                owned_digests=owned_digests,
                retain_start=seed,
                retain_end=period_end,
            )
        )
        verify_full_segment_product_materialization(
            closure,
            product=product,
            run=run_rows[0] if len(run_rows) == 1 else None,
            raw_manifest=raw_manifests[0] if len(raw_manifests) == 1 else None,
            observed_count=observed_count,
            observed_digest=observed_digest,
            observed_bytes=observed_bytes,
        )
    except (PitError, TypeError, ValueError):
        return None
    finally:
        owned_digests.clear()
    if closure.structured_row_count < 1 or not snapshots:
        return None
    return _VerifiedGeneration(
        closure=closure,
        segment_start=segment_key[0],
        segment_end=segment_key[1],
        business_dates=calendar.business_dates,
        business_dates_digest=calendar.business_dates_digest,
        snapshots=snapshots,
    )


def _load_required_master_generations(
    conn: sqlite3.Connection,
    *,
    official_calendars: Mapping[str, bytes] | None,
    observed_through: str,
    seed: str,
    period_end: str,
) -> tuple[_VerifiedGeneration, ...]:
    closures = _iter_success_closures(conn)
    required = [
        closure
        for closure in closures
        if _segment_intersects(
            closure.segment_start[:10],
            closure.segment_end[:10],
            seed=seed,
            period_end=period_end,
        )
    ]
    if not required:
        raise PitError(
            "collection_receipts has no usable verified equities_master generation"
        )
    covering = [
        (closure.segment_start[:10], closure.segment_end[:10])
        for closure in required
    ]
    missing_dates = [
        day
        for day in _calendar_dates(seed, period_end)
        if not any(start <= day <= end for start, end in covering)
    ]
    if missing_dates:
        raise PitError(
            "official master segment does not cover source date "
            f"{missing_dates[0]}; complete master remains inactive"
        )
    generations: list[_VerifiedGeneration] = []
    for closure in required:
        generation = _verify_one_generation(
            conn,
            closure,
            official_calendars=official_calendars,
            observed_through=observed_through,
            seed=seed,
            period_end=period_end,
        )
        if generation is not None:
            generations.append(generation)
    if not generations:
        raise PitError(
            "collection_receipts has no usable verified equities_master generation"
        )
    return tuple(generations)


def _owned_complete_master_selection_from_connection(
    conn: sqlite3.Connection,
    *,
    period_start: str,
    period_end: str,
    as_of_for_day: Mapping[str, str],
    official_calendar_raw: Sequence[bytes] | None = None,
) -> _OwnedCompleteMasterSelection:
    """Return immutable day membership plus owner-side proof.

    A supplied ``official_calendar_raw`` sequence is the private fixture path:
    bodies are matched only by signed raw-body digest and are not mixed with
    stored rows. When omitted, each required verified master closure loads its
    signed digest from official_calendar_raw on this connection. Callers cannot
    supply dates or calendar objects as the source domain.
    """

    calendars = (
        None
        if official_calendar_raw is None
        else _index_calendar_bodies(official_calendar_raw)
    )
    if _compact_flag_from_connection(conn):
        raise PitError("complete master does not read compact personal history")
    from .query import normalize_as_of
    from .read_clock import resolve_read_clock

    last_as_of = normalize_as_of(max(as_of_for_day.values()))
    clock = resolve_read_clock(last_as_of, conn=conn)
    observed_through = _parse_dt(
        clock.observed_through, label="observed_through"
    )
    gate = _CompleteMembershipGate(
        conn=conn,
        official_calendars=calendars,
        period_end=period_end,
        observed_through=observed_through,
        observed_through_text=clock.observed_through,
    )
    slices = _universe_day_slices_from_connection(
        conn,
        period_start=period_start,
        period_end=period_end,
        as_of_for_day=as_of_for_day,
        complete_membership=gate,
        product_fields=True,
    )
    proof = CompleteMasterProof(
        format=COMPLETE_MASTER_SELECTION_EVIDENCE,
        seed_snapshot_date=gate.seed_snapshot_date,
        receipt_digests=tuple(
            generation.closure.receipt_digest for generation in gate.generations
        ),
        official_business_dates_digests=tuple(
            generation.business_dates_digest for generation in gate.generations
        ),
    )
    return _OwnedCompleteMasterSelection(slices=slices, proof=proof)


def _official_calendar_raw_body_for_digest(
    conn: sqlite3.Connection, raw_digest: str
) -> bytes:
    """Return the persisted calendar BLOB for one signed raw-body digest."""

    columns = _table_columns(conn, "official_calendar_raw")
    if not columns:
        raise PitError(
            "official_calendar_raw is missing; complete master remains inactive"
        )
    if not {"raw_body_digest", "body"} <= columns:
        raise PitError(
            "official_calendar_raw is missing required columns; "
            "complete master remains inactive"
        )
    row = conn.execute(
        "SELECT body FROM official_calendar_raw WHERE raw_body_digest=?",
        (raw_digest,),
    ).fetchone()
    if row is None:
        raise PitError(
            "official calendar raw body is missing; complete master remains inactive"
        )
    body = row[0]
    if type(body) is not bytes or not body:
        raise PitError(
            "official calendar raw body is not exact stored bytes; "
            "complete master remains inactive"
        )
    if _raw_calendar_digest(body) != raw_digest:
        raise PitError(
            "official calendar raw body digest does not match stored key"
        )
    return body


def _complete_master_day_slices_from_connection(
    conn: sqlite3.Connection,
    *,
    period_start: str,
    period_end: str,
    as_of_for_day: Mapping[str, str],
) -> tuple[UniverseDaySlice, ...]:
    """Resolve complete-master day slices on an already-open owned connection."""

    owned = _owned_complete_master_selection_from_connection(
        conn,
        period_start=period_start,
        period_end=period_end,
        as_of_for_day=as_of_for_day,
    )
    return owned.slices


__all__ = [
    "COMPLETE_MASTER_SELECTION_EVIDENCE",
    "CompleteMasterProof",
]
