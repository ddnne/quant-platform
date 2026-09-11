# 現行アーキテクチャ

通常経路は Cloudflare 上の取得・不変保存・一時計算です。入口の向きは [../README.md](../README.md)、残作業の順は [roadmap.md](roadmap.md)、役割は [../AGENTS.md](../AGENTS.md) です。個人 / Controlled / Mass の分離と歴史的朝値の意味は [architecture/adr_phase632_architecture_simplification.md](architecture/adr_phase632_architecture_simplification.md) です。配置ナビは [architecture/repo_layout_migration.md](architecture/repo_layout_migration.md) と [architecture/llm_nav_map.md](architecture/llm_nav_map.md) を使い、古い文書をライブの正本にしません。

## クラウド面

市場データの通常取得は ingestion Worker が行い、raw と products を R2 へ不変に置き、構造化分を D1 へ書きます。研究の実データ実行は既存の research-mass-eval Worker が Container を使い、R2 由来の一時 SQLite で計算します。利用者マシンに実価格・財務履歴は残しません。ローカルはコードと fixture です。`qp-research` は開発者・復旧互換であり、通常経路ではありません。稼働面の正本は [../specs/cloudflare/active_worker_bindings.json](../specs/cloudflare/active_worker_bindings.json)、D1 移行は [../specs/cloudflare/d1_migration_manifest.json](../specs/cloudflare/d1_migration_manifest.json) です。目録は写しません。個人 DRAFT の API 限界は [../platform/workers/research-mass-eval/README.md](../platform/workers/research-mass-eval/README.md)、秘密の名前だけ [../platform/secrets.example.md](../platform/secrets.example.md) です。

| 層 | 責務 | 統合先 |
| --- | --- | --- |
| data_plane | SQL・貯蔵・時計・PIT。不変スライスを供給する | R2 の raw / products と D1 |
| research_runtime | 与えられたスライスで計算するだけ | research-mass-eval の Container（一時 SQLite） |
| product | 経路の組み立てと認可境界 | 既存 Worker 契約。Worker や authority を増やさない |

計算は閉じた DSL に限り、生成 Python も `eval` / `exec` も使いません。Risk は独立です。スコープコンパイラ、財務の compact state、complete-master 所有者は既にあります。未完なのは共有の bar / 財務スコープと、認証済み候補・READY・runtime・Trader の接続です。データベース境界が閉じた、とは言いません。ソース受理はロールアウトを自動にしません。

## 時刻と PIT

すべての面は明示の `as_of` / `available_at` と正確な版を保存します。PIT は `available_at <= as_of` を含みます。固定 allowlist の日次交差は所属の不変条件であり、PIT 全体ではありません。一般研究と個人 DRAFT をグローバルに Prime へ限定しません。いまの正本 Controlled は凍結した `tse_prime_with_fins`（市場コード `0111`）を保ち、定義とフィルタは [../packages/product/research/universe_contract.py](../packages/product/research/universe_contract.py) にあります。他の研究はそれぞれの版付きユニバース定義を使います。適格ユニバースは版付きプロファイルから取り、カタログを手で写しません。

注文は、その朝に利用可能な情報で数量を決め、当日の PM 終値で約定を測ります。AM専用APIは現在の tip を返すため、正本の回顧は日次フィールドを使います。Premium 日次の生の朝値 MC、調整済み朝値 MAdjC、調整済み午後終値 AAdjC は、版付き再構成契約の下で回顧 Paper の正当なソースです。当時 11:30 に同時観測したことそのものではありません。生の取得時刻と公表時刻は残します。中核は AM 数量を `am_frozen_order_batch/v1` で凍結し、PM は約定・PnL・gross breach を測るだけで、事後のリサイズはしません。複数日保有のオーバーナイトリスクは残ります。18 年ランも成績も主張しません。戦略ごとの入手可能性・ウォームアップ・フィールド被覆は、その戦略の証拠で見ます。

## 信頼と配布

Controlled Pilot は `controlled_pilot_v1` の正確に四本です。実行には、その計画に対する正確な ExperimentPlan / StrategySpec / FeatureRef / プロファイル / closure / snapshot、信頼できる全セグメント receipt、B0 / B4、現行の source / export / applied generation、不変 READY、Trader の署名済み実行許可と Budget ゲートが要ります。欠けた証拠は実行を止めます。必須 closure は [../specs/ready/controlled_pilot_v1.generated.json](../specs/ready/controlled_pilot_v1.generated.json) と [../specs/experiment_plans/](../specs/experiment_plans/) が指すソースに従い、そこに無い履歴を必須にしません。汎用 caller JSON や DRAFT への署名は証明になりません。ソース実装は運用起動ではありません。READY 候補の準備から既存署名者、Trader 本番接続までは開いたままです。政策入力は [../specs/policy/controlled_pilot_policy.json](../specs/policy/controlled_pilot_policy.json)、ドリフト確認は [../scripts/verify_controlled_pilot_v1_drift.py](../scripts/verify_controlled_pilot_v1_drift.py) です。

個人 DRAFT の結果は研究用です。同じ規約の下で完備なら比較してよいですが、READY や Live ではありません。Mass は無効で、Pilot の証跡では Mass を有効化できません。凍結リプレイは通常実行ではありません。

通常配布が除外するのは legacy の `research.offline` / `research.unique_logic` 系だけです。通常の research ルートは入り、origin を検査します。wheel は研究スキーマ全体の自己完結バンドルではなく、schema と `repo_root` は checkout とアプリ資源に依存します。実 Container の smoke は現行消費者の import を確認します。これは方針であり、[operations/current_work_ledger.json](operations/current_work_ledger.json) が受理する前に達成とは言いません。検証入口は [../scripts/verify_source_capability_wheel.py](../scripts/verify_source_capability_wheel.py) です。再生互換ソースは残しますが通常実行ではなく、T01 の replay 階層化は未完です。

Coverage は契約と receipt からドメインを導きます。空の COMPLETE で無い被覆を埋めません。OpsCurrent は運用の読取モデルであり research READY ではありません。欠測投影を 0 とみなしません。運用ステータスや Cron PASS だけでは READY を証明しません。ソース公開、staging、production、データ有効化、READY、Pilot 実行は別工程です。承認と cancel / HOLD は他の CLI / API で迂回できません。本番 DLQ 本文は読まず、ack も purge もしません。共有 D1 は前方修復であり、ライター再開後の全 DB 復元ではありません。実行可能な運用手順は [operations/current_production_runbook.md](operations/current_production_runbook.md) だけです。文書の閲覧に許可は不要で、ライブ操作だけが現行認可と HOLD に従います。

CI は実際の Worker / workerd、環境の型検査と dry-run、リモート Container ビルドを回し、ローカル Docker の代用ではありません。native app `85455` 検査は維持します。入口は [../scripts/verify_ci.sh](../scripts/verify_ci.sh)、不変条件の対応は [ci/invariant_test_audit.md](ci/invariant_test_audit.md) と [operations/test_reduction_ledger.json](operations/test_reduction_ledger.json) です。所見は [phase633_finding_ledger.md](phase633_finding_ledger.md)、記録済み残差は [phase62_residual_status.md](phase62_residual_status.md) です。日付付き文書を鮮度として使いません。
