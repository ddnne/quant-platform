#!/usr/bin/env bash
# Production-ready local cron entry for Ops projection refresh.
# Intended for launchd/cron on the research host (or a runner with CF auth).
#
# Steps:
#   1) refresh_coverage_ledger (honest PARTIAL/COMPLETE from receipts)
#   2) publish_ops_projection (local SQL + meta)
#   3) optional --apply-remote when APPLY_REMOTE_OPS=1 and wrangler auth present
#
# Never claims coverage COMPLETE; only publishes whatever the ledger reports.
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
"$PY" scripts/refresh_coverage_ledger.py --db "$DB" || true
ARGS=(scripts/publish_ops_projection.py --db "$DB")
if [[ "${APPLY_REMOTE_OPS:-0}" == "1" ]]; then
  ARGS+=(--apply-remote)
fi
"$PY" "${ARGS[@]}"
echo "[cron_publish_ops] done $(date -Iseconds)"
