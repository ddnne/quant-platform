# Phase 3.5 — Validation Matrix (coverage catalog)

This is the **canonical catalog** of Premium-core (23 datasets) data-quality
checks. Job-level pass/fail (`cf_platform.ingest_premium.validate`) remains
necessary but **not sufficient**.

Target: **Premium core only** (no minute / tick / TDnet addons).
Official start dates and retention: [J-Quants data-spec](https://jpx-jquants.com/en/spec/data-spec)
is authoritative; expected year span follows the contracted Premium window.

## Legend

| Code | Meaning |
|------|---------|
| **H** | History coverage (years / start date) |
| **G** | Time-series gaps |
| **U** | Universe / security coverage |
| **P** | PIT / quality |
| **X** | Cross-dataset consistency |

## Execution tiers

| Tier | When | Scope |
|------|------|--------|
| **daily** | every run / nightly | C1–C5, C8, C12, B2, B4, K3, X4 |
| **weekly** | weekly / monthly full | C6–C7, C9–C11, series-specific A–F, X1–X3, X5 |

Full matrix is always defined here even when only the daily tier runs.

---

## Common checks (all 23 datasets) — C1–C12

| ID | Item | Content |
|----|------|---------|
| C1 | Job exists | In required list + run record present |
| C2 | Last run outcome | pass / fail / partial retained |
| C3 | Row count | Not zero (unless series allows empty, e.g. non-trading day) |
| C4 | `event_time` min/max | Observed history endpoints |
| C5 | `available_at` min/max | Missing rate 0 (or explicit tolerance) |
| C6 | Lag vs official start | Years late vs data-spec start |
| C7 | Expected years fill rate | % of Premium-expected span covered |
| C8 | Freshness | Latest `event_time` within N trading days |
| C9 | Incremental continuity | New dates accumulate over last M runs |
| C10 | Idempotency | Re-fetch same key does not explode row counts |
| C11 | Raw present | R2 (or raw partition) exists per series |
| C12 | No addon leak | minute / trades / td_* not in required schedule |

---

## Series-specific checks

### A. Equities price / master

**`equities_master`**

| ID | Item |
|----|------|
| M1 | Issuer count ≳ full-list order (thousands), not dozens only |
| M2 | Multi-day snapshots (not a single frozen day) |
| M3 | Key codes present (e.g. 8697, 7203) |
| M4 | Listings / delistings observed over the window (not survivor-only fixed list) |

**`equities_bars_daily`**

| ID | Item |
|----|------|
| B1 | Year span (min–max date) near Premium expectation |
| B2 | Universe coverage: share of master issuers with ≥1 bar |
| B3 | Concentration: top-N issuers do not dominate all rows |
| B4 | Calendar gaps: market-wide missing trading days |
| B5 | Per-issuer missing rate on listed window (sample) |
| B6 | OHLC null rate, zero price, high < low anomaly rate |
| B7 | Adjustment field consistency |

**`equities_bars_daily_am`**

| ID | Item |
|----|------|
| A1 | If “recent only” by spec, score **recent** coverage not multi-decade history |
| A2 | Sample join vs full-day bars same date/code |
| A3 | Issuer count not pathologically small |

### B. Calendar / schedules

**`markets_calendar`**

| ID | Item |
|----|------|
| K1 | Year span |
| K2 | Holiday / session flag completeness |
| K3 | Market-wide bar gaps ⊆ non-trading days |

**`equities_earnings_calendar` / `fins_earnings_date`**

| ID | Item |
|----|------|
| E1 | Period coverage |
| E2 | “Recent only” schedules match spec |
| E3 | Sample major-code miss rate |

### C. Fundamentals

**`fins_summary` / `fins_details` / `fins_dividend`**

| ID | Item |
|----|------|
| F1 | Year span vs official start |
| F2 | Issuer coverage vs master (with allow-list for no-filers) |
| F3 | Period jumps (quarterly / annual holes) |
| F4 | Dividend record/pay date order anomalies |
| F5 | details ⊇ summary sample inclusion |

### D. Indices / derivatives

**`indices_bars_daily` / `indices_bars_daily_topix`**

| ID | Item |
|----|------|
| I1 | Year span |
| I2 | Required index continuity (gap days) |
| I3 | Not empty / not tiny |

**`derivatives_bars_daily_*`**

| ID | Item |
|----|------|
| D1 | Year span |
| D2 | Contract/month cardinality order-of-magnitude |
| D3 | Trading-day gaps |
| D4 | Sample post-expiry holes |

### E. Market stats

**`equities_investor_types` / `markets_margin_*` / `markets_short_*` / `markets_breakdown`**

| ID | Item |
|----|------|
| S1 | Year span per series start |
| S2 | Daily vs weekly cadence matches spec |
| S3 | Key cardinality not “a few rows only” |
| S4 | Freshness lag |

### F. EDINET via JQ

**`edinet_*`**

| ID | Item |
|----|------|
| N1 | Year span vs official start |
| N2 | Issuer coverage (hundreds order, not always a handful) |
| N3 | Filing date vs `available_at` order |
| N4 | Sample issuer time series present |

---

## Cross checks — X

| ID | Item |
|----|------|
| X1 | master issuer count vs issuers with ≥1 daily bar |
| X2 | bar date set ⊆ calendar trading days (explained) |
| X3 | PIT: fixed past `as_of` does not leak future rows |
| X4 | D1/SQLite row counts consistent with validation `rows_inserted` |
| X5 | After backfill, min(event_time) moves toward expected start |

---

## Scale

- Common C1–C12: ~23 × 12 ≈ 276  
- Series-specific A–F: ~50–80  
- Cross X: ~5–10  

→ **300+ matrix cells**. Implement all IDs as catalog entries; execute by tier.

## Status vs prior job validation

| View | Job validate | This matrix |
|------|--------------|-------------|
| Job success | ✓ | ✓ (C1–C2) |
| Years / start | ✗ | ✓ C6–C7 |
| Date gaps | ✗ | ✓ B4, K3, G |
| Issuer skew | ✗ | ✓ B2–B3, M1 |
| Cross series | ✗ | ✓ X1–X5 |

**Phase 3.5 “validation complete” requires this catalog implemented and at
least the daily tier auto-runnable.**

---

## Parallel execution policy

1. **23 endpoint collection/validation is path-parallel** (configurable concurrency, J-Quants Premium rate margin).
2. **Phase 3.5 (data) and Phase 4 (features/BT)** start independent work in parallel; only real-DB B0–B2 wait on a readable multi-issuer DB.
3. Independent checks within a path may run together.
4. Offline CI tests and live-DB runners develop in parallel.
5. On 429, retry **only that worker**; do not serialize the entire grid.
6. Serial only where there is a true dependency (e.g. cross-checks after path aggregates).

### Concurrency knobs

| Setting | Env / CLI | Default |
|---------|-----------|---------|
| Path workers | `QP_VAL_WORKERS` / `--workers` | 4 (safe Premium margin) |
| Max retries per path | `QP_VAL_RETRIES` | 3 |
| Retry backoff | exponential, jitter | starts 1s |

### Order-of-magnitude gates (shared 3.5 / 4)

| Series | Gate (approx) |
|--------|----------------|
| Master issuers | ≳ 3,000 (ideal ≳ 3.8k–4.2k) |
| Daily bars issuers | ≳ 3,000 with ≥1 bar |
| Bars on latest trading day | ≳ 3,000 rows |
| Trading days / year | ~240–245 |
| Bars / year (full market) | ~0.9M–1.0M |

Offline fixtures use scaled-down counts but the **same check IDs** and report `metrics` so live runs can enforce full gates.

---

## Live strict gates

When run in a live context (env `QP_LIVE=1`), the runner defaults to
`--strict-live-gates`. Live runs **must** enforce LIVE_GATES — there is no
soft path in production. The `--no-strict-live-gates` flag exists for
one-shot diagnostic runs only.

Strict mode promotes the following checks from informational metrics to
hard failures:

| ID(s) | Soft (offline) | Strict (live) |
|-------|----------------|----------------|
| **B0** (daily) | not emitted | one row per gate (`B0_master`, `B0_bars_issuers`, `B0_bars_latest_day`); fail if any gate missed (≥3k master, ≥3k bar issuers, ≥3k latest-day rows) |
| **C6 / C7** (weekly) | `warn` even on tiny spans | `fail` when fill-rate < 0.20 vs `EXPECTED_START` |
| **B1** (weekly) | `warn` when bars span < 1 year | `fail` when bars span < 1 year |
| **X1** (weekly) | `warn` when coverage < 0.5 | `fail` when coverage < 0.8 **and** master > 1,000 (real-sized universe) |

`b0_pass(db, strict=None)` (used by Phase 4 live smoke) treats
`QP_LIVE=1` as strict — pass `strict=False` explicitly for the soft
offline path.

### `EXPECTED_START` assumptions

The C6/C7 fill-rate baseline uses a per-dataset start date from the
J-Quants data-spec (https://jpx-jquants.com/en/spec/data-spec). Values
in `cf_platform/ingest_premium/coverage.EXPECTED_START` are
**conservative** (rounded toward the nearest recent month so live
expectations are forgiving) and are **assumptions, not contractual
truths** — update as the spec evolves.

---

## Validation honesty (P0-2)

The runner refuses to report a "soft pass" that hides a missing
implementation. Three behavior changes:

### C1 / C2 use real run logs when present

When the CF/D1 ``ingestion_validation`` table is mirrored to the local
SQLite DB, C1 and C2 mirror its per-dataset ``status`` exactly. When only
fact rows are available (no run log), C2 degrades to ``warn`` (not pass)
with ``reason_code="no_run_log"`` so a green offline report can never be
confused with a real per-job pass verdict.

### Weekly completion mode (`--require-implemented`)

The weekly tier defaults to completion mode: any ``skip`` with
``reason_code == "not_implemented"`` is treated as a failure. The daily
tier defaults to the soft path (tolerate stubs). Override with
``--require-implemented`` / ``--allow-not-implemented``. The
``reason_code == "needs_r2"`` skip (C11) is exempt — it represents an
intentional offline deferral, not a missing implementation.

### C9 / C10 approximated when validation history is present

When ``ingestion_validation`` has multiple per-dataset rows, C9 evaluates
incremental progress (latest run inserted > 0 or accumulated revisions)
and C10 evaluates idempotency (insert-only runs with zero revisions, or
revisions alongside inserts). Without that table both checks skip with
``reason_code="not_implemented"``. **C11** always skips offline with
``reason_code="needs_r2"`` — R2 raw partitions are simply not visible
from a SQLite mirror.

### Persisted report JSON

Every CLI run persists the full result set under
``data/reports/validation_YYYYMMDD_HHMMSS.json`` so an operator can
audit what the runner saw even after the DB is re-synced. The directory
is gitignored (``data/reports/*`` but keep ``.gitkeep``); use
``--no-persist-report`` to skip.
