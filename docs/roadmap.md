# 残作業

単一利用者の Cloudflare 先行研究と、プロファイル拘束の Controlled Pilot 一本に向けた接続です。完了したことにしません。面の境界は [architecture.md](architecture.md)、入口は [../README.md](../README.md)、役割は [../AGENTS.md](../AGENTS.md) です。最新の受理と HOLD は [operations/current_work_ledger.json](operations/current_work_ledger.json)、所見は [phase633_finding_ledger.md](phase633_finding_ledger.md) です。

## 1. ソースとデータ所有者、スコープ

予定の price-master 四案は runtime の共有 bar scope と DRAFT 入口の closure 拘束を使い、READY 候補経路は通りません。正本 Controlled の v3 bar / 財務スコープは compiler、候補、READY、runtime へ接続済みで、master seed、財務期首状態、split anchor、必須列は既存 DataPlane 所有者が選択します。残るのは実データの全必要スコープを同じクラウド snapshot で証明することです。全 feature / 全 DRAFT の詳細スコープ完了とは言わず、旧版の互換経路も区別します。ソース受理はロールアウトを自動にしません。

## 2. Receipt、クラウドスナップショット、READY、Trader

既存 Container の receipt-bound 候補から Premium の READY / Trader 署名者、verify-only 評価 Worker までのソース経路は接続済みです。未受入なのは、本番で同じ snapshot / scope / B0・B4 / plan・profile・closure を束縛した証拠と実行許可です。欠けた証拠は止めます。DRAFT の署名や汎用 JSON は証明にならず、ソース接続だけでは研究 GO を出しません。

## 3. 単純化、テスト、文書

旧 Mass 実装、offline / unique_logic の並行経路と専用 replay lane は退役済みです。再現に必要なコードは Git 履歴、凍結カタログと過去成果は既存 artifact に残し、通常 install / active bundle へ戻しません。全体の単純化は継続課題で、コード半減や全テスト削減の完了とは言いません。不変条件の対応は [ci/invariant_test_audit.md](ci/invariant_test_audit.md) と [operations/test_reduction_ledger.json](operations/test_reduction_ledger.json) です。CI 入口は [../scripts/verify_ci.sh](../scripts/verify_ci.sh) です。件数目標ではありません。

## 4. 個別に認可した staging、そのあと production

ソース公開、staging、production は別工程です。新しい Worker や外部アンカーは増やしません。承認と HOLD は他経路で迂回できません。実行手順は [operations/current_production_runbook.md](operations/current_production_runbook.md) だけです。

## 5. データ有効化、物理証明、現行投影

デプロイ成功はデータ有効化ではなく、有効化は READY ではなく、READY は Pilot 実行ではありません。OpsCurrent や Cron PASS では READY を証明しません。欠測投影を 0 とみなしません。[phase62_residual_status.md](phase62_residual_status.md) の記録を鮮度として使わず、現行認可の下で測り直します。

## 6. すべての GO のあと、単一の Controlled Pilot だけ

正本は `controlled_pilot_v1` の正確に四本です。経済アイデア、2023 ベンチマーク、保有期間、予算は変えません。追加戦略はありません。GO が揃う前にも、保存中の HOLD があるあいだにも、実行しません。

## 7. 対象外のままにするもの

Mass、ファンド・オブ・ファンズ、実ブローカー、実注文、自動昇格は対象外です。Pilot の証跡では Mass を有効化できません。凍結リプレイも、ローカルに実市場履歴を残す運用も、通常経路にしません。
