# scripts

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

J-Quants の鍵は **CF proxy が既定**（環境変数 `INGESTION_PROXY_URL`/`INGESTION_PROXY_TOKEN` または `~/.config/quant-platform/ingestion_proxy_{url,token}` で有効化）。proxy 未設定時のみ環境変数 `JQUANTS_API_KEY` で直接取得。JSDA は鍵不要。

終了コード: `0`=取得/登録あり, `1`=予期せぬエラー, `2`=何も実行せず（CF ランタイム or 全ソース skip）。
詳細は [docs/data_sources.md](../docs/data_sources.md)。
