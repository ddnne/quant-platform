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

**Mandatory local CI:** [`verify_ci.sh`](verify_ci.sh) (active Worker lanes in parallel; no `VERIFY_*` skips). It pins `uv 0.11.26`, runs `uv sync --frozen --extra dev`, the complete Python suite with two file-scoped pytest workers, the Evaluation IR freeze, verifies the machine-readable Cloudflare binding manifest, then runs each Worker through `npm ci`, tests, typecheck, base/production/staging Wrangler dry-runs, and generated-types checks. The legacy catalog is not compiled into CI or Worker source. Wrangler, TypeScript, and Workers types are exact-versioned. Never `--legacy-peer-deps`; never skip missing dependencies; never live `wrangler deploy`.

[`activate_jsda_v3_cutover.py`](activate_jsda_v3_cutover.py) observes
Cloudflare JSDA state twice. `--check` is read-only; `--activate --yes`
mutates only after zero/current observations. Caller JSON is not authority.
Required non-secret env names: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`.
Queue pause/resume uses Wrangler `queues pause-delivery` /
`resume-delivery`. Cron stop/restore uses
`PUT /accounts/{account_id}/workers/scripts/{script}/schedules` because
Wrangler 4.125.0 has no schedule mutation command.

Ops Projection cloud publication is `ingestion-premium` scheduled work.
Deploy Premium before MCP. MCP keeps its current dedicated D1 binding until a
SEALED generation exists; `predeploy_ops_projection_gate.py` fails MCP deploy
closed until that generation verifies. Do not commit placeholder verify keys.

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
Its scoped `--pending-receipt-authority` mode also invokes the exact live
three-Worker verifier described below; the local PENDING gate alone is not an
accepted post-deploy result.

[`receipt_authority_pending_live_acceptance.py`](receipt_authority_pending_live_acceptance.py)
is the GET-only post-deploy acceptance for the PENDING Receipt chain. It binds
the exact reviewed source SHA to one 100%-traffic version of acquisition,
authority and caller Workers. For each Worker it compares the live downloaded
main-module bytes to a credential-free deterministic dry-run build from the
clean reviewed commit; the SHA must equal locally tracked and remotely observed
official `origin/main`, so a self-reported version message/tag or caller-chosen
clean commit is insufficient. A chain-wide before/after observation detects an
earlier Worker changing while a later Worker is inspected. Authenticated
Wrangler subprocesses use a fresh isolated home containing only the expected
Cloudflare account/token, not ambient OAuth or unrelated secrets.
It also compares the complete live binding/resource inventory with the frozen
manifest, rejects extra capability surfaces, and proves the expected
workers.dev, preview, route, custom-domain, Cron, Logpush and tail-consumer
surfaces, including closed script/runtime/observability settings. Secret values
are neither requested nor emitted. Its result remains
research-ineligible and cannot authorize an ACTIVE authority, Receipt
issuance, Coverage, READY, or Pilot. Production stays C7 `HOLD` while the
ingestion-secrets workers.dev surface lacks independently verified Cloudflare
Access. PENDING staging acceptance also does not make Premium registration
reachable; a separately reviewed private operator Service Binding/entrypoint
is still required, and adding a public Premium route is prohibited.

[`receipt_authority_staging_active_gate.py`](receipt_authority_staging_active_gate.py)
is the staging-only, audit-only activation observer gate. It accepts only the
reviewed source SHA, account ID, and Cloudflare API token; the Access manifest,
staging key registry, and output directory are fixed. The gate independently
brackets four live deployments, GETs the observer by its immutable Workers
Beta ID, binds its enabled non-preview `subdomain.url` to the exact HTTPS
endpoint, checks Access's exact Worker destination, application AUD and
`non_identity` Service Auth policy/token, and verifies the Premium D1
schema/attestation row. The observer Service Binding targets only
`PremiumReceiptAuditEvidenceService`, which has no registration RPC. The gate
then makes an unauthenticated rejection probe and
one random-challenge HTTPS request to the Access-protected observer. Access
client ID/secret values come only from
`RECEIPT_OBSERVER_ACCESS_CLIENT_ID` and
`RECEIPT_OBSERVER_ACCESS_CLIENT_SECRET`, and are never arguments or evidence.
The checked-in Access manifest is deliberately `PENDING`; error `9999`, any
covering/broader Access app, redirect, HTML, deployment/D1 drift, or old
version/key pair remains an operational hold. A success writes only canonical,
content-addressed, create-only local `AUDIT_ONLY` evidence and cannot authorize
Receipt issuance, release, READY, or Pilot.

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
- `d1_ingestion_migration_validation.py` — validate the canonical migration
  history, schema, triggers and populated v2-to-v3 preservation on an isolated
  ephemeral database. Recorded partial or malformed states fail.
- `apply_ingestion_d1_migrations.py --check` — read-only remote D1 migration,
  schema and Time Travel observation. Its mutation helper is private to the
  cutover operator and runs under the same-D1 CAS lease.
- `activate_jsda_v3_cutover.py` — the only staging/production mutation entry.
  It stops writers, drains and pauses the Queue, records the Time Travel
  bookmark and undo command, applies the canonical chain under a short D1
  lease, verifies, and restores the prior Cron/Queue state. `--resume` and
  `--rollback` require the original run ID. The small local create-only control
  intent is crash-recovery cache only; remote D1 plus live Cloudflare state are
  authoritative. Whole-file D1 exports are not part of this path.
- `build_release_evidence.py` — **publication PENDING / fail-closed**. The
  former normalized JSON format is retained only as a private schema-regression
  helper; caller-supplied names, UUIDs and digests are not evidence. The private
  JSDA `/health/ready` collector now runs through the observer Service Binding,
  but publication remains closed until the release-observation key is active
  and the exact response bytes are signed. The exact contract is
  `specs/cloudflare/release_observation_authority.json`.

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

The successful JSON output is a path-free rollback-backup candidate object.
Re-run `verify` against the encrypted artifact, but do not treat that JSON as
release evidence or publish a release manifest while the signed observation
authority remains PENDING.
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

Official OTC archive recovery (not a COMPLETE issuer). Host-local fetch and
seal require `QP_ALLOW_LOCAL_MARKET_DATA=1`; the backfill planner launches the
guarded fetch child and does not duplicate the opt-in.

```bash
QP_ALLOW_LOCAL_MARKET_DATA=1 uv run python scripts/jsda_otc_official_backfill.py --year 2003 --n 100 --log-dir data/ops/otc_official_backfill --fetch
QP_ALLOW_LOCAL_MARKET_DATA=1 uv run python scripts/jsda_otc_seal_official.py --log-dir data/ops/otc_official_backfill
```

The second command records `FAILED/REPROOF_REQUIRED` plus
`RECOVERED_RAW_ONLY`. It deliberately does not mutate structured facts, sign a
trusted receipt, refresh COMPLETE, or publish an Ops projection. Reprocess the
persisted raw through the governed acquisition/reconciliation service instead.

## run_ingestion_once.py

1 パスのデータ取得。既定ランタイムは `cloudflare`（ホストローカルへは取得しない）。
通常経路は Cloudflare（R2 正本、D1 メタデータ、Container SQLite は ephemeral）。
ホストローカル取得は復旧用で、実行ファイル起動時に `QP_ALLOW_LOCAL_MARKET_DATA=1`
と `--runtime local` が必要。

```bash
python scripts/run_ingestion_once.py --source {jquants|jsda|all}
QP_ALLOW_LOCAL_MARKET_DATA=1 python scripts/run_ingestion_once.py --source jsda --runtime local
```

主なオプション:

- `--source {jquants|jsda|all}` — 対象ソース（既定 `all`）。
- `--runtime {cloudflare|local}` — 既定 `cloudflare`（環境変数 `INGESTION_RUNTIME`）。`local` は opt-in 復旧。
- `--mode {incremental|backfill}` — J-Quants カタログ取得モード（既定 `incremental`。`incremental` は直近約5日、`backfill` は全範囲）。
- `--dataset NAME` — J-Quants カタログのデータセット id（繰り返し可・カンマ区切り可。`fins_dividend` 等）。指定時は汎用テーブル `jquants_records` へ蓄積。未指定時は curate 済み3系列 + `fins/summary` raw の従来経路。
- `--personal-draft` — 個人用DRAFT研究向けの明示的なlocal-onlyモード。`--source jquants --runtime local --dataset ...` が必須。既定DBは専用の `data/structured/personal-ingestion.sqlite`。immutable raw manifest とPIT正規化行だけを保存し、署名receipt・Coverage COMPLETE・READY・完全性を発行/主張しない。`run_historical_backfill.py` からも同じflagを指定できる（既定 runtime は `cf`；local 側は子の `run_ingestion_once.py` が opt-in を見る）。
- `hydrate_personal_history.py` — 4系列だけを専用SQLiteへ低速・逐次・再開可能に保存する個人DRAFT用hydrator。既定はdry-run・30 requests/minで、dry-runは opt-in 不要。実行には`--execute`と `QP_ALLOW_LOCAL_MARKET_DATA=1` が必須。速度は`--requests-per-minute`で上書きでき、saved proxyは従来どおり最大60 requests/minに制限される。raw本文は保存せずpage SHA-256と件数だけをcheckpointし、masterの`Date 08:00 JST`は訂正publication時刻を復元しない近似である。receipt・Coverage・READY・controlled/live適格性・完全性は一切主張しない。
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

終了コード: `0`=取得/登録あり, `1`=予期せぬエラー, `2`=何も実行せず（opt-in 拒否、CF ランタイム、または全ソース skip）。
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
