# tests

テスト一式。Phase 1 ではオフライン（鍵不要・ネットワーク不要）で green。

対象: smoke / timeutil(JST) / available_at 検証 / HttpClient（MockTransport・CF stub・fake）/ JSDA パース+正規化+パイプライン / 冪等性 / retry・rate limit。

```bash
python -m pytest tests/ -q
python -m unittest tests.test_smoke -v   # スモークは unittest でも可
```

ライブ API は未使用（モック＋ `tests/fixtures/` の合成データで検証）。
