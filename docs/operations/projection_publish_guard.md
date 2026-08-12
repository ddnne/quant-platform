# Full projection publish fail-closed guard

## 概要

`publish_ops_projection` 実行時、ローカル COMPLETE 件数がリモート COMPLETE 件数に満たない場合は即時拒否（fail-closed）する。

## 判定ルール

| 条件 | 判定 |
|------|------|
| `LOCAL_COMPLETE` ≥ `REMOTE_COMPLETE` | **GO** |
| `LOCAL_COMPLETE` < `REMOTE_COMPLETE` | **NO-GO（拒否・即時停止）** |

## 変数

| 変数 | 説明 |
|------|------|
| `LOCAL_COMPLETE` | ローカル projection の COMPLETE 件数 |
| `REMOTE_COMPLETE` | リモート projection の COMPLETE 件数 |

## fail-closed 動作

```text
if LOCAL_COMPLETE < REMOTE_COMPLETE:
    → refuse, EXIT 1, publish は一切実行しない
```

- 拒否理由を stderr に出力
- 部分適用は禁止

## オーバーライド

```bash
publish_ops_projection --force-apply-remote
```

- リモート COMPLETE を強制適用して publish を継続
- ⚠️ 使用時はオーナー承認・事由を必ず記録すること

## Mass NO-GO

一括評価時、対象 projection の **1件でも** `LOCAL_COMPLETE < REMOTE_COMPLETE` があれば **Mass NO-GO**。

- 全 projection の publish を一括停止
- 全件解消、または全件 `--force-apply-remote` 承認後のみ再開可能
