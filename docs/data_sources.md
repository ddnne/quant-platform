# データソース（Phase 1）

外部データ取得は `ingestion/` のみが行う。Phase 1 は **ローカルランタイム** を主系とする。
PIT のため、構造化行は必ず `event_time` / `available_at` / `source` / `ingested_at` を持つ。

> **利用規約（ToS）**: 各ソースは個人研究目的。生データの再配布は行わない。J-Quants / EDINET DB は各サービスの利用規約・ライセンスを遵守すること。JSDA は出典を明記すること。

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
| EDINET DB | local 必須 / CF 任意 | **未実施** | 公式 API（仕様の一部が不確かなため正規化は防御的）。 |
| JSDA | **local 推奨** | **未実施（非推奨）** | HTML/CSV/XLSX。ボット/DC リスクがあるためエッジからの取得は避ける。 |

> Cloudflare 直接 fetch は Phase 1 では **未実施**（`CloudflareHttpClient` は fetch を意図的に実装しない）。将来 Phase で Workers の `fetch()` を経由する取得が必要になった場合のみ実装する。

## 共通仕様

- **PIT 列**: `event_time`（事象時刻）/ `available_at`（利用可能時刻）/ `source` / `ingested_at`。タイムゾーンは **Asia/Tokyo**、文字列表現は ISO-8601（例: `2025-04-01T15:00:00+09:00`）。
- **`available_at` の既定値**: 真の公開時刻が不明な場合、安全（先読みしない）な値として取得時刻 `ingested_at` を使う。ソース個別の公開タイミングが確認でき次第、より正確な値に差し替える。現状の既定は **仮** とする（`conservative_available_at(event_time)` = 翌日 08:00 JST を参考ヘルパとして用意）。
- **`available_at` 必須**: 構造化保存で `available_at` が空の行は拒否される（`storage.sqlite_store.MissingAvailableAt`）。
- **冪等性**: 各テーブルの自然キーを `PRIMARY KEY` とし `ON CONFLICT DO UPDATE` で upsert。同一日の再実行で重複行はできない。衝突時は **`available_at` を既存・新規の早い方（`MIN`）で保持**（元の PIT タイムスタンプを上書きしない）、それ以外の列は新規値で更新し `ingested_at` を最新にする。バッチは単一トランザクションで実行し、失敗時はロールバックする（部分コミットなし）。
- **Raw 保存**: `data/raw/{source}/{yyyy}/{mm}/{dd}/<file>`（gitignore）。
- **構造化保存**: `data/structured/ingestion.sqlite`（gitignore）。将来 R2/D1 へのレイアウトは `storage/schema.py` のコメント参照。
- **秘匿**: API 鍵は環境変数のみ（`JQUANTS_API_KEY`, `EDINETDB_API_KEY`）。コード・ログに出力しない。

## 1. J-Quants（API V2）

- Base: `https://api.jquants.com`、ヘッダ `x-api-key`。
- Phase 1 エンドポイント:
  - `GET /v2/equities/master`（銘柄一覧）
  - `GET /v2/equities/bars/daily`（日足 OHLCV・調整済）
  - `GET /v2/markets/calendar`（取引カレンダー・休業区分）
  - `GET /v2/fins/summary`（**任意**。Plan により 403/404 の可能性 → エラー時は skip）
- ページネーション: **要求パラメータは `pagination_key`**（V2）。応答キーは `pagination_key`（標準）または `pagination_token`（レガシー）のいずれかのため両方を見る。レコード一覧は V2 エンベロープのトップレベル **`data`** から読む（レガシー `info`/`daily_bars`/`calendar`/`summary` はフォールバック）。
- リトライ: 429/5xx および接続・タイムアウト系のトランスポートエラーを指数バックオフで再試行（`ingestion/common/retry.py`）。
- レート制限: 既定 0.5s 間隔（`ingestion/common/rate_limit.py`）。

| テーブル | 自然キー | `event_time` | `available_at` 既定 |
|----------|----------|--------------|---------------------|
| `jquants_listed_info` | (source, code, snapshot_date) | snapshot_date 09:00 JST | 取得時刻（仮） |
| `jquants_daily_bars` | (source, code, date) | 当日引け JST（[2024-11-05 以降は 15:30、それより前は 15:00](https://www.jpx.co.jp/)） | 取得時刻（仮） |
| `jquants_market_calendar` | (source, date) | 当日 09:00 JST | 取得時刻（カレンダーは事前公開だが保守的に取得時刻） |

> **引け時刻の変更**: 東京証券取引所は 2024-11-05 から立会終了を 15:00 → 15:30 に変更（昼休み短縮）。`normalize_daily_bars` は日付で切り替える（`CLOSE_CHANGE_DATE = 2024-11-05`）。

> **V2 項目名の略称**: 日足・マスターは長名（`Open`/`High`/…, `CompanyName`/…）または短縮名（`O`/`H`/`L`/`C`/`Vo`/`Va`, `CoName`/`HolDiv`/…）で届く場合があるため、正規化は候補キーを順に解決する（`_pick`）。

## 2. EDINET DB

- Base: `https://edinetdb.jp/v1`、ヘッダ `X-API-Key`。
- Phase 1 エンドポイント:
  - `GET /v1/companies`（検索/一覧）
  - `GET /v1/companies/{code}`（詳細）
  - `GET /v1/companies/{code}/financials`（財務）
- **注**: 応答 JSON の項目名が公式に完全には確定していないため、正規化は複数候補キーで防御的に解決する。項目対応は **仮**。

| テーブル | 自然キー | 備考 |
|----------|----------|------|
| `edinetdb_companies` | (source, code) | code は `code`/`edinet_code`/`stock_code` のいずれか |
| `edinetdb_financials` | (source, code, period, statement_type) | `statement_type` は空文字可（DEFAULT ''） |

財務の金額項目: `revenue`, `operating_income`, `net_income`, `total_assets`, `equity`（候補キー多数、`edinetdb/normalize.py` 参照）。

## 3. JSDA（公社債取引統計）

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

- `available_at` のソース別実測（J-Quants 翌営業日朝、EDINET 提出日 等）。
- Cloudflare 側 Registrar（R2/D1 読取）と Workers `fetch()` 経由取得の要否判断。
- 履歴バックフィル（直近N日＋サンプルは Phase 1 対応済）。
