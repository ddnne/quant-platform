#!/usr/bin/env bash
# Authenticated, read-only acceptance gate before any production deployment.
# Secret values are never requested or printed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Capture the only accepted live credentials, then remove every supported
# Wrangler credential from the ambient environment before executing repository
# code.  The lower-case variables are deliberately not exported.
cloudflare_api_token="${CLOUDFLARE_API_TOKEN:-}"
cloudflare_account_id="${CLOUDFLARE_ACCOUNT_ID:-}"
export -n cloudflare_api_token cloudflare_account_id 2>/dev/null || true
unset CLOUDFLARE_API_TOKEN CLOUDFLARE_API_KEY CLOUDFLARE_EMAIL \
  CLOUDFLARE_ACCOUNT_ID

acceptance_runtime="$(
  /usr/bin/mktemp -d "${TMPDIR:-/tmp}/quant-platform-acceptance.XXXXXX"
)"
if [[ ! -d "$acceptance_runtime" || \
      "${acceptance_runtime##*/}" != quant-platform-acceptance.?????? ]]; then
  echo "Could not create the isolated acceptance runtime" >&2
  exit 1
fi
cleanup_acceptance_runtime() {
  cloudflare_api_token=""
  cloudflare_account_id=""
  if [[ -n "${acceptance_runtime:-}" && -d "$acceptance_runtime" && \
        "${acceptance_runtime##*/}" == quant-platform-acceptance.?????? ]]; then
    /bin/rm -rf -- "$acceptance_runtime"
  fi
}
trap cleanup_acceptance_runtime EXIT
/bin/chmod 700 "$acceptance_runtime"
/bin/mkdir -m 700 \
  "$acceptance_runtime/home" \
  "$acceptance_runtime/wrangler" \
  "$acceptance_runtime/cache" \
  "$acceptance_runtime/config" \
  "$acceptance_runtime/data" \
  "$acceptance_runtime/tmp"

minimum_environment=(
  "PATH=${PATH:-/usr/bin:/bin}"
  "LANG=${LANG:-C}"
  "HOME=$acceptance_runtime/home"
  "WRANGLER_HOME=$acceptance_runtime/wrangler"
  "XDG_CACHE_HOME=$acceptance_runtime/cache"
  "XDG_CONFIG_HOME=$acceptance_runtime/config"
  "XDG_DATA_HOME=$acceptance_runtime/data"
  "TMPDIR=$acceptance_runtime/tmp"
  "CI=true"
  "NO_COLOR=1"
  "WRANGLER_SEND_METRICS=false"
)

run_without_cloudflare_credentials() {
  /usr/bin/env -i "${minimum_environment[@]}" "$@"
}

run_with_cloudflare_credentials() {
  /usr/bin/env -i \
    "${minimum_environment[@]}" \
    "CLOUDFLARE_API_TOKEN=$cloudflare_api_token" \
    "CLOUDFLARE_ACCOUNT_ID=$cloudflare_account_id" \
    "$@"
}

gate_py="$(command -v python3.11 2>/dev/null || command -v python3 2>/dev/null || true)"
if [[ -z "$gate_py" ]]; then
  echo "Python is required for the pinned finding-ledger release gate" >&2
  exit 1
fi

pending_environment=""
expected_source_sha=""
if [[ "$#" -eq 0 ]]; then
  run_without_cloudflare_credentials \
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

if [[ -z "$cloudflare_api_token" ]]; then
  echo "CLOUDFLARE_API_TOKEN is required for production acceptance" >&2
  exit 1
fi
if [[ -z "$cloudflare_account_id" ]]; then
  echo "CLOUDFLARE_ACCOUNT_ID is required for production acceptance" >&2
  exit 1
fi

# Keep production credentials and stored Wrangler OAuth out of dependency
# installation, tests, builds, and dry-runs. Only the read-only live inventory
# commands below receive the captured API token and account id.
run_without_cloudflare_credentials \
  /bin/bash "$ROOT/scripts/verify_ci.sh"

py="$ROOT/.venv/bin/python"
if [[ ! -x "$py" ]]; then
  echo "verify_ci did not provide the pinned Python runtime" >&2
  exit 1
fi

if [[ -n "$pending_environment" ]]; then
  run_without_cloudflare_credentials \
    "$py" "$ROOT/scripts/receipt_authority_pending_gate.py" \
    --environment "$pending_environment" \
    --expected-source-sha "$expected_source_sha"
  run_with_cloudflare_credentials \
    "$py" "$ROOT/scripts/verify_cloudflare_secret_inventory.py" \
    --require-api-token \
    --environment "$pending_environment" \
    --worker receipt-evidence-authority
  run_with_cloudflare_credentials \
    "$py" "$ROOT/scripts/receipt_authority_pending_live_acceptance.py" \
    --environment "$pending_environment" \
    --expected-source-sha "$expected_source_sha" \
    --expected-account-id "$cloudflare_account_id"
  echo "receipt authority PENDING deployment acceptance: ok ($pending_environment)"
  exit 0
fi

run_with_cloudflare_credentials \
  "$py" "$ROOT/scripts/verify_cloudflare_secret_inventory.py" \
  --require-api-token

echo "cloudflare deployment acceptance: ok"
