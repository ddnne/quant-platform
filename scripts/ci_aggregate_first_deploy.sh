#!/usr/bin/env bash
# Print-only helper for first create of quant-platform-ci-aggregate.
# Default: dry-run / print-only. Does not wrangler deploy. Does not mint tokens.
# --apply without CONFIRM_CI_AGGREGATE_CREATE=1 fails closed.
# Secret names only — never put CI_LANE_TOKEN / GITHUB_STATUS_TOKEN values here.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/ci_aggregate_first_deploy.sh [--apply]

Print the operator commands for first create of quant-platform-ci-aggregate.
Default is dry-run / print-only. This helper never execs wrangler deploy
and never puts secrets.

  --apply  refuse unless CONFIRM_CI_AGGREGATE_CREATE=1; still print-only
EOF
}

APPLY=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $arg" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "$APPLY" -eq 1 && "${CONFIRM_CI_AGGREGATE_CREATE:-}" != "1" ]]; then
  echo "refusing --apply without CONFIRM_CI_AGGREGATE_CREATE=1" >&2
  echo "default is dry-run / print-only; this helper does not wrangler deploy" >&2
  exit 1
fi

if [[ "$APPLY" -eq 1 ]]; then
  echo "CONFIRM_CI_AGGREGATE_CREATE=1: still print-only; this helper does not wrangler deploy" >&2
fi

# Exact operator commands. Dry-run first; live deploy + secret put stay comments.
cat <<'EOF'
cd platform/workers/ci-aggregate
npx wrangler deploy --dry-run
# npx wrangler deploy
# npx wrangler secret put CI_LANE_TOKEN
# npx wrangler secret put GITHUB_STATUS_TOKEN
EOF
