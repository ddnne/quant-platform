#!/usr/bin/env bash
# Authenticated, read-only acceptance gate before any production deployment.
# Secret values are never requested or printed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

gate_py="$(command -v python3.11 2>/dev/null || command -v python3 2>/dev/null || true)"
if [[ -z "$gate_py" ]]; then
  echo "Python is required for the pinned finding-ledger release gate" >&2
  exit 1
fi

pending_environment=""
expected_source_sha=""
if [[ "$#" -eq 0 ]]; then
  "$gate_py" "$ROOT/scripts/finding_ledger_gate.py"
elif [[ "$#" -eq 4 && "$1" == "--pending-receipt-authority" && \
        "$3" == "--expected-source-sha" && \
        ( "$2" == "staging" || "$2" == "production" ) ]]; then
  pending_environment="$2"
  expected_source_sha="$4"
else
  echo "usage: $0 [--pending-receipt-authority staging|production --expected-source-sha SHA]" >&2
  exit 2
fi

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  echo "CLOUDFLARE_API_TOKEN is required for production acceptance" >&2
  exit 1
fi
if [[ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]]; then
  echo "CLOUDFLARE_ACCOUNT_ID is required for production acceptance" >&2
  exit 1
fi

# Keep production credentials out of dependency installation, tests, builds,
# and dry-runs. Only the read-only live inventory below receives them.
env \
  -u CLOUDFLARE_API_TOKEN \
  -u CLOUDFLARE_API_KEY \
  -u CLOUDFLARE_EMAIL \
  -u CLOUDFLARE_ACCOUNT_ID \
  bash "$ROOT/scripts/verify_ci.sh"

py="$ROOT/.venv/bin/python"
if [[ ! -x "$py" ]]; then
  echo "verify_ci did not provide the pinned Python runtime" >&2
  exit 1
fi

if [[ -n "$pending_environment" ]]; then
  "$py" "$ROOT/scripts/receipt_authority_pending_gate.py" \
    --environment "$pending_environment" \
    --expected-source-sha "$expected_source_sha"
  "$py" "$ROOT/scripts/verify_cloudflare_secret_inventory.py" \
    --require-api-token \
    --environment "$pending_environment" \
    --worker receipt-evidence-authority
  "$py" "$ROOT/scripts/receipt_authority_pending_live_acceptance.py" \
    --environment "$pending_environment" \
    --expected-source-sha "$expected_source_sha" \
    --expected-account-id "$CLOUDFLARE_ACCOUNT_ID"
  echo "receipt authority PENDING deployment acceptance: ok ($pending_environment)"
  exit 0
fi

"$py" "$ROOT/scripts/verify_cloudflare_secret_inventory.py" --require-api-token

echo "cloudflare deployment acceptance: ok"
