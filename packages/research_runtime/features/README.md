# features

**研究用特徴量**の定義・Registry・計算パイプライン。

PIT を尊重し、特徴量計算は `available_at` を起点とする設計を想定。Ingestion（`ingestion/`）が保存した構造化データは **PIT Data API（`pit/`・`as_of` 必須）経由で読み込んで** 計算する（直接 SQLite は不可）。外部 API には直接アクセスしない。

各 `FeatureDefinition` は `intended_role` を必須で宣言する。新規・外部 feature の
`status` は既定で `candidate` となり、StrategySpec は `get_for_strategy` を通じて
`approved` のみを既定で利用する。価格 feature は Core と同じ `RAW` basis を明示し、
vendor adjusted 列を証拠なしに PIT-safe と扱わない。詳細は
[../docs/features.md](../docs/features.md)。
