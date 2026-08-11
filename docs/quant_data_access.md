# Quant Data Access MCP

人が使う正規経路は、Cloudflare 上の認証付き **Quant Ops Read remote
MCP** です。ブラウザ／mobile の ChatGPT などから、収集状況・Coverage
V2・品質・READY publication metadata を確認します。ローカル Python
stdio MCP は offline test と開発用 adapter であり、本番の人向け経路では
ありません。

```text
Browser / mobile ChatGPT and remote MCP clients
              │ OAuth + Streamable HTTP
              ▼
 Cloudflare Quant Ops Read MCP ──► mutable current Ops control plane
              │                       (status, receipts, gaps, no facts)
              └──► immutable READY publication metadata only

Local development clients
              │ stdio JSON-RPC
              ▼
 mcp_servers.quant_data ──► shared read-domain service
              ├──► mutable local Ops mirror
              └──► PIT-gated immutable READY snapshot research reads
```

**どちらの MCP も DB や D1 を公開しません。** Remote は Ops read-only
domain tools だけを持ち、local adapter も既存の Snapshot / PIT / Coverage /
Feature 境界を越えません。

---

## 1. 何ができるか / 何ができないか

### Remote Ops Read でできること

| 用途 | tools |
|------|--------|
| 現在の運用状態 | `ops_status`, `ingestion_last_run`, `sync_status` |
| Coverage V2 | `dataset_coverage`, `coverage_gaps`, `coverage_segments`, `backfill_status` |
| 品質ゲート | `validation_summary`, `b0_status` |
| READY metadata | `latest_ready_snapshot`, `snapshot_quality` |
| raw 証跡 | `raw_retention_status`（R2 自由探索なし） |

チャットから例えば次が聞けます。

- 「JQ と JSDA の incomplete segment は？」
- 「JSDA OTC 2002 年 archive の missing day は？」
- 「最新 ingestion と B0 の状態は？」
- 「最新 READY snapshot の quality metadata は？」

Remote Ops server は fact row を返しません。`query_dataset` / Feature /
provenance は、Cloudflare が published READY generation を content hash で
pin・verify できるまで local/dev research interface のみに残します。

### できないこと（意図的に載せない）

- 任意 SQL / 任意 DB path
- ingestion / backfill / snapshot publish
- Feature approve / delete / rebuild
- Secrets / proxy token / J-Quants 直叩き
- R2 オブジェクト一覧の無制限閲覧
- 本番ブローカー / 注文

運用系 write は将来の **別プロセス DataOps MCP** に分離します。通常の
ChatGPT には本 Remote Ops Read MCP だけを繋ぎます。

---

## 2. Remote-first の接続先

### 本番 endpoint（SoT）

Cloudflare deploy 後の接続先は次の 1 endpoint です。

```text
https://quant-platform-ops-read-mcp.<account-subdomain>.workers.dev/mcp
```

| 項目 | 値 |
|------|-----|
| transport | MCP Streamable HTTP (`2025-06-18`) |
| auth | Cloudflare Access + Managed OAuth（同等構成可） |
| scope | `quant.read.ops` |
| data plane | current Ops control DB + READY metadata only |
| 書き込み | なし（read-only） |

具体的な Access/OAuth、D1 migration、unauth/auth smoke、deploy 手順は
[`platform/workers/quant-ops-mcp/README.md`](../platform/workers/quant-ops-mcp/README.md)
を参照してください。

### ローカル stdio smoke（dev adapter）

```bash
cd /Users/taku/GitHub/quant-platform

.venv/bin/python -m mcp_servers.quant_data \
  --snapshot-dir data/research_snapshots \
  --ops-db data/structured/ingestion.sqlite \
  --list-tools
.venv/bin/python scripts/ops_status.py --json
```

この command を browser/mobile ChatGPT の本番接続先として公開しません。
`ops_status.py` はチャットなしで同じ local control-plane を見る入口です。

### データが見える条件

