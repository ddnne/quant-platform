-- Raw retention completeness is a raw-plane acquisition status.
-- Coverage COMPLETE is not stored in this column.
-- Widen CHECK to allow ACQUIRED (new writes) while keeping historical COMPLETE
-- rows readable. Do not rewrite existing COMPLETE labels to invent Coverage.

CREATE TABLE raw_retention_manifests__v10 (
    dataset      TEXT NOT NULL,
    run_id       INTEGER NOT NULL,
    manifest_key TEXT NOT NULL,
    page_count   INTEGER NOT NULL CHECK (page_count >= 0),
    row_count    INTEGER NOT NULL CHECK (row_count >= 0),
    raw_bytes    INTEGER NOT NULL CHECK (raw_bytes >= 0),
    data_digest  TEXT NOT NULL,
    completeness TEXT NOT NULL CHECK (
        completeness IN ('ACQUIRED', 'FAILED', 'COMPLETE')
    ),
    created_at   TEXT NOT NULL,
    PRIMARY KEY (dataset, run_id)
);

INSERT INTO raw_retention_manifests__v10
    SELECT dataset, run_id, manifest_key, page_count, row_count, raw_bytes,
           data_digest, completeness, created_at
    FROM raw_retention_manifests;

DROP TABLE raw_retention_manifests;
ALTER TABLE raw_retention_manifests__v10 RENAME TO raw_retention_manifests;

CREATE INDEX IF NOT EXISTS ix_raw_retention_run_complete
    ON raw_retention_manifests (run_id, completeness, dataset);
