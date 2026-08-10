# features

**研究用特徴量**の定義・Registry・計算パイプラインの置き場所（後続 Phase）。

PIT を尊重し、特徴量計算は `available_at` を起点とする設計を想定。Ingestion（`ingestion/`）が保存した構造化データは **PIT Data API（`pit/`・`as_of` 必須）経由で読み込んで** 計算する（直接 SQLite は不可）。外部 API には直接アクセスしない。

実装は後続 Phase（ロードマップ上は特徴量 Registry 周り）。現時点では空。
