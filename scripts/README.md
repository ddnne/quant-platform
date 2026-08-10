# scripts

開発・運用用の補助スクリプト。

## run_ingestion_once.py（Phase 1）

1 パスのデータ取得。local ランタイム主系。

```bash
python scripts/run_ingestion_once.py --source {jquants|jsda|all} --runtime local
```

主なオプション:

- `--source {jquants|jsda|all}` — 対象ソース（既定 `all`）。
- `--mode {incremental|backfill}` — J-Quants 取得モード（カタログへ pass-through、既定 `incremental`）。
- `--dataset NAME` — J-Quants データセット名（繰り返し可、カタログへ pass-through）。既定は Phase 1 のコアエンドポイント。
- `--code/--from-date/--to-date` — J-Quants の銘柄・日付絞り込み。
- `--jsda-url URL` — JSDA の取得ファイル URL 直指定（インデックス略過）。

J-Quants の鍵は **CF proxy が既定**（`~/.config/quant-platform/ingestion-proxy.json` で有効化）。proxy 未設定時のみ環境変数 `JQUANTS_API_KEY` で直接取得。JSDA は鍵不要。

終了コード: `0`=取得/登録あり, `1`=予期せぬエラー, `2`=何も実行せず（CF ランタイム or 全ソース skip）。
詳細は [docs/data_sources.md](../docs/data_sources.md)。
