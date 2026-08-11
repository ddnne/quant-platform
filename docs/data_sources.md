# データソース（Phase 1）

外部データ取得は `ingestion/` のみが行う。Phase 1 は **ローカルランタイム** を主系とする。
PIT のため、構造化行は必ず `event_time` / `available_at` / `source` / `ingested_at` を持つ。

> **利用規約（ToS）**: 各ソースは個人研究目的。生データの再配布は行わない。J-Quants は各サービスの利用規約・ライセンスを遵守すること。JSDA は出典を明記すること。

## ランタイム設計（local vs Cloudflare）

| 保守点 | local | cloudflare |
|--------|-------|------------|
| HTTP 発行 | `LocalHttpClient`（httpx）— **必須** | `CloudflareHttpClient` — **stub（fetch しない）** |
| 役割 | 取得→raw 保存→正規化→構造化保存（Fetcher + Registrar） | ストレージ読み取りのみ（Registrar 相当） |
| 切替 | `INGESTION_RUNTIME=local` / `--runtime local`（既定） | `--runtime cloudflare`（Phase 1 では何も取得しない → exit 2） |

**Pattern B**: 取得は local で行い raw/structured を保存。Cloudflare 側はストレージを読むだけ。
そのため `ingestion/pipeline.py` は **Fetcher**（HTTP・raw 保存・正規化）と **Registrar**（`available_at` 検証→構造化 upsert）に分離している。

## 初期ランタイム仮説と計測結果

| Source | Phase 1 推奨 | 計測結果（Cloudflare 直接 fetch） | 備考 |
|--------|--------------|----------------------------------|------|
| J-Quants | local 必須 / CF 任意 | **未実施** | 公式 REST API。Plan の範囲で取得。 |
| JSDA | **local 推奨** | **未実施（非推奨）** | HTML/CSV/XLSX。ボット/DC リスクがあるためエッジからの取得は避ける。 |

> Cloudflare 直接 fetch は Phase 1 では **未実施**（`CloudflareHttpClient` は fetch を意図的に実装しない）。将来 Phase で Workers の `fetch()` を経由する取得が必要になった場合のみ実装する。

## 共通仕様

- **PIT 列**: `event_time`（事象時刻）/ `available_at`（利用可能時刻）/ `source` / `ingested_at`。タイムゾーンは **Asia/Tokyo**、文字列表現は ISO-8601（例: `2025-04-01T15:00:00+09:00`）。
- **`available_at` の既定値**: 真の公開時刻が不明な場合、安全（先読みしない）な値として取得時刻 `ingested_at` を使う。ソース個別の公開タイミングが確認でき次第、より正確な値に差し替える。現状の既定は **仮** とする（`conservative_available_at(event_time)` = 翌日 08:00 JST を参考ヘルパとして用意）。
- **`available_at` 必須**: 構造化保存で `available_at` が空の行は拒否される（`storage.sqlite_store.MissingAvailableAt`）。
- **冪等性**: 各テーブルの自然キーを `PRIMARY KEY` とし `ON CONFLICT DO UPDATE` で upsert。同一日の再実行で重複行はできない。衝突時は **`available_at` を既存・新規の早い方（`MIN`）で保持**（元の PIT タイムスタンプを上書きしない）、それ以外の列は新規値で更新し `ingested_at` を最新にする。バッチは単一トランザクションで実行し、失敗時はロールバックする（部分コミットなし）。
- **Raw 保存**: `data/raw/{source}/{yyyy}/{mm}/{dd}/<file>`（gitignore）。
- **構造化保存**: `data/structured/ingestion.sqlite`（gitignore）。将来 R2/D1 へのレイアウトは `storage/schema.py` のコメント参照。
- **秘匿**: API 鍵はコード・ログに出力しない。J-Quants の正本は **Cloudflare Secret**（Worker 保持）。ローカルは **CF 秘匿プロキシを既定**（`JQUANTS_PROXY_URL`/`JQUANTS_PROXY_TOKEN` または `~/.config/quant-platform/jquants_proxy_{url,token}`）。local `JQUANTS_API_KEY` は無視し、直接取得は `UNSAFE_DEV_DIRECT_JQUANTS=1` を明示した開発時だけ。

## 1. J-Quants（API V2）

