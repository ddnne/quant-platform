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
  "$cand" - <<'PY'
import sqlite3
import sys

if sys.version_info < (3, 11):
    raise SystemExit(1)
with sqlite3.connect(":memory:") as db:
    if db.execute("SELECT 1").fetchone() != (1,):
        raise SystemExit(1)
PY
}

# Host interpreter is only for `python -m venv`. Never run pytest with it.
# Prefer python3.11; accept python3 only when it is 3.11+ and has working
# stdlib sqlite3. Do not use system 3.9 or a version-only incomplete runtime.
find_python_311_plus() {
  local cand path
  for cand in python3.11 python3; do
    path="$(command -v "$cand" 2>/dev/null || true)"
    if [[ -n "$path" ]] && python_is_311_plus "$path"; then
      printf '%s' "$path"
      return 0
    fi
  done
  return 1
}

echo "==> secret/path scan (tracked .env / *.pem)"
if git ls-files | grep -E '(^|/)\.env$|\.pem$'; then
  echo "tracked secret path: .env or *.pem must not be in git ls-files" >&2
  exit 1
fi

host_py=""
if ! host_py="$(find_python_311_plus)"; then
  echo "Python 3.11+ with working stdlib sqlite3 is required." >&2
  echo "do not silently use system python" >&2
  exit 1
fi

UV_VERSION="0.11.26"
uv_cmd="$(command -v uv 2>/dev/null || true)"
if [[ -z "$uv_cmd" ]]; then
  echo "==> bootstrap uv $UV_VERSION"
  "$host_py" -m venv "$ROOT/.ci-uv"
  "$ROOT/.ci-uv/bin/python" -m pip install "uv==$UV_VERSION"
  uv_cmd="$ROOT/.ci-uv/bin/uv"
fi
if [[ "$($uv_cmd --version)" != "uv $UV_VERSION "* && "$($uv_cmd --version)" != "uv $UV_VERSION" ]]; then
  echo "uv version drift: expected $UV_VERSION, got $($uv_cmd --version)" >&2
  exit 1
fi

echo "==> uv sync --frozen --extra dev"
"$uv_cmd" sync --frozen --extra dev --python "$host_py"
py="$ROOT/.venv/bin/python"
if ! python_is_311_plus "$py"; then
  echo "uv-managed .venv must be Python 3.11+ with working stdlib sqlite3." >&2
  exit 1
fi

echo "==> Cloudflare active-worker binding manifest"
"$py" scripts/cloudflare_binding_manifest.py

echo "==> Cloudflare canonical D1 migration manifest"
"$py" scripts/cloudflare_d1_migration_manifest.py

echo "==> python pytest"
"$py" -m pytest tests/

echo "==> Evaluation IR schema + golden (jsonschema + codec roundtrip)"
golden="$ROOT/specs/evaluation_ir/golden.jsonl"
schema="$ROOT/specs/evaluation_ir/schema.json"
schema_py="$ROOT/packages/product/research/evaluation_ir.py"
schema_ts="$ROOT/platform/workers/research-mass-eval/src/evaluation_ir.ts"
allowed_ts="$ROOT/platform/workers/research-mass-eval/src/evaluation_ir_allowed_fields.generated.ts"
codec_ts="$ROOT/platform/workers/research-mass-eval/src/evaluation_ir_codec.generated.ts"
codec_py="$ROOT/packages/product/research/evaluation_ir_codec.generated.py"
types_py="$ROOT/packages/product/research/evaluation_ir_types.generated.py"
for p in "$golden" "$schema" "$schema_py" "$schema_ts" "$allowed_ts" "$codec_ts" "$codec_py" "$types_py"; do
  if [[ ! -f "$p" ]]; then
    echo "Evaluation IR missing golden/schema: $p" >&2
    exit 1
  fi
done
if [[ ! -s "$golden" ]]; then
  echo "Evaluation IR golden is empty: $golden" >&2
  exit 1
fi
# Independent jsonschema + Python encode/decode. evaluation_ir.ts is the
# Worker façade; encode/decode body is generated from schema.json.
# Python evaluation_ir.py is the façade; encode/decode body is generated.
# ALLOWED_FIELDS, encode object keys, and Python TypedDicts are generated
# from schema.json. Types are not a grade policy.
"$py" -c 'from research.evaluation_ir import assert_evaluation_ir_allowed_fields_ts_frozen, assert_evaluation_ir_codec_ts_frozen, assert_evaluation_ir_codec_py_frozen, assert_evaluation_ir_types_py_frozen, assert_evaluation_ir_encode_keys_match_schema; assert_evaluation_ir_allowed_fields_ts_frozen(); assert_evaluation_ir_codec_ts_frozen(); assert_evaluation_ir_codec_py_frozen(); assert_evaluation_ir_types_py_frozen(); assert_evaluation_ir_encode_keys_match_schema()'
"$py" -c 'import json
from pathlib import Path
import jsonschema
from jsonschema import Draft7Validator
from research.evaluation_ir import (
    decode_evaluation_ir,
    encode_evaluation_ir,
    load_evaluation_ir_schema,
)

schema_path = Path("specs/evaluation_ir/schema.json")
golden_path = Path("specs/evaluation_ir/golden.jsonl")
if not schema_path.is_file():
    raise SystemExit(f"Evaluation IR schema missing: {schema_path}")
if not golden_path.is_file():
    raise SystemExit(f"Evaluation IR golden missing: {golden_path}")
