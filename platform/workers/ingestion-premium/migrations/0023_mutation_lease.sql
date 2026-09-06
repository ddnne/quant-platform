-- Single-operator D1 mutation lease and resumable JSDA cutover state.

CREATE TABLE IF NOT EXISTS quant_ingest_mutation_lease (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    environment TEXT NOT NULL DEFAULT '',
    database_id TEXT NOT NULL DEFAULT '',
    manifest_digest TEXT NOT NULL DEFAULT '',
    source_sha TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    nonce TEXT NOT NULL DEFAULT '',
    phase TEXT NOT NULL DEFAULT 'vacant' CHECK (
        phase IN ('vacant','acquired','migrating','verifying','recovery_required')
    ),
    expires_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z',
    remote_spawned INTEGER NOT NULL DEFAULT 0 CHECK (remote_spawned IN (0,1)),
    updated_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z'
);

INSERT OR IGNORE INTO quant_ingest_mutation_lease(singleton) VALUES (1);

CREATE TRIGGER IF NOT EXISTS quant_ingest_mutation_lease_no_steal
BEFORE UPDATE ON quant_ingest_mutation_lease
WHEN OLD.phase IN ('migrating','verifying','recovery_required')
 AND NEW.phase = 'acquired'
BEGIN
    SELECT RAISE(ABORT, 'sticky mutation lease cannot be stolen');
END;

CREATE TABLE IF NOT EXISTS jsda_v3_cutover_run (
    run_id TEXT PRIMARY KEY CHECK (length(run_id)=71 AND substr(run_id,1,7)='sha256:'),
    environment TEXT NOT NULL CHECK (environment IN ('staging','production')),
    source_sha TEXT NOT NULL CHECK (length(source_sha)=40),
    selected_version_id TEXT NOT NULL,
    selected_deployment_id TEXT NOT NULL,
    selected_version_tag TEXT NOT NULL CHECK (length(selected_version_tag)=40),
    cutover_config_digest TEXT NOT NULL CHECK (length(cutover_config_digest)=71),
    rollback_bookmark TEXT NOT NULL CHECK (length(rollback_bookmark)=59),
    owner TEXT NOT NULL CHECK (length(owner)=38),
    fence TEXT NOT NULL CHECK (length(fence)=64),
    phase TEXT NOT NULL CHECK (phase IN (
        'queue_paused','bridge_established','deployed','v3_active','activated'
    )),
    evidence_digest TEXT NOT NULL CHECK (length(evidence_digest)=71),
    drain_evidence_digest TEXT,
    document_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS jsda_v3_cutover_run_no_delete
BEFORE DELETE ON jsda_v3_cutover_run
BEGIN
    SELECT RAISE(ABORT, 'cutover run cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS jsda_v3_cutover_run_identity_immutable
BEFORE UPDATE ON jsda_v3_cutover_run
WHEN OLD.run_id IS NOT NEW.run_id
  OR OLD.environment IS NOT NEW.environment
  OR OLD.source_sha IS NOT NEW.source_sha
  OR OLD.selected_version_id IS NOT NEW.selected_version_id
  OR OLD.selected_deployment_id IS NOT NEW.selected_deployment_id
  OR OLD.selected_version_tag IS NOT NEW.selected_version_tag
  OR OLD.cutover_config_digest IS NOT NEW.cutover_config_digest
  OR OLD.rollback_bookmark IS NOT NEW.rollback_bookmark
  OR OLD.owner IS NOT NEW.owner OR OLD.fence IS NOT NEW.fence
BEGIN
    SELECT RAISE(ABORT, 'cutover run identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS jsda_v3_cutover_run_adjacent_phase
BEFORE UPDATE OF phase ON jsda_v3_cutover_run
WHEN NOT (
       (OLD.phase='queue_paused' AND NEW.phase='bridge_established')
    OR (OLD.phase='bridge_established' AND NEW.phase='deployed')
    OR (OLD.phase='deployed' AND NEW.phase='v3_active')
    OR (OLD.phase='v3_active' AND NEW.phase='activated')
)
BEGIN
    SELECT RAISE(ABORT, 'cutover run phase must advance exactly once');
END;
