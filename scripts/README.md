# scripts

**Bootstrap (B1-e):** `scripts/_bootstrap.py` → `ensure_repo_root()` (repo root +
`packages/{edge,data_plane,research_runtime,product}` plane paths). Ops/coverage/receipt
CLIs (`issue_receipts_parallel`, `publish_ops_projection`, `export_ops_projection`,
`refresh_coverage_ledger`, `sync_dataset_coverage_from_segments`, `ops_status`,
`ops_reeval_*`, `write_collection_receipts`, `issue_signed_receipts_for_segments`,
`restore_local_complete_from_receipt`,
`backfill_status_report`,
`generate_governed_js`, `verify_governed_js_drift`,
`report_raw_throughput`) use it.
CLIs under `scripts/` and `scripts/ops/` use the same `_bootstrap` finder.
Candidate eval is `POST /v1/daily-path`, not `python -m research.unique_logic`
(that CLI is a retired fail-closed stub). Live counts / GO gates: [docs/phase62_residual_status.md](../docs/phase62_residual_status.md)
only. Do not launch Mass / READY / Phase7 / `cf_premium_backfill` from residual prose alone.

**Mandatory local CI:** [`verify_ci.sh`](verify_ci.sh) (active Worker lanes in parallel; no `VERIFY_*` skips). It pins `uv 0.11.26`, runs `uv sync --frozen --extra dev`, `pytest tests/`, the Evaluation IR freeze, verifies the machine-readable Cloudflare binding manifest, then runs each Worker through `npm ci`, tests, typecheck, base/production/staging Wrangler dry-runs, and generated-types checks. The legacy catalog is not compiled into CI or Worker source. Wrangler, TypeScript, and Workers types are exact-versioned. Never `--legacy-peer-deps`; never skip missing dependencies; never live `wrangler deploy`.

[`finding_ledger_ci.py`](finding_ledger_ci.py) runs before source-integration CI.
It validates the exact tracked ledger schema and OPEN P0 inventory, but it does
not authorize a deployment, release, or source-safety decision. Independent
review may accept an inactive fail-closed implementation while operational
work remains; an OPEN row may also still contain source work such as crash-safe
recovery.

[`finding_ledger_gate.py`](finding_ledger_gate.py) remains mandatory before
authenticated deployment acceptance, release-evidence construction, READY
publication, and Controlled Pilot. It accepts no ledger path argument:
production always reads the tracked `docs/phase633_finding_ledger.json` and
fails until every code-pinned P0 finding is `FIXED` and the independent-review
unresolved count is zero. Finding IDs are a closed inventory so deleting every
row cannot vacuously pass. Adding a real finding requires one reviewed change
that updates the JSON and Markdown rows and the code-pinned ID inventory
together; the row starts `OPEN`, and a later reviewed evidence commit may mark
it `FIXED`. Test fixtures may call the private bytes evaluator with an all-FIXED
document, but no production release CLI accepts a caller-selected ledger.

[`verify_all.sh`](verify_all.sh) is a skippable helper only. Merge authority is the live native GitHub check from the Cloudflare Workers & Pages GitHub App for the repository-root Build running `verify_ci.sh`. The caller-supplied receipt aggregator is removed. Do not add `.github/workflows`. See [`docs/ci/workers_builds.md`](../docs/ci/workers_builds.md).

**Authenticated production acceptance:**
[`verify_cloudflare_deployment_acceptance.sh`](verify_cloudflare_deployment_acceptance.sh)
runs mandatory CI and then compares live production `wrangler secret list`
names with the frozen manifest. It requires Cloudflare API token/account
presence, requests names only, never prints values, and fails closed on drift.

Phase 6 hardening utilities:

- `ops_status.py --json` — offline READY snapshot, coverage, B0 and validation status.
- `encrypt_d1_backup.py` — stream a fresh governed production or staging D1 SQL export into a
  temporary SQLite restore, run `integrity_check`, verify the fixed
  environment-specific `quant-ingest` database ID from the canonical migration
  manifest plus the canonical minimum schema and non-empty
  production evidence, then encrypt with AES-256-GCM. Database/export/restore
  evidence, environment, format/cipher, nonce, and key fingerprint are
  authenticated in the v3 header. Only a successfully decrypted
  and re-verified artifact is atomically published; the plaintext is then
  removed by default. Any restore/schema/encryption failure retains the source
  and leaves the target unpublished. Retention requires the explicit unsafe
  `--keep-source` opt-in. The raw 32-byte key stays outside the repository with
  mode `0600`; neither SQL contents nor key material is logged. The encrypted
  artifact is rollback material only. Its header, restore verification, key,
  or digest never attests the executing source SHA and never grants migration
  or staging authority.
- `d1_ingestion_migration_validation.py` — restore a remote export locally,
  require canonical migration-history prefix and FK/integrity checks, replay
  pending 0011-0018 on an isolated copy, and prove exact final schema plus
  populated v2-to-v3 JSDA preservation. Recorded partial/malformed states fail.
