# platform

Cloudflare 等の **プラットフォーム設定・運用の置き場所**。

- [secrets.example.md](secrets.example.md) — Secrets の **名前一覧** とローカル proxy 設定（値は書かない）。
- `workers/ingestion-secrets/` — J-Quants 鍵を Cloudflare 側で保持し、ローカルランナー向けに **proxy** する Worker（`/v1/proxy/jquants`）。ローカルは `~/.config/quant-platform/ingestion-proxy.json` でこの proxy を既定で利用する（`ingestion/common/secrets.py`・`ProxyHttpClient`）。

Workers / Workflows / wrangler 設定・CI（Cloudflare 側）の本実装は **後続 Phase**。この Phase では文書と置き場所、および上記 secrets proxy Worker のみ。
