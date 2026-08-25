-- Three-identity JSDA acquisition contract plus descendant run closure.
-- SourceObject: stable canonical official URL/locator.
-- Observation: D1-owned monotonic generation of that object.
-- Artifact: immutable content digest; locations are separate R2 keys.
-- v2 job rows remain the work graph; rolling URLs may be re-observed.
-- Discovery frontier exhaustion is not terminal success: a parent stays
-- waiting_children until every governed descendant is durably terminal.

-- D1 applies each statement independently, so PRAGMA foreign_keys does not
-- cover a RENAME. Copy, drop children, then recreate the parent with the
-- expanded state/result checks.
CREATE TABLE jsda_acquisition_jobs_v2_next AS
SELECT * FROM jsda_acquisition_jobs_v2;

CREATE TABLE jsda_acquisition_events_v2_next AS
SELECT * FROM jsda_acquisition_events_v2;

CREATE TABLE jsda_acquisition_discoveries_v2_next AS
SELECT * FROM jsda_acquisition_discoveries_v2;

DROP TABLE jsda_acquisition_events_v2;
DROP TABLE jsda_acquisition_discoveries_v2;
DROP TABLE jsda_acquisition_jobs_v2;

CREATE TABLE jsda_acquisition_jobs_v2 (
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

INSERT INTO jsda_acquisition_jobs_v2 (
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
  FROM jsda_acquisition_jobs_v2_next;

DROP TABLE jsda_acquisition_jobs_v2_next;

CREATE TABLE jsda_acquisition_events_v2 (
    event_id               INTEGER PRIMARY KEY AUTOINCREMENT,
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
    FOREIGN KEY (work_key) REFERENCES jsda_acquisition_jobs_v2(work_key)
);

INSERT INTO jsda_acquisition_events_v2 (
    event_id, work_key, run_key, dataset, job_type, segment_id, attempt, cursor,
    result, reason_code, detail, content_digest, raw_key,
    audit_receipt_key, audit_receipt_digest, occurred_at
)
SELECT
    event_id, work_key, run_key, dataset, job_type, segment_id, attempt, cursor,
    result, reason_code, detail, content_digest, raw_key,
    audit_receipt_key, audit_receipt_digest, occurred_at
  FROM jsda_acquisition_events_v2_next;

DROP TABLE jsda_acquisition_events_v2_next;

CREATE TABLE jsda_acquisition_discoveries_v2 (
    parent_work_key        TEXT NOT NULL,
    child_work_key         TEXT NOT NULL,
    run_key                TEXT NOT NULL,
    discovered_at          TEXT NOT NULL,
    PRIMARY KEY (parent_work_key, child_work_key),
    FOREIGN KEY (parent_work_key) REFERENCES jsda_acquisition_jobs_v2(work_key),
    FOREIGN KEY (child_work_key) REFERENCES jsda_acquisition_jobs_v2(work_key)
);

INSERT INTO jsda_acquisition_discoveries_v2 (
    parent_work_key, child_work_key, run_key, discovered_at
)
SELECT parent_work_key, child_work_key, run_key, discovered_at
  FROM jsda_acquisition_discoveries_v2_next;

DROP TABLE jsda_acquisition_discoveries_v2_next;

CREATE INDEX IF NOT EXISTS ix_jsda_discoveries_v2_run
    ON jsda_acquisition_discoveries_v2 (run_key, parent_work_key, child_work_key);

UPDATE jsda_acquisition_jobs_v2
   SET freshness = 'archive',
       observation_epoch = 'archive'
 WHERE job_type = 'fetch_file'
   AND freshness IS NULL;

DROP INDEX IF EXISTS ux_jsda_jobs_v2_fetched_file_url;

CREATE UNIQUE INDEX IF NOT EXISTS ux_jsda_jobs_v2_archive_file_url
    ON jsda_acquisition_jobs_v2 (dataset, job_type, target_url)
    WHERE job_type = 'fetch_file' AND freshness = 'archive';

CREATE UNIQUE INDEX IF NOT EXISTS ux_jsda_jobs_v2_rolling_file_epoch
    ON jsda_acquisition_jobs_v2 (dataset, job_type, target_url, run_key)
    WHERE job_type = 'fetch_file' AND freshness = 'rolling';

CREATE INDEX IF NOT EXISTS ix_jsda_jobs_v2_state_updated
    ON jsda_acquisition_jobs_v2 (state, updated_at, work_key);

CREATE INDEX IF NOT EXISTS ix_jsda_jobs_v2_run_parent
    ON jsda_acquisition_jobs_v2 (run_key, parent_work_key, job_type, state);

CREATE INDEX IF NOT EXISTS ix_jsda_events_v2_run_time
    ON jsda_acquisition_events_v2 (run_key, occurred_at, event_id);

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
    FOREIGN KEY (work_key) REFERENCES jsda_acquisition_jobs_v2(work_key)
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
    FOREIGN KEY (root_work_key) REFERENCES jsda_acquisition_jobs_v2(work_key),
    FOREIGN KEY (parent_work_key) REFERENCES jsda_acquisition_jobs_v2(work_key),
    FOREIGN KEY (child_work_key) REFERENCES jsda_acquisition_jobs_v2(work_key),
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
UPDATE jsda_acquisition_jobs_v2
   SET state = 'rejected',
       last_error = COALESCE(
         (
           SELECT child.last_error
             FROM jsda_acquisition_jobs_v2 AS child
            WHERE child.parent_work_key = jsda_acquisition_jobs_v2.work_key
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
       FROM jsda_acquisition_jobs_v2 AS child
      WHERE child.parent_work_key = jsda_acquisition_jobs_v2.work_key
        AND child.state = 'rejected'
   );

UPDATE jsda_acquisition_jobs_v2
   SET state = 'rejected',
       last_error = COALESCE(
         (
           SELECT child.last_error
             FROM jsda_acquisition_jobs_v2 AS child
            WHERE child.parent_work_key = jsda_acquisition_jobs_v2.work_key
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
       FROM jsda_acquisition_jobs_v2 AS child
      WHERE child.parent_work_key = jsda_acquisition_jobs_v2.work_key
        AND child.state = 'rejected'
   );

UPDATE jsda_acquisition_jobs_v2
   SET state = 'waiting_children'
 WHERE job_type = 'discover_year'
   AND state = 'completed'
   AND audit_receipt_key IS NOT NULL
   AND audit_receipt_digest IS NOT NULL
   AND EXISTS (
     SELECT 1
       FROM jsda_acquisition_jobs_v2 AS child
      WHERE child.parent_work_key = jsda_acquisition_jobs_v2.work_key
        AND child.state NOT IN ('completed', 'rejected')
   );

UPDATE jsda_acquisition_jobs_v2
   SET state = 'waiting_children'
 WHERE job_type = 'discover_root'
   AND state = 'completed'
   AND audit_receipt_key IS NOT NULL
   AND audit_receipt_digest IS NOT NULL
   AND EXISTS (
     SELECT 1
       FROM jsda_acquisition_jobs_v2 AS child
      WHERE child.parent_work_key = jsda_acquisition_jobs_v2.work_key
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
        ELSE 'rejected'
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
        WHEN child.run_key != d.run_key
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
        WHEN child.run_key != d.run_key
            THEN 'adopted child lacks authoritative artifact/audit evidence'
        ELSE NULL
    END,
    CASE WHEN child.run_key != d.run_key THEN d.discovered_at ELSE NULL END,
    d.discovered_at
  FROM jsda_acquisition_discoveries_v2 AS d
  JOIN jsda_acquisition_jobs_v2 AS child
    ON child.work_key = d.child_work_key;

UPDATE jsda_acquisition_jobs_v2
   SET state = 'rejected',
       last_error = COALESCE(
         (
           SELECT failure_detail FROM jsda_run_membership
            WHERE parent_work_key = jsda_acquisition_jobs_v2.work_key
              AND run_key = jsda_acquisition_jobs_v2.run_key
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
      WHERE parent_work_key = jsda_acquisition_jobs_v2.work_key
        AND run_key = jsda_acquisition_jobs_v2.run_key
        AND terminal_state = 'rejected'
   );

UPDATE jsda_acquisition_jobs_v2
   SET state = 'rejected',
       last_error = COALESCE(
         (
           SELECT failure_detail FROM jsda_run_membership
            WHERE parent_work_key = jsda_acquisition_jobs_v2.work_key
              AND run_key = jsda_acquisition_jobs_v2.run_key
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
      WHERE parent_work_key = jsda_acquisition_jobs_v2.work_key
        AND run_key = jsda_acquisition_jobs_v2.run_key
        AND terminal_state = 'rejected'
   );

UPDATE jsda_acquisition_jobs_v2
   SET state = 'waiting_children'
 WHERE job_type = 'discover_year'
   AND state = 'completed'
   AND audit_receipt_key IS NOT NULL
   AND audit_receipt_digest IS NOT NULL
   AND EXISTS (
     SELECT 1 FROM jsda_run_membership
      WHERE parent_work_key = jsda_acquisition_jobs_v2.work_key
        AND run_key = jsda_acquisition_jobs_v2.run_key
        AND terminal_state IN ('pending', 'queued', 'running', 'waiting_children', 'failed_transient')
   );

UPDATE jsda_acquisition_jobs_v2
   SET state = 'waiting_children'
 WHERE job_type = 'discover_root'
   AND state = 'completed'
   AND audit_receipt_key IS NOT NULL
   AND audit_receipt_digest IS NOT NULL
   AND EXISTS (
     SELECT 1 FROM jsda_run_membership
      WHERE parent_work_key = jsda_acquisition_jobs_v2.work_key
        AND run_key = jsda_acquisition_jobs_v2.run_key
        AND terminal_state IN ('pending', 'queued', 'running', 'waiting_children', 'failed_transient')
   );

CREATE TRIGGER IF NOT EXISTS jsda_run_membership_enqueued_insert
AFTER INSERT ON jsda_acquisition_jobs_v2
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
ON jsda_acquisition_jobs_v2
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
    FOREIGN KEY (work_key) REFERENCES jsda_acquisition_jobs_v2(work_key)
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
    FOREIGN KEY (root_work_key) REFERENCES jsda_acquisition_jobs_v2(work_key)
);

CREATE INDEX IF NOT EXISTS ix_jsda_run_closures_state
    ON jsda_run_closures (closure_state, updated_at, run_key);

INSERT OR IGNORE INTO jsda_run_closures
    (run_key, root_work_key, dataset, closure_state, updated_at)
SELECT work_key, work_key, dataset, 'open', updated_at
  FROM jsda_acquisition_jobs_v2
 WHERE job_type = 'discover_root';

INSERT OR IGNORE INTO jsda_job_closures
    (work_key, run_key, parent_work_key, job_type, closure_state, updated_at)
SELECT work_key, run_key, parent_work_key, job_type, 'open', updated_at
  FROM jsda_acquisition_jobs_v2
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
           SELECT state FROM jsda_acquisition_jobs_v2
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
           SELECT state FROM jsda_acquisition_jobs_v2
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
