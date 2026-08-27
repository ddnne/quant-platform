"""Persistent collection-coverage ledger built from Phase 3.5 checks."""

from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping, Sequence

from cf_platform.ingest_premium.coverage import CheckResult, run_coverage
from data_contracts.coverage import (
    COVERAGE_STATUSES,
    SNAPSHOT_SEGMENT_GRANULARITIES,
    CollectionCoverageContract,
    all_coverage_contracts,
    coverage_contract_for,
    coverage_policy_binding,
    coverage_policy_set_binding,
)
from data_contracts.source_capability import (
    COLLECTION_COVERAGE_V3,
    TIP_SNAPSHOT_MODES,
    OfficialRequiredDomainSubset,
    SourceCapabilityContract,
    required_domain_subset_official,
    source_capability_contract_or_none,
)
from ingestion.jsda.official_index import (
    OFFICIAL_ARCHIVE_INDEX_DATASETS as _OFFICIAL_ARCHIVE_INDEX_DATASETS,
    official_index_days,
)
from storage.coverage_ledger_io import (
    persist_refreshed_coverage,
    preserve_existing_complete_coverage_row,
    read_collection_receipts,
    read_coverage_segments,
    read_dataset_coverage,
    record_collection_receipt,
    record_required_segments,
    update_dataset_coverage_row,
    update_existing_complete_coverage_evidence,
)
from storage.coverage_receipts import (
    EXPECTED_EMPTY_WITH_EVIDENCE,
    SYNTHETIC_RECEIPT_MARKER,
    build_collection_receipt,
    build_synthetic_complete_receipt,
    compute_raw_digest,
)
from storage.receipt_policy import (
    is_recovered_only_digests,
    receipt_source_for_canonical_source,
)
from storage.receipt_crypto import (
    PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST,
    PRODUCTION_RECEIPT_ENVIRONMENT,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True)
class RequiredCoverageSegment:
    """One independently planned segment required by a coverage contract."""

    source: str
    dataset: str
    segment_id: str
    segment_start: str
    segment_end: str
    expected_scope: Mapping[str, Any]
    expected_items: int | None = None


@dataclass(frozen=True)
class CollectionReceipt:
    """Untrusted persisted transport for one collection observation.

    No field in this DTO is COMPLETE-authoritative until the v2 verifier has
    returned a ``VerifiedCollectionClosure``.
    """

    source: str
    dataset: str
    segment_id: str
    segment_start: str
    segment_end: str
    expected_scope: Mapping[str, Any]
    expected_items: int | None
    observed_items: int
    raw_page_count: int
    raw_row_count: int
    structured_row_count: int
    pagination_exhausted: bool
    digests: Mapping[str, Any]
    run_id: int
    status: str
    error: str | None
    checked_at: str


class CoverageInventoryAuthorityUnavailable(RuntimeError):
    """Exact inventory cannot be regenerated without transition authority."""


class CoveragePublicationCutoffError(RuntimeError):
    """The active publication lifecycle cannot authorize a frozen cutoff."""


@dataclass(frozen=True)
class CanonicalCoverageSegmentIdentity:
    """Closed identity used for exact expected/actual inventory comparison."""

    source: str
    dataset: str
    segment_id: str
    policy_id: str
    policy_version: str
    policy_digest: str
    segment_start: str
    segment_end: str
    expected_scope_json: str
    expected_items: int | None

    @property
    def logical_key(self) -> tuple[str, str]:
        return self.dataset, self.segment_id

    @property
    def storage_key(self) -> tuple[str, str, str, str]:
        return self.source, self.dataset, self.segment_id, self.policy_version

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "dataset": self.dataset,
            "segment_id": self.segment_id,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_digest": self.policy_digest,
            "segment_start": self.segment_start,
            "segment_end": self.segment_end,
            "expected_scope": json.loads(self.expected_scope_json),
            "expected_items": self.expected_items,
        }


@dataclass(frozen=True)
class ExactCoverageInventoryComparison:
    """Verifier-produced comparison; callers cannot supply expected inventory."""

    target_end: str
    expected_segments: tuple[RequiredCoverageSegment, ...]
    expected_identities: tuple[CanonicalCoverageSegmentIdentity, ...]
    actual_identities: tuple[CanonicalCoverageSegmentIdentity, ...]
    missing: tuple[CanonicalCoverageSegmentIdentity, ...]
    unexpected: tuple[CanonicalCoverageSegmentIdentity, ...]
    duplicates: tuple[tuple[str, str, int], ...]
    wrong_policy: tuple[tuple[str, str, tuple[str, ...]], ...]
    malformed: tuple[tuple[str, str, str], ...]

    @property
    def exact(self) -> bool:
        return not (
            self.missing
            or self.unexpected
            or self.duplicates
            or self.wrong_policy
            or self.malformed
        )

    def segments_for(self, dataset: str) -> tuple[RequiredCoverageSegment, ...]:
        return tuple(
            segment for segment in self.expected_segments
            if segment.dataset == dataset
        )

    def detail(self, *, limit: int = 20) -> dict[str, Any]:
        def brief(item: CanonicalCoverageSegmentIdentity) -> tuple[str, ...]:
            return (
                item.source,
                item.dataset,
                item.segment_id,
                item.policy_version,
                item.segment_start,
                item.segment_end,
            )

        return {
            "target_end": self.target_end,
            "expected_count": len(self.expected_identities),
            "actual_count": len(self.actual_identities),
            "missing": [brief(item) for item in self.missing[:limit]],
            "unexpected": [brief(item) for item in self.unexpected[:limit]],
            "duplicate": list(self.duplicates[:limit]),
            "wrong_policy": list(self.wrong_policy[:limit]),
            "malformed": list(self.malformed[:limit]),
        }


@dataclass(frozen=True)
class ExactCoverageCompleteVerification:
    """Exact inventory plus verifier-minted closures for selected receipts."""

    inventory: ExactCoverageInventoryComparison
    closures: tuple[Any, ...]
    invalid_segments: tuple[tuple[str, str, str], ...]

    @property
    def complete_eligible(self) -> bool:
        return (
            self.inventory.exact
            and not self.invalid_segments
            and len(self.closures) == len(self.inventory.expected_segments)
        )

    def detail(self, *, limit: int = 20) -> dict[str, Any]:
        return {
            **self.inventory.detail(limit=limit),
            "verified_receipt_count": len(self.closures),
            "invalid_selected_receipts": list(self.invalid_segments[:limit]),
        }


def _month_end(value: date) -> date:
    return value.replace(day=calendar.monthrange(value.year, value.month)[1])


_TIP_COVERAGE_MODES = frozenset({
    "recent_snapshot",
    "next_business_day_snapshot",
    "same_day_am_snapshot",
    "tip_snapshot",
})
_OFFICIAL_ARCHIVE_INDEX_MODES = frozenset({
    "official_archive_index",
    "official_archive_index_reconciled",
})


def _source_capability_for(
    dataset_id: str,
) -> SourceCapabilityContract | None:
    return source_capability_contract_or_none(dataset_id)


def _official_domain_for(
    capability: SourceCapabilityContract | None,
) -> OfficialRequiredDomainSubset | None:
    if capability is None:
        return None
    return required_domain_subset_official(capability)


def _is_tip_snapshot_policy(
    policy: CollectionCoverageContract,
    domain: OfficialRequiredDomainSubset | None,
) -> bool:
    if domain is not None and not domain.admit_historical_required_segments:
        return True
    if policy.segment_granularity in SNAPSHOT_SEGMENT_GRANULARITIES:
        return True
    if policy.coverage_mode in _TIP_COVERAGE_MODES:
        return True
    history_mode = policy.history_mode
    return history_mode in TIP_SNAPSHOT_MODES


def _snapshot_extra_scope(
    policy: CollectionCoverageContract,
    capability: SourceCapabilityContract | None,
    domain: OfficialRequiredDomainSubset | None,
    grain: str,
) -> dict[str, Any]:
    history_mode = (
        domain.history_mode
        if domain is not None
        else (policy.history_mode or policy.coverage_mode)
    )
    extra: dict[str, Any] = {
        "history_mode": history_mode,
        "tip_only_operational": True,
    }
    if capability is None:
        return extra
    sla = capability.freshness_sla
    extra["freshness_sla"] = {
        "expected_after": sla.expected_after,
        "usable_by": sla.usable_by,
        "timezone": sla.timezone,
        "rule": sla.rule,
    }
    window = capability.collection_window
    extra["collection_window"] = {
        "grain": grain,
        "open": window.open,
        "close": window.close,
    }
    if history_mode == "next_business_day_snapshot":
        extra["evaluate_via"] = [
            "collection_generation",
            "collection_cutoff",
            "freshness_sla",
        ]
    return extra


def _uses_official_archive_index(
    policy: CollectionCoverageContract,
    domain: OfficialRequiredDomainSubset | None,
) -> bool:
    if policy.dataset_id in _OFFICIAL_ARCHIVE_INDEX_DATASETS:
        return True
    if policy.coverage_mode in _OFFICIAL_ARCHIVE_INDEX_MODES:
        return True
    if policy.history_mode == "official_archive_index":
        return True
    if domain is None:
        return False
    return (
        domain.history_mode == "official_archive_index"
        or domain.publication_days_only
    )


