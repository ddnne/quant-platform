# storage

構造化データのスキーマ・ライタ。

Phase 1 実装:

- `schema.py` — SQLite DDL（6 テーブル + run log）。各テーブルは自然キー `PRIMARY KEY` で冪等 upsert。全行に PIT 列 `event_time` / `available_at` / `source` / `ingested_at` と `raw_payload`。
- `sqlite_store.py` — `SqliteStore`。`upsert` は `available_at` 必須を検証し `INSERT OR REPLACE`。`count` / `fetch_all` / `fetch_where` / `log_run`。

Host-local `data/structured/ingestion.sqlite` and `data/raw/` are
developer/recovery compatibility (gitignored). Operator storage is
Cloudflare R2 (persistent authority) plus D1 metadata; Container SQLite is
ephemeral. `SqliteStore` remains the local schema/writer used by tests and
opt-in recovery CLIs (`QP_ALLOW_LOCAL_MARKET_DATA=1`).

PIT のため `available_at` は構造化保存で必須（空は拒否）。

Receipt/Coverage verification authorities are package-owned under
`storage/authorities/`: the Coverage transition public-key registry and the
signed Receipt claims schema ship in the wheel beside their verify-only
consumers. Their canonical identities and digests are unchanged by the move;
runtime loading has no repository-root or CWD fallback.

Phase 6 hardening adds formal migrations for `dataset_coverage`, publication
lifecycle/quality rows, and fact/revision mutation triggers.

Phase 6.1 adds Coverage V2:

- `coverage_segments` is the independent required inventory.
- `collection_receipts` stores expected/observed counts, raw pages/rows,
  structured rows, pagination exhaustion, digests, run/status/error/time.
- `dataset_coverage` is COMPLETE only when every governed required segment is
  COMPLETE; observed min/max alone cannot prove it.
- Event windows may reconcile 0 raw rows to 0 structured rows as COMPLETE when
  the successful receipt and retained raw query evidence prove the window.

JSDA governed tables retain separate PIT timestamps and revision tables.
`SqliteStore` applies ordered idempotent migrations on open; operators should
back up the staging database before first open after an upgrade.
