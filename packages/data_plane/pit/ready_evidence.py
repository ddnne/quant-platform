"""READY ledger reads on one market snapshot connection.

Runtime policy converts these facts into PASS/FAIL evidence items. This
module owns the SQLite access; it does not decide READY. Connection lifetime
for publication remains the shared staging write transaction in paper_runtime.
"""

from __future__ import annotations

import sqlite3
from typing import Sequence

from storage.coverage_proof import (
    CoverageProofVerificationError,
    VerifiedCoverageProof,
    require_persisted_coverage_proof,
)


class ReadyLedgerSession:
    """Purpose-specific READY ledger reader. Not a Connection API."""

    __slots__ = ("_conn",)

    def __init__(self, conn: sqlite3.Connection) -> None:
        if type(conn) is not sqlite3.Connection:
            raise TypeError("ready ledger session requires sqlite3.Connection")
        self._conn = conn

    def require_persisted_coverage_proof(
        self,
        required_datasets: Sequence[str],
        proof_id: object,
        *,
        build_id: object,
    ) -> VerifiedCoverageProof:
        return require_persisted_coverage_proof(
            self._conn,
            required_datasets,
            proof_id,
            build_id=build_id,
        )

    def raw_retention_rows(
        self, run_id: int, required: tuple[str, ...]
    ) -> tuple[tuple[str, str], ...] | None:
        try:
            placeholders = ",".join("?" for _ in required)
            rows = self._conn.execute(
                "SELECT dataset, completeness FROM raw_retention_manifests "
                f"WHERE run_id=? AND dataset IN ({placeholders})",
                (run_id, *required),
            ).fetchall()
        except sqlite3.Error:
            return None
        return tuple((str(row[0]), str(row[1])) for row in rows)

    def validation_rows(
        self, run_id: int, required: tuple[str, ...]
    ) -> tuple[tuple[str, str], ...] | None:
        try:
            placeholders = ",".join("?" for _ in required)
            rows = self._conn.execute(
                "SELECT dataset, status FROM ingestion_validation "
                f"WHERE run_id=? AND dataset IN ({placeholders})",
                (run_id, *required),
            ).fetchall()
        except sqlite3.Error:
            return None
        return tuple((str(row[0]), str(row[1])) for row in rows)

    def latest_natural_key_state(self) -> str | None:
        try:
            row = self._conn.execute(
                "SELECT state FROM natural_key_migrations "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            return None
        if row:
            return str(row[0])
        return None

    def quality_rows(
        self, build_id: str
    ) -> tuple[tuple[str, str], ...] | None:
        try:
            rows = self._conn.execute(
                "SELECT status, results_json FROM snapshot_quality_results "
                "WHERE build_id=?",
                (build_id,),
            ).fetchall()
        except sqlite3.Error:
            return None
        return tuple((str(row[0]), str(row[1])) for row in rows)

    def max_change_seq(self) -> int | None:
        try:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(change_seq), 0) FROM ingestion_change_log"
            ).fetchone()
        except sqlite3.Error:
            return None
        return int(row[0]) if row else 0

    def last_applied_change_seq(self) -> int | None:
        try:
            row = self._conn.execute(
                "SELECT last_applied_change_seq FROM sync_change_state "
                "WHERE feed='jquants_records'"
            ).fetchone()
        except sqlite3.Error:
            return None
        return int(row[0]) if row else 0


__all__ = [
    "CoverageProofVerificationError",
    "ReadyLedgerSession",
]
