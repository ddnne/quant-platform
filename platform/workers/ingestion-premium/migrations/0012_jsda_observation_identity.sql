-- Three-identity JSDA acquisition contract plus descendant run closure.
-- SourceObject: stable canonical official URL/locator.
-- Observation: D1-owned monotonic generation of that object.
-- Artifact: immutable content digest; locations are separate R2 keys.
-- v2 job rows remain immutable cutover history; v3 is the active work graph.
-- Discovery frontier exhaustion is not terminal success: a parent stays
-- waiting_children until every governed descendant is durably terminal.

-- D1 migrations must remain safe even if a provider interruption commits only
-- a prefix of this file.  The v2 graph therefore remains immutable audit and
-- rollback history.  A fully constrained v3 graph is built beside it, v2
-- writes are bridged before the populated copy, and every later statement is
-- idempotent.  No table or row is dropped by this migration.
CREATE TABLE IF NOT EXISTS jsda_acquisition_jobs_v3 (
    work_key               TEXT PRIMARY KEY,
    run_key                TEXT NOT NULL,
    dataset                TEXT NOT NULL,
    job_type               TEXT NOT NULL CHECK
        (job_type IN ('discover_root', 'discover_year', 'fetch_file')),
    target_url             TEXT NOT NULL,
    segment_id             TEXT NOT NULL,
    parent_work_key        TEXT,
    contract_digest        TEXT NOT NULL,
    state                  TEXT NOT NULL CHECK
        (state IN ('pending', 'queued', 'running', 'waiting_children',
                   'completed', 'failed_transient', 'rejected')),
    attempt                INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    cursor                 INTEGER NOT NULL DEFAULT 0 CHECK (cursor >= 0),
    frontier_json          TEXT,
    last_error             TEXT,
    content_digest         TEXT,
    raw_key                TEXT,
    audit_receipt_key      TEXT,
    audit_receipt_digest   TEXT,
    requested_by           TEXT NOT NULL CHECK (requested_by IN ('cron', 'manual')),
    requested_at           TEXT NOT NULL,
    first_seen_at          TEXT NOT NULL,
    enqueued_at            TEXT,
    started_at             TEXT,
    completed_at           TEXT,
    updated_at             TEXT NOT NULL,
    lease_until            TEXT,
    source_object_id       TEXT,
    freshness              TEXT,
    observation_epoch      TEXT,
    CHECK ((state NOT IN ('completed', 'rejected', 'waiting_children')) OR
           (audit_receipt_key IS NOT NULL AND audit_receipt_digest IS NOT NULL)),
    CHECK ((job_type = 'discover_root' AND parent_work_key IS NULL) OR
           (job_type != 'discover_root' AND parent_work_key IS NOT NULL))
);

-- Deployment is a separate, explicit one-way cutover.  While phase=bridge,
-- drained v1/v2 instances may finish in-flight writes and the v2 bridge
-- copies them.  The v3 Worker refuses product Cron/Queue until this singleton
-- is v3_active with a Git source SHA, the compiled cutover config digest, and
-- a distinct content-addressed drain-evidence digest.  Those two digests are
-- not interchangeable.  Active facts are immutable; reverse transitions are
-- forbidden.  SQLite CHECK/WHEN treat NULL as pass, so every required fact
-- uses IS NOT NULL before length/GLOB compares.  INSERT OR REPLACE must not
-- reverse activation: a side-table insert guard survives REPLACE's internal
-- DELETE (recursive_triggers stays off).
CREATE TABLE IF NOT EXISTS jsda_v3_cutover_control (
    singleton                 INTEGER PRIMARY KEY CHECK (singleton = 1),
    phase                     TEXT NOT NULL CHECK (phase IN ('bridge', 'v3_active')),
    activated_at              TEXT,
    activated_source_sha      TEXT,
    cutover_config_digest     TEXT,
    drain_evidence_digest     TEXT,
    CHECK (
        phase = 'bridge'
        OR (
            activated_at IS NOT NULL
            AND activated_source_sha IS NOT NULL
            AND cutover_config_digest IS NOT NULL
            AND drain_evidence_digest IS NOT NULL
            AND substr(activated_at, -1) = 'Z'
            AND substr(activated_at, 5, 1) = '-'
            AND substr(activated_at, 8, 1) = '-'
            AND substr(activated_at, 11, 1) = 'T'
            AND substr(activated_at, 14, 1) = ':'
            AND substr(activated_at, 17, 1) = ':'
            AND substr(activated_at, 1, 4) GLOB '[0-9][0-9][0-9][0-9]'
            AND substr(activated_at, 6, 2) GLOB '[0-9][0-9]'
            AND substr(activated_at, 9, 2) GLOB '[0-9][0-9]'
            AND substr(activated_at, 12, 2) GLOB '[0-9][0-9]'
            AND substr(activated_at, 15, 2) GLOB '[0-9][0-9]'
            AND substr(activated_at, 18, 2) GLOB '[0-9][0-9]'
            AND (
                length(activated_at) = 20
                OR (
                    substr(activated_at, 20, 1) = '.'
                    AND length(activated_at) >= 22
                    AND substr(activated_at, 21, length(activated_at) - 21)
                        NOT GLOB '*[^0-9]*'
                )
            )
            AND length(activated_source_sha) = 40
            AND activated_source_sha NOT GLOB '*[^0-9a-f]*'
            AND length(cutover_config_digest) = 71
            AND substr(cutover_config_digest, 1, 7) = 'sha256:'
            AND substr(cutover_config_digest, 8) NOT GLOB '*[^0-9a-f]*'
            AND length(drain_evidence_digest) = 71
            AND substr(drain_evidence_digest, 1, 7) = 'sha256:'
            AND substr(drain_evidence_digest, 8) NOT GLOB '*[^0-9a-f]*'
            AND cutover_config_digest != drain_evidence_digest
        )
    )
);

CREATE TABLE IF NOT EXISTS jsda_v3_cutover_insert_guard (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1)
);

CREATE TABLE IF NOT EXISTS jsda_v3_drain_evidence (
    drain_evidence_digest TEXT PRIMARY KEY,
    observed_at           TEXT NOT NULL,
    document_json         TEXT NOT NULL,
    CHECK (
        drain_evidence_digest IS NOT NULL
        AND length(drain_evidence_digest) = 71
        AND substr(drain_evidence_digest, 1, 7) = 'sha256:'
        AND substr(drain_evidence_digest, 8) NOT GLOB '*[^0-9a-f]*'
        AND observed_at IS NOT NULL
        AND substr(observed_at, -1) = 'Z'
        AND substr(observed_at, 5, 1) = '-'
        AND substr(observed_at, 8, 1) = '-'
        AND substr(observed_at, 11, 1) = 'T'
        AND substr(observed_at, 14, 1) = ':'
        AND substr(observed_at, 17, 1) = ':'
        AND substr(observed_at, 1, 4) GLOB '[0-9][0-9][0-9][0-9]'
        AND substr(observed_at, 6, 2) GLOB '[0-9][0-9]'
        AND substr(observed_at, 9, 2) GLOB '[0-9][0-9]'
        AND substr(observed_at, 12, 2) GLOB '[0-9][0-9]'
        AND substr(observed_at, 15, 2) GLOB '[0-9][0-9]'
        AND substr(observed_at, 18, 2) GLOB '[0-9][0-9]'
        AND (
            length(observed_at) = 20
            OR (
                substr(observed_at, 20, 1) = '.'
                AND length(observed_at) >= 22
                AND substr(observed_at, 21, length(observed_at) - 21)
                    NOT GLOB '*[^0-9]*'
            )
        )
        AND document_json IS NOT NULL
        AND length(document_json) > 1
    )
);

CREATE TRIGGER IF NOT EXISTS jsda_v3_drain_evidence_no_update
BEFORE UPDATE ON jsda_v3_drain_evidence
BEGIN
    SELECT RAISE(ABORT, 'JSDA v3 drain evidence is immutable');