- `apply_ingestion_d1_migrations.py` — a source-only fail-closed D1
  observation/HOLD and recovery implementation; its legacy filename does not
  make it a remote mutation authority. The canonical reservation identity is
  environment + canonical database ID + source SHA + canonical manifest
  digest. Local create-only/`O_EXCL` files are single-host crash markers, not a
  cross-host lock, so both staging and production remain `HOLD` until a trusted
  remote lock and control-plane source-SHA attestation exist. Production
  independently re-observes the canonical staging D1 and accepts no caller
  staging JSON, path, backup, or key. Recovery classifies
  `RECOVERED_APPLIED_EXACT` as `APPLIED` only for exact canonical postflight
  with zero pending, and `RECOVERED_NOT_APPLIED` as `NOT_APPLIED` only when a
  fresh live observation exactly matches the recorded baseline; every other
  state stays `UNKNOWN`. No recovery result grants mutation authority or
  permits a blind retry. This revision publishes no remote apply command.
- `build_release_evidence.py` — validate normalized post-deploy observations
  and emit a content-addressed, read-only, non-secret v4 manifest suitable for
  a GitHub Release. Every check/build/deployment/migration/smoke/MCP observation
  has a closed collector-provenance record (evidence ID, UTC timestamp, response
  digest, source SHA). Nested extra fields, local paths, provider-token shapes,
  unverified backup metadata, non-canonical migrations, unproven Pilot `GO`,
  and Mass `GO` are rejected. The exact pinned finding-ledger byte digest and
  OPEN-P0 inventory are part of the content-addressed payload and cannot be
  caller-substituted. JSDA acceptance specifically requires `/health/ready`,
  HTTP 200, `product_ready:true`, `cutover:"V3_ACTIVE"`, the deployed source
  SHA/version, and a response digest equal to its provenance response digest;
  generic `/health` `PASS` evidence is rejected.

Rollback-only production backup example (timestamps and final SHA must be the
observed values):

```bash
uv run python scripts/encrypt_d1_backup.py encrypt \
  quant-ingest.sql quant-ingest.sql.enc \
  --key /secure/private/d1_backup_aes256.key \
  --environment production \
  --database-name quant-ingest \
  --database-id be6fdcf8-40be-41fc-9535-7facd1fc2ffc \
  --exported-at 2026-08-25T06:00:00Z \
  --release-source-sha 0123456789abcdef0123456789abcdef01234567
```

The successful JSON output is the exact closed `backup` object accepted by
`build_release_evidence.py`; it intentionally contains no local path. Re-run
`verify` against the encrypted artifact before publishing the release manifest.
- Paper CLIs (`run_paper_once.py`, `run_agents_paper_once.py`, `rebuild_paper_index.py`) are **deleted**. Paper runtime stays in `packages/research_runtime/paper_runtime/`.
- `python -m mcp_servers.quant_data --list-tools` — Quant Data Access MCP smoke.
- `export_ops_projection.py` — verified local Coverage/READY/B0 metadataを bounded
  D1 projection SQL に変換。MCP 自体には write capability を与えない。

開発・運用用の補助スクリプト。

## Deprecated: `scripts/run_w*.py`

Wave eval runners (`run_w*.py`) are **gone**. Do **not** add new
`run_wNN_*.py`. Evaluators live in `research.unique_logic`. See
[`docs/architecture/wave_assets_deprecated.md`](../docs/architecture/wave_assets_deprecated.md).

New research:

- legacy catalog: `artifacts/replay/legacy_strategy_catalog/` (immutable replay only; `specs/research_logics/` YAML is empty)
- bounded daily path: exact-four only; legacy catalog IDs fail closed
- local unique CLI (`python -m research.unique_logic`): retired fail-closed stub, not candidate SoT
- CF screen (auxiliary): `research.cf_mass_eval_job.run_cf_mass_eval_job`
- record: `research.occupancy_audit.run_eval_wave` (R2 `research/eval/job={id}/`; no `run_wNN`)

See [`docs/architecture/adr_research_recording.md`](../docs/architecture/adr_research_recording.md)
and [`docs/architecture/wave_assets_deprecated.md`](../docs/architecture/wave_assets_deprecated.md).
The exact-four runtime and replay-isolation tests enforce the operational
boundary; filenames are not used as a security or release boundary.

Official OTC archive recovery (not a COMPLETE issuer):

```bash
uv run python scripts/jsda_otc_official_backfill.py --year 2003 --n 100 --log-dir data/ops/otc_official_backfill --fetch
uv run python scripts/jsda_otc_seal_official.py --log-dir data/ops/otc_official_backfill
```

The second command records `FAILED/REPROOF_REQUIRED` plus
`RECOVERED_RAW_ONLY`. It deliberately does not mutate structured facts, sign a
trusted receipt, refresh COMPLETE, or publish an Ops projection. Reprocess the
persisted raw through the governed acquisition/reconciliation service instead.

## run_ingestion_once.py（Phase 1）

1 パスのデータ取得。local ランタイム主系。

```bash
python scripts/run_ingestion_once.py --source {jquants|jsda|all} --runtime local
```