def plan_required_segments(
    policy: CollectionCoverageContract,
    target_end: str,
    *,
    source: str = "jquants",
    expected_items_by_segment: Mapping[str, int] | None = None,
    index_text: str | None = None,
) -> tuple[RequiredCoverageSegment, ...]:
    """Create the required inventory independently of observed rows/receipts.

    SourceCapabilityContract V3 is SoT when present: official availability
    clips bounded history, and tip/snapshot history modes yield a current
    snapshot segment instead of invented monthly shells.

    Official-archive-index datasets take listed publication days from
    ``index_text``. Missing index text yields an empty required set
    (UNKNOWN / fail-closed), not a calendar-day walk.
    """
    capability = _source_capability_for(policy.dataset_id)
    domain = _official_domain_for(capability)
    start = date.fromisoformat(policy.history_target_start)
    if domain is not None:
        official = date.fromisoformat(domain.earliest_official_availability)
        if start < official:
            start = official
    end = date.fromisoformat(target_end)
    if end < start:
        raise ValueError("target_end precedes coverage history target")
    tip_snapshot = _is_tip_snapshot_policy(policy, domain)
    if tip_snapshot:
        grain = (
            domain.collection_window_grain
            if domain is not None
            else policy.segment_granularity
        )
        if grain not in SNAPSHOT_SEGMENT_GRANULARITIES:
            grain = policy.segment_granularity
            if grain not in SNAPSHOT_SEGMENT_GRANULARITIES:
                grain = "collection_cutoff_snapshot"
    else:
        grain = policy.segment_granularity
    granularity = grain
    segments: list[RequiredCoverageSegment] = []
    extra_scope = (
        _snapshot_extra_scope(policy, capability, domain, grain)
        if tip_snapshot
        else None
    )

    def _append(segment_id: str, segment_start: date, segment_end: date) -> None:
        expected_items = None
        if expected_items_by_segment is not None:
            expected_items = expected_items_by_segment.get(segment_id)
            if expected_items is not None and expected_items < 0:
                raise ValueError("expected segment items must be non-negative")
        unit = (
            "source_event"
            if policy.expected_frequency == "event_driven"
            else "source_query"
        )
        # Non-event source_query needs expected_items for COMPLETE; default one exhausted query.
        if expected_items is None and unit == "source_query":
            expected_items = 1
        scope: dict[str, Any] = {
            "coverage_mode": policy.coverage_mode,
            "expected_frequency": policy.expected_frequency,
            "expected_item_unit": unit,
            "segment_end": segment_end.isoformat(),
            "segment_start": segment_start.isoformat(),
            "universe_rule": policy.universe_rule,
            "segment_granularity": granularity,
        }
        if extra_scope:
            scope.update(extra_scope)
        segments.append(RequiredCoverageSegment(
            source=source,
            dataset=policy.dataset_id,
            segment_id=segment_id,
            segment_start=segment_start.isoformat(),
            segment_end=segment_end.isoformat(),
            expected_scope=scope,
            expected_items=expected_items,
        ))

    if tip_snapshot:
        # Current collection window only. Do not expand monthly history.
        _append(end.isoformat(), end, end)
        return tuple(segments)
    if (
        _uses_official_archive_index(policy, domain)
        or granularity == "official_archive_index_day"
    ):
        # Listed index days only. Grain is an alias, not a calendar walk.
        # Missing index_text → empty, not weekends.
        for day_s in official_index_days(policy.dataset_id, index_text):
            day = date.fromisoformat(day_s)
            if start <= day <= end:
                _append(day_s, day, day)
        return tuple(segments)
    if granularity == "calendar_month":
        cursor = start
        while cursor <= end:
            segment_end = min(_month_end(cursor), end)
            _append(cursor.strftime("%Y-%m"), cursor, segment_end)
            cursor = date.fromordinal(segment_end.toordinal() + 1)
    elif granularity == "official_archive_year":
        for year in range(start.year, end.year + 1):
            segment_start = max(start, date(year, 1, 1))
            segment_end = min(end, date(year, 12, 31))
            _append(str(year), segment_start, segment_end)
    elif granularity == "official_archive_day":
        # Non-index official_archive_day only. Index datasets returned above.
        cursor = start
        while cursor <= end:
            _append(cursor.isoformat(), cursor, cursor)
            cursor = date.fromordinal(cursor.toordinal() + 1)
    elif granularity == "source_time_series_file":
        # Stable id must match discovery/ingest. Date-range ids create phantom PARTIAL inventory.
        stable_ids = {
            "jsda_tokyo_repo_rates": "jsda-era-timeseries",
        }
        segment_id = stable_ids.get(
            policy.dataset_id, f"{policy.dataset_id}_timeseries"
        )
        _append(segment_id, start, end)
    else:  # pragma: no cover
        raise ValueError(
            f"unsupported segment granularity: {policy.segment_granularity!r}"
        )
    return tuple(segments)


_DETERMINISTIC_READY_INVENTORY_GRAINS = frozenset({"calendar_month"})


def _canonical_segment_identity(
    segment: RequiredCoverageSegment,
) -> CanonicalCoverageSegmentIdentity:
    binding = coverage_policy_binding(segment.dataset)
    return CanonicalCoverageSegmentIdentity(
        source=segment.source,
        dataset=segment.dataset,
        segment_id=segment.segment_id,
        policy_id=str(binding["policy_id"]),
        policy_version=str(binding["policy_version"]),
        policy_digest=str(binding["policy_digest"]),
        segment_start=segment.segment_start,
        segment_end=segment.segment_end,
        expected_scope_json=_canonical_json(dict(segment.expected_scope)),
        expected_items=segment.expected_items,
    )


def _persisted_segment_identity(
    row: Mapping[str, Any],
) -> CanonicalCoverageSegmentIdentity:
    dataset = str(row["dataset"])
    scope = json.loads(str(row["expected_scope"]))
    if not isinstance(scope, dict):
        raise ValueError("coverage segment expected_scope must be an object")
    binding = coverage_policy_binding(dataset)
    expected_items = row["expected_items"]
    return CanonicalCoverageSegmentIdentity(
        source=str(row["source"]),
        dataset=dataset,
        segment_id=str(row["segment_id"]),
        policy_id=str(binding["policy_id"]),
        policy_version=str(row["policy_version"]),
        policy_digest=str(binding["policy_digest"]),
        segment_start=str(row["segment_start"]),
        segment_end=str(row["segment_end"]),
        expected_scope_json=_canonical_json(scope),
        expected_items=(
            None if expected_items is None else int(expected_items)
        ),
    )


def compare_exact_coverage_inventory(
    conn: sqlite3.Connection,
    datasets: Iterable[str],
    *,
    target_end: str,
) -> ExactCoverageInventoryComparison:
    """Compare live rows with independently regenerated deterministic V3 inventory.

    Expected identities always come from checked-in Coverage and
    SourceCapability contracts. Observed ``coverage_segments`` can never define
    or shrink the expected set. Discovery/tip/index/time-series modes remain
    authority-PENDING until C10 provides a verifier-owned inventory.
    """
    observed = tuple(datasets)
    selected = tuple(sorted(set(observed)))
    if not selected or observed != selected:
        raise ValueError(
            "exact Coverage inventory datasets must be sorted and duplicate-free"
        )

    expected_segments: list[RequiredCoverageSegment] = []
    expected_identities: list[CanonicalCoverageSegmentIdentity] = []
    for dataset in selected:
        try:
            policy = coverage_contract_for(dataset)
        except KeyError as exc:
            raise CoverageInventoryAuthorityUnavailable(
                f"Coverage inventory authority unavailable for {dataset}: "
                "checked-in Coverage V3 policy is missing"
            ) from exc
        capability = source_capability_contract_or_none(dataset)
        if policy.policy_version != COLLECTION_COVERAGE_V3 or capability is None:
            raise CoverageInventoryAuthorityUnavailable(
                f"Coverage inventory authority unavailable for {dataset}: "
                "checked-in V3 policy pair is required"
            )
        grain = capability.collection_window.grain
        if (
            grain not in _DETERMINISTIC_READY_INVENTORY_GRAINS
            or policy.segment_granularity != grain
        ):
            raise CoverageInventoryAuthorityUnavailable(
                f"Coverage inventory authority unavailable for {dataset}: "
                f"{grain!r} requires an authority-issued inventory (C10 OPEN)"
            )
        try:
            source = receipt_source_for_canonical_source(capability.source)
        except ValueError as exc:
            raise CoverageInventoryAuthorityUnavailable(
                f"Coverage inventory authority unavailable for {dataset}: "
                f"unsupported source {capability.source!r}"
            ) from exc
        segments = plan_required_segments(
            policy,
            target_end,
            source=source,
            index_text=None,
        )
        if not segments:
            raise CoverageInventoryAuthorityUnavailable(
                f"Coverage canonical inventory is empty for {dataset}"
            )
        expected_segments.extend(segments)
        expected_identities.extend(
            _canonical_segment_identity(segment) for segment in segments
        )

    placeholders = ",".join("?" for _ in selected)
    cursor = conn.execute(
        "SELECT source,dataset,segment_id,policy_version,segment_start,"
        "segment_end,expected_scope,expected_items FROM coverage_segments "
        f"WHERE dataset IN ({placeholders}) "
        "ORDER BY dataset,segment_start,segment_id,source,policy_version",
        selected,
    )
    columns = tuple(item[0] for item in cursor.description or ())
    rows = [
        dict(zip(columns, row, strict=True)) for row in cursor.fetchall()
    ]
    expected_by_key = {
        _canonical_json(identity.to_dict()): identity
        for identity in expected_identities
    }
    actual_by_key: dict[str, CanonicalCoverageSegmentIdentity] = {}
    logical_rows: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    old_policy_rows: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    malformed: list[tuple[str, str, str]] = []
    for row in rows:
        dataset = str(row["dataset"])
        logical = dataset, str(row["segment_id"])
        expected_version = str(
            coverage_policy_binding(dataset)["policy_version"]
        )
        if str(row["policy_version"]) != expected_version:
            old_policy_rows.setdefault(logical, []).append(row)
            continue
        logical_rows.setdefault(logical, []).append(row)
        try:
            identity = _persisted_segment_identity(row)
            key = _canonical_json(identity.to_dict())
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            malformed.append((dataset, str(row["segment_id"]), str(exc)))
            continue
        if key in actual_by_key:
            malformed.append(
                (dataset, str(row["segment_id"]), "duplicate exact identity")
            )
            continue
        actual_by_key[key] = identity

    expected_keys = set(expected_by_key)
    actual_keys = set(actual_by_key)

    def sort_identity(item: CanonicalCoverageSegmentIdentity) -> str:
        return _canonical_json(item.to_dict())

    missing = tuple(sorted(
        (expected_by_key[key] for key in expected_keys - actual_keys),
        key=sort_identity,
    ))
    unexpected = tuple(sorted(
        (actual_by_key[key] for key in actual_keys - expected_keys),
        key=sort_identity,
    ))
    duplicates = tuple(sorted(
        (dataset, segment_id, len(group))
        for (dataset, segment_id), group in logical_rows.items()
        if len(group) != 1
    ))
    expected_logical = {identity.logical_key for identity in expected_identities}
    wrong_policy = tuple(sorted(
        (
            dataset,
            segment_id,
            tuple(sorted({str(row["policy_version"]) for row in group})),
        )
        for (dataset, segment_id), group in old_policy_rows.items()
        if (dataset, segment_id) in expected_logical
        and (dataset, segment_id) not in logical_rows
    ))
    return ExactCoverageInventoryComparison(
        target_end=target_end,
        expected_segments=tuple(expected_segments),
        expected_identities=tuple(expected_identities),
        actual_identities=tuple(sorted(actual_by_key.values(), key=sort_identity)),
        missing=missing,
        unexpected=unexpected,
        duplicates=duplicates,
        wrong_policy=wrong_policy,
        malformed=tuple(sorted(malformed)),
    )