schema = json.loads(schema_path.read_text(encoding="utf-8"))
if not isinstance(schema, dict) or not schema:
    raise SystemExit("Evaluation IR schema is empty")
if load_evaluation_ir_schema() != schema:
    raise SystemExit("Evaluation IR schema.json drifted from research.evaluation_ir")
raw = golden_path.read_text(encoding="utf-8")
if not raw.strip():
    raise SystemExit(f"Evaluation IR golden is empty: {golden_path}")
n = 0
for lineno, line in enumerate(raw.splitlines(), start=1):
    if not line.strip():
        continue
    n += 1
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Evaluation IR golden line {lineno}: invalid JSON: {exc}") from exc
    if not isinstance(row, dict):
        raise SystemExit(f"Evaluation IR golden line {lineno}: row must be an object")
    label = row.get("id", lineno)
    op = row.get("op")
    if op == "roundtrip":
        encoded = encode_evaluation_ir(**row["args"])
        jsonschema.validate(instance=encoded, schema=schema, cls=Draft7Validator)
        decoded = decode_evaluation_ir(encoded)
        if decoded.to_dict() != encoded:
            raise SystemExit(f"Evaluation IR golden {label}: encode/decode roundtrip drift")
        expect = row["expect"]
        if (
            encoded["candidate"] is not expect["candidate"]
            or encoded["failure_reason"] != expect["failure_reason"]
        ):
            raise SystemExit(f"Evaluation IR golden {label}: expect drift")
        continue
    if op == "decode":
        payload = row["payload"]
        schema_ok = True
        try:
            jsonschema.validate(instance=payload, schema=schema, cls=Draft7Validator)
        except jsonschema.ValidationError:
            schema_ok = False
        try:
            decode_evaluation_ir(payload)
        except (ValueError, TypeError) as exc:
            needle = str(row.get("expect_error") or "")
            if needle and needle not in str(exc):
                raise SystemExit(
                    f"Evaluation IR golden {label}: unexpected decode error: {exc}"
                ) from exc
            continue
        if not schema_ok:
            raise SystemExit(f"Evaluation IR golden {label}: decode ignored schema.json")
        raise SystemExit(f"Evaluation IR golden {label}: expected decode to fail")
    raise SystemExit(f"Evaluation IR golden {label}: unknown op {op!r}")
if n == 0:
    raise SystemExit(f"Evaluation IR golden is empty: {golden_path}")
'

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found" >&2
  exit 1
fi

verify_worker() {
  local dir="$1" name
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
  echo "==> wrangler deploy --dry-run --env= ($name)"
  (cd "$dir" && npx --no-install wrangler deploy --dry-run --env="")
  echo "==> wrangler deploy --dry-run --env=production ($name)"
  (cd "$dir" && npx --no-install wrangler deploy --dry-run --env=production)
  echo "==> wrangler deploy --dry-run --config=wrangler.staging.toml ($name)"
  (cd "$dir" && npx --no-install wrangler deploy --dry-run --config=wrangler.staging.toml)
  if [[ -n "$(npm_script_body "$py" "$dir/package.json" types)" ]]; then
    echo "==> wrangler types --check ($name)"
    # Honor scripts.types flags (include-runtime false). Bare
    # `npx wrangler types --check` regenerates workerd runtime types.
    (cd "$dir" && npm run types -- --check)
  else
    echo "==> wrangler types ($name)"
    (cd "$dir" && npx --no-install wrangler types)
  fi
  local type_dir production_types staging_types
  type_dir="$ci_log_dir/types-$name"
  mkdir -p "$type_dir"
  production_types="$type_dir/production.d.ts"
  staging_types="$type_dir/staging.d.ts"
  echo "==> wrangler types --env=production ($name)"
  (cd "$dir" && npx --no-install wrangler types "$production_types" \
    --env=production --include-runtime=false)
  echo "==> wrangler types --config=wrangler.staging.toml ($name)"
  (cd "$dir" && npx --no-install wrangler types "$staging_types" \
    --config=wrangler.staging.toml --include-runtime=false)
  # Values and optional capabilities intentionally differ between environments
  # (for example, staging OAuth is fail-closed).  The frozen binding manifest
  # verifies those exact differences; here we require Wrangler to successfully
  # materialize a non-empty Env surface for both deployment configurations.
  if ! grep -q '^interface __BaseEnv_Env {' "$production_types" \
    || ! grep -q '^interface __BaseEnv_Env {' "$staging_types"; then
    echo "worker $name: missing generated production/staging Env surface" >&2
    exit 1
  fi
}

echo "==> active Worker lanes (parallel, fail-closed aggregation)"
ci_log_dir="$(mktemp -d "${TMPDIR:-/tmp}/quant-platform-ci.XXXXXX")"
trap 'rm -rf -- "$ci_log_dir"' EXIT
worker_pids=()
worker_names=()
for dir in "${WORKERS[@]}"; do
  name="$(basename "$dir")"
  worker_names+=("$name")
  (verify_worker "$dir") >"$ci_log_dir/$name.log" 2>&1 &
  worker_pids+=("$!")
done

worker_failed=0
for i in "${!worker_pids[@]}"; do
  name="${worker_names[$i]}"
  if ! wait "${worker_pids[$i]}"; then
    worker_failed=1
    echo "worker lane failed: $name" >&2
  fi
  cat "$ci_log_dir/$name.log"
done
if [[ "$worker_failed" -ne 0 ]]; then
  echo "one or more active Worker lanes failed" >&2
  exit 1
fi

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
