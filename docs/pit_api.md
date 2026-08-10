# PIT Data API (`pit/`)

Phase 2. The **sole read path for structured facts**. Every read takes an
explicit `as_of` instant and returns only data that was **available** at or
before that instant — never future data. No writes, no external HTTP.

> **研究・特徴量・戦略コードは構造化データを直接 SQLite で読まないこと。**
> 必ずこの PIT API を経由すること（point-in-time 一貫性の保証と、将来データの
> 漏れ込み（look-ahead）防止のため）。Direct SQLite reads for research are
> **forbidden** — go through `pit`.

## 前提

Ingestion（Phase 1）が `data/structured/ingestion.sqlite` に構造化行を格納済みである
こと。全行は PIT 列 `event_time` / `available_at` / `source` / `ingested_at` を持ち、
`available_at` は **必須**（空は書き込み時に拒否される）。`available_at` は
`+09:00`（Asia/Tokyo）の ISO-8601 文字列として正規化されて格納される。

## コア契約（contracts）

1. **`as_of` は全関数で必須。** 省略 → `pit.AsOfRequired`。"latest" の既定値は **ない**。
2. **`as_of` の解釈**: ISO-8601 文字列・aware/naive `datetime`（naive は JST 扱い）・
   `date`（JST 0時）を受け付け、`+09:00` の秒精度 ISO に正規化する。不正値 →
   `pit.InvalidAsOf`。
3. **PIT ゲート（必ず適用）**: `WHERE available_at IS NOT NULL AND available_at <= ?`。
   `available_at` と `as_of` は同じ正規形（固定幅 `YYYY-MM-DDTHH:MM:SS+09:00`）なので、
   ISO 文字列の辞書式比較が正しく働く。`available_at == as_of` の行は **含まれる**
   （その瞬間に公表された情報は使える）。`available_at > as_of`（未来）の行は **絶対に
   返らない**。
   同じ自然キーに訂正履歴がある場合は、条件を満たす版のうち `available_at` が最大の
   1 行を返す。したがって訂正前と訂正後の間を `as_of` に指定すると訂正前の値が見える。
4. **範囲フィルタは加算的**: `from_*` / `to_*` / `code` 等は `available_at` ゲートの
   **上** に重ねるだけで、ゲートを **置き換えない**。
5. **読み取り専用**: SQLite を `mode=ro`（read-only URI）で開く。書込みは構造的に
   失敗する（`sqlite3.OperationalError`）。DB が存在しない → `pit.DatabaseNotFound`。
6. **`db_path` は変更可能**: 既定は `data/structured/ingestion.sqlite`（cwd=リポジトリ
   ルートを想定）。
7. **応答**: `pit.PitResult`。`.rows`（dict のリスト。JSON 系カラム `raw_payload` /
   `payload` はオブジェクトにデコード）と `.metadata`（`as_of`・`table`・`source`・
   `dataset`・`count`・`pit_api_version`）を持つ。反復可能・`len()` 可能。

## 公開 API

| 関数 | テーブル | 主なフィルタ |
|------|----------|--------------|
| `get_equity_master(as_of, code=None, *, db_path=None)` | `jquants_listed_info` + `jquants_records(equities_master)` | `code` |
| `get_equity_bars_daily(as_of, code=None, from_event=None, to_event=None, *, db_path=None)` | `jquants_daily_bars` + `jquants_records(equities_bars_daily)` | `code`, `from_event`/`to_event`（**date**） |
| `get_market_calendar(as_of, from_date=None, to_date=None, *, db_path=None)` | `jquants_market_calendar` + `jquants_records(markets_calendar)` | `from_date`/`to_date`（**date**） |
| `get_jquants_records(as_of, dataset, code=None, from_event=None, to_event=None, *, db_path=None)` | `jquants_records` | `dataset`（必須）, `code`, `from_event`/`to_event`（**event_time**） |
| `get_jsda_bond_trades(as_of, isin=None, from_event=None, to_event=None, *, db_path=None)` | `jsda_bond_trades` | `isin`, `from_event`/`to_event`（**trade_date**） |

> `jquants_records` は `dataset` でパーティションされる汎用テーブル（カタログ実行では
> 3 つのキュレーション済系列を含む全カタログデータセット）。公開キュレーション getter
> は専用テーブルと対応パーティションを二重読みし、同じ自然キーは最新既知版にまとめる。
> `get_jquants_records` では `dataset` は必須。有効な id は
> `ingestion.jquants.catalog.DATASETS` を参照。未知の `dataset` は空結果になる（エラー
> ではない）。

`pit_api_version` = `"0.2.0"`。

## 例

```python
from pit import get_equity_bars_daily, AsOfRequired

# 2025-04-01 17:00 JST 時点で知っていた 8697 の 3 月日足
res = get_equity_bars_daily(
    as_of="2025-04-01T17:00:00+09:00",
    code="8697",
    from_event="2025-03-01",
    to_event="2025-03-31",
    # db_path="data/structured/ingestion.sqlite",  # 既定値
)
for row in res:
    print(row["date"], row["close"])

print(res.metadata)
# {'as_of': '2025-04-01T17:00:00+09:00', 'table': 'jquants_daily_bars',
#  'source': 'jquants', 'count': 21, 'pit_api_version': '0.2.0'}
```

`as_of` を省略すると例外:

```python
get_equity_bars_daily(code="8697")   # -> raises pit.AsOfRequired
```

`datetime` も渡せる（naive は JST、aware は JST に変換）:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

get_equity_bars_daily(as_of=datetime(2025, 4, 1, 8, 0, tzinfo=ZoneInfo("UTC")))
# 08:00 UTC == 17:00 JST として扱われる
```

汎用レコード（`jquants_records`）の読み出し:

```python
from pit import get_jquants_records

res = get_jquants_records(
    as_of="2025-04-01T17:00:00+09:00",
    dataset="fins_dividend",
    code="8697",
)
div = res.rows[0]["payload"]["Dividend"] if res else None
```

## エラー一覧

| エラー | 起きる条件 |
|--------|------------|
| `pit.AsOfRequired` | `as_of` の省略・`None`・空文字 |
| `pit.InvalidAsOf` | `as_of` が日時にパースできない・未対応型 |
| `pit.InvalidDataset` | `get_jquants_records` で `dataset` が空/省略 |
| `pit.DatabaseNotFound` | 指定パスに構造化 DB が存在しない |
| （すべて `pit.PitError` の派生。`except PitError` で一括捕捉可能） | |

## なぜ直接 SQLite がダメか

1. **Look-ahead**: `available_at <= as_of` を忘れると、バックテストに「その時点では
   存在しなかったデータ」が混入し、結果が信用できなくなる。PIT API はこのゲートを
   構造で強制する（省略不可）。
2. **一貫性**: `available_at` の正規化（オフセット → `+09:00`）や NULL 拒否を API 側で
   一元化。各呼び出しで自前の SQL を書くと、これらが徐々に破綻する。
3. **読み取り専用**: `mode=ro` で開くので、研究コードから誤ってデータを書き換える事故
   が起きない。
4. **証跡**: `.metadata` に `as_of` と `pit_api_version` が残るので、再現・監査が可能。

## テスト

- `tests/test_pit_as_of.py` — `as_of` 必須・パース・空結果
- `tests/test_pit_lookahead.py` — `available_at > as_of` は不可視、`==` は可視、オフセットの一貫性
- `tests/test_pit_coverage.py` — 各テーブルのハッピーパス読み出し・読み取り専用強制
- `tests/test_pit_revisions_catalog.py` — 訂正履歴の as-of 再現・カタログ/専用テーブル二重読み
