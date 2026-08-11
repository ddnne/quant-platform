# ingestion

外部データ源からの **取得・正規化・格納** を担当する層。  
システム内で外部 API に直接触れるのは原則ここだけ。

実装済み:

- `common/` — HttpClient 抽象（`LocalHttpClient`=httpx 必須 / `CloudflareHttpClient`=stub / `CloudflareJquantsProxyHttpClient`=J-Quants CF 秘匿プロキシ）、retry、rate limit、JST 時刻、`available_at` 検証、raw path、secrets（プロキシ設定解決）
- `jquants/` — API V2 クライアント・正規化（銘柄/日足/カレンダー/財務サマリ任意）
- `jsda/` — governed JSDA ingestion。公社債店頭売買参考統計値の公式 2002+ archive、
  東京レポ・レートの authoritative `.xls` 時系列、社債取引情報を別 dataset として扱う。
  raw-before-parse、checksum/source URL/fetch time、Coverage V2 receipt、revision provenance、
  resumable segment を持つ。既定 local。
- `pipeline.py` — **Fetcher vs Registrar**（Pattern B）。`run_jquants/run_jsda`

J-Quants Premium Worker は fetch plan から required monthly segment を取得前に記録し、
response pagination 完走と R2 raw manifest に対応する collection receipt を出力する。
一部期間の ad-hoc request は canonical monthly inventory を満たさない。

> 開示系は独立ソースではなく J-Quants EDINET 系 API で統合する。

ランタイム・PIT・冪等性の詳細は [docs/data_sources.md](../docs/data_sources.md)。
