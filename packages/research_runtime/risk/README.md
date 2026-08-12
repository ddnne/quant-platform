# risk

**リスク制約・モニタリング・監査（audit）** 向けロジックの置き場所。

研究特徴量（`features/`）とは明確に分離する。こちらはリスク制限の計算、PIT 監査ログ、ポジション/感度の監視など、実行系・監査系で使う安全・統制レイヤを想定。

Phase 6 では最小の `RiskAgent` が永続化済み `PaperRunResult` を読み、content-derived id の
immutable JSON audit を `data/risk/audits/` に保存する。Paper result の保存先とは物理的に
分離される。FoF や live risk は Phase 8 以降。
