# Quant Platform

日本株・開示・債券のリサーチと Paper を、単一利用者向けに Cloudflare 上で進めるリポジトリです。通常の市場データ取得・保存・実データ研究はクラウドが本体です。ファンド・オブ・ファンズ、実ブローカー、実注文、自動昇格はありません。Mass は無効です。新しい Worker、authority、UID、WebAuthn、外部アンカーは増やしません。

実装と一次自己レビューは Grok、計画・独立レビュー・テスト・Git・CI・マージは Codex です。役割は [AGENTS.md](AGENTS.md) に従います。時刻・PIT・保存・信頼境界は [docs/architecture.md](docs/architecture.md)、残作業の順は [docs/roadmap.md](docs/roadmap.md) です。古いフェーズ成功表は Git と ADR に残し、ここには現行経路だけを書きます。

## 三つの経路

個人 DRAFT と Controlled Pilot は別物です。Mass はどちらでもありません。

**個人 DRAFT**は既存の `POST /v1/personal-snapshot-build` と `POST /v1/personal-research-batch` です。Controlled READY は不要ですが、現行のデプロイ品質や実行認可の代用ではありません。結果は研究用であり、同じ規約の下で完備なら比較に使えます。可変で短命な成果は観測されうる一方、管理されないことがあります。DRAFT の完備は、信頼できる Controlled の COMPLETE / READY / 昇格ではありません。状態・上限・認証は [platform/workers/research-mass-eval/README.md](platform/workers/research-mass-eval/README.md) を正本にします。保存中の cancel / HOLD があるあいだ、ここから実行を指示しません。

**Controlled Pilot**はプロファイルに拘束された `controlled_pilot_v1` の正確に四本です。個人 DRAFT の四候補コホートとは別です。必要な証拠と未接続箇所は [docs/architecture.md](docs/architecture.md) です。計画と政策の入力は [specs/policy/controlled_pilot_policy.json](specs/policy/controlled_pilot_policy.json)、[specs/ready/controlled_pilot_v1.generated.json](specs/ready/controlled_pilot_v1.generated.json)、[specs/experiment_plans/](specs/experiment_plans/) です。版やダイジェストは写しません。ドリフト確認は [scripts/verify_controlled_pilot_v1_drift.py](scripts/verify_controlled_pilot_v1_drift.py) です。

**Mass**は無効です。Pilot の証跡では Mass を有効化できません。追加戦略やカタログ拡張はありません。凍結リプレイは通常実行ではありません。

## 読む場所

配置は [docs/architecture/repo_layout_migration.md](docs/architecture/repo_layout_migration.md) と [docs/architecture/llm_nav_map.md](docs/architecture/llm_nav_map.md)、経路の分離は [docs/architecture/adr_phase632_architecture_simplification.md](docs/architecture/adr_phase632_architecture_simplification.md) です。

作業の受理、保存中の cancel / HOLD、最後に読んだ計測は [docs/operations/current_work_ledger.json](docs/operations/current_work_ledger.json) です。ライブ照会の代わりにはしません。所見と昇格ゲートは [docs/phase633_finding_ledger.md](docs/phase633_finding_ledger.md) と [docs/phase633_finding_ledger.json](docs/phase633_finding_ledger.json) です。記録済み live GO 残差は [docs/phase62_residual_status.md](docs/phase62_residual_status.md) に残りますが、日付付き文書から鮮度を主張しません。

リポジトリ文書を読むのに許可は不要です。ライブ運用の実行だけが現行認可と HOLD に従い、手順は [docs/operations/current_production_runbook.md](docs/operations/current_production_runbook.md) にだけあります。コマンドはここへ貼りません。

稼働面は [specs/cloudflare/active_worker_bindings.json](specs/cloudflare/active_worker_bindings.json)、D1 移行は [specs/cloudflare/d1_migration_manifest.json](specs/cloudflare/d1_migration_manifest.json) です。件数や目録は写しません。不変条件の対応は [docs/ci/invariant_test_audit.md](docs/ci/invariant_test_audit.md) と [docs/operations/test_reduction_ledger.json](docs/operations/test_reduction_ledger.json) です。秘密は名前だけ [platform/secrets.example.md](platform/secrets.example.md) を見ます。

## 開発者セットアップとテスト

checkout した開発者向けです。通常利用者の実行手順ではなく、実市場のローカル取得や Docker 起動は書きません。`qp-research` は開発者・復旧互換であり、通常経路ではありません。配布と CI の境界は [docs/architecture.md](docs/architecture.md) です。

```bash
# ロックどおり開発 extra を同期する
uv sync --frozen --extra dev

# 通常スイート。toolchain / live / platform を除く
.venv/bin/python -m pytest tests/ -m "not toolchain and not live and not platform"

# toolchain。live と platform は除く
.venv/bin/python -m pytest tests/ -m "toolchain and not live and not platform"

# platform マーカーだけを選び、--run-platform でオプトインする
.venv/bin/python -m pytest tests/ -m platform --run-platform
```

Cloudflare Builds 上のランナー専用です。Mac で実行する指示ではありません。実 Wrangler dry-run と Container イメージビルドを含みます。

```bash
scripts/verify_ci.sh
```

既定の pytest-socket は、テスト実行中の通常 Python ソケット生成と `getaddrinfo` / `gethostbyname` を拒みます。Unix IPC は許します。すべての DNS を止めるわけではなく、コレクションや import、exec した子、native / Node / Worker までは覆いません。`-m platform` は該当テストだけを選び、`--run-platform` がオプトインです。`live` は CI から除外しますが収集スキップではなく、`QP_LIVE` だけではネットワークは開きません。非 live スイートは SQLite とプロセス統合を含みます。件数・壁時計・費用は保証しません。
