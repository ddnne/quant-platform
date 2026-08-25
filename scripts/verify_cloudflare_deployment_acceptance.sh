#!/usr/bin/env bash
# Authenticated, read-only acceptance gate before any production deployment.
# Secret values are never requested or printed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  echo "CLOUDFLARE_API_TOKEN is required for production acceptance" >&2
  exit 1
fi
if [[ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]]; then
  echo "CLOUDFLARE_ACCOUNT_ID is required for production acceptance" >&2
  exit 1
fi

bash "$ROOT/scripts/verify_ci.sh"

py="$ROOT/.venv/bin/python"
if [[ ! -x "$py" ]]; then
  echo "verify_ci did not provide the pinned Python runtime" >&2
  exit 1
fi

"$py" "$ROOT/scripts/verify_cloudflare_secret_inventory.py" \
  --require-api-token

echo "cloudflare deployment acceptance: ok"
