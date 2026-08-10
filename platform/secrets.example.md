# Secrets（名前のみ）

値は書かない。**正本は Cloudflare Secrets**。ローカル実行は **CF proxy を既定**で利用し、ローカルに鍵を置かない。

## Phase 1 で使用

### Cloudflare 側（Worker secret — 値は Cloudflare のみ）

- `JQUANTS_API_KEY` — J-Quants API V2（ヘッダ `x-api-key`）。**Cloudflare の Worker** `platform/workers/ingestion-secrets` が保持し、proxy 経由で J-Quants へ注入する。ローカル環境変数としては **proxy 未設定時のフォールバック**でのみ使う。
- `INGESTION_PROXY_TOKEN` — proxy 認証トークン（Worker の `/v1/proxy/jquants` が `X-Ingestion-Token` ヘッダで検証）。proxy 利用時に必須。

### ローカル設定ファイル（鍵ではない — proxy の宛先情報のみ）

`~/.config/quant-platform/ingestion-proxy.json`（配置すると proxy が有効）:

```json
{
  "proxy_url": "https://quant-platform-ingestion-secrets.<sub>.workers.dev",
  "proxy_token": "<INGESTION_PROXY_TOKEN と同じ値>"
}
```

- `proxy_url` は Worker origin（または `…/v1/proxy/jquants` のフル URL）。設定ディレクトリは環境変数 `QUANT_PLATFORM_CONFIG_DIR` で上書き可。
- `proxy_token` は `INGESTION_PROXY_TOKEN` と一致させる（これは J-Quants 鍵 **ではない**）。
- このファイルが **ない** 場合のみ、環境変数 `JQUANTS_API_KEY` の直接利用にフォールバックする。解決優先度と詳細は `ingestion/common/secrets.py` 参照。

### 実行時

- `INGESTION_RUNTIME` — `local`（既定）/ `cloudflare`。CLI `--runtime` で上書き。

> JSDA は鍵不要（公開統計ページ）。`--source jsda` は環境変数・proxy なしで実行可能。

## その他

必要に応じて後続 Phase で名前を追加する（例: AI Gateway、執行系）。  
**値や本番キーをこのリポジトリにコミットしないこと。**
