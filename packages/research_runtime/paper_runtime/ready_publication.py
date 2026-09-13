"""Trusted READY publication service. Product receives closed evidence only."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from core.execution import (
    close_as_of,
    morning_close_as_of,
)
from data_contracts import coverage_contract_for
from pit import PitError

from pit.read_clock import (
    PitReadClock,
    SNAPSHOT_OBSERVATION_LABEL,
    install_read_clock,
)
from research.universe_contract import (
    EXACT_FOUR_UNIVERSE_RULE_DIGEST,
    resolve_tse_prime_with_fins,
)
from selection.budget_ledger import MassResearchDisabledError
from paper_runtime.readiness_attestation import EXACT_FOUR_DATASET_IDS
from storage.receipt_crypto import (
    PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS,
    PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST,
    PRODUCTION_RECEIPT_ENVIRONMENT,
)
from storage.coverage_ledger import (
    CollectionReceipt,
    declared_coverage_segments,
    evaluate_segment,
)
from ops.receipt_product import (
    _aware_instant,
    measure_owned_product_artifact_body,
    open_stored_product_artifact,
    verify_full_segment_product_materialization,
)
from storage.verified_receipt import require_verified_collection_closure


def _calendar_dates(start: str, end: str) -> tuple[str, ...]:
    cursor = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    values: list[str] = []
    while cursor <= stop:
        values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return tuple(values)


def canonical_digest(payload: Mapping[str, Any] | Sequence[Any] | str) -> str:
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _closed_applied_mirror_identity(
    identity: Mapping[str, object],
) -> dict[str, Any]:
    """Copy the sealed identity. Callers cannot inject or omit fields."""

    if type(identity) is not MappingProxyType:
        raise PitError("READY publication identity is not authority-frozen")
    closed: dict[str, Any] = {}
    for key, value in identity.items():
        if isinstance(value, Mapping):
            closed[str(key)] = dict(value)
        else:
            closed[str(key)] = value
    return json.loads(
        json.dumps(closed, sort_keys=True, separators=(",", ":"), allow_nan=False)
    )


@dataclass(frozen=True, slots=True)
class VerifiedPublicationEvidence:
    """Closed READY publication result. Not a storage or SQL capability."""

    payload: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.payload)


class ReadyPublicationService:
    """Governed READY publication. Pre-READY scans stay closure-local."""

    def request_verified_publication(
        self,
        applied_mirror: object,
        binding: Any,
    ) -> VerifiedPublicationEvidence:
        """Publish request: closed evidence only. Not a catalog enumerator."""

        if isinstance(applied_mirror, (str, Path)):
            raise TypeError(
                "ReadyPublicationService does not accept a filesystem path"
            )
        from scripts.sync_d1_to_sqlite import (
            _consume_authenticated_applied_mirror_for_ready_publication,
        )

        return _consume_authenticated_applied_mirror_for_ready_publication(
            applied_mirror, binding
        )


def verify_controlled_publication_evidence(
    applied_mirror: object,
    binding: Any,
) -> VerifiedPublicationEvidence:
    """Consume one sealed applied-mirror handle through READY verification."""

    return ReadyPublicationService().request_verified_publication(
        applied_mirror, binding
    )


def _require_controlled_exact_four_binding(
    binding: Any,
) -> tuple[str, str, int, tuple[str, ...]]:
    periods = {
        (str(profile.period_start), str(profile.period_end))
        for profile in binding.profiles
    }
    if len(periods) != 1:
        raise MassResearchDisabledError(
            "exact-four plans must share one governed universe period"
        )
    period_start, period_end = next(iter(periods))
    from research.research_data_profile import (
        PROFILE_VERSION_V3,
        ResearchDataProfile,
    )

    if len(binding.profiles) != 4 or any(
        type(profile) is not ResearchDataProfile
        or profile.profile_version != PROFILE_VERSION_V3
        for profile in binding.profiles
    ):
        raise MassResearchDisabledError(
            "controlled READY requires four research-data-profile/v3 consumers"
        )
    max_lookback = max(
        int(scope["required_lookback_trading_days"])
        for profile in binding.profiles
        for scope in profile.dataset_scopes
    )
    required_datasets = tuple(binding.required_datasets)
    if set(required_datasets) != frozenset(EXACT_FOUR_DATASET_IDS):
        raise MassResearchDisabledError(
            "exact-four PIT verifier dataset closure drifted"
        )
    return period_start, period_end, max_lookback, required_datasets


def _max_original_checked_at(values: Sequence[str]) -> str:
    if not values:
        raise MassResearchDisabledError(
            "receipt candidate has no verified collection closures"
        )
    best = values[0]
    best_at = _aware_instant(best, label="receipt checked_at")
    for value in values[1:]:
        instant = _aware_instant(value, label="receipt checked_at")
        if instant > best_at:
            best = value
            best_at = instant
    return best


def _load_receipt_scope(
    conn: sqlite3.Connection,
    datasets: Sequence[str],
) -> tuple[
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
    tuple[dict[str, Any], ...],
]:
    catalog_required = {
        "source",
        "dataset",
        "natural_key",
        "event_time",
        "available_at",
        "ingested_at",
        "payload",
        "raw_payload",
    }
    receipt_required = {
        "source",
        "dataset",
        "segment_id",
        "segment_start",
        "segment_end",
        "expected_scope",
        "expected_items",
        "observed_items",
        "raw_page_count",
        "raw_row_count",
        "structured_row_count",
        "pagination_exhausted",
        "digests_json",
        "run_id",
        "status",
        "error",
        "checked_at",
    }
    product_required = {
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

    def table_columns(table: str) -> set[str]:
        return {
            str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")
        }

    columns = table_columns("jquants_records")
    if not catalog_required <= columns:
        raise PitError(
            "PIT dependency scope requires canonical jquants_records columns"
        )
    revision_columns = table_columns("jquants_records_revisions")
    if not catalog_required <= revision_columns:
        raise PitError(
            "PIT dependency scope requires canonical "
            "jquants_records_revisions columns"
        )
    placeholders = ",".join("?" for _ in datasets)
    if not receipt_required <= table_columns("collection_receipts"):
        raise PitError(
            "PIT dependency scope requires signed collection receipt columns"
        )
    if not product_required <= table_columns("receipt_product_materializations"):
        raise PitError(
            "PIT dependency scope requires receipt product materializations"
        )
    if "authority_operation_id" not in table_columns("ingestion_run_log"):
        raise PitError(
            "PIT dependency scope requires authority-bound ingestion runs"
        )
    collection_receipts = tuple(
        dict(row)
        for row in conn.execute(
            "SELECT * FROM collection_receipts WHERE source='jquants' "
            f"AND dataset IN ({placeholders}) ORDER BY checked_at,run_id",
            tuple(datasets),
        )
    )
    run_ids = tuple(
        dict.fromkeys(
            int(row["run_id"])
            for row in collection_receipts
            if row.get("run_id") is not None
        )
    )
    if not run_ids:
        return collection_receipts, (), (), ()
    run_placeholders = ",".join("?" for _ in run_ids)
    bound = tuple(datasets) + run_ids
    product_materializations = tuple(
        dict(row)
        for row in conn.execute(
            "SELECT operation_id,run_id,source,dataset,segment_id,"
            "artifact_key,artifact_digest,row_count,"
            "byte_count,manifest_key,manifest_digest,raw_manifest_key,"
            "raw_manifest_digest,raw_page_count,raw_row_count,"
            "raw_bytes,committed_at FROM receipt_product_materializations "
            "WHERE source='jquants' "
            f"AND dataset IN ({placeholders}) "
            f"AND run_id IN ({run_placeholders})",
            bound,
        )
    )
    ingestion_runs = tuple(
        dict(row)
        for row in conn.execute(
            "SELECT id,source,runtime,status,authority_operation_id "
            f"FROM ingestion_run_log WHERE id IN ({run_placeholders})",
            run_ids,
        )
    )
    raw_retention_manifests = tuple(
        dict(row)
        for row in conn.execute(
            "SELECT dataset,run_id,manifest_key,page_count,row_count,"
            "raw_bytes,data_digest FROM raw_retention_manifests "
            f"WHERE dataset IN ({placeholders}) "
            f"AND run_id IN ({run_placeholders})",
            bound,
        )
    )
    return (
        collection_receipts,
        product_materializations,
        ingestion_runs,
        raw_retention_manifests,
    )


def _resolve_controlled_universe(
    conn: sqlite3.Connection,
    *,
    period_start: str,
    period_end: str,
    observed_through: str,
    expected_environment: str,
    expected_authority_instance_digest: str,
):
    class _OwnedUniverseVerifier:
        """Purpose-specific universe capability. Not a SQL/path/row API."""

        def resolve_day_slices(
            self,
            *,
            period_start: str,
            period_end: str,
            as_of_for_day: Mapping[str, str],
        ):
            from pit.complete_master import (
                _complete_master_day_slices_from_connection,
            )

            return _complete_master_day_slices_from_connection(
                conn,
                period_start=period_start,
                period_end=period_end,
                as_of_for_day=as_of_for_day,
                expected_environment=expected_environment,
                expected_authority_instance_digest=(
                    expected_authority_instance_digest
                ),
            )

    proof_clock = PitReadClock(
        decision_at=close_as_of(period_end),
        observed_through=observed_through,
        observation_label=SNAPSHOT_OBSERVATION_LABEL,
        promotable=True,
    )
    as_of_for_day = {
        day: morning_close_as_of(day)
        for day in _calendar_dates(period_start, period_end)
    }
    with install_read_clock(proof_clock):
        slices = _OwnedUniverseVerifier().resolve_day_slices(
            period_start=period_start,
            period_end=period_end,
            as_of_for_day=as_of_for_day,
        )
    resolved_universe = resolve_tse_prime_with_fins(
        slices,
        period_start=period_start,
        period_end=period_end,
    )
    return proof_clock, slices, resolved_universe


def _collect_verified_receipt_backings(
    conn: sqlite3.Connection,
    *,
    collection_receipts: Sequence[Mapping[str, Any]],
    product_materializations: Sequence[Mapping[str, Any]],
    ingestion_runs: Sequence[Mapping[str, Any]],
    raw_retention_manifests: Sequence[Mapping[str, Any]],
    required_datasets: Sequence[str],
    expected_environment: str,
    expected_authority_instance_digest: str,
    measure_through: str | None,
    allowed_segments: frozenset[tuple[str, str]] | None,
) -> tuple[
    dict[str, dict[str, list[tuple[str, str]]]],
    set[str],
    tuple[str, ...],
    tuple[Mapping[str, Any], ...],
    tuple[Mapping[str, Any], ...],
]:
    verified_row_backings: dict[str, dict[str, list[tuple[str, str]]]] = {
        dataset_id: {} for dataset_id in required_datasets
    }
    witness: set[str] = set()
    accepted_clocks: list[str] = []
    accepted_runset: list[dict[str, Any]] = []
    accepted_bindings: list[dict[str, Any]] = []
    for raw in collection_receipts:
        stored = dict(raw)
        dataset_id = str(stored["dataset"])
        if allowed_segments is not None and (
            dataset_id,
            str(stored["segment_id"]),
        ) not in allowed_segments:
            continue
        try:
            expected_scope = json.loads(str(stored["expected_scope"]))
            digests = json.loads(str(stored["digests_json"]))
            receipt = CollectionReceipt(
                source=str(stored["source"]),
                dataset=dataset_id,
                segment_id=str(stored["segment_id"]),
                segment_start=str(stored["segment_start"]),
                segment_end=str(stored["segment_end"]),
                expected_scope=expected_scope,
                expected_items=(
                    None
                    if stored["expected_items"] is None
                    else int(stored["expected_items"])
                ),
                observed_items=int(stored["observed_items"]),
                raw_page_count=int(stored["raw_page_count"]),
                raw_row_count=int(stored["raw_row_count"]),
                structured_row_count=int(stored["structured_row_count"]),
                pagination_exhausted=bool(stored["pagination_exhausted"]),
                digests=digests,
                run_id=int(stored["run_id"]),
                status=str(stored["status"]),
                error=(
                    None if stored["error"] is None else str(stored["error"])
                ),
                checked_at=str(stored["checked_at"]),
            )
            closure = require_verified_collection_closure(
                receipt,
                expected_environment=expected_environment,
                expected_authority_instance_digest=(
                    expected_authority_instance_digest
                ),
                expected_policy_version=coverage_contract_for(
                    dataset_id
                ).policy_version,
            )
            if closure.environment != expected_environment:
                raise PitError("signed receipt environment does not match")
            product_rows = [
                row
                for row in product_materializations
                if row.get("source") == closure.source
                and row.get("dataset") == closure.dataset
                and row.get("segment_id") == closure.segment_id
                and row.get("run_id") == closure.run_id
            ]
            if len(product_rows) != 1:
                continue
            product = dict(product_rows[0])
            run_rows = [
                row
                for row in ingestion_runs
                if row.get("id") == closure.run_id
            ]
            raw_manifests = [
                row
                for row in raw_retention_manifests
                if row.get("dataset") == closure.dataset
                and row.get("run_id") == closure.run_id
            ]
            operation_id = str(product["operation_id"])
            receipt_clock = (
                measure_through
                if measure_through is not None
                else closure.checked_at
            )
            with open_stored_product_artifact(conn, operation_id) as artifact:
                observed_count, observed_product_digest, observed_bytes, row_digests = (
                    measure_owned_product_artifact_body(
                        artifact,
                        conn=conn,
                        source="jquants",
                        dataset=dataset_id,
                        segment_start=closure.segment_start,
                        segment_end=closure.segment_end,
                        observed_through=receipt_clock,
                        tables=(
                            "jquants_records",
                            "jquants_records_revisions",
                        ),
                    )
                )
            with open_stored_product_artifact(conn, operation_id) as artifact:
                verify_full_segment_product_materialization(
                    closure,
                    product=product,
                    run=run_rows[0] if len(run_rows) == 1 else None,
                    raw_manifest=(
                        raw_manifests[0] if len(raw_manifests) == 1 else None
                    ),
                    observed_count=observed_count,
                    observed_digest=observed_product_digest,
                    observed_bytes=observed_bytes,
                    artifact=artifact,
                )
        except Exception:
            continue
        backings = verified_row_backings[dataset_id]
        pair = (closure.receipt_digest, closure.structured_digest)
        for digest in row_digests:
            bucket = backings.setdefault(digest, [])
            if pair not in bucket:
                bucket.append(pair)
        if dataset_id in {"equities_bars_daily", "fins_summary"}:
            witness.update(row_digests)
        accepted_clocks.append(closure.checked_at)
        accepted_runset.append(
            {
                "artifact_digest": str(product["artifact_digest"]),
                "dataset": str(closure.dataset),
                "operation_id": str(operation_id),
                "raw_manifest_digest": str(closure.raw_manifest_digest),
                "receipt_digest": str(closure.receipt_digest),
                "run_id": int(closure.run_id),
                "segment_id": str(closure.segment_id),
                "structured_digest": str(closure.structured_digest),
            }
        )
        accepted_bindings.append(
            {
                "dataset": str(closure.dataset),
                "raw_manifest": (
                    dict(raw_manifests[0]) if len(raw_manifests) == 1 else None
                ),
                "raw_manifest_digest": str(closure.raw_manifest_digest),
                "receipt": receipt,
                "receipt_digest": str(closure.receipt_digest),
                "run_id": int(closure.run_id),
                "segment_id": str(closure.segment_id),
                "source": str(closure.source),
            }
        )
    return (
        verified_row_backings,
        witness,
        tuple(accepted_clocks),
        tuple(accepted_runset),
        tuple(accepted_bindings),
    )


def _receipt_runset_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    closed = list(rows)
    closed.sort(
        key=lambda row: (
            str(row["dataset"]),
            str(row["segment_id"]),
            int(row["run_id"]),
            str(row["operation_id"]),
        )
    )
    return canonical_digest(closed)


def _scoped_receipt_native_proofs(
    *,
    payload: Mapping[str, Any],
    accepted_bindings: Sequence[Mapping[str, Any]],
    lookback_start: str,
    period_end: str,
    selected_event_dates: Mapping[str, frozenset[str]],
    bar_split_interval_start: str | None,
    binding: Any,
    physical_digest: str,
    expected_environment: str,
    expected_authority_instance_digest: str,
) -> tuple[str, str, str, str | None]:
    from data_contracts.coverage import coverage_policy_set_binding
    from research.ready_manifest import MISSING

    cited: set[str] = set()
    for entry in payload.get("entries") or ():
        if not isinstance(entry, Mapping):
            continue
        receipts = entry.get("receipt_digests")
        if type(receipts) is not list:
            continue
        cited.update(str(item) for item in receipts if type(item) is str and item)

    def _identity_proofs(
        rows: Sequence[Mapping[str, Any]],
    ) -> tuple[str, str]:
        ordered = sorted(
            (dict(row) for row in rows),
            key=lambda row: (
                str(row["source"]),
                str(row["dataset"]),
                str(row["segment_id"]),
                int(row["run_id"]),
            ),
        )
        rebound: list[dict[str, Any]] = []
        for item in ordered:
            raw = item.get("raw_manifest")
            if (
                not isinstance(raw, Mapping)
                or str(raw.get("data_digest") or "")
                != str(item["raw_manifest_digest"])
            ):
                return MISSING, MISSING
            rebound.append(
                {
                    "dataset": str(item["dataset"]),
                    "manifest_key": str(raw["manifest_key"]),
                    "page_count": int(raw["page_count"]),
                    "raw_bytes": int(raw["raw_bytes"]),
                    "raw_manifest_digest": str(item["raw_manifest_digest"]),
                    "receipt_digest": str(item["receipt_digest"]),
                    "row_count": int(raw["row_count"]),
                    "run_id": int(item["run_id"]),
                    "segment_id": str(item["segment_id"]),
                    "source": str(item["source"]),
                }
            )
        return (
            canonical_digest(
                {"physical_digest": physical_digest, "raw": rebound}
            ),
            canonical_digest(
                {
                    "coverage_receipt_count": len(ordered),
                    "physical_digest": physical_digest,
                    "receipts": [
                        {
                            "dataset": str(row["dataset"]),
                            "receipt_digest": str(row["receipt_digest"]),
                            "run_id": int(row["run_id"]),
                            "segment_id": str(row["segment_id"]),
                            "source": str(row["source"]),
                        }
                        for row in ordered
                    ],
                }
            ),
        )

    selected = [
        dict(row)
        for row in accepted_bindings
        if str(row.get("receipt_digest") or "") in cited
    ]
    if not selected:
        return MISSING, MISSING, MISSING, "compiled selected receipts are missing"
    raw_proof, receipt_proof = _identity_proofs(selected)
    coverage_proof = MISSING
    reason: str | None = None
    try:
        policy_set = coverage_policy_set_binding(list(binding.required_datasets))
        planned = declared_coverage_segments(
            tuple(binding.required_datasets),
            lookback_start=lookback_start,
            period_end=period_end,
            selected_event_dates=selected_event_dates,
            bar_split_interval_start=bar_split_interval_start,
        )
        covered: list[dict[str, Any]] = []
        inventory: list[Mapping[str, Any]] = []
        by_identity: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
        for row in accepted_bindings:
            key = (
                str(row["source"]),
                str(row["dataset"]),
                str(row["segment_id"]),
            )
            by_identity.setdefault(key, []).append(row)
        for segment in planned:
            matches = by_identity.get(
                (segment.source, segment.dataset, segment.segment_id),
                (),
            )
            if len(matches) != 1:
                raise ValueError(
                    "declared segment "
                    f"{segment.dataset}/{segment.segment_id} "
                    "is not a unique signed closure"
                )
            match = matches[0]
            status, detail = evaluate_segment(
                coverage_contract_for(segment.dataset),
                segment,
                match.get("receipt"),
                expected_environment=expected_environment,
                expected_authority_instance_digest=(
                    expected_authority_instance_digest
                ),
            )
            raw = match.get("raw_manifest")
            if (
                status != "COMPLETE"
                or not isinstance(raw, Mapping)
                or str(raw.get("data_digest") or "")
                != str(match["raw_manifest_digest"])
            ):
                raise ValueError(
                    "declared segment "
                    f"{segment.dataset}/{segment.segment_id} "
                    f"is not a complete signed closure: {detail.get('reason')}"
                )
            covered.append(
                {
                    "dataset": segment.dataset,
                    "expected_items": segment.expected_items,
                    "expected_scope": dict(segment.expected_scope),
                    "receipt_digest": str(match["receipt_digest"]),
                    "run_id": int(match["run_id"]),
                    "segment_end": segment.segment_end,
                    "segment_id": segment.segment_id,
                    "segment_start": segment.segment_start,
                    "source": segment.source,
                }
            )
            inventory.append(match)
        covered.sort(
            key=lambda row: (
                row["source"],
                row["dataset"],
                row["segment_id"],
                row["run_id"],
            )
        )
        inventory_raw, inventory_receipt = _identity_proofs(inventory)
        if inventory_raw == MISSING or inventory_receipt == MISSING:
            raise ValueError(
                "declared coverage inventory raw identities are incomplete"
            )
        raw_proof = inventory_raw
        receipt_proof = inventory_receipt
        coverage_proof = canonical_digest(
            {
                "coverage_policy_digest": str(policy_set["policy_digest"]),
                "coverage_policy_version": str(policy_set["policy_version"]),
                "lookback_start": lookback_start,
                "lookback_trading_days": payload["lookback_trading_days"],
                "period_end": payload["period_end"],
                "period_start": payload["period_start"],
                "physical_digest": physical_digest,
                "profile_id": binding.profile_id,
                "profile_version": binding.profile_version,
                "segments": covered,
            }
        )
    except (KeyError, TypeError, ValueError) as exc:
        coverage_proof = MISSING
        reason = str(exc)
    return coverage_proof, raw_proof, receipt_proof, reason


def _prove_exact_four_compiled_scope(
    conn: sqlite3.Connection,
    binding: Any,
    *,
    expected_environment: str,
    expected_authority_instance_digest: str,
    snapshot_observed_through: str | None,
    physical_digest: str,
    allowed_segments: frozenset[tuple[str, str]] | None = None,
) -> tuple[
    VerifiedPublicationEvidence,
    str,
    str,
    tuple[
        tuple[Mapping[str, Any], ...],
        str,
        Mapping[str, frozenset[str]],
        str | None,
    ],
]:
    period_start, period_end, max_lookback, required_datasets = (
        _require_controlled_exact_four_binding(binding)
    )
    if not conn.in_transaction:
        conn.execute("BEGIN")
    (
        collection_receipts,
        product_materializations,
        ingestion_runs,
        raw_retention_manifests,
    ) = _load_receipt_scope(conn, required_datasets)
    backing_kwargs = {
        "collection_receipts": collection_receipts,
        "product_materializations": product_materializations,
        "ingestion_runs": ingestion_runs,
        "raw_retention_manifests": raw_retention_manifests,
        "required_datasets": required_datasets,
        "expected_environment": expected_environment,
        "expected_authority_instance_digest": expected_authority_instance_digest,
        "allowed_segments": allowed_segments,
    }
    if snapshot_observed_through is not None:
        observed_through = snapshot_observed_through
        proof_clock, slices, resolved_universe = _resolve_controlled_universe(
            conn,
            period_start=period_start,
            period_end=period_end,
            observed_through=observed_through,
            expected_environment=expected_environment,
            expected_authority_instance_digest=(
                expected_authority_instance_digest
            ),
        )
        verified_row_backings, witness, _accepted, runset_rows, accepted_bindings = (
            _collect_verified_receipt_backings(
                conn,
                measure_through=observed_through,
                **backing_kwargs,
            )
        )
    else:
        verified_row_backings, witness, accepted, runset_rows, accepted_bindings = (
            _collect_verified_receipt_backings(
                conn,
                measure_through=None,
                **backing_kwargs,
            )
        )
        observed_through = _max_original_checked_at(accepted)
        proof_clock, slices, resolved_universe = _resolve_controlled_universe(
            conn,
            period_start=period_start,
            period_end=period_end,
            observed_through=observed_through,
            expected_environment=expected_environment,
            expected_authority_instance_digest=(
                expected_authority_instance_digest
            ),
        )

    from pit.compiled_dependency_scope import (
        CompiledControlledSelection,
        _select_compiled_dependency_scope,
    )
    from pit.scoped_selection import (
        _owned_scoped_research_owner_from_verified_witness,
    )

    owner = _owned_scoped_research_owner_from_verified_witness(
        conn, witness=frozenset(witness)
    )
    try:
        selected_scope = _select_compiled_dependency_scope(
            conn,
            compiled=CompiledControlledSelection(
                period_start=period_start,
                period_end=period_end,
                lookback_trading_days=max_lookback,
                profile_digest=binding.profile_digest,
                feature_consumers=tuple(
                    profile.feature_consumers() for profile in binding.profiles
                ),
            ),
            observed_through=proof_clock.observed_through,
            slices=slices,
            resolved_universe=resolved_universe,
            scoped_owner=owner,
        )
    except ValueError as exc:
        raise PitError(str(exc)) from exc
    selected_keys = {
        dataset_id: set(selected_scope.selected_keys[dataset_id])
        for dataset_id in required_datasets
    }
    selected_digests = {
        dataset_id: set(selected_scope.selected_versions[dataset_id])
        for dataset_id in required_datasets
    }
    entries: list[dict[str, Any]] = []
    for dataset_id in required_datasets:
        selected = selected_keys[dataset_id]
        selected_versions = selected_digests[dataset_id]
        if not selected or not selected_versions:
            raise MassResearchDisabledError(
                f"PIT dependency scope selected no keys for {dataset_id}"
            )
        used_receipts: set[str] = set()
        used_products: set[str] = set()
        for digest in selected_versions:
            matches = verified_row_backings[dataset_id].get(digest, ())
            if not matches:
                raise MassResearchDisabledError(
                    "PIT dependency scope selected version is not bound to a "
                    f"current signed receipt: {dataset_id}"
                )
            for receipt_digest, product_digest in matches:
                used_receipts.add(receipt_digest)
                used_products.add(product_digest)
        entries.append(
            {
                "dataset_id": dataset_id,
                "natural_key_count": len(selected),
                "natural_key_digest": canonical_digest(sorted(selected)),
                "receipt_digests": sorted(used_receipts),
                "receipt_set_digest": canonical_digest(sorted(used_receipts)),
                "product_artifact_digests": sorted(used_products),
                "product_artifact_set_digest": canonical_digest(
                    sorted(used_products)
                ),
            }
        )
    body = {
        "format": "pit-dependency-scope-proof/v1",
        "status": "PASS",
        "profile_digest": binding.profile_digest,
        "plan_set_digest": binding.plan_set_digest,
        "dependency_closure_digest": binding.closure_set_digest,
        "universe_rule_digest": EXACT_FOUR_UNIVERSE_RULE_DIGEST,
        "resolved_universe_digest": (
            resolved_universe.resolved_membership_digest
        ),
        "universe_daily_summary": [
            {
                "decision_date": day,
                "member_count": len(codes),
                "membership_digest": canonical_digest(list(codes)),
            }
            for day, codes in resolved_universe.decision_memberships
        ],
        "period_start": period_start,
        "period_end": period_end,
        "lookback_trading_days": max_lookback,
        "physical_db_digest": physical_digest,
        "entries": entries,
        "product_materialization_digest": canonical_digest(
            [
                {
                    "dataset_id": entry["dataset_id"],
                    "product_artifact_digests": entry[
                        "product_artifact_digests"
                    ],
                }
                for entry in entries
            ]
        ),
    }
    return (
        VerifiedPublicationEvidence(
            {**body, "proof_digest": canonical_digest(body)}
        ),
        observed_through,
        _receipt_runset_digest(runset_rows),
        (
            tuple(accepted_bindings),
            selected_scope.lookback_start,
            selected_scope.selected_event_dates,
            selected_scope.bar_split_interval_start,
        ),
    )


def _verify_publication_on_authenticated_mirror(
    conn: sqlite3.Connection,
    identity: Mapping[str, object],
    binding: Any,
) -> VerifiedPublicationEvidence:
    """Prove the exact natural-key closure consumed by the controlled pilot.

    A single historical row cannot prove a period.  This gate derives the
    versioned daily universe from the candidate snapshot, enumerates every
    calendar/master/bar/TOPIX/financials key needed by that universe and its
    longest lookback, enforces ``available_at <= decision as_of``, and then
    requires every selected version digest to belong to a verified v4 signed
    collection closure whose immutable artifact is catalog-owned on CURRENT
    and REVISION rows.
    Catalog and product scans are closure-local: they never accept a caller
    clock, token, or path, and they never escape as rows or connections.
    """

    from scripts.sync_d1_to_sqlite import (
        _authenticated_applied_mirror_connection_identity,
        _canonical_applied_mirror_identity_json,
        _require_canonical_applied_mirror_exported_at,
    )

    if type(conn) is not sqlite3.Connection:
        raise MassResearchDisabledError(
            "READY publication requires the pinned applied-mirror connection"
        )
    registered = _authenticated_applied_mirror_connection_identity(conn)
    if registered is None:
        raise MassResearchDisabledError(
            "READY publication connection is not the authenticated applied mirror"
        )
    try:
        closed_identity = _closed_applied_mirror_identity(identity)
        _canonical_applied_mirror_identity_json(dict(closed_identity))
        exported_at = _require_canonical_applied_mirror_exported_at(
            closed_identity.get("exported_at")
        )
        if closed_identity["exported_at"] != exported_at:
            raise PitError("READY publication identity is not canonical")
        physical_digest = registered.digest
        conn.row_factory = sqlite3.Row
        with nullcontext(conn) as conn:
            if _authenticated_applied_mirror_connection_identity(conn) is not registered:
                raise PitError("READY publication connection identity swapped")
            evidence, _observed_through, _runset_digest, _proof_scope = _prove_exact_four_compiled_scope(
                conn,
                binding,
                expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
                expected_authority_instance_digest=(
                    PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
                ),
                snapshot_observed_through=exported_at,
                physical_digest=physical_digest,
            )
            final_registered = _authenticated_applied_mirror_connection_identity(
                conn
            )
            if (
                final_registered is not registered
                or final_registered.digest != physical_digest
            ):
                raise PitError(
                    "physical DB digest does not match the prepared snapshot"
                )
            return evidence
    except PitError as exc:
        raise MassResearchDisabledError(str(exc)) from exc
    except sqlite3.Error as exc:
        raise MassResearchDisabledError(
            "PIT dependency scope query failed closed"
        ) from exc


RECEIPT_CANDIDATE_OBSERVATION_POLICY = "max_verified_claims_checked_at"
RECEIPT_CANDIDATE_SCOPE_DIAGNOSTIC_KIND = (
    "receipt-candidate-scope-diagnostic/v1"
)
RECEIPT_CANDIDATE_SNAPSHOT_QUALITY_KIND = (
    "receipt-candidate-snapshot-quality/v1"
)


def verify_committed_receipt_candidate_scope(
    store: object,
    *,
    binding: Any,
    environment: str,
    allowed_segments: frozenset[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Non-READY compiled-scope diagnostic on a job-owned committed store.

    Discards the full pit-dependency-scope-proof body so the 64KiB job
    terminal stays compact. Not a READY attestation or signer input.
    Snapshot B0/B4/C8 are read-only measures on this sqlite, not Ops B0
    and not official-domain COMPLETE.
    """

    from ops.receipt_candidate_materialize import (
        freeze_receipt_candidate_snapshot,
        hash_receipt_candidate_snapshot,
    )
    from storage.coverage import measure_receipt_snapshot_quality
    from storage.sqlite_store import SqliteStore

    if type(store) is not SqliteStore:
        raise TypeError(
            "receipt candidate scope requires the governed SqliteStore"
        )
    if environment not in PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS:
        raise MassResearchDisabledError(
            "receipt candidate environment is not pinned"
        )
    periods = {
        (str(profile.period_start), str(profile.period_end))
        for profile in binding.profiles
        if getattr(profile, "period_start", None)
        and getattr(profile, "period_end", None)
    }
    if len(periods) != 1:
        raise MassResearchDisabledError(
            "exact-four plans must share one governed universe period"
        )
    period_start, period_end = next(iter(periods))
    conn = store._conn  # noqa: SLF001
    freeze_receipt_candidate_snapshot(store)
    physical_digest = hash_receipt_candidate_snapshot(store)
    started = conn.in_transaction
    compiled: dict[str, Any] = {
        "compiled_scope_status": "FAIL",
        "compiled_scope_kind": RECEIPT_CANDIDATE_SCOPE_DIAGNOSTIC_KIND,
        "physical_db_digest": physical_digest,
    }
    try:
        conn.row_factory = sqlite3.Row
        evidence, observed_through, runset_digest, proof_scope = (
            _prove_exact_four_compiled_scope(
                conn,
                binding,
                expected_environment=environment,
                expected_authority_instance_digest=(
                    PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS[environment]
                ),
                snapshot_observed_through=None,
                physical_digest=physical_digest,
                allowed_segments=allowed_segments,
            )
        )
        payload = evidence.as_dict()
        if payload.get("physical_db_digest") != physical_digest:
            raise MassResearchDisabledError(
                "physical DB digest does not match the prepared snapshot"
            )
        receipt_source = {
            "kind": "governed-receipt-candidate",
            "environment": environment,
            "authority_instance_digest": (
                PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS[environment]
            ),
            "physical_digest": physical_digest,
            "observation_policy": RECEIPT_CANDIDATE_OBSERVATION_POLICY,
            "observed_through": observed_through,
            "compiled_scope_proof_digest": payload["proof_digest"],
            "receipt_runset_digest": runset_digest,
        }
        compiled = {
            "compiled_scope_status": "PASS",
            "compiled_scope_kind": RECEIPT_CANDIDATE_SCOPE_DIAGNOSTIC_KIND,
            "observation_policy": RECEIPT_CANDIDATE_OBSERVATION_POLICY,
            "observation_checked_at": observed_through,
            "compiled_scope_proof_digest": payload["proof_digest"],
            "physical_db_digest": physical_digest,
            "receipt_source": receipt_source,
        }
    except (MassResearchDisabledError, PitError, sqlite3.Error) as exc:
        compiled = {
            "compiled_scope_status": "FAIL",
            "compiled_scope_kind": RECEIPT_CANDIDATE_SCOPE_DIAGNOSTIC_KIND,
            "compiled_scope_error": str(exc),
            "physical_db_digest": physical_digest,
        }
    finally:
        if conn.in_transaction and not started:
            conn.rollback()
    if hash_receipt_candidate_snapshot(store) != physical_digest:
        raise MassResearchDisabledError(
            "physical DB digest does not match the prepared snapshot"
        )
    measured = measure_receipt_snapshot_quality(
        store.path,
        period_start=period_start,
        period_end=period_end,
        required_datasets=binding.required_datasets,
    )
    if hash_receipt_candidate_snapshot(store) != physical_digest:
        raise MassResearchDisabledError(
            "physical DB digest does not match the prepared snapshot"
        )
    runset_digest = None
    source = compiled.get("receipt_source")
    if isinstance(source, Mapping):
        runset_digest = source.get("receipt_runset_digest")
    quality = {
        "kind": RECEIPT_CANDIDATE_SNAPSHOT_QUALITY_KIND,
        "physical_digest": physical_digest,
        "profile_digest": binding.profile_digest,
        "plan_set_digest": binding.plan_set_digest,
        "dependency_closure_digest": binding.closure_set_digest,
        "receipt_runset_digest": runset_digest,
        "observation_policy": RECEIPT_CANDIDATE_OBSERVATION_POLICY,
        "observed_through": compiled.get("observation_checked_at"),
        **measured,
    }
    quality_digest = canonical_digest(quality)
    proof_context = {
        "physical_digest": physical_digest,
        "profile_digest": binding.profile_digest,
        "plan_set_digest": binding.plan_set_digest,
        "dependency_closure_digest": binding.closure_set_digest,
        "receipt_runset_digest": runset_digest,
        "period_start": period_start,
        "period_end": period_end,
        "observation_policy": RECEIPT_CANDIDATE_OBSERVATION_POLICY,
        "observed_through": compiled.get("observation_checked_at"),
    }
    b0_proof_digest = canonical_digest({**proof_context, "b0": quality["b0"]})
    b4_proof_digest = canonical_digest({**proof_context, "b4": quality["b4"]})
    compiled["snapshot_quality_kind"] = RECEIPT_CANDIDATE_SNAPSHOT_QUALITY_KIND
    compiled["snapshot_quality_digest"] = quality_digest
    compiled["snapshot_b0_status"] = quality["b0_status"]
    compiled["snapshot_b4_status"] = quality["b4_status"]
    compiled["snapshot_c8_status"] = quality["c8_status"]
    compiled["b0_proof_digest"] = b0_proof_digest
    compiled["b4_proof_digest"] = b4_proof_digest
    compiled["validation_proof_digest"] = quality_digest
    compiled["snapshot_quality"] = quality
    if compiled.get("compiled_scope_status") == "PASS":
        from research.ready_manifest import (
            MISSING as READY_MISSING,
            build_receipt_native_ready_manifest,
            generation_pins,
        )

        feature_generation, catalog_generation = generation_pins(
            profile_digest=binding.profile_digest,
            feature_dependencies=binding.feature_dependencies,
            contract_versions=binding.contract_versions,
            dataset_ids=binding.required_datasets,
        )
        (
            accepted_bindings,
            lookback_start,
            selected_event_dates,
            bar_split_interval_start,
        ) = proof_scope
        coverage_proof, raw_proof, receipt_proof, coverage_reason = (
            _scoped_receipt_native_proofs(
                payload=payload,
                accepted_bindings=accepted_bindings,
                lookback_start=lookback_start,
                period_end=period_end,
                selected_event_dates=selected_event_dates,
                bar_split_interval_start=bar_split_interval_start,
                binding=binding,
                physical_digest=physical_digest,
                expected_environment=environment,
                expected_authority_instance_digest=(
                    PINNED_RECEIPT_AUTHORITY_INSTANCE_DIGESTS[environment]
                ),
            )
        )
        if coverage_reason:
            compiled["coverage_proof_reason"] = coverage_reason
        if hash_receipt_candidate_snapshot(store) != physical_digest:
            raise MassResearchDisabledError(
                "physical DB digest does not match the prepared snapshot"
            )
        receipt_manifest = build_receipt_native_ready_manifest(
            compiled["receipt_source"],
            binding=binding,
            created_at=READY_MISSING,
            published_at=READY_MISSING,
            b0_proof_digest=b0_proof_digest,
            b4_proof_digest=b4_proof_digest,
            validation_proof_digest=quality_digest,
            resolved_universe_digest=payload["resolved_universe_digest"],
            feature_generation=feature_generation,
            catalog_generation=catalog_generation,
            coverage_proof_digest=coverage_proof,
            raw_proof_digest=raw_proof,
            receipt_proof_digest=receipt_proof,
        )
        compiled["receipt_native_manifest"] = receipt_manifest.to_dict()
        compiled["receipt_native_manifest_digest"] = receipt_manifest.manifest_digest
    return compiled


__all__ = [
    "RECEIPT_CANDIDATE_OBSERVATION_POLICY",
    "RECEIPT_CANDIDATE_SCOPE_DIAGNOSTIC_KIND",
    "RECEIPT_CANDIDATE_SNAPSHOT_QUALITY_KIND",
    "ReadyPublicationService",
    "VerifiedPublicationEvidence",
    "canonical_digest",
    "verify_committed_receipt_candidate_scope",
    "verify_controlled_publication_evidence",
]
