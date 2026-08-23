#!/usr/bin/env bash
# Pre-push entry: pytest + catalog freeze + worker npm tests.
# Fail-closed. No live wrangler deploy. Never npm ci --legacy-peer-deps.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Ban: do not pass --legacy-peer-deps (peer graph must resolve from lockfiles).
# Optional VERIFY_NPM_CI=1 runs `npm ci` (not `npm ci --legacy-peer-deps`) when
# a worker is missing node_modules. Default is skip with a reason (npm ci is slow).
# Optional VERIFY_NPM_TYPECHECK=1 / VERIFY_NPM_BUILD=1 (default off): if
# node_modules exists, run `npm run typecheck` / `npm run build` when the
# script is present (skip with reason otherwise). Build must be dry-run;
# never wrangler deploy.

WORKERS=(
  platform/workers/quant-ops-mcp
  platform/workers/research-ai-gateway
  platform/workers/research-mass-eval
)

# Print package.json scripts.<name> body, or empty if missing.
npm_script_body() {
  python3 -c 'import json, sys
p = json.load(open(sys.argv[1], encoding="utf-8"))
sys.stdout.write(str((p.get("scripts") or {}).get(sys.argv[2]) or ""))
' "$1" "$2"
}

missing_venv=0
py=""

python_is_311_plus() {
  local cand="$1"
  "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
}

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  py="$ROOT/.venv/bin/python"
else
  missing_venv=1
  echo "clean venv is required: create .venv with Python 3.11+ (e.g. python3.11 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]')" >&2
  for cand in python3.13 python3.12 python3.11 python3; do
    if command -v "$cand" >/dev/null 2>&1 && python_is_311_plus "$(command -v "$cand")"; then
      py="$(command -v "$cand")"
      echo "using $py for pytest (venv still required; this run will exit non-zero)" >&2
      break
    fi
  done
  if [[ -z "$py" ]]; then
    echo "python 3.11+ not found; cannot run pytest" >&2
  fi
fi

echo "==> python pytest"
if [[ -n "$py" ]]; then
  "$py" -m pytest tests/ -q
elif [[ "$missing_venv" -eq 1 ]]; then
  : # already reported; fail after remaining checks
else
  echo "python interpreter missing" >&2
  exit 1
fi

echo "==> catalog compile + freeze"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  "$ROOT/.venv/bin/python" -c "from research.catalog_compiler import compile_catalog, assert_catalog_ids_emit_frozen; compile_catalog(); assert_catalog_ids_emit_frozen()"
else
  echo "catalog: skip — .venv missing (clean venv is required)" >&2
fi

for dir in "${WORKERS[@]}"; do
  name="$(basename "$dir")"
  if [[ ! -f "$dir/package.json" ]]; then
    echo "worker $name: missing package.json ($dir)" >&2
    exit 1
  fi
  if [[ ! -d "$dir/node_modules" ]]; then
    if [[ "${VERIFY_NPM_CI:-0}" == "1" ]]; then
      echo "==> npm ci ($name) (VERIFY_NPM_CI=1)"
      if ! command -v npm >/dev/null 2>&1; then
        echo "worker $name: npm not found" >&2
        exit 1
      fi
      # Do not use npm ci --legacy-peer-deps
      (cd "$dir" && npm ci)
    else
      echo "worker $name: skip — node_modules missing (install in $dir, or VERIFY_NPM_CI=1)"
      continue
    fi
  fi
  if ! command -v npm >/dev/null 2>&1; then
    echo "worker $name: npm not found" >&2
    exit 1
  fi
  echo "==> npm test ($name)"
  (cd "$dir" && npm test)
  if [[ "${VERIFY_NPM_TYPECHECK:-0}" == "1" ]]; then
    if [[ -n "$(npm_script_body "$dir/package.json" typecheck)" ]]; then
      echo "==> npm run typecheck ($name) (VERIFY_NPM_TYPECHECK=1)"
      (cd "$dir" && npm run typecheck)
    else
      echo "worker $name: skip typecheck — no typecheck script in package.json"
    fi
  fi
  if [[ "${VERIFY_NPM_BUILD:-0}" == "1" ]]; then
    build_cmd="$(npm_script_body "$dir/package.json" build)"
    if [[ -z "$build_cmd" ]]; then
      echo "worker $name: skip build — no build script in package.json"
    elif [[ "$build_cmd" == *"wrangler deploy"* && "$build_cmd" != *"--dry-run"* ]]; then
      echo "worker $name: refuse build — not dry-run (never wrangler deploy): $build_cmd" >&2
      exit 1
    else
      echo "==> npm run build ($name) (VERIFY_NPM_BUILD=1, dry-run/no deploy)"
      (cd "$dir" && npm run build)
    fi
  fi
done

if [[ "$missing_venv" -eq 1 ]]; then
  echo "verify_all: failed — clean venv is required" >&2
  exit 1
fi

echo "verify_all: ok"
