# Roadmap

| Phase | 内容 |
|-------|------|
| 0 | リポジトリと土台（本依頼） |
| 1 | Ingestion（J-Quants / JSDA） ✅ 完了 |
| 2 | PIT Data API（`pit/`・`as_of` 必須・look-ahead 防止） ✅ 完了 |
| 3 | コアエンジン最小（`core/`・PIT 経由のみ・ブラックボックス） ✅ 完了 |
| 4 | 特徴量 Registry |
| 5 | Paper 縦通し |
| 6 | 役割エージェント |
| 7 | 選抜・Knowledge・AI Gateway |
| 8 | FoF・Risk |
| 9 | 執行の厚み・追加データ |

> **次は Phase 4（特徴量 Registry）。** Phase 3 ではコアエンジン最小を実装した
> （`core/`・fact は `pit` 経由のみ・`next_close`/`same_day_close` 執行・標準/ストレス費用・
> 再現性メタデータ）。詳細は [core_engine.md](core_engine.md)。
