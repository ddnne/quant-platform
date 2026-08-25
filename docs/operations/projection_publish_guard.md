# Full projection publish fail-closed guard

## 概要

`publish_ops_projection` 実行時、ローカル COMPLETE 件数がリモートの
active generation の COMPLETE 件数に満たない場合は即時拒否
（fail-closed）する。対象は ingestion D1 ではなく、専用
`quant-ops-projection` D1 である。

## 判定ルール

| 条件 | 判定 |
|------|------|
| `LOCAL_COMPLETE` ≥ `REMOTE_COMPLETE` | **GO** |
| `LOCAL_COMPLETE` < `REMOTE_COMPLETE` | **NO-GO（拒否・即時停止）** |

## 変数

| 変数 | 説明 |
|------|------|
| `LOCAL_COMPLETE` | ローカル projection の COMPLETE 件数 |
| `REMOTE_COMPLETE` | リモート active projection generation の COMPLETE 件数 |

## fail-closed 動作

```text
if REMOTE_COMPLETE is unknown:
    → refuse, EXIT 3
if LOCAL_COMPLETE < REMOTE_COMPLETE:
    → refuse, EXIT 3
```

- 拒否理由を stderr に出力
- D1 import は非transactionalでも安全に見えなくてはならない。各内容行を
  generation-scoped に追記し、expected row count が一致した場合だけ
  immutable `SEALED` generation 行を追記する。
- active pointer の更新は必ず最後に行う。途中失敗で残った内容行は
  pointer から参照されず、MCP から不可視である。
- generation 行は publish 後に UPDATE／DELETE しない。
- remote apply は専用 Ops Projection Ed25519 署名鍵がなければ EXIT 6 で
  拒否する。Receipt/READY 鍵への fallback はない。
- consumer は `ops-projection-signed-envelope/v1` を public-key registry で
  検証する。unsigned・unknown issuer・tamper は `NOT_PROJECTED` である。

## オーバーライド

```bash
publish_ops_projection --force-apply-remote
```

- remote probe 不明または COMPLETE 減少を明示的に上書きして publish を継続
- ⚠️ 使用時はオーナー承認・事由を必ず記録すること

## Mass NO-GO

一括評価時、対象 projection の **1件でも** `LOCAL_COMPLETE < REMOTE_COMPLETE` があれば **Mass NO-GO**。

- 全 projection の publish を一括停止
- 全件解消、または全件 `--force-apply-remote` 承認後のみ再開可能
