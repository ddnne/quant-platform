# Architecture（概要）

> **Live residual SoT:** [phase62_residual_status.md](phase62_residual_status.md)  
> (COMPLETE counts / raw_n / Mass·READY **NO-GO** / Phase 7 **OFF** — do not invent live status here.)  
> **Agent nav:** [architecture/llm_nav_map.md](architecture/llm_nav_map.md) · **Layout SoT:** [architecture/repo_layout_migration.md](architecture/repo_layout_migration.md)

Phase 6.1 時点のデータ完全性、PIT、公開 snapshot、外部 read surface の境界を固定する。

## Repository layout

Library code is grouped under `packages/{edge,data_plane,research_runtime,product}` by plane.
**Import names stay top-level** (`import ingestion`, `import pit`, …). Cloudflare Workers remain
at `platform/workers/**` (path frozen). See
[architecture/repo_layout_migration.md](architecture/repo_layout_migration.md) for the mapping
and packaging policy.

## 目的

日本株・開示・債券データを用いた **研究／Paper／FoF** 基盤を構築する。

## 正本と実験・CI

| 項目 | 方針 |
|------|------|
| 正本 | **GitHub リポジトリ 1 本（公開・非公開は運用で変更可）**（本リポジトリ） |
| 実験の枝分かれ | Cloudflare **Artifacts**（後続） |
| CI/CD | **Cloudflare**（後続）。**GitHub Actions には載せない** |

## データ取得と境界

- 外部データ取得は **Ingestion のみ**。エージェントや戦略コードから外部 API へ直接は出ない。
- **Secrets** は Cloudflare Secrets／環境変数。コード・リポジトリに埋め込まない。
- データは **`event_time`**（事象の時刻）と **`available_at`**（利用可能になった時刻）を持つ（**PIT** 前提）。
- 構造化保存では `available_at` は必須（空は拒否）。
- **構造化データの読み出しは PIT Data API（`pit/`）のみ。** 研究・特徴量・戦略コードは
  直接 SQLite を開かず、必ず `as_of` を取る `pit.get_*` 経由で読む。これが **fact の
  唯一の読み出し経路（sole read path for facts）** であり、look-ahead を構造で防ぐ。
  詳細は [pit_api.md](pit_api.md) を参照。

## Coverage V2 と READY

`observed_start` / `observed_end` は診断値であり、完全性の証明ではない。
Coverage V2 はデータセットごとに独立した必須 segment inventory と collection receipt を持つ。
receipt は期待 scope/件数、raw page/row、structured row、pagination exhausted、digest、run、
error を記録し、各 segment を個別に評価する。

- trading-day / calendar / periodic は契約が要求する日・期間・universe の全 segment を必要とする。
- event-driven は対象 window の query 成功、pagination 完走、raw 保持、structured reconcile を要求する。
  この証明が揃えば 0 event でも COMPLETE だが、古い 1 行だけでは COMPLETE にならない。
- dataset は全 required segment が COMPLETE のときだけ COMPLETE になる。途中の欠落は PARTIAL。
- READY publication は governed dataset 全件について Coverage V2 proof を再検証し、proof digest を
  immutable manifest と content address に含める。

Mutable staging DB は研究入力ではない。研究は content-addressed READY SQLite generation を
`mode=ro&immutable=1` で PIT API から読む。この Phase 6 の境界は変更しない。

## Read service と MCP

read domain は明示的に 2 plane に分離する。

| plane | 状態 | 公開経路 |
|------|------|----------|
| `ops_current` | mutable な ingestion / validation / coverage / sync 状態 | Cloudflare remote Ops Read MCP |
| `research_ready` | 検証済み immutable READY generation | local/dev adapter。Remote は READY backend を pin できるまで未公開 |

ブラウザ ChatGPT / mobile の人向け標準経路は OAuth/Cloudflare Access で保護した
Streamable HTTP MCP である。`mcp_servers.quant_data` の stdio は offline test と local development
専用であり、本番の接続方式ではない。Remote Ops は domain-level の 12 read tool のみを公開し、
SQL、D1/R2 handle、secret、shell、任意 URL fetch、ingest/delete/publish、feature approve、broker
を公開しない。詳細は [quant_data_access.md](quant_data_access.md) と
[`quant-ops-mcp` README](../platform/workers/quant-ops-mcp/README.md) を参照。

## Governed データ源

- **J-Quants**（API V2）
- **JSDA** 公社債店頭売買参考統計値（公式 archive の 2002-08-02 以降）、東京レポ・レート
  （JSDA 公表主体の 2012-10-29 以降）、社債の取引情報

> 開示系データは独立した EDINET DB を介さず、**J-Quants の EDINET 系 API**（`/v2/edinet/major-shareholders`, `/v2/edinet/cross-shareholdings`, `/v2/edinet/large-volume-shareholders`, および `/v2/fins/...`）で統合する（カタログ実体: `ingestion/jquants/catalog.py`）。

JSDA の 3 系列は別 dataset id と別 natural key を持ち、ひとつの `jsda` blob へ統合しない。
公表ラベル日、quote/effective time、`available_at`、`ingested_at` を別々に保持する。公表時刻が
公式に分からない場合、`available_at` は取得時刻より前へ推測しない。訂正は同じ natural key の
revision として保存し、訂正公表または取得より前の `as_of` に見せない。

Ingestion は **ローカルランタイム主系**。ランタイムの切替（local / cloudflare）、Fetcher vs
Registrar 分離（Pattern B）、`available_at` 検証、冪等 upsert、raw/structured 保存の詳細は
[data_sources.md](data_sources.md) 参照。

## コアエンジンとエージェント

- **コアエンジン（Phase 3 最小実装）**はブラックボックス。エージェント・研究コードは
  `core.run_backtest` を呼び出して結果を消費するだけで、内部を改変しない。
- **fact は `pit.get_*` 経由のみ**（`core/` は SQLite/HTTP を直接開かない。`tests/test_core_data_boundary.py`
  が静的に強制）。戦略には意思決定 `as_of` 時点で既に PIT 読出し済みの狭い `BarContext` のみ渡す。
  look-ahead は PIT の `available_at <= as_of` と執行定義（`next_close` では D のシグナルは
  D に約定しない）の 2 重構造で防ぐ。詳細は [core_engine.md](core_engine.md)。
- 役割エージェント（後続）の例：
  - マクロ / ファンダ / クオンツ / コンポーザー
  - ストラテジスト / PM / トレーダー / Risk

## 選抜と規制

- **選抜優先**（戦略・実験の採用・淘汰を中心に回す）。
- 規制は最小限にとどめ、**PIT** と **境界**（Ingestion のみ外部通信、Secrets 非埋め込み等）は **構造で強制**する。