def _empty_observed_forbids_complete(policy: CollectionCoverageContract) -> bool:
    """Tip snapshots and official-archive-index never COMPLETE on empty receipts.

    Event-zero COMPLETE stays only for genuine event_driven historical windows
    (fins disclosures). coverage_mode containing snapshot, snapshot grains
    (collection_cutoff / same_trading_day), or official_archive_index stay
    PARTIAL even when expected_frequency is still event_driven.
    """
    domain = _official_domain_for(_source_capability_for(policy.dataset_id))
    if _is_tip_snapshot_policy(policy, domain):
        return True
    if _uses_official_archive_index(policy, domain):
        return True
    mode = policy.coverage_mode
    grain = policy.segment_granularity
    history_mode = policy.history_mode or ""
    if "snapshot" in mode or "snapshot" in history_mode:
        return True
    if grain in SNAPSHOT_SEGMENT_GRANULARITIES:
        return True
    if grain.startswith(("collection_cutoff", "same_trading_day")):
        return True
    if grain == "official_archive_index_day":
        return True
    return "official_archive_index" in mode


def _evaluate_segment_with_closure(
    policy: CollectionCoverageContract,
    required: RequiredCoverageSegment,
    receipt: CollectionReceipt | None,
) -> tuple[str, dict[str, Any], Any | None]:
    """Evaluate one segment and retain the verifier-minted closure internally."""
    if receipt is None:
        return "PARTIAL", {"reason": "missing collection receipt"}, None
    # Persisted CollectionReceipt is an untrusted transport DTO.  From this
    # boundary onward COMPLETE policy may observe only the opaque closure.
    try:
        from storage.verified_receipt import (
            ReceiptVerificationError,
            require_verified_collection_closure,
        )

        closure = require_verified_collection_closure(
            receipt,
            expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
            expected_authority_instance_digest=(
                PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
            ),
            required=required,
            expected_policy_version=policy.policy_version,
        )
    except ReceiptVerificationError as exc:
        return (
            "PARTIAL",
            {
                "reason": f"receipt closure invalid: {exc}",
                "eligibility": "RECOVERED_RAW_ONLY",
            },
            None,
        )
    if closure.status != "SUCCESS" or closure.error:
        return "FAILED", {"reason": closure.error or "collection failed"}, closure
    if not closure.pagination_exhausted or not closure.discovery_exhausted:
        return (
            "PARTIAL",
            {"reason": "collection discovery is not exhausted"},
            closure,
        )
    if closure.observed_items == 0 and _empty_observed_forbids_complete(policy):
        return (
            "PARTIAL",
            {"reason": "empty tip-snapshot or archive-index receipt is not complete"},
            closure,
        )
    if (
        policy.expected_frequency != "event_driven"
        and required.expected_items is None
    ):
        return (
            "PARTIAL",
            {"reason": "non-event segment lacks explicit expected items"},
            closure,
        )
    if closure.expected_items is not None and (
        closure.observed_items != closure.expected_items
    ):
        return "PARTIAL", {"reason": "expected scope not fully observed"}, closure
    if (
        policy.expected_frequency != "event_driven"
        and closure.observed_items == 0
    ):
        return (
            "PARTIAL",
            {"reason": "empty receipt is complete only for event-driven windows"},
            closure,
        )
    raw_digest = closure.raw_digest
    if policy.raw_retention_required and (
        closure.raw_page_count < 1
        or not isinstance(raw_digest, str)
        or not raw_digest
    ):
        return "PARTIAL", {"reason": "raw pages/digest not retained"}, closure
    if (
        policy.structured_reconciliation_required
        and closure.raw_row_count != closure.structured_row_count
    ):
        return "FAILED", {"reason": "raw/structured row mismatch"}, closure
    if not _has_nonempty_trusted_raw_evidence(closure):
        return (
            "PARTIAL",
            {
                "reason": "empty raw is not COMPLETE-eligible without "
                "EXPECTED_EMPTY_WITH_EVIDENCE",
                "raw_row_count": closure.raw_row_count,
            },
            closure,
        )
    return (
        "COMPLETE",
        {
            "reason": "receipt reconciled",
            "event_zero": closure.observed_items == 0,
        },
        closure,
    )


def evaluate_segment(
    policy: CollectionCoverageContract,
    required: RequiredCoverageSegment,
    receipt: CollectionReceipt | None,
) -> tuple[str, dict[str, Any]]:
    """Evaluate one required segment without treating absent events as gaps."""
    status, detail, _closure = _evaluate_segment_with_closure(
        policy,
        required,
        receipt,
    )
    return status, detail


def _latest_run_id(conn: sqlite3.Connection, dataset: str) -> int | None:
    try:
        row = conn.execute(
            "SELECT run_id FROM ingestion_validation WHERE dataset=? "
            "ORDER BY started_at DESC, id DESC LIMIT 1",
            (dataset,),
        ).fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row is not None and row[0] is not None else None


def _date_prefix(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) < 10:
        return None
    return text[:10]


def _receipt_observed_window(
    receipts: Sequence[CollectionReceipt],
) -> tuple[str | None, str | None, int]:
    """Observed calendar span from verified v3 closures with retained rows."""
    from storage.verified_receipt import (
        ReceiptVerificationError,
        require_verified_collection_closure,
    )

    starts: list[str] = []
    ends: list[str] = []
    raw_total = 0
    for receipt in receipts:
        try:
            closure = require_verified_collection_closure(
                receipt,
                expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
                expected_authority_instance_digest=(
                    PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
                ),
            )
        except ReceiptVerificationError:
            continue
        raw_n = closure.raw_row_count
        if raw_n <= 0:
            continue
        start = _date_prefix(closure.segment_start)
        end = _date_prefix(closure.segment_end)
        if start is None or end is None:
            continue
        starts.append(start)
        ends.append(end)
        raw_total += raw_n
    if not starts:
        return None, None, 0
    return min(starts), max(ends), raw_total


def _merge_observed_window(
    hot_start: str | None,
    hot_end: str | None,
    receipt_start: str | None,
    receipt_end: str | None,
) -> tuple[str | None, str | None]:
    """Union D1-hot C4 window with receipt-plane evidence (calendar dates)."""
    candidates_start = [
        v for v in (_date_prefix(hot_start), _date_prefix(receipt_start)) if v
    ]
    candidates_end = [
        v for v in (_date_prefix(hot_end), _date_prefix(receipt_end)) if v
    ]
    if not candidates_start and not candidates_end:
        return hot_start, hot_end
    merged_start = min(candidates_start) if candidates_start else None
    merged_end = max(candidates_end) if candidates_end else None
    if (
        merged_start is not None
        and hot_start is not None
        and _date_prefix(hot_start) == merged_start
    ):
        out_start: str | None = str(hot_start)
    else:
        out_start = merged_start
    if (
        merged_end is not None
        and hot_end is not None
        and _date_prefix(hot_end) == merged_end
    ):
        out_end: str | None = str(hot_end)
    else:
        out_end = merged_end
    return out_start, out_end


def _calendar_days_between(start: str, end: str) -> int | None:
    try:
        a = date.fromisoformat(str(start)[:10])
        b = date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    return (b - a).days


def _apply_receipt_freshness_c8(
    evidence: list[CheckResult],
    *,
    dataset: str,
    receipt_end: str | None,
    reference: str,
    freshness_days: int,
) -> list[CheckResult]:
    """Re-score C8 from SUCCESS receipt ``segment_end`` when newer than D1-hot."""
    if not receipt_end:
        return evidence
    receipt_hi = _date_prefix(receipt_end)
    ref = _date_prefix(reference) or str(reference)[:10]
    if receipt_hi is None or ref is None:
        return evidence
    days = _calendar_days_between(receipt_hi, ref)
    if days is None:
        return evidence
    out: list[CheckResult] = []
    replaced = False
    for result in evidence:
        if result.check_id != "C8" or str(result.dataset or "") != dataset:
            out.append(result)
            continue
        hot_hi = result.metrics.get("latest_event_time")
        hot_prefix = _date_prefix(str(hot_hi)) if hot_hi is not None else None
        if hot_prefix is not None and hot_prefix >= receipt_hi:
            out.append(result)
            continue
        if days <= freshness_days:
            status = "pass"
            detail = f"{days} day(s) since latest event_time"
        else:
            status = "fail"
            detail = f"stale: {days} day(s) > {freshness_days}"
        out.append(
            CheckResult(
                "C8",
                dataset,
                status,
                detail,
                {
                    "latest_event_time": receipt_hi,
                    "reference": ref,
                    "max_days": freshness_days,
                    "days_lag": days,
                    "source": "receipt_observed_end",
                    "hot_latest_event_time": hot_hi,
                },
            )
        )
        replaced = True
    if not replaced:
        # No hot C8 (empty dataset) — still emit receipt C8.
        if days <= freshness_days:
            status = "pass"
            detail = f"{days} day(s) since latest event_time"
        else:
            status = "fail"
            detail = f"stale: {days} day(s) > {freshness_days}"
        out.append(
            CheckResult(
                "C8",
                dataset,
                status,
                detail,
                {
                    "latest_event_time": receipt_hi,
                    "reference": ref,
                    "max_days": freshness_days,
                    "days_lag": days,
                    "source": "receipt_observed_end",
                    "hot_latest_event_time": None,
                },
            )
        )
    return out