```text
D1 current Ops + Coverage V2 receipts ──► Remote Ops Read MCP

D1 sync → Coverage V2 / quality gate → READY publish
  → data/research_snapshots/<content-id>.sqlite (+ manifest)
  → local/dev Research READY reads
```

Remote の current Ops status と Research READY は別状態です。Cron が緑でも
READY 未発行なら research data は読めず、古い READY が存在しても current
backfill が complete とは限りません。

---

## 3. クライアント別設定

Browser/mobile client は remote `/mcp` URL と OAuth を使います。以下の
stdio 設定は local/offline development を必要とするクライアントだけの
appendix です。

### 3.1 ChatGPT browser / mobile（正規経路）

ChatGPT の remote MCP / connector 設定に production `/mcp` URL を追加し、
OAuth flow で `quant.read.ops` を許可します。Custom remote MCP の利用可否は
workspace/plan に依存します。利用できない場合も MCP Inspector と server
tests で protocol/auth acceptance は検証できます。

### 3.2 Grok Build / Grok TUI（local dev）

**User scope:** `~/.grok/config.toml`
**Project scope:** `/Users/taku/GitHub/quant-platform/.grok/config.toml`

```toml
[mcp_servers.quant_data]
command = "/Users/taku/GitHub/quant-platform/.venv/bin/python"
args = [
  "-m",
  "mcp_servers.quant_data",
  "--snapshot-dir",
  "/Users/taku/GitHub/quant-platform/data/research_snapshots",
]
cwd = "/Users/taku/GitHub/quant-platform"
enabled = true
startup_timeout_sec = 30
```

CLI:

```bash
grok mcp add quant_data -- \
  /Users/taku/GitHub/quant-platform/.venv/bin/python \
  -m mcp_servers.quant_data \
  --snapshot-dir /Users/taku/GitHub/quant-platform/data/research_snapshots

# cwd が CLI で入らない場合は config.toml を手編集
grok mcp list
grok mcp doctor quant_data
```

設定後は **セッション再起動**。

### 3.3 Codex CLI / Codex app（local dev）

Codex は `~/.codex/config.toml` の `[mcp_servers.*]` で stdio MCP を起動します。

```toml
[mcp_servers.quant_data]
command = "/Users/taku/GitHub/quant-platform/.venv/bin/python"
args = [
  "-m",
  "mcp_servers.quant_data",
  "--snapshot-dir",
  "/Users/taku/GitHub/quant-platform/data/research_snapshots",
]
cwd = "/Users/taku/GitHub/quant-platform"
enabled = true
startup_timeout_sec = 30
```

この設定は local repository / READY snapshot を使う開発用です。Browser の
ChatGPT は上の remote endpoint を使います。

### 3.4 Claude Desktop（local dev）

