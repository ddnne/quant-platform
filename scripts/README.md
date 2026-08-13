# scripts

**Bootstrap (B1-e):** `scripts/_bootstrap.py` → `ensure_repo_root()`. Ops/coverage/receipt
CLIs (`issue_receipts_parallel`, `publish_ops_projection`, `export_ops_projection`,
`refresh_coverage_ledger`, `ops_status`, `ops_reeval_*`, `write_collection_receipts`,
`issue_signed_receipts_for_segments`, `restore_local_complete_from_receipt`,
`evaluate_collection_sla`) use it. Other scripts may still use local `sys.path`
inserts until migrated. Do not launch Mass / READY / Phase7 / `cf_premium_backfill`
from residual prose alone.

Phase 6 hardening utilities:

- `ops_status.py --json` — offline READY snapshot, coverage, B0 and validation status.
- `rebuild_paper_index.py --root data/paper --json` — rebuild the disposable index from immutable Paper JSON.
- `python -m mcp_servers.quant_data --list-tools` — Quant Data Access MCP smoke.
- `export_ops_projection.py` — verified local Coverage/READY/B0 metadataを bounded
  D1 projection SQL に変換。MCP 自体には write capability を与えない。

開発・運用用の補助スクリプト。

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
