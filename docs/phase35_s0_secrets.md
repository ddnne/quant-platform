# Phase 3.5 S0 — CF Secrets バインド確認

> **Live residual / GO SoT:** [`phase62_residual_status.md`](phase62_residual_status.md)
> (Mass NO-GO · Phase 7 OFF). Historical bind check (2026-08-11), not live GO.

**確認日:** 2026-08-11  
**結果:** **CF に設定済み**

## リポジトリ上の参照名

| 名前 | 用途 |
|------|------|
| `JQUANTS_API_KEY` | J-Quants API V2 鍵（Worker のみが保持） |
| `INGESTION_PROXY_TOKEN` | local → CF プロキシ認証用共有トークン |

- Worker: `platform/workers/ingestion-secrets/`（name: `quant-platform-ingestion-secrets`）
- `wrangler.toml` コメントおよび `platform/secrets.example.md` と一致

## 確認方法（値は表示されない）

### CLI（実施済み）

```bash
cd platform/workers/ingestion-secrets
npx wrangler secret list
# → name のみ: JQUANTS_API_KEY, INGESTION_PROXY_TOKEN
```

```bash
# デプロイ済み Worker の /health（鍵の有無の boolean のみ）
curl -sS "$WORKER_BASE/health"
# → {"ok":true,"has_jquants_key":true}
```

### Cloudflare Dashboard（画面上）

1. [Cloudflare Dashboard](https://dash.cloudflare.com/) にログイン
2. 左メニュー **Workers & Pages**（または **Compute → Workers**）
3. ワーカー **`quant-platform-ingestion-secrets`** を開く
4. タブ **Settings** → **Variables and Secrets**（または **Secrets**）
5. 一覧に **`JQUANTS_API_KEY`** と **`INGESTION_PROXY_TOKEN`** の **名前** が出ていればバインド済み  
   - **値は画面にも CLI にも出ない**（再表示不可。未設定時だけ `wrangler secret put` で上書き登録）

Account 配下の別場所（例: **Secrets Store** 製品）ではなく、**この Worker の Settings にバインドされた secret** が正。

## 方針

- **再発行しない**（既存キーを使用）
- 収集ジョブは同じ Secret 名を参照
- 値をリポジトリ・ログ・Issue に書かない
