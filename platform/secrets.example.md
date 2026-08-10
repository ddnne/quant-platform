# Secrets（名前のみ）

値は書かない。Cloudflare Secrets または実行環境の環境変数として設定する。

## Phase 1 で使用

- `JQUANTS_API_KEY` — J-Quants API V2（ヘッダ `x-api-key`）。未設定時は skip。
- `EDINETDB_API_KEY` — EDINET DB（ヘッダ `X-API-Key`）。未設定時は skip。
- `INGESTION_RUNTIME` — `local`（既定）/ `cloudflare`。CLI `--runtime` で上書き。

> JSDA は鍵不要（公開統計ページ）。`--source jsda` は環境変数なしで実行可能。

## その他

必要に応じて後続 Phase で名前を追加する（例: AI Gateway、執行系）。  
**値や本番キーをこのリポジトリにコミットしないこと。**