END;

CREATE TRIGGER IF NOT EXISTS jsda_v3_drain_evidence_no_delete
BEFORE DELETE ON jsda_v3_drain_evidence
BEGIN
    SELECT RAISE(ABORT, 'JSDA v3 drain evidence is immutable');
END;

CREATE TRIGGER IF NOT EXISTS jsda_v3_cutover_no_delete
BEFORE DELETE ON jsda_v3_cutover_control
BEGIN
    SELECT RAISE(ABORT, 'JSDA v3 cutover control cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS jsda_v3_cutover_guard_no_delete
BEFORE DELETE ON jsda_v3_cutover_insert_guard
BEGIN
    SELECT RAISE(ABORT, 'JSDA v3 cutover insert guard cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS jsda_v3_cutover_no_second_insert
BEFORE INSERT ON jsda_v3_cutover_control
WHEN EXISTS (
    SELECT 1 FROM jsda_v3_cutover_insert_guard WHERE singleton = 1
)
BEGIN
    SELECT RAISE(ABORT, 'JSDA v3 cutover control cannot be replaced');
END;

CREATE TRIGGER IF NOT EXISTS jsda_v3_cutover_mark_inserted
AFTER INSERT ON jsda_v3_cutover_control
BEGIN
    INSERT INTO jsda_v3_cutover_insert_guard (singleton)
    SELECT 1
    WHERE NOT EXISTS (
        SELECT 1 FROM jsda_v3_cutover_insert_guard WHERE singleton = 1
    );
END;

CREATE TRIGGER IF NOT EXISTS jsda_v3_cutover_immutable_active
BEFORE UPDATE ON jsda_v3_cutover_control
WHEN OLD.phase = 'v3_active'
BEGIN
    SELECT RAISE(ABORT, 'JSDA v3 cutover is immutable after activation');
END;

CREATE TRIGGER IF NOT EXISTS jsda_v3_cutover_activate_requires_facts
BEFORE UPDATE ON jsda_v3_cutover_control
WHEN OLD.phase = 'bridge' AND NEW.phase = 'v3_active' AND NOT (
    NEW.activated_at IS NOT NULL
    AND NEW.activated_source_sha IS NOT NULL
    AND NEW.cutover_config_digest IS NOT NULL
    AND NEW.drain_evidence_digest IS NOT NULL
    AND substr(NEW.activated_at, -1) = 'Z'
    AND substr(NEW.activated_at, 5, 1) = '-'
    AND substr(NEW.activated_at, 8, 1) = '-'
    AND substr(NEW.activated_at, 11, 1) = 'T'
    AND substr(NEW.activated_at, 14, 1) = ':'
    AND substr(NEW.activated_at, 17, 1) = ':'
    AND substr(NEW.activated_at, 1, 4) GLOB '[0-9][0-9][0-9][0-9]'
    AND substr(NEW.activated_at, 6, 2) GLOB '[0-9][0-9]'
    AND substr(NEW.activated_at, 9, 2) GLOB '[0-9][0-9]'
    AND substr(NEW.activated_at, 12, 2) GLOB '[0-9][0-9]'
    AND substr(NEW.activated_at, 15, 2) GLOB '[0-9][0-9]'
    AND substr(NEW.activated_at, 18, 2) GLOB '[0-9][0-9]'
    AND (
        length(NEW.activated_at) = 20
        OR (
            substr(NEW.activated_at, 20, 1) = '.'
            AND length(NEW.activated_at) >= 22
            AND substr(NEW.activated_at, 21, length(NEW.activated_at) - 21)
                NOT GLOB '*[^0-9]*'
        )
    )
    AND length(NEW.activated_source_sha) = 40
    AND NEW.activated_source_sha NOT GLOB '*[^0-9a-f]*'
    AND length(NEW.cutover_config_digest) = 71
    AND substr(NEW.cutover_config_digest, 1, 7) = 'sha256:'
    AND substr(NEW.cutover_config_digest, 8) NOT GLOB '*[^0-9a-f]*'
    AND length(NEW.drain_evidence_digest) = 71
    AND substr(NEW.drain_evidence_digest, 1, 7) = 'sha256:'
    AND substr(NEW.drain_evidence_digest, 8) NOT GLOB '*[^0-9a-f]*'
    AND NEW.cutover_config_digest != NEW.drain_evidence_digest
    AND EXISTS (
        SELECT 1 FROM jsda_v3_drain_evidence
         WHERE drain_evidence_digest = NEW.drain_evidence_digest
    )
)
BEGIN
    SELECT RAISE(ABORT, 'JSDA v3 cutover activation is incomplete');
END;

INSERT INTO jsda_v3_cutover_control (singleton, phase)
SELECT 1, 'bridge'
WHERE NOT EXISTS (
    SELECT 1 FROM jsda_v3_cutover_control WHERE singleton = 1
);

-- Live production still writes the original v1 table.  After activation the
-- v3 Worker is the only writer; late v1 rows must not land.
CREATE TRIGGER IF NOT EXISTS jsda_v1_jobs_insert_retired
BEFORE INSERT ON jsda_acquisition_jobs
WHEN (SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1) = 'v3_active'
BEGIN
    SELECT RAISE(ABORT, 'JSDA v1 acquisition graph is retired');
END;

CREATE TRIGGER IF NOT EXISTS jsda_v1_jobs_update_retired
BEFORE UPDATE ON jsda_acquisition_jobs
WHEN (SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1) = 'v3_active'
BEGIN
    SELECT RAISE(ABORT, 'JSDA v1 acquisition graph is retired');
END;

CREATE TRIGGER IF NOT EXISTS jsda_v1_jobs_delete_retired
BEFORE DELETE ON jsda_acquisition_jobs
WHEN (SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1) = 'v3_active'
BEGIN
    SELECT RAISE(ABORT, 'JSDA v1 acquisition graph is retired');
END;

-- Late v1 writers during bridge are fenced into an append-only copy so a write
-- after the initial populated snapshot cannot be lost.
CREATE TABLE IF NOT EXISTS jsda_v1_bridge_writes (
    job_id      TEXT PRIMARY KEY,
    dataset     TEXT NOT NULL,
    job_type    TEXT NOT NULL,
    target_url  TEXT NOT NULL,
    segment_id  TEXT,
    state       TEXT NOT NULL,
    attempt     INTEGER NOT NULL,
    priority    INTEGER NOT NULL,
    reason_code TEXT,
    detail      TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    lease_until TEXT,
    bridged_at  TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS jsda_v1_jobs_insert_bridge
AFTER INSERT ON jsda_acquisition_jobs
WHEN (SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1) = 'bridge'
BEGIN
    INSERT INTO jsda_v1_bridge_writes (
        job_id, dataset, job_type, target_url, segment_id, state, attempt,
        priority, reason_code, detail, created_at, updated_at, lease_until,
        bridged_at
    )
    VALUES (
        NEW.job_id, NEW.dataset, NEW.job_type, NEW.target_url, NEW.segment_id,
        NEW.state, NEW.attempt, NEW.priority, NEW.reason_code, NEW.detail,
        NEW.created_at, NEW.updated_at, NEW.lease_until, NEW.updated_at
    )
    ON CONFLICT(job_id) DO UPDATE SET
        dataset=excluded.dataset,
        job_type=excluded.job_type,
        target_url=excluded.target_url,
        segment_id=excluded.segment_id,
        state=excluded.state,
        attempt=excluded.attempt,
        priority=excluded.priority,
        reason_code=excluded.reason_code,
        detail=excluded.detail,
        created_at=excluded.created_at,
        updated_at=excluded.updated_at,
        lease_until=excluded.lease_until,
        bridged_at=excluded.bridged_at
    WHERE jsda_v1_bridge_writes.updated_at <= excluded.updated_at;
END;

CREATE TRIGGER IF NOT EXISTS jsda_v1_jobs_update_bridge
AFTER UPDATE ON jsda_acquisition_jobs
WHEN (SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1) = 'bridge'
BEGIN
    INSERT INTO jsda_v1_bridge_writes (
        job_id, dataset, job_type, target_url, segment_id, state, attempt,
        priority, reason_code, detail, created_at, updated_at, lease_until,
        bridged_at
    )
    VALUES (
        NEW.job_id, NEW.dataset, NEW.job_type, NEW.target_url, NEW.segment_id,
        NEW.state, NEW.attempt, NEW.priority, NEW.reason_code, NEW.detail,
        NEW.created_at, NEW.updated_at, NEW.lease_until, NEW.updated_at
    )
    ON CONFLICT(job_id) DO UPDATE SET
        dataset=excluded.dataset,
        job_type=excluded.job_type,
        target_url=excluded.target_url,
        segment_id=excluded.segment_id,
        state=excluded.state,
        attempt=excluded.attempt,
        priority=excluded.priority,
        reason_code=excluded.reason_code,
        detail=excluded.detail,
        created_at=excluded.created_at,
        updated_at=excluded.updated_at,
        lease_until=excluded.lease_until,
        bridged_at=excluded.bridged_at
    WHERE jsda_v1_bridge_writes.updated_at <= excluded.updated_at;
END;

-- Close the old-Worker write race before taking the populated snapshot.  The
-- bridge deliberately updates only the v2/common columns; a resumed migration
-- must not erase v3 identity fields already derived by a prior prefix.
CREATE TRIGGER IF NOT EXISTS jsda_migration_v2_jobs_insert_to_v3
AFTER INSERT ON jsda_acquisition_jobs_v2
WHEN (SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1) = 'bridge'
BEGIN
    INSERT INTO jsda_acquisition_jobs_v3 (
        work_key, run_key, dataset, job_type, target_url, segment_id,
        parent_work_key, contract_digest, state, attempt, cursor, frontier_json,
        last_error, content_digest, raw_key, audit_receipt_key,
        audit_receipt_digest, requested_by, requested_at, first_seen_at,
        enqueued_at, started_at, completed_at, updated_at, lease_until
    )
    VALUES (
        NEW.work_key, NEW.run_key, NEW.dataset, NEW.job_type, NEW.target_url,
        NEW.segment_id, NEW.parent_work_key, NEW.contract_digest, NEW.state,
        NEW.attempt, NEW.cursor, NEW.frontier_json, NEW.last_error,
        NEW.content_digest, NEW.raw_key, NEW.audit_receipt_key,
        NEW.audit_receipt_digest, NEW.requested_by, NEW.requested_at,
        NEW.first_seen_at, NEW.enqueued_at, NEW.started_at, NEW.completed_at,
        NEW.updated_at, NEW.lease_until
    )
    ON CONFLICT(work_key) DO UPDATE SET
        run_key=excluded.run_key,
        dataset=excluded.dataset,
        job_type=excluded.job_type,
        target_url=excluded.target_url,
        segment_id=excluded.segment_id,
        parent_work_key=excluded.parent_work_key,
        contract_digest=excluded.contract_digest,
        state=excluded.state,
        attempt=excluded.attempt,
        cursor=excluded.cursor,
        frontier_json=excluded.frontier_json,
        last_error=excluded.last_error,
        content_digest=excluded.content_digest,
        raw_key=excluded.raw_key,
        audit_receipt_key=excluded.audit_receipt_key,
        audit_receipt_digest=excluded.audit_receipt_digest,
        requested_by=excluded.requested_by,
        requested_at=excluded.requested_at,
        first_seen_at=excluded.first_seen_at,
        enqueued_at=excluded.enqueued_at,
        started_at=excluded.started_at,
        completed_at=excluded.completed_at,
        updated_at=excluded.updated_at,
        lease_until=excluded.lease_until
    WHERE jsda_acquisition_jobs_v3.updated_at <= excluded.updated_at;
END;

CREATE TRIGGER IF NOT EXISTS jsda_migration_v2_jobs_update_to_v3
AFTER UPDATE ON jsda_acquisition_jobs_v2
WHEN (SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1) = 'bridge'
BEGIN
    INSERT INTO jsda_acquisition_jobs_v3 (
        work_key, run_key, dataset, job_type, target_url, segment_id,
        parent_work_key, contract_digest, state, attempt, cursor, frontier_json,
        last_error, content_digest, raw_key, audit_receipt_key,
        audit_receipt_digest, requested_by, requested_at, first_seen_at,
        enqueued_at, started_at, completed_at, updated_at, lease_until
    )
    VALUES (
        NEW.work_key, NEW.run_key, NEW.dataset, NEW.job_type, NEW.target_url,
        NEW.segment_id, NEW.parent_work_key, NEW.contract_digest, NEW.state,
        NEW.attempt, NEW.cursor, NEW.frontier_json, NEW.last_error,
        NEW.content_digest, NEW.raw_key, NEW.audit_receipt_key,
        NEW.audit_receipt_digest, NEW.requested_by, NEW.requested_at,
        NEW.first_seen_at, NEW.enqueued_at, NEW.started_at, NEW.completed_at,
        NEW.updated_at, NEW.lease_until
    )
    ON CONFLICT(work_key) DO UPDATE SET
        run_key=excluded.run_key,
        dataset=excluded.dataset,
        job_type=excluded.job_type,
        target_url=excluded.target_url,
        segment_id=excluded.segment_id,
        parent_work_key=excluded.parent_work_key,
        contract_digest=excluded.contract_digest,
        state=excluded.state,
        attempt=excluded.attempt,
        cursor=excluded.cursor,
        frontier_json=excluded.frontier_json,
        last_error=excluded.last_error,
        content_digest=excluded.content_digest,
        raw_key=excluded.raw_key,
        audit_receipt_key=excluded.audit_receipt_key,
        audit_receipt_digest=excluded.audit_receipt_digest,
        requested_by=excluded.requested_by,
        requested_at=excluded.requested_at,
        first_seen_at=excluded.first_seen_at,
        enqueued_at=excluded.enqueued_at,
        started_at=excluded.started_at,
        completed_at=excluded.completed_at,
        updated_at=excluded.updated_at,
        lease_until=excluded.lease_until
    WHERE jsda_acquisition_jobs_v3.updated_at <= excluded.updated_at;
END;

CREATE TRIGGER IF NOT EXISTS jsda_v2_jobs_insert_retired
BEFORE INSERT ON jsda_acquisition_jobs_v2
WHEN (SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1) = 'v3_active'
BEGIN
    SELECT RAISE(ABORT, 'JSDA v2 acquisition graph is retired');
END;

CREATE TRIGGER IF NOT EXISTS jsda_v2_jobs_update_retired
BEFORE UPDATE ON jsda_acquisition_jobs_v2
WHEN (SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1) = 'v3_active'
BEGIN
    SELECT RAISE(ABORT, 'JSDA v2 acquisition graph is retired');
END;

CREATE TRIGGER IF NOT EXISTS jsda_v2_jobs_delete_retired
BEFORE DELETE ON jsda_acquisition_jobs_v2
WHEN (SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1) = 'v3_active'
BEGIN
    SELECT RAISE(ABORT, 'JSDA v2 acquisition graph is retired');
END;

INSERT INTO jsda_acquisition_jobs_v3 (
    work_key, run_key, dataset, job_type, target_url, segment_id,
    parent_work_key, contract_digest, state, attempt, cursor, frontier_json,
    last_error, content_digest, raw_key, audit_receipt_key, audit_receipt_digest,
    requested_by, requested_at, first_seen_at, enqueued_at, started_at,
    completed_at, updated_at, lease_until
)
SELECT
    work_key, run_key, dataset, job_type, target_url, segment_id,
    parent_work_key, contract_digest, state, attempt, cursor, frontier_json,
    last_error, content_digest, raw_key, audit_receipt_key, audit_receipt_digest,
    requested_by, requested_at, first_seen_at, enqueued_at, started_at,
    completed_at, updated_at, lease_until
  FROM jsda_acquisition_jobs_v2
 WHERE 1
ON CONFLICT(work_key) DO UPDATE SET
    run_key=excluded.run_key,
    dataset=excluded.dataset,
    job_type=excluded.job_type,
    target_url=excluded.target_url,
    segment_id=excluded.segment_id,
    parent_work_key=excluded.parent_work_key,
    contract_digest=excluded.contract_digest,
    state=excluded.state,
    attempt=excluded.attempt,
    cursor=excluded.cursor,
    frontier_json=excluded.frontier_json,
    last_error=excluded.last_error,
    content_digest=excluded.content_digest,
    raw_key=excluded.raw_key,
    audit_receipt_key=excluded.audit_receipt_key,
    audit_receipt_digest=excluded.audit_receipt_digest,
    requested_by=excluded.requested_by,
    requested_at=excluded.requested_at,
    first_seen_at=excluded.first_seen_at,
    enqueued_at=excluded.enqueued_at,
    started_at=excluded.started_at,
    completed_at=excluded.completed_at,
    updated_at=excluded.updated_at,
    lease_until=excluded.lease_until;

CREATE TABLE IF NOT EXISTS jsda_acquisition_events_v3 (
    event_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    legacy_event_id        INTEGER,
    work_key               TEXT NOT NULL,
    run_key                TEXT NOT NULL,
    dataset                TEXT NOT NULL,
    job_type               TEXT NOT NULL,
    segment_id             TEXT NOT NULL,
    attempt                INTEGER NOT NULL,
    cursor                 INTEGER NOT NULL,
    result                 TEXT NOT NULL CHECK
        (result IN ('continued', 'frontier_exhausted', 'completed',
                    'failed_transient', 'rejected')),
    reason_code            TEXT,
    detail                 TEXT,
    content_digest         TEXT,
    raw_key                TEXT,
    audit_receipt_key      TEXT NOT NULL,
    audit_receipt_digest   TEXT NOT NULL,
    occurred_at            TEXT NOT NULL,
    FOREIGN KEY (work_key) REFERENCES jsda_acquisition_jobs_v3(work_key)
);

CREATE TRIGGER IF NOT EXISTS jsda_migration_v2_events_insert_to_v3
AFTER INSERT ON jsda_acquisition_events_v2
WHEN (SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1) = 'bridge'
BEGIN
    INSERT OR IGNORE INTO jsda_acquisition_events_v3 (
        legacy_event_id, work_key, run_key, dataset, job_type, segment_id, attempt,
        cursor, result, reason_code, detail, content_digest, raw_key,
        audit_receipt_key, audit_receipt_digest, occurred_at
    ) VALUES (
        NEW.event_id, NEW.work_key, NEW.run_key, NEW.dataset, NEW.job_type,
        NEW.segment_id, NEW.attempt, NEW.cursor, NEW.result, NEW.reason_code,
        NEW.detail, NEW.content_digest, NEW.raw_key, NEW.audit_receipt_key,
        NEW.audit_receipt_digest, NEW.occurred_at
    );
END;

CREATE TRIGGER IF NOT EXISTS jsda_v2_events_insert_retired
BEFORE INSERT ON jsda_acquisition_events_v2
WHEN (SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1) = 'v3_active'
BEGIN
    SELECT RAISE(ABORT, 'JSDA v2 acquisition graph is retired');
END;

INSERT OR IGNORE INTO jsda_acquisition_events_v3 (
    legacy_event_id, work_key, run_key, dataset, job_type, segment_id, attempt, cursor,
    result, reason_code, detail, content_digest, raw_key,
    audit_receipt_key, audit_receipt_digest, occurred_at
)
SELECT
    event_id, work_key, run_key, dataset, job_type, segment_id, attempt, cursor,
    result, reason_code, detail, content_digest, raw_key,
    audit_receipt_key, audit_receipt_digest, occurred_at
  FROM jsda_acquisition_events_v2 AS legacy
 WHERE NOT EXISTS (
       SELECT 1
         FROM jsda_acquisition_events_v3 AS current
        WHERE current.legacy_event_id = legacy.event_id
   );

CREATE UNIQUE INDEX IF NOT EXISTS ux_jsda_events_v3_legacy_event
    ON jsda_acquisition_events_v3 (legacy_event_id)
    WHERE legacy_event_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS jsda_acquisition_discoveries_v3 (
    parent_work_key        TEXT NOT NULL,
    child_work_key         TEXT NOT NULL,
    run_key                TEXT NOT NULL,
    discovered_at          TEXT NOT NULL,
    PRIMARY KEY (parent_work_key, child_work_key),
    FOREIGN KEY (parent_work_key) REFERENCES jsda_acquisition_jobs_v3(work_key),
    FOREIGN KEY (child_work_key) REFERENCES jsda_acquisition_jobs_v3(work_key)
);

CREATE TRIGGER IF NOT EXISTS jsda_migration_v2_discoveries_insert_to_v3
AFTER INSERT ON jsda_acquisition_discoveries_v2
WHEN (SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1) = 'bridge'
BEGIN
    INSERT OR IGNORE INTO jsda_acquisition_discoveries_v3 (
        parent_work_key, child_work_key, run_key, discovered_at
    ) VALUES (
        NEW.parent_work_key, NEW.child_work_key, NEW.run_key, NEW.discovered_at
    );
END;

CREATE TRIGGER IF NOT EXISTS jsda_v2_discoveries_insert_retired
BEFORE INSERT ON jsda_acquisition_discoveries_v2
WHEN (SELECT phase FROM jsda_v3_cutover_control WHERE singleton=1) = 'v3_active'
BEGIN
    SELECT RAISE(ABORT, 'JSDA v2 acquisition graph is retired');
END;

INSERT OR IGNORE INTO jsda_acquisition_discoveries_v3 (
    parent_work_key, child_work_key, run_key, discovered_at
)
SELECT parent_work_key, child_work_key, run_key, discovered_at
  FROM jsda_acquisition_discoveries_v2;

CREATE INDEX IF NOT EXISTS ix_jsda_discoveries_v3_run
    ON jsda_acquisition_discoveries_v3 (run_key, parent_work_key, child_work_key);

-- Backfill the same table-driven locator policy used by the Worker. Treating
-- every legacy URL as an archive would put an already-seen rolling locator
-- under the URL-unique archive index and prevent every later run-scoped
-- observation from being registered.
UPDATE jsda_acquisition_jobs_v3
   SET freshness = CASE
         WHEN dataset = 'jsda_tokyo_repo_rates' THEN 'rolling'
         WHEN dataset = 'jsda_corporate_bond_transactions'
          AND instr(lower(target_url), '/torihiki') > 0
          AND substr(
                lower(target_url),
                instr(lower(target_url), '/torihiki') + 9,
                4
              ) GLOB '[0-9][0-9][0-9][0-9]'
          AND substr(
                lower(target_url),
                instr(lower(target_url), '/torihiki') + 9,
                4
              ) = substr(requested_at, 1, 4)
          AND substr(
                lower(target_url),
                instr(lower(target_url), '/torihiki') + 13,
                1
              ) = '.'
          AND substr(
                lower(target_url),
                instr(lower(target_url), '/torihiki') + 14,
                1
              ) GLOB '[a-z0-9]'
           THEN 'rolling'
         WHEN dataset = 'jsda_corporate_bond_transactions' THEN 'archive'
         WHEN dataset = 'jsda_otc_bond_reference_prices'
          AND (
            lower(target_url) GLOB
              '*[^0-9]20[0-9][0-9][0-9][0-9][0-9][0-9][^0-9]*'
            OR lower(target_url) GLOB
              '*/s[0-9][0-9][0-9][0-9][0-9][0-9].*'
          )
           THEN 'archive'
         ELSE 'rolling'
       END
 WHERE job_type = 'fetch_file'
   AND freshness IS NULL;

UPDATE jsda_acquisition_jobs_v3
   SET observation_epoch = CASE
         WHEN freshness = 'rolling' THEN run_key
         ELSE 'archive'
       END
 WHERE job_type = 'fetch_file'
   AND observation_epoch IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_jsda_jobs_v3_archive_file_url
    ON jsda_acquisition_jobs_v3 (dataset, job_type, target_url)
    WHERE job_type = 'fetch_file' AND freshness = 'archive';

CREATE UNIQUE INDEX IF NOT EXISTS ux_jsda_jobs_v3_rolling_file_epoch
    ON jsda_acquisition_jobs_v3 (dataset, job_type, target_url, run_key)
    WHERE job_type = 'fetch_file' AND freshness = 'rolling';

CREATE INDEX IF NOT EXISTS ix_jsda_jobs_v3_state_updated
    ON jsda_acquisition_jobs_v3 (state, updated_at, work_key);

CREATE INDEX IF NOT EXISTS ix_jsda_jobs_v3_run_parent
    ON jsda_acquisition_jobs_v3 (run_key, parent_work_key, job_type, state);

CREATE INDEX IF NOT EXISTS ix_jsda_events_v3_run_time
    ON jsda_acquisition_events_v3 (run_key, occurred_at, event_id);

CREATE TABLE IF NOT EXISTS jsda_source_objects (
    source_object_id           TEXT PRIMARY KEY,
    dataset                    TEXT NOT NULL,
    canonical_url              TEXT NOT NULL,
    freshness                  TEXT NOT NULL CHECK (freshness IN ('archive', 'rolling')),
    next_observation_seq       INTEGER NOT NULL DEFAULT 1
                               CHECK (next_observation_seq >= 1),
    current_observation_seq    INTEGER
                               CHECK (current_observation_seq IS NULL
                                      OR current_observation_seq >= 1),
    current_digest             TEXT,
    current_raw_key            TEXT,
    current_observation_key    TEXT,
    first_seen_at              TEXT NOT NULL,
    last_observed_at           TEXT,
    updated_at                 TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_jsda_source_objects_locator
    ON jsda_source_objects (dataset, canonical_url);

CREATE TABLE IF NOT EXISTS jsda_artifacts (
    content_digest           TEXT PRIMARY KEY,
    first_seen_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jsda_artifact_locations (
    raw_key                  TEXT PRIMARY KEY,
    content_digest           TEXT NOT NULL,
    dataset                  TEXT NOT NULL,
    first_seen_at            TEXT NOT NULL,
    FOREIGN KEY (content_digest) REFERENCES jsda_artifacts(content_digest)
);

CREATE INDEX IF NOT EXISTS ix_jsda_artifact_locations_digest
    ON jsda_artifact_locations (content_digest, first_seen_at);

CREATE TABLE IF NOT EXISTS jsda_observations (
    observation_key          TEXT PRIMARY KEY,
    source_object_id         TEXT NOT NULL,
    work_key                 TEXT NOT NULL,
    run_key                  TEXT NOT NULL,
    dataset                  TEXT NOT NULL,
    target_url               TEXT NOT NULL,
    freshness                TEXT NOT NULL CHECK (freshness IN ('archive', 'rolling')),
    epoch                    TEXT NOT NULL,
    observation_seq          INTEGER NOT NULL CHECK (observation_seq >= 1),
    state                    TEXT NOT NULL CHECK
        (state IN ('pending', 'queued', 'running', 'completed',
                   'failed_transient', 'rejected')),
    content_digest           TEXT,
    raw_key                  TEXT,
    observed_at              TEXT,
    first_seen_at            TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    FOREIGN KEY (source_object_id) REFERENCES jsda_source_objects(source_object_id),
    FOREIGN KEY (work_key) REFERENCES jsda_acquisition_jobs_v3(work_key)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_jsda_observations_epoch
    ON jsda_observations (source_object_id, epoch);

CREATE UNIQUE INDEX IF NOT EXISTS ux_jsda_observations_source_seq
    ON jsda_observations (source_object_id, observation_seq);

CREATE INDEX IF NOT EXISTS ix_jsda_observations_source_time
    ON jsda_observations (source_object_id, observed_at, observation_key);

CREATE INDEX IF NOT EXISTS ix_jsda_observations_artifact
    ON jsda_observations (content_digest, raw_key, source_object_id);

-- Canonical run-scoped descendant/adoption relation. Closure aggregates this
-- table, never the child's original immutable run_key/parent_work_key.
-- Adopted rows snapshot revalidated evidence; they do not rewrite old jobs.
CREATE TABLE IF NOT EXISTS jsda_run_membership (
    run_key                    TEXT NOT NULL,
    root_work_key              TEXT NOT NULL,
    parent_work_key            TEXT NOT NULL,
    child_work_key             TEXT NOT NULL,
    membership_kind            TEXT NOT NULL CHECK
        (membership_kind IN ('enqueued', 'adopted')),
    child_job_type             TEXT NOT NULL CHECK
        (child_job_type IN ('discover_year', 'fetch_file')),
    terminal_state             TEXT NOT NULL CHECK (
        terminal_state IN (
            'pending',
            'queued',
            'running',
            'waiting_children',
            'completed',
            'failed_transient',
            'rejected'
        )
    ),
    content_digest             TEXT,
    raw_key                    TEXT,
    audit_receipt_key          TEXT,
    audit_receipt_digest       TEXT,
    failure_reason_code        TEXT,
    failure_detail             TEXT,
    adopted_at                 TEXT,
    updated_at                 TEXT NOT NULL,
    PRIMARY KEY (run_key, parent_work_key, child_work_key),
    FOREIGN KEY (root_work_key) REFERENCES jsda_acquisition_jobs_v3(work_key),
    FOREIGN KEY (parent_work_key) REFERENCES jsda_acquisition_jobs_v3(work_key),
    FOREIGN KEY (child_work_key) REFERENCES jsda_acquisition_jobs_v3(work_key),
    CHECK (
        membership_kind = 'enqueued'
        OR adopted_at IS NOT NULL
    ),
    CHECK (
        terminal_state != 'completed'
        OR (
            audit_receipt_key IS NOT NULL
            AND audit_receipt_digest IS NOT NULL
            AND content_digest IS NOT NULL
            AND raw_key IS NOT NULL
        )
    ),
    CHECK (
        terminal_state != 'rejected'
        OR failure_reason_code IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS ix_jsda_run_membership_run_child
    ON jsda_run_membership (run_key, child_work_key, terminal_state);

CREATE INDEX IF NOT EXISTS ix_jsda_run_membership_parent
    ON jsda_run_membership (parent_work_key, run_key, terminal_state);

-- Years first, then roots: a newly rejected year must fail its completed root.
UPDATE jsda_acquisition_jobs_v3
   SET state = 'rejected',
       last_error = COALESCE(
         (
           SELECT child.last_error
             FROM jsda_acquisition_jobs_v3 AS child
            WHERE child.parent_work_key = jsda_acquisition_jobs_v3.work_key
              AND child.state = 'rejected'
            ORDER BY child.updated_at, child.work_key
            LIMIT 1
         ),
         'descendant_rejected'
       )
 WHERE job_type = 'discover_year'
   AND state = 'completed'
   AND audit_receipt_key IS NOT NULL
   AND audit_receipt_digest IS NOT NULL
   AND EXISTS (
     SELECT 1
       FROM jsda_acquisition_jobs_v3 AS child
      WHERE child.parent_work_key = jsda_acquisition_jobs_v3.work_key
        AND child.state = 'rejected'
   );

UPDATE jsda_acquisition_jobs_v3
   SET state = 'rejected',
       last_error = COALESCE(
         (
           SELECT child.last_error
             FROM jsda_acquisition_jobs_v3 AS child
            WHERE child.parent_work_key = jsda_acquisition_jobs_v3.work_key
              AND child.state = 'rejected'
            ORDER BY child.updated_at, child.work_key
            LIMIT 1
         ),
         'descendant_rejected'
       )
 WHERE job_type = 'discover_root'
   AND state = 'completed'
   AND audit_receipt_key IS NOT NULL
   AND audit_receipt_digest IS NOT NULL
   AND EXISTS (
     SELECT 1
       FROM jsda_acquisition_jobs_v3 AS child
      WHERE child.parent_work_key = jsda_acquisition_jobs_v3.work_key
        AND child.state = 'rejected'
   );

UPDATE jsda_acquisition_jobs_v3
   SET state = 'waiting_children'
 WHERE job_type = 'discover_year'
   AND state = 'completed'
   AND audit_receipt_key IS NOT NULL
   AND audit_receipt_digest IS NOT NULL
   AND EXISTS (
     SELECT 1
       FROM jsda_acquisition_jobs_v3 AS child
      WHERE child.parent_work_key = jsda_acquisition_jobs_v3.work_key
        AND child.state NOT IN ('completed', 'rejected')
   );

UPDATE jsda_acquisition_jobs_v3
   SET state = 'waiting_children'
 WHERE job_type = 'discover_root'
   AND state = 'completed'
   AND audit_receipt_key IS NOT NULL
   AND audit_receipt_digest IS NOT NULL
   AND EXISTS (
     SELECT 1
       FROM jsda_acquisition_jobs_v3 AS child
      WHERE child.parent_work_key = jsda_acquisition_jobs_v3.work_key
        AND child.state NOT IN ('completed', 'rejected')
   );

INSERT OR IGNORE INTO jsda_run_membership (
    run_key, root_work_key, parent_work_key, child_work_key,
    membership_kind, child_job_type, terminal_state,
    content_digest, raw_key, audit_receipt_key, audit_receipt_digest,
    failure_reason_code, failure_detail, adopted_at, updated_at
)
SELECT
    d.run_key,
    d.run_key,
    d.parent_work_key,
    d.child_work_key,
    CASE WHEN child.run_key = d.run_key THEN 'enqueued' ELSE 'adopted' END,
    child.job_type,
    CASE
        WHEN child.run_key = d.run_key THEN child.state
        WHEN child.state = 'completed'
         AND child.audit_receipt_key IS NOT NULL
         AND child.audit_receipt_digest IS NOT NULL
         AND child.content_digest IS NOT NULL
         AND child.raw_key IS NOT NULL
            THEN 'completed'
        WHEN child.state = 'rejected' THEN 'rejected'
        WHEN child.state = 'completed' THEN 'rejected'
        ELSE child.state
    END,
    CASE
        WHEN child.run_key = d.run_key THEN child.content_digest
        WHEN child.state = 'completed'
         AND child.audit_receipt_key IS NOT NULL
         AND child.audit_receipt_digest IS NOT NULL
         AND child.content_digest IS NOT NULL
         AND child.raw_key IS NOT NULL
            THEN child.content_digest
        ELSE NULL
    END,
    CASE
        WHEN child.run_key = d.run_key THEN child.raw_key
        WHEN child.state = 'completed'
         AND child.audit_receipt_key IS NOT NULL
         AND child.audit_receipt_digest IS NOT NULL
         AND child.content_digest IS NOT NULL
         AND child.raw_key IS NOT NULL
            THEN child.raw_key
        ELSE NULL
    END,
    CASE
        WHEN child.run_key = d.run_key THEN child.audit_receipt_key
        WHEN child.state = 'completed'
         AND child.audit_receipt_key IS NOT NULL
         AND child.audit_receipt_digest IS NOT NULL
         AND child.content_digest IS NOT NULL
         AND child.raw_key IS NOT NULL
            THEN child.audit_receipt_key
        ELSE NULL
    END,
    CASE
        WHEN child.run_key = d.run_key THEN child.audit_receipt_digest
        WHEN child.state = 'completed'
         AND child.audit_receipt_key IS NOT NULL
         AND child.audit_receipt_digest IS NOT NULL
         AND child.content_digest IS NOT NULL
         AND child.raw_key IS NOT NULL
            THEN child.audit_receipt_digest
        ELSE NULL
    END,
    CASE
        WHEN child.run_key = d.run_key AND child.state = 'rejected'
            THEN 'rejected'
        WHEN child.run_key != d.run_key
         AND child.state = 'completed'
         AND child.audit_receipt_key IS NOT NULL
         AND child.audit_receipt_digest IS NOT NULL
         AND child.content_digest IS NOT NULL
         AND child.raw_key IS NOT NULL
            THEN NULL
        WHEN child.run_key != d.run_key AND child.state = 'rejected'
            THEN 'rejected'
        WHEN child.run_key != d.run_key AND child.state = 'completed'
            THEN 'insufficient_legacy_evidence'
        ELSE NULL
    END,
    CASE
        WHEN child.run_key = d.run_key AND child.state = 'rejected'
            THEN child.last_error
        WHEN child.run_key != d.run_key
         AND child.state = 'completed'
         AND child.audit_receipt_key IS NOT NULL
         AND child.audit_receipt_digest IS NOT NULL
         AND child.content_digest IS NOT NULL
         AND child.raw_key IS NOT NULL
            THEN NULL
        WHEN child.run_key != d.run_key AND child.state = 'rejected'
            THEN child.last_error
        WHEN child.run_key != d.run_key AND child.state = 'completed'
            THEN 'adopted child lacks authoritative artifact/audit evidence'
        ELSE NULL
    END,
    CASE WHEN child.run_key != d.run_key THEN d.discovered_at ELSE NULL END,
    d.discovered_at
  FROM jsda_acquisition_discoveries_v3 AS d
  JOIN jsda_acquisition_jobs_v3 AS child
    ON child.work_key = d.child_work_key;

UPDATE jsda_acquisition_jobs_v3
   SET state = 'rejected',
       last_error = COALESCE(
         (
           SELECT failure_detail FROM jsda_run_membership
            WHERE parent_work_key = jsda_acquisition_jobs_v3.work_key
              AND run_key = jsda_acquisition_jobs_v3.run_key
              AND terminal_state = 'rejected'
            ORDER BY updated_at, child_work_key
            LIMIT 1
         ),
         last_error,
         'descendant_rejected'
       )
 WHERE job_type = 'discover_year'
   AND state IN ('completed', 'waiting_children')
   AND audit_receipt_key IS NOT NULL
   AND audit_receipt_digest IS NOT NULL
   AND EXISTS (
     SELECT 1 FROM jsda_run_membership
      WHERE parent_work_key = jsda_acquisition_jobs_v3.work_key
        AND run_key = jsda_acquisition_jobs_v3.run_key
        AND terminal_state = 'rejected'
   );

UPDATE jsda_acquisition_jobs_v3
   SET state = 'rejected',
       last_error = COALESCE(
         (
           SELECT failure_detail FROM jsda_run_membership
            WHERE parent_work_key = jsda_acquisition_jobs_v3.work_key
              AND run_key = jsda_acquisition_jobs_v3.run_key
              AND terminal_state = 'rejected'
            ORDER BY updated_at, child_work_key
            LIMIT 1
         ),
         last_error,
         'descendant_rejected'
       )
 WHERE job_type = 'discover_root'
   AND state IN ('completed', 'waiting_children')
   AND audit_receipt_key IS NOT NULL
   AND audit_receipt_digest IS NOT NULL
   AND EXISTS (
     SELECT 1 FROM jsda_run_membership
      WHERE parent_work_key = jsda_acquisition_jobs_v3.work_key
        AND run_key = jsda_acquisition_jobs_v3.run_key
        AND terminal_state = 'rejected'
   );

UPDATE jsda_acquisition_jobs_v3
   SET state = 'waiting_children'
 WHERE job_type = 'discover_year'
   AND state = 'completed'
   AND audit_receipt_key IS NOT NULL
   AND audit_receipt_digest IS NOT NULL
   AND EXISTS (
     SELECT 1 FROM jsda_run_membership
      WHERE parent_work_key = jsda_acquisition_jobs_v3.work_key
        AND run_key = jsda_acquisition_jobs_v3.run_key
        AND terminal_state IN ('pending', 'queued', 'running', 'waiting_children', 'failed_transient')
   );

UPDATE jsda_acquisition_jobs_v3
   SET state = 'waiting_children'
 WHERE job_type = 'discover_root'
   AND state = 'completed'
   AND audit_receipt_key IS NOT NULL
   AND audit_receipt_digest IS NOT NULL
   AND EXISTS (
     SELECT 1 FROM jsda_run_membership
      WHERE parent_work_key = jsda_acquisition_jobs_v3.work_key
        AND run_key = jsda_acquisition_jobs_v3.run_key
        AND terminal_state IN ('pending', 'queued', 'running', 'waiting_children', 'failed_transient')
   );

CREATE TRIGGER IF NOT EXISTS jsda_run_membership_enqueued_insert
AFTER INSERT ON jsda_acquisition_jobs_v3
WHEN NEW.parent_work_key IS NOT NULL
BEGIN
    INSERT OR IGNORE INTO jsda_run_membership (
        run_key, root_work_key, parent_work_key, child_work_key,
        membership_kind, child_job_type, terminal_state,
        content_digest, raw_key, audit_receipt_key, audit_receipt_digest,
        failure_reason_code, failure_detail, adopted_at, updated_at
    )
    VALUES (
        NEW.run_key,
        NEW.run_key,
        NEW.parent_work_key,
        NEW.work_key,
        'enqueued',
        NEW.job_type,
        NEW.state,
        NEW.content_digest,
        NEW.raw_key,
        NEW.audit_receipt_key,
        NEW.audit_receipt_digest,
        CASE WHEN NEW.state = 'rejected' THEN 'rejected' ELSE NULL END,
        NEW.last_error,
        NULL,
        NEW.updated_at
    );
END;

CREATE TRIGGER IF NOT EXISTS jsda_run_membership_enqueued_sync
AFTER UPDATE OF state, content_digest, raw_key, audit_receipt_key,
                audit_receipt_digest, last_error
ON jsda_acquisition_jobs_v3
WHEN NEW.parent_work_key IS NOT NULL
 AND (
   NEW.state != 'completed'
   OR (
     NEW.audit_receipt_key IS NOT NULL
     AND NEW.audit_receipt_digest IS NOT NULL
     AND NEW.content_digest IS NOT NULL
     AND NEW.raw_key IS NOT NULL
   )
 )
BEGIN
    UPDATE jsda_run_membership
       SET terminal_state = NEW.state,
           content_digest = NEW.content_digest,
           raw_key = NEW.raw_key,
           audit_receipt_key = NEW.audit_receipt_key,
           audit_receipt_digest = NEW.audit_receipt_digest,
           failure_reason_code = CASE
             WHEN NEW.state = 'rejected' THEN COALESCE(
               failure_reason_code, 'rejected'
             )
             ELSE failure_reason_code
           END,
           failure_detail = CASE
             WHEN NEW.state = 'rejected' THEN NEW.last_error
             ELSE failure_detail
           END,
           updated_at = NEW.updated_at
     WHERE child_work_key = NEW.work_key
       AND run_key = NEW.run_key
       AND membership_kind = 'enqueued';
END;

CREATE TABLE IF NOT EXISTS jsda_job_closures (
    work_key                     TEXT PRIMARY KEY,
    run_key                      TEXT NOT NULL,
    parent_work_key              TEXT,
    job_type                     TEXT NOT NULL,
    closure_state                TEXT NOT NULL CHECK (
        closure_state IN (
            'open',
            'waiting_children',
            'completed',
            'failed',
            'partial'
        )
    ),
    frontier_exhausted           INTEGER NOT NULL DEFAULT 0
                                 CHECK (frontier_exhausted IN (0, 1)),
    descendant_total             INTEGER NOT NULL DEFAULT 0,
    descendant_completed         INTEGER NOT NULL DEFAULT 0,
    descendant_rejected          INTEGER NOT NULL DEFAULT 0,
    descendant_failed_transient  INTEGER NOT NULL DEFAULT 0,
    descendant_nonterminal       INTEGER NOT NULL DEFAULT 0,
    failure_work_key             TEXT,
    failure_reason_code          TEXT,
    failure_detail               TEXT,
    closed_at                    TEXT,
    updated_at                   TEXT NOT NULL,
    FOREIGN KEY (work_key) REFERENCES jsda_acquisition_jobs_v3(work_key)
);

CREATE INDEX IF NOT EXISTS ix_jsda_job_closures_run
    ON jsda_job_closures (run_key, closure_state, work_key);

CREATE TABLE IF NOT EXISTS jsda_run_closures (
    run_key                      TEXT PRIMARY KEY,
    root_work_key                TEXT NOT NULL,
    dataset                      TEXT NOT NULL,
    closure_state                TEXT NOT NULL CHECK (
        closure_state IN (
            'open',
            'waiting_children',
            'completed',
            'failed',
            'partial'
        )
    ),
    frontier_exhausted           INTEGER NOT NULL DEFAULT 0
                                 CHECK (frontier_exhausted IN (0, 1)),
    descendant_total             INTEGER NOT NULL DEFAULT 0,
    descendant_completed         INTEGER NOT NULL DEFAULT 0,
    descendant_rejected          INTEGER NOT NULL DEFAULT 0,
    descendant_failed_transient  INTEGER NOT NULL DEFAULT 0,
    descendant_nonterminal       INTEGER NOT NULL DEFAULT 0,
    failure_work_key             TEXT,
    failure_reason_code          TEXT,
    failure_detail               TEXT,
    closed_at                    TEXT,
    updated_at                   TEXT NOT NULL,
    FOREIGN KEY (root_work_key) REFERENCES jsda_acquisition_jobs_v3(work_key)
);

CREATE INDEX IF NOT EXISTS ix_jsda_run_closures_state
    ON jsda_run_closures (closure_state, updated_at, run_key);

INSERT OR IGNORE INTO jsda_run_closures
    (run_key, root_work_key, dataset, closure_state, updated_at)
SELECT work_key, work_key, dataset, 'open', updated_at
  FROM jsda_acquisition_jobs_v3
 WHERE job_type = 'discover_root';

INSERT OR IGNORE INTO jsda_job_closures
    (work_key, run_key, parent_work_key, job_type, closure_state, updated_at)
SELECT work_key, run_key, parent_work_key, job_type, 'open', updated_at
  FROM jsda_acquisition_jobs_v3
 WHERE job_type IN ('discover_root', 'discover_year');

UPDATE jsda_job_closures
   SET descendant_total = (
         SELECT COUNT(*) FROM jsda_run_membership
          WHERE parent_work_key = jsda_job_closures.work_key
            AND run_key = jsda_job_closures.run_key
       ),
       descendant_completed = (
         SELECT COUNT(*) FROM jsda_run_membership
          WHERE parent_work_key = jsda_job_closures.work_key
            AND run_key = jsda_job_closures.run_key
            AND terminal_state = 'completed'
            AND audit_receipt_key IS NOT NULL
            AND audit_receipt_digest IS NOT NULL
            AND content_digest IS NOT NULL
            AND raw_key IS NOT NULL
       ),
       descendant_rejected = (
         SELECT COUNT(*) FROM jsda_run_membership
          WHERE parent_work_key = jsda_job_closures.work_key
            AND run_key = jsda_job_closures.run_key
            AND terminal_state = 'rejected'
       ),
       descendant_failed_transient = (
         SELECT COUNT(*) FROM jsda_run_membership
          WHERE parent_work_key = jsda_job_closures.work_key
            AND run_key = jsda_job_closures.run_key
            AND terminal_state = 'failed_transient'
       ),
       descendant_nonterminal = (
         SELECT COUNT(*) FROM jsda_run_membership
          WHERE parent_work_key = jsda_job_closures.work_key
            AND run_key = jsda_job_closures.run_key
            AND terminal_state IN
                ('pending', 'queued', 'running', 'waiting_children')
       ),
       frontier_exhausted = CASE
         WHEN (
           SELECT state FROM jsda_acquisition_jobs_v3
            WHERE work_key = jsda_job_closures.work_key
         ) IN ('waiting_children', 'completed', 'rejected') THEN 1
         ELSE frontier_exhausted
       END,
       failure_work_key = (
         SELECT child_work_key FROM jsda_run_membership
          WHERE parent_work_key = jsda_job_closures.work_key
            AND run_key = jsda_job_closures.run_key
            AND terminal_state = 'rejected'
          ORDER BY updated_at, child_work_key
          LIMIT 1
       ),
       failure_reason_code = CASE
         WHEN (
           SELECT COUNT(*) FROM jsda_run_membership
            WHERE parent_work_key = jsda_job_closures.work_key
              AND run_key = jsda_job_closures.run_key
              AND terminal_state = 'rejected'
         ) > 0 THEN COALESCE(
           (
             SELECT failure_reason_code FROM jsda_run_membership
              WHERE parent_work_key = jsda_job_closures.work_key
                AND run_key = jsda_job_closures.run_key
                AND terminal_state = 'rejected'
              ORDER BY updated_at, child_work_key
              LIMIT 1
           ),
           'descendant_rejected'
         )
         ELSE failure_reason_code
       END,
       failure_detail = (
         SELECT failure_detail FROM jsda_run_membership
          WHERE parent_work_key = jsda_job_closures.work_key
            AND run_key = jsda_job_closures.run_key
            AND terminal_state = 'rejected'
          ORDER BY updated_at, child_work_key
          LIMIT 1
       );

UPDATE jsda_run_closures
   SET descendant_total = (
         SELECT COUNT(DISTINCT child_work_key) FROM jsda_run_membership
          WHERE run_key = jsda_run_closures.run_key
       ),
       descendant_completed = (
         SELECT COUNT(DISTINCT child_work_key) FROM jsda_run_membership
          WHERE run_key = jsda_run_closures.run_key
            AND terminal_state = 'completed'
            AND audit_receipt_key IS NOT NULL
            AND audit_receipt_digest IS NOT NULL
            AND content_digest IS NOT NULL
            AND raw_key IS NOT NULL
       ),
       descendant_rejected = (
         SELECT COUNT(DISTINCT child_work_key) FROM jsda_run_membership
          WHERE run_key = jsda_run_closures.run_key
            AND terminal_state = 'rejected'
       ),
       descendant_failed_transient = (
         SELECT COUNT(DISTINCT child_work_key) FROM jsda_run_membership
          WHERE run_key = jsda_run_closures.run_key
            AND terminal_state = 'failed_transient'
       ),
       descendant_nonterminal = (
         SELECT COUNT(DISTINCT child_work_key) FROM jsda_run_membership
          WHERE run_key = jsda_run_closures.run_key
            AND terminal_state IN
                ('pending', 'queued', 'running', 'waiting_children')
       ),
       frontier_exhausted = CASE
         WHEN (
           SELECT state FROM jsda_acquisition_jobs_v3
            WHERE work_key = jsda_run_closures.root_work_key
         ) IN ('waiting_children', 'completed', 'rejected') THEN 1
         ELSE frontier_exhausted
       END,
       failure_work_key = (
         SELECT child_work_key FROM jsda_run_membership
          WHERE run_key = jsda_run_closures.run_key
            AND terminal_state = 'rejected'
          ORDER BY updated_at, child_work_key
          LIMIT 1
       ),
       failure_reason_code = CASE
         WHEN (
           SELECT COUNT(DISTINCT child_work_key) FROM jsda_run_membership
            WHERE run_key = jsda_run_closures.run_key
              AND terminal_state = 'rejected'
         ) > 0 THEN COALESCE(
           (
             SELECT failure_reason_code FROM jsda_run_membership
              WHERE run_key = jsda_run_closures.run_key
                AND terminal_state = 'rejected'
              ORDER BY updated_at, child_work_key
              LIMIT 1
           ),
           'descendant_rejected'
         )
         ELSE failure_reason_code
       END,
       failure_detail = (
         SELECT failure_detail FROM jsda_run_membership
          WHERE run_key = jsda_run_closures.run_key
            AND terminal_state = 'rejected'
          ORDER BY updated_at, child_work_key
          LIMIT 1
       );

UPDATE jsda_job_closures
   SET closure_state = CASE
         WHEN descendant_rejected > 0 AND descendant_completed > 0 THEN 'partial'
         WHEN descendant_rejected > 0 THEN 'failed'
         WHEN frontier_exhausted = 1
          AND descendant_total > 0
          AND descendant_completed = descendant_total
          AND descendant_rejected = 0
          AND descendant_failed_transient = 0
          AND descendant_nonterminal = 0 THEN 'completed'
         WHEN frontier_exhausted = 1 THEN 'waiting_children'
         ELSE 'open'
       END,
       closed_at = CASE
         WHEN descendant_rejected > 0 THEN updated_at
         WHEN frontier_exhausted = 1
          AND descendant_total > 0
          AND descendant_completed = descendant_total
          AND descendant_rejected = 0
          AND descendant_failed_transient = 0
          AND descendant_nonterminal = 0 THEN updated_at
         ELSE NULL
       END;

UPDATE jsda_run_closures
   SET closure_state = CASE
         WHEN descendant_rejected > 0 AND descendant_completed > 0 THEN 'partial'
         WHEN descendant_rejected > 0 THEN 'failed'
         WHEN frontier_exhausted = 1
          AND descendant_total > 0
          AND descendant_completed = descendant_total
          AND descendant_rejected = 0
          AND descendant_failed_transient = 0
          AND descendant_nonterminal = 0 THEN 'completed'
         WHEN frontier_exhausted = 1 THEN 'waiting_children'
         ELSE 'open'
       END,
       closed_at = CASE
         WHEN descendant_rejected > 0 THEN updated_at
         WHEN frontier_exhausted = 1
          AND descendant_total > 0
          AND descendant_completed = descendant_total
          AND descendant_rejected = 0
          AND descendant_failed_transient = 0
          AND descendant_nonterminal = 0 THEN updated_at
         ELSE NULL
       END;

-- Earlier queue-v2 code emitted PASS for individual leaves. Preserve those
-- rows for audit, but append an authoritative correction for every affected
-- run whose governed closure is not actually complete. Current projections
-- select the latest row and therefore cannot surface the superseded PASS.
INSERT INTO ingestion_run_log (ran_at, source, runtime, status, detail)
SELECT COALESCE(rc.updated_at, CURRENT_TIMESTAMP),
       'jsda',
       'cloudflare_queue_v2',
       CASE WHEN rc.closure_state = 'partial' THEN 'partial' ELSE 'fail' END,
       json_object(
         'mode', 'cloudflare_queue_v2',
         'run_id', rc.run_key,
         'job_id', rc.root_work_key,
         'result', 'rejected',
         'reason', 'migration_invalidated_legacy_false_pass',
         'closure_state', rc.closure_state,
         'supersedes_false_pass', 1
       )
  FROM jsda_run_closures AS rc
 WHERE rc.closure_state != 'completed'
   AND EXISTS (
     SELECT 1 FROM ingestion_run_log AS old
      WHERE old.source = 'jsda'
        AND old.runtime = 'cloudflare_queue_v2'
        AND old.status = 'pass'
        AND json_extract(old.detail, '$.run_id') = rc.run_key
   )
   AND NOT EXISTS (
     SELECT 1 FROM ingestion_run_log AS correction
      WHERE correction.source = 'jsda'
        AND correction.runtime = 'cloudflare_queue_v2'
        AND json_extract(correction.detail, '$.run_id') = rc.run_key
        AND json_extract(correction.detail, '$.reason') =
            'migration_invalidated_legacy_false_pass'
   );
