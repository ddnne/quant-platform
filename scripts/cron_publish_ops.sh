#!/usr/bin/env bash
# Production-ready local cron entry for Ops projection refresh.
# Never presents a failed refresh as FRESH (handled in publish_ops_projection).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DB="${OPS_DB:-$ROOT/data/structured/ingestion.sqlite}"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
LOGDIR="${OPS_LOGDIR:-$ROOT/.glm-logs/ops-cron}"
mkdir -p "$LOGDIR"
STAMP=$(date +%Y%m%dT%H%M%S)
LOG="$LOGDIR/publish_$STAMP.log"
exec > >(tee -a "$LOG") 2>&1
echo "[cron_publish_ops] start $(date -Iseconds) db=$DB"
if [[ ! -f "$DB" ]]; then
  echo "[cron_publish_ops] missing db: $DB" >&2
  exit 2
fi
# Local refresh may lag remote COMPLETE. Full --apply-remote is fail-closed
# (see publish_ops_projection enforce_complete_count_guard). Prefer targeted
# remote freshness when APPLY_REMOTE_OPS=1 but full publish would be refused.
ARGS=(scripts/publish_ops_projection.py --db "$DB" --refresh-coverage)
if [[ "${APPLY_REMOTE_OPS:-0}" == "1" ]]; then
  ARGS+=(--apply-remote)
fi
set +e
"$PY" "${ARGS[@]}"
rc=$?
set -e
if [[ "$rc" -eq 3 && "${APPLY_REMOTE_OPS:-0}" == "1" ]]; then
  echo "[cron_publish_ops] full apply refused by COMPLETE guard (rc=3); running targeted ops_reeval_freshness"
  set +e
  "$PY" scripts/ops_reeval_freshness.py
  rc=$?
  set -e
fi
echo "[cron_publish_ops] done rc=$rc $(date -Iseconds)"
exit "$rc"
