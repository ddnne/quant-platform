#!/usr/bin/env bash
# Standalone CI lane helper. Run as a process, not `source` + `if ! function`.
# A parent conditional must not disable errexit inside Worker jobs.
set -euo pipefail

# Usage: ci_bounded_jobs.sh <max> <log_dir> <log_prefix> <fail_word> <runner> <item>...
# <runner> is an executable path or an exported bash function name.
# Each item runs in a new bash process with its own errexit.

if [[ "$#" -lt 5 ]]; then
  echo "ci_bounded_jobs.sh: usage: max log_dir log_prefix fail_word runner item..." >&2
  exit 1
fi

max_jobs="$1"
log_dir="$2"
prefix="$3"
fail_word="$4"
runner="$5"
shift 5

if [[ "$max_jobs" -lt 1 ]]; then
  echo "ci_bounded_jobs.sh: max jobs must be >= 1" >&2
  exit 1
fi

pending_pids=()
pending_names=()
failed=0

kill_pending_runners() {
  local pid
  if [[ "${#pending_pids[@]}" -gt 0 ]]; then
    for pid in "${pending_pids[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
  fi
}
trap kill_pending_runners EXIT

reap_batch() {
  local i name
  if [[ "${#pending_pids[@]}" -eq 0 ]]; then
    return 0
  fi
  for i in "${!pending_pids[@]}"; do
    name="${pending_names[$i]}"
    if ! wait "${pending_pids[$i]}"; then
      failed=1
      echo "${fail_word} failed: $name" >&2
    fi
    cat "${log_dir}/${prefix}${name}.log"
  done
  pending_pids=()
  pending_names=()
}

for item in "$@"; do
  name="$(basename "$item")"
  bash -c 'set -euo pipefail
runner=$1
item=$2
if [[ "$runner" == /* || "$runner" == ./* || "$runner" == ../* ]]; then
  exec "$runner" "$item"
fi
"$runner" "$item"
' bash "$runner" "$item" >"${log_dir}/${prefix}${name}.log" 2>&1 &
  pending_pids+=("$!")
  pending_names+=("$name")
  if [[ "${#pending_pids[@]}" -ge "$max_jobs" ]]; then
    reap_batch
  fi
done
reap_batch
trap - EXIT
exit "$failed"