- Base: `https://api.jquants.com`、ヘッダ `x-api-key`。
- 公式仕様（最終確認: 2026-08-10）: <https://jpx-jquants.com/en/spec/data-spec> — Premium（コア）＋ 分钟足・Tick・TDnet のアドオンを含む全データセットをカバー。パスの一覧は `ingestion/jquants/catalog.py`（`DATASETS`）が唯一の真実源。
- カバレッジ保証: `catalog.assert_catalog_coverage()` と `tests/test_jquants_catalog.py` が、カタログ内の全データセットに `/v2/` パスと `JQuantsClient.fetch_dataset` 経由のルートを要求する（stub-only は不可）。
- ページネーション: **要求パラメータは `pagination_key`**（V2）。応答キーは `pagination_key`（標準）または `pagination_token`（レガシー）のいずれかのため両方を見る。レコード一覧は V2 エンベロープのトップレベル **`data`** から読む（レガシー `info`/`daily_bars`/`calendar`/`summary` はフォールバック）。
- リトライ: 429/5xx および接続・タイムアウト系のトランスポートエラーを指数バックオフで再試行（`ingestion/common/retry.py`）。
- レート制限: Premium は 500 req/min。安全側として **約 8 rps（0.125s 間隔 ≒ 480/min）** を既定（`catalog.PREMIUM_MIN_INTERVAL`）。`ingestion/common/rate_limit.py`。

### エンドポイントカタログ（Premium + アドオン）

汎用クライアント `JQuantsClient.fetch_dataset(dataset_id, **params)` で全件取得可能。`bulk` 列が `bulk` のものは公式バルクパス（`ingestion/jquants/bulk.py`）が存在し得る（Phase 1 はページネーション REST 既定）。

| group | dataset id | path | bulk | 主パラメータ |
|-------|-----------|------|------|--------------|
| core | `equities_master` | `/v2/equities/master` | api | code, date |
| core | `equities_bars_daily` | `/v2/equities/bars/daily` | bulk | code, date, from, to |
| core | `equities_bars_daily_am` | `/v2/equities/bars/daily/am` | api | code, date |
| core | `fins_summary` | `/v2/fins/summary` | api | code, date（Plan により 403 → skip） |
| core | `fins_details` | `/v2/fins/details` | api | code, date |
| core | `fins_dividend` | `/v2/fins/dividend` | api | code, from, to |
| core | `fins_earnings_date` | `/v2/fins/earnings-date` | api | code |
| core | `equities_earnings_calendar` | `/v2/equities/earnings-calendar` | api | from, to, date |
| core | `markets_calendar` | `/v2/markets/calendar` | api | from, to, holidaydivision |
| core | `equities_investor_types` | `/v2/equities/investor-types` | api | code, from, to |
| core | `indices_bars_daily_topix` | `/v2/indices/bars/daily/topix` | api | from, to |
| core | `indices_bars_daily` | `/v2/indices/bars/daily` | api | code, from, to |
| core | `derivatives_bars_daily_options_225` | `/v2/derivatives/bars/daily/options/225` | api | from, to |
| core | `derivatives_bars_daily_futures` | `/v2/derivatives/bars/daily/futures` | api | code, from, to |
| core | `derivatives_bars_daily_options` | `/v2/derivatives/bars/daily/options` | api | code, from, to |
| core | `markets_margin_interest` | `/v2/markets/margin-interest` | api | code, date, from, to |
| core | `markets_margin_alert` | `/v2/markets/margin-alert` | api | code, date, from, to |
| core | `markets_short_ratio` | `/v2/markets/short-ratio` | api | code, date, from, to, section |
| core | `markets_short_sale_report` | `/v2/markets/short-sale-report` | api | code, date, from, to |
| core | `markets_breakdown` | `/v2/markets/breakdown` | api | code, date, from, to |
| edinet | `edinet_major_shareholders` | `/v2/edinet/major-shareholders` | api | code, date |
| edinet | `edinet_cross_shareholdings` | `/v2/edinet/cross-shareholdings` | api | code, date |
| edinet | `edinet_large_volume_shareholders` | `/v2/edinet/large-volume-shareholders` | api | code, date |
| addon | `equities_bars_minute` | `/v2/equities/bars/minute` | bulk | code, from, to |
| addon | `equities_trades` | `/v2/equities/trades` | bulk | code, date, from, to（Tick; パスは要確認） |
| addon | `td_list` | `/v2/td/list` | api | date |
| addon | `td_files` | `/v2/td/files` | api | date |
| addon | `td_bulk` | `/v2/td/bulk` | bulk | date（公式パスは要確認） |