def _dataset_status(
    results: list[CheckResult],
) -> tuple[str, int, str | None, str | None]:
    """Validation/freshness gates only; segments/receipts own COMPLETE."""
    checks = {result.check_id: result for result in results}
    c3 = checks.get("C3")
    row_count = int(c3.metrics.get("row_count", 0)) if c3 is not None else 0
    c4 = checks.get("C4")
    observed_start = None if c4 is None else c4.metrics.get("event_time_min")
    observed_end = None if c4 is None else c4.metrics.get("event_time_max")

    if any(
        result.check_id in {"C1", "C2", "C3", "C4", "C5"}
        and result.status == "fail"
        for result in results
    ):
        return "FAILED", row_count, observed_start, observed_end
    freshness = checks.get("C8")
    if freshness is not None and freshness.status == "fail":
        return "STALE", row_count, observed_start, observed_end

    validation = checks.get("C2")
    if validation is None or validation.metrics.get("source") != "ingestion_validation":
        return "UNKNOWN", row_count, observed_start, observed_end
    if validation.metrics.get("validation_status") != "pass":
        return "FAILED", row_count, observed_start, observed_end
    return "COMPLETE", row_count, observed_start, observed_end


def _coverage_source(dataset: str) -> str:
    from data_contracts.canonical import canonical_dataset_for

    return receipt_source_for_canonical_source(
        canonical_dataset_for(dataset).source
    )


def _jsda_validation_status(
    conn: sqlite3.Connection, dataset: str
) -> tuple[str, int, str | None, str | None]:
    """PIT-shape prerequisite; collection completeness stays receipt-owned."""
    # jsda_* must map here (UNKNOWN otherwise). Not legacy jsda_bond_trades.
    fact_tables = {
        "jsda_otc_bond_reference_prices": "jsda_otc_bond_reference_prices",
        "jsda_tokyo_repo_rates": "jsda_repo_rates",
        "jsda_corporate_bond_transactions": "jsda_corporate_bond_transactions",
    }
    table = fact_tables.get(dataset)
    if table is None:
        return "UNKNOWN", 0, None, None
    try:
        row = conn.execute(
            "SELECT COUNT(*),MIN(event_time),MAX(event_time),"
            "SUM(CASE WHEN available_at IS NULL OR available_at='' THEN 1 ELSE 0 END) "
            f"FROM {table}"
        ).fetchone()
    except sqlite3.Error:
        return "UNKNOWN", 0, None, None
    count = int(row[0] or 0)
    observed_start = None if row[1] is None else str(row[1])
    observed_end = None if row[2] is None else str(row[2])
    missing_available = int(row[3] or 0)
    if missing_available:
        return "FAILED", count, observed_start, observed_end
    return "COMPLETE", count, observed_start, observed_end