`~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）:

```json
{
  "mcpServers": {
    "quant-data": {
      "command": "/Users/taku/GitHub/quant-platform/.venv/bin/python",
      "args": [
        "-m",
        "mcp_servers.quant_data",
        "--snapshot-dir",
        "/Users/taku/GitHub/quant-platform/data/research_snapshots"
      ],
      "cwd": "/Users/taku/GitHub/quant-platform"
    }
  }
}
```

Claude を完全終了して再起動。

### 3.5 Cursor（local dev）

`~/.cursor/mcp.json` または project の `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "quant-data": {
      "command": "/Users/taku/GitHub/quant-platform/.venv/bin/python",
      "args": [
        "-m",
        "mcp_servers.quant_data",
        "--snapshot-dir",
        "/Users/taku/GitHub/quant-platform/data/research_snapshots"
      ],
      "cwd": "/Users/taku/GitHub/quant-platform"
    }
  }
}
```

### 3.6 設定の対応表

| クライアント | 設定場所 | transport | 備考 |
|--------------|----------|----------|------|
| Browser/mobile ChatGPT | remote connector 設定 | Streamable HTTP + OAuth | **正規経路** |
| Grok | `~/.grok/config.toml` または project `.grok/config.toml` | stdio | local dev |
| Codex app/CLI | `~/.codex/config.toml` | stdio | local dev |
| Claude Desktop | `claude_desktop_config.json` | stdio | local dev |
| Cursor | `mcp.json` | stdio | local dev |

Remote と local は同じ read-domain semantics を共有しますが capability が
違います。Remote は Ops-only、local adapter は Ops + READY/PIT research
です。この差を remote convenience のために縮めません。

---

## 4. チャットでの聞き方（クライアント共通）

### Remote の収集・品質（as_of 不要）

- 「`ops_status` で全体を」
- 「`coverage_gaps` で薄い dataset 一覧」
- 「`coverage_segments` で missing middle を確認」
- 「`latest_ready_snapshot` と `snapshot_quality`」

### Local/dev research データ（as_of 必須）

- 「`query_dataset` dataset=`equities_bars_daily` as_of=`2022-12-30T15:00:00+09:00` code=7203」
- 「`get_series` で同じ as_of の close」

`as_of` を省略した「最新の株価」要求には、サーバ側が **曖昧な latest data endpoint を持たない**ため、クライアントは先に `latest_ready_snapshot` を取り、明示 as_of で query する流れになります。

### Feature

- `feature_id` + **exact `version`** + `as_of` + `params`
- approved 以外・version 不一致は reject

---

## 5. セキュリティモデル（マルチチャット前提）

| 層 | 役割 |
|----|------|
| チャット UI | 人が質問する。Secret を渡さない |
| Access / OAuth | OAuth scope を専用 Access app/AUD に対応付け、JWT issuer/audience/signature を再検証。human と service token を分離 |
| Remote MCP | Ops domain tools のみ。D1 handle/SQL/write なし |
| quota | D1 の subject/client/UTC-day 単位 durable quota |
| `data_access` (local) | allowlist / SQL keyset / READY only / `available_at <= as_of` |
| READY snapshot | immutable な研究正本。ingestion とは分離 |

`quant.read.ops` と `quant.read.research` は別 scope です。本 Remote server は
前者だけを受け付け、write scope は持ちません。Ingestion token / proxy /
publish credential はどのチャットにも載せません。

---

## 6. トラブルシュート

| 症状 | 確認 |
|------|------|
| Remote tools が出ない | `/mcp` URL、OAuth protected-resource metadata、Access AUD/scope |
| `401` | Access JWT 未送信／署名・issuer・audience 不一致 |
| `403` | `quant.read.ops` 不足、または Origin allowlist 不一致 |
| coverage が UNKNOWN | Coverage V2 migration/backfill/aggregation 未完了 |
| READY が NONE | current Ops と別。production READY workflow を実行 |
| local tools が出ない | 絶対パス、`cwd`、venv の python 存在 |
| import error | `cwd` が repo root か、`.venv` の python を使っているか |
| as_of エラー | PIT query は as_of 必須 |
| 権限エラー | 本 MCP に write tool は無い（仕様） |

```bash
# local dev adapter
.venv/bin/python -m mcp_servers.quant_data --list-tools

# Grok
grok mcp doctor quant_data
```

---

## 7. 実装パス

| パス | 内容 |
|------|------|
| `platform/workers/quant-ops-mcp/` | human-facing remote Ops Read MCP (**GitHub OAuth**, news-mcp 同型) |
| Production URL | `https://quant-platform-ops-read-mcp.taku-haga.workers.dev/mcp` |
| `mcp_servers/quant_data/` | local/dev stdio facade |
| `data_access/` | shared Ops/Research read-domain + PIT Gatekeeper |
| `scripts/ops_status.py` | チャット無しの同じ確認口 |
| `docs/phase6_snapshot_publication.md` | READY 発行 |
| `docs/phase6_hardening_acceptance.md` | 境界と P0 監査 |

Operational writes（ingestion trigger 等）は別 DataOps MCP とし、本サーバと process / credential を共有しない。
