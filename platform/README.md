# platform

Cloudflare 等の **プラットフォーム設定・運用の置き場所**。

- [secrets.example.md](secrets.example.md) — Secrets の **名前一覧** とローカル proxy 設定（値は書かない）。
- `workers/ingestion-secrets/` — J-Quants 鍵を Cloudflare 側で保持し、ローカルランナー向けに **proxy** する Worker（`/v1/proxy/jquants`）。upstream は canonical Premium contract + 明示的 addon contract の exact path と `GET` のみに限定する。ローカルは環境変数 `INGESTION_PROXY_URL`/`INGESTION_PROXY_TOKEN` または `~/.config/quant-platform/ingestion_proxy_{url,token}` でこの proxy を既定で利用する（`ingestion/common/secrets.py`・`CloudflareJquantsProxyHttpClient`）。
- `workers/ingestion-premium/` — J-Quants Premium core の取得、R2 raw、D1 structured、
  Coverage V2 の required segment / collection receipt export を担う Worker。
- [`workers/research-mass-eval/`](workers/research-mass-eval/README.md) — multi-logic
  period-net screen（`POST /v1/mass-eval` → R2 `research/mass_eval/job={id}/`）。
  `n_survivors` is not a `daily_path_DD` pass. Research only · Mass/READY/GO 未武装 · pure TS。
- [`workers/quant-ops-mcp/`](workers/quant-ops-mcp/README.md) — Cloudflare Access +
  Managed OAuth で保護した Streamable HTTP の **Ops Read-only MCP**。mutable な current ops
  projection だけを公開し、research fact row や write tool は公開しない。durable quota は D1。

Remote Research Read MCP は Cloudflare backend が immutable READY generation を pin/verify
できるまで後続。local stdio MCP は offline/dev adapter であり、browser/mobile の本番経路ではない。
