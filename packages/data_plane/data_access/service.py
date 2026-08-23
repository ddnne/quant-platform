"""Shared read-domain service for Ops-current and Research-READY clients.

The two planes deliberately have different consistency contracts:

* ``OpsCurrentReadService`` reads the mutable local control database. Its
  results are operational observations and are never research facts.
* ``ResearchReadyReadService`` composes :class:`QuantDataAccess`, preserving
  its READY-only, PIT-bounded behavior.

Only named domain operations cross this boundary. Callers cannot provide SQL,
filesystem paths, storage handles, URLs, or mutation instructions.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from data_contracts import all_coverage_contracts

from .adapter import QuantDataAccess


DEFAULT_OPS_DB = Path("data/structured/ingestion.sqlite")
RESEARCH_READY_METHODS = frozenset({
    "list_datasets",
    "describe_dataset",
    "coverage_summary",
    "dataset_coverage",
    "coverage_gaps",
    "latest_ready_snapshot",
    "describe_snapshot",
    "diff_snapshots",
    "quality_summary",
    "quality_failures",
    "query_dataset",
    "get_series",
    "compute_feature",
    "compute_features",
    "raw_manifest",
    "trace_provenance",
})
OPS_CURRENT_METHODS = frozenset({
    "ops_status",
    "ingestion_last_run",
    "dataset_coverage",
    "coverage_gaps",
    "coverage_segments",
    "backfill_status",
    "validation_summary",
    "b0_status",
    "raw_retention_status",
    "sync_status",
    "storage_plane_status",
})


def _plane(value: Any, *, name: str, mutable: bool) -> dict[str, Any]:
    body = dict(value) if isinstance(value, Mapping) else {"result": value}
    return {**body, "plane": name, "mutable": mutable}


def _stored_policy_version(row: Mapping[str, Any] | None) -> str:
    if not isinstance(row, Mapping):
        return ""
    policy = row.get("policy_version")
    if isinstance(policy, str) and policy.strip():
        return policy.strip()
    return ""


def _coverage_projection_missing_reason(
    row: Mapping[str, Any] | None = None,
) -> str:
    # Echo stored policy_version. Live projection is still collection-coverage/v2
    # STALE; never freeze "Coverage V2" or invent unpublished V3.
    policy = _stored_policy_version(row)
    if policy:
        return f"Coverage projection ({policy}) has not been populated"
    return "Coverage projection has not been populated"


class ResearchReadyReadService:
    """Immutable research interface backed only by published READY data."""

    plane = "research_ready"
    mutable = False

    def __init__(self, access: QuantDataAccess) -> None:
        self.access = access

    def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        if name not in RESEARCH_READY_METHODS:
            raise KeyError(f"unknown Research READY read: {name!r}")
        method = getattr(self.access, name)
        value = method(**dict(arguments or {}))
        return _plane(value, name=self.plane, mutable=self.mutable)

    def latest_ready_snapshot(self) -> dict[str, Any]:
        return self.call_tool("latest_ready_snapshot")

    def snapshot_quality(self, snapshot_id: str | None = None) -> dict[str, Any]:
        arguments = {"snapshot_id": snapshot_id} if snapshot_id is not None else {}
        return self.call_tool("quality_summary", arguments)


class OpsCurrentReadService:
    """Read-only operational interface over the mutable control database."""

    plane = "ops_current"
    mutable = True
    _SEGMENT_STATUSES = frozenset({
        "COMPLETE", "PARTIAL", "FAILED", "UNKNOWN", "STALE"
    })

    def __init__(self, db_path: str | Path = DEFAULT_OPS_DB) -> None:
        self.db_path = Path(db_path)
        # Ops visibility follows the governed Coverage catalog, which includes
        # J-Quants and JSDA. Research fact allowlists remain separately owned
        # by QuantDataAccess/READY.
        self._datasets = frozenset(
            item.dataset_id for item in all_coverage_contracts()
        )

    def _connect(self) -> sqlite3.Connection | None:
        if not self.db_path.is_file():
            return None
        path = self.db_path.resolve()
        conn = sqlite3.connect(
            "file:" + quote(str(path)) + "?mode=ro",
            uri=True,
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _all(
        self, sql: str, parameters: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        if conn is None:
            return []
        try:
            return [dict(row) for row in conn.execute(sql, parameters)]
        except sqlite3.OperationalError as exc:
            # Older local mirrors legitimately lack newer control tables. An
            # empty/UNKNOWN domain result is more useful than treating that as
            # evidence, while unrelated database failures still surface.
            message = str(exc).lower()
            if "no such table" in message or "no such column" in message:
                return []
            raise
        finally:
            conn.close()

    def _one(
        self, sql: str, parameters: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        rows = self._all(sql, parameters)
        return rows[0] if rows else None

    def _result(self, **values: Any) -> dict[str, Any]:
        return _plane(values, name=self.plane, mutable=self.mutable)

    def _require_dataset(self, dataset: Any) -> str:
        value = str(dataset).strip()
        if value not in self._datasets:
            raise PermissionError(f"dataset is not allowlisted: {value!r}")
        return value

    def ingestion_last_run(self) -> dict[str, Any]:
        run = self._one(
            "SELECT id, ran_at, source, runtime, status, detail "
            "FROM ingestion_run_log ORDER BY id DESC LIMIT 1"
        )
        return self._result(run=run)

    def dataset_coverage(self, dataset: str) -> dict[str, Any]:
        dataset = self._require_dataset(dataset)
        coverage = self._one(
            "SELECT * FROM dataset_coverage WHERE dataset=? LIMIT 1",
            (dataset,),
        )
        if coverage is None:
            return self._result(
                dataset=dataset,
                status="UNKNOWN",
                coverage=None,
                reason=_coverage_projection_missing_reason(coverage),
            )
        return self._result(
            dataset=dataset,
            status=coverage.get("status", "UNKNOWN"),
            coverage=coverage,
        )

    def coverage_gaps(self) -> dict[str, Any]:
        rows = self._all(
            "SELECT * FROM dataset_coverage ORDER BY dataset LIMIT 500"
        )
        present = {
            str(row.get("dataset")): row
            for row in rows
            if row.get("dataset") in self._datasets
        }
        gaps = []
        for dataset in sorted(self._datasets):
            row = present.get(dataset)
            if row is None:
                gaps.append({
                    "dataset": dataset,
                    "status": "UNKNOWN",
                    "reason": _coverage_projection_missing_reason(row),
                })
            elif row.get("status") != "COMPLETE":
                gaps.append(row)
        return self._result(
            status=(
                "UNKNOWN" if not rows else
                "INCOMPLETE" if gaps else "COMPLETE"
            ),
            governed_dataset_count=len(self._datasets),
            gaps=gaps,
        )

    def coverage_segments(
        self,
        dataset: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        size = int(limit)
        if not 1 <= size <= 500:
            raise ValueError("limit must be between 1 and 500")
        clauses: list[str] = []
        values: list[Any] = []
        if dataset is not None:
            clauses.append("dataset=?")
            values.append(self._require_dataset(dataset))
        if status is not None:
            normalized = str(status).upper()
            if normalized not in self._SEGMENT_STATUSES:
                raise ValueError(f"unknown coverage segment status: {status!r}")
            clauses.append("status=?")
            values.append(normalized)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self._all(
            "SELECT * FROM coverage_segments" + where
            + " ORDER BY dataset, segment_start, segment_id LIMIT ?",
            (*values, size),
        )
        return self._result(
            status="AVAILABLE" if rows else "UNKNOWN",
            **({} if rows else {
                "reason": _coverage_projection_missing_reason()
            }),
            segments=rows,
            limit=size,
        )

    def backfill_status(self, dataset: str | None = None) -> dict[str, Any]:
        where = ""
        parameters: tuple[Any, ...] = ()
        if dataset is not None:
            where = " WHERE dataset=?"
            parameters = (self._require_dataset(dataset),)
        rows = self._all(
            "SELECT dataset, COUNT(*) AS required_segments, "
            "SUM(CASE WHEN status='COMPLETE' THEN 1 ELSE 0 END) "
            "AS complete_segments, "
            "SUM(CASE WHEN status<>'COMPLETE' THEN 1 ELSE 0 END) "
            "AS remaining_segments FROM coverage_segments" + where
            + " GROUP BY dataset ORDER BY dataset",
            parameters,
        )
        if rows:
            return self._result(status="AVAILABLE", datasets=rows)
        requested = (
            [self._require_dataset(dataset)]
            if dataset is not None else sorted(self._datasets)
        )
        return self._result(
            status="UNKNOWN",
            reason=_coverage_projection_missing_reason(),
            datasets=[{
                "dataset": item,
                "required_segments": None,
                "complete_segments": None,
                "remaining_segments": None,
            } for item in requested],
        )

    def validation_summary(self) -> dict[str, Any]:
        latest = self._one(
            "SELECT MAX(run_id) AS run_id FROM ingestion_validation"
        )
        run_id = latest.get("run_id") if latest else None
        rows = [] if run_id is None else self._all(
            "SELECT dataset, status, rows_seen, rows_inserted, "
            "rows_revisions, detail FROM ingestion_validation "
            "WHERE run_id=? ORDER BY dataset LIMIT 500",
            (run_id,),
        )
        failures = [row for row in rows if row.get("status") != "pass"]
        status = "PASS" if rows and not failures else (
            "FAIL" if rows else "UNKNOWN"
        )
        return self._result(
            run_id=run_id,
            status=status,
            dataset_count=len(rows),
            failures=failures,
        )

    def b0_status(self) -> dict[str, Any]:
        row = self._one(
            "SELECT status, policy_version, evaluated_at AS checked_at, "
            "summary_json, results_json, build_id "
            "FROM snapshot_quality_results ORDER BY evaluated_at DESC LIMIT 1"
        )
        if row is None:
            return self._result(
                status="UNKNOWN",
                reason="snapshot quality/B0 has not been evaluated in the current control database",
            )
        return self._result(**row)

    def raw_retention_status(
        self, dataset: str | None = None
    ) -> dict[str, Any]:
        where = ""
        parameters: tuple[Any, ...] = ()
        if dataset is not None:
            where = " WHERE dataset=?"
            parameters = (self._require_dataset(dataset),)
        rows = self._all(
            "SELECT dataset, run_id, manifest_key, page_count, row_count, "
            "raw_bytes, data_digest, completeness, created_at "
            "FROM raw_retention_manifests" + where
            + " ORDER BY run_id DESC, dataset LIMIT 500",
            parameters,
        )
        return self._result(attestations=rows)

    def sync_status(self) -> dict[str, Any]:
        watermarks = self._all(
            "SELECT * FROM ingestion_watermarks ORDER BY dataset LIMIT 500"
        )
        change = self._one(
            "SELECT MAX(change_seq) AS latest_change_seq "
            "FROM ingestion_change_log"
        )
        return self._result(
            watermarks=watermarks,
            latest_change_seq=(change or {}).get("latest_change_seq"),
        )

    def storage_plane_status(self) -> dict[str, Any]:
        """CF-native P0 counts-only proof (hot window / cold residual / JSDA).

        Fact-table counts are **plane-local** (this DB). Dataset COMPLETE is
        **receipt-owned** via ``dataset_coverage`` / ``coverage_segments`` and
        may be projected without a matching full fact backfill on D1. Do not
        treat ``tokyo_repo_rows == 0`` as contradiction of coverage COMPLETE
        without checking ``jsda.coverage`` and the plane identity.
        """
        hot_cutoff = "2026-07-01"

        def count(sql: str, params: tuple[Any, ...] = ()) -> int:
            try:
                row = self._one(sql, params)
            except Exception:
                return 0
            if not row:
                return 0
            for key in ("n", "c", "count"):
                if key in row and row[key] is not None:
                    return int(row[key])
            return 0

        jquants_total = count("SELECT COUNT(*) AS n FROM jquants_records")
        bars_hot = count(
            "SELECT COUNT(*) AS n FROM jquants_records "
            "WHERE dataset='equities_bars_daily' AND substr(event_time,1,10) >= ?",
            (hot_cutoff,),
        )
        bars_cold = count(
            "SELECT COUNT(*) AS n FROM jquants_records "
            "WHERE dataset='equities_bars_daily' AND substr(event_time,1,10) < ?",
            (hot_cutoff,),
        )
        master_hot = count(
            "SELECT COUNT(*) AS n FROM jquants_records "
            "WHERE dataset='equities_master' AND substr(event_time,1,10) >= ?",
            (hot_cutoff,),
        )
        change_log = count("SELECT COUNT(*) AS n FROM ingestion_change_log")
        complete = count(
            "SELECT COUNT(*) AS n FROM coverage_segments WHERE status='COMPLETE'"
        )
        otc = count("SELECT COUNT(*) AS n FROM jsda_otc_bond_reference_prices")
        corp = count("SELECT COUNT(*) AS n FROM jsda_corporate_bond_transactions")
        repo = count("SELECT COUNT(*) AS n FROM jsda_repo_rates")
        legacy_bars = count("SELECT COUNT(*) AS n FROM jquants_daily_bars")
        legacy_listed = count("SELECT COUNT(*) AS n FROM jquants_listed_info")
        legacy_cal = count("SELECT COUNT(*) AS n FROM jquants_market_calendar")
        stage_primary = count(
            "SELECT COUNT(*) AS n FROM jquants_records_nk_v2_primary_stage"
        )
        stage_chg = count(
            "SELECT COUNT(*) AS n FROM ingestion_change_log_nk_v2_stage"
        )
        empty_legacy = (
            legacy_bars == 0 and legacy_listed == 0 and legacy_cal == 0
        )
        # Coverage ledger (receipt-owned COMPLETE) vs fact-table counts.
        jsda_cov_rows = self._all(
            "SELECT dataset, status, row_count, observed_start, observed_end "
            "FROM dataset_coverage WHERE dataset LIKE 'jsda_%' "
            "ORDER BY dataset"
        ) or []
        jsda_coverage: dict[str, Any] = {}
        for row in jsda_cov_rows:
            ds = str(row.get("dataset") or "")
            if not ds:
                continue
            jsda_coverage[ds] = {
                "status": row.get("status"),
                "coverage_row_count": int(row.get("row_count") or 0),
                "observed_start": row.get("observed_start"),
                "observed_end": row.get("observed_end"),
            }
        fact_by_dataset = {
            "jsda_otc_bond_reference_prices": otc,
            "jsda_corporate_bond_transactions": corp,
            "jsda_tokyo_repo_rates": repo,
        }
        fact_table_by_dataset = {
            "jsda_otc_bond_reference_prices": "jsda_otc_bond_reference_prices",
            "jsda_corporate_bond_transactions": "jsda_corporate_bond_transactions",
            "jsda_tokyo_repo_rates": "jsda_repo_rates",
        }
        divergence: list[dict[str, Any]] = []
        for ds, fact_n in fact_by_dataset.items():
            cov = jsda_coverage.get(ds) or {}
            status = cov.get("status")
            cov_n = int(cov.get("coverage_row_count") or 0)
            if status == "COMPLETE" and fact_n == 0 and cov_n > 0:
                divergence.append({
                    "dataset": ds,
                    "fact_table": fact_table_by_dataset[ds],
                    "coverage_status": status,
                    "coverage_row_count": cov_n,
                    "fact_rows": fact_n,
                    "kind": "COMPLETE_WITHOUT_LOCAL_FACTS",
                    "note": (
                        "Receipt/coverage COMPLETE projected without this "
                        "plane holding fact rows. Not automatic data loss — "
                        "check local research DB / R2 structured SoT."
                    ),
                })
            elif status == "COMPLETE" and fact_n > 0 and cov_n > 0 and fact_n != cov_n:
                divergence.append({
                    "dataset": ds,
                    "fact_table": fact_table_by_dataset[ds],
                    "coverage_status": status,
                    "coverage_row_count": cov_n,
                    "fact_rows": fact_n,
                    "kind": "FACT_VS_COVERAGE_COUNT_MISMATCH",
                    "note": (
                        "Plane fact count differs from coverage ledger "
                        "row_count (often hot-tip D1 vs full local history)."
                    ),
                })
        return self._result(
            hot_cutoff=hot_cutoff,
            d1_approx_via_counts={
                "jquants_records_total": jquants_total,
                "bars_hot": bars_hot,
                "bars_cold_before_hot_cutoff": bars_cold,
                "master_hot": master_hot,
                "change_log_rows": change_log,
            },
            complete_segments=complete,
            jsda={
                # Plane-local fact counts (table COUNT(*)).
                "otc_rows": otc,
                "corporate_rows": corp,
                "tokyo_repo_rows": repo,
                "fact_table_map": {
                    "jsda_otc_bond_reference_prices": "jsda_otc_bond_reference_prices",
                    "jsda_corporate_bond_transactions": (
                        "jsda_corporate_bond_transactions"
                    ),
                    "jsda_tokyo_repo_rates": "jsda_repo_rates",
                },
                # Receipt-owned coverage (may be COMPLETE with empty fact plane).
                "coverage": jsda_coverage,
                "coverage_vs_fact_divergence": divergence,
                "definition": (
                    "tokyo_repo_rows = COUNT(jsda_repo_rates) on this plane only. "
                    "dataset COMPLETE for jsda_tokyo_repo_rates is owned by signed "
                    "collection_receipts + coverage_segments (segment "
                    "jsda-era-timeseries), not by D1 fact backfill. "
                    "ops projection publishes coverage ledgers; full JSDA history "
                    "lives on local research DB / R2 structured SoT."
                ),
            },
            empty_legacy_tables={
                "jquants_daily_bars": legacy_bars == 0,
                "jquants_listed_info": legacy_listed == 0,
                "jquants_market_calendar": legacy_cal == 0,
                "all_empty": empty_legacy,
            },
            stage_table_counts={
                "jquants_records_nk_v2_primary_stage": stage_primary,
                "ingestion_change_log_nk_v2_stage": stage_chg,
            },
            p0_claims={
                "bars_cold_cleared": (
                    "CONFIRMED" if bars_cold == 0 else "RESIDUAL_COLD"
                ),
                "legacy_empty": (
                    "CONFIRMED_EMPTY" if empty_legacy else "NOT_EMPTY"
                ),
                "mass_research": "NO-GO",
                "ready": None,
                "honesty_note": (
                    "Counts-only ops proof. Not READY. Not full history COMPLETE. "
                    "JSDA COMPLETE is receipt-owned; fact counts are plane-local "
                    "(D1 may show tokyo_repo_rows=0 while coverage COMPLETE)."
                ),
            },
        )

    def ops_status(self) -> dict[str, Any]:
        last_run = self.ingestion_last_run().get("run")
        coverage = self._all(
            "SELECT status, COUNT(*) AS count FROM dataset_coverage "
            "GROUP BY status ORDER BY status"
        )
        raw = self._one(
            "SELECT COUNT(*) AS manifests, "
            "SUM(CASE WHEN completeness='COMPLETE' THEN 1 ELSE 0 END) "
            "AS complete FROM raw_retention_manifests"
        )
        return self._result(
            available=self.db_path.is_file(),
            last_run=last_run,
            coverage_status="AVAILABLE" if coverage else "UNKNOWN",
            coverage_status_counts=coverage,
            governed_dataset_count=len(self._datasets),
            raw_retention=raw or {"manifests": 0, "complete": 0},
            research_note=(
                "Current Ops state is not evidence that the same data is in "
                "a published READY generation."
            ),
        )

    def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        if name not in OPS_CURRENT_METHODS:
            raise KeyError(f"unknown Ops current read: {name!r}")
        method = getattr(self, name)
        return method(**dict(arguments or {}))


class QuantReadDomainService:
    """Shared dispatcher with explicit current and immutable interfaces."""

    def __init__(
        self,
        research_access: QuantDataAccess | None = None,
        *,
        ops_db_path: str | Path = DEFAULT_OPS_DB,
    ) -> None:
        self.research_ready = ResearchReadyReadService(
            research_access or QuantDataAccess()
        )
        self.ops_current = OpsCurrentReadService(ops_db_path)

    def call_tool(
        self, name: str, arguments: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        # The local/dev MCP combines both planes. Coverage without a snapshot
        # is explicitly current; READY coverage remains available through the
        # research_ready Python interface and coverage_summary.
        if name in OPS_CURRENT_METHODS:
            return self.ops_current.call_tool(name, arguments)
        if name == "latest_ready_snapshot":
            return self.research_ready.latest_ready_snapshot()
        if name == "snapshot_quality":
            values = dict(arguments or {})
            return self.research_ready.snapshot_quality(values.get("snapshot_id"))
        return self.research_ready.call_tool(name, arguments)


__all__ = [
    "DEFAULT_OPS_DB",
    "OPS_CURRENT_METHODS",
    "RESEARCH_READY_METHODS",
    "OpsCurrentReadService",
    "QuantReadDomainService",
    "ResearchReadyReadService",
]
