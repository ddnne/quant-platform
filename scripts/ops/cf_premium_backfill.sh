#!/usr/bin/env bash
# DEPRECATED operational path — prefer contract-driven:
#   python scripts/ops/cf_premium_backfill.py
# This shell driver keeps hand-written recent windows only as a temporary
# companion while the planner-based driver is the long-history SoT.
# Drive historical backfill via Cloudflare ingestion-premium /v1/run.
# Does NOT call J-Quants from this host; CF holds the API key.
set -euo pipefail
PREMIUM="${PREMIUM_URL:-https://quant-platform-ingestion-premium.taku-haga.workers.dev}"
TOKEN_FILE="${INGESTION_RUN_TOKEN_FILE:-$HOME/.config/quant-platform/ingestion_run_token}"
TOKEN="$(cat "$TOKEN_FILE")"
LOG_DIR="${LOG_DIR:-.glm-logs/cf-backfill}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/run_$(date +%Y%m%d_%H%M%S).log"
STATE="$LOG_DIR/state.tsv"
SLEEP_SEC="${SLEEP_SEC:-8}"
MAX_TODAY_CHUNK_DAYS="${MAX_TODAY_CHUNK_DAYS:-7}"

log() { echo "[$(date +%Y-%m-%dT%H:%M:%S%z)] $*" | tee -a "$LOG"; }

run_one() {
  local dataset="$1" from="$2" to="$3"
  local url="${PREMIUM}/v1/run?dataset=${dataset}&from=${from}&to=${to}"
  log "START $dataset $from..$to"
  local body code
  body="$(curl -sS -w '\n%{http_code}' -X POST -H "X-Ingestion-Token: ${TOKEN}" "$url" || true)"
  code="$(echo "$body" | tail -n1)"
  body="$(echo "$body" | sed '$d')"
  echo "$body" >> "$LOG"
  if [[ "$code" != "200" ]]; then
    log "FAIL HTTP $code $dataset $from..$to"
    echo -e "${dataset}\t${from}\t${to}\tHTTP_${code}\t$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$STATE"
    return 1
  fi
  local status passed failed rows
  status="$(python3 -c "import sys,json; d=json.loads(sys.argv[1]); s=d.get('summary',{}); print(s.get('status','?'), s.get('passed',0), s.get('failed',0), s.get('rowsInserted',0))" "$body" 2>/dev/null || echo '? 0 0 0')"
  log "DONE $dataset $from..$to -> $status"
  echo -e "${dataset}\t${from}\t${to}\t${status// /$}\t$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$STATE"
  sleep "$SLEEP_SEC"
}

# month iterator: emit YYYY-MM-DD start/end pairs
months_between() {
  python3 - "$1" "$2" <<'PY'
import sys
from datetime import date
from calendar import monthrange
start=date.fromisoformat(sys.argv[1]); end=date.fromisoformat(sys.argv[2])
y,m=start.year,start.month
while True:
    first=date(y,m,1)
    last=date(y,m,monthrange(y,m)[1])
    a=max(first,start); b=min(last,end)
    if a<=b: print(f"{a.isoformat()} {b.isoformat()}")
    if (y,m)==(end.year,end.month): break
    m+=1
    if m>12: m=1; y+=1
PY
}

days_chunks() {
  python3 - "$1" "$2" "$3" <<'PY'
import sys
from datetime import date, timedelta
start=date.fromisoformat(sys.argv[1]); end=date.fromisoformat(sys.argv[2]); n=int(sys.argv[3])
cur=start
while cur<=end:
    chunk_end=min(cur+timedelta(days=n-1), end)
    print(f"{cur.isoformat()} {chunk_end.isoformat()}")
    cur=chunk_end+timedelta(days=1)
PY
}

# Phase A: low-volume range datasets (yearly/monthly ok as one range query)
log "=== Phase A: range datasets ==="
# markets_calendar full history
run_one markets_calendar 2008-01-01 2026-08-10 || true
run_one indices_bars_daily_topix 2008-01-01 2026-08-10 || true
run_one equities_investor_types 2013-01-04 2026-08-10 || true
run_one equities_earnings_calendar 2010-01-04 2026-08-10 || true

# Phase B: recent window first (last 90 days) for all today-mode critical sets
log "=== Phase B: recent 90d today-mode (weekly chunks) ==="
TODAY_DATASETS=(
  equities_master
  equities_bars_daily
  equities_bars_daily_am
  fins_summary
  fins_dividend
  fins_earnings_date
  indices_bars_daily
  markets_margin_interest
  markets_margin_alert
  markets_short_ratio
  markets_short_sale_report
  markets_breakdown
  edinet_major_shareholders
  edinet_cross_shareholdings
  edinet_large_volume_shareholders
)
# recent window
RECENT_FROM="$(python3 -c 'from datetime import date,timedelta; print((date.today()-timedelta(days=90)).isoformat())')"
RECENT_TO="$(python3 -c 'from datetime import date,timedelta; print((date.today()-timedelta(days=1)).isoformat())')"
for ds in "${TODAY_DATASETS[@]}"; do
  while read -r f t; do
    run_one "$ds" "$f" "$t" || true
  done < <(days_chunks "$RECENT_FROM" "$RECENT_TO" "$MAX_TODAY_CHUNK_DAYS")
done

# Phase C: deeper history for bars/master — month by month from coverage starts
log "=== Phase C: deep history month chunks (bars + master + key markets) ==="
DEEP=(
  "equities_master 2000-07-13"
  "equities_bars_daily 2004-01-05"
  "equities_bars_daily_am 2024-01-04"
  "fins_summary 2008-01-08"
  "indices_bars_daily 2008-01-01"
  "markets_breakdown 2013-01-04"
  "markets_margin_interest 2013-01-04"
)
# Only go deep up to before recent window to avoid redoing phase B
DEEP_END="$(python3 -c "from datetime import date,timedelta; print((date.fromisoformat('$RECENT_FROM')-timedelta(days=1)).isoformat())")"
for item in "${DEEP[@]}"; do
  ds="${item%% *}"; start="${item##* }"
  while read -r f t; do
    run_one "$ds" "$f" "$t" || true
  done < <(months_between "$start" "$DEEP_END")
done

# Phase D: derivatives (heavier) — recent year then deeper months
log "=== Phase D: derivatives ==="
for ds in derivatives_bars_daily_futures derivatives_bars_daily_options_225 derivatives_bars_daily_options; do
  while read -r f t; do
    run_one "$ds" "$f" "$t" || true
  done < <(days_chunks 2024-01-04 "$RECENT_TO" 3)
done

log "=== CF backfill driver finished ==="
