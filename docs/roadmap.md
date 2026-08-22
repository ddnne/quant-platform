# Roadmap

| Phase | 内容 |
|-------|------|
| 0 | リポジトリと土台（本依頼） |
| 1 | Ingestion（J-Quants / JSDA） ✅ 完了 |
| 2 | PIT Data API（`pit/`・`as_of` 必須・look-ahead 防止） ✅ 完了 |
| 3 | コアエンジン最小（`core/`・PIT 経由のみ・ブラックボックス） ✅ 完了 |
| 3.5 | CF J-Quants Premium 閉路（`platform/workers/ingestion-premium/`） ✅ 完了 |
| 4 | 特徴量 Registry（`features/`・PIT 経由のみ・versioned・`as_of` 必須） ✅ 完了 |
| 5 | Paper 縦通し（`strategies/paper/`・result 永続化・sample strategies・CLI） ✅ 完了 |
| 5.5 | Phase 6 foundation（`ctx.feature` 境界・snapshot ID・experiment identity・index） ✅ 完了 |
| 6 | F0 full-code hardening・役割エージェント・StrategySpec ✅ 完了 |
| 6.1 | Coverage V2 + remote Ops Read MCP + governed JSDA ✅ 完了 |
| 6.2 | Inventory tools・projection publish・minimal Phase7 stubs ✅ code-complete / 🚫 live NO-GO（残差は [phase62_residual_status.md](phase62_residual_status.md)）|
| 7 | 選抜・Knowledge・AI Gateway 🚫 NO-GO until READY + Coverage V2 COMPLETE |
| 8 | FoF・Risk |
| 9 | 執行の厚み・追加データ |

> **Phase 7 は NO-GO**（READY + Coverage V2 COMPLETE まで。研究の次は propose→occupancy
> 閉ループであり Mass / GO ではない）。Phase 6 では Premium core 23 の
> canonical data contract、revision/change-feed、validated snapshot manifest、SQLite WAL paper
> index、stale valuation marks、RAW price basis、feature governance を hardening した。
> さらに 8 役割の structured interface、declarative StrategySpec whitelist interpreter、
> offline Paper orchestrator、独立 risk audit を実装した。任意 Python、agent への secrets/raw
> data/SQLite/HTTP の引き渡しは禁止。詳細は [agents.md](agents.md)。
>
> その前提として Phase 5.5 では、戦略が
> `BarContext` / `ctx.feature` だけを通じて特徴量を取得する境界、軽量な control-plane
> `data_snapshot_id`、lifecycle と分離した決定論的 `experiment_id`、run 索引を固定した。
> Phase 6 では宣言的 StrategySpec / DSL と trusted interpreter を使い、LLM が生成した
> 任意の Python を実行しない。Phase 5 では Paper 縦通しを実装した
> （`PaperRunConfig` → feature-driven strategy → `core.run_backtest` →
> `PaperRunResult` → `data/paper/<strategy_id>/<experiment_id>/<run_id>.json`）。戦略から DB／PIT／HTTP／
> secrets への直接アクセスは禁止し、再現性 metadata を result に固定する。詳細は
> [paper.md](paper.md)。Phase 4 では特徴量 Registry を実装した
> （`features/`・`compute` は PIT 経由のみ・`return_1d`/`momentum_n`/`volatility_n` 同梱・
> 再現性メタデータ付き）。詳細は [features.md](features.md)。
> Phase 3.5 では Cloudflare 上の Premium core 取得閉路（`platform/workers/ingestion-premium/`・
> R2 raw + D1 structured・per-dataset 検証・hourly cron・local sync）を構築した。
> 詳細は [phase35_cf_ingest.md](phase35_cf_ingest.md)。
>
> **運用完了の定義**: Phase 3.5 の運用完了には (1) cron `failed=0` と (2) live B0 strict
> pass の両方が必要。フレームワーク完了 ≠ データ品質完了。詳細は
> [phase35_validation_matrix.md](phase35_validation_matrix.md) の "Live strict gates" 節を参照。
