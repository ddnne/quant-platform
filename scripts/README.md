# scripts

開発・運用用の補助スクリプト。

## run_ingestion_once.py（Phase 1）

1 パスのデータ取得。local ランタイム主系。

```bash
python scripts/run_ingestion_once.py --source {jquants|edinetdb|jsda|all} --runtime local
```

終了コード: `0`=取得/登録あり, `1`=予期せぬエラー, `2`=何も実行せず（CF ランタイム or 全ソース skip）。
詳細は [docs/data_sources.md](../docs/data_sources.md)。
