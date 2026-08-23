#!/usr/bin/env bash
# Authoritative CI: fail if anything is missing. No VERIFY_* skip flags.
# Fail-closed. No live wrangler deploy. Never npm ci --legacy-peer-deps.
# Never skip missing node_modules. Fast local helper: scripts/verify_all.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Ban: do not pass --legacy-peer-deps (peer graph must resolve from lockfiles).
# Ban: do not skip missing node_modules (always npm ci from package-lock.json).

WORKERS=(
  platform/workers/ingestion-jsda
  platform/workers/ingestion-premium
  platform/workers/ingestion-secrets
  platform/workers/quant-ops-mcp
  platform/workers/research-ai-gateway
  platform/workers/research-mass-eval
)

# Print package.json scripts.<name> body, or empty if missing.
npm_script_body() {
  "$1" -c 'import json, sys
p = json.load(open(sys.argv[1], encoding="utf-8"))
sys.stdout.write(str((p.get("scripts") or {}).get(sys.argv[2]) or ""))
' "$2" "$3"
}

python_is_311_plus() {
  local cand="$1"
  "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
}

echo "==> secret/path scan (tracked .env / *.pem)"
if git ls-files | grep -E '(^|/)\.env$|\.pem$'; then
  echo "tracked secret path: .env or *.pem must not be in git ls-files" >&2
  exit 1
fi

venv_py="$ROOT/.venv/bin/python"
if [[ ! -x "$venv_py" ]]; then
  echo "clean venv is required: create .venv with Python 3.11+ (e.g. python3.11 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]')" >&2
  echo "do not silently use system python" >&2
  exit 1
fi
if ! python_is_311_plus "$venv_py"; then
  echo ".venv must be Python 3.11+ (got $($venv_py -V 2>&1)); recreate: python3.11 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'" >&2
  exit 1
fi
py="$venv_py"

echo "==> pip install -e \".[dev]\""
"$py" -m pip install -e ".[dev]"

echo "==> python pytest"
"$py" -m pytest tests/

echo "==> catalog compile + catalog_ids freeze"
"$py" -c "from research.catalog_compiler import compile_catalog, assert_catalog_ids_emit_frozen; compile_catalog(); assert_catalog_ids_emit_frozen()"

echo "==> Evaluation IR golden/schema presence"
golden="$ROOT/specs/evaluation_ir/golden.jsonl"
schema_py="$ROOT/packages/product/research/evaluation_ir.py"
schema_ts="$ROOT/platform/workers/research-mass-eval/src/evaluation_ir.ts"
for p in "$golden" "$schema_py" "$schema_ts"; do
  if [[ ! -f "$p" ]]; then
    echo "Evaluation IR missing golden/schema: $p" >&2
    exit 1
  fi
done
if [[ ! -s "$golden" ]]; then
  echo "Evaluation IR golden is empty: $golden" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found" >&2
  exit 1
fi

for dir in "${WORKERS[@]}"; do
  name="$(basename "$dir")"
  if [[ ! -d "$dir" ]]; then
    echo "worker $name: missing directory ($dir)" >&2
    exit 1
  fi
  if [[ ! -f "$dir/package.json" ]]; then
    echo "worker $name: missing package.json ($dir)" >&2
    exit 1
  fi
  if [[ ! -f "$dir/package-lock.json" ]]; then
    echo "worker $name: missing package-lock.json ($dir)" >&2
    exit 1
  fi
  echo "==> npm ci ($name)"
  # Do not use npm ci --legacy-peer-deps
  (cd "$dir" && npm ci)
  echo "==> npm test ($name)"
  (cd "$dir" && npm test)
  echo "==> npm run typecheck ($name)"
  (cd "$dir" && npm run typecheck)
  echo "==> wrangler deploy --dry-run ($name)"
  (cd "$dir" && npx wrangler deploy --dry-run)
  if [[ -n "$(npm_script_body "$py" "$dir/package.json" types)" ]]; then
    echo "==> wrangler types --check ($name)"
    (cd "$dir" && npx wrangler types --check)
  else
    echo "==> wrangler types ($name)"
    (cd "$dir" && npx wrangler types)
  fi
done

echo "==> git working tree clean (generated types)"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "git working tree dirty after generated types; commit generated types" >&2
  git status --porcelain >&2
  exit 1
fi
if git ls-files --others --exclude-standard | grep -E '(^|/)worker-configuration\.d\.ts$'; then
  echo "untracked worker-configuration.d.ts after wrangler types; commit generated types" >&2
  exit 1
fi

echo "verify_ci: ok"
