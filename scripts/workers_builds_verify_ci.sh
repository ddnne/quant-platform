#!/usr/bin/env bash
# Cloudflare Workers Builds bootstrap for the authoritative repository CI.
# The build image's asdf Python may be compiled without CPython's optional
# _sqlite3 module. Use the Ubuntu distribution interpreter only after proving
# its version and SQLite behavior, then hand authority to verify_ci.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

fail() {
  echo "workers_builds_verify_ci: $*" >&2
  exit 1
}

python_has_ci_runtime() {
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

[[ "${WORKERS_CI:-}" == "1" ]] || fail "WORKERS_CI=1 is required"
[[ "${SKIP_DEPENDENCY_INSTALL:-}" == "1" ]] || \
  fail "SKIP_DEPENDENCY_INSTALL=1 is required"

[[ -r /etc/os-release ]] || fail "/etc/os-release is required"
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]] || \
  fail "expected the documented Ubuntu 24.04 Workers Builds image"

system_py="/usr/bin/python3"
[[ -x "$system_py" ]] || fail "$system_py is required"
python_has_ci_runtime "$system_py" || \
  fail "$system_py must be Python 3.11+ with working stdlib sqlite3"

command -v pipx >/dev/null 2>&1 || fail "Cloudflare's preinstalled pipx is required"
pipx run --spec "virtualenv==21.7.4" virtualenv \
  --python "$system_py" \
  --clear \
  "$ROOT/.venv"

venv_py="$ROOT/.venv/bin/python"
[[ -x "$venv_py" ]] || fail "virtualenv did not create .venv/bin/python"
python_has_ci_runtime "$venv_py" || \
  fail "created .venv must preserve the Python and SQLite runtime contract"

exec bash "$ROOT/scripts/verify_ci.sh"
