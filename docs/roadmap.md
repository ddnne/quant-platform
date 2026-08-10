# Roadmap

| Phase | 内容 |
|-------|------|
| 0 | リポジトリと土台（本依頼） |
| 1 | Ingestion（J-Quants / JSDA） ✅ 完了 |
| 2 | PIT Data API（`pit/`・`as_of` 必須・look-ahead 防止） ✅ 完了 |
| 3 | コアエンジン最小 |
| 4 | 特徴量 Registry |
| 5 | Paper 縦通し |
| 6 | 役割エージェント |
| 7 | 選抜・Knowledge・AI Gateway |
| 8 | FoF・Risk |
| 9 | 執行の厚み・追加データ |

> **次は Phase 3（コアエンジン最小）。** Phase 2 では構造化データの読み出し経路として
> PIT Data API を実装した（`as_of` 必須・読み取り専用・直接 SQLite 禁止）。詳細は
> [pit_api.md](pit_api.md)。
