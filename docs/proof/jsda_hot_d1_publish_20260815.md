# JSDA hot tip → D1 publish (2026-08-15)

**Mass / READY / Phase7:** **NO-GO / OFF**  
**empty-raw ban:** held (no invent rows; copy of sealed local facts only)  
**Policy:** D1 = **hot tip only** · full history = local research DB / R2

## Problem

Audit (W20-G4/G5) documented:

| Plane | `jsda_repo_rates` | `jsda_tokyo_repo_rates` COMPLETE |
|-------|------------------:|----------------------------------|
| Local research sqlite | **30 303** | **COMPLETE** (receipt = 30 303) |
| D1 (before this wave) | **0** | **COMPLETE** (coverage projected) |

`tokyo_repo_rows=0` was **not data loss** — receipt-owned COMPLETE vs plane-local fact COUNT.

## Design decision (implemented)

| Plane | Content |
|-------|---------|
| Local + R2 | Full sealed history (SoT for research) |
| D1 | **Hot tip only** (`as_of_date >= 2026-07-01`, same cutoff as `storage_plane_status`) |
| COMPLETE | Still **receipt-owned** (not redefined by D1 fact count) |

Full D1 backfill of 30k+ repo / 700k+ OTC is **explicitly out of scope** (D1 size / hot-only architecture).

## Tooling

```bash
.venv/bin/python scripts/publish_jsda_hot_to_d1.py --dry-run
.venv/bin/python scripts/publish_jsda_hot_to_d1.py --apply-remote
```

Script path: `scripts/publish_jsda_hot_to_d1.py`

- `DELETE` cold rows on D1 (`as_of_date < hot_cutoff`)
- `INSERT OR REPLACE` hot rows from local DB
- Does not rewrite coverage / receipts / COMPLETE

## Result (this run)

| Metric | PRE | POST |
|--------|----:|-----:|
| D1 `jsda_repo_rates` COUNT | **0** | **252** |
| Hot cutoff | — | **2026-07-01** |
| Cold rows on D1 (`as_of_date < cutoff`) | — | **0** |
| Local full history | 30 303 | 30 303 (unchanged) |
| Dataset COMPLETE | COMPLETE | COMPLETE (unchanged) |

Remote probe:

```text
remote PRE tokyo_repo_rows=0
remote POST tokyo_repo_rows=252
ok=true hot_rows_exported=252
```

SQL artifact: `.glm-logs/jsda_hot_d1/jsda_repo_hot_2026-07-01.sql`

## Residual items closed / held

| Item | Status |
|------|--------|
| Source always-null fields | **DEFER** (documented; do not invent) |
| tip-only am / earnings_calendar | **DEFER** held |
| JSDA corp schema-superset empties | **DEFER** held |
| D1 JSDA **full** fact backfill | **NO-GO** by design |
| D1 JSDA **hot tip** fact | **DONE** this wave (repo rates) |
| Coverage DEFER D1–D10 | unchanged |
| Mass / READY / Phase7 | **NO-GO / OFF** |

## Honesty

- COMPLETE still means signed receipt + coverage, not “D1 has full history”.
- `storage_plane_status` honesty flags (`4fcef08`) remain valid when D1 is empty; after hot publish, divergence of kind `COMPLETE_WITHOUT_LOCAL_FACTS` should clear for tokyo_repo on D1 while `FACT_VS_COVERAGE_COUNT_MISMATCH` may appear (252 tip vs 30303 ledger) — expected and documented.
