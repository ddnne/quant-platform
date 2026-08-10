# ingestion

外部データ源からの **取得・正規化・格納** を担当する層。  
システム内で外部 API に直接触れるのは原則ここだけ。

Phase 1 で実装済み:

- `common/` — HttpClient 抽象（`LocalHttpClient`=httpx 必須 / `CloudflareHttpClient`=stub / `ProxyHttpClient`=J-Quants CF proxy）、retry、rate limit、JST 時刻、`available_at` 検証、raw path、secrets（J-Quants 認証解決）
- `jquants/` — API V2 クライアント・正規化（銘柄/日足/カレンダー/財務サマリ任意）
- `jsda/` — 公社債取引統計（URL 解決・パース・正規化・取得）。既定 local
- `pipeline.py` — **Fetcher vs Registrar**（Pattern B）。`run_jquants/run_jsda`

> 開示系は独立ソースではなく J-Quants EDINET 系 API で後続 Phase に統合する方針（Phase 1 では上記 2 ソース）。

ランタイム・PIT・冪等性の詳細は [docs/data_sources.md](../docs/data_sources.md)。