主なオプション:

- `--source {jquants|jsda|all}` — 対象ソース（既定 `all`）。
- `--mode {incremental|backfill}` — J-Quants カタログ取得モード（既定 `incremental`。`incremental` は直近約5日、`backfill` は全範囲）。
- `--dataset NAME` — J-Quants カタログのデータセット id（繰り返し可・カンマ区切り可。`fins_dividend` 等）。指定時は汎用テーブル `jquants_records` へ蓄積。未指定時は curate 済み3系列 + `fins/summary` raw の従来経路。
- `--code/--from-date/--to-date` — J-Quants の銘柄・日付絞り込み。
- `--workers N` — J-Quants 並列ワーカ数（データセット×日付ウィンドウのジョブ数。レート制限は共有で Premium 約500/min に抑える。既定8）。
- `--chunk-days N` — `from/to` 長期間を N 日グリッドに分割して並列バックフィル（J-Quants、既定30）。
- `--no-jquants-proxy` — CF プロキシ設定があっても直接取得に強制。
- `--jsda-url URL` — JSDA の取得ファイル URL 直指定（インデックス略過）。
- `--jsda-dataset otc-reference --jsda-from-year 2002` — JSDA 公社債店頭売買
  参考統計値を公式 archive segment 単位で resumable backfill。
- `--jsda-dataset tokyo-repo` — authoritative `trrts.xls` を含む東京レポ・レート
  JSDA-era 全履歴。`.xls` は `xlrd` で parse し、silent skip しない。
- `--jsda-force` — exact COMPLETE receipt があっても再取得し、訂正/revision を検出。

J-Quants の鍵は **CF proxy が既定**（環境変数 `JQUANTS_PROXY_URL`/`JQUANTS_PROXY_TOKEN` または `~/.config/quant-platform/jquants_proxy_{url,token}`）。local `JQUANTS_API_KEY` は `UNSAFE_DEV_DIRECT_JQUANTS=1` を明示した開発時だけ利用する。JSDA は鍵不要。

終了コード: `0`=取得/登録あり, `1`=予期せぬエラー, `2`=何も実行せず（CF ランタイム or 全ソース skip）。
詳細は [docs/data_sources.md](../docs/data_sources.md)。

Full governed READY、D1 migration、Ops MCP projection/deploy の順序は
[docs/phase61_production_runbook.md](../docs/phase61_production_runbook.md) を参照。

## run_phase35_validation.py（Phase 3.5 検証マトリクス）

PIT SQLite DB に対して validation matrix（`cf_platform/ingest_premium/matrix.py`）
の各チェックを実行し、結果を表示。実行結果は `data/reports/validation_*.json` に恒久化。

```bash
python3 scripts/run_phase35_validation.py --db data/structured/ingestion.sqlite
python3 scripts/run_phase35_validation.py --db ./ingestion.sqlite --tier weekly --json
python3 scripts/run_phase35_validation.py --db ./ingestion.sqlite --validation-json ./validation_rows.json
```

主なオプション:

- `--tier {daily|weekly}` — 実行階層（既定 `daily`）。
- `--datasets a,b,c` — データセット id でスコープ（既定: Premium core 23）。
- `--require-implemented` / `--allow-not-implemented` — `skip + reason_code=not_implemented`
  を失敗扱いにするか（週次は既定で `--require-implemented`、日次は `--allow`）。
- `--strict-live-gates` / `--no-strict-live-gates` — LIVE_GATES を強制（`QP_LIVE=1` 既定で ON）。
- `--reports-dir DIR` — JSON レポート出力先（既定 `data/reports/`）。
- `--no-persist-report` — JSON 恒久化をスキップ。

終了コード: `0`=失敗なし、`1`=いずれかのチェックが失敗（or 週次で未実装 stub が残存）。

詳細は [docs/phase35_validation_matrix.md](../docs/phase35_validation_matrix.md) を参照。

## run_phase4_accept.py（Phase 4 accept レポート）

Phase 4 の features registry + バックテスト閉路の健全性をチェックして JSON レポートを出力。

```bash
# Offline: フィクスチャ DB を構築して ~20+ 日の feature バックテストを走らせる。
python3 scripts/run_phase4_accept.py

# Live: 実 DB で 50 銘柄サンプル + 50 日以上の BT + B0 strict を通す。
QP_LIVE=1 QP_DB=data/structured/ingestion.sqlite \
    python3 scripts/run_phase4_accept.py
```

主なオプション:

- `--db PATH` — 構造化 DB へのパス（offline 未指定時は一時フィクスチャを生成）。
- `--out PATH` — 出力 JSON の直接指定（省略時は `data/reports/phase4_accept_<ts>.json`）。
- `--reports-dir DIR` — `--out` 省略時の出力ディレクトリ。
- `--live-sample-codes N` — Live 時のサンプル銘柄数（既定 50）。
- `--min-trading-days N` — BT の最小取引日数（offline 既定 20、live 既定 50）。

終了コード: `0`=全セクション ok、`1`=いずれかのセクションが基準未達。
