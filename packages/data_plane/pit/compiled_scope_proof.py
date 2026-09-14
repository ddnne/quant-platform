"""One transactional compiled-scope proof session.

Owns market-DB connection lifetime and SQL for READY and receipt-candidate
compiled-scope proof. Publication policy and TSE-prime universe resolution
stay in paper_runtime.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator, Mapping, Sequence

from data_contracts import coverage_contract_for
from ops.receipt_product import (
    measure_owned_product_artifact_body,
    open_stored_product_artifact,
    verify_full_segment_product_materialization,
)
from storage.coverage_ledger import CollectionReceipt
from storage.sqlite_store import SqliteStore
from storage.verified_receipt import require_verified_collection_closure

from .compiled_dependency_scope import (
    CompiledControlledSelection,
    _select_compiled_dependency_scope,
)
from .complete_master import _complete_master_day_slices_from_connection
from .errors import PitError
from .receipt_scope import load_collection_receipt_scope
from .scoped_selection import (
    _owned_scoped_research_owner_from_verified_witness,
    _require_active_sqlite_transaction,
)


class CompiledScopeProofSession:
    """Snapshot reader for one compiled-scope proof. Not a Connection API."""

    __slots__ = ("_conn",)

    def __init__(self, conn: sqlite3.Connection) -> None:
        _require_active_sqlite_transaction(conn)
        self._conn = conn

    def load_receipt_scope(
        self, datasets: Sequence[str]
    ) -> tuple[
        tuple[Mapping[str, Any], ...],
        tuple[Mapping[str, Any], ...],
        tuple[Mapping[str, Any], ...],
        tuple[Mapping[str, Any], ...],
    ]:
        _require_active_sqlite_transaction(self._conn)
        return load_collection_receipt_scope(self._conn, datasets)

    def collect_verified_receipt_backings(
        self,
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
        """Stream/measure catalog-owned artifacts on this snapshot.

        Unsigned or unclosed receipts are skipped, matching the prior
        prove-path ``except Exception: continue`` behavior.
        """

        _require_active_sqlite_transaction(self._conn)
        conn = self._conn
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

    def complete_master_day_slices(
        self,
        *,
        period_start: str,
        period_end: str,
        as_of_for_day: Mapping[str, str],
        expected_environment: str,
        expected_authority_instance_digest: str,
    ) -> Any:
        _require_active_sqlite_transaction(self._conn)
        return _complete_master_day_slices_from_connection(
            self._conn,
            period_start=period_start,
            period_end=period_end,
            as_of_for_day=as_of_for_day,
            expected_environment=expected_environment,
            expected_authority_instance_digest=expected_authority_instance_digest,
        )

    def select_compiled_dependency_scope(
        self,
        *,
        compiled: CompiledControlledSelection,
        observed_through: str,
        slices: Sequence[Any],
        resolved_universe: Any,
        witness: frozenset[str],
    ) -> Any:
        _require_active_sqlite_transaction(self._conn)
        owner = _owned_scoped_research_owner_from_verified_witness(
            self._conn, witness=frozenset(witness)
        )
        try:
            return _select_compiled_dependency_scope(
                self._conn,
                compiled=compiled,
                observed_through=observed_through,
                slices=slices,
                resolved_universe=resolved_universe,
                scoped_owner=owner,
            )
        except ValueError as exc:
            raise PitError(str(exc)) from exc

    def measure_receipt_snapshot_quality(
        self,
        *,
        period_start: str,
        period_end: str,
        required_datasets: Sequence[str],
    ) -> dict[str, Any]:
        from storage.coverage import measure_receipt_snapshot_quality

        _require_active_sqlite_transaction(self._conn)
        return measure_receipt_snapshot_quality(
            self._conn,
            period_start=period_start,
            period_end=period_end,
            required_datasets=required_datasets,
        )


def _session_on_connection(conn: sqlite3.Connection) -> CompiledScopeProofSession:
    if type(conn) is not sqlite3.Connection:
        raise PitError("compiled-scope proof requires sqlite3.Connection")
    conn.row_factory = sqlite3.Row
    if not conn.in_transaction:
        conn.execute("BEGIN")
    return CompiledScopeProofSession(conn)


@contextmanager
def compiled_scope_proof_session_from_store(
    store: object,
) -> Iterator[CompiledScopeProofSession]:
    """Own the job-store market connection for one compiled-scope snapshot."""

    if type(store) is not SqliteStore:
        raise TypeError(
            "receipt candidate scope requires the governed SqliteStore"
        )
    conn = store._conn  # noqa: SLF001 — data-plane store lifetime
    started = conn.in_transaction
    session = _session_on_connection(conn)
    try:
        yield session
    finally:
        if conn.in_transaction and not started:
            conn.rollback()


@contextmanager
def compiled_scope_proof_session_from_pinned_connection(
    conn: sqlite3.Connection,
) -> Iterator[CompiledScopeProofSession]:
    """Lend one already-pinned applied-mirror connection. Caller owns close."""

    yield _session_on_connection(conn)


__all__ = [
    "CompiledControlledSelection",
    "CompiledScopeProofSession",
    "compiled_scope_proof_session_from_pinned_connection",
    "compiled_scope_proof_session_from_store",
]
