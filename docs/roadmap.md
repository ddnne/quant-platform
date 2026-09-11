# 残作業

単一利用者の Cloudflare 先行研究と、プロファイル拘束の Controlled Pilot 一本に向けた接続です。完了したことにしません。面の境界は [architecture.md](architecture.md)、入口は [../README.md](../README.md)、役割は [../AGENTS.md](../AGENTS.md) です。最新の受理と HOLD は [operations/current_work_ledger.json](operations/current_work_ledger.json)、所見は [phase633_finding_ledger.md](phase633_finding_ledger.md) です。

## 1. ソースとデータ所有者、スコープ

スコープコンパイラ、財務 compact state、complete-master 所有者は既にあります。残るのは共有の bar / 財務スコープを、認証済み候補・READY・runtime・Trader まで通すことです。通常配布の除外対象は architecture の方針どおりで、ledger 受理前に達成とは言いません。ソース受理はロールアウトを自動にしません。

## 2. Receipt、クラウドスナップショット、READY、Trader

全セグメント receipt、不変 READY、Trader の署名済み実行許可と Budget を、同じ Pilot 実行に載せる経路が未接続です。欠けた証拠は止めます。DRAFT の署名や汎用 JSON は証明になりません。候補準備から既存署名者、Trader 本番接続までは開いています。

## 3. 単純化、テスト、文書

入口から現行でない案内を外し、Coverage は契約と receipt からドメインを導きます。T01 の replay 階層化は未完です。不変条件の対応は [ci/invariant_test_audit.md](ci/invariant_test_audit.md) と [operations/test_reduction_ledger.json](operations/test_reduction_ledger.json) です。CI 入口は [../scripts/verify_ci.sh](../scripts/verify_ci.sh) です。件数目標ではありません。

## 4. 個別に認可した staging、そのあと production

ソース公開、staging、production は別工程です。新しい Worker や外部アンカーは増やしません。承認と HOLD は他経路で迂回できません。実行手順は [operations/current_production_runbook.md](operations/current_production_runbook.md) だけです。

## 5. データ有効化、物理証明、現行投影

デプロイ成功はデータ有効化ではなく、有効化は READY ではなく、READY は Pilot 実行ではありません。OpsCurrent や Cron PASS では READY を証明しません。欠測投影を 0 とみなしません。[phase62_residual_status.md](phase62_residual_status.md) の記録を鮮度として使わず、現行認可の下で測り直します。

## 6. すべての GO のあと、単一の Controlled Pilot だけ

正本は `controlled_pilot_v1` の正確に四本です。経済アイデア、2023 ベンチマーク、保有期間、予算は変えません。追加戦略はありません。GO が揃う前にも、保存中の HOLD があるあいだにも、実行しません。

## 7. 対象外のままにするもの

Mass、ファンド・オブ・ファンズ、実ブローカー、実注文、自動昇格は対象外です。Pilot の証跡では Mass を有効化できません。凍結リプレイも、ローカルに実市場履歴を残す運用も、通常経路にしません。
