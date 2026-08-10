# storage

構造化データのスキーマ・ライタ。

Phase 1 実装:

- `schema.py` — SQLite DDL（6 テーブル + run log）。各テーブルは自然キー `PRIMARY KEY` で冪等 upsert。全行に PIT 列 `event_time` / `available_at` / `source` / `ingested_at` と `raw_payload`。
- `sqlite_store.py` — `SqliteStore`。`upsert` は `available_at` 必須を検証し `INSERT OR REPLACE`。`count` / `fetch_all` / `fetch_where` / `log_run`。

既定パス: `data/structured/ingestion.sqlite`（gitignore）。Raw は `data/raw/`（`ingestion/common/paths.py`）。将来の R2/D1 レイアウトは `schema.py` コメント参照。

PIT のため `available_at` は構造化保存で必須（空は拒否）。
