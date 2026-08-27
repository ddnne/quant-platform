#!/usr/bin/env bash
# Production-ready local cron entry for Ops projection refresh.
# Never presents a failed refresh as FRESH (handled in publish_ops_projection).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DB="${OPS_SOURCE_DB:-$ROOT/data/structured/ingestion.sqlite}"
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
# Local refresh may lag the active projection. Full --apply-remote is
# fail-closed. A refused publication leaves the prior immutable generation
# active and exits non-zero; no targeted mutation of ingestion D1 is allowed.
ARGS=(scripts/publish_ops_projection.py --db "$DB" --refresh-coverage)
if [[ "${APPLY_REMOTE_OPS:-0}" == "1" ]]; then
  ARGS+=(--apply-remote)
fi
set +e
"$PY" "${ARGS[@]}"
rc=$?
set -e
echo "[cron_publish_ops] done rc=$rc $(date -Iseconds)"
exit "$rc"