def _required_from_inventory(row: Mapping[str, Any]) -> RequiredCoverageSegment:
    try:
        expected_scope = json.loads(str(row["expected_scope"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("coverage segment contains invalid expected scope") from exc
    if not isinstance(expected_scope, dict):
        raise ValueError("coverage segment expected scope must be an object")
    return RequiredCoverageSegment(
        source=str(row["source"]),
        dataset=str(row["dataset"]),
        segment_id=str(row["segment_id"]),
        segment_start=str(row["segment_start"]),
        segment_end=str(row["segment_end"]),
        expected_scope=expected_scope,
        expected_items=(
            None if row["expected_items"] is None else int(row["expected_items"])
        ),
    )


def _receipt_from_row(row: Mapping[str, Any]) -> CollectionReceipt:
    try:
        expected_scope = json.loads(str(row["expected_scope"]))
        digests = json.loads(str(row["digests_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("collection receipt contains invalid JSON evidence") from exc
    if not isinstance(expected_scope, dict) or not isinstance(digests, dict):
        raise ValueError("collection receipt JSON evidence must be objects")
    return CollectionReceipt(
        source=str(row["source"]),
        dataset=str(row["dataset"]),
        segment_id=str(row["segment_id"]),
        segment_start=str(row["segment_start"]),
        segment_end=str(row["segment_end"]),
        expected_scope=expected_scope,
        expected_items=(
            None if row["expected_items"] is None else int(row["expected_items"])
        ),
        observed_items=int(row["observed_items"]),
        raw_page_count=int(row["raw_page_count"]),
        raw_row_count=int(row["raw_row_count"]),
        structured_row_count=int(row["structured_row_count"]),
        pagination_exhausted=bool(row["pagination_exhausted"]),
        digests=digests,
        run_id=int(row["run_id"]),
        status=str(row["status"]),
        error=None if row["error"] is None else str(row["error"]),
        checked_at=str(row["checked_at"]),
    )


def verify_exact_coverage_complete(
    conn: sqlite3.Connection,
    datasets: Iterable[str],
    *,
    target_end: str,
) -> ExactCoverageCompleteVerification:
    """Verify exact inventory/receipts in one SQLite read snapshot."""
    owns_snapshot = not conn.in_transaction
    if owns_snapshot:
        conn.execute("BEGIN")
    try:
        return _verify_exact_coverage_complete_in_snapshot(
            conn,
            datasets,
            target_end=target_end,
        )
    finally:
        if owns_snapshot:
            conn.rollback()


def _verify_exact_coverage_complete_in_snapshot(
    conn: sqlite3.Connection,
    datasets: Iterable[str],
    *,
    target_end: str,
) -> ExactCoverageCompleteVerification:
    """Verify exact canonical identities and each selected signed receipt.

    The expected set is regenerated internally.  A receipt is considered only
    when the exact canonical segment selects its run id; arbitrary latest or
    orphan receipts cannot satisfy COMPLETE eligibility.
    """
    inventory = compare_exact_coverage_inventory(
        conn,
        datasets,
        target_end=target_end,
    )
    if not inventory.exact:
        return ExactCoverageCompleteVerification(inventory, (), ())

    selected = tuple(sorted({item.dataset for item in inventory.expected_segments}))
    placeholders = ",".join("?" for _ in selected)
    try:
        cursor = conn.execute(
            """
            SELECT
                s.source AS segment_source,
                s.dataset AS segment_dataset,
                s.segment_id AS segment_id,
                s.policy_version AS segment_policy_version,
                s.segment_start AS segment_start,
                s.segment_end AS segment_end,
                s.expected_scope AS segment_expected_scope,
                s.expected_items AS segment_expected_items,
                s.status AS segment_status,
                s.receipt_run_id AS selected_receipt_run_id,
                r.source AS receipt_source,
                r.dataset AS receipt_dataset,
                r.segment_id AS receipt_segment_id,
                r.segment_start AS receipt_segment_start,
                r.segment_end AS receipt_segment_end,
                r.expected_scope AS receipt_expected_scope,
                r.expected_items AS receipt_expected_items,
                r.observed_items AS receipt_observed_items,
                r.raw_page_count AS receipt_raw_page_count,
                r.raw_row_count AS receipt_raw_row_count,
                r.structured_row_count AS receipt_structured_row_count,
                r.pagination_exhausted AS receipt_pagination_exhausted,
                r.digests_json AS receipt_digests_json,
                r.run_id AS receipt_run_id,
                r.status AS receipt_status,
                r.error AS receipt_error,
                r.checked_at AS receipt_checked_at
            FROM coverage_segments AS s
            LEFT JOIN collection_receipts AS r
              ON r.source=s.source
             AND r.dataset=s.dataset
             AND r.segment_id=s.segment_id
             AND r.run_id=s.receipt_run_id
            WHERE s.dataset IN ("""
            + placeholders
            + ")",
            selected,
        )
        columns = tuple(item[0] for item in cursor.description or ())
        rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    except sqlite3.Error:
        invalid = tuple(
            (
                segment.dataset,
                segment.segment_id,
                "selected collection receipt ledger unavailable",
            )
            for segment in inventory.expected_segments
        )
        return ExactCoverageCompleteVerification(inventory, (), invalid)

    by_key = {
        (
            str(row["segment_source"]),
            str(row["segment_dataset"]),
            str(row["segment_id"]),
            str(row["segment_policy_version"]),
        ): row
        for row in rows
    }
    closures: list[Any] = []
    invalid: list[tuple[str, str, str]] = []
    selected_receipts: set[tuple[str, str, str, int]] = set()
    for identity, required in zip(
        inventory.expected_identities,
        inventory.expected_segments,
        strict=True,
    ):
        row = by_key.get(identity.storage_key)
        reason: str | None = None
        closure: Any | None = None
        if row is None:
            reason = "canonical segment disappeared during receipt verification"
        else:
            try:
                joined_identity = _persisted_segment_identity({
                    "source": row["segment_source"],
                    "dataset": row["segment_dataset"],
                    "segment_id": row["segment_id"],
                    "policy_version": row["segment_policy_version"],
                    "segment_start": row["segment_start"],
                    "segment_end": row["segment_end"],
                    "expected_scope": row["segment_expected_scope"],
                    "expected_items": row["segment_expected_items"],
                })
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                reason = f"canonical segment changed: {exc}"
            else:
                if joined_identity != identity:
                    reason = "canonical segment changed during receipt verification"
        if reason is None and row["segment_status"] != "COMPLETE":
            reason = "segment not COMPLETE"
        elif reason is None and (
            row["selected_receipt_run_id"] is None
            or row["receipt_run_id"] is None
        ):
            reason = "selected signed receipt missing"
        elif reason is None:
            receipt_payload = {
                "source": row["receipt_source"],
                "dataset": row["receipt_dataset"],
                "segment_id": row["receipt_segment_id"],
                "segment_start": row["receipt_segment_start"],
                "segment_end": row["receipt_segment_end"],
                "expected_scope": row["receipt_expected_scope"],
                "expected_items": row["receipt_expected_items"],
                "observed_items": row["receipt_observed_items"],
                "raw_page_count": row["receipt_raw_page_count"],
                "raw_row_count": row["receipt_raw_row_count"],
                "structured_row_count": row["receipt_structured_row_count"],
                "pagination_exhausted": row["receipt_pagination_exhausted"],
                "digests_json": row["receipt_digests_json"],
                "run_id": row["receipt_run_id"],
                "status": row["receipt_status"],
                "error": row["receipt_error"],
                "checked_at": row["receipt_checked_at"],
            }
            try:
                receipt = _receipt_from_row(receipt_payload)
                status, detail, closure = _evaluate_segment_with_closure(
                    coverage_contract_for(required.dataset),
                    required,
                    receipt,
                )
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                reason = f"selected receipt malformed: {exc}"
            else:
                if status != "COMPLETE" or closure is None:
                    reason = str(detail.get("reason") or "receipt is not COMPLETE")
        if reason is None:
            receipt_identity = (
                closure.source,
                closure.dataset,
                closure.segment_id,
                closure.run_id,
            )
            if receipt_identity in selected_receipts:
                reason = "selected receipt reused"
            else:
                selected_receipts.add(receipt_identity)
                closures.append(closure)
        if reason is not None:
            invalid.append((required.dataset, required.segment_id, reason))

    return ExactCoverageCompleteVerification(
        inventory=inventory,
        closures=tuple(closures),
        invalid_segments=tuple(invalid),
    )


def _rank_receipt_for_match(item: CollectionReceipt) -> tuple:
    """Trusted first, recovered last, then structured/time."""
    trusted = 1 if is_complete_eligible_receipt(item) else 0
    recovered = 1 if is_recovered_only_digests(item.digests) else 0
    structured = int(item.structured_row_count or 0)
    return (trusted, -recovered, structured, item.checked_at, item.run_id)


def _latest_receipt_for(
    receipts: Sequence[CollectionReceipt],
    required: RequiredCoverageSegment,
) -> CollectionReceipt | None:
    """Best receipt for a segment; trusted wins over a newer recovered rebuild."""
    exact = [
        receipt for receipt in receipts
        if receipt.source == required.source
        and receipt.dataset == required.dataset
        and receipt.segment_id == required.segment_id
        and receipt.segment_start == required.segment_start
        and receipt.segment_end == required.segment_end
    ]
    if not exact:
        return None
    return max(exact, key=_rank_receipt_for_match)


def _latest_complete_receipt_for_required(
    receipts: Sequence[CollectionReceipt],
    *,
    policy: CollectionCoverageContract,
    required: RequiredCoverageSegment,
) -> tuple[CollectionReceipt, Any] | None:
    """Best receipt that independently evaluates COMPLETE for this scope."""
    from storage.verified_receipt import (
        ReceiptVerificationError,
        require_verified_collection_closure,
    )

    candidates: list[tuple[CollectionReceipt, Any]] = []
    for receipt in receipts:
        if evaluate_segment(policy, required, receipt)[0] != "COMPLETE":
            continue
        try:
            closure = require_verified_collection_closure(
                receipt,
                expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
                expected_authority_instance_digest=(
                    PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
                ),
                required=required,
                expected_policy_version=policy.policy_version,
            )
        except ReceiptVerificationError:  # defensive; evaluate already verified
            continue
        candidates.append((receipt, closure))
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            item[1].structured_row_count,
            item[1].checked_at,
            item[1].run_id,
        ),
    )


def evaluate_required_segments(
    policy: CollectionCoverageContract,
    required_segments: Sequence[RequiredCoverageSegment],
    receipts: Sequence[CollectionReceipt],
) -> tuple[str, list[tuple[RequiredCoverageSegment, CollectionReceipt | None, str, dict[str, Any]]]]:
    """Evaluate the planned inventory, including missing receipts."""
    evaluated = []
    for required in required_segments:
        receipt = _latest_receipt_for(receipts, required)
        status, detail = evaluate_segment(policy, required, receipt)
        evaluated.append((required, receipt, status, detail))
    statuses = [item[2] for item in evaluated]
    if any(status == "FAILED" for status in statuses):
        aggregate = "FAILED"
    elif statuses and all(status == "COMPLETE" for status in statuses):
        aggregate = "COMPLETE"
    else:
        aggregate = "PARTIAL"
    return aggregate, evaluated


def validation_coverage_cutoff_for_build(
    conn: sqlite3.Connection,
    db_path: str | Path,
    build_id: object,
) -> str:
    """Derive the cutoff from the unique active VALIDATING build.

    The caller supplies only an identifier.  This verifier re-derives the date
    from the publication row and binds it to the active local policy and the
    exact main/staging database path in the caller's current transaction.
    """
    if not isinstance(build_id, str) or not build_id:
        raise CoveragePublicationCutoffError(
            "Coverage refresh requires a publisher-owned build id"
        )
    try:
        publications = conn.execute(
            "SELECT state,staging_path,created_at FROM snapshot_publications "
            "WHERE build_id=?",
            (build_id,),
        ).fetchall()
        policies = conn.execute(
            "SELECT publication_state,snapshot_ready,active_build_id "
            "FROM local_snapshot_policy WHERE singleton=1"
        ).fetchall()
        main_path = next(
            (
                str(row[2])
                for row in conn.execute("PRAGMA database_list").fetchall()
                if str(row[1]) == "main"
            ),
            "",
        )
    except sqlite3.Error as exc:
        raise CoveragePublicationCutoffError(
            "Coverage refresh publication lifecycle is unavailable"
        ) from exc
    if len(publications) != 1 or len(policies) != 1:
        raise CoveragePublicationCutoffError(
            "Coverage refresh has no unique active publication lifecycle"
        )
    publication = publications[0]
    policy = policies[0]
    staging_path = str(publication[1])
    try:
        descriptor_prefix = next(
            (
                prefix
                for prefix in ("/dev/fd/", "/proc/self/fd/")
                if main_path.startswith(prefix)
            ),
            None,
        )
        main_info = (
            os.fstat(int(main_path.removeprefix(descriptor_prefix)))
            if descriptor_prefix is not None
            else Path(main_path).stat()
        )
        main_matches_staging = os.path.samestat(main_info, Path(staging_path).stat())
        main_matches_governed = os.path.samestat(main_info, Path(db_path).stat())
    except (OSError, ValueError):
        main_matches_staging = False
        main_matches_governed = False
    if (
        str(publication[0]) != "VALIDATING"
        or str(policy[0]) != "VALIDATING"
        or int(policy[1]) != 0
        or policy[2] != build_id
        or not main_path
        or not main_matches_staging
        or not main_matches_governed
    ):
        raise CoveragePublicationCutoffError(
            "Coverage refresh build is not the unique active VALIDATING build"
        )
    created_at = str(publication[2])
    try:
        instant = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CoveragePublicationCutoffError(
            "Coverage refresh publication timestamp is malformed"
        ) from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise CoveragePublicationCutoffError(
            "Coverage refresh publication timestamp must be timezone-aware"
        )
    return instant.astimezone(timezone.utc).date().isoformat()


def _refresh_inventory_target_end(
    conn: sqlite3.Connection,
    db_path: str | Path,
    evaluated_at: str,
    publication_build_id: object | None,
) -> str:
    """Use an internally verified build cutoff or the internal UTC clock."""
    if publication_build_id is not None:
        return validation_coverage_cutoff_for_build(
            conn,
            db_path,
            publication_build_id,
        )
    try:
        instant = datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
    except ValueError as exc:  # pragma: no cover - internal clock contract
        raise RuntimeError("Coverage refresh clock did not return ISO-8601") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise RuntimeError("Coverage refresh clock must be timezone-aware")
    return instant.astimezone(timezone.utc).date().isoformat()


def _apply_refresh_complete_gate(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
    *,
    prior_coverage: Mapping[str, Mapping[str, Any]],
    inventory_target_end: str,
) -> None:
    """Fail closed every aggregate COMPLETE computed by generic refresh.

    C10 transition authority does not exist yet, so generic refresh can never
    promote an aggregate.  A current-policy COMPLETE may survive only when the
    replacement inventory is exact and every selected persisted receipt closes
    under its signature.  This function runs after segment replacement and in
    the same write transaction as the final aggregate upsert.
    """
    for row in rows:
        dataset = str(row["dataset"])
        computed_status = str(row["status"])
        current_policy_version = str(row["policy_version"])
        prior = prior_coverage.get(dataset)
        prior_status = None if prior is None else str(prior.get("status") or "")
        prior_policy_version = (
            None if prior is None else str(prior.get("policy_version") or "")
        )
        inventory_status = "NOT_EVALUATED"
        selected_receipt_status = "NOT_EVALUATED"
        inventory_detail: dict[str, Any] | None = None
        blocker: str | None = None

        if computed_status == "COMPLETE":
            if prior_status != "COMPLETE":
                blocker = "transition_authority_required"
            elif prior_policy_version != current_policy_version:
                blocker = "prior_aggregate_policy_mismatch"
            else:
                try:
                    verification = verify_exact_coverage_complete(
                        conn,
                        (dataset,),
                        target_end=inventory_target_end,
                    )
                except CoverageInventoryAuthorityUnavailable as exc:
                    inventory_status = "PENDING"
                    inventory_detail = {
                        "target_end": inventory_target_end,
                        "reason": str(exc),
                    }
                    blocker = "inventory_authority_pending"
                else:
                    inventory_detail = verification.detail()
                    if not verification.inventory.exact:
                        inventory_status = "MISMATCH"
                        blocker = "inventory_mismatch"
                    else:
                        inventory_status = "EXACT"
                        if verification.complete_eligible:
                            selected_receipt_status = "VERIFIED"
                        else:
                            selected_receipt_status = "INVALID"
                            blocker = "selected_receipt_invalid"
            if blocker is not None:
                row["status"] = "PARTIAL"
        else:
            blocker = "evaluation_not_complete"

        try:
            detail = json.loads(str(row.get("detail_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            detail = {}
        if not isinstance(detail, dict):
            detail = {}
        coverage_detail = dict(detail.get("coverage_v2") or {})
        coverage_detail["aggregate_complete_gate"] = {
            "mode": "generic_refresh_c10_transition_authority_unavailable",
            "computed_status": computed_status,
            "persisted_status": row["status"],
            "prior_status": prior_status,
            "prior_policy_version": prior_policy_version,
            "current_policy_version": current_policy_version,
            "inventory_target_end": inventory_target_end,
            "inventory_status": inventory_status,
            "selected_receipt_status": selected_receipt_status,
            "blocker": blocker,
            "inventory": inventory_detail,
        }
        detail["coverage_v2"] = coverage_detail
        row["detail_json"] = _canonical_json(detail)


def _refresh_coverage_ledger_in_transaction(
    conn: sqlite3.Connection,
    db_path: str | Path,
    *,
    datasets: Iterable[str] | None = None,
    today: str | None = None,
    freshness_days: int = 7,
    index_text: str | None = None,
    _publication_build_id: object | None = None,
) -> list[dict[str, Any]]:
    """Evaluate Coverage V2 segments and atomically refresh aggregate rows.

    Official-archive-index datasets take required days from
    ``plan_required_segments`` / ``index_text``. Missing index text is
    fail-closed empty, not a replay of calendar-day inventory.
    """
    selected = tuple(datasets) if datasets is not None else tuple(
        policy.dataset_id for policy in all_coverage_contracts()
    )
    if not selected:
        raise ValueError("datasets must not be empty")
    policies = {dataset: coverage_contract_for(dataset) for dataset in selected}
    evaluated_at = _now()
    inventory_target_end = _refresh_inventory_target_end(
        conn,
        db_path,
        evaluated_at,
        _publication_build_id,
    )
    target_end = today or datetime.now(timezone.utc).date().isoformat()
    prior_cursor = conn.execute(
        "SELECT dataset,status,policy_version FROM dataset_coverage "
        f"WHERE dataset IN ({','.join('?' for _ in selected)})",
        selected,
    )
    prior_columns = tuple(item[0] for item in prior_cursor.description or ())
    prior_coverage = {
        str(row["dataset"]): row
        for row in (
            dict(zip(prior_columns, raw, strict=True))
            for raw in prior_cursor.fetchall()
        )
    }
    jquants_selected = tuple(
        dataset for dataset in selected if _coverage_source(dataset) == "jquants"
    )
    evidence = (
        run_coverage(
            db_path,
            tier="daily",
            datasets=jquants_selected,
            today=target_end,
            freshness_days=freshness_days,
            workers=1,
            strict_live_gates=False,
        )
        if jquants_selected else []
    )
    by_dataset: dict[str, list[CheckResult]] = {dataset: [] for dataset in selected}
    global_failures = [
        result for result in evidence
        if result.dataset is None and result.status == "fail"
    ]
    for result in evidence:
        if result.dataset in by_dataset:
            by_dataset[str(result.dataset)].append(result)

    placeholders = ",".join("?" for _ in selected)
    # status + receipt_run_id: sticky COMPLETE needs prior COMPLETE inventory.
    inventory_cursor = conn.execute(
        "SELECT source,dataset,segment_id,policy_version,segment_start,segment_end,"
        "expected_scope,expected_items,status,receipt_run_id FROM coverage_segments "
        f"WHERE dataset IN ({placeholders})",
        selected,
    )
    inventory_by_dataset: dict[str, dict[str, Mapping[str, Any]]] = {
        dataset: {} for dataset in selected
    }
    for raw in inventory_cursor.fetchall():
        row: Mapping[str, Any] = dict(raw) if isinstance(raw, sqlite3.Row) else {
            "source": raw[0], "dataset": raw[1], "segment_id": raw[2],
            "policy_version": raw[3],
            "segment_start": raw[4], "segment_end": raw[5],
            "expected_scope": raw[6], "expected_items": raw[7],
            "status": raw[8], "receipt_run_id": raw[9],
        }
        if row.get("policy_version") != policies[str(row["dataset"])].policy_version:
            continue
        inventory_by_dataset[str(row["dataset"])][str(row["segment_id"])] = row
    receipt_cursor = conn.execute(
        "SELECT * FROM collection_receipts "
        f"WHERE dataset IN ({placeholders}) "
        "ORDER BY checked_at, run_id",
        selected,
    )
    receipt_columns = tuple(item[0] for item in receipt_cursor.description or ())
    receipts_by_dataset: dict[str, list[CollectionReceipt]] = {
        dataset: [] for dataset in selected
    }
    for raw in receipt_cursor.fetchall():
        row = dict(zip(receipt_columns, raw))
        receipt = _receipt_from_row(row)
        receipts_by_dataset[receipt.dataset].append(receipt)

    rows: list[dict[str, Any]] = []
    segment_rows: list[dict[str, Any]] = []
    for dataset in selected:
        policy = policies[dataset]
        source = _coverage_source(dataset)
        # D1 jquants_records is hot-window only; observed_*/C8 expand from SUCCESS raw receipts.
        receipt_start, receipt_end, receipt_raw_rows = _receipt_observed_window(
            receipts_by_dataset[dataset]
        )
        dataset_evidence = by_dataset[dataset]
        if source == "jquants":
            dataset_evidence = _apply_receipt_freshness_c8(
                dataset_evidence,
                dataset=dataset,
                receipt_end=receipt_end,
                reference=target_end,
                freshness_days=freshness_days,
            )
            by_dataset[dataset] = dataset_evidence
        if source == "jsda":
            validation_status, count, observed_start, observed_end = (
                _jsda_validation_status(conn, dataset)
            )
        else:
            validation_status, count, observed_start, observed_end = _dataset_status(
                dataset_evidence
            )
        if receipt_start is not None or receipt_end is not None:
            observed_start, observed_end = _merge_observed_window(
                observed_start, observed_end, receipt_start, receipt_end,
            )
        domain = _official_domain_for(_source_capability_for(dataset))
        if (
            policy.segment_granularity in {
                "official_archive_day", "source_time_series_file"
            }
            and not _uses_official_archive_index(policy, domain)
        ):
            # Keep inventory through target_end, plus already-COMPLETE days past UTC (JST can lead).
            required_segments = tuple(sorted(
                (
                    _required_from_inventory(row)
                    for row in inventory_by_dataset[dataset].values()
                    if str(row["source"]) == source
                    and (
                        str(row["segment_start"]) <= target_end
                        or str(row.get("status") or "") == "COMPLETE"
                    )
                ),
                key=lambda item: (item.segment_start, item.segment_id),
            ))
        else:
            base_segments = plan_required_segments(
                policy, target_end, source=source, index_text=index_text,
            )
            expected_items_by_segment: dict[str, int] = {}
            for segment in base_segments:
                inventory = inventory_by_dataset[dataset].get(segment.segment_id)
                if (
                    inventory is not None
                    and inventory["segment_start"] == segment.segment_start
                    and inventory["segment_end"] == segment.segment_end
                    and inventory["expected_scope"] == _canonical_json(
                        dict(segment.expected_scope)
                    )
                    and inventory["expected_items"] is not None
                ):
                    expected_items_by_segment[segment.segment_id] = int(
                        inventory["expected_items"]
                    )
            required_segments = plan_required_segments(
                policy,
                target_end,
                source=source,
                expected_items_by_segment=expected_items_by_segment,
                index_text=index_text,
            )
        segment_aggregate, segment_evaluations = evaluate_required_segments(
            policy, required_segments, receipts_by_dataset[dataset]
        )
        segment_statuses: list[str] = []
        for (
            required_segment, receipt, segment_status, segment_detail
        ) in segment_evaluations:
            # Sticky COMPLETE: never demote while a COMPLETE-eligible SUCCESS receipt remains.
            prior_inv = inventory_by_dataset[dataset].get(
                required_segment.segment_id
            )
            prior_status = (
                None if prior_inv is None else str(prior_inv.get("status") or "")
            )
            sticky = None
            if segment_status != "COMPLETE" and prior_status == "COMPLETE":
                sticky = _latest_complete_receipt_for_required(
                    receipts_by_dataset[dataset],
                    policy=policy,
                    required=required_segment,
                )
            if (
                segment_status != "COMPLETE"
                and prior_status == "COMPLETE"
                and sticky is not None
            ):
                sticky_receipt, sticky_closure = sticky
                segment_detail = {
                    **dict(segment_detail),
                    "sticky_complete": True,
                    "demotion_blocked": segment_detail.get("reason"),
                    "reason": "sticky COMPLETE: eligible SUCCESS receipt retained",
                    "sticky_receipt_run_id": sticky_closure.run_id,
                }
                segment_status = "COMPLETE"
                receipt = sticky_receipt
            segment_statuses.append(segment_status)
            selected_run_id = None if receipt is None else receipt.run_id
            if segment_status == "COMPLETE":
                from storage.verified_receipt import (
                    require_verified_collection_closure,
                )

                selected_run_id = require_verified_collection_closure(
                    receipt,
                    expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
                    expected_authority_instance_digest=(
                        PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
                    ),
                    required=required_segment,
                    expected_policy_version=policy.policy_version,
                ).run_id
            segment_rows.append({
                "source": required_segment.source,
                "dataset": required_segment.dataset,
                "segment_id": required_segment.segment_id,
                "policy_version": policy.policy_version,
                "segment_start": required_segment.segment_start,
                "segment_end": required_segment.segment_end,
                "expected_scope": _canonical_json(
                    dict(required_segment.expected_scope)
                ),
                "expected_items": required_segment.expected_items,
                "status": segment_status,
                "receipt_run_id": selected_run_id,
                "evaluated_at": evaluated_at,
                "detail_json": _canonical_json(segment_detail),
            })
        # Recompute aggregate after sticky upgrades so day-roll does not pin dataset PARTIAL.
        if any(status == "FAILED" for status in segment_statuses):
            segment_aggregate = "FAILED"
        elif segment_statuses and all(
            status == "COMPLETE" for status in segment_statuses
        ):
            segment_aggregate = "COMPLETE"
        else:
            segment_aggregate = "PARTIAL"
        if validation_status != "COMPLETE":
            status = validation_status
        else:
            status = segment_aggregate
        if source == "jquants" and global_failures:
            status = "FAILED"
        if status not in COVERAGE_STATUSES:  # pragma: no cover
            raise AssertionError(f"unexpected coverage status: {status}")
        detail = {
            "checks": [result.as_log_dict() for result in dataset_evidence],
            "global_failures": [result.as_log_dict() for result in global_failures],
            # Compatibility shape for existing operational readers. The
            # authoritative policy version is the per-dataset column above;
            # this nested key is not used as READY policy authority.
            "coverage_v2": {
                "required_segments": len(segment_statuses),
                "status_counts": {
                    value: segment_statuses.count(value)
                    for value in sorted(COVERAGE_STATUSES)
                    if segment_statuses.count(value)
                },
                "target_end": target_end,
            },
            "observed_window": {
                "receipt_start": receipt_start,
                "receipt_end": receipt_end,
                "receipt_raw_rows": receipt_raw_rows,
                "source": (
                    "receipt_union_hot"
                    if receipt_start is not None or receipt_end is not None
                    else "hot_c4_only"
                ),
            },
        }
        rows.append({
            "dataset": dataset,
            **asdict(policy),
            "status": status,
            "policy_version": policy.policy_version,
            "observed_start": observed_start,
            "observed_end": observed_end,
            "row_count": count,
            "source_run_id": (
                _latest_run_id(conn, dataset)
                if source == "jquants"
                else max(
                    (receipt.run_id for receipt in receipts_by_dataset[dataset]),
                    default=None,
                )
            ),
            "evaluated_at": evaluated_at,
            "detail_json": _canonical_json(detail),
        })

    persist_refreshed_coverage(
        conn,
        delete_keys=[
            (_coverage_source(dataset), dataset, policies[dataset].policy_version)
            for dataset in selected
        ],
        segment_rows=segment_rows,
        coverage_rows=(),
    )
    _apply_refresh_complete_gate(
        conn,
        rows,
        prior_coverage=prior_coverage,
        inventory_target_end=inventory_target_end,
    )
    persist_refreshed_coverage(
        conn,
        delete_keys=(),
        segment_rows=(),
        coverage_rows=tuple(row for row in rows if row["status"] != "COMPLETE"),
    )
    for row in rows:
        if row["status"] == "COMPLETE":
            preserve_existing_complete_coverage_row(conn, row)
    return rows


def refresh_coverage_ledger(
    conn: sqlite3.Connection,
    db_path: str | Path,
    *,
    datasets: Iterable[str] | None = None,
    today: str | None = None,
    freshness_days: int = 7,
    index_text: str | None = None,
    _publication_build_id: object | None = None,
) -> list[dict[str, Any]]:
    """Refresh under one write snapshot; generic callers cannot mint COMPLETE."""
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        rows = _refresh_coverage_ledger_in_transaction(
            conn,
            db_path,
            datasets=datasets,
            today=today,
            freshness_days=freshness_days,
            index_text=index_text,
            _publication_build_id=_publication_build_id,
        )
        if owns_transaction:
            conn.commit()
        return rows
    except BaseException:
        if owns_transaction:
            conn.rollback()
        raise


def coverage_summary(db_path: str | Path) -> dict[str, Any]:
    rows = read_dataset_coverage(db_path)
    policy_set = coverage_policy_set_binding(
        [str(row["dataset"]) for row in rows]
    ) if rows else None
    counts = {status: 0 for status in sorted(COVERAGE_STATUSES)}
    for row in rows:
        counts[str(row["status"])] += 1
    governed = [row for row in rows if row["governance_tier"] == "governed"]
    return {
        "policy_version": (
            policy_set["policy_version"] if policy_set is not None else "UNKNOWN"
        ),
        "policy_digest": (
            policy_set["policy_digest"] if policy_set is not None else "UNKNOWN"
        ),
        "dataset_count": len(rows),
        "status_counts": counts,
        "governed_ready": bool(governed) and all(
            row["status"] == "COMPLETE" for row in governed
        ),
    }


def coverage_gaps(db_path: str | Path) -> list[dict[str, Any]]:
    return [
        row for row in read_dataset_coverage(db_path)
        if row["status"] != "COMPLETE"
    ]


def aggregate_status_from_segment_counts(
    status_counts: Mapping[str, int],
) -> str:
    """Fail-closed aggregate: empty→UNKNOWN; any FAILED→FAILED; else all COMPLETE."""
    counts = {
        str(status): int(n)
        for status, n in dict(status_counts or {}).items()
        if int(n) > 0
    }
    total = sum(counts.values())
    if total <= 0:
        return "UNKNOWN"
    if int(counts.get("FAILED", 0)) > 0:
        return "FAILED"
    if int(counts.get("COMPLETE", 0)) == total:
        return "COMPLETE"
    return "PARTIAL"


def honest_status_counts(
    status_counts: Mapping[str, int],
) -> dict[str, int]:
    """Drop zero counts; coerce values to int."""
    return {
        str(status): int(n)
        for status, n in sorted(dict(status_counts or {}).items())
        if int(n) > 0
    }


def _failing_checks_from_detail(detail: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    checks = [] if detail is None else list(detail.get("checks") or [])
    failing: list[dict[str, Any]] = []
    for check in checks:
        if not isinstance(check, Mapping):
            continue
        status = str(check.get("status", "")).lower()
        if status in {"fail", "failed", "error"}:
            failing.append(dict(check))
    return failing


def build_surgical_reagg_detail(
    existing_detail: Mapping[str, Any] | None,
    *,
    status_counts: Mapping[str, int],
    required_segments: int | None,
    audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge honest coverage_v2 status_counts into ``detail_json``."""
    detail = dict(existing_detail or {})
    cov = dict(detail.get("coverage_v2") or {})
    prev_counts = cov.get("status_counts")
    new_counts = honest_status_counts(status_counts)
    cov["status_counts"] = new_counts
    if required_segments is None:
        cov.pop("required_segments", None)
    else:
        cov["required_segments"] = int(required_segments)
    if audit is not None:
        cov["surgical_reagg"] = dict(audit)
        if prev_counts is not None and "prev_status_counts" not in cov["surgical_reagg"]:
            cov["surgical_reagg"]["prev_status_counts"] = prev_counts
    detail["coverage_v2"] = cov
    detail["aggregate_source"] = "surgical_reagg_from_coverage_segments"
    return detail


def _sync_dataset_coverage_from_segments_in_transaction(
    conn: sqlite3.Connection,
    *,
    datasets: Iterable[str] | None = None,
    dry_run: bool = False,
    wave: str | None = None,
) -> list[dict[str, Any]]:
    """Re-aggregate only after verifier-owned exact inventory comparison.

    The surgical path cannot accept caller-supplied inventory or bypass flags.
    Deterministic V3 inventory is regenerated from checked-in contracts at the
    evaluation date.  Every other mode is transition-authority PENDING (C10),
    so this function can neither mint nor preserve ``COMPLETE`` for it.
    """
    if datasets is None:
        selected = [
            str(row[0])
            for row in conn.execute(
                "SELECT dataset FROM dataset_coverage ORDER BY dataset"
            ).fetchall()
        ]
    else:
        selected = sorted(set(datasets))
    if not selected:
        return []

    evaluated_at = _now()
    try:
        evaluated_dt = datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
    except ValueError as exc:  # pragma: no cover - internal clock contract
        raise RuntimeError("Coverage sync clock did not return ISO-8601") from exc
    if evaluated_dt.tzinfo is None:  # pragma: no cover - internal clock contract
        raise RuntimeError("Coverage sync clock must be timezone-aware")
    inventory_target_end = evaluated_dt.astimezone(timezone.utc).date().isoformat()
    results: list[dict[str, Any]] = []
    pre_platform = conn.execute(
        "SELECT COUNT(*) FROM coverage_segments WHERE status='COMPLETE'"
    ).fetchone()[0]

    for dataset in selected:
        try:
            effective_policy_version = coverage_contract_for(dataset).policy_version
        except KeyError:
            aggregate_policy_row = conn.execute(
                "SELECT policy_version FROM dataset_coverage WHERE dataset=?",
                (dataset,),
            ).fetchone()
            effective_policy_version = (
                str(aggregate_policy_row[0])
                if aggregate_policy_row is not None and aggregate_policy_row[0]
                else "authority-unavailable"
            )
        seg_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS n
            FROM coverage_segments
            WHERE dataset=? AND policy_version=?
            GROUP BY status
            """,
            (dataset, effective_policy_version),
        ).fetchall()
        raw_counts = {
            str(row[0]): int(row[1]) for row in seg_rows if int(row[1]) > 0
        }
        status_counts = honest_status_counts(raw_counts)
        total = sum(status_counts.values())
        complete = int(status_counts.get("COMPLETE", 0))
        derived = aggregate_status_from_segment_counts(status_counts)

        dc = conn.execute(
            "SELECT status,policy_version,detail_json,observed_start,"
            "observed_end,row_count "
            "FROM dataset_coverage WHERE dataset=?",
            (dataset,),
        ).fetchone()
        if dc is None:
            results.append(
                {
                    "dataset": dataset,
                    "action": "skip_missing_dataset_coverage",
                    "status_counts": status_counts,
                    "derived_status": derived,
                    "total": total,
                    "complete": complete,
                }
            )
            continue

        old_status = str(dc[0] if not isinstance(dc, sqlite3.Row) else dc["status"])
        old_policy_version = str(
            dc[1] if not isinstance(dc, sqlite3.Row) else dc["policy_version"]
        )
        detail_raw = dc[2] if not isinstance(dc, sqlite3.Row) else dc["detail_json"]
        try:
            detail = json.loads(detail_raw or "{}")
            if not isinstance(detail, dict):
                detail = {}
        except (TypeError, ValueError, json.JSONDecodeError):
            detail = {}
        prev_counts = (detail.get("coverage_v2") or {}).get("status_counts")
        failing = _failing_checks_from_detail(detail)

        empty_complete = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM coverage_segments
                WHERE dataset=? AND policy_version=? AND status='COMPLETE'
                  AND (receipt_run_id IS NULL OR receipt_run_id=0)
                """,
                (dataset, effective_policy_version),
            ).fetchone()[0]
        )

        verification: ExactCoverageCompleteVerification | None = None
        inventory: ExactCoverageInventoryComparison | None = None
        inventory_status = "EXACT"
        receipt_status = "NOT_EVALUATED"
        inventory_reason: str | None = None
        inventory_detail: dict[str, Any]
        try:
            verification = verify_exact_coverage_complete(
                conn,
                (dataset,),
                target_end=inventory_target_end,
            )
        except CoverageInventoryAuthorityUnavailable as exc:
            inventory_status = "PENDING"
            inventory_reason = str(exc)
            inventory_detail = {
                "target_end": inventory_target_end,
                "reason": inventory_reason,
            }
        else:
            inventory = verification.inventory
            inventory_detail = verification.detail()
            if not inventory.exact:
                inventory_status = "MISMATCH"
                inventory_reason = "persisted segments do not equal canonical inventory"
            elif verification.complete_eligible:
                receipt_status = "VERIFIED"
            else:
                receipt_status = "INVALID"
                inventory_reason = "selected signed receipt closure is incomplete"

        base = {
            "dataset": dataset,
            "old_status": old_status,
            "old_policy_version": old_policy_version,
            "current_policy_version": effective_policy_version,
            "status_counts": status_counts,
            "prev_status_counts": prev_counts,
            "derived_status": derived,
            "total": total,
            "complete": complete,
            "failing_checks": len(failing),
            "empty_complete": empty_complete,
            "inventory_status": inventory_status,
            "selected_receipt_status": receipt_status,
            "inventory": inventory_detail,
            "dry_run": dry_run,
        }

        blocker: str | None = None
        if inventory_status == "PENDING":
            blocker = "inventory_authority_pending"
        elif inventory_status == "MISMATCH":
            blocker = "inventory_mismatch"
        elif receipt_status != "VERIFIED":
            blocker = "selected_receipt_invalid"
        elif (
            old_status == "COMPLETE"
            and old_policy_version != effective_policy_version
        ):
            blocker = "prior_aggregate_policy_mismatch"
        elif total <= 0:
            blocker = "empty_inventory"
        elif derived == "COMPLETE" and failing:
            blocker = "failing_checks"
        elif derived == "COMPLETE" and empty_complete > 0:
            blocker = "empty_complete_segments"
        elif derived == "COMPLETE" and old_status != "COMPLETE":
            blocker = "transition_authority_required"

        if blocker is not None:
            new_status = "FAILED" if derived == "FAILED" else "PARTIAL"
        elif derived == "FAILED":
            new_status = "FAILED"
        elif derived == "COMPLETE":
            new_status = "COMPLETE"
        else:
            new_status = "PARTIAL"

        new_counts = honest_status_counts(status_counts)
        prev_norm = honest_status_counts(prev_counts or {})
        status_same = old_status == new_status
        counts_same = prev_norm == new_counts

        # A non-exact or blocked verdict is material evidence even if the
        # aggregate was already non-COMPLETE; persist it instead of verify_only.
        if status_same and counts_same and blocker is None:
            results.append(
                {
                    **base,
                    "action": "verify_only",
                    "status": new_status,
                    "eligible": new_status == "COMPLETE",
                }
            )
            continue

        if blocker == "inventory_authority_pending":
            action = "inventory_authority_pending"
        elif blocker == "inventory_mismatch":
            action = "inventory_mismatch"
        elif blocker == "selected_receipt_invalid":
            action = "selected_receipt_invalid"
        elif blocker == "prior_aggregate_policy_mismatch":
            action = "prior_aggregate_policy_mismatch"
        elif blocker == "transition_authority_required":
            action = "transition_authority_required"
        elif blocker == "empty_inventory":
            action = "empty_inventory_rejected"
        elif blocker == "failing_checks":
            action = "failing_checks_rejected"
        elif blocker == "empty_complete_segments":
            action = "empty_complete_segments_rejected"
        elif old_status == "COMPLETE" and new_status != "COMPLETE":
            action = "demoted"
        else:
            action = "counts_refreshed"

        audit = {
            "at": evaluated_at,
            "reason": (
                inventory_reason
                or "existing COMPLETE retained after exact signed verification"
                if new_status == "COMPLETE"
                else inventory_reason
                or "fail-closed re-aggregate from exact coverage inventory"
            ),
            "prev_status": old_status,
            "new_status": new_status,
            "prev_policy_version": old_policy_version,
            "current_policy_version": effective_policy_version,
            "prev_status_counts": prev_counts,
            "inventory_status": inventory_status,
            "selected_receipt_status": receipt_status,
            "inventory": inventory_detail,
            "blocker": blocker,
            "wave": wave,
        }
        new_detail = build_surgical_reagg_detail(
            detail,
            status_counts=new_counts,
            required_segments=(
                len(inventory.expected_identities)
                if inventory is not None
                else None
            ),
            audit=audit,
        )
        detail_json = _canonical_json(new_detail)

        if not dry_run:
            if new_status == "COMPLETE":
                update_existing_complete_coverage_evidence(
                    conn,
                    dataset=dataset,
                    policy_version=effective_policy_version,
                    detail_json=detail_json,
                    evaluated_at=evaluated_at,
                )
            else:
                update_dataset_coverage_row(
                    conn,
                    dataset=dataset,
                    status=new_status,
                    detail_json=detail_json,
                    evaluated_at=evaluated_at,
                )

        results.append(
            {
                **base,
                "action": action,
                "from": old_status,
                "to": new_status,
                "status": new_status,
                "new_status_counts": new_counts,
                "blocker": blocker,
            }
        )

    post_platform = conn.execute(
        "SELECT COUNT(*) FROM coverage_segments WHERE status='COMPLETE'"
    ).fetchone()[0]
    if post_platform != pre_platform:
        raise RuntimeError(
            "coverage_segments mutated during surgical re-aggregate: "
            f"COMPLETE {pre_platform} -> {post_platform}"
        )

    for row in results:
        row["platform_complete_segs"] = post_platform
    return results


def sync_dataset_coverage_from_segments(
    conn: sqlite3.Connection,
    *,
    datasets: Iterable[str] | None = None,
    dry_run: bool = False,
    wave: str | None = None,
) -> list[dict[str, Any]]:
    """Run surgical aggregation under one pinned SQLite snapshot/write lock."""
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN" if dry_run else "BEGIN IMMEDIATE")
    try:
        results = _sync_dataset_coverage_from_segments_in_transaction(
            conn,
            datasets=datasets,
            dry_run=dry_run,
            wave=wave,
        )
        if owns_transaction:
            if dry_run:
                conn.rollback()
            else:
                conn.commit()
        return results
    except BaseException:
        if owns_transaction:
            conn.rollback()
        raise


def is_synthetic_receipt(receipt: CollectionReceipt) -> bool:
    return bool(receipt.digests.get("synthetic"))


def receipt_eligibility(receipt: CollectionReceipt) -> str:
    """TRUSTED_COLLECTION only with a scoped v3 closure, never issuer strings."""
    from storage.verified_receipt import (
        ReceiptVerificationError,
        require_verified_collection_closure,
    )

    try:
        require_verified_collection_closure(
            receipt,
            expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
            expected_authority_instance_digest=(
                PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
            ),
        )
    except ReceiptVerificationError:
        return "RECOVERED_RAW_ONLY"
    return "TRUSTED_COLLECTION"


def _has_nonempty_trusted_raw_evidence(closure: Any) -> bool:
    """COMPLETE needs raw_count>0 or signed EXPECTED_EMPTY_WITH_EVIDENCE.

    Unsigned ``[]`` / ``{"data":[]}`` is not expected-empty evidence.
    """
    if closure.raw_row_count > 0:
        return True
    return bool(closure.extra_digests.get(EXPECTED_EMPTY_WITH_EVIDENCE))


def is_complete_eligible_receipt(receipt: CollectionReceipt) -> bool:
    """COMPLETE only with a verified scoped v3 closure and trusted raw evidence."""
    from storage.verified_receipt import (
        ReceiptVerificationError,
        require_verified_collection_closure,
    )

    try:
        closure = require_verified_collection_closure(
            receipt,
            expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
            expected_authority_instance_digest=(
                PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
            ),
        )
    except ReceiptVerificationError:
        return False
    return _has_nonempty_trusted_raw_evidence(closure)


__all__ = [
    "CanonicalCoverageSegmentIdentity",
    "CollectionReceipt",
    "CoverageInventoryAuthorityUnavailable",
    "ExactCoverageCompleteVerification",
    "ExactCoverageInventoryComparison",
    "RequiredCoverageSegment",
    "EXPECTED_EMPTY_WITH_EVIDENCE",
    "SYNTHETIC_RECEIPT_MARKER",
    "build_collection_receipt",
    "build_synthetic_complete_receipt",
    "compute_raw_digest",
    "compare_exact_coverage_inventory",
    "coverage_gaps",
    "coverage_summary",
    "evaluate_segment",
    "evaluate_required_segments",
    "is_synthetic_receipt",
    "official_index_days",
    "plan_required_segments",
    "read_collection_receipts",
    "read_coverage_segments",
    "read_dataset_coverage",
    "record_collection_receipt",
    "record_required_segments",
    "refresh_coverage_ledger",
    "sync_dataset_coverage_from_segments",
    "verify_exact_coverage_complete",
]