> EDINET 系はバルク API がないためページネーション REST で取得。`equities_trades`/`td_bulk` はアドオンで公式バルク/CSV 面の一部が未確認; クライアント経由で呼び出し自体は可能。

### 保管

- 従来のキュレーション実行では 3 系列（`equities_master`/`equities_bars_daily`/`markets_calendar`）を専用テーブル（下記）に正規化。
- `--dataset` を使うカタログ実行では、3 系列を含む全データセットを汎用テーブル `jquants_records(dataset, natural_key, event_time, available_at, ingested_at, payload, raw_payload)` へ格納。`natural_key` はカタログの識別フィールド（`Code`/`Date` 等）の JSON、該当が無ければ行ハッシュ。PIT 列を全行に付与。PIT のキュレーション getter は専用テーブルと対応する汎用パーティションを二重読みする。
- 各 fact テーブルの訂正前の値は対応する `*_revisions` テーブルに保持し、PIT 読み出しは `available_at <= as_of` の最新版を自然キーごとに選ぶ。

| テーブル | 自然キー | `event_time` | `available_at` 既定 |
|----------|----------|--------------|---------------------|
| `jquants_listed_info` | (source, code, snapshot_date) | snapshot_date 09:00 JST | 取得時刻（仮） |
| `jquants_daily_bars` | (source, code, date) | 当日引け JST（[2024-11-05 以降は 15:30、それより前は 15:00](https://www.jpx.co.jp/)） | 取得時刻（仮） |
| `jquants_market_calendar` | (source, date) | 当日 09:00 JST | 取得時刻（カレンダーは事前公開だが保守的に取得時刻） |
| `jquants_records` | (source, dataset, natural_key) | データセット別（引け時刻 / 開示日 09:00 / 無ければ取得時刻） | 取得時刻（仮） |

> **引け時刻の変更**: 東京証券取引所は 2024-11-05 から立会終了を 15:00 → 15:30 に変更（昼休み短縮）。`normalize_daily_bars` は日付で切り替える（`CLOSE_CHANGE_DATE = 2024-11-05`）。

> **V2 項目名の略称**: 日足・マスターは長名（`Open`/`High`/…, `CompanyName`/…）または短縮名（`O`/`H`/`L`/`C`/`Vo`/`Va`, `CoName`/`HolDiv`/…）で届く場合があるため、正規化は候補キーを順に解決する（`_pick`）。

### Cloudflare 秘匿プロキシ（推奨: ローカル実行時）

J-Quants API 鍵は Cloudflare Worker `quant-platform-ingestion-secrets` のみが保持し、**ローカルには置かない**。ローカルランナは Worker のプロキシエンドポイント `POST {proxy}/v1/proxy/jquants`（ボディ `{path, query}`、ヘッダ `X-Ingestion-Token`）を呼び出し、Worker が上流へ `x-api-key` を注入する。

- プロキシ設定の解決（`ingestion/common/secrets.py`）: 環境変数 `JQUANTS_PROXY_URL`/`JQUANTS_PROXY_TOKEN`、なければ `~/.config/quant-platform/jquants_proxy_{url,token}`。片方しか無ければ `None`（未認証プロキシは使わない）。旧 `INGESTION_PROXY_*` は J-Quants proxy 入力としてのみ互換読込し、run/export 権限には再利用しない。
- HTTP クライアント: `CloudflareJquantsProxyHttpClient`（`ingestion/common/http.py`）が J-Quants の `GET https://api.jquants.com/v2/...` をプロキシ `POST` に変換。呼び出し元が渡した `x-api-key` ヘッダは**転送しない**（鍵漏洩の二重防御）。
- ファクトリ: `make_jquants_http(runtime, via_cf_proxy=None)` が local + プロキシ設定ありなら自動でプロキリクライアントを選択（`--no-jquants-proxy` で強制直接）。汎用 `make_http_client(runtime)` は常に直接（JSDA と共有のため鍵代理は J-Quants のみ）。
- `JQUANTS_API_KEY` は Cloudflare Worker ランタイムが注入する。local 直接モードは `UNSAFE_DEV_DIRECT_JQUANTS=1` が無い限り fail closed。

実行例:

```bash
# カタログ駆動で特定データセット（プロキシ設定があれば自動でプロキシ経由）
python3 scripts/run_ingestion_once.py --source jquants \
    --dataset fins_dividend,markets_breakdown --mode incremental

# 従来既定（curated 3 系列 + fins/summary raw）
python3 scripts/run_ingestion_once.py --source jquants
```

## 2. JSDA（公社債取引統計）

- 参照ページ: `https://www.jsda.or.jp/shiryoshitsu/toukei/saiken_torihiki/`
- 形式: HTML ページ上の CSV / XLSX。URL は期ごとに変わるため `ingestion/jsda/urls.py` で一元管理（インデックスをスクレイプしてデータ拡張子のリンクを抽出）。
- 既定ランタイム: **local**（エッジからのスクレイピングはボット/DC リスクのため非推奨）。
- パース: `ingestion/jsda/parse.py`。エンコーディング自動検出（utf-8-sig → cp932 → shift_jis → latin-1）。タイトル行をスキップし、ヘッダ行を日付マーカーで特定。列は別名マッチ（exact 優先 → substring）で解決。
- ディスパッチ: 取得ファイルの拡張子・内容で切替（`pipeline._choose_jsda_parser`）。`.xlsx`（または ZIP マジック `PK`）→ `parse_xlsx`、`.csv` → `parse_csv`、**レガシー `.xls` は非対応（明示的にエラー＝skip ではなく error）**。
- XLSX: `openpyxl` が任意（`pip install -e ".[xlsx]"`）。CSV が既定経路。
- リトライ: 429/5xx・トランスポートエラーを指数バックオフで再試行。

### JSDA カラム対応（引値相当）

`jsda_bond_trades` テーブル。自然キー: **(source, trade_date, isin, issuer_name)**。

| スキーマ列 | JSDA ヘッダー（例・別名） | 内容 |
|------------|---------------------------|------|
| `trade_date` | 年月日 / 取引日 / 営業日 | 取引日（`event_time` は当日 15:00 JST） |
| `issuer_name` | 銘柄名 / 発行体 | 発行体/銘柄名 |
| `isin` | ISINコード | ISIN（無ければ空） |
| `coupon_rate` | 利率(%) / 表面利率 | クーポン（%） |
| `maturity_date` | 償還年月日 / 償還日 | 償還日 |
| `high_yield` | 最高利回り(%) / 高値 | 最高利回り（%） |
| `low_yield` | 最低利回り(%) / 安値 | 最低利回り（%） |
| `close_yield` | 終値利回り(%) / 終値 | 終値利回り（%） |
| `trade_amount_mil_jpy` | 取引金額(百万円) / 出来高 | 取引金額（百万円） |

> 「引値相当」= 社債の高値/安値/終値利回りおよび取引金額。JSDA は利回りベースの公表が主。

### JSDA レポレート（東京レポ・レート / TRR）

- 参照ページ: `https://www.jsda.or.jp/shiryoshitsu/toukei/trr/`（`repo_index_url()`）。2012-10-29 に日本銀行から日本証券業協会へ公表主体が移管された「東京レポ・レート」シリーズ。
- 形式: HTML ページ上のデータファイル。公表実体は **レガシー `.xls`**（`trr.xls` = 当日分、`trrts.xls` = 時系列一覧）および年度別のレファレンス先（参考施設）PDF/XLSX。URL 解決は `ingestion/jsda/urls.py` に隔離（`resolve_repo_links` / `pick_repo_file`）。`pick_repo_file` は時系列一覧（`trr*ts`）を優先し、レファレンス先一覧（`bessi*` / `reference`）を除外する。
- 既定ランタイム: **local**（ボンド統計と同じ理由でエッジからのスクレイピングは非推奨）。
- パース: `ingestion/jsda/parse.py`（`parse_repo_csv` / `parse_repo_xlsx`）。エンコーディング自動検出・タイトル行スキップ・数値の `%`/`,` 削除はボンドと共通ヘルパを再利用。**wide**（日付列＋テナーごとの数値列）と **long**（日付列＋期間列＋レート列）の両レイアウトを `(as_of_date, tenor, rate)` に正規化する。テナー名はソースのヘッダ/セル文字列をそのまま保持（語彙を捏造しない）。
- ディスパッチ: `pipeline._choose_jsda_repo_parser`（`.xlsx`/ZIP→`parse_repo_xlsx`、`.csv`→`parse_repo_csv`、**レガシー `.xls` は非対応**）。ボンドとは異なり、実ソースが `.xls` であることが既知のため、`run_jsda` は `.xls` を **clean skip**（error ではなく）とし、ボンド取引の成功を阻害しない。実運用で取り込むには `trr.xls`/`trrts.xls` を `.xlsx`/`.csv` に変換のうえ `--jsda-repo-url` で指定（ボンドの `.xls` 方針と同一）。
- リトライ: ボンド経路と同じ 429/5xx・トランスポートエラーの指数バックオフ。
- `run_jsda` は既定で **ボンド取引とレポレートの両方** を 1 パスで実行（各々独立の `RunReport`）。`bond=False` / `repo=False`、または CLI `--jsda-only bond|repo` で制限可能。

#### `jsda_repo_rates` カラム対応

自然キー: **(source, as_of_date, tenor, rate_type)**。

| スキーマ列 | ソース（例・別名） | 内容 |
|------------|---------------------|------|
| `as_of_date` | 年月日 / 取引日 / 営業日 / 日付 | レート基準日（`event_time` は当日 15:00 JST・引け） |
| `tenor` | 期間（long）/ ヘッダー（wide: 隔日物・1週間物・1ヶ月物・…・12ヶ月物） | テナー（ソース文字列をそのまま保持） |
| `rate_type` | （固定既定） | シリーズ名。既定 `東京レポ・レート`（`normalize_repo_rates(rate_type=)` で上書き、例: GCレポレート） |
| `rate` | レート(%) / 金利 / rate | 公表レート（%、`%`/`,` 除去） |

> **`available_at` は仮**: TRR の真の公開タイミング（概ね翌営業日朝）は未計測のため、既定で取得時刻 `ingested_at` を使う。実測でき次第、より正確な値に差し替える（`conservative_available_at` 参照）。
>
> **実ソース形式について（仮）**: 公表ファイルはレガシー `.xls`。本経路は `.csv`/`.xlsx` を対象とするため、`.xls` は clean skip となる。直接取り込みが必要な場合は xlrd 等による `.xls` 読取サポートの追加が別途課題（ボンド経路と同様の方針）。

## 取得スクリプト

```bash
# ローカルで 1 パス（既定 local）
python3 scripts/run_ingestion_once.py --source all --runtime local

# JSDA のみ（鍵不要）
python3 scripts/run_ingestion_once.py --source jsda

# J-Quants を 1 銘柄・小ウィンドウで
JQUANTS_API_KEY=*** python3 scripts/run_ingestion_once.py --source jquants \
    --code 8697 --from-date 2025-04-01 --to-date 2025-04-05
```

終了コード: `0`=取得/登録あり, `1`=**少なくとも1ソースがエラー**（取得/正規化/登録の失敗）, `2`=何も実行せず（CF ランタイム または全ソース clean skip）。

> **0行 = 成功としない**: 取得したが正規化で 0 行になった（スキーマ不一致の疑い）場合は `ok` 扱いにしない。`ok` は登録行数>0 または明示的な空（例: `fins/summary` は raw 保存専用）の場合のみ。エラーと clean skip は `RunReport.error` / `RunReport.skipped` で区別し、CLI はエラー優先で終了コードを決める（`ingestion/pipeline.decide_exit`）。

## 次フェーズでの改善点

- `available_at` のソース別実測（J-Quants 翌営業日朝、J-Quants 開示系（`/v2/edinet/`, `/v2/fins/`）の提出日 等）。
- Cloudflare 側 Registrar（R2/D1 読取）と Workers `fetch()` 経由取得の要否判断。
- 履歴バックフィル（直近N日＋サンプルは Phase 1 対応済）。
