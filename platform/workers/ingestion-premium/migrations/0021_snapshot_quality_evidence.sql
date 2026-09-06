-- Immutable signed B0/B4 evidence.
-- Append-only: no UPDATE, no DELETE. Publication re-reads this table.

CREATE TABLE snapshot_quality_evidence (
    evidence_digest TEXT PRIMARY KEY,
    evidence_version TEXT NOT NULL CHECK (evidence_version = 'snapshot-quality-evidence/v1'),
    environment TEXT NOT NULL CHECK (environment IN ('staging', 'production')),
    generation_id TEXT NOT NULL,
    snapshot_cursor INTEGER,
    source_cursor INTEGER,
    export_cursor INTEGER,
    applied_cursor INTEGER,
    b0_status TEXT NOT NULL CHECK (b0_status IN ('PASS', 'FAIL', 'UNKNOWN')),
    b0_reason TEXT NOT NULL,
    b4_status TEXT NOT NULL CHECK (b4_status IN ('PASS', 'FAIL', 'UNKNOWN')),
    b4_reason TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    issuer_key_id TEXT NOT NULL,
    canonical_evidence_digest TEXT NOT NULL,
    signature TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    summary_json TEXT NOT NULL,
    results_json TEXT NOT NULL,
    source_build_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PASS', 'FAIL', 'UNKNOWN')),
    CHECK (evidence_digest GLOB 'sha256:[0-9a-f]*' AND length(evidence_digest) = 71),
    CHECK (canonical_evidence_digest = evidence_digest),
    CHECK (signature GLOB 'ed25519:*'),
    CHECK (length(generation_id) > 0),
    CHECK (length(issuer_key_id) > 0),
    CHECK (
        (snapshot_cursor IS NULL OR snapshot_cursor >= 0)
        AND (source_cursor IS NULL OR source_cursor >= 0)
        AND (export_cursor IS NULL OR export_cursor >= 0)
        AND (applied_cursor IS NULL OR applied_cursor >= 0)
    )
);

CREATE TRIGGER snapshot_quality_evidence_no_update
BEFORE UPDATE ON snapshot_quality_evidence
BEGIN
    SELECT RAISE(ABORT, 'snapshot_quality_evidence is immutable');
END;

CREATE TRIGGER snapshot_quality_evidence_no_delete
BEFORE DELETE ON snapshot_quality_evidence
BEGIN
    SELECT RAISE(ABORT, 'snapshot_quality_evidence is immutable');
END;

CREATE INDEX ix_snapshot_quality_evidence_eval
    ON snapshot_quality_evidence (environment, evaluated_at, evidence_digest);
