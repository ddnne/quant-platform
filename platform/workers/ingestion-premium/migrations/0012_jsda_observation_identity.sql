-- Three-identity JSDA acquisition contract.
-- SourceObject: stable canonical official URL/locator.
-- Observation: run/freshness-epoch scoped attempt to observe that object.
-- Artifact: immutable content digest and R2 key.
-- v2 job rows remain the work graph; rolling URLs may be re-observed.

ALTER TABLE jsda_acquisition_jobs_v2 ADD COLUMN source_object_id TEXT;
ALTER TABLE jsda_acquisition_jobs_v2 ADD COLUMN freshness TEXT;
ALTER TABLE jsda_acquisition_jobs_v2 ADD COLUMN observation_epoch TEXT;

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

CREATE TABLE IF NOT EXISTS jsda_source_objects (
    source_object_id         TEXT PRIMARY KEY,
    dataset                  TEXT NOT NULL,
    canonical_url            TEXT NOT NULL,
    freshness                TEXT NOT NULL CHECK (freshness IN ('archive', 'rolling')),
    current_digest           TEXT,
    current_raw_key          TEXT,
    current_observation_key  TEXT,
    first_seen_at            TEXT NOT NULL,
    last_observed_at         TEXT,
    updated_at               TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_jsda_source_objects_locator
    ON jsda_source_objects (dataset, canonical_url);

CREATE TABLE IF NOT EXISTS jsda_artifacts (
    content_digest           TEXT PRIMARY KEY,
    raw_key                  TEXT NOT NULL UNIQUE,
    dataset                  TEXT NOT NULL,
    source_object_id         TEXT NOT NULL,
    first_seen_at            TEXT NOT NULL,
    FOREIGN KEY (source_object_id) REFERENCES jsda_source_objects(source_object_id)
);

CREATE INDEX IF NOT EXISTS ix_jsda_artifacts_source
    ON jsda_artifacts (source_object_id, first_seen_at);

CREATE TABLE IF NOT EXISTS jsda_observations (
    observation_key          TEXT PRIMARY KEY,
    source_object_id         TEXT NOT NULL,
    work_key                 TEXT NOT NULL,
    run_key                  TEXT NOT NULL,
    dataset                  TEXT NOT NULL,
    target_url               TEXT NOT NULL,
    freshness                TEXT NOT NULL CHECK (freshness IN ('archive', 'rolling')),
    epoch                    TEXT NOT NULL,
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

CREATE INDEX IF NOT EXISTS ix_jsda_observations_source_time
    ON jsda_observations (source_object_id, observed_at, observation_key);
