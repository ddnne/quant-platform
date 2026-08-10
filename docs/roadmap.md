# Roadmap

| Phase | 内容 |
|-------|------|
| 0 | リポジトリと土台（本依頼） |
| 1 | Ingestion（J-Quants / JSDA） ✅ 完了 |
| 2 | PIT Data API（`pit/`・`as_of` 必須・look-ahead 防止） ✅ 完了 |
| 3 | コアエンジン最小（`core/`・PIT 経由のみ・ブラックボックス） ✅ 完了 |
| 3.5 | CF J-Quants Premium 閉路（`platform/workers/ingestion-premium/`） ✅ 完了 |
| 4 | 特徴量 Registry（`features/`・PIT 経由のみ・versioned・`as_of` 必須） ✅ 完了 |
| 5 | Paper 縦通し |
| 6 | 役割エージェント |
| 7 | 選抜・Knowledge・AI Gateway |
| 8 | FoF・Risk |
| 9 | 執行の厚み・追加データ |

> **次は Phase 5（Paper 縦通し）。** Phase 4 では特徴量 Registry を実装した
> （`features/`・`compute` は PIT 経由のみ・`return_1d`/`momentum_n`/`volatility_n` 同梱・
> 再現性メタデータ付き）。詳細は [features.md](features.md)。
> Phase 3.5 では Cloudflare 上の Premium core 取得閉路（`platform/workers/ingestion-premium/`・
> R2 raw + D1 structured・per-dataset 検証・hourly cron・local sync）を構築した。
> 詳細は [phase35_cf_ingest.md](phase35_cf_ingest.md)。
