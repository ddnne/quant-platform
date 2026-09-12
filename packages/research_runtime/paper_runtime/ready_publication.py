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
    PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST,
    PRODUCTION_RECEIPT_ENVIRONMENT,
)
from storage.coverage_ledger import CollectionReceipt
from ops.receipt_product import (
    catalog_owned_product_row_digests,
    measure_owned_product_artifact_body,
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
    expected_exact = frozenset(EXACT_FOUR_DATASET_IDS)
    if set(required_datasets) != expected_exact:
        raise MassResearchDisabledError(
            "exact-four PIT verifier dataset closure drifted"
        )

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
                    )

            verifier = _OwnedUniverseVerifier()

            if _authenticated_applied_mirror_connection_identity(conn) is not registered:
                raise PitError("READY publication connection identity swapped")
            stamped = exported_at
            proof_clock = PitReadClock(
                decision_at=close_as_of(period_end),
                observed_through=stamped,
                observation_label=SNAPSHOT_OBSERVATION_LABEL,
                promotable=True,
            )
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

            def load_receipt_scope(
                datasets: Sequence[str],
            ) -> tuple[
                tuple[dict[str, Any], ...],
                tuple[dict[str, Any], ...],
                tuple[dict[str, Any], ...],
                tuple[dict[str, Any], ...],
            ]:
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
                if not product_required <= table_columns(
                    "receipt_product_materializations"
                ):
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
                        "artifact_key,artifact_digest,artifact_body,row_count,"
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

            as_of_for_day = {
                day: morning_close_as_of(day)
                for day in _calendar_dates(period_start, period_end)
            }
            with install_read_clock(proof_clock):
                slices = verifier.resolve_day_slices(
                    period_start=period_start,
                    period_end=period_end,
                    as_of_for_day=as_of_for_day,
                )
            resolved_universe = resolve_tse_prime_with_fins(
                slices,
                period_start=period_start,
                period_end=period_end,
            )
            (
                collection_receipts,
                product_materializations,
                ingestion_runs,
                raw_retention_manifests,
            ) = load_receipt_scope(required_datasets)

            from pit.compiled_dependency_scope import (
                CompiledControlledSelection,
                _select_compiled_dependency_scope,
            )
            from pit.scoped_selection import (
                _owned_scoped_research_owner_from_verified_witness,
            )

            verified_row_backings: dict[str, dict[str, list[tuple[str, str]]]] = {
                dataset_id: {} for dataset_id in required_datasets
            }
            witness: set[str] = set()
            for raw in collection_receipts:
                stored = dict(raw)
                dataset_id = str(stored["dataset"])
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
                        expected_environment=PRODUCTION_RECEIPT_ENVIRONMENT,
                        expected_authority_instance_digest=(
                            PRODUCTION_RECEIPT_AUTHORITY_INSTANCE_DIGEST
                        ),
                        expected_policy_version=coverage_contract_for(
                            dataset_id
                        ).policy_version,
                    )
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
                    owned_digests = catalog_owned_product_row_digests(
                        conn,
                        source="jquants",
                        dataset=dataset_id,
                        segment_start=closure.segment_start,
                        segment_end=closure.segment_end,
                        observed_through=proof_clock.observed_through,
                        tables=(
                            "jquants_records",
                            "jquants_records_revisions",
                        ),
                    )
                    observed_count, observed_product_digest, observed_bytes, row_digests = (
                        measure_owned_product_artifact_body(
                            product.get("artifact_body"),
                            owned_digests=owned_digests,
                        )
                    )
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

            if not conn.in_transaction:
                conn.execute("BEGIN")
            owner = _owned_scoped_research_owner_from_verified_witness(
                conn, witness=frozenset(witness)
            )
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
                        "receipt_set_digest": canonical_digest(
                            sorted(used_receipts)
                        ),
                        "product_artifact_digests": sorted(used_products),
                        "product_artifact_set_digest": canonical_digest(
                            sorted(used_products)
                        ),
                    }
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
            return VerifiedPublicationEvidence({**body, "proof_digest": canonical_digest(body)})
    except PitError as exc:
        raise MassResearchDisabledError(str(exc)) from exc
    except sqlite3.Error as exc:
        raise MassResearchDisabledError(
            "PIT dependency scope query failed closed"
        ) from exc


__all__ = [
    "ReadyPublicationService",
    "VerifiedPublicationEvidence",
    "canonical_digest",
    "verify_controlled_publication_evidence",
]
